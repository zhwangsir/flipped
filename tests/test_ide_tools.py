"""M141 · IDE 控制面工具面接入驾驭层 · TDD 单测（全确定性，无需 VS Code 宿主）。

覆盖：注册表漂移守门 / render 映射 / 五级管线权限矩阵 / governed 执行与异常 / factory_events 审计。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from driving.event_log import append_event, ensure_event_table, list_events  # noqa: E402
from driving.ide_tools import (  # noqa: E402
    IDE_TOOL_REGISTRY,
    IdeCallResult,
    governed_ide_call,
    render_ide_action,
)

# 与 ide-extension/src/extension.ts 的 tools 表对齐（漂移守门：改一侧必须改另一侧）
EXPECTED_TOOLS = {
    "ide.runTask": ["name"],
    "ide.openTerminal": [],
    "ide.getSetting": ["section"],
    "ide.updateSetting": ["section", "value"],
    "ide.installExtension": ["id"],
    "ide.runCommand": ["commandId"],
    "env.addDevcontainerFeature": ["feature"],
    "env.miseUse": ["tool", "version"],
    "env.rebuildDevcontainer": [],
}


def _fake_caller_ok(name, args):
    return {"echo": name, "args": args}


def _fake_caller_boom(name, args):
    raise RuntimeError("bridge down")


class _Recorder:
    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else {"ok": True}

    def __call__(self, name, args):
        self.calls.append((name, args))
        return self.result


# ---------- M141.1 · 注册表 ----------


def test_registry_matches_extension_tools():
    assert set(IDE_TOOL_REGISTRY) == set(EXPECTED_TOOLS), "注册表与 extension.ts 工具表漂移"
    for name, required in EXPECTED_TOOLS.items():
        spec = IDE_TOOL_REGISTRY[name]
        assert spec["required"] == required, f"{name} 必填参漂移"
        assert spec["description"], f"{name} 缺 description"


def test_render_unknown_tool_raises():
    with pytest.raises(KeyError):
        render_ide_action("ide.nope", {})


# ---------- M141.1 · render 映射 ----------


def test_render_action_mapping():
    assert render_ide_action("ide.runTask", {"name": "build"}) == "ide runTask build"
    assert render_ide_action("ide.openTerminal", {"name": "t1"}) == "ide openTerminal"
    assert render_ide_action("ide.getSetting", {"section": "editor.fontSize"}) == \
        "ide getSetting editor.fontSize"
    assert render_ide_action("ide.updateSetting", {"section": "x", "value": 1}) == "ide updateSetting x"
    assert render_ide_action("ide.installExtension", {"id": "a.b"}) == "installExtension a.b"
    assert render_ide_action("ide.runCommand", {"commandId": "workbench.files.new"}) == \
        "ide runCommand workbench.files.new"
    assert render_ide_action("env.addDevcontainerFeature", {"feature": "node"}) == \
        "env addDevcontainerFeature node"
    assert render_ide_action("env.miseUse", {"tool": "python", "version": "3.12"}) == \
        "env miseUse python 3.12"
    assert render_ide_action("env.rebuildDevcontainer", {}) == "devcontainer rebuild"


def test_render_open_terminal_command_passthrough():
    """安全关键：openTerminal 带 command 时渲染为命令本体，让管线直接评估真实命令。"""
    assert render_ide_action("ide.openTerminal", {"command": "rm -rf /"}) == "rm -rf /"
    assert render_ide_action("ide.openTerminal", {"command": "  git status  "}) == "git status"


# ---------- M141.2 · 权限矩阵（governed 不执行 deny/ask） ----------


@pytest.mark.parametrize("name,args", [
    ("ide.openTerminal", {"command": "rm -rf /"}),
    ("ide.openTerminal", {"command": "sudo apt update"}),
    ("ide.openTerminal", {"command": "git push --force origin main"}),
])
def test_deny_matrix_never_executes(name, args):
    rec = _Recorder()
    r = governed_ide_call(name, args, caller=rec)
    assert r.decision == "deny", f"{args} 应 deny，实际 {r.decision}（{r.reason}）"
    assert rec.calls == [], "deny 路径绝不允许执行"
    assert r.result is None


@pytest.mark.parametrize("name,args", [
    ("ide.installExtension", {"id": "ms-python.python"}),
    ("ide.runCommand", {"commandId": "workbench.action.reloadWindow"}),
    ("ide.updateSetting", {"section": "editor.fontSize", "value": 14}),
    ("env.rebuildDevcontainer", {}),
    ("ide.openTerminal", {"command": "git push origin feature"}),
])
def test_ask_matrix_never_executes(name, args):
    rec = _Recorder()
    r = governed_ide_call(name, args, caller=rec)
    assert r.decision == "ask", f"{args} 应 ask，实际 {r.decision}（{r.reason}）"
    assert rec.calls == [], "ask 路径绝不允许直接执行（需人工放行后重调）"
    assert r.result is None


@pytest.mark.parametrize("name,args", [
    ("ide.getSetting", {"section": "editor.fontSize"}),
    ("ide.runTask", {"name": "build"}),
    ("ide.openTerminal", {"name": "t1"}),
    ("ide.openTerminal", {"command": "git status"}),
    ("ide.openTerminal", {"command": "ls -la"}),
    ("env.addDevcontainerFeature", {"feature": "ghcr.io/devcontainers/features/node:1"}),
    ("env.miseUse", {"tool": "python", "version": "3.12"}),
])
def test_allow_matrix_executes(name, args):
    rec = _Recorder(result={"done": 1})
    r = governed_ide_call(name, args, caller=rec)
    assert r.decision == "allow", f"{args} 应 allow，实际 {r.decision}（{r.reason}）"
    assert rec.calls == [(name, args)], "allow 路径必须执行一次且透传参数"
    assert r.result == {"done": 1}
    assert r.error is None


def test_chained_command_deny_segment_wins():
    """链式命令：任一分段 deny → 整体 deny（evaluate_command 语义）。"""
    rec = _Recorder()
    r = governed_ide_call("ide.openTerminal", {"command": "ls && rm -rf /"}, caller=rec)
    assert r.decision == "deny"
    assert rec.calls == []


# ---------- M141.2 · 执行异常 fail-open ----------


def test_caller_exception_captured_in_error():
    r = governed_ide_call("ide.getSetting", {"section": "x"}, caller=_fake_caller_boom)
    assert r.decision == "allow"
    assert r.result is None
    assert "bridge down" in (r.error or ""), "桥不可用等执行异常进 error，不上抛"


def test_result_dataclass_defaults():
    r = IdeCallResult("deny", "L2", "规则命中")
    assert r.result is None and r.error is None


# ---------- M141.2 · factory_events 审计 ----------


def _tmp_conn(td: str):
    conn = sqlite3.connect(str(Path(td) / "audit.db"))
    ensure_event_table(conn)
    return conn


def test_audit_records_allow_and_deny():
    with tempfile.TemporaryDirectory() as td:
        conn = _tmp_conn(td)
        governed_ide_call("ide.getSetting", {"section": "x"}, caller=_fake_caller_ok,
                          audit_conn=conn, factory_id="f1")
        governed_ide_call("ide.openTerminal", {"command": "rm -rf /"}, caller=_fake_caller_ok,
                          audit_conn=conn, factory_id="f1")
        events = list_events(conn, "f1")
        conn.close()
    kinds = [e["kind"] for e in events]
    assert kinds == ["ide_tool_call", "ide_tool_call"], "allow/deny 都应留痕"
    allow_ev, deny_ev = events
    assert allow_ev["payload"]["decision"] == "allow"
    assert allow_ev["payload"]["name"] == "ide.getSetting"
    assert deny_ev["payload"]["decision"] == "deny"
    assert deny_ev["payload"]["reason"], "deny 必须记录拦截理由"


def test_audit_optional_no_crash():
    """不给 audit_conn/factory_id 时审计跳过，不影响调用。"""
    r = governed_ide_call("ide.runTask", {"name": "b"}, caller=_fake_caller_ok)
    assert r.decision == "allow"
    r2 = governed_ide_call("ide.runTask", {"name": "b"}, caller=_fake_caller_ok,
                           audit_conn=None, factory_id="f1")
    assert r2.decision == "allow"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
