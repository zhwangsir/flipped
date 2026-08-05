"""M183 Worker 规则注入系统（纯逻辑零 FastAPI）。

orchestrator（local_worker 注入 / verify 节点效果统计）与 api/main 均 import 本模块。

- WorkerRule：规则模型（text strip 1..500；注入防护 blocklist；priority 0..100）
- WorkerRuleStore：JSON 持久化 + 版本史快照 + 回滚；tmp+os.replace 原子写；坏文件回退空
- build_worker_rules_text：渲染注入文本（enabled+scope 过滤、priority desc → id asc、
  字符预算整条丢弃 + "…(略N条)" 尾注）
- WorkerRuleStats：applied/outcome 统计（规则效果 = 降低失败迭代数）
- AUTO_RULE_TEMPLATES + generate_auto_rules：失败模式 → 规则候选（去重、限量）
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# 注入防护 blocklist（case-insensitive 子串匹配）
_BLOCKLIST: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard all",
    "忽略之前的指令",
    "忽略以上指令",
    "忽略先前",
)

_HISTORY_CAP = 20

# M185.1：chat/plan 通路注入 scope="all" 规则时的 system 段头
WORKER_RULES_CHAT_HEADER = "以下是全局工作规则（必须遵守）："

# M185.2：stats 语义显式化（snapshot 顶层携带，前端面板展示）
STATS_SEMANTICS = (
    "applied=规则注入次数；success/failure=verify 通过/失败次数"
    "（中间迭代失败记 failure）；success_rate=success/(success+failure)，"
    "规则效果=降低失败迭代数，非端到端任务成功率直接度量"
)


class WorkerRule(BaseModel):
    id: str
    text: str
    scope: Literal["worker", "all"] = "worker"
    source: Literal["manual", "auto"] = "manual"
    enabled: bool = True
    priority: int = Field(default=50, ge=0, le=100)
    created_at: float = Field(default_factory=time.time)

    @field_validator("text")
    @classmethod
    def _check_text(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 500):
            raise ValueError("text strip 后长度须为 1..500")
        low = v.lower()
        for bad in _BLOCKLIST:
            if bad.lower() in low:
                raise ValueError(f"text 命中注入防护 blocklist: {bad}")
        return v


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class WorkerRuleStore:
    """规则持久化：{"version": int, "rules": [...], "history": [快照...]}。

    每次变更（add/update/delete/set_enabled/rollback）bump version 并追加 history
    快照（变更后的 rules 序列化），history 上限 20 条。坏文件/缺字段 → 空 store(v0)。
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._version = 0
        self._rules: list[WorkerRule] = []
        self._history: list[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._version = int(data["version"])
            self._rules = [WorkerRule(**r) for r in data["rules"]]
            self._history = list(data["history"])
        except Exception:
            self._version, self._rules, self._history = 0, [], []

    def _save(self) -> None:
        _atomic_write_json(self._path, {
            "version": self._version,
            "rules": [r.model_dump() for r in self._rules],
            "history": self._history,
        })

    def _bump(self, action: str, detail: str) -> None:
        self._version += 1
        self._history.append({
            "version": self._version,
            "ts": time.time(),
            "action": action,
            "detail": detail,
            "rules": [r.model_dump() for r in self._rules],
        })
        self._history = self._history[-_HISTORY_CAP:]
        self._save()

    def list(self) -> list[WorkerRule]:
        return list(self._rules)

    def add(self, text: str, *, scope: str = "worker", source: str = "manual",
            priority: int | None = None) -> WorkerRule:
        if priority is None:
            priority = 10 if source == "auto" else 50
        existing_ids = {r.id for r in self._rules}
        rid = ""
        for _ in range(100):  # id 碰撞重试
            rid = "wr-" + secrets.token_hex(4)
            if rid not in existing_ids:
                break
        else:
            raise RuntimeError("worker rule id 碰撞重试超限")
        rule = WorkerRule(id=rid, text=text, scope=scope, source=source, priority=priority)
        self._rules.append(rule)
        self._bump("add", f"add {rid}")
        return rule

    def update(self, rule_id: str, *, text: str | None = None,
               priority: int | None = None, scope: str | None = None) -> WorkerRule | None:
        for i, r in enumerate(self._rules):
            if r.id == rule_id:
                data = r.model_dump()
                if text is not None:
                    data["text"] = text
                if priority is not None:
                    data["priority"] = priority
                if scope is not None:
                    data["scope"] = scope
                rule = WorkerRule(**data)  # 重走校验（text/priority/scope）
                self._rules[i] = rule
                self._bump("update", f"update {rule_id}")
                return rule
        return None

    def delete(self, rule_id: str) -> bool:
        for i, r in enumerate(self._rules):
            if r.id == rule_id:
                del self._rules[i]
                self._bump("delete", f"delete {rule_id}")
                return True
        return False

    def set_enabled(self, rule_id: str, enabled: bool) -> WorkerRule | None:
        for i, r in enumerate(self._rules):
            if r.id == rule_id:
                rule = r.model_copy(update={"enabled": bool(enabled)})
                self._rules[i] = rule
                self._bump("set_enabled", f"set_enabled {rule_id} {bool(enabled)}")
                return rule
        return None

    @property
    def version(self) -> int:
        return self._version

    def versions(self) -> list[dict]:
        """history 元信息（version/ts/action/detail/rule_count，不含快照全文）。"""
        return [{
            "version": h["version"],
            "ts": h["ts"],
            "action": h["action"],
            "detail": h["detail"],
            "rule_count": len(h["rules"]),
        } for h in self._history]

    def rollback(self, version: int) -> bool:
        """恢复指定 version 的 rules 快照；自身亦 bump version（action="rollback"）。"""
        for h in self._history:
            if h["version"] == version:
                self._rules = [WorkerRule(**r) for r in h["rules"]]
                self._bump("rollback", f"rollback to v{version}")
                return True
        return False


def build_worker_rules_text(rules: list[WorkerRule], *,
                            max_chars: int = 300,
                            scopes: tuple[str, ...] = ("worker", "all")
                            ) -> tuple[str, list[str]]:
    """渲染注入文本：enabled 且 scope∈scopes；priority desc → id asc。

    scopes 缺省 ("worker","all") = M183 现状（worker 通路）；chat/plan 通路传
    ("all",) 只注入全域规则（worker-only 工程约束不进对话）。
    逐条 "- {text}"，累计超 max_chars 即停（当前条整条不装）；尾部有丢弃则追加
    "…(略N条)"（此行自身需在预算内，装不下则直接截掉）。空集 → ("", [])。
    """
    eligible = [r for r in rules if r.enabled and r.scope in scopes]
    eligible.sort(key=lambda r: (-r.priority, r.id))

    lines: list[str] = []
    applied: list[str] = []
    used = 0
    dropped = 0
    for r in eligible:
        line = f"- {r.text}"
        cost = len(line) if not lines else len(line) + 1  # +1 为 \n
        if used + cost > max_chars:
            dropped = len(eligible) - len(applied)
            break
        lines.append(line)
        applied.append(r.id)
        used += cost
    if dropped:
        tail = f"…(略{dropped}条)"
        cost = len(tail) if not lines else len(tail) + 1
        if used + cost <= max_chars:
            lines.append(tail)
    return "\n".join(lines), applied


class WorkerRuleStats:
    """规则效果统计：{"stats": {id: {applied,success,failure}}, "total_runs": n}。

    applied 按注入次计数（record_applied），outcome 按 verify 次计数
    （record_outcome：total_runs+1，对每个 id 记 success/failure）。坏文件回退空。
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._stats: dict[str, dict] = {}
        self._total_runs = 0
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._stats = {
                str(k): {"applied": int(v["applied"]),
                         "success": int(v["success"]),
                         "failure": int(v["failure"])}
                for k, v in data["stats"].items()
            }
            self._total_runs = int(data["total_runs"])
        except Exception:
            self._stats, self._total_runs = {}, 0

    def _save(self) -> None:
        _atomic_write_json(self._path, {"stats": self._stats, "total_runs": self._total_runs})

    def _entry(self, rule_id: str) -> dict:
        return self._stats.setdefault(rule_id, {"applied": 0, "success": 0, "failure": 0})

    def record_applied(self, ids: list[str]) -> None:
        for rid in ids:
            self._entry(rid)["applied"] += 1
        self._save()

    def record_outcome(self, ids: list[str], success: bool) -> None:
        self._total_runs += 1
        key = "success" if success else "failure"
        for rid in ids:
            self._entry(rid)[key] += 1
        self._save()

    def snapshot(self) -> dict:
        """快照：stats 每条派生 success_rate（不落盘），顶层带 semantics 说明。

        success_rate = success/(success+failure)；零 outcome（无 verify 记录）→ None。
        """
        stats: dict[str, dict] = {}
        for k, v in self._stats.items():
            entry = dict(v)
            outcomes = v["success"] + v["failure"]
            entry["success_rate"] = (
                v["success"] / outcomes if outcomes > 0 else None)
            stats[k] = entry
        return {
            "stats": stats,
            "total_runs": self._total_runs,
            "semantics": STATS_SEMANTICS,
        }


AUTO_RULE_TEMPLATES: list[tuple[str, str]] = [
    (r"unused variable|未使用", "声明变量前确认会被使用，未用变量直接删除"),
    (r"verify_cmd 失败|verification failed", "输出代码前先自检语法与依赖导入完整性"),
    (r"timeout|超时", "避免生成超长文件，单文件控制在 300 行内"),
    (r"import.*not found|ModuleNotFound", "只使用项目已声明的依赖，不引入新包"),
    (r"diff|回归", "修改保持原有设计风格、配色与布局不变"),
    (r"test.*fail|测试失败", "改动后必须自跑相关测试确认通过再交付"),
    (r"json|parse|解析", "结构化输出严格使用合法 JSON，不带多余文本"),
]


def generate_auto_rules(failure_texts: list[str], existing: list[WorkerRule], *,
                        max_rules: int = 3) -> list[str]:
    """失败文本 → 规则候选：按序匹配模板（同模板只产一次），对 existing 文本 +
    本次候选去重（strip 后相等即重），返回 ≤max_rules 条候选文本。"""
    seen = {r.text.strip() for r in existing}
    candidates: list[str] = []
    used_templates: set[int] = set()
    for ft in failure_texts or []:
        if not ft:
            continue
        for ti, (pattern, rule_text) in enumerate(AUTO_RULE_TEMPLATES):
            if ti in used_templates:
                continue
            if re.search(pattern, ft, re.IGNORECASE):
                used_templates.add(ti)
                key = rule_text.strip()
                if key not in seen:
                    seen.add(key)
                    candidates.append(rule_text)
    return candidates[:max_rules]


# ---------- M190.2 · LLM 兜底生成（消化 L-M183-2） ----------

_LLM_RULE_MAX_LEN = 200

_LLM_PROMPT = (
    "你是软件工程导师。根据下列失败文本，总结最多 {max_rules} 条可执行的编码工作规则"
    "（中文，每条一句祈使句，针对根因可落地，不重复既有规则）。"
    "只输出 JSON 字符串数组，不要输出任何其他文字。\n\n"
    "失败文本：\n{failures}\n\n既有规则（不要重复）：\n{existing}"
)


def _llm_complete(prompt: str, *, timeout: float = 30.0) -> str:
    """POST {FLIPPED_MODEL_BASE_URL}/chat/completions 非流式，返回 content 文本。

    模块级 seam：测试 monkeypatch 本函数即切断真实 HTTP。
    """
    base = os.environ.get("FLIPPED_MODEL_BASE_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("FLIPPED_MODEL_BASE_URL not set")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({
            "model": os.environ.get("FLIPPED_RULES_LLM_MODEL", "default"),
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _parse_rules_json(content: str) -> list:
    """剥离 ```json 围栏后 json.loads；失败则截取首个 [...] 块兜底；再失败 → []。"""
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                return []
        return []


def generate_auto_rules_llm(failure_texts: list[str], existing: list[WorkerRule], *,
                            max_rules: int = 3) -> list[str]:
    """固定模板未命中时的 LLM 兜底：失败文本 → LLM → ≤max_rules 条规则候选。

    - FLIPPED_RULES_LLM=0 或 failure_texts 为空 → []（不发起调用）。
    - 解析 content 为 JSON array of str（剥离围栏）；非字符串项过滤。
    - strip 去重（existing + 候选内）；每条 ≤200 字符截断。
    - 任何异常 → []（fail-open，绝不让兜底拖垮 auto 通路）。
    """
    if os.environ.get("FLIPPED_RULES_LLM", "1") == "0":
        return []
    texts = [t.strip() for t in (failure_texts or []) if t and t.strip()]
    if not texts:
        return []
    try:
        prompt = _LLM_PROMPT.format(
            max_rules=max_rules,
            failures="\n".join(f"- {t}" for t in texts[:20]),
            existing="\n".join(f"- {r.text}" for r in existing) or "（无）",
        )
        items = _parse_rules_json(_llm_complete(prompt))
        if not isinstance(items, list):
            return []
        seen = {r.text.strip() for r in existing}
        out: list[str] = []
        for it in items:
            if not isinstance(it, str):
                continue
            t = it.strip()[:_LLM_RULE_MAX_LEN]
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= max_rules:
                break
        return out
    except Exception:
        return []
