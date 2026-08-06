"""M197 · registry P2 批消化单测。

- M197.1：_git_files 子目录 pathspec 作用域列举（消化 L-M171-2）
- M197.2：_run_chat RAG 注入 asyncio.to_thread 异步化（消化 L-M172-3）
- M197.3：_git_fingerprint untracked 超时降级 + env 覆盖（消化 L-M189-1）
- M197.4：verify_cmd host 执行 rlimit + env 净化（消化 L-M188-2）
- M197.5：FLIPPED_BIND_ALL 一键局域网（消化 L-M181-4，脚本 grep 断言）
- M197.6：classify 全表打分制 + --stats 未命中率（消化 L-M184-1）
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import limitations_report  # noqa: E402

pytestmark = pytest.mark.skipif(
    __import__("shutil").which("git") is None, reason="git 不可用")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def monorepo(tmp_path):
    """monorepo：根 a.py + sub/b.md + sub/deep/c.md + other/d.md，全部 tracked。"""
    root = tmp_path / "mono"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.py").write_text("x=1\n")
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "sub" / "b.md").write_text("# b\n")
    (root / "sub" / "deep" / "c.md").write_text("# c\n")
    (root / "other").mkdir()
    (root / "other" / "d.md").write_text("# d\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    return root


# ====================================================================
# 1 · M197.1 _git_files 子目录 pathspec（消化 L-M171-2）
# ====================================================================

def test_git_files_subdir_scoped(monkeypatch, monorepo):
    """子目录摄入：返回文件全在 sub/ 内，且 ls-files argv 带 `-- sub` pathspec。"""
    from rag import ingest
    real_run = subprocess.run
    ls_calls: list[list[str]] = []

    def _spy(cmd, **kw):
        if "ls-files" in cmd:
            ls_calls.append(list(cmd))
        return real_run(cmd, **kw)

    monkeypatch.setattr(ingest.subprocess, "run", _spy)
    files = ingest._git_files(monorepo / "sub", {".md"})
    assert files is not None
    names = sorted(p.relative_to(monorepo).as_posix() for p in files)
    assert names == ["sub/b.md", "sub/deep/c.md"], "只列 sub/ 下文件（含深层）"
    assert ls_calls, "应调用 ls-files"
    cmd = ls_calls[0]
    assert "--" in cmd and cmd[cmd.index("--") + 1] == "sub", \
        f"ls-files 应带子目录 pathspec: {cmd}"


def test_git_files_toplevel_omits_pathspec(monkeypatch, monorepo):
    """base==toplevel：省略 pathspec（保持原语义），全 repo 列举。"""
    from rag import ingest
    real_run = subprocess.run
    ls_calls: list[list[str]] = []

    def _spy(cmd, **kw):
        if "ls-files" in cmd:
            ls_calls.append(list(cmd))
        return real_run(cmd, **kw)

    monkeypatch.setattr(ingest.subprocess, "run", _spy)
    files = ingest._git_files(monorepo, {".md", ".py"})
    assert files is not None
    names = sorted(p.relative_to(monorepo).as_posix() for p in files)
    assert names == ["a.py", "other/d.md", "sub/b.md", "sub/deep/c.md"]
    assert ls_calls and "--" not in ls_calls[0], "toplevel 不应加 pathspec"


def test_git_files_outside_toplevel_falls_back(monorepo, tmp_path):
    """base 不在 toplevel 下 → None（回退 rglob），不抛异常。"""
    from rag import ingest
    outside = tmp_path / "outside"
    outside.mkdir()
    assert ingest._git_files(outside, {".md"}) is None


# ====================================================================
# 2 · M197.2 RAG 注入 to_thread 异步化（消化 L-M172-3）
# ====================================================================

def _drive_chat_for_thread(monkeypatch, rag_recorder):
    """跑一次非流式 _run_chat，返回 (main, sid, llm_calls)。"""
    import api.main as main

    monkeypatch.setenv("FLIPPED_CHAT_STREAM", "0")
    monkeypatch.delenv("FLIPPED_RAG_AUTO", raising=False)
    monkeypatch.setattr(
        "driving.model_router.resolve_worker_model_config",
        lambda alias="coder": ("http://fake.test/v1", "fake-model"),
    )
    llm_calls: list[dict] = []

    async def _fake_chat(base_url, model, system, user, timeout=120.0):
        llm_calls.append({"system": system, "user": user})
        return "回复", None

    monkeypatch.setattr(main, "_llm_chat", _fake_chat)
    fake = types.ModuleType("api.rag_context")
    fake.build_rag_context = rag_recorder
    monkeypatch.setitem(sys.modules, "api.rag_context", fake)

    sid = main.store.create("m197-thread", mode="chat").id

    async def _wrap():
        await main._run_chat(sid, "task-1", "hello", "coder", "chat")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_wrap())
    return main, sid, llm_calls


def test_rag_context_runs_off_event_loop_thread(monkeypatch):
    """build_rag_context 经 asyncio.to_thread 在 worker 线程执行，不阻塞 event loop。"""
    main_thread = threading.get_ident()
    seen: dict = {}

    def _recorder(query, *, project=None, n_results=4, max_chars=2400, store=None):
        seen["thread"] = threading.get_ident()
        return "RAGCTX", 1

    main, sid, llm_calls = _drive_chat_for_thread(monkeypatch, _recorder)
    assert seen.get("thread") is not None, "build_rag_context 应被调用"
    assert seen["thread"] != main_thread, "应经 to_thread 在 worker 线程执行"
    assert llm_calls[0]["system"].endswith("RAGCTX"), "注入语义不变"


def test_default_store_singleton_survives_concurrency(tmp_path, monkeypatch):
    """默认 store 单例化回归：并发 build_rag_context（store=None）全部命中。

    历史 bug：每次调用新建 PersistentClient，返回后 GC → chromadb
    SharedSystemClient refcount 归零逐出 System → 并发线程 KeyError，
    被 fail-open 吞掉表现为 rag_chunks=0（verify_m197.sh 场景 b 实测复现）。
    """
    import rag.ingest as ingest_mod
    from api import rag_context

    monkeypatch.setenv("RAG_DB_DIR", str(tmp_path / "ragdb"))
    monkeypatch.setenv("RAG_EMBEDDING", "mock")
    monkeypatch.setattr(rag_context, "_default_store", None)  # 隔离：防跨测试持活

    ingest_mod.ingest_text("M197ConcurrencyMarker 并发唯一标记片段",
                           metadata={"project": "m197", "source": "m197.md"})

    results: list = [None] * 8

    def _w(i):
        results[i] = rag_context.build_rag_context(f"M197ConcurrencyMarker 是什么 {i}")

    ts = [threading.Thread(target=_w, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(r and r[1] >= 1 for r in results), \
        f"并发查询应全部命中: {[r[1] if r else None for r in results]}"
    assert rag_context._default_store is not None, "默认 store 应已单例持活"


# ====================================================================
# 3 · M197.3 _git_fingerprint 超时降级（消化 L-M189-1）
# ====================================================================

def test_fingerprint_degrades_to_normal_on_timeout(monkeypatch, monorepo):
    """首试 --untracked-files=all 超时 → 降级 normal 重试成功 → 返回指纹。"""
    from api import project_map
    real_run = subprocess.run
    status_calls: list[list[str]] = []

    def _fake(cmd, **kw):
        if "status" in cmd:
            status_calls.append(list(cmd))
            if "--untracked-files=all" in cmd:
                raise subprocess.TimeoutExpired(cmd, 5)
        return real_run(cmd, **kw)

    monkeypatch.setattr(project_map.subprocess, "run", _fake)
    fp = project_map._git_fingerprint(monorepo)
    assert fp is not None and len(fp) == 16
    modes = [c[c.index("--porcelain=v1") + 1] for c in status_calls]
    assert modes == ["--untracked-files=all", "--untracked-files=normal"], \
        f"应先 all 超时后降级 normal: {modes}"


def test_fingerprint_both_timeout_returns_none(monkeypatch, monorepo):
    """all + normal 均超时 → None（调用方回退 mtime 判定）。"""
    from api import project_map

    def _always_timeout(cmd, **kw):
        if "status" in cmd:
            raise subprocess.TimeoutExpired(cmd, 5)
        return subprocess.CompletedProcess(cmd, 0, "true\n", "")

    monkeypatch.setattr(project_map.subprocess, "run", _always_timeout)
    assert project_map._git_fingerprint(monorepo) is None


def test_fingerprint_env_normal_skips_all(monkeypatch, monorepo):
    """FLIPPED_FP_UNTRACKED=normal → 首试即 normal，不降级重试。"""
    from api import project_map
    real_run = subprocess.run
    status_calls: list[list[str]] = []

    def _spy(cmd, **kw):
        if "status" in cmd:
            status_calls.append(list(cmd))
        return real_run(cmd, **kw)

    monkeypatch.setenv("FLIPPED_FP_UNTRACKED", "normal")
    monkeypatch.setattr(project_map.subprocess, "run", _spy)
    fp = project_map._git_fingerprint(monorepo)
    assert fp is not None
    assert len(status_calls) == 1
    assert "--untracked-files=normal" in status_calls[0]


def test_fingerprint_real_repo_still_works(monkeypatch, monorepo):
    """真实路径回归：默认 all 模式正常出指纹（不触发降级）。"""
    from api import project_map
    monkeypatch.delenv("FLIPPED_FP_UNTRACKED", raising=False)
    fp = project_map._git_fingerprint(monorepo)
    assert fp is not None and len(fp) == 16


# ====================================================================
# 4 · M197.4 verify_cmd host 资源闸 + env 净化（消化 L-M188-2）
# ====================================================================

def test_verify_env_strips_secrets(monkeypatch):
    """env 净化：白名单保留 PATH，剥掉敏感变量。"""
    from api import assistant
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "super-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    env = assistant._verify_env()
    assert "PATH" in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "OPENAI_API_KEY" not in env


def test_verify_env_keep_extends_whitelist(monkeypatch):
    """FLIPPED_VERIFY_ENV_KEEP 逗号分隔追加放行。"""
    from api import assistant
    monkeypatch.setenv("MY_CUSTOM_FLAG", "1")
    monkeypatch.setenv("FLIPPED_VERIFY_ENV_KEEP", "MY_CUSTOM_FLAG, OTHER")
    env = assistant._verify_env()
    assert env.get("MY_CUSTOM_FLAG") == "1"


@pytest.mark.skipif(os.name != "posix", reason="preexec_fn 仅 POSIX")
def test_run_verify_host_passes_rlimits_and_clean_env(monkeypatch, tmp_path):
    """subprocess.run 收到 preexec_fn + 净化 env；退出码语义不变。"""
    from api import assistant
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "super-secret")
    captured: dict = {}
    real_run = subprocess.run

    def _spy(cmd, **kw):
        captured.update(kw)
        return real_run(cmd, **kw)

    monkeypatch.setattr(assistant.subprocess, "run", _spy)
    proc = assistant._run_verify_host(["true"], str(tmp_path))
    assert proc.returncode == 0
    assert captured.get("preexec_fn") is assistant._verify_rlimits
    assert "AWS_SECRET_ACCESS_KEY" not in captured["env"]
    assert captured["timeout"] == 120


@pytest.mark.skipif(os.name != "posix", reason="rlimit 仅 POSIX")
def test_verify_rlimits_actually_limit_child():
    """子进程真实生效：_verify_rlimits 后 getrlimit 读回 CPU=120s；AS 闸按平台二态断言。

    平台现实（已探测）：
    - RLIMIT_CPU：macOS/Linux 均可设 → 读回必须是 (120, 120)。
    - RLIMIT_AS：Linux 可设 1GB；macOS setrlimit 抛 ValueError
      （current limit exceeds maximum limit）被 _verify_rlimits 静默跳过，
      读回保持 RLIM_INFINITY——这是「失败静默」既定设计，非缺陷。
    不依赖「超限分配被杀」断言：macOS 对 RLIMIT_AS 惰性虚拟内存本就不强制。
    """
    code = (
        "import sys, resource; sys.path.insert(0, %r);"
        "from api.assistant import _verify_rlimits;"
        "_verify_rlimits();"
        "cpu = resource.getrlimit(resource.RLIMIT_CPU);"
        "as_ = resource.getrlimit(resource.RLIMIT_AS);"
        "assert cpu == (120, 120), cpu;"
        "inf = resource.RLIM_INFINITY;"
        "assert as_ in ((1 << 30, 1 << 30), (inf, inf)), as_;"
        "print('rlimits ok', cpu, as_)"
    ) % str(REPO_ROOT / "src")
    proc = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"rlimit 应符合期望: {proc.stderr}"
    assert "rlimits ok" in proc.stdout


# ====================================================================
# 5 · M197.5 FLIPPED_BIND_ALL 一键局域网（消化 L-M181-4）
# ====================================================================

def test_dev_up_supports_bind_all():
    """dev_up.sh：FLIPPED_BIND_ALL=1 → --host 0.0.0.0 变量化。"""
    text = (REPO_ROOT / "scripts" / "dev_up.sh").read_text(encoding="utf-8")
    assert "FLIPPED_BIND_ALL" in text
    assert 'BIND_HOST="0.0.0.0"' in text
    assert '--host "$BIND_HOST"' in text


def test_predev_supports_bind_all():
    """console/predev.sh 同款开关。"""
    text = (REPO_ROOT / "console" / "predev.sh").read_text(encoding="utf-8")
    assert "FLIPPED_BIND_ALL" in text
    assert 'BIND_HOST="0.0.0.0"' in text
    assert '--host "$BIND_HOST"' in text


def test_bind_all_default_is_loopback():
    """两脚本默认仍 127.0.0.1（不改安全面）。"""
    for rel in ("scripts/dev_up.sh", "console/predev.sh"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert 'BIND_HOST="127.0.0.1"' in text


# ====================================================================
# 6 · M197.6 classify 全表打分制（消化 L-M184-1）
# ====================================================================

def test_classify_multi_hit_picks_highest_score():
    """多类关键词同时命中：命中数最多者胜（2 安全 > 1 性能）。"""
    hit = limitations_report._classify_text("token 注入鉴权验证存在超时开销")
    assert hit is not None
    assert hit[0] == "安全", f"安全 4 命中应胜性能 2 命中: {hit}"


def test_classify_tie_falls_back_to_table_order():
    """同分按 CLASSIFY_RULES 表序（安全在功能缺口前）。"""
    hit = limitations_report._classify_text("token 未做")
    assert hit is not None and hit[0] == "安全"


def test_classify_no_hit_returns_none():
    """无任何关键词 → None（保持人工分类入口）。"""
    assert limitations_report._classify_text("天马行空毫不相关") is None


def test_classify_stats_reports_unhit_rate(tmp_path, capsys):
    """classify --stats 输出未命中率统计行。"""
    import json
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"version": 1, "updated_at": "", "limitations": [
        {"id": "L-M1-1", "milestone": "M1", "text": "token 泄漏风险",
         "category": "未分类", "priority": "P2", "difficulty": "中",
         "status": "open", "resolution_note": "", "target": ""},
        {"id": "L-M1-2", "milestone": "M1", "text": "毫不相关的天马行空",
         "category": "未分类", "priority": "P2", "difficulty": "中",
         "status": "open", "resolution_note": "", "target": ""},
    ]}, ensure_ascii=False), encoding="utf-8")
    rc = limitations_report.main(["classify", "--registry", str(reg), "--stats"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "未命中率" in out and "50.0%" in out
