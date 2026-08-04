"""M136-B — API 契约治理。

- B1: OpenAPI 快照漂移检测（新增/删除/变更的路径与 schema 一目了然）
      + 响应模型覆盖（新路由必须有命名 response_model，老路由登记在 allowlist）。
- B2: 事件 WS（/api/v1/sessions/{id}/events）ack 语义 + 垃圾帧容错。

运行: PYTHONPATH=src .venv/bin/python -m pytest tests/test_api_contract.py -v
更新快照: FLIPPED_UPDATE_API_SNAPSHOT=1 PYTHONPATH=src .venv/bin/python -m pytest tests/test_api_contract.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from api.main import API_PREFIX, app

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "api_contract_snapshot.json"
UPDATE_ENV = "FLIPPED_UPDATE_API_SNAPSHOT"

# 归一化时剔除的易变键（如未来引入时间戳/随机描述，加到这里）。
VOLATILE_KEYS: frozenset[str] = frozenset()


# ---------- B1a · OpenAPI 快照 ----------

def _normalize(node: Any) -> Any:
    """递归排序字典键并剔除易变字段，保证快照 diff 稳定。"""
    if isinstance(node, dict):
        return {k: _normalize(node[k]) for k in sorted(node) if k not in VOLATILE_KEYS}
    if isinstance(node, list):
        return [_normalize(item) for item in node]
    return node


def _canonical(spec: dict[str, Any]) -> str:
    return json.dumps(_normalize(spec), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _summarize_drift(old: dict[str, Any], new: dict[str, Any]) -> str:
    """path/operation/schema 级别的 added/removed/changed 摘要。"""
    lines: list[str] = []
    old_paths, new_paths = old.get("paths", {}), new.get("paths", {})
    for p in sorted(new_paths.keys() - old_paths.keys()):
        lines.append(f"  + 新增路径: {p} [{', '.join(sorted(new_paths[p]))}]")
    for p in sorted(old_paths.keys() - new_paths.keys()):
        lines.append(f"  - 移除路径: {p} [{', '.join(sorted(old_paths[p]))}]")
    for p in sorted(old_paths.keys() & new_paths.keys()):
        old_ops, new_ops = old_paths[p], new_paths[p]
        for op in sorted(new_ops.keys() - old_ops.keys()):
            lines.append(f"  + 新增方法: {op.upper()} {p}")
        for op in sorted(old_ops.keys() - new_ops.keys()):
            lines.append(f"  - 移除方法: {op.upper()} {p}")
        for op in sorted(old_ops.keys() & new_ops.keys()):
            if old_ops[op] != new_ops[op]:
                lines.append(f"  ~ 契约变更: {op.upper()} {p}")
    old_sch = old.get("components", {}).get("schemas", {})
    new_sch = new.get("components", {}).get("schemas", {})
    for s in sorted(new_sch.keys() - old_sch.keys()):
        lines.append(f"  + 新增 schema: {s}")
    for s in sorted(old_sch.keys() - new_sch.keys()):
        lines.append(f"  - 移除 schema: {s}")
    for s in sorted(old_sch.keys() & new_sch.keys()):
        if old_sch[s] != new_sch[s]:
            lines.append(f"  ~ schema 变更: {s}")
    if not lines:
        lines.append("  (顶层元数据变化，非 paths/schemas)")
    return "\n".join(lines)


def test_openapi_contract_matches_snapshot():
    """API 契约不得静默漂移：与 tests/snapshots/api_contract_snapshot.json 比对。

    - 快照不存在（首次运行）→ 自动播种并通过；
    - 不一致 → FAIL 并打印 drift 摘要；
    - 有意变更契约后，用 FLIPPED_UPDATE_API_SNAPSHOT=1 重跑本测试更新快照并一并提交。
    """
    normalized = _normalize(app.openapi())
    if not SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(_canonical(app.openapi()), encoding="utf-8")
        return  # 首次播种
    if os.environ.get(UPDATE_ENV) == "1":
        SNAPSHOT_PATH.write_text(_canonical(app.openapi()), encoding="utf-8")
        return  # 显式登记新契约
    old = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if old != normalized:
        summary = _summarize_drift(old, normalized)
        pytest.fail(
            "OpenAPI 契约与已登记快照不一致！\n"
            f"{summary}\n\n"
            "若这是有意的契约变更，请更新快照并连同本测试一起提交:\n"
            f"  {UPDATE_ENV}=1 PYTHONPATH=src .venv/bin/python -m pytest tests/test_api_contract.py\n"
            f"快照文件: {SNAPSHOT_PATH}"
        )


# ---------- B1b · 响应模型覆盖 ----------

# 治理起点：已存在、响应体未用命名 BaseModel 建模（dict/list 裸注解）的路由。
# 目标 = 防增量：新路由一律要声明 response_model=<命名 Pydantic 模型>；
# 给老路由补上模型后，请把对应条目从这里移除（allowlist 只减不增）。
RESPONSE_MODEL_ALLOWLIST: frozenset[str] = frozenset({
    "POST /api/v1/browser/render",
    "DELETE /api/v1/sessions/{session_id}",
    "GET /api/v1/factories",
    "GET /api/v1/factories/{factory_id}/detail",
    "GET /api/v1/factories/{factory_id}/quality-trend",
    "GET /api/v1/factories/{factory_id}/rca_history",
    "GET /api/v1/mcp/servers",
    "GET /api/v1/project/context",
    "GET /api/v1/project/diff",
    "GET /api/v1/project/file",
    "GET /api/v1/project/files",
    "GET /api/v1/project/verify",
    "GET /api/v1/projects",
    "GET /api/v1/rca/failure_counter",
    "GET /api/v1/sessions",
    "GET /api/v1/sessions/{session_id}/events",
    "POST /api/v1/mcp/servers/{name}/toggle",
    "POST /api/v1/project/open",
    "POST /api/v1/project/reveal",
    "POST /api/v1/projects",
    # M151 · assistant history 返回 list[AssistantTurn]（命名模型，list 包裹），
    # 契约已命名但本测试的启发式只认直接 BaseModel 子类，故登记。
    # approve/reject 已补 response_model=DecisionResponse，不需要 allowlist。
    "GET /api/v1/assistant/sessions/{session_id}/history",
    # M178.1 · GET /tasks 返回 list[ScheduledTaskResponse]（命名模型，list 包裹），同上登记。
    "GET /api/v1/tasks",
    # M181 · 移动远程控制：HTML 页与 QR SVG 直出 Response（非 JSON 媒体），
    # 无 Pydantic response_model 可挂；其余 5 端点均有命名模型。
    "GET /remote/{token}",
    "GET /api/v1/remote/{token}/qr.svg",
    # M182 · Bot Channel：企业微信回调协议要求明文直出（URL 验证回解密 echostr、
    # 消息回调回 "success"），PlainTextResponse 无 Pydantic 模型可挂；
    # 其余 3 端点（telegram webhook / channels / test）均有命名模型。
    "GET /api/v1/bot/wecom/callback",
    "POST /api/v1/bot/wecom/callback",
})


def test_new_routes_must_have_named_response_model():
    """每个已注册 HTTP 路由：有命名 response_model，或显式登记在 allowlist。"""
    violations: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue  # websocket / 挂载点不在本检查范围
        for method in sorted(route.methods or []):
            if method in ("HEAD", "OPTIONS"):
                continue
            documented = (isinstance(route.response_model, type)
                          and issubclass(route.response_model, BaseModel))
            key = f"{method} {route.path}"
            if not documented and key not in RESPONSE_MODEL_ALLOWLIST:
                violations.append(key)
    assert not violations, (
        "以下路由没有命名 response_model（dict/list 裸注解不算契约）:\n"
        + "\n".join(f"  - {v}" for v in sorted(violations))
        + "\n请给端点声明 response_model=<PydanticModel>；"
          "确属临时端点再把它加进 tests/test_api_contract.py 的 RESPONSE_MODEL_ALLOWLIST。"
    )


# ---------- B2 · 事件 WS ack 语义 ----------

class TestEventsWebsocketAck:
    """事件 WS：ack → ack_ok；垃圾帧/非 JSON 帧不崩连接。"""

    @staticmethod
    def _new_session(c: TestClient) -> str:
        return c.post(f"{API_PREFIX}/sessions", params={"title": "ack"}).json()["id"]

    def test_ack_frame_gets_ack_ok(self):
        with TestClient(app) as c:
            sid = self._new_session(c)
            with c.websocket_connect(f"{API_PREFIX}/sessions/{sid}/events") as ws:
                replayed = ws.receive_json()  # 建会话时的 status 事件回放
                assert "id" in replayed
                ws.send_json({"type": "ack", "last_event_id": replayed["id"]})
                reply = ws.receive_json()
                assert reply == {"type": "ack_ok", "last_event_id": replayed["id"]}

    def test_ack_unknown_id_still_ok(self):
        """ack 是尽力而为的断点确认：未知 id 也回执（客户端据此对齐水位）。"""
        with TestClient(app) as c:
            sid = self._new_session(c)
            with c.websocket_connect(f"{API_PREFIX}/sessions/{sid}/events") as ws:
                ws.receive_json()  # 回放
                ws.send_json({"type": "ack", "last_event_id": "evt-does-not-exist"})
                reply = ws.receive_json()
                assert reply == {"type": "ack_ok", "last_event_id": "evt-does-not-exist"}

    def test_garbage_frames_do_not_crash(self):
        with TestClient(app) as c:
            sid = self._new_session(c)
            with c.websocket_connect(f"{API_PREFIX}/sessions/{sid}/events") as ws:
                ws.receive_json()  # 回放
                ws.send_text("this is not json at all")   # 非 JSON 文本帧
                ws.send_text("[1, 2, 3]")                  # 合法 JSON 但不是对象
                ws.send_json({"type": "ping"})             # 已知但无操作的类型
                # 连接必须仍活着：ack 仍能拿到回执
                ws.send_json({"type": "ack", "last_event_id": "evt-00000007"})
                reply = ws.receive_json()
                assert reply["type"] == "ack_ok"
                assert reply["last_event_id"] == "evt-00000007"

    def test_existing_message_flow_unaffected(self):
        """回归：未知 type 仍按用户消息事件转发（既有行为不破坏）。"""
        with TestClient(app) as c:
            sid = self._new_session(c)
            with c.websocket_connect(f"{API_PREFIX}/sessions/{sid}/events") as ws:
                ws.receive_json()  # 回放
                ws.send_json({"type": "chat", "text": "hello"})
                echoed = ws.receive_json()  # _handle_client_message emit 后广播回来
                assert echoed["type"] == "message"
                assert echoed["payload"]["text"] == "hello"
