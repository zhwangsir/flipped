"""双模型并行验证监督（M14 / D19）。

用户原话："两个模型需要同时进行使用，一个用来跑代码的时候另外一个用来验证监督"

本模块让 GLM 在 worker(Kimi) 产出代码后，**与确定性 verifier 并行**对产物做语义
监督验证——不是事后 overseer 的方向判断，而是对**代码产物本身**的语义检查。

设计：
- `make_parallel_verifier(base_verifier, glm_alias)` 返回 verifier_fn
- 用 ThreadPoolExecutor 并行跑：
  * base_verifier（确定性：verify_cmd + design-lint + a11y）
  * GLM 语义验证（读产物文件，评判质量/设计/结构/a11y hints）
- 合并：deterministic_ok AND glm_severity != "blocker"
- 优雅降级：GLM 不可用/超时 → fail-open（只返回确定性结果，不阻塞）

跨模型族验证（Kimi 产代码 → GLM 验证）避免同模型自偏（D15）。
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from driving.model_router import resolve_model_config


# ---------- 数据结构 ----------

@dataclass
class SemanticVerdict:
    """GLM 语义验证的结构化判定。"""
    severity: str  # "ok" / "warning" / "blocker"
    issues: list[str] = field(default_factory=list)
    rationale: str = ""
    checked: bool = False  # 是否真的执行了 GLM 调用
    skip_reason: str = ""  # 未执行的原因

    @property
    def is_blocker(self) -> bool:
        return self.severity == "blocker"

    def summary(self) -> str:
        if not self.checked:
            return f"⚠️ glm_semantic 跳过 ({self.skip_reason})"
        if self.severity == "ok":
            return "✅ glm_semantic 通过"
        prefix = "❌" if self.is_blocker else "⚠️"
        issues_str = "; ".join(self.issues[:3]) if self.issues else "无"
        return f"{prefix} glm_semantic {self.severity} (issues={len(self.issues)}): {issues_str}"


# ---------- 产物读取 ----------

# UI 产物文件优先级
_ARTIFACT_PRIORITY = (
    "index.html", "index.htm",
    "App.tsx", "App.jsx",
    "main.tsx", "main.jsx",
)

# 单文件读取上限（防止 prompt 过长触发 GLM reasoning 循环）
_MAX_FILE_BYTES = 4000
_MAX_TOTAL_BYTES = 6000


def _read_artifacts(cwd: str | Path) -> str:
    """读取 cwd 下的 UI 产物文件，拼接成 GLM 可读的文本。

    策略：优先 index.html，否则扫 *.html/*.tsx/.jsx。每文件截断到 _MAX_FILE_BYTES，
    总计截断到 _MAX_TOTAL_BYTES。
    """
    cwd = Path(cwd)
    chunks: list[str] = []
    total = 0

    # 1. 优先入口文件
    for name in _ARTIFACT_PRIORITY:
        p = cwd / name
        if p.exists() and p.is_file():
            content = p.read_text(encoding="utf-8", errors="ignore")
            if len(content) > _MAX_FILE_BYTES:
                content = content[:_MAX_FILE_BYTES] + "\n... (truncated)"
            chunks.append(f"=== {name} ===\n{content}")
            total += len(content)
            if total >= _MAX_TOTAL_BYTES:
                break

    # 2. 兜底：扫其他 html/tsx/jsx
    if total < _MAX_TOTAL_BYTES:
        for pattern in ("*.html", "*.htm", "*.tsx", "*.jsx"):
            for p in sorted(cwd.glob(pattern)):
                if p.name in _ARTIFACT_PRIORITY:
                    continue
                if total >= _MAX_TOTAL_BYTES:
                    break
                content = p.read_text(encoding="utf-8", errors="ignore")
                if len(content) > _MAX_FILE_BYTES:
                    content = content[:_MAX_FILE_BYTES] + "\n... (truncated)"
                chunks.append(f"=== {p.name} ===\n{content}")
                total += len(content)

    return "\n\n".join(chunks) if chunks else ""


# ---------- GLM 语义验证调用 ----------

_SEMANTIC_PROMPT_TEMPLATE = """你是 UI 代码监督验证者。下面是 worker(Kimi) 刚产出的代码产物。
请评判以下维度，输出 JSON：

1. design_consistency: 设计系统是否一致（颜色/字体/间距是否符合规范）
2. structure: HTML/组件结构是否完整（必要 section/语义标签）
3. a11y_hints: 无障碍明显问题（缺 alt/lang/label/对比度）
4. potential_bugs: 潜在 bug（未闭合标签/JS 错误/资源 404）
5. severity: "ok" | "warning" | "blocker"
   - ok: 无明显问题
   - warning: 有小问题但不阻断验收
   - blocker: 严重缺陷（结构缺失/语法错误/设计系统完全偏离）
6. issues: 问题列表（每条 ≤80 字）
7. rationale: 一句话总结（≤100 字）

严格：只 blocker 级才算失败。小瑕疵算 warning。产物已通过确定性 verify_cmd 校验，
你只需补充确定性检查发现不了的语义/设计/结构问题。

产物内容：
{artifacts}

输出 JSON（只输出 JSON，不要其他内容）：
"""


def _call_glm_semantic(
    base_url: str,
    model: str,
    api_key: str,
    artifacts: str,
    timeout: float = 120.0,
) -> SemanticVerdict:
    """直调 GLM /v1/chat/completions 做语义验证。

    复用 orchestrator._direct_glm_tool_call 的风格：
    - enable_thinking=false（避免 reasoning tokens 占满 max_tokens）
    - max_tokens=800（紧凑 JSON 足够）
    - trust_env=False（绕过本机代理劫持，D5）
    """
    import httpx

    if not artifacts.strip():
        return SemanticVerdict(severity="ok", checked=False, skip_reason="无产物文件可读")

    prompt = _SEMANTIC_PROMPT_TEMPLATE.format(artifacts=artifacts)
    # 限制 prompt 长度（防 reasoning 循环）
    if len(prompt) > 8000:
        prompt = prompt[:8000] + "\n\n输出 JSON："

    try:
        r = httpx.post(
            f"{str(base_url).rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "enable_thinking": False,
                "max_tokens": int(os.environ.get("FLIPPED_PARALLEL_GLM_MAX_TOKENS", "800")),
                "temperature": 0,
            },
            timeout=httpx.Timeout(timeout, connect=10.0),
            trust_env=False,
        )
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        content = msg.get("content", "") or ""
        if not content:
            finish = choice.get("finish_reason", "")
            return SemanticVerdict(
                severity="ok", checked=False,
                skip_reason=f"GLM 空响应 finish={finish}",
            )
        return _parse_semantic_json(content)
    except Exception as e:  # noqa: BLE001 — fail-open
        return SemanticVerdict(
            severity="ok", checked=False,
            skip_reason=f"GLM 调用失败: {type(e).__name__}: {str(e)[:120]}",
        )


# JSON 候选提取（应对 GLM 偶发把 JSON 包在 markdown code block 或附加文字里）
_JSON_CANDIDATE_RE = re.compile(r"\{[\s\S]*\}")


def _parse_semantic_json(content: str) -> SemanticVerdict:
    """从 GLM content 解析 SemanticVerdict。

    GLM 可能输出：
    1. 纯 JSON
    2. ```json\n{...}\n```
    3. JSON + 附加文字
    """
    # 优先：直接 json.loads
    try:
        data = json.loads(content)
        return _coerce_verdict(data)
    except Exception:
        pass

    # 兜底：贪婪匹配 {...}
    m = _JSON_CANDIDATE_RE.search(content)
    if m:
        # 尝试截断到最后一个合法 }
        cand = m.group(0)
        for i in range(len(cand) - 1, -1, -1):
            if cand[i] == "}":
                tail = cand[i + 1:].strip().strip("`").strip()
                if not tail or tail.startswith("```"):
                    try:
                        return _coerce_verdict(json.loads(cand[:i + 1]))
                    except Exception:
                        pass
        try:
            return _coerce_verdict(json.loads(cand))
        except Exception:
            pass

    # 全部失败 → fail-open（不当 blocker）
    return SemanticVerdict(
        severity="ok", checked=False,
        skip_reason=f"GLM 输出无法解析为 JSON: {content[:120]}",
    )


def _coerce_verdict(data: dict) -> SemanticVerdict:
    """把 dict 强转成 SemanticVerdict，做类型修复。"""
    if not isinstance(data, dict):
        return SemanticVerdict(severity="ok", checked=False, skip_reason="GLM 输出非 object")

    severity = str(data.get("severity", "ok")).strip().lower()
    if severity not in ("ok", "warning", "blocker"):
        severity = "ok"  # 未知值 fail-open

    issues_raw = data.get("issues", [])
    if isinstance(issues_raw, str):
        issues = [issues_raw] if issues_raw else []
    elif isinstance(issues_raw, list):
        issues = [str(i)[:80] for i in issues_raw if i]
    else:
        issues = []

    rationale = str(data.get("rationale", ""))[:200]

    return SemanticVerdict(
        severity=severity,
        issues=issues,
        rationale=rationale,
        checked=True,
    )


# ---------- verifier 工厂 ----------

VerifierFn = Callable[[list[str], str], "tuple[bool, str]"]


def make_glm_semantic_verifier(glm_alias: str = "architect", timeout: float = 120.0):
    """构造 GLM 语义验证器。

    返回 (cmd_list, cwd) -> SemanticVerdict。
    不依赖 cmd_list（GLM 只看产物文件）。
    """

    def _verify(cmd_list: list[str], cwd: str) -> SemanticVerdict:
        base_url, model = resolve_model_config(glm_alias)
        api_key = os.environ.get("EXO_API_KEY") or os.environ.get("LITELLM_MASTER_KEY", "dummy")
        artifacts = _read_artifacts(cwd)
        return _call_glm_semantic(base_url, model, api_key, artifacts, timeout=timeout)

    return _verify


def make_parallel_verifier(
    base_verifier: VerifierFn,
    glm_alias: str = "architect",
    glm_timeout: float = 120.0,
    max_workers: int = 2,
) -> VerifierFn:
    """构造双模型并行验证器。

    worker(Kimi) 产出后，并行跑：
    - base_verifier（确定性：verify_cmd + design-lint + a11y）
    - GLM 语义验证（读产物，跨模型族监督）

    合并规则：
    - deterministic fail → fail（带确定性 msg）
    - deterministic ok + GLM blocker → fail（带 GLM issues，让 worker 知道修什么）
    - deterministic ok + GLM ok/warning/skip → ok
    - GLM 超时/异常 → fail-open（不阻塞，只返回确定性结果）

    用法：
        verifier = make_parallel_verifier(combined_verifier_with_a11y(base, style))
        graph = build_orchestrator(verifier=verifier, ...)
    """
    glm_verifier = make_glm_semantic_verifier(glm_alias=glm_alias, timeout=glm_timeout)

    def _verify(cmd_list: list[str], cwd: str) -> "tuple[bool, str]":
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            det_future = pool.submit(base_verifier, cmd_list, cwd)
            glm_future = pool.submit(glm_verifier, cmd_list, cwd)

            # 等确定性结果（必须有）
            try:
                det_ok, det_msg = det_future.result()
            except Exception as e:  # noqa: BLE001
                det_ok, det_msg = False, f"deterministic verifier crashed: {type(e).__name__}: {e}"

            # 等 GLM 结果（带超时降级）
            try:
                glm_verdict: SemanticVerdict = glm_future.result(timeout=glm_timeout + 10)
            except FuturesTimeoutError:
                glm_verdict = SemanticVerdict(severity="ok", checked=False, skip_reason="GLM 超时")
            except Exception as e:  # noqa: BLE001
                glm_verdict = SemanticVerdict(
                    severity="ok", checked=False,
                    skip_reason=f"GLM verifier crashed: {type(e).__name__}: {str(e)[:120]}",
                )

        # 合并
        if not det_ok:
            return False, f"verify: {det_msg} | glm: {glm_verdict.summary()}"

        if glm_verdict.is_blocker:
            issues_str = "; ".join(glm_verdict.issues[:3]) if glm_verdict.issues else "无具体 issues"
            return False, f"glm_blocker: {issues_str} | rationale: {glm_verdict.rationale} | det: {det_msg}"

        # ok 或 warning 都通过
        return True, f"{det_msg}; {glm_verdict.summary()}"

    return _verify
