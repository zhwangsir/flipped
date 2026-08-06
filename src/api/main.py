"""flipped orchestration API。

入口: PYTHONPATH=src uvicorn api.main:app --host 127.0.0.1 --port 8011  (见 scripts/dev_up.sh)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .events import EventBus, get_bus
from .schemas import BrowserRenderRequest, Event, EventType, HealthResponse, MetricsResponse, ModelAliasesResponse, ProjectMapResponse, Role, Session, SessionStatus, TaskRequest, TaskResponse
from .session import SessionStore, store
from driving.safety import validate_secrets
from metrics import COLLECTOR
from .factory import router as factory_router

MOCK_WORKER = os.environ.get("FLIPPED_MOCK_WORKER", "0") == "1"
RUNNING_TASKS: dict[str, asyncio.Task] = {}  # M6.2 — 每会话运行中任务句柄，供取消
_STALE_SEEN: set[str] = set()  # M191.4 — watchdog 两击确认用的首击标记集
# M137：默认值收敛为统一库（FLIPPED_DB）；FLIPPED_CHECKPOINT_DB 保留向后兼容
FLIPPED_CHECKPOINT_DB = os.environ.get("FLIPPED_CHECKPOINT_DB") or os.environ.get("FLIPPED_DB", "data/flipped.db")

API_PREFIX = "/api/v1"
CONSOLE_ORIGIN = "http://127.0.0.1:5273"

bus: EventBus = get_bus(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus.set_loop(asyncio.get_running_loop())
    store.load(os.environ.get("FLIPPED_SESSION_STORE_PATH", ".sessions.json"))
    ok, findings = validate_secrets(Path(__file__).resolve().parent.parent)
    if not ok:
        for f in findings:
            print(f"[safety] {f}", file=sys.stderr)
    for session in store.list():
        # M188.2：goal 断点续跑优先于 checkpoint 恢复。goal wrapper 是纯内存协程，
        # 无 checkpoint，但事件流可重建循环态。不能按 status==running 过滤：
        # goal 每轮 dispatch 复用 _run_chat/_run_orchestrator，其尾段会把 store
        # 状态写成 done/error，进程死时 status 不可靠；改由 rebuild_running 从
        # 事件流判可续跑性（无 goal/已终态 → None，回落既有分支）。
        # paused（审批中）不续跑 goal（登记限制），走 orchestrator checkpoint 恢复。
        if session.status != SessionStatus.paused:
            from api.assistant import try_resume_goal
            t_goal = try_resume_goal(session)
            if t_goal is not None:
                RUNNING_TASKS[session.id] = t_goal
                t_goal.add_done_callback(lambda _t, s=session.id: RUNNING_TASKS.pop(s, None))
                continue
        if session.status in (SessionStatus.running, SessionStatus.paused) and session.checkpoint_db_path:
            # M187.3：恢复任务注册进 RUNNING_TASKS（与 _dispatch_scheduled 尾段同形状），
            # 让 scheduler 防重入能看到恢复中的会话，闭合重启后重复派发缺口
            t = asyncio.create_task(_resume_orchestrator(session))
            RUNNING_TASKS[session.id] = t
            t.add_done_callback(lambda _t, s=session.id: RUNNING_TASKS.pop(s, None))
        elif session.status == SessionStatus.running and not session.checkpoint_db_path:
            # M187.3：无 checkpoint 的 running 会话（chat/plan 进程死后无恢复可能）
            # → 启动时一次性标 error，不再永远假 running；paused 不动
            store.update_status(session.id, SessionStatus.error)
    # M178.1：已安排任务定时扫描（FLIPPED_TASKS=0 不起 scheduler）
    scheduler = (asyncio.create_task(_task_scheduler())
                 if os.environ.get("FLIPPED_TASKS", "1") != "0" else None)
    # M191.4：stale running 看门狗（FLIPPED_WATCHDOG=0 不起；独立于 FLIPPED_TASKS）
    watchdog = (asyncio.create_task(_stale_watchdog())
                if os.environ.get("FLIPPED_WATCHDOG", "1") != "0" else None)
    yield
    if scheduler is not None:
        scheduler.cancel()
        try:
            await scheduler
        except asyncio.CancelledError:
            pass
    if watchdog is not None:
        watchdog.cancel()
        try:
            await watchdog
        except asyncio.CancelledError:
            pass
    bus.set_loop(None)
    bus._connections.clear()
    store.save()


async def _stale_sweep_once() -> None:
    """M191.4 · watchdog 单轮扫描（两击确认）。

    status==running 且 RUNNING_TASKS 无活句柄的会话：
    首击记入 _STALE_SEEN 不动（跳过派发链 status=running 先于 create_task 的竞态窗）；
    次击按 lifespan 同款恢复：try_resume_goal 命中 → 注册 RUNNING_TASKS；
    否则有 checkpoint_db_path → create_task(_resume_orchestrator) 注册；
    否则 → update_status(error) + bus.emit status「watchdog: 运行句柄丢失，标记 error」。
    动作后弹出标记；健康/非 running 会话清标记；paused 不动（审批中合法无句柄）。
    单会话异常隔离，不炸整轮。
    """
    for session in store.list():
        sid = session.id
        try:
            if session.status != SessionStatus.running:
                _STALE_SEEN.discard(sid)
                continue
            t = RUNNING_TASKS.get(sid)
            if t is not None and not t.done():
                _STALE_SEEN.discard(sid)  # 健康：活句柄在，清标记
                continue
            if sid not in _STALE_SEEN:
                _STALE_SEEN.add(sid)  # 首击：只记标记不动
                continue
            # 次击：lifespan 同款恢复（goal 续跑优先 → checkpoint resume → 标 error）
            from api.assistant import try_resume_goal
            t_goal = try_resume_goal(session)
            if t_goal is not None:
                RUNNING_TASKS[sid] = t_goal
                t_goal.add_done_callback(lambda _t, s=sid: RUNNING_TASKS.pop(s, None))
            elif session.checkpoint_db_path:
                t = asyncio.create_task(_resume_orchestrator(session))
                RUNNING_TASKS[sid] = t
                t.add_done_callback(lambda _t, s=sid: RUNNING_TASKS.pop(s, None))
            else:
                store.update_status(sid, SessionStatus.error)
                bus.emit(sid, EventType.status, Role.system,
                         {"status": "error", "note": "watchdog: 运行句柄丢失，标记 error"})
            _STALE_SEEN.discard(sid)
        except Exception:  # noqa: BLE001 单会话异常隔离，不炸整轮
            continue


async def _stale_watchdog() -> None:
    """M191.4 · stale running 看门狗：每 FLIPPED_WATCHDOG_SCAN_S（默认 60s）扫一轮。"""
    while True:
        await asyncio.sleep(float(os.environ.get("FLIPPED_WATCHDOG_SCAN_S", "60")))
        try:
            await _stale_sweep_once()
        except Exception:  # noqa: BLE001 扫描循环容错，下轮继续
            continue


app = FastAPI(title="flipped orchestration API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CONSOLE_ORIGIN, "http://localhost:5273"],
    # 桌面壳(Electron,M6.8)从本地静态端口发请求 → 放行 localhost/127.0.0.1 任意端口
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(factory_router)
# M151.1 · 代码助手 assistant router（对话式 surface，复用既有 orchestrator/chat）
# assistant.py 不在模块级 import main 的符号（用函数级 lazy import），故无循环导入，
# 可在 app 创建后立即挂载。router 内的端点在调用时才取 main._run_orchestrator 等。
from .assistant import router as assistant_router  # noqa: E402

app.include_router(assistant_router)


# ---------- 健康检查 ----------

@app.get(f"{API_PREFIX}/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    proxy_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{proxy_url}/models", headers={
                "Authorization": f"Bearer {os.environ.get('LITELLM_MASTER_KEY', 'dummy')}"
            })
        data = r.json() if r.status_code == 200 else {"status_code": r.status_code, "text": r.text}
        return HealthResponse(ok=r.status_code == 200, proxy=data)
    except Exception as e:
        return HealthResponse(ok=False, proxy={}, error=str(e))


# ---------- 性能指标 ----------

@app.get(f"{API_PREFIX}/metrics", response_model=MetricsResponse)
async def metrics() -> MetricsResponse:
    return MetricsResponse(**COLLECTOR.snapshot())


# ---------- M195.3 · 模型 alias 清单（消化 L-M194-2） ----------

@app.get(f"{API_PREFIX}/models/aliases", response_model=ModelAliasesResponse)
async def model_aliases() -> dict[str, Any]:
    """可用模型 alias → 解析后模型 id 清单（env 覆盖实时反映，运行期读不缓存）。

    前端评审模型下拉等动态选项由此供给，替代硬编码 coder/architect。
    """
    from driving.model_router import list_model_aliases
    return {"aliases": list_model_aliases()}


# ---------- RCA 失败计数（M95） ----------

@app.get(f"{API_PREFIX}/rca/failure_counter")
async def get_failure_counter_endpoint() -> dict[str, Any]:
    """返回 RCA 连续失败计数器(按根因分类)。"""
    from driving.rca import get_failure_counter
    return {"counter": {k.value: v for k, v in get_failure_counter().items()}}


# ---------- MCP 服务器（M7.3 真实列表 + 开关） ----------

@app.get(f"{API_PREFIX}/mcp/servers")
async def get_mcp_servers() -> list[dict[str, Any]]:
    from api.mcp_registry import list_servers
    return list_servers()


@app.post(f"{API_PREFIX}/mcp/servers/{{name}}/toggle")
async def toggle_mcp_server(name: str, enabled: bool = Query(...)) -> dict[str, Any]:
    from api.mcp_registry import toggle_server
    try:
        return toggle_server(name, enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown MCP server: {name}")


# ---------- M170.1 · 编辑器直调 MCP 工具（薄路由，逻辑在 api/mcp_call.py） ----------

from fastapi import Response as _Response  # 局部 import：本段自包含，不动顶部 import 行
from . import mcp_call as _mcp_call
from .mcp_call import CallToolRequest, CallToolResponse, ToolListResponse


@app.get(f"{API_PREFIX}/mcp/tools", response_model=ToolListResponse)
async def list_mcp_tools() -> dict[str, Any]:
    """工具清单：内省 mcp_server.tools.TOOLS 动态生成（不硬编码）；内省失败 500 明示。"""
    try:
        return {"tools": _mcp_call.list_tool_specs()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MCP 工具内省失败: {e}")


@app.post(f"{API_PREFIX}/mcp/tools/{{name}}/call", response_model=CallToolResponse)
async def call_mcp_tool(name: str, req: CallToolRequest, response: _Response) -> CallToolResponse:
    """编辑器直调 MCP 工具：快工具同步 200；长工具 202 后台跑，结果回灌会话事件流。"""
    result = await _mcp_call.call_tool(name, req)
    if result.accepted:
        response.status_code = 202
    return result


# ---------- 项目上下文（Stage 3 — composer 上下文行 / 状态栏真实分支） ----------

from . import project_state as ps


@app.websocket(f"{API_PREFIX}/terminal")
async def terminal_ws(websocket: WebSocket) -> None:
    """Stage 5 — 真实 pty 终端（作用域=活动项目根，无项目则回退项目主目录）。"""
    from api.terminal import terminal_bridge
    await terminal_bridge(websocket)


@app.get(f"{API_PREFIX}/project/context")
async def project_context() -> dict[str, Any]:
    """返回活动项目(名/host路径/沙盒路径) + git 分支;无项目 project=None。"""
    import subprocess

    proj = ps.active_project()
    if not proj:
        return {"project": None, "path": None, "sandbox": None, "branch": None, "mode": "本地模式"}
    branch = "unknown"
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3, cwd=proj["host"],
        )
        if out.returncode == 0:
            branch = out.stdout.strip() or "detached"
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "project": proj["name"], "path": proj["host"], "sandbox": proj["sandbox"],
        "branch": branch, "mode": "本地模式",
    }


@app.get(f"{API_PREFIX}/projects")
async def list_projects_endpoint() -> dict[str, Any]:
    """列出项目主目录(~/projects)下的项目 + 当前活动项目。"""
    return {
        "projects_dir": str(ps.PROJECTS_DIR),
        "projects": ps.list_projects(),
        "active": ps.active_project(),
    }


@app.post(f"{API_PREFIX}/projects")
async def create_project(req: dict[str, Any]) -> dict[str, Any]:
    """在项目主目录下新建空白项目文件夹并设为活动项目。"""
    name = str(req.get("name") or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="项目名非法")
    dest = ps.PROJECTS_DIR / name
    if dest.exists():
        raise HTTPException(status_code=409, detail="项目已存在")
    try:
        dest.mkdir(parents=True)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"创建失败: {e}")
    # F8 经验固化:新项目自动带默认 AGENTS.md(测试隔离/python3 -m pytest/换思路等
    # 实测避坑约定),F6 每轮注入 Supervisor,提升自主任务一次通过率。
    from driving.project_rules import write_default_rules
    write_default_rules(dest)
    return ps.set_active(dest)


@app.post(f"{API_PREFIX}/project/open")
async def project_open(req: dict[str, Any]) -> dict[str, Any]:
    """打开/导入项目为活动项目。

    - 路径已在 ~/projects 下 → 直接设为活动;
    - 外部文件夹 → 拷进 ~/projects/<basename> 再设为活动(沙盒经 /projects 挂载才可访问)。
      拷贝保留 .git(审查需要),排除 node_modules 等重依赖/构建产物。
    """
    raw = str(req.get("path") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="path required")
    try:
        src = Path(raw).expanduser().resolve()
    except OSError:
        raise HTTPException(status_code=400, detail="无效路径")
    if not src.is_dir():
        raise HTTPException(status_code=404, detail="不是有效文件夹")
    if ps.is_within_projects(src):
        return ps.set_active(src)
    # 外部文件夹:拷进项目主目录,让沙盒(/projects 挂载)可访问
    import shutil

    dest = ps.PROJECTS_DIR / src.name
    if dest.exists():
        raise HTTPException(status_code=409, detail=f"~/projects/{src.name} 已存在,请改名或直接打开")
    try:
        ps.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(
            "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
            ".pytest_cache", ".mypy_cache", ".ruff_cache", ".DS_Store", ".next", "target",
        ))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")
    return ps.set_active(dest)


# ---------- 项目文件树 / 单文件读取（阶段② — 右侧「文件」做真） ----------

_IGNORE_NAMES = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".devlogs", ".pytest_cache", ".mypy_cache", ".ruff_cache", "chroma",
    ".DS_Store", ".idea", ".vscode", ".sessions.json",
}
_FILES_CAP = 3000  # 总条目上限，避免超大仓库拖垮响应
_FILE_MAX_BYTES = 512_000  # 单文件读取上限（512KB）


def _list_tree(root: Path) -> list[dict[str, Any]]:
    """递归列出项目树（跳过 vcs/依赖/构建产物与隐藏目录，全局限量）。"""
    count = 0

    def walk(d: Path, depth: int) -> list[dict[str, Any]]:
        nonlocal count
        if depth > 8 or count >= _FILES_CAP:
            return []
        try:
            children = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for p in children:
            if count >= _FILES_CAP:
                break
            if p.name in _IGNORE_NAMES:
                continue
            if p.name.startswith(".") and p.is_dir():
                continue
            count += 1
            rel = str(p.relative_to(root))
            if p.is_dir():
                out.append({"name": p.name, "path": rel, "type": "dir",
                            "children": walk(p, depth + 1)})
            else:
                out.append({"name": p.name, "path": rel, "type": "file"})
        return out

    return walk(root, 0)


@app.get(f"{API_PREFIX}/project/files")
async def project_files() -> dict[str, Any]:
    """项目文件树（供右侧「文件」浏览器）。无活动项目返回空树 + needs_project。"""
    root = ps.project_root()
    if root is None:
        return {"root": None, "tree": [], "needs_project": True}
    return {"root": root.name, "tree": _list_tree(root)}


_DIFF_LINE_CAP = 4000


def _parse_unified_diff(text: str) -> list[dict[str, Any]]:
    """把 `git diff` 统一 diff 解析成 [{path, added, removed, lines:[{type,text}]}]。"""
    files: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    budget = _DIFF_LINE_CAP
    for line in text.splitlines():
        if line.startswith("diff --git"):
            path = line.split(" b/")[-1] if " b/" in line else line[len("diff --git "):]
            cur = {"path": path, "added": 0, "removed": 0, "lines": []}
            files.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith(("index ", "--- ", "+++ ", "new file", "deleted file",
                            "similarity", "rename ", "old mode", "new mode", "Binary ")):
            continue
        if budget <= 0:
            continue
        budget -= 1
        if line.startswith("@@"):
            cur["lines"].append({"type": "hunk", "text": line})
        elif line.startswith("+"):
            cur["added"] += 1
            cur["lines"].append({"type": "add", "text": line[1:]})
        elif line.startswith("-"):
            cur["removed"] += 1
            cur["lines"].append({"type": "del", "text": line[1:]})
        else:
            cur["lines"].append({"type": "ctx", "text": line[1:] if line.startswith(" ") else line})
    return files


def _untracked_entries(root: Path) -> list[dict[str, Any]]:
    """untracked 新文件清单（`git diff HEAD` 不覆盖它们，审查面板会漏掉 agent 新写的文件）。

    每条 {"path", "added", "removed": 0, "lines": [], "untracked": True}；
    二进制（utf-8 解码失败 / 含 \\x00 / > _FILE_MAX_BYTES）或单文件任何异常
    → added=0 + "binary": True，绝不上抛。非 git repo / git 失败 → []。
    按 path 字典序输出，保证确定性。
    """
    import subprocess

    try:
        out = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    entries: list[dict[str, Any]] = []
    for rel in sorted(p.strip() for p in out.stdout.splitlines() if p.strip()):
        entry: dict[str, Any] = {"path": rel, "added": 0, "removed": 0,
                                 "lines": [], "untracked": True}
        try:
            f = root / rel
            if f.stat().st_size > _FILE_MAX_BYTES:
                entry["binary"] = True
            else:
                text = f.read_text(encoding="utf-8")
                if "\x00" in text:
                    entry["binary"] = True
                else:
                    entry["added"] = len(text.splitlines())
        except Exception:  # noqa: BLE001 单文件任何异常 → binary 占位，绝不上抛
            entry["added"] = 0
            entry["binary"] = True
        entries.append(entry)
    return entries


@app.post(f"{API_PREFIX}/project/reveal")
async def project_reveal() -> dict[str, Any]:
    """在系统文件管理器中显示项目根目录（侧栏项目「⋯」菜单）。仅 macOS。"""
    import subprocess

    if sys.platform != "darwin":
        raise HTTPException(status_code=501, detail="仅 macOS 支持在 Finder 中显示")
    root = ps.project_root()
    if root is None:
        raise HTTPException(status_code=400, detail="未选择项目")
    try:
        subprocess.run(["open", "-R", str(root)], timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        raise HTTPException(status_code=500, detail=f"打开失败: {e}")
    return {"ok": True, "path": str(root)}


@app.get(f"{API_PREFIX}/project/diff")
async def project_diff() -> dict[str, Any]:
    """工作区真实 git 变更（相对 HEAD），供右侧「变更/审查」渲染真 +/- diff。"""
    import subprocess

    root = ps.project_root()
    if root is None:
        return {"files": []}
    try:
        out = subprocess.run(
            ["git", "diff", "HEAD", "--no-color"],
            cwd=str(root), capture_output=True, text=True, timeout=6,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise HTTPException(status_code=500, detail=f"git diff 失败: {e}")
    files = _parse_unified_diff(out.stdout) if out.returncode == 0 else []
    files += _untracked_entries(root)  # M177.1：git diff 不含 untracked，补上
    return {"files": files}


# ---------- M177.1 · 逐文件回滚（Review 面板） ----------

class RevertRequest(BaseModel):
    path: str = Field(..., min_length=1)


class RevertResponse(BaseModel):
    ok: bool
    path: str
    action: str  # "restored" | "deleted"


def _is_tracked(root: Path, rel: str) -> bool:
    """`git ls-files --error-unmatch -- <rel>` rc==0 即 tracked；任何失败 → False。"""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", rel],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def _git_restore_file(root: Path, rel: str) -> None:
    """`git restore --source=HEAD --worktree -- <rel>`：worktree 回 HEAD（不碰 staging area）。

    非零退出 → RuntimeError 带 stderr（写法参照 assistant._git_restore）。
    """
    import subprocess

    try:
        out = subprocess.run(
            ["git", "restore", "--source=HEAD", "--worktree", "--", rel],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"git restore 执行失败: {exc}") from exc
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git restore exit {out.returncode}")


@app.post(f"{API_PREFIX}/project/revert", response_model=RevertResponse)
async def project_revert(req: RevertRequest) -> RevertResponse:
    """逐文件回滚：tracked → git restore 回 HEAD；untracked → 删除。含路径穿越防护。"""
    if os.environ.get("FLIPPED_REVIEW", "1") == "0":
        raise HTTPException(status_code=404, detail="Review 功能已禁用")
    root = ps.project_root()
    if root is None:
        raise HTTPException(status_code=400, detail="未选择项目")
    target = (root / req.path).resolve()
    root = root.resolve()
    # 路径穿越防护：必须落在仓库根内（同 project_file）
    if target != root and not str(target).startswith(str(root) + os.sep):
        raise HTTPException(status_code=403, detail="path outside project")
    if target == root or target.is_dir():
        raise HTTPException(status_code=422, detail="不能回滚目录")
    rel = target.relative_to(root).as_posix()
    if await asyncio.to_thread(_is_tracked, root, rel):
        try:
            await asyncio.to_thread(_git_restore_file, root, rel)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        return RevertResponse(ok=True, path=rel, action="restored")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not a file")
    await asyncio.to_thread(target.unlink)
    return RevertResponse(ok=True, path=rel, action="deleted")


# ---------- M193.1 · 逐 hunk 拒绝（Review 面板） ----------

class RevertHunkRequest(BaseModel):
    path: str = Field(..., min_length=1)
    hunk_index: int = Field(..., ge=0)


class RevertHunkResponse(BaseModel):
    ok: bool
    path: str
    hunk_index: int
    action: str  # 固定 "hunk_reverted"


def _git_file_patch(root: Path, rel: str) -> str:
    """`git diff HEAD --no-color -- <rel>` 原文（含 header 与全部 hunk）。

    非零退出 / 进程异常 → RuntimeError 带 stderr（写法同 _git_restore_file）。
    """
    import subprocess

    try:
        out = subprocess.run(
            ["git", "diff", "HEAD", "--no-color", "--", rel],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"git diff 执行失败: {exc}") from exc
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git diff exit {out.returncode}")
    return out.stdout


def split_patch_hunks(patch: str) -> tuple[list[str], list[list[str]]]:
    """纯函数：把单文件 unified diff 拆成 (header_lines, hunks)。

    header = 首个以 "@@ " 开头的行之前的全部行；hunks[i] = 第 i 个 "@@ "
    行起到下个 "@@ " 行或 EOF 的行列表（不含下个 @@ 行）。空 patch → ([], [])。
    """
    header: list[str] = []
    hunks: list[list[str]] = []
    cur: list[str] | None = None
    for line in patch.splitlines():
        if line.startswith("@@ "):
            cur = [line]
            hunks.append(cur)
        elif cur is None:
            header.append(line)
        else:
            cur.append(line)
    return header, hunks


def _git_apply_reverse(root: Path, patch_text: str) -> None:
    """`git apply --reverse --whitespace=nowarn -`：把 patch 反向套用到工作区。

    非零退出（典型：diff 漂移、工作区已变化）→ RuntimeError 带 stderr。
    """
    import subprocess

    try:
        out = subprocess.run(
            ["git", "apply", "--reverse", "--whitespace=nowarn", "-"],
            input=patch_text,
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"git apply 执行失败: {exc}") from exc
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git apply exit {out.returncode}")


@app.post(f"{API_PREFIX}/project/revert-hunk", response_model=RevertHunkResponse)
async def project_revert_hunk(req: RevertHunkRequest) -> RevertHunkResponse:
    """逐 hunk 拒绝：重取该文件 diff，把第 hunk_index 个 hunk 反向 apply 回工作区。

    防护链与 project_revert 同款；apply 失败（diff 漂移）→ 409 提示刷新重试。
    """
    if os.environ.get("FLIPPED_REVIEW", "1") == "0":
        raise HTTPException(status_code=404, detail="Review 功能已禁用")
    root = ps.project_root()
    if root is None:
        raise HTTPException(status_code=400, detail="未选择项目")
    target = (root / req.path).resolve()
    root = root.resolve()
    # 路径穿越防护：必须落在仓库根内（同 project_revert）
    if target != root and not str(target).startswith(str(root) + os.sep):
        raise HTTPException(status_code=403, detail="path outside project")
    if target == root or target.is_dir():
        raise HTTPException(status_code=422, detail="不能回滚目录")
    rel = target.relative_to(root).as_posix()
    if not await asyncio.to_thread(_is_tracked, root, rel):
        raise HTTPException(status_code=422, detail="新文件无 hunk，请用整文件回滚")
    try:
        patch = await asyncio.to_thread(_git_file_patch, root, rel)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not patch.strip():
        raise HTTPException(status_code=404, detail="该文件当前无变更")
    header, hunks = split_patch_hunks(patch)
    # 新增/删除文件的 diff 无法按 hunk 部分回滚，走整文件回滚
    if any(line.startswith(("--- /dev/null", "+++ /dev/null")) for line in header):
        raise HTTPException(status_code=422, detail="新增/删除文件请用整文件回滚")
    if req.hunk_index >= len(hunks):
        raise HTTPException(
            status_code=422,
            detail=f"hunk_index 越界（共 {len(hunks)} 个 hunk）")
    single = "\n".join(header + hunks[req.hunk_index]) + "\n"
    try:
        await asyncio.to_thread(_git_apply_reverse, root, single)
    except RuntimeError as e:
        raise HTTPException(
            status_code=409,
            detail=f"工作区已变化（diff 漂移），请刷新后重试: {e}")
    return RevertHunkResponse(ok=True, path=rel, hunk_index=req.hunk_index,
                              action="hunk_reverted")


# ---------- M179.1 · AI 代码评审（Review 面板「AI 评审」按钮） ----------

class ReviewRequest(BaseModel):
    model: str | None = None


class ReviewFinding(BaseModel):
    path: str
    line: int | None = None
    severity: str
    message: str
    suggestion: str | None = None


class ReviewResponse(BaseModel):
    findings: list[ReviewFinding]
    files_reviewed: int
    model: str
    note: str | None = None
    review_id: str | None = None  # M186：落盘成功后的记录 id；干净工作区/落盘失败 → None


def _reviews_dir() -> Path:
    """评审历史根目录（每次调用现读 env，便于测试隔离）。

    M196.4（消化 L-M186-1）三级解析：env FLIPPED_REVIEWS_DIR 显式覆盖 >
    活动项目 {root}/.flipped/reviews（项目资产，随 repo 走）> data/reviews 兜底。
    """
    env = os.environ.get("FLIPPED_REVIEWS_DIR")
    if env:
        return Path(env)
    root = ps.project_root()
    if root is not None:
        return Path(root) / ".flipped" / "reviews"
    return Path("data/reviews")


def _reviews_dir_migrated(project: str) -> Path:
    """_reviews_dir() + 应用侧 legacy data/reviews/<project> 一次性迁入（M196.4）。

    env 显式覆盖时跳过迁移（测试隔离语义不动）；迁移 fail-open 不影响主流程。
    """
    target = _reviews_dir()
    if not os.environ.get("FLIPPED_REVIEWS_DIR"):
        from .review_store import migrate_legacy_reviews
        migrate_legacy_reviews(Path("data/reviews"), target, project)
    return target


@app.post(f"{API_PREFIX}/project/review", response_model=ReviewResponse)
async def project_review(req: ReviewRequest) -> ReviewResponse:
    """AI 代码评审：工作区 git diff → LLM → 结构化 findings。

    M186：成功后 fail-open 落盘（M196.4 起默认 {root}/.flipped/reviews/<project>/，
    超 50 条删最旧；env FLIPPED_REVIEWS_DIR 可覆盖），落盘失败绝不影响响应（review_id=None）。
    """
    if os.environ.get("FLIPPED_AI_REVIEW", "1") == "0":
        raise HTTPException(status_code=404, detail="AI 评审功能已禁用")
    root = ps.project_root()
    if root is None:
        raise HTTPException(status_code=400, detail="未选择项目")
    import subprocess

    from driving.model_router import resolve_worker_model_config

    from .review import (REVIEW_SYSTEM_PROMPT, ReviewParseError,
                         build_review_prompt, parse_review_reply)

    base_url, model = resolve_worker_model_config(req.model or "coder")
    try:
        out = await asyncio.to_thread(
            subprocess.run,
            ["git", "diff", "HEAD", "--no-color"],
            cwd=str(root), capture_output=True, text=True, timeout=6,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise HTTPException(status_code=500, detail=f"git diff 失败: {e}")
    files = _parse_unified_diff(out.stdout) if out.returncode == 0 else []
    files += await asyncio.to_thread(_untracked_entries, root)
    if not files:
        return ReviewResponse(findings=[], files_reviewed=0, model=model,
                              note="工作区干净")
    prompt = build_review_prompt(files)
    try:
        reply, _usage = await _llm_chat(base_url, model, REVIEW_SYSTEM_PROMPT, prompt)
        findings = parse_review_reply(reply)
    except ReviewParseError as e:
        raise HTTPException(status_code=502, detail=f"评审结果解析失败: {e}")
    except Exception as e:  # noqa: BLE001 LLM 调用任何失败 → 502，绝不返回伪造 findings
        raise HTTPException(status_code=502, detail=f"评审模型调用失败: {e}")
    review_id: str | None = None
    try:  # noqa: BLE001 落盘 fail-open：任何持久化失败都不影响评审响应
        from .review_store import save_review
        rec = save_review(_reviews_dir_migrated(ps.active_project()["name"]),
                          project=ps.active_project()["name"],
                          model=model, files_reviewed=len(files), findings=findings)
        review_id = rec["id"]
    except Exception:
        review_id = None
    return ReviewResponse(findings=findings, files_reviewed=len(files), model=model,
                          review_id=review_id)


# ---------- M186 · 评审历史（Review 面板「历史」列表/详情） ----------

class ReviewHistoryEntry(BaseModel):
    id: str
    ts: str
    project: str
    model: str
    files_reviewed: int
    findings_count: int


class ReviewsHistoryResponse(BaseModel):
    reviews: list[ReviewHistoryEntry]


class ReviewRecord(BaseModel):
    id: str
    ts: str
    project: str
    model: str
    files_reviewed: int
    findings_count: int
    findings: list[ReviewFinding]


@app.get(f"{API_PREFIX}/project/reviews", response_model=ReviewsHistoryResponse)
async def project_reviews_history() -> ReviewsHistoryResponse:
    """评审历史列表（ts desc，摘要无 findings）。无活动项目 → 空列表（不 400）。"""
    if os.environ.get("FLIPPED_AI_REVIEW", "1") == "0":
        raise HTTPException(status_code=404, detail="AI 评审功能已禁用")
    proj = ps.active_project()
    if proj is None:
        return ReviewsHistoryResponse(reviews=[])
    from .review_store import list_reviews
    return ReviewsHistoryResponse(
        reviews=[ReviewHistoryEntry(**e)
                 for e in list_reviews(_reviews_dir_migrated(proj["name"]), proj["name"])])


@app.get(f"{API_PREFIX}/project/reviews/{{review_id}}", response_model=ReviewRecord)
async def project_review_detail(review_id: str) -> ReviewRecord:
    """单条评审完整记录（含 findings）。非法 id/未命中/无活动项目 → 404。"""
    if os.environ.get("FLIPPED_AI_REVIEW", "1") == "0":
        raise HTTPException(status_code=404, detail="AI 评审功能已禁用")
    proj = ps.active_project()
    if proj is None:
        raise HTTPException(status_code=404, detail="评审记录不存在")
    from .review_store import load_review
    rec = load_review(_reviews_dir_migrated(proj["name"]), proj["name"], review_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="评审记录不存在")
    return ReviewRecord(**rec)


# ---------- M186 · AI commit message 草稿（Review 面板「生成提交信息」） ----------

class CommitMessageResponse(BaseModel):
    message: str
    model: str
    files_count: int
    note: str | None = None


@app.post(f"{API_PREFIX}/project/commit_message", response_model=CommitMessageResponse)
async def project_commit_message(req: ReviewRequest) -> CommitMessageResponse:
    """AI commit message 草稿：工作区 git diff → LLM → conventional commit 文本（不落盘）。"""
    if os.environ.get("FLIPPED_AI_REVIEW", "1") == "0":
        raise HTTPException(status_code=404, detail="AI 评审功能已禁用")
    root = ps.project_root()
    if root is None:
        raise HTTPException(status_code=400, detail="未选择项目")
    import subprocess

    from driving.model_router import resolve_worker_model_config

    from .review import (COMMIT_SYSTEM_PROMPT, ReviewParseError,
                         build_commit_prompt, parse_commit_reply)

    base_url, model = resolve_worker_model_config(req.model or "coder")
    try:
        out = await asyncio.to_thread(
            subprocess.run,
            ["git", "diff", "HEAD", "--no-color"],
            cwd=str(root), capture_output=True, text=True, timeout=6,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise HTTPException(status_code=500, detail=f"git diff 失败: {e}")
    files = _parse_unified_diff(out.stdout) if out.returncode == 0 else []
    files += await asyncio.to_thread(_untracked_entries, root)
    if not files:
        return CommitMessageResponse(message="", model=model, files_count=0,
                                     note="工作区干净")
    prompt = build_commit_prompt(files)
    try:
        reply, _usage = await _llm_chat(base_url, model, COMMIT_SYSTEM_PROMPT, prompt)
        message = parse_commit_reply(reply)
    except ReviewParseError as e:
        raise HTTPException(status_code=502, detail=f"提交信息解析失败: {e}")
    except Exception as e:  # noqa: BLE001 LLM 调用任何失败 → 502，绝不返回伪造 message
        raise HTTPException(status_code=502, detail=f"提交信息模型调用失败: {e}")
    return CommitMessageResponse(message=message, model=model, files_count=len(files))


# ---------- M180 · 项目规则系统（规则面板查看/编辑；chat/plan 注入见 _run_chat） ----------

class RulesResponse(BaseModel):
    files: list[str]
    markdown: str
    total_chars: int
    rules_content: str
    needs_project: bool = False


class RulesPutRequest(BaseModel):
    content: str = Field(max_length=65536)


def _rules_payload(root: Path) -> RulesResponse:
    """load_project_rules + rules_raw_content 组装响应（needs_project=False）。"""
    from api.rules import load_project_rules, rules_raw_content
    rules = load_project_rules(root)
    return RulesResponse(
        files=rules.files, markdown=rules.markdown, total_chars=rules.total_chars,
        rules_content=rules_raw_content(root), needs_project=False)


@app.get(f"{API_PREFIX}/project/rules", response_model=RulesResponse)
async def project_rules_get() -> RulesResponse:
    """活动项目的规则文档（多文件拼接 markdown + .flipped/rules.md 原文）。无项目 → needs_project。"""
    root = ps.project_root()
    if root is None:
        return RulesResponse(files=[], markdown="", total_chars=0,
                             rules_content="", needs_project=True)
    return _rules_payload(root)


@app.put(f"{API_PREFIX}/project/rules", response_model=RulesResponse)
async def project_rules_put(req: RulesPutRequest) -> RulesResponse:
    """写 .flipped/rules.md（固定相对路径，原子写）后重载返回。无项目 → 400。"""
    root = ps.project_root()
    if root is None:
        raise HTTPException(status_code=400, detail="未选择项目")
    from api.rules import write_project_rules
    write_project_rules(root, req.content)
    return _rules_payload(root)


@app.get(f"{API_PREFIX}/project/verify")
async def project_verify() -> dict[str, Any]:
    """探测活动项目的验收命令(自主模式据此自我验证)。无项目 → detected=False。"""
    from driving.verify_detect import detect_verify_command

    root = ps.project_root()
    if root is None:
        return {"command": ["true"], "label": "(未选择项目)", "source": "none",
                "confidence": "none", "detected": False}
    plan = detect_verify_command(root)
    return {"command": plan.command, "label": plan.label, "source": plan.source,
            "confidence": plan.confidence, "detected": plan.detected}


@app.get(f"{API_PREFIX}/project/file")
async def project_file(path: str = Query(..., min_length=1)) -> dict[str, Any]:
    """读取项目内单个文本文件（点击文件树 → 载入编辑器）。含路径穿越防护。"""
    root = ps.project_root()
    if root is None:
        raise HTTPException(status_code=400, detail="未选择项目")
    root = root.resolve()
    target = (root / path).resolve()
    # 路径穿越防护：必须落在仓库根内
    if target != root and not str(target).startswith(str(root) + os.sep):
        raise HTTPException(status_code=403, detail="path outside project")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not a file")
    if target.stat().st_size > _FILE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="file too large")
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise HTTPException(status_code=415, detail="binary or unreadable file")
    return {"path": path, "content": content}


# ---------- M173 · 项目结构地图（全局概览面板；chat/plan 注入见 _run_chat） ----------

def _project_map_payload(m: Any) -> dict[str, Any]:
    """ProjectMap → 前端契约形状（五字段）。"""
    return {
        "markdown": m.markdown,
        "generated_at": m.generated_at,
        "stale": m.stale,
        "from_cache": m.from_cache,
        "stack": m.stack,
    }


@app.get(f"{API_PREFIX}/project/map", response_model=ProjectMapResponse)
async def project_map() -> dict[str, Any]:
    """活动项目的结构地图（带缓存）。无项目 → needs_project；生成失败 500 明示。"""
    root = ps.project_root()
    if root is None:
        return {"map": None, "needs_project": True}
    try:
        from api.project_map import get_project_map
        m = get_project_map(root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"项目地图生成失败: {e}")
    return {"map": _project_map_payload(m), "needs_project": False}


@app.post(f"{API_PREFIX}/project/map/regenerate", response_model=ProjectMapResponse)
async def project_map_regenerate() -> dict[str, Any]:
    """强制重建项目结构地图（绕过缓存）。无项目 → needs_project；重建失败 500 明示。"""
    root = ps.project_root()
    if root is None:
        return {"map": None, "needs_project": True}
    try:
        from api.project_map import regenerate_project_map
        m = regenerate_project_map(root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"项目地图重建失败: {e}")
    return {"map": _project_map_payload(m), "needs_project": False}


# ---------- 浏览器真内核渲染（阶段②b — 右侧「浏览器」实时看效果 + 选中元素追踪） ----------

@app.post(f"{API_PREFIX}/browser/render")
async def browser_render(req: BrowserRenderRequest) -> dict[str, Any]:
    """用真 Chromium 渲染 URL，返回截图 + 可点击 DOM 元素框。"""
    url = req.url.strip()
    if url.startswith(("localhost", "127.0.0.1", "0.0.0.0", "[::1]")):
        url = "http://" + url
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="仅支持 http/https URL")
    from api.browser import render_page
    try:
        return await render_page(url)
    except Exception as e:  # 渲染失败（超时/DNS/崩溃）→ 502 携带原因
        raise HTTPException(status_code=502, detail=f"渲染失败: {type(e).__name__}: {e}")


# ---------- 会话管理 ----------

@app.post(f"{API_PREFIX}/sessions", response_model=Session)
async def create_session(title: str = "新任务", mode: str = "agent") -> Session:
    # 捕获当前活动项目 → 会话绑定该项目(切回会话时项目跟着切)
    proj = ps.active_project()
    session = store.create(
        title=title, mode=mode,
        project=proj["host"] if proj else None,
        project_name=proj["name"] if proj else None,
    )
    bus.emit(session.id, EventType.status, Role.system,
             {"status": session.status, "progress": 0, "note": "会话已创建"})
    return session


@app.get(f"{API_PREFIX}/sessions", response_model=list[Session])
async def list_sessions() -> list[Session]:
    return store.list()


@app.get(f"{API_PREFIX}/sessions/{{session_id}}", response_model=Session)
async def get_session(session_id: str) -> Session:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.delete(f"{API_PREFIX}/sessions/{{session_id}}")
async def delete_session(session_id: str) -> dict:
    """删除会话及其事件;若正在运行先取消其任务。"""
    if not store.get(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    task = RUNNING_TASKS.pop(session_id, None)
    if task and not task.done():
        task.cancel()
    store.delete(session_id)
    return {"ok": True, "id": session_id}


@app.get(f"{API_PREFIX}/sessions/{{session_id}}/events", response_model=list[Event])
async def get_events(session_id: str, after_id: str | None = Query(None)) -> list[Event]:
    """REST 事件历史(回放/调试用),WebSocket 之外的兜底。"""
    if not store.get(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return store.events(session_id, after_id)


@app.post(f"{API_PREFIX}/sessions/{{session_id}}/cancel", response_model=Session)
async def cancel_session(session_id: str) -> Session:
    """取消会话运行中的任务:cancel asyncio 任务 + 状态回 idle + emit。"""
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    task = RUNNING_TASKS.pop(session_id, None)
    if task and not task.done():
        task.cancel()
    updated = store.update_status(session_id, SessionStatus.idle)
    bus.emit(session_id, EventType.status, Role.system,
             {"status": "idle", "progress": 0, "note": "任务已取消"})
    return updated


# ---------- 任务派发 ----------

def _select_runner(mode: str, has_orchestrator: bool, mock: bool) -> str:
    """据 mode/上下文选执行器(纯函数,可测)。

    - auto(F3 一等自主模式)或显式 orchestrator 配置 → 完整多 Agent 监督循环
    - chat/plan → 直连模型对话/规划,不启沙盒
    - 其余(agent) → 单次 OpenHands 沙盒执行(mock 时走事件流模拟)
    """
    if mode == "auto" or has_orchestrator:
        return "orchestrator"
    if mode in ("chat", "plan"):
        return "chat"
    return "mock" if mock else "openhands"


@app.post(f"{API_PREFIX}/sessions/{{session_id}}/tasks", response_model=TaskResponse)
async def create_task(session_id: str, req: TaskRequest) -> TaskResponse:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    # 并发守卫：同一会话已有未完成任务时拒绝重复派发（否则旧任务句柄丢失、无法取消）
    existing = RUNNING_TASKS.get(session_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="session already has a running task")
    # task_id 加 uuid 后缀：避免同秒重复派发撞名
    task_id = f"task-{datetime.now(timezone.utc).strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
    store.update_status(session_id, SessionStatus.running)
    bus.emit(session_id, EventType.status, Role.system,
             {"status": "running", "progress": 0, "note": f"任务 {task_id} 已派发"})
    mode = req.context.get("mode", "agent")
    runner = _select_runner(mode, bool(req.context.get("orchestrator")), MOCK_WORKER)
    if runner == "orchestrator":
        t = asyncio.create_task(_run_orchestrator(session_id, task_id, req))
    elif runner == "chat":
        # 对话/规划模式：直连本地模型，不启动沙盒
        chat_kw: dict[str, Any] = {}
        if "rag_auto" in req.context:  # M172：请求显式携带才覆盖，缺省走 _run_chat 默认 rag_auto=True
            chat_kw["rag_auto"] = req.context["rag_auto"]
        if "map_auto" in req.context:  # M173：同款，请求显式携带才覆盖，缺省走默认 map_auto=True
            chat_kw["map_auto"] = req.context["map_auto"]
        if "rules_auto" in req.context:  # M180：同款，请求显式携带才覆盖，缺省走默认 rules_auto=True
            chat_kw["rules_auto"] = req.context["rules_auto"]
        t = asyncio.create_task(
            _run_chat(session_id, task_id, req.description, req.context.get("model", "coder"), mode,
                      **chat_kw)
        )
    elif runner == "mock":
        t = asyncio.create_task(_mock_run(session_id, task_id, req.description))
    else:
        t = asyncio.create_task(_run_openhands(session_id, task_id, req.description, req.context.get("model", "coder")))
    RUNNING_TASKS[session_id] = t
    t.add_done_callback(lambda _t, sid=session_id: RUNNING_TASKS.pop(sid, None))
    return TaskResponse(task_id=task_id, session_id=session_id, status="running")


@app.post(f"{API_PREFIX}/sessions/{{session_id}}/resume", response_model=Session)
async def resume_session(session_id: str) -> Session:
    """从持久化的 LangGraph checkpoint 恢复并继续运行 orchestrator 会话。"""
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    if not session.checkpoint_db_path:
        raise HTTPException(status_code=400, detail="session has no checkpoint_db_path")
    # 并发守卫：已在运行则拒绝重复恢复（防双 orchestrator 写同一 checkpoint）
    existing = RUNNING_TASKS.get(session_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="session already has a running task")
    t = asyncio.create_task(_resume_orchestrator(session))
    RUNNING_TASKS[session_id] = t
    t.add_done_callback(lambda _t, sid=session_id: RUNNING_TASKS.pop(sid, None))
    return session


# ---------- WebSocket 事件流 ----------

@app.websocket(f"{API_PREFIX}/sessions/{{session_id}}/events")
async def events_ws(websocket: WebSocket, session_id: str,
                    last_event_id: str | None = Query(None)):
    await bus.connect(session_id, websocket)
    try:
        # 重连回放
        if store.get(session_id):
            await bus.replay(session_id, websocket, last_event_id)
        # 保持连接，接收客户端 ack / pong / approval 结果
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(code=message.get("code", 1000))
            raw = message.get("text")
            if raw is None:  # 二进制帧：忽略，保持连接
                continue
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue  # 非 JSON 文本帧：忽略，不许崩掉事件循环
            if not isinstance(data, dict):
                continue
            if data.get("type") == "ack":
                await websocket.send_json({"type": "ack_ok", "last_event_id": data.get("last_event_id")})
                continue
            await _handle_client_message(session_id, data)
    except WebSocketDisconnect:
        await bus.disconnect(session_id, websocket)
    except Exception:
        await bus.disconnect(session_id, websocket)


def _mock_orchestrator_fns():
    """Deterministic orchestrator nodes for API recovery tests."""
    verify_count = [0]

    def supervisor(state):
        count = len([h for h in state.get("history", []) if h.get("step") == "supervisor"])
        return {
            "current_subtask": f"sub{count}",
            "believe_done": count == 1,
            "history": state.get("history", []) + [{"step": "supervisor"}],
        }

    def worker(state):
        return {
            "last_obs": {"summary": {"tool_calls": 1}},
            "signatures": state.get("signatures", []) + ["mock"],
            "history": state.get("history", []) + [{"step": "worker"}],
            "worker_error": False,
        }

    def overseer(state):
        return {
            "verdict": {"action": "continue"},
            "history": state.get("history", []) + [{"step": "overseer"}],
        }

    def verifier(cmd, cwd):
        verify_count[0] += 1
        return verify_count[0] == 2, ("fail" if verify_count[0] == 1 else "ok")

    return supervisor, worker, overseer, verifier


def _resolve_verify_cmd(cfg: dict[str, Any], host_root: Path | None) -> list[str]:
    """自主模式验收命令:显式指定优先;否则据 host 项目根探测(F1c)。

    显式的 ["true"] 视作"未指定"→ 交给探测(它才是要替换掉的空转占位)。
    """
    explicit = cfg.get("verify_cmd")
    if explicit and explicit != ["true"]:
        return list(explicit)
    if host_root is not None:
        from driving.verify_detect import detect_verify_command
        return detect_verify_command(host_root).command
    return ["true"]


def _gather_project_context(cfg: dict[str, Any]) -> tuple[list[str], str, str]:
    """同步读活动项目的 验收命令(F1c)/规则(F6)/结构地图(F5)。

    这些是阻塞文件 IO(glob/读多个规则文件/iterdir),必须经 asyncio.to_thread 调用,
    否则跑在事件循环线程上会卡住整个进程的其它会话广播/请求。
    """
    from driving.project_rules import read_project_rules
    from driving.repo_map import build_repo_map

    root = ps.project_root()
    return (_resolve_verify_cmd(cfg, root), read_project_rules(root), build_repo_map(root))


def _build_real_nodes(session_id: str, cwd: str, verify_cmd: list[str]) -> dict[str, Any]:
    """构建真实执行路径的 orchestrator 节点:沙盒 verifier(有真实命令时)+ F2/F4 事件流。

    首跑与 resume 共用,保证恢复的运行同样可见(不退回 NullEventBus 黑盒)。
    """
    from driving.orchestrator import _safe_default_verifier

    # F1d — 有真实命令时在沙盒内验收(cwd=沙盒路径天然成立)。
    # M89 修复:['true'](无验收命令)时用 no-op,避免 host verifier 在沙盒路径
    # cwd(/projects/X,host 上不存在)上 subprocess.run 触发 FileNotFoundError。
    def _noop_verifier(_cmd: list, _cwd: str) -> "tuple[bool, str]":
        return True, "(skip) 无验收命令"
    base_verifier = _noop_verifier
    if verify_cmd != ["true"]:
        from executor.sandbox_verify import make_sandbox_verifier
        from executor.openhands_worker import OpenHandsWorker
        base_verifier = make_sandbox_verifier(
            agent_host=os.environ.get("OPENHANDS_AGENT_HOST", "http://localhost:8000"),
            working_dir=cwd,
            api_key=OpenHandsWorker._default_agent_api_key(),
        )
    # F2/F4 — 每步实时推 WS 事件 + 计划清单
    from api.orchestrator_stream import build_streaming_nodes
    return build_streaming_nodes(bus, session_id, base_verifier)


async def _run_orchestrator(session_id: str, task_id: str, req: TaskRequest) -> None:
    """在后台线程运行 orchestrator，并持久化 checkpoint。"""
    from driving.orchestrator import drive_orchestrated

    # orchestrator 字段可能是 bool(true/false,用于 _select_runner 判断)或 dict(详细配置)。
    # 仅当为 dict 时当作配置,否则用空 dict 走默认值。修复 'bool' object has no attribute 'get'。
    _raw_orch = req.context.get("orchestrator")
    cfg = _raw_orch if isinstance(_raw_orch, dict) else {}
    goal = req.description
    # agent 工作目录 = 活动项目在沙盒里的路径(/projects/<名>);无项目回退 /workspace
    cwd = cfg.get("cwd") or ps.sandbox_cwd()
    # F1c/F5/F6 — 项目上下文读取(阻塞 IO)放进线程,避免卡事件循环
    verify_cmd, project_rules, repo_map = await asyncio.to_thread(_gather_project_context, cfg)
    db_path = FLIPPED_CHECKPOINT_DB
    # F8 真机实测抓到的缺陷:SqliteSaver 不自动建父目录 → "unable to open database file"
    Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    store.update(session_id, goal=goal, verify_cmd=verify_cmd, cwd=cwd, checkpoint_db_path=db_path)

    # M151.2：审批门 interrupt 前发 approval_request 事件，让前端/TUI 即时弹审批卡。
    # 闭包捕 session_id + bus，在 drive_orchestrated 的工作线程内被 approval_gate 调用。
    def _on_approval_request(state):
        subtask = state.get("current_subtask", "")
        bus.emit(session_id, EventType.approval_request, Role.system,
                 {"action": subtask, "reason": "高风险子任务，需人工放行（§7 沙箱外要审批）"})
        # 同步把会话置 paused，让 approve 端点的 pending 守卫可识别（interrupt 后
        # drive_orchestrated 返回，_run_orchestrated 会再置 review；paused 仅在窗口期内有效）
        store.update_status(session_id, SessionStatus.paused)

    try:
        if os.environ.get("FLIPPED_MOCK_ORCHESTRATOR"):
            sup, work, over, ver = _mock_orchestrator_fns()
            final = await asyncio.to_thread(
                drive_orchestrated,
                goal=goal, cwd=cwd, verify_cmd=verify_cmd,
                project_rules=project_rules, repo_map=repo_map,
                thread_id=session_id, db_path=db_path,
                require_approval=cfg.get("require_approval", False),
                max_iterations=cfg.get("max_iterations", 30),
                supervisor=sup, worker=work, overseer=over, verifier=ver,
                on_approval_request=_on_approval_request,
            )
        else:
            nodes = _build_real_nodes(session_id, cwd, verify_cmd)
            final = await asyncio.to_thread(
                drive_orchestrated,
                goal=goal, cwd=cwd, verify_cmd=verify_cmd,
                project_rules=project_rules, repo_map=repo_map,
                thread_id=session_id, db_path=db_path,
                require_approval=cfg.get("require_approval", False),
                max_iterations=cfg.get("max_iterations", 30),
                on_approval_request=_on_approval_request,
                **nodes,
            )
        if final.get("verified"):
            # F7 交付步:验收通过 → 沙盒内自动提交成果(真实项目 + 非 mock + 未禁用)
            if (not os.environ.get("FLIPPED_MOCK_ORCHESTRATOR")
                    and ps.active_project() and cfg.get("auto_commit", True)):
                await _deliver(session_id, goal, cwd)
            store.update_status(session_id, SessionStatus.done)
        elif final.get("stop_reason") in ("worker_error", "overseer_abort", "loop_detected", "circuit_breaker"):
            store.update_status(session_id, SessionStatus.error)
        else:
            store.update_status(session_id, SessionStatus.review)
    except Exception as exc:
        store.update_status(session_id, SessionStatus.error)
        bus.emit(session_id, EventType.error, Role.system,
                 {"message": f"Orchestrator failed: {exc}"})


async def _deliver(session_id: str, goal: str, cwd: str) -> None:
    """交付步:在沙盒内提交验收通过的成果,并 emit 可见交付事件(F7)。

    **绝不抛异常**——交付是尽力而为,任何失败(读 key/连沙盒/emit)都不该翻转已通过的验收。
    """
    try:
        from executor.sandbox_deliver import make_sandbox_deliver
        from executor.openhands_worker import OpenHandsWorker

        deliver = make_sandbox_deliver(
            agent_host=os.environ.get("OPENHANDS_AGENT_HOST", "http://localhost:8000"),
            working_dir=cwd,
            api_key=OpenHandsWorker._default_agent_api_key(),
        )
        result = await asyncio.to_thread(deliver, goal)
        if result.get("committed"):
            subject = result["message"].splitlines()[0]
            bus.emit(session_id, EventType.message, Role.worker,
                     {"text": f"📦 已交付 · git commit\n{subject}", "source": "deliver"})
        elif result.get("nochange"):
            bus.emit(session_id, EventType.message, Role.worker,
                     {"text": "📦 无文件变更,跳过提交。", "source": "deliver"})
        else:
            bus.emit(session_id, EventType.message, Role.worker,
                     {"text": f"⚠️ 交付未提交:\n{result.get('output', '')[-400:]}", "source": "deliver"})
    except Exception as exc:  # noqa: BLE001 交付尽力而为,失败绝不翻转已通过的验收
        try:
            bus.emit(session_id, EventType.message, Role.worker,
                     {"text": f"⚠️ 交付步异常,成果仍在工作区: {exc}", "source": "deliver"})
        except Exception:
            pass


async def _resume_orchestrator(session: Session) -> None:
    """从 checkpoint 恢复一个 orchestrator 会话(与首跑一致:接 F2/F4 事件流 + F7 交付)。"""
    from driving.orchestrator import resume_orchestrated

    bus.emit(session.id, EventType.status, Role.system,
             {"status": "running", "progress": 0, "note": "从 checkpoint 恢复继续执行"})
    try:
        if os.environ.get("FLIPPED_MOCK_ORCHESTRATOR"):
            sup, work, over, ver = _mock_orchestrator_fns()
            final = await asyncio.to_thread(
                resume_orchestrated,
                session.id,
                session.checkpoint_db_path,
                supervisor=sup, worker=work, overseer=over, verifier=ver,
            )
        else:
            # 恢复也接实时事件流/计划清单(不退回黑盒)
            nodes = _build_real_nodes(session.id, session.cwd, session.verify_cmd or ["true"])
            final = await asyncio.to_thread(
                resume_orchestrated,
                session.id,
                session.checkpoint_db_path,
                **nodes,
            )
        if final is None:
            store.update_status(session.id, SessionStatus.error)
            bus.emit(session.id, EventType.error, Role.system,
                     {"message": "没有找到 checkpoint"})
            return
        if final.get("verified"):
            # F7 恢复后若验收通过也交付(真实项目 + 非 mock)
            if (not os.environ.get("FLIPPED_MOCK_ORCHESTRATOR")
                    and session.cwd and session.cwd != "/workspace"):
                await _deliver(session.id, session.goal or "", session.cwd)
            store.update_status(session.id, SessionStatus.done)
        elif final.get("done"):
            store.update_status(session.id, SessionStatus.error)
        else:
            store.update_status(session.id, SessionStatus.running)
    except Exception as exc:
        store.update_status(session.id, SessionStatus.error)
        bus.emit(session.id, EventType.error, Role.system,
                 {"message": f"Resume failed: {exc}"})


async def _run_openhands(session_id: str, task_id: str, description: str, model_alias: str = "coder") -> None:
    """在后台线程运行 OpenHands Worker，避免阻塞 FastAPI 主循环。

    模型端点经 model_router 自动选择(M6.6):LiteLLM proxy 健康走 proxy，
    否则回退 exo 直连(FLIPPED_MODEL_BASE_URL / 默认 exo)。
    """
    from executor.openhands_worker import OpenHandsWorker
    from driving.model_router import resolve_worker_model_config
    from api.mcp_registry import enabled_mcp_config

    base_url, model = resolve_worker_model_config(model_alias)
    worker = OpenHandsWorker(
        session_id=session_id,
        task_id=task_id,
        bus=bus,
        agent_host=os.environ.get("OPENHANDS_AGENT_HOST", "http://localhost:8000"),
        # agent 工作目录 = 活动项目沙盒路径(/projects/<名>);无项目回退 /workspace
        working_dir=os.environ.get("OPENHANDS_WORKING_DIR") or ps.sandbox_cwd(),
        model_alias=model,
        base_url=base_url,
        mcp_config=enabled_mcp_config(),
    )
    try:
        await asyncio.to_thread(worker.run, description)
    except Exception as exc:
        bus.emit(session_id, EventType.error, Role.system,
                 {"message": f"OpenHands Worker 失败: {exc}"})
        store.update_status(session_id, SessionStatus.error)


CHAT_SYSTEM = (
    "你是 flipped 的对话助手。用简洁中文回答用户的问题；涉及代码时给出可直接运行的片段。"
    "你只负责对话，不执行任何操作、不修改文件。"
)
PLAN_SYSTEM = (
    "你是 flipped 的规划助手。把用户目标拆解为可执行的有序步骤，每一步给出【要做什么】与【如何验证】。"
    "用 markdown 有序列表输出，聚焦计划本身，不要编写实现代码、不要执行任何操作。"
)


async def _llm_chat(base_url: str, model: str, system: str, user: str | list[dict],
                    timeout: float = 120.0) -> tuple[str, dict | None]:
    """直连 OpenAI 兼容端点做一次非流式对话补全。

    M169：返回 (content, usage)；usage 取响应 usage 字段（dict 含
    prompt_tokens/completion_tokens），缺失时 None。
    M192：user 支持多模态 parts 数组（list 原样进 messages payload 的 user content）。
    """
    url = base_url.rstrip("/") + "/chat/completions"
    api_key = os.environ.get("EXO_API_KEY") or os.environ.get("OPENAI_API_KEY") or "dummy"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"], data.get("usage")


async def _llm_chat_stream(base_url: str, model: str, system: str, user: str | list[dict],
                           timeout: float = 120.0, usage_box: dict | None = None):
    """直连 OpenAI 兼容端点做流式对话补全（SSE），逐 chunk yield 文本增量（M166）。

    建流阶段（连接失败/非 200/请求本身）与迭代中途（断流）的异常都抛给调用方：
    _run_chat 用「是否已产出 chunk」区分静默 fallback（建流失败）与断流清态（中途失败）。

    M169：payload 带 stream_options.include_usage；末尾 choices=[] 的 usage 汇总
    chunk 不 yield，写入 usage_box["usage"]（调用方传 dict 时）。
    M192：user 支持多模态 parts 数组（list 原样进 messages payload 的 user content）。
    """
    url = base_url.rstrip("/") + "/chat/completions"
    api_key = os.environ.get("EXO_API_KEY") or os.environ.get("OPENAI_API_KEY") or "dummy"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload,
                                 headers={"Authorization": f"Bearer {api_key}"}) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if not data:
                    continue
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue  # 坏行跳过，不中断流
                choices = chunk.get("choices") or []
                if not choices:
                    # M169：usage 汇总 chunk（choices 为空）→ 写 usage_box，不当文本产出
                    if usage_box is not None and isinstance(chunk.get("usage"), dict):
                        usage_box["usage"] = chunk["usage"]
                    continue
                content = (choices[0].get("delta") or {}).get("content")
                if content:
                    yield content


async def _run_chat(session_id: str, task_id: str, description: str, model_alias: str, mode: str,
                    *, rag_auto: bool = True, map_auto: bool = True, rules_auto: bool = True,
                    attachments: list[dict] | None = None) -> None:
    """对话/规划模式：直连本地模型返回文本，不启动沙盒、不用工具。

    M166：默认 token 级流式（FLIPPED_CHAT_STREAM=0 关闭）。
    - 正常序列：token{text, seq:1..N, done:false}* → token{text:"", done:true} → 既有 message 落盘；
    - 建流失败（未产出任何 chunk 即异常）→ 静默 fallback 非流式 _llm_chat，无 token 事件；
    - 中途断流（已产出 chunk 后异常）→ token done=true 清前端流式态，再走既有 error 分支。

    M192：attachments 非空 → vision 路由（resolve_vision_model_config）取 (base_url, model)；
    逐张按 payload.path 读盘组装多模态 parts（text + image_url data URL）。
    读盘失败单张跳过（fail-open，对齐 refs 哲学）；全部失败 → 纯 str 发送（降级不炸）。
    attachments 为空：现状 str 路径零变化。
    """
    from driving.model_router import resolve_worker_model_config

    if attachments:
        from driving.model_router import resolve_vision_model_config
        base_url, model = resolve_vision_model_config()
    else:
        base_url, model = resolve_worker_model_config(model_alias)
    system = PLAN_SYSTEM if mode == "plan" else CHAT_SYSTEM
    # M172：chat/plan 自动注入 RAG 上下文（FLIPPED_RAG_AUTO=0 或请求级 rag_auto=False 关闭）。
    # 全程 fail-open：RAG 任何故障都不让对话失败。
    rag_ctx, rag_k = "", 0
    if mode in ("chat", "plan") and rag_auto and os.environ.get("FLIPPED_RAG_AUTO", "1") != "0":
        try:
            from api.rag_context import build_rag_context
            sess = store.get(session_id)
            # M197.2（消化 L-M172-3）：Chroma 查询走 SQLite/文件 IO，to_thread 不阻塞 event loop
            rag_ctx, rag_k = await asyncio.to_thread(
                build_rag_context, description,
                project=getattr(sess, "project_name", None))
        except Exception:  # noqa: BLE001 fail-open：注入失败=无注入
            if os.environ.get("FLIPPED_RAG_DEBUG") == "1":  # 临时诊断
                import traceback
                traceback.print_exc()
            rag_ctx, rag_k = "", 0
    if rag_ctx:
        system = system + "\n\n" + rag_ctx
    # M173：chat/plan 自动注入项目结构地图（FLIPPED_MAP_AUTO=0 或请求级 map_auto=False 关闭）。
    # 全程 fail-open：地图任何故障都不让对话失败。
    map_injected = False
    if mode in ("chat", "plan") and map_auto and os.environ.get("FLIPPED_MAP_AUTO", "1") != "0":
        try:
            from api.project_map import get_project_map, MAP_INJECT_HEADER
            root = ps.project_root()
            if root is not None:
                m = get_project_map(root, max_chars=1600)
                if m.markdown:
                    system += "\n\n" + MAP_INJECT_HEADER + "\n" + m.markdown
                    map_injected = True
        except Exception:  # noqa: BLE001 fail-open：注入失败=无注入
            pass
    # M180：chat/plan 自动注入项目规则（FLIPPED_RULES_AUTO=0 或请求级 rules_auto=False 关闭）。
    # 全程 fail-open：规则装载任何故障都不让对话失败；空规则零注入。
    if mode in ("chat", "plan") and rules_auto and os.environ.get("FLIPPED_RULES_AUTO", "1") != "0":
        try:
            from api.rules import RULES_INJECT_HEADER, load_project_rules
            rules = load_project_rules(ps.project_root())
            if rules.markdown:
                system += "\n\n" + RULES_INJECT_HEADER + "\n" + rules.markdown
        except Exception:  # noqa: BLE001 fail-open：注入失败=无注入
            pass
    # M185.1：chat/plan 注入 scope="all" 的 worker 规则（FLIPPED_WORKER_RULES_CHAT=0 关闭）。
    # worker-only 规则不进对话（工程约束面向执行者）；全程 fail-open。
    worker_rules_injected = False
    if mode in ("chat", "plan") and os.environ.get("FLIPPED_WORKER_RULES_CHAT", "1") != "0":
        try:
            from driving.worker_rules import (
                WORKER_RULES_CHAT_HEADER as _WR_CHAT_HEADER,
                WorkerRuleStore as _WRStoreChat,
                build_worker_rules_text as _build_wr_text,
                chat_rules_max_chars as _chat_rules_max_chars,
            )
            _wr_store = _WRStoreChat(Path(
                os.environ.get("FLIPPED_WORKER_RULES_PATH", "data/worker_rules.json")))
            # M194.2：chat 通路预算读 FLIPPED_CHAT_RULES_MAX_CHARS
            # （缺省回落 FLIPPED_WORKER_RULES_MAX_CHARS 解析值，双缺省 300）
            _wr_text, _ = _build_wr_text(_wr_store.list(), scopes=("all",),
                                         max_chars=_chat_rules_max_chars())
            if _wr_text:
                system += "\n\n" + _WR_CHAT_HEADER + "\n" + _wr_text
                worker_rules_injected = True
        except Exception:  # noqa: BLE001 fail-open：注入失败=无注入
            pass
    note = "规划" if mode == "plan" else "对话"
    bus.emit(session_id, EventType.status, Role.system,
             {"status": "running", "progress": 20, "note": f"{note}中（{model_alias}）"})

    # M192：附件读盘组装多模态 parts；单张失败跳过（fail-open），全部失败降级纯 str
    user_content: str | list[dict] = description
    if attachments:
        import base64 as _b64  # 局部 import：仅多模态分支使用，不动顶部 import 行
        from api.assistant import attachments_dir
        parts: list[dict] = [{"type": "text", "text": description}]
        for att in attachments:
            try:
                raw = (attachments_dir() / str(att.get("path", ""))).read_bytes()
                mt = att.get("media_type") or "image/png"
                parts.append({"type": "image_url",
                              "image_url": {"url": f"data:{mt};base64,{_b64.b64encode(raw).decode('ascii')}"}})
            except Exception:  # noqa: BLE001 fail-open：单张读盘失败跳过
                continue
        if len(parts) > 1:
            user_content = parts

    def _done_token(seq: int) -> None:
        bus.emit_transient(session_id, EventType.token, Role.worker,
                           {"text": "", "seq": seq, "done": True})

    try:
        usage: dict | None = None
        if os.environ.get("FLIPPED_CHAT_STREAM", "1") != "0":
            chunks: list[str] = []
            seq = 0
            usage_box: dict = {}
            try:
                async for chunk in _llm_chat_stream(base_url, model, system, user_content,
                                                    usage_box=usage_box):
                    seq += 1
                    chunks.append(chunk)
                    bus.emit_transient(session_id, EventType.token, Role.worker,
                                       {"text": chunk, "seq": seq, "done": False})
            except Exception:
                if chunks:
                    # 中途断流：清前端流式态后交既有 error 分支
                    _done_token(seq + 1)
                    raise
                # 建流失败：静默 fallback 非流式（无 token 事件，行为=现状）
                reply, usage = await _llm_chat(base_url, model, system, user_content)
            else:
                _done_token(seq + 1)
                reply = "".join(chunks)
                usage = usage_box.get("usage")
        else:
            reply, usage = await _llm_chat(base_url, model, system, user_content)
        payload: dict[str, Any] = {"text": reply, "source": "agent"}
        if rag_k > 0:  # M172：仅命中 RAG 时附带 chunk 数，k==0 保持现状形状
            payload["rag_chunks"] = rag_k
        if map_injected:  # M173：仅实际注入地图时附带标记，未注入保持现状形状
            payload["map_injected"] = True
        if worker_rules_injected:  # M185.1：仅实际注入 worker 规则（scope=all）时附带标记
            payload["worker_rules_injected"] = True
        bus.emit(session_id, EventType.message, Role.worker, payload)
        # M169：per-turn token 用量事件（落盘，history 折叠进 assistant turn）+
        # 补全局计数漏 chat/plan 的缺口；统计失败不影响主流程
        if usage:
            bus.emit(session_id, EventType.usage, Role.worker, {
                "prompt": int(usage.get("prompt_tokens", 0) or 0),
                "completion": int(usage.get("completion_tokens", 0) or 0),
                "calls": 1, "source": mode})
            try:
                COLLECTOR.record_usage(
                    prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                    completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                    calls=1)
            except Exception:  # noqa: BLE001 统计失败不影响主流程
                pass
        bus.emit(session_id, EventType.status, Role.system,
                 {"status": "done", "progress": 100, "note": f"{note}完成"})
        store.update_status(session_id, SessionStatus.done)
    except Exception as exc:
        bus.emit(session_id, EventType.error, Role.system, {"message": f"{note}失败: {exc}"})
        bus.emit(session_id, EventType.status, Role.system,
                 {"status": "error", "progress": 100, "note": str(exc)})
        store.update_status(session_id, SessionStatus.error)


async def _handle_client_message(session_id: str, data: dict[str, Any]) -> None:
    msg_type = data.get("type")
    if msg_type == "approval_result":
        bus.emit(session_id, EventType.approval_result, Role.user,
                 {"decision": data.get("decision"), "reason": data.get("reason")})
    elif msg_type == "ping":
        pass
    else:
        bus.emit(session_id, EventType.message, Role.user,
                 {"text": data.get("text", ""), "raw": data})


# ---------- Mock 执行流（B1 仅验证通路，B2 替换为 OpenHands Worker） ----------

async def _mock_run(session_id: str, task_id: str, description: str) -> None:
    """模拟一次 Supervisor→Worker→Overseer→Verify 的完整事件流。"""
    def e(type_: EventType, agent: Role | None, payload: dict[str, Any]) -> None:
        bus.emit(session_id, type_, agent, payload, parent_id=task_id)

    e(EventType.message, Role.user, {"text": description})
    await asyncio.sleep(0.3)

    e(EventType.message, Role.supervisor,
      {"text": "拆解目标 → 子任务①：创建 app.py 与 test_app.py，跑 pytest 通过。", "model": "GLM-5.2"})
    await asyncio.sleep(0.2)

    e(EventType.tool_call, Role.worker, {"tool": "file_editor", "summary": "创建 app.py", "status": "running"})
    await asyncio.sleep(0.2)
    e(EventType.file_change, Role.worker, {"path": "/workspace/app.py", "change": "add", "language": "python"})
    e(EventType.tool_result, Role.worker, {"tool": "file_editor", "summary": "创建 app.py", "status": "ok"})
    await asyncio.sleep(0.2)
    if os.environ.get("FLIPPED_MOCK_APPROVAL") == "1":
        bus.emit(session_id, EventType.approval_request, Role.system,
                 {"action": "Worker 写入 /workspace/app.py", "reason": "文件系统写操作，需人工确认", "risk": "medium"})
        approval = await _wait_for_event(session_id, EventType.approval_result)
        decision = str(approval.get("decision", "")).lower()
        if decision not in ("approve", "approved", "yes", "y", "true", "1", "ok", "放行", "同意"):
            store.update_status(session_id, SessionStatus.review)
            bus.emit(session_id, EventType.status, Role.system,
                     {"status": "review", "progress": 20, "note": "审批被否决"})
            bus.emit(session_id, EventType.error, Role.system, {"message": "审批被否决，任务中止"})
            return

    e(EventType.tool_call, Role.worker, {"tool": "file_editor", "summary": "创建 test_app.py", "status": "running"})
    await asyncio.sleep(0.2)
    e(EventType.file_change, Role.worker, {"path": "/workspace/test_app.py", "change": "add", "language": "python"})
    e(EventType.tool_result, Role.worker, {"tool": "file_editor", "summary": "创建 test_app.py", "status": "ok"})
    await asyncio.sleep(0.2)

    e(EventType.tool_call, Role.worker, {"tool": "terminal", "summary": "pytest -q", "status": "running"})
    await asyncio.sleep(0.3)
    e(EventType.terminal, Role.worker, {"command": "pytest -q", "output": "...\n3 passed in 0.42s", "exit_code": 0})
    e(EventType.tool_result, Role.worker, {"tool": "terminal", "summary": "pytest -q", "status": "ok"})
    await asyncio.sleep(0.2)

    e(EventType.message, Role.overseer,
      {"verdict": {"efficiency": 0.9, "direction": 1.0, "action": "continue",
                   "note": "建档+测试完成，方向正确。"}, "model": "GLM-5.2"})
    await asyncio.sleep(0.2)

    e(EventType.message, Role.supervisor,
      {"text": "子任务②：启动 uvicorn，用内置浏览器打开 /docs 截图确认。", "model": "GLM-5.2"})
    await asyncio.sleep(0.2)

    e(EventType.tool_call, Role.worker, {"tool": "terminal", "summary": "uvicorn app:app --port 8000", "status": "running"})
    await asyncio.sleep(0.2)
    e(EventType.terminal, Role.worker, {"command": "uvicorn app:app --port 8000 &",
                                        "output": "Uvicorn running on http://127.0.0.1:8000", "exit_code": 0})
    e(EventType.tool_result, Role.worker, {"tool": "terminal", "summary": "uvicorn app:app --port 8000", "status": "ok"})
    await asyncio.sleep(0.2)

    e(EventType.tool_call, Role.worker, {"tool": "browser", "summary": "打开 /docs 并截图", "status": "running"})
    await asyncio.sleep(0.3)
    e(EventType.browser, Role.worker, {"url": "http://127.0.0.1:8000/docs",
                                       "title": "Todo API - Swagger UI",
                                       "screenshot": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="})
    e(EventType.tool_result, Role.worker, {"tool": "browser", "summary": "打开 /docs 并截图", "status": "ok"})
    await asyncio.sleep(0.2)

    e(EventType.message, Role.overseer,
      {"verdict": {"efficiency": 0.95, "direction": 1.0, "action": "continue",
                   "note": "服务起、页面通、截图有据。"}, "model": "GLM-5.2"})
    await asyncio.sleep(0.2)

    e(EventType.message, Role.verify,
      {"text": "强制验收：pytest 全通过 + /docs HTTP 200 + Swagger 标题匹配 → 目标达成。", "ok": True})
    store.update_status(session_id, SessionStatus.done)
    e(EventType.status, Role.system, {"status": "done", "progress": 100, "note": "任务完成"})
async def _wait_for_event(session_id: str, event_type: EventType, timeout: float = 15.0) -> dict:
    """在 store 中轮询等待指定类型的事件返回。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        for ev in reversed(store.events(session_id)):
            if ev.type == event_type:
                return ev.payload
        await asyncio.sleep(0.2)
    return {}


# ---------- M178.1 · 后台任务系统（已安排任务：注册表 + 定时派发） ----------

from dataclasses import asdict as _asdict  # 局部 import：本段自包含，不动顶部 import 行
from typing import Literal

from .cron import CronError, validate_cron
from .tasks import ScheduledTask, TaskRegistry, due_tasks

_TASK_REGISTRY: TaskRegistry | None = None


def _get_task_registry() -> TaskRegistry:
    """任务注册表单例（惰性构造；路径 FLIPPED_TASKS_PATH，缺省 data/scheduled_tasks.json）。"""
    global _TASK_REGISTRY
    if _TASK_REGISTRY is None:
        _TASK_REGISTRY = TaskRegistry(
            Path(os.environ.get("FLIPPED_TASKS_PATH", "data/scheduled_tasks.json")))
    return _TASK_REGISTRY


class TaskCreateRequest(BaseModel):
    """创建已安排任务请求（M178.1；M187.1 增加 cron kind）。"""
    title: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    mode: str = "chat"
    model: str = "coder"
    kind: Literal["once", "interval", "cron"] = "once"
    run_at: str | None = None
    every_minutes: int | None = None
    cron: str | None = None


class ScheduledTaskResponse(BaseModel):
    """已安排任务响应（镜像 tasks.ScheduledTask 全字段）。"""
    id: str
    title: str
    prompt: str
    mode: str
    model: str
    kind: str
    run_at: str | None = None
    every_minutes: int | None = None
    cron: str | None = None
    enabled: bool
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_status: str | None = None
    last_session_id: str | None = None
    run_count: int
    created_at: str


class TaskDeleteResponse(BaseModel):
    ok: bool
    id: str


_TASK_ALLOWED_MODES = {"auto", "agent", "chat", "plan"}


def _tasks_feature_off() -> bool:
    """整体开关：FLIPPED_TASKS=0 → 4 端点 404、scheduler 不启动（同 FLIPPED_GOAL 惯例）。"""
    return os.environ.get("FLIPPED_TASKS", "1") == "0"


@app.post(f"{API_PREFIX}/tasks", response_model=ScheduledTaskResponse, status_code=201)
async def create_scheduled_task(req: TaskCreateRequest) -> dict:
    """创建已安排任务：once 必须有 run_at；interval 必须 every_minutes>=1。"""
    if _tasks_feature_off():
        raise HTTPException(status_code=404, detail="任务功能已禁用")
    if req.mode not in _TASK_ALLOWED_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {_TASK_ALLOWED_MODES}")
    if req.kind == "once" and not req.run_at:
        raise HTTPException(status_code=422, detail="once 任务必须提供 run_at")
    if req.kind == "interval" and (req.every_minutes is None or req.every_minutes < 1):
        raise HTTPException(status_code=422, detail="interval 任务必须提供 every_minutes>=1")
    # M187.1：cron 校验——kind=cron 必填且合法；其余 kind 带 cron → 422（防脏数据）
    if req.kind == "cron":
        if not req.cron:
            raise HTTPException(status_code=422, detail="cron 任务必须提供 cron 表达式")
        try:
            validate_cron(req.cron)
        except CronError as e:
            raise HTTPException(status_code=422, detail=f"cron 表达式非法: {e}")
    elif req.cron:
        raise HTTPException(status_code=422, detail="仅 cron 任务可传 cron 表达式")
    task = _get_task_registry().add(
        title=req.title, prompt=req.prompt, mode=req.mode, model=req.model,
        kind=req.kind, run_at=req.run_at, every_minutes=req.every_minutes,
        cron=req.cron, now=datetime.now(timezone.utc))
    return _asdict(task)


@app.get(f"{API_PREFIX}/tasks", response_model=list[ScheduledTaskResponse])
async def list_scheduled_tasks() -> list[dict]:
    """任务清单：next_run_at 升序，None 沉底（注册表 list 语义）。"""
    if _tasks_feature_off():
        raise HTTPException(status_code=404, detail="任务功能已禁用")
    return [_asdict(t) for t in _get_task_registry().list()]


class TaskPatchRequest(BaseModel):
    """M187.2 · 编辑已安排任务请求（全字段可选，exclude_unset 语义：
    显式传 null 会进入 fields，置空后合并非法由 registry.update 校验拦截）。"""
    title: str | None = None
    prompt: str | None = None
    mode: str | None = None
    model: str | None = None
    kind: Literal["once", "interval", "cron"] | None = None
    run_at: str | None = None
    every_minutes: int | None = None
    cron: str | None = None


@app.patch(f"{API_PREFIX}/tasks/{{task_id}}", response_model=ScheduledTaskResponse)
async def patch_scheduled_task(task_id: str, req: TaskPatchRequest) -> dict:
    """编辑任务：白名单合并校验；调度字段实际变更 → 重算 next_run_at。"""
    if _tasks_feature_off():
        raise HTTPException(status_code=404, detail="任务功能已禁用")
    fields = req.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=422, detail="至少提供一个字段")
    if fields.get("mode") is not None and fields["mode"] not in _TASK_ALLOWED_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {_TASK_ALLOWED_MODES}")
    try:
        task = _get_task_registry().update(
            task_id, now=datetime.now(timezone.utc), **fields)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return _asdict(task)


@app.delete(f"{API_PREFIX}/tasks/{{task_id}}", response_model=TaskDeleteResponse)
async def delete_scheduled_task(task_id: str) -> TaskDeleteResponse:
    if _tasks_feature_off():
        raise HTTPException(status_code=404, detail="任务功能已禁用")
    if not _get_task_registry().remove(task_id):
        raise HTTPException(status_code=404, detail="task not found")
    return TaskDeleteResponse(ok=True, id=task_id)


@app.post(f"{API_PREFIX}/tasks/{{task_id}}/toggle", response_model=ScheduledTaskResponse)
async def toggle_scheduled_task(task_id: str, enabled: bool = Query(...)) -> dict:
    """启停任务：停用 → next_run_at=None；启用 → 按当前时刻重算。"""
    if _tasks_feature_off():
        raise HTTPException(status_code=404, detail="任务功能已禁用")
    task = _get_task_registry().toggle(task_id, enabled, now=datetime.now(timezone.utc))
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return _asdict(task)


async def _task_scheduler() -> None:
    """M178.1 · 定时任务扫描循环：每 FLIPPED_TASKS_SCAN_S（默认 30s）扫 due 任务逐个派发。

    单任务派发异常隔离（mark_run failed），循环自身任何异常都不崩（下轮继续）。
    """
    while True:
        await asyncio.sleep(float(os.environ.get("FLIPPED_TASKS_SCAN_S", "30")))
        try:
            now = datetime.now(timezone.utc)
            for task in due_tasks(_get_task_registry().list(), now):
                try:
                    await _dispatch_scheduled(task)
                except Exception:  # noqa: BLE001 单任务异常绝不炸 scheduler
                    try:
                        _get_task_registry().mark_run(
                            task.id, "failed", None, datetime.now(timezone.utc))
                    except Exception:  # noqa: BLE001 落盘失败也继续
                        pass
        except Exception:  # noqa: BLE001 扫描循环容错，下轮继续
            continue


async def _dispatch_scheduled(task: ScheduledTask) -> None:
    """派发一个到期任务：防重入 → 建会话 → 复刻 assistant 派发链 → mark_run。

    派发链与 assistant.send_assistant_message 同语义（进程内直调，不 HTTP 自调）：
    update_status running → emit status → emit user message → agent/auto 做
    git shadow snapshot（M168.1 惯例，非 git 工作区仅提示不阻塞）→ TaskRequest →
    模块级名取 _run_chat/_run_orchestrator（monkeypatch api.main.* 生效）→
    create_task + RUNNING_TASKS 注册 + done_callback pop。git 调用经 to_thread 包裹。
    """
    from .assistant import _git_head, _git_snapshot

    now = datetime.now(timezone.utc)
    # 防重入：上次会话仍在跑 → 本轮记 skipped 不派
    if task.last_session_id:
        prev = RUNNING_TASKS.get(task.last_session_id)
        if prev is not None and not prev.done():
            _get_task_registry().mark_run(task.id, "skipped", None, now)
            return
    proj = ps.active_project()
    session = store.create(
        title=task.title, model=task.model, mode=task.mode,
        project=proj["host"] if proj else None,
        project_name=proj["name"] if proj else None,
    )
    sid = session.id
    task_id = f"task-{now.strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
    store.update_status(sid, SessionStatus.running)
    bus.emit(sid, EventType.status, Role.system,
             {"status": "running", "progress": 0, "note": f"定时任务已派发 {task_id}"})
    bus.emit(sid, EventType.message, Role.user, {"text": task.prompt})
    if task.mode in ("auto", "agent"):
        root = ps.project_root()
        snap = await asyncio.to_thread(_git_snapshot, root) if root is not None else None
        if snap:
            head = await asyncio.to_thread(_git_head, root)
            bus.emit(sid, EventType.snapshot, Role.system,
                     {"snapshot": snap, "head": head, "task_id": task_id})
        else:
            bus.emit(sid, EventType.message, Role.system,
                     {"text": "非 git 工作区，本轮改动不可撤销"})
    task_req = TaskRequest(
        description=task.prompt,
        context={"mode": task.mode, "model": task.model,
                 "orchestrator": {"require_approval": True}},
    )
    if task.mode in ("auto", "agent"):
        coro = _run_orchestrator(sid, task_id, task_req)
    else:  # chat / plan
        coro = _run_chat(sid, task_id, task.prompt, task.model, task.mode)
    t = asyncio.create_task(coro)
    RUNNING_TASKS[sid] = t
    t.add_done_callback(lambda _t, s=sid: RUNNING_TASKS.pop(s, None))
    _get_task_registry().mark_run(task.id, "done", sid, now)


# ---------- M181 · 移动远程控制（手机扫码查看进度/发消息/审批；纯逻辑在 api/remote.py） ----------

import time  # 局部 import：本段自包含，不动顶部 import 行
from typing import Literal

from fastapi import Request, Response
from fastapi.responses import HTMLResponse

from .assistant import DecisionResponse, MessageResponse
from .remote import RemoteRegistry, detect_lan_ip, mobile_page_html, qr_svg

_REMOTE_REGISTRY: RemoteRegistry | None = None


def _remote_registry() -> RemoteRegistry:
    """远程 token 注册表单例（惰性构造；FLIPPED_REMOTE_DB / FLIPPED_REMOTE_TTL_S）。"""
    global _REMOTE_REGISTRY
    if _REMOTE_REGISTRY is None:
        _REMOTE_REGISTRY = RemoteRegistry(
            Path(os.environ.get("FLIPPED_REMOTE_DB", "data/remote_tokens.json")),
            ttl_s=int(os.environ.get("FLIPPED_REMOTE_TTL_S", "1800")))
    return _REMOTE_REGISTRY


class RemoteIssueRequest(BaseModel):
    """签发远程链接请求：session_id 缺省 → 绑定最新会话。"""
    session_id: str | None = None


class RemoteIssueResponse(BaseModel):
    """签发响应：移动页 URL + QR 地址 + 绑定会话信息 + 回环提示。"""
    token: str
    url: str
    qr_url: str
    session_id: str
    session_title: str
    expires_at: float
    host_note: str


class RemoteStateResponse(BaseModel):
    """移动页轮询态：会话标识 + 状态徽标 + 尾 20 turns + pending 审批。"""
    session_id: str
    title: str
    mode: str
    status: str
    pending_approval: dict[str, str] | None
    turns: list[dict[str, str]]


class RemoteMessageRequest(BaseModel):
    """远程发消息请求（与 console 发送同语义，仅文本）。"""
    text: str = Field(min_length=1, max_length=8000)


class RemoteDecisionRequest(BaseModel):
    """远程审批请求：放行 | 否决。"""
    decision: Literal["approve", "reject"]


class RemoteRevokeResponse(BaseModel):
    """撤销响应（幂等：token 存在与否都 ok=True）。"""
    ok: bool


_LOOPBACK_HOST_NOTE = (
    "当前绑定回环地址，手机可能无法打开：请用 --host 0.0.0.0 起后端或设 FLIPPED_REMOTE_HOST")

_REMOTE_GONE_HTML = (
    "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
    "<title>链接已失效</title></head>"
    "<body style=\"margin:0;min-height:100vh;display:flex;align-items:center;"
    "justify-content:center;background:#0f1115;color:#a8adb8;"
    "font-family:system-ui,-apple-system,sans-serif\">"
    "<p>链接已失效</p></body></html>")


def _remote_host() -> str:
    """移动页 URL 的 host：FLIPPED_REMOTE_HOST 优先，否则主网卡 LAN IP。"""
    return os.environ.get("FLIPPED_REMOTE_HOST") or detect_lan_ip()


def _remote_page_url(request: Request, token: str) -> str:
    """重建移动页 URL（port 取请求自带，与 issue 时一致）。"""
    return f"http://{_remote_host()}:{request.url.port}/remote/{token}"


def _resolve_remote_token(token: str):
    """token 守卫：未知/过期一律 404（统一 detail，不区分，无 oracle）。"""
    tok = _remote_registry().resolve(token, now=time.time())
    if tok is None:
        raise HTTPException(status_code=404, detail="remote token invalid")
    return tok


@app.post(f"{API_PREFIX}/remote/sessions", response_model=RemoteIssueResponse)
async def issue_remote_session(req: RemoteIssueRequest, request: Request) -> RemoteIssueResponse:
    """签发移动远程链接：token 绑定单会话（同 session 单活），返回 URL + QR 地址。

    session_id 缺省 → 最新会话（created_at ISO 字符串降序取首）；无会话 → 400；
    指定不存在 → 404。host 为回环时 host_note 提示手机可能无法打开。
    """
    if req.session_id:
        session = store.get(req.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
    else:
        sessions = sorted(store.list(), key=lambda s: s.created_at, reverse=True)
        if not sessions:
            raise HTTPException(status_code=400, detail="no session available")
        session = sessions[0]
    tok = _remote_registry().issue(session.id, now=time.time())
    host = _remote_host()
    return RemoteIssueResponse(
        token=tok.token,
        url=f"http://{host}:{request.url.port}/remote/{tok.token}",
        qr_url=f"{API_PREFIX}/remote/{tok.token}/qr.svg",
        session_id=session.id,
        session_title=session.title,
        expires_at=tok.expires_at,
        host_note=_LOOPBACK_HOST_NOTE if host == "127.0.0.1" else "")


@app.get(f"{API_PREFIX}/remote/{{token}}/state", response_model=RemoteStateResponse)
async def remote_state(token: str) -> RemoteStateResponse:
    """移动页轮询态：尾 20 条 user/assistant turns（text 截 2000）+ pending 审批标志。"""
    from .assistant import _has_pending_approval, _latest_pending_action, get_assistant_history

    tok = _resolve_remote_token(token)
    session = store.get(tok.session_id)
    if session is None:  # token 活着但会话被删 → 同 404 语义，不泄露细节
        raise HTTPException(status_code=404, detail="remote token invalid")
    history = await get_assistant_history(tok.session_id)
    turns = [
        {"role": t.role, "text": (t.text or "")[:2000]}
        for t in history
        if t.role in ("user", "assistant") and t.text
    ][-20:]
    pending_approval = None
    if _has_pending_approval(store, tok.session_id):
        pending_approval = {
            "action": _latest_pending_action(store, tok.session_id) or "",
            "reason": "高风险子任务，需人工放行",
        }
    status = session.status.value if hasattr(session.status, "value") else str(session.status)
    return RemoteStateResponse(
        session_id=session.id, title=session.title, mode=str(session.mode),
        status=status, pending_approval=pending_approval, turns=turns)


@app.post(f"{API_PREFIX}/remote/{{token}}/message", response_model=MessageResponse)
async def remote_message(token: str, req: RemoteMessageRequest) -> MessageResponse:
    """远程发消息 = console 发送同语义（转发 canonical handler；409 会话忙透传）。"""
    from .assistant import SendMessageRequest, send_assistant_message

    tok = _resolve_remote_token(token)
    return await send_assistant_message(tok.session_id, SendMessageRequest(text=req.text))


@app.post(f"{API_PREFIX}/remote/{{token}}/decision", response_model=DecisionResponse)
async def remote_decision(token: str, req: RemoteDecisionRequest) -> DecisionResponse:
    """远程审批放行/否决（转发 _do_decision；无 pending approval → 409 透传）。"""
    from .assistant import _do_decision

    tok = _resolve_remote_token(token)
    return await _do_decision(tok.session_id, req.decision)


@app.get("/remote/{token}", response_class=HTMLResponse)
async def remote_page(token: str) -> HTMLResponse:
    """手机扫码打开的远程控制页（自包含 HTML，无 API_PREFIX）。无效 token → 404 失效页。"""
    if _remote_registry().resolve(token, now=time.time()) is None:
        return HTMLResponse(_REMOTE_GONE_HTML, status_code=404)
    return HTMLResponse(mobile_page_html(token))


@app.get(f"{API_PREFIX}/remote/{{token}}/qr.svg")
async def remote_qr(token: str, request: Request) -> Response:
    """远程链接的 QR（SVG 直出，前端 <img> 直挂，零 npm 依赖）。"""
    _resolve_remote_token(token)
    return Response(qr_svg(_remote_page_url(request, token)), media_type="image/svg+xml")


@app.delete(f"{API_PREFIX}/remote/{{token}}", response_model=RemoteRevokeResponse)
async def remote_revoke(token: str) -> RemoteRevokeResponse:
    """撤销远程链接（幂等：token 存在与否都 200）。"""
    _remote_registry().revoke(token)
    return RemoteRevokeResponse(ok=True)


# ---------- M182 · Bot Channel（多平台接入：Telegram webhook + 企业微信应用回调） ----------
# 纯逻辑在 api/bot_channel.py（身份映射/状态统计/入站编排）与 api/bot_telegram.py /
# api/bot_wecom.py（平台协议）；本段只做 HTTP 接线。token/secret 全走 env，绝不进代码/日志。
# FLIPPED_BOT=0 → 全部端点 404；平台 env 未配齐 → 对应 webhook/callback 404。

from fastapi.responses import JSONResponse as _JSONResponse
from fastapi.responses import PlainTextResponse as _PlainTextResponse

from . import bot_telegram as _bot_tg
from . import bot_wecom as _bot_wc
from .bot_channel import (
    BotSessionRegistry as _BotSessionRegistry,
    ChannelStats as _ChannelStats,
    UnifiedMessage as _UnifiedMessage,
    bot_db_path as _bot_db_path,
    bot_reply_timeout_s as _bot_reply_timeout_s,
    bot_stats_db_path as _bot_stats_db_path,
    handle_inbound as _bot_handle_inbound,
    wait_for_reply as _bot_wait_for_reply,
)

_BOT_REGISTRY: _BotSessionRegistry | None = None
_BOT_STATS: _ChannelStats | None = None


class BotChannelStatusEntry(BaseModel):
    """单平台通道状态（GET /bot/channels 条目，与前端 BotChannelInfo 对齐）。"""
    platform: str
    enabled: bool
    configured: bool
    inbound_count: int
    outbound_count: int
    error_count: int
    last_inbound_at: float | None
    last_outbound_at: float | None
    last_error: str


class BotChannelsResponse(BaseModel):
    """通道状态列表。"""
    channels: list[BotChannelStatusEntry]


class BotWebhookResponse(BaseModel):
    """webhook 受理回执（handled=False = 非文本/无 message，已忽略不重试）。"""
    ok: bool
    handled: bool


class BotTestRequest(BaseModel):
    """测试消息请求（发到该平台最近绑定的 chat）。"""
    text: str = Field(min_length=1, max_length=4000)


class BotTestResponse(BaseModel):
    """测试消息结果（send 失败走 502 JSONResponse，此模型仅 ok=True 路径）。"""
    ok: bool
    error: str = ""


def _bot_enabled() -> bool:
    """Bot Channel 总开关：FLIPPED_BOT=0 → 全端点 404。"""
    return os.environ.get("FLIPPED_BOT", "1") != "0"


def _bot_sessions() -> _BotSessionRegistry:
    """身份映射注册表单例（惰性构造；FLIPPED_BOT_DB 默认 data/bot_sessions.json）。"""
    global _BOT_REGISTRY
    if _BOT_REGISTRY is None:
        _BOT_REGISTRY = _BotSessionRegistry(_bot_db_path())
    return _BOT_REGISTRY


def _bot_channel_stats() -> _ChannelStats:
    """通道统计单例（惰性构造；FLIPPED_BOT_STATS_DB 默认 data/bot_stats.json）。"""
    global _BOT_STATS
    if _BOT_STATS is None:
        _BOT_STATS = _ChannelStats(_bot_stats_db_path())
    return _BOT_STATS


def _bot_sender(platform: str):
    """按平台构造 send(chat_id, text) 闭包；未知平台/未配置 → None。"""
    if platform == "telegram":
        if not _bot_tg.configured():
            return None
        sender = _bot_tg.TelegramSender(os.environ["FLIPPED_BOT_TELEGRAM_TOKEN"].strip())
        return sender.send_message
    if platform == "wecom":
        if not _bot_wc.configured():
            return None
        sender = _bot_wc.WeComSender(
            os.environ["FLIPPED_BOT_WECOM_CORP_ID"].strip(),
            os.environ["FLIPPED_BOT_WECOM_SECRET"].strip(),
            _bot_wc.agent_id())
        return sender.send_message
    return None


def _wecom_crypto() -> _bot_wc.WeComCrypto:
    """企业微信加解密器（调用前须已过 configured() 守卫）。"""
    return _bot_wc.WeComCrypto(
        os.environ["FLIPPED_BOT_WECOM_TOKEN"].strip(),
        os.environ["FLIPPED_BOT_WECOM_AES_KEY"].strip(),
        os.environ["FLIPPED_BOT_WECOM_CORP_ID"].strip())


def _wecom_extract_encrypt(xml_text: str) -> str | None:
    """从回调外层 XML 提取 <Encrypt>（畸形 → None）。"""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except Exception:  # noqa: BLE001 畸形 XML 不炸
        return None
    if root is None:
        return None
    return root.findtext("Encrypt") or None


async def _bot_run_inbound(msg: _UnifiedMessage) -> None:
    """单条入站消息的编排任务（webhook 以 create_task 派发，绝不阻塞 200 回执）。

    转发 canonical send_assistant_message（与 M181 remote 同模式，函数级 import），
    baseline 在 dispatch 前快照，await_reply 轮询 history 等 baseline 后新 assistant turn。
    """
    from .assistant import SendMessageRequest, get_assistant_history, send_assistant_message

    baselines: dict[str, int] = {}

    async def create_session(title: str) -> str:
        return store.create(title=title, mode="chat").id

    async def dispatch(sid: str, text: str) -> None:
        baselines[sid] = len(await get_assistant_history(sid))
        await send_assistant_message(sid, SendMessageRequest(text=text))

    async def await_reply(sid: str) -> str | None:
        async def get_hist(s: str) -> list[dict]:
            return [{"role": t.role, "text": t.text or ""}
                    for t in await get_assistant_history(s)]

        return await _bot_wait_for_reply(
            get_hist, sid, baselines.get(sid, 0), _bot_reply_timeout_s())

    async def send_reply(text: str) -> tuple[bool, str]:
        sender = _bot_sender(msg.platform)
        if sender is None:
            return (False, f"platform not configured: {msg.platform}")
        return await sender(msg.chat_id, text)

    await _bot_handle_inbound(
        msg, registry=_bot_sessions(), stats=_bot_channel_stats(),
        create_session=create_session, dispatch=dispatch,
        await_reply=await_reply, send_reply=send_reply)


@app.post(f"{API_PREFIX}/bot/telegram/webhook", response_model=BotWebhookResponse)
async def bot_telegram_webhook(request: Request) -> BotWebhookResponse:
    """Telegram webhook：secret 头验签（hmac 常量时间）；非文本消息 200 handled=False。

    未配置 token → 404（不暴露通道存在性）；secret 不符 → 403；解析后后台
    create_task 编排，立即 200（Telegram 重发窗口内绝不阻塞）。
    """
    if not _bot_enabled() or not _bot_tg.configured():
        raise HTTPException(status_code=404, detail="bot channel not configured")
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not _bot_tg.verify_secret(secret, _bot_tg.secret_configured()):
        raise HTTPException(status_code=403, detail="invalid secret")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 非法 JSON 也回 200 handled=False，防 Telegram 重试风暴
        return BotWebhookResponse(ok=True, handled=False)
    msg = _bot_tg.parse_update(body)
    if msg is None:
        return BotWebhookResponse(ok=True, handled=False)
    asyncio.create_task(_bot_run_inbound(msg))
    return BotWebhookResponse(ok=True, handled=True)


@app.get(f"{API_PREFIX}/bot/wecom/callback")
async def bot_wecom_verify(msg_signature: str = Query(...), timestamp: str = Query(...),
                           nonce: str = Query(...), echostr: str = Query(...)
                           ) -> _PlainTextResponse:
    """企业微信回调 URL 验证：验签 → 解密 echostr → 明文直出（协议要求）。

    返回 PlainTextResponse 非 JSON，无 Pydantic 模型可挂 → 登记契约 allowlist。
    """
    if not _bot_enabled() or not _bot_wc.configured():
        raise HTTPException(status_code=404, detail="bot channel not configured")
    crypto = _wecom_crypto()
    if not crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
        raise HTTPException(status_code=403, detail="invalid signature")
    try:
        plain = crypto.decrypt(echostr)
    except ValueError:
        raise HTTPException(status_code=403, detail="decrypt failed")
    return _PlainTextResponse(plain)


@app.post(f"{API_PREFIX}/bot/wecom/callback")
async def bot_wecom_callback(request: Request, msg_signature: str = Query(...),
                             timestamp: str = Query(...), nonce: str = Query(...)
                             ) -> _PlainTextResponse:
    """企业微信消息回调：验签(用外层 Encrypt) → 解密 → 非文本/解密失败也回 "success"。

    协议要求无论处理结果都回明文 success（否则企业微信判定失败重推）；
    返回 PlainTextResponse → 登记契约 allowlist。
    """
    if not _bot_enabled() or not _bot_wc.configured():
        raise HTTPException(status_code=404, detail="bot channel not configured")
    body = (await request.body()).decode("utf-8", errors="replace")
    encrypt = _wecom_extract_encrypt(body)
    crypto = _wecom_crypto()
    if encrypt is None or not crypto.verify_signature(
            msg_signature, timestamp, nonce, encrypt):
        raise HTTPException(status_code=403, detail="invalid signature")
    msg = None
    try:
        msg = _bot_wc.parse_callback_xml(crypto.decrypt(encrypt))
    except ValueError:  # corp_id 尾缀不符 → 按无效消息吞掉回 success
        msg = None
    if msg is not None:
        asyncio.create_task(_bot_run_inbound(msg))
    return _PlainTextResponse("success")


@app.get(f"{API_PREFIX}/bot/channels", response_model=BotChannelsResponse)
async def bot_channels() -> BotChannelsResponse:
    """通道状态监控：两平台计数/末次时间/末次错误（未配置也列出，前端引导配置）。"""
    if not _bot_enabled():
        raise HTTPException(status_code=404, detail="bot channel disabled")
    configured = {"telegram": _bot_tg.configured(), "wecom": _bot_wc.configured()}
    return BotChannelsResponse(channels=[
        BotChannelStatusEntry(**vars(s))
        for s in _bot_channel_stats().all_statuses(configured, enabled=True)
    ])


@app.post(f"{API_PREFIX}/bot/channels/{{platform}}/test", response_model=BotTestResponse)
async def bot_channel_test(platform: str, req: BotTestRequest) -> BotTestResponse | _JSONResponse:
    """发测试消息到该平台最近绑定的 chat：未知平台 404 / 未配置 400 / 无绑定 400 /
    发送失败 502 {ok:false,error}；成功 {ok:true} 并记 outbound 统计。"""
    if not _bot_enabled():
        raise HTTPException(status_code=404, detail="bot channel disabled")
    if platform not in ("telegram", "wecom"):
        raise HTTPException(status_code=404, detail=f"unknown platform: {platform}")
    sender = _bot_sender(platform)
    if sender is None:
        raise HTTPException(status_code=400, detail=f"platform not configured: {platform}")
    chat_id = _bot_sessions().latest_chat_id(platform)
    if chat_id is None:
        raise HTTPException(status_code=400, detail=f"no bound chat for platform: {platform}")
    ok, err = await sender(chat_id, req.text)
    if not ok:
        return _JSONResponse(status_code=502, content={"ok": False, "error": err})
    _bot_channel_stats().record_outbound(platform)
    return BotTestResponse(ok=True)


# ---------- M183 · Worker 规则注入系统（agent 通路手动 CRUD + auto 通路自动生成） ----------
# 纯逻辑在 driving/worker_rules.py（WorkerRule/Store/Stats/build/generate）；
# orchestrator local_worker 注入 + verify 节点效果统计已在 B183 接线（fail-open）。
# 本段只做 HTTP 接线。FLIPPED_WORKER_RULES=0 → 全部端点 404。
# store/stats 每请求新实例（orchestrator 同进程并发写 stats 文件，缓存会读旧值）。

from driving.worker_rules import (
    WorkerRule as _WorkerRule,
    WorkerRuleStats as _WorkerRuleStats,
    WorkerRuleStore as _WorkerRuleStore,
    generate_auto_rules as _generate_auto_rules,
    generate_auto_rules_llm as _generate_auto_rules_llm,
)


class WorkerRuleCreateRequest(BaseModel):
    """新建规则：text 必填（1..500，blocklist 由 WorkerRule 校验），scope 缺省 worker。"""
    text: str = Field(min_length=1, max_length=500)
    scope: Literal["worker", "all"] = "worker"
    priority: int | None = Field(default=None, ge=0, le=100)


class WorkerRuleUpdateRequest(BaseModel):
    """更新规则：三字段全可选（None = 不动）。"""
    text: str | None = Field(default=None, min_length=1, max_length=500)
    priority: int | None = Field(default=None, ge=0, le=100)
    scope: Literal["worker", "all"] | None = None


class WorkerRuleToggleRequest(BaseModel):
    """启停规则。"""
    enabled: bool


class WorkerRuleDeleteResponse(BaseModel):
    """删除回执。"""
    ok: bool


class WorkerRulesResponse(BaseModel):
    """规则列表 + 当前版本号。"""
    version: int
    rules: list[_WorkerRule]


class WorkerRuleVersionEntry(BaseModel):
    """版本史元信息（不含快照全文）。"""
    version: int
    ts: float
    action: str
    detail: str
    rule_count: int


class WorkerRuleVersionsResponse(BaseModel):
    """版本史列表。"""
    versions: list[WorkerRuleVersionEntry]


class WorkerRuleRollbackRequest(BaseModel):
    """回滚到指定版本。"""
    version: int


class WorkerRuleRollbackResponse(BaseModel):
    """回滚回执：version 为回滚后的新版本号（rollback 自身亦 bump）。"""
    ok: bool
    version: int


class WorkerRuleAutoGenRequest(BaseModel):
    """自动生成请求：failure_texts 缺省 → 失败知识库最近未解决条目。"""
    failure_texts: list[str] | None = None


class WorkerRuleAutoGenResponse(BaseModel):
    """自动生成回执：added 为实际入库的规则，candidates 为候选条数。

    M190.2：llm_used 标记候选是否来自 LLM 兜底（固定模板未命中时触发）。
    """
    added: list[_WorkerRule]
    candidates: int
    llm_used: bool = False


class WorkerRuleStatEntry(BaseModel):
    """单规则效果：applied=注入次；success/failure=对应 verify 通过/失败次。

    success_rate=success/(success+failure)（同单位 verify 次）；零 outcome → null。
    """
    applied: int
    success: int
    failure: int
    success_rate: float | None = None


class WorkerRuleStatsResponse(BaseModel):
    """规则执行效果统计快照（semantics 显式语义注记，M185.2）。"""
    stats: dict[str, WorkerRuleStatEntry]
    total_runs: int
    semantics: str = ""


def _worker_rules_guard() -> None:
    """总开关守卫：FLIPPED_WORKER_RULES=0 → 404。"""
    if os.environ.get("FLIPPED_WORKER_RULES", "1") == "0":
        raise HTTPException(status_code=404, detail="worker rules disabled")


def _worker_rule_store() -> _WorkerRuleStore:
    """每请求新实例（坏文件回退空不炸；FLIPPED_WORKER_RULES_PATH 默认 data/worker_rules.json）。"""
    return _WorkerRuleStore(
        Path(os.environ.get("FLIPPED_WORKER_RULES_PATH", "data/worker_rules.json")))


def _worker_rule_stats() -> _WorkerRuleStats:
    """每请求新实例（orchestrator verify 节点并发写，单例缓存会读旧值）。"""
    return _WorkerRuleStats(
        Path(os.environ.get("FLIPPED_WORKER_RULE_STATS_PATH", "data/worker_rule_stats.json")))


def _recent_failure_texts(limit: int = 20) -> list[str]:
    """auto 通路缺省数据源：失败知识库最近未解决条目（fail-open → []）。"""
    try:
        from driving.failure_kb import get_all_failures
        entries = get_all_failures(limit=limit, resolved=False)
        return [f"{e.cause} {e.error_detail}".strip() for e in entries]
    except Exception:  # noqa: BLE001 fail-open
        return []


def _error_event_texts(limit: int = 20) -> list[str]:
    """M190.2：扫描全会话事件流的 error 事件，取 payload 字符串值拼接（最新优先）。"""
    out: list[str] = []
    for sess in store.list():
        for ev in reversed(store.events(sess.id)):
            etype = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
            if etype != "error":
                continue
            text = " ".join(str(v) for v in ev.payload.values()
                            if isinstance(v, str) and v.strip()).strip()
            if text:
                out.append(text)
            if len(out) >= limit:
                return out
    return out


def _collect_failure_texts(limit: int = 20) -> list[str]:
    """M190.2 多源汇聚：failure_kb 未解决 ∪ 会话事件流 error 事件。

    dedup 保序（kb 在前），单源异常各自 fail-open，总量 cap limit*2。
    """
    texts: list[str] = []
    seen: set[str] = set()

    def _add(items: list[str]) -> None:
        for t in items:
            t = (t or "").strip()
            if t and t not in seen:
                seen.add(t)
                texts.append(t)

    try:
        _add(_recent_failure_texts(limit))
    except Exception:  # noqa: BLE001 单源 fail-open
        pass
    try:
        _add(_error_event_texts(limit))
    except Exception:  # noqa: BLE001 单源 fail-open
        pass
    return texts[: limit * 2]


@app.get(f"{API_PREFIX}/worker/rules", response_model=WorkerRulesResponse)
async def worker_rules_list(
        enabled: bool | None = Query(None),
        sort: Literal["insertion", "priority"] = Query("insertion")
        ) -> WorkerRulesResponse:
    """规则列表 + 版本号（前端 WorkerRulesPanel mount 拉取）。

    缺省 = D20 契约（全量插入序）；enabled=true/false 服务端过滤；
    sort=priority → priority desc → id asc（与注入层同序，M185.3）。
    """
    _worker_rules_guard()
    store_ = _worker_rule_store()
    rules = store_.list()
    if enabled is not None:
        rules = [r for r in rules if r.enabled is enabled]
    if sort == "priority":
        rules = sorted(rules, key=lambda r: (-r.priority, r.id))
    return WorkerRulesResponse(version=store_.version, rules=rules)


@app.post(f"{API_PREFIX}/worker/rules", response_model=_WorkerRule, status_code=201)
async def worker_rules_create(req: WorkerRuleCreateRequest) -> _WorkerRule:
    """agent 通路手动注入：校验失败（长度/blocklist）→ 422。"""
    _worker_rules_guard()
    try:
        return _worker_rule_store().add(
            req.text, scope=req.scope, source="manual", priority=req.priority)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.put(f"{API_PREFIX}/worker/rules/{{rule_id}}", response_model=_WorkerRule)
async def worker_rules_update(rule_id: str, req: WorkerRuleUpdateRequest) -> _WorkerRule:
    """更新规则文本/优先级/作用域（重走 WorkerRule 校验）；未知 id → 404。"""
    _worker_rules_guard()
    try:
        rule = _worker_rule_store().update(
            rule_id, text=req.text, priority=req.priority, scope=req.scope)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return rule


@app.delete(f"{API_PREFIX}/worker/rules/{{rule_id}}", response_model=WorkerRuleDeleteResponse)
async def worker_rules_delete(rule_id: str) -> WorkerRuleDeleteResponse:
    """删除规则；未知 id → 404。"""
    _worker_rules_guard()
    if not _worker_rule_store().delete(rule_id):
        raise HTTPException(status_code=404, detail="rule not found")
    return WorkerRuleDeleteResponse(ok=True)


@app.post(f"{API_PREFIX}/worker/rules/{{rule_id}}/toggle", response_model=_WorkerRule)
async def worker_rules_toggle(rule_id: str, req: WorkerRuleToggleRequest) -> _WorkerRule:
    """启停规则（停用即不再注入 prompt，保留供复启）；未知 id → 404。"""
    _worker_rules_guard()
    rule = _worker_rule_store().set_enabled(rule_id, req.enabled)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return rule


@app.get(f"{API_PREFIX}/worker/rules/versions", response_model=WorkerRuleVersionsResponse)
async def worker_rules_versions() -> WorkerRuleVersionsResponse:
    """版本史（每次变更 bump + 快照，cap 20）。"""
    _worker_rules_guard()
    return WorkerRuleVersionsResponse(versions=[
        WorkerRuleVersionEntry(**v) for v in _worker_rule_store().versions()])


@app.post(f"{API_PREFIX}/worker/rules/rollback", response_model=WorkerRuleRollbackResponse)
async def worker_rules_rollback(req: WorkerRuleRollbackRequest) -> WorkerRuleRollbackResponse:
    """回滚到指定版本快照；未知版本 → 404。回滚自身亦 bump version。"""
    _worker_rules_guard()
    store_ = _worker_rule_store()
    if not store_.rollback(req.version):
        raise HTTPException(status_code=404, detail="version not found")
    return WorkerRuleRollbackResponse(ok=True, version=store_.version)


@app.post(f"{API_PREFIX}/worker/rules/auto-generate", response_model=WorkerRuleAutoGenResponse)
async def worker_rules_auto_generate(
        req: WorkerRuleAutoGenRequest | None = None) -> WorkerRuleAutoGenResponse:
    """auto 通路：失败文本 → 模板命中 → 去重 → 入库（source="auto"，priority 默认 10）。

    failure_texts 缺省时走 M190.2 多源汇聚（failure_kb ∪ 事件流 error）；
    模板全未命中且 texts 非空且 FLIPPED_RULES_LLM≠0 → LLM 兜底生成候选。
    无候选 → added=[] 不报错。
    """
    _worker_rules_guard()
    texts = req.failure_texts if req and req.failure_texts else _collect_failure_texts()
    store_ = _worker_rule_store()
    candidates = _generate_auto_rules(texts, store_.list())
    llm_used = False
    if not candidates and texts and os.environ.get("FLIPPED_RULES_LLM", "1") != "0":
        llm_candidates = _generate_auto_rules_llm(texts, store_.list())
        if llm_candidates:
            candidates = llm_candidates
            llm_used = True
    added = [store_.add(text, source="auto") for text in candidates]
    return WorkerRuleAutoGenResponse(added=added, candidates=len(candidates),
                                     llm_used=llm_used)


@app.get(f"{API_PREFIX}/worker/rules/stats", response_model=WorkerRuleStatsResponse)
async def worker_rules_stats() -> WorkerRuleStatsResponse:
    """规则执行效果统计（orchestrator 注入/verify 节点实时累积）。"""
    _worker_rules_guard()
    snap = _worker_rule_stats().snapshot()
    return WorkerRuleStatsResponse(
        stats={k: WorkerRuleStatEntry(**v) for k, v in snap["stats"].items()},
        total_runs=snap["total_runs"],
        semantics=snap.get("semantics", ""))
