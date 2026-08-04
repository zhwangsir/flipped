"""M179.1 · AI 代码评审（B 队后端）：review.py 纯逻辑 + POST /project/review。

- build_review_prompt：评审指令 + 逐文件 diff 段（fence 包裹防注入）；
  untracked 仅列路径+行数；超 12k 预算按文件逆序截断并注记「已截断 N 个文件」。
- parse_review_reply：剥 fence 找首个 JSON 数组 / {"findings": [...]}，
  逐项规范化（缺 path 跳过、severity 非法→medium、line 非法→None），
  完全无 JSON → ReviewParseError。
- 端点：空 diff 短路不调 LLM；解析失败/LLM 异常 → 502；
  FLIPPED_AI_REVIEW=0 → 404；无项目 → 400。

测试风格沿用 test_m177_review.py：TestClient + tmp_path 真 git 仓库
（无 git → 全模块 skip）；LLM 一律 monkeypatch fake，不烧真模型。
"""
from __future__ import annotations

import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from api.review import (
    REVIEW_PROMPT_BUDGET,
    ReviewParseError,
    build_review_prompt,
    parse_review_reply,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git 不可用")


def _git(root, *args):
    subprocess.run(["git", *args], cwd=str(root), check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator，返回 TestClient（同 test_m177_review.py）。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from api.main import app
    return TestClient(app)


@pytest.fixture()
def repo(tmp_path):
    """tmp_path 下真 git 仓库（含一个 tracked 文件）并设为活动项目；测后清理。"""
    from api import project_state as ps
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "tracked.txt").write_text("v1\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    ps.set_active(root)
    yield root
    ps.clear_active()


@pytest.fixture()
def fake_llm(monkeypatch):
    """fake _llm_chat + resolve_worker_model_config；calls 列表记录调用。"""
    calls: list[dict] = []
    box = {"reply": "[]", "exc": None}

    async def _fake_chat(base_url, model, system, user, timeout=120.0):
        calls.append({"base_url": base_url, "model": model,
                      "system": system, "user": user})
        if box["exc"] is not None:
            raise box["exc"]
        return box["reply"], None

    monkeypatch.setattr("api.main._llm_chat", _fake_chat)
    monkeypatch.setattr(
        "driving.model_router.resolve_worker_model_config",
        lambda alias="coder": ("http://fake-llm", f"fake-{alias}"),
    )
    box["calls"] = calls
    return box


def _review(client, **kw):
    return client.post("/api/v1/project/review", json=kw or {})


# ====================================================================
# 1 · build_review_prompt
# ====================================================================

def test_prompt_instruction_requires_json_only():
    """评审指令明确「只输出 JSON」（注入防护的一半）。"""
    prompt = build_review_prompt([{"path": "a.py", "added": 1, "removed": 0,
                                   "lines": [{"type": "add", "text": "x=1"}]}])
    assert "只输出 JSON" in prompt
    assert "severity" in prompt and "suggestion" in prompt


def test_prompt_diff_body_wrapped_in_fence():
    """tracked 文件 diff 内容包在 ```diff fence 内（注入防护的另一半）。"""
    prompt = build_review_prompt([{
        "path": "a.py", "added": 1, "removed": 1,
        "lines": [{"type": "del", "text": "old"}, {"type": "add", "text": "new"}],
    }])
    assert "```diff\n" in prompt
    assert "old\nnew" in prompt
    assert prompt.count("```") >= 2  # 开闭合围栏都在


def test_prompt_untracked_lists_path_and_count_only():
    """untracked 文件无行内容：仅列路径 + added 行数，不出 fence。"""
    prompt = build_review_prompt([{
        "path": "new.py", "added": 5, "removed": 0, "lines": [], "untracked": True,
    }])
    assert "new.py" in prompt
    assert "5" in prompt
    assert "```diff" not in prompt, "untracked 文件绝不出 fence 行内容"


def test_prompt_empty_files():
    """空 files 列表 → 仍是指令完整、可发送的 prompt。"""
    prompt = build_review_prompt([])
    assert "只输出 JSON" in prompt
    assert "已截断" not in prompt


def test_prompt_truncation_drops_tail_files():
    """超预算按文件逆序丢弃：前部文件完整保留，尾部注记「已截断 N 个文件」。"""
    big_lines = [{"type": "add", "text": "x" * 200} for _ in range(80)]  # ~16k chars
    files = [
        {"path": "keep.py", "added": 1, "removed": 0,
         "lines": [{"type": "add", "text": "small"}]},
        {"path": "drop1.py", "added": len(big_lines), "removed": 0, "lines": big_lines},
        {"path": "drop2.py", "added": 1, "removed": 0,
         "lines": [{"type": "add", "text": "y"}]},
    ]
    prompt = build_review_prompt(files)
    assert "keep.py" in prompt, "前部文件必须完整保留"
    assert "drop1.py" not in prompt and "drop2.py" not in prompt
    assert "已截断 2 个文件" in prompt
    assert len(prompt) <= REVIEW_PROMPT_BUDGET + 16


# ====================================================================
# 2 · parse_review_reply
# ====================================================================

def test_parse_json_fence():
    """```json fence 包裹的回复正常解析。"""
    text = '```json\n[{"path": "a.py", "line": 3, "severity": "high", "message": "空指针", "suggestion": "加判空"}]\n```'
    findings = parse_review_reply(text)
    assert findings == [{"path": "a.py", "line": 3, "severity": "high",
                         "message": "空指针", "suggestion": "加判空"}]


def test_parse_bare_json_array_with_prose():
    """裸 JSON 数组（带前导散文）正常解析。"""
    text = '好的，以下是评审结果：\n[{"path": "b.py", "severity": "low", "message": "命名差"}]'
    findings = parse_review_reply(text)
    assert len(findings) == 1
    assert findings[0]["path"] == "b.py"
    assert findings[0]["line"] is None
    assert findings[0]["suggestion"] is None


def test_parse_findings_object_form():
    """{"findings": [...]} 对象形态正常解析。"""
    text = '{"findings": [{"path": "c.py", "severity": "medium", "message": "m"}]}'
    findings = parse_review_reply(text)
    assert len(findings) == 1 and findings[0]["path"] == "c.py"


def test_parse_item_missing_path_skipped():
    """缺 path / path 非 str 的项跳过，不炸整体。"""
    text = '[{"message": "无路径"}, {"path": 42, "message": "数字路径"}, {"path": "ok.py", "severity": "low", "message": "好"}]'
    findings = parse_review_reply(text)
    assert len(findings) == 1
    assert findings[0]["path"] == "ok.py"


def test_parse_illegal_severity_defaults_medium():
    """severity 非法 → medium。"""
    findings = parse_review_reply(
        '[{"path": "a.py", "severity": "critical", "message": "x"}]')
    assert findings[0]["severity"] == "medium"


def test_parse_illegal_line_becomes_none():
    """line 非 int → None。"""
    findings = parse_review_reply(
        '[{"path": "a.py", "line": "三", "severity": "low", "message": "x"}]')
    assert findings[0]["line"] is None


def test_parse_no_json_raises():
    """完全无 JSON → ReviewParseError。"""
    with pytest.raises(ReviewParseError):
        parse_review_reply("我觉得代码写得挺好，没什么问题。")


def test_parse_empty_findings():
    """空 findings [] → 空列表。"""
    assert parse_review_reply("[]") == []
    assert parse_review_reply('{"findings": []}') == []


# ====================================================================
# 3 · POST /api/v1/project/review 端点
# ====================================================================

def test_review_clean_workspace_short_circuits(client, repo, fake_llm):
    """工作区干净 → 200 findings=[] note 非空，且 _llm_chat 未被调用。"""
    r = _review(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["findings"] == []
    assert body["files_reviewed"] == 0
    assert body["note"], "空 diff 必须有 note"
    assert body["model"] == "fake-coder"
    assert fake_llm["calls"] == [], "空 diff 短路，绝不准调 LLM"


def test_review_returns_structured_findings(client, repo, fake_llm):
    """有 diff + fake LLM 返回 fence JSON → 200，findings 结构与 files_reviewed 正确。"""
    (repo / "tracked.txt").write_text("v2\n")
    (repo / "new.py").write_text("print(1)\n")
    fake_llm["reply"] = (
        '```json\n'
        '[{"path": "tracked.txt", "line": 1, "severity": "HIGH", "message": "版本号写死", "suggestion": null},'
        ' {"path": "new.py", "severity": "low", "message": "调试输出"}]\n'
        '```'
    )
    r = _review(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["files_reviewed"] == 2  # tracked 修改 + untracked 新文件
    assert body["model"] == "fake-coder"
    assert len(body["findings"]) == 2
    f0 = body["findings"][0]
    assert f0["path"] == "tracked.txt"
    assert f0["line"] == 1
    assert f0["severity"] == "medium"  # "HIGH" 非法 → 规范化 medium
    assert f0["suggestion"] is None
    assert body["findings"][1]["path"] == "new.py"
    # prompt 里确实带上了 diff（fence 包裹）
    assert "```diff" in fake_llm["calls"][0]["user"]


def test_review_model_alias_passthrough(client, repo, fake_llm):
    """请求体 model alias 透传到 resolve_worker_model_config。"""
    (repo / "tracked.txt").write_text("v2\n")
    r = _review(client, model="architect")
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "fake-architect"


def test_review_parse_failure_502(client, repo, fake_llm):
    """LLM 返回非 JSON → 502 明示，绝不返回伪造 findings。"""
    (repo / "tracked.txt").write_text("v2\n")
    fake_llm["reply"] = "看起来没啥问题。"
    r = _review(client)
    assert r.status_code == 502
    assert "解析失败" in r.json()["detail"]


def test_review_llm_exception_502(client, repo, fake_llm):
    """LLM 调用抛异常 → 502。"""
    (repo / "tracked.txt").write_text("v2\n")
    fake_llm["exc"] = RuntimeError("connection refused")
    r = _review(client)
    assert r.status_code == 502
    assert "评审模型调用失败" in r.json()["detail"]


def test_review_disabled_by_env_404(client, repo, fake_llm, monkeypatch):
    """FLIPPED_AI_REVIEW=0 → 404「AI 评审功能已禁用」。"""
    monkeypatch.setenv("FLIPPED_AI_REVIEW", "0")
    r = _review(client)
    assert r.status_code == 404
    assert "AI 评审功能已禁用" in r.json()["detail"]


def test_review_no_active_project_400(client, fake_llm):
    """无活动项目 root None → 400。"""
    from api import project_state as ps
    ps.clear_active()
    r = _review(client)
    assert r.status_code == 400
    assert "未选择项目" in r.json()["detail"]
