"""M143 · 真实 IDE 桥验收矩阵（真实 VS Code Extension Development Host + governed 五级管线）。

前置：scripts/verify_m143_ide_bridge.sh 已起隔离 Extension Development Host，
桥在 127.0.0.1:39217 应答（该脚本负责轮询就绪后再调本脚本）。

用法: .venv/bin/python scripts/verify_m143_ide_bridge.py --db <tmp.db> --ws <隔离工作区路径>
退出码: 0 = CORE 全绿；1 = 有失败。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from driving.event_log import ensure_event_table, list_events  # noqa: E402
from driving.ide_client import call_ide_tool  # noqa: E402
from driving.ide_tools import governed_ide_call  # noqa: E402

FACTORY_ID = "m143-ide-bridge"
fail = 0


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def bad(msg: str) -> None:
    global fail
    print(f"  ❌ {msg}")
    fail = 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="审计落库 tmp sqlite 路径")
    ap.add_argument("--base-url", default="http://127.0.0.1:39217", help="IDE 桥地址")
    ap.add_argument("--ws", required=True, help="隔离验收工作区路径（读回 .mise.toml / devcontainer.json 断言用）")
    args = ap.parse_args()
    ws = Path(args.ws)

    def _caller(name: str, args_: dict | None = None):
        return call_ide_tool(name, args_, base_url=args.base_url, timeout=15)
    caller = _caller

    conn = sqlite3.connect(args.db)
    ensure_event_table(conn)

    print("== [1/12] 桥应答：raw ide.getSetting 读回工作区标记值 ==")
    try:
        v = caller("ide.getSetting", {"section": "editor.fontSize"})
        if v == 13:
            ok(f"editor.fontSize={v}（.vscode/settings.json 标记值真实读回）")
        else:
            bad(f"editor.fontSize={v!r} ≠ 13（桥通了但值不符）")
    except Exception as e:  # noqa: BLE001
        bad(f"桥调用失败: {type(e).__name__}: {e}")

    print("== [2/12] governed allow（真实读）==")
    r = governed_ide_call("ide.getSetting", {"section": "editor.fontSize"}, caller=caller,
                          audit_conn=conn, factory_id=FACTORY_ID)
    if r.decision == "allow" and r.result == 13 and r.error is None:
        ok(f"decision=allow, result={r.result}")
    else:
        bad(f"decision={r.decision} result={r.result!r} error={r.error}")

    print("== [3/12] governed allow（真实执行：IDE 开终端）==")
    r = governed_ide_call("ide.openTerminal", {"name": "m143-probe"}, caller=caller,
                          audit_conn=conn, factory_id=FACTORY_ID)
    if r.decision == "allow" and r.error is None:
        ok(f"decision=allow, result={r.result}")
    else:
        bad(f"decision={r.decision} result={r.result!r} error={r.error}")

    print("== [4/12] governed deny（rm -rf / 绝不进桥）==")
    r = governed_ide_call("ide.openTerminal", {"command": "rm -rf /"}, caller=caller,
                          audit_conn=conn, factory_id=FACTORY_ID)
    if r.decision == "deny" and r.result is None:
        ok(f"decision=deny, reason={r.reason}")
    else:
        bad(f"decision={r.decision} result={r.result!r}（应为 deny 且零执行）")

    print("== [5/12] deny 后桥无损（raw getSetting 再通）==")
    try:
        v = caller("ide.getSetting", {"section": "editor.fontSize"})
        ok(f"桥仍正常应答（fontSize={v}）") if v == 13 else bad(f"fontSize={v!r} ≠ 13")
    except Exception as e:  # noqa: BLE001
        bad(f"deny 后桥异常: {type(e).__name__}: {e}")

    print("== [6/12] governed ask（updateSetting 不执行，等人工）==")
    r = governed_ide_call("ide.updateSetting", {"section": "editor.fontSize", "value": 99}, caller=caller,
                          audit_conn=conn, factory_id=FACTORY_ID)
    if r.decision == "ask" and r.result is None:
        ok(f"decision=ask, reason={r.reason}")
    else:
        bad(f"decision={r.decision} result={r.result!r}（应为 ask 且零执行）")
    print("== [7/12] ask 零执行佐证：fontSize 未被改 ==")
    try:
        v = caller("ide.getSetting", {"section": "editor.fontSize"})
        ok("ask 零执行佐证：fontSize 仍为 13") if v == 13 else bad(f"fontSize 被改为 {v!r}！ask 路径泄漏执行")
    except Exception as e:  # noqa: BLE001
        bad(f"读回校验失败: {e}")

    print("== [8/12] governed allow（真实执行：ide.runTask 跑无害 echo 任务）==")
    r = governed_ide_call("ide.runTask", {"name": "m144-echo"}, caller=caller,
                          audit_conn=conn, factory_id=FACTORY_ID)
    # tasks.executeTask 返回对象序列化后 result 可能是 {}，不断言 result 内容
    if r.decision == "allow" and r.error is None:
        ok(f"decision=allow, result={r.result}")
    else:
        bad(f"decision={r.decision} result={r.result!r} error={r.error}")

    print("== [9/12] governed allow（真实执行：env.miseUse 钉 python 3.12）==")
    r = governed_ide_call("env.miseUse", {"tool": "python", "version": "3.12"}, caller=caller,
                          audit_conn=conn, factory_id=FACTORY_ID)
    if r.decision == "allow" and r.error is None:
        ok(f"decision=allow, result={r.result}")
    else:
        bad(f"decision={r.decision} result={r.result!r} error={r.error}")
    # 真实读回工作区 .mise.toml 佐证
    mise_file = ws / ".mise.toml"
    if mise_file.is_file():
        mise_text = mise_file.read_text(encoding="utf-8")
        if "python" in mise_text and "3.12" in mise_text:
            ok(f".mise.toml 真实落盘: {mise_text.strip()!r}")
        else:
            bad(f".mise.toml 内容不符: {mise_text!r}（应含 python 与 3.12）")
    else:
        bad(f".mise.toml 未生成: {mise_file}")

    print("== [10/12] governed allow（真实执行：env.addDevcontainerFeature 加 python）==")
    r = governed_ide_call("env.addDevcontainerFeature", {"feature": "python", "version": "3.12"},
                          caller=caller, audit_conn=conn, factory_id=FACTORY_ID)
    if r.decision == "allow" and r.error is None:
        ok(f"decision=allow, result={r.result}")
    else:
        bad(f"decision={r.decision} result={r.result!r} error={r.error}")
    # 真实读回 .devcontainer/devcontainer.json 佐证 features 含 python 键
    dc_file = ws / ".devcontainer" / "devcontainer.json"
    if dc_file.is_file():
        try:
            import json
            dc = json.loads(dc_file.read_text(encoding="utf-8"))
            feats = dc.get("features") or {}
            py_keys = [k for k in feats if "python" in k]
            if py_keys:
                ok(f"devcontainer.json features 含 python 键: {py_keys}")
            else:
                bad(f"devcontainer.json features 无 python 键: {feats}")
        except Exception as e:  # noqa: BLE001
            bad(f"devcontainer.json 解析失败: {type(e).__name__}: {e}")
    else:
        bad(f"devcontainer.json 未生成: {dc_file}")

    print("== [11/12] governed ask 零执行 ×3（installExtension / runCommand / rebuildDevcontainer）==")
    for name, a in [
        ("ide.installExtension", {"id": "ms-python.python"}),
        ("ide.runCommand", {"commandId": "workbench.action.reloadWindow"}),
        ("env.rebuildDevcontainer", {}),
    ]:
        r = governed_ide_call(name, a, caller=caller, audit_conn=conn, factory_id=FACTORY_ID)
        if r.decision == "ask" and r.result is None:
            ok(f"{name}: decision=ask 零执行, reason={r.reason}")
        else:
            bad(f"{name}: decision={r.decision} result={r.result!r}（应为 ask 且零执行）")

    print("== [12/12] 审计：10 条 ide_tool_call 事件（allow×5 + deny×1 + ask×4）==")
    events = list_events(conn, FACTORY_ID)
    kinds = [e["kind"] for e in events]
    decisions = [e["payload"].get("decision") for e in events]
    names = [e["payload"].get("name") for e in events]
    expected = [
        ("ide.getSetting", "allow"),
        ("ide.openTerminal", "allow"),
        ("ide.openTerminal", "deny"),
        ("ide.updateSetting", "ask"),
        ("ide.runTask", "allow"),
        ("env.miseUse", "allow"),
        ("env.addDevcontainerFeature", "allow"),
        ("ide.installExtension", "ask"),
        ("ide.runCommand", "ask"),
        ("env.rebuildDevcontainer", "ask"),
    ]
    if kinds == ["ide_tool_call"] * 10 and list(zip(names, decisions)) == expected:
        ok(f"10 事件全留痕: {list(zip(names, decisions))}")
    else:
        bad(f"事件不符: kinds={kinds} got={list(zip(names, decisions))}")
    conn.close()

    print()
    print("M143 真实 IDE 桥验收矩阵：通过 ✅" if fail == 0 else "M143 真实 IDE 桥验收矩阵：有未通过 ❌")
    return fail


if __name__ == "__main__":
    sys.exit(main())
