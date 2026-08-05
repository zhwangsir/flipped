"""M186 · AI 评审历史持久化 + commit message 生成（A 队后端）。

- review_store：save 原子写落盘 + 返回完整记录；list ts desc（文件名降序）且不含
  findings；load 命中/未知 id/「..」「/」/空 id → None；目录不存在 → []；
  坏 JSON 跳过不炸；写后超 REVIEW_HISTORY_CAP 按文件名升序删最旧；tmp 不残留。
- build_commit_prompt：conventional commit 指令 + 逐文件 diff 段（复用 _file_section）；
  空 files → 指令 + 「（当前无文件变更）」；超 6k 预算按文件逆序截断并注记。
- parse_commit_reply：剥 fence 后取首个非空行起至多 20 个非空行 join；全空 →
  ReviewParseError。
- 端点：POST /project/review 成功后 fail-open 落盘并回传 review_id（干净工作区
  review_id=None）；GET /project/reviews 列表（无活动项目 → 空不 400）；
  GET /project/reviews/{id} 详情（未命中/无项目 → 404）；
  POST /project/commit_message（干净 → message="" note="工作区干净"；LLM/解析失败 →
  502）；FLIPPED_AI_REVIEW=0 → 三个新端点 404。

测试风格沿用 test_m179_review.py：TestClient + tmp_path 真 git 仓库
（无 git → 全模块 skip）；LLM 一律 monkeypatch fake，不烧真模型；
FLIPPED_REVIEWS_DIR 隔离到 tmp_path，不落真盘。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from api.review import (
    COMMIT_PROMPT_BUDGET,
    COMMIT_SYSTEM_PROMPT,
    ReviewParseError,
    build_commit_prompt,
    parse_commit_reply,
)
from api.review_store import (
    REVIEW_HISTORY_CAP,
    list_reviews,
    load_review,
    save_review,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git 不可用")

_FINDINGS = [{"path": "a.py", "line": 1, "severity": "low",
              "message": "命名差", "suggestion": None}]


def _git(root, *args):
    subprocess.run(["git", *args], cwd=str(root), check=True,
                   capture_output=True, text=True)


def _write(reviews_dir, project, name, **over):
    """直接手写一条记录文件（crafted 文件名控序，用于 list/cap 测试）。"""
    rec = {"id": name[:-5], "ts": "2026-01-01T00:00:00+00:00", "project": project,
           "model": "m", "files_reviewed": 1, "findings_count": 0, "findings": []}
    rec.update(over)
    d = reviews_dir / project
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(rec), encoding="utf-8")
    return rec


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + reviews 目录 + mock orchestrator，返回 TestClient（同 m179 套路）。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    monkeypatch.setenv("FLIPPED_REVIEWS_DIR", str(tmp_path / "reviews"))
    from api.main import app
    return TestClient(app)


@pytest.fixture()
def reviews_dir(tmp_path):
    """与 client fixture 相同的隔离 reviews 目录（tmp_path 测试内唯一）。"""
    return tmp_path / "reviews"


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


def _commit(client, **kw):
    return client.post("/api/v1/project/commit_message", json=kw or {})


# ====================================================================
# 1 · review_store.save_review
# ====================================================================

def test_save_review_writes_file_and_returns_record(tmp_path):
    """save 落盘 {dir}/{project}/{id}.json，返回完整记录且与盘上内容一致。"""
    rec = save_review(tmp_path, project="proj", model="m1",
                      files_reviewed=2, findings=_FINDINGS)
    assert rec["project"] == "proj"
    assert rec["model"] == "m1"
    assert rec["files_reviewed"] == 2
    assert rec["findings_count"] == 1
    assert rec["findings"] == _FINDINGS
    assert rec["id"], "id 非空"
    datetime.fromisoformat(rec["ts"])  # ts 为可解析 iso8601
    f = tmp_path / "proj" / f"{rec['id']}.json"
    assert f.is_file(), "id = 文件名去 .json"
    assert json.loads(f.read_text(encoding="utf-8")) == rec


def test_save_review_atomic_write_no_tmp_residue(tmp_path):
    """原子写：写后目录里只有 .json，无 .tmp 残留。"""
    save_review(tmp_path, project="p", model="m", files_reviewed=0, findings=[])
    names = [p.name for p in (tmp_path / "p").iterdir()]
    assert len(names) == 1
    assert names[0].endswith(".json")
    assert not any(n.endswith(".tmp") for n in names)


def test_save_review_cap_evicts_oldest(tmp_path):
    """写后超 cap：按文件名升序删最旧，保留最新 REVIEW_HISTORY_CAP 条。"""
    for i in range(REVIEW_HISTORY_CAP):
        _write(tmp_path, "p", f"20200101T0000{i:02d}_old{i:02d}.json")
    rec = save_review(tmp_path, project="p", model="m", files_reviewed=0, findings=[])
    files = sorted(p.name for p in (tmp_path / "p").iterdir())
    assert len(files) == REVIEW_HISTORY_CAP
    assert f"{rec['id']}.json" in files, "新写入的记录必须保留"
    assert "20200101T000000_old00.json" not in files, "最旧一条被删"
    assert "20200101T000001_old01.json" in files


# ====================================================================
# 2 · review_store.list_reviews
# ====================================================================

def test_list_reviews_ts_desc_and_strips_findings(tmp_path):
    """ts desc（文件名降序）；每项无 findings，恰为 6 个摘要字段。"""
    _write(tmp_path, "p", "20260101T000000_aaa.json")
    _write(tmp_path, "p", "20260103T000000_ccc.json")
    _write(tmp_path, "p", "20260102T000000_bbb.json")
    out = list_reviews(tmp_path, "p")
    assert [e["id"] for e in out] == [
        "20260103T000000_ccc", "20260102T000000_bbb", "20260101T000000_aaa"]
    for e in out:
        assert "findings" not in e
        assert set(e) == {"id", "ts", "project", "model",
                          "files_reviewed", "findings_count"}


def test_list_reviews_missing_dir_returns_empty(tmp_path):
    """目录不存在 → []，不炸。"""
    assert list_reviews(tmp_path, "nope") == []
    assert list_reviews(tmp_path / "ghost", "p") == []


def test_list_reviews_skips_bad_json(tmp_path):
    """坏 JSON 文件跳过不炸，好文件照常返回。"""
    good = _write(tmp_path, "p", "20260101T000000_ok.json")
    (tmp_path / "p" / "20260102T000000_bad.json").write_text("{not json",
                                                            encoding="utf-8")
    out = list_reviews(tmp_path, "p")
    assert [e["id"] for e in out] == [good["id"]]


# ====================================================================
# 3 · review_store.load_review
# ====================================================================

def test_load_review_hit_returns_full_record(tmp_path):
    """命中 → 完整记录（含 findings）。"""
    rec = save_review(tmp_path, project="p", model="m",
                      files_reviewed=1, findings=_FINDINGS)
    got = load_review(tmp_path, "p", rec["id"])
    assert got == rec
    assert got["findings"] == _FINDINGS


def test_load_review_unknown_id_none(tmp_path):
    """未知 id → None。"""
    save_review(tmp_path, project="p", model="m", files_reviewed=0, findings=[])
    assert load_review(tmp_path, "p", "20990101T000000_nope") is None


@pytest.mark.parametrize("bad_id", ["", "../escape", "a/b", "..", "x/../y"])
def test_load_review_illegal_id_none(tmp_path, bad_id):
    """id 含「..」/「/」或为空 → None（路径穿越防护）。"""
    save_review(tmp_path, project="p", model="m", files_reviewed=0, findings=[])
    assert load_review(tmp_path, "p", bad_id) is None


def test_load_review_bad_json_none(tmp_path):
    """文件存在但 JSON 坏 → None。"""
    d = tmp_path / "p"
    d.mkdir()
    (d / "20260101T000000_bad.json").write_text("oops", encoding="utf-8")
    assert load_review(tmp_path, "p", "20260101T000000_bad") is None


# ====================================================================
# 4 · build_commit_prompt
# ====================================================================

def test_commit_prompt_has_instruction_and_file_section():
    """指令含 conventional commit 要求，文件段复用 _file_section（fence 包裹）。"""
    prompt = build_commit_prompt([{"path": "a.py", "added": 1, "removed": 0,
                                   "lines": [{"type": "add", "text": "x=1"}]}])
    assert "conventional commit" in prompt
    assert "type(scope): subject" in prompt
    assert "72" in prompt
    assert "只输出 commit 文本" in prompt
    assert "### 文件: a.py" in prompt
    assert "```diff" in prompt


def test_commit_prompt_empty_files():
    """空 files → 指令 + 「（当前无文件变更）」，无截断注记。"""
    prompt = build_commit_prompt([])
    assert "conventional commit" in prompt
    assert "（当前无文件变更）" in prompt
    assert "已截断" not in prompt


def test_commit_prompt_truncation_drops_tail_files():
    """超 COMMIT_PROMPT_BUDGET 按文件逆序丢弃，尾部注记「已截断 N 个文件」。"""
    big = [{"type": "add", "text": "x" * 200} for _ in range(60)]  # ~12k > 6k 预算
    files = [
        {"path": "keep.py", "added": 1, "removed": 0,
         "lines": [{"type": "add", "text": "s"}]},
        {"path": "drop.py", "added": len(big), "removed": 0, "lines": big},
    ]
    prompt = build_commit_prompt(files)
    assert "keep.py" in prompt, "前部文件必须完整保留"
    assert "drop.py" not in prompt
    assert "已截断 1 个文件" in prompt
    assert len(prompt) <= COMMIT_PROMPT_BUDGET + 16


# ====================================================================
# 5 · parse_commit_reply
# ====================================================================

def test_parse_commit_reply_plain_multiline():
    """普通 subject + body：空行折叠，非空行 join。"""
    assert (parse_commit_reply("feat(api): 加端点\n\n补充 body")
            == "feat(api): 加端点\n补充 body")


def test_parse_commit_reply_strips_fence():
    """``` 围栏包裹的回复剥壳后取文本。"""
    assert parse_commit_reply("```\nfeat: x\n```") == "feat: x"
    assert (parse_commit_reply("```text\nfix(api): y\n\nbody\n```")
            == "fix(api): y\nbody")


def test_parse_commit_reply_collapses_blank_lines():
    """前导/中间/尾部空行（含纯空白行）一律折叠。"""
    assert (parse_commit_reply("\n\n  \nchore: z\n\n\n\nbody line\n\n")
            == "chore: z\nbody line")


def test_parse_commit_reply_caps_at_20_lines():
    """至多 20 个非空行。"""
    text = "\n".join(f"line{i}" for i in range(30))
    assert parse_commit_reply(text) == "\n".join(f"line{i}" for i in range(20))


def test_parse_commit_reply_empty_raises():
    """全空（空串/纯空白/剥完 fence 啥也不剩）→ ReviewParseError。"""
    with pytest.raises(ReviewParseError):
        parse_commit_reply("")
    with pytest.raises(ReviewParseError):
        parse_commit_reply("   \n\n  ")
    with pytest.raises(ReviewParseError):
        parse_commit_reply("```\n```")


# ====================================================================
# 6 · POST /project/review 落盘 + review_id
# ====================================================================

def test_review_persists_and_returns_review_id(client, repo, fake_llm, reviews_dir):
    """评审成功后落盘：响应带 review_id，盘上记录字段与响应一致。"""
    (repo / "tracked.txt").write_text("v2\n")
    fake_llm["reply"] = ('[{"path": "tracked.txt", "line": 1, "severity": "low",'
                         ' "message": "版本号写死", "suggestion": null}]')
    r = _review(client)
    assert r.status_code == 200, r.text
    body = r.json()
    rid = body["review_id"]
    assert isinstance(rid, str) and rid
    f = reviews_dir / repo.name / f"{rid}.json"
    assert f.is_file(), "记录落在 {reviews_dir}/{project}/{review_id}.json"
    rec = json.loads(f.read_text(encoding="utf-8"))
    assert rec["id"] == rid
    assert rec["project"] == repo.name
    assert rec["model"] == "fake-coder"
    assert rec["files_reviewed"] == 1
    assert rec["findings_count"] == 1
    assert rec["findings"][0]["path"] == "tracked.txt"
    datetime.fromisoformat(rec["ts"])


def test_review_clean_workspace_review_id_none_no_persist(client, repo, fake_llm,
                                                          reviews_dir):
    """干净工作区早返：review_id=None，且不产生任何落盘文件。"""
    r = _review(client)
    assert r.status_code == 200, r.text
    assert r.json()["review_id"] is None
    assert not reviews_dir.exists() or list(reviews_dir.iterdir()) == []


def test_review_persist_failure_fail_open(client, repo, fake_llm, monkeypatch):
    """落盘异常 fail-open：响应照常 200，review_id=None。"""
    (repo / "tracked.txt").write_text("v2\n")

    def _boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr("api.review_store.save_review", _boom)
    r = _review(client)
    assert r.status_code == 200, r.text
    assert r.json()["review_id"] is None
    assert r.json()["findings"] == []


# ====================================================================
# 7 · GET /project/reviews + GET /project/reviews/{id}
# ====================================================================

def test_reviews_list_after_review(client, repo, fake_llm):
    """列表项为摘要（无 findings），字段与契约一致。"""
    (repo / "tracked.txt").write_text("v2\n")
    rid = _review(client).json()["review_id"]
    r = client.get("/api/v1/project/reviews")
    assert r.status_code == 200, r.text
    reviews = r.json()["reviews"]
    assert len(reviews) == 1
    e = reviews[0]
    assert e["id"] == rid
    assert e["project"] == repo.name
    assert e["model"] == "fake-coder"
    assert e["files_reviewed"] == 1
    assert e["findings_count"] == 0
    assert isinstance(e["ts"], str) and e["ts"]
    assert "findings" not in e


def test_reviews_list_no_active_project_returns_empty(client, fake_llm):
    """无活动项目 → 200 {"reviews": []}（不 400）。"""
    from api import project_state as ps
    ps.clear_active()
    r = client.get("/api/v1/project/reviews")
    assert r.status_code == 200, r.text
    assert r.json() == {"reviews": []}


def test_review_detail_returns_full_record(client, repo, fake_llm):
    """详情返回完整记录（含 findings 数组）。"""
    (repo / "tracked.txt").write_text("v2\n")
    fake_llm["reply"] = '[{"path": "tracked.txt", "severity": "high", "message": "危"}]'
    rid = _review(client).json()["review_id"]
    r = client.get(f"/api/v1/project/reviews/{rid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == rid
    assert body["project"] == repo.name
    assert body["model"] == "fake-coder"
    assert body["files_reviewed"] == 1
    assert body["findings_count"] == 1
    assert body["findings"] == [{"path": "tracked.txt", "line": None,
                                 "severity": "high", "message": "危",
                                 "suggestion": None}]


def test_review_detail_unknown_id_404(client, repo, fake_llm):
    """未知 id → 404。"""
    r = client.get("/api/v1/project/reviews/20990101T000000_nope")
    assert r.status_code == 404


def test_review_detail_traversal_id_404(client, repo, fake_llm):
    """id 含路径穿越（%2F 编码斜杠 + ..）→ 404，绝不读到项目目录外。"""
    r = client.get("/api/v1/project/reviews/..%2F..%2Fsecret")
    assert r.status_code == 404


def test_review_detail_no_active_project_404(client, fake_llm):
    """无活动项目 → 404。"""
    from api import project_state as ps
    ps.clear_active()
    r = client.get("/api/v1/project/reviews/whatever")
    assert r.status_code == 404


# ====================================================================
# 8 · POST /project/commit_message
# ====================================================================

def test_commit_message_happy_path(client, repo, fake_llm):
    """有 diff → LLM 回复剥 fence 后回传 message；system/prompt 符合契约。"""
    (repo / "tracked.txt").write_text("v2\n")
    fake_llm["reply"] = "```\nfeat(repo): 更新 tracked\n\n细节说明\n```"
    r = _commit(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["message"] == "feat(repo): 更新 tracked\n细节说明"
    assert body["model"] == "fake-coder"
    assert body["files_count"] == 1
    assert body["note"] is None
    call = fake_llm["calls"][0]
    assert call["system"] == COMMIT_SYSTEM_PROMPT
    assert "conventional commit" in call["user"]
    assert "```diff" in call["user"]


def test_commit_message_model_alias_passthrough(client, repo, fake_llm):
    """请求体 model alias 透传。"""
    (repo / "tracked.txt").write_text("v2\n")
    fake_llm["reply"] = "fix: x"
    r = _commit(client, model="architect")
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "fake-architect"


def test_commit_message_clean_workspace(client, repo, fake_llm):
    """干净工作区：message="" files_count=0 note="工作区干净"，不调 LLM。"""
    r = _commit(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["message"] == ""
    assert body["model"] == "fake-coder"
    assert body["files_count"] == 0
    assert body["note"] == "工作区干净"
    assert fake_llm["calls"] == [], "空 diff 短路，绝不准调 LLM"


def test_commit_message_parse_failure_502(client, repo, fake_llm):
    """LLM 返回全空 → 502 解析失败，绝不返回伪造 message。"""
    (repo / "tracked.txt").write_text("v2\n")
    fake_llm["reply"] = "   \n  "
    r = _commit(client)
    assert r.status_code == 502
    assert "解析失败" in r.json()["detail"]


def test_commit_message_llm_exception_502(client, repo, fake_llm):
    """LLM 调用抛异常 → 502。"""
    (repo / "tracked.txt").write_text("v2\n")
    fake_llm["exc"] = RuntimeError("connection refused")
    r = _commit(client)
    assert r.status_code == 502
    assert "提交信息模型调用失败" in r.json()["detail"]


def test_commit_message_no_active_project_400(client, fake_llm):
    """无活动项目 → 400 未选择项目。"""
    from api import project_state as ps
    ps.clear_active()
    r = _commit(client)
    assert r.status_code == 400
    assert "未选择项目" in r.json()["detail"]


# ====================================================================
# 9 · FLIPPED_AI_REVIEW=0 守卫（三个新端点 + review 既有形状）
# ====================================================================

def test_ai_review_disabled_all_new_endpoints_404(client, repo, fake_llm,
                                                  monkeypatch):
    """FLIPPED_AI_REVIEW=0 → review/reviews/reviews/{id}/commit_message 全 404。"""
    monkeypatch.setenv("FLIPPED_AI_REVIEW", "0")
    assert _review(client).status_code == 404
    r = client.get("/api/v1/project/reviews")
    assert r.status_code == 404
    assert "AI 评审功能已禁用" in r.json()["detail"]
    assert client.get("/api/v1/project/reviews/abc").status_code == 404
    assert _commit(client).status_code == 404
