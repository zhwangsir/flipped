"""驾驭层 → IDE 控制面桥客户端（D13）：经本地 HTTP(127.0.0.1) 调 ide-extension 工具。

让多Agent编排在真实 IDE 里驱动子系统（终端/任务/设置/扩展/环境）。
`build_tool_request` / `parse_tool_response` 是纯函数（可单测）；`call_ide_tool` 走网络（需扩展宿主在跑）。
"""
from __future__ import annotations

import json
import urllib.request

DEFAULT_BRIDGE = "http://127.0.0.1:39217"


def build_tool_request(name: str, args: dict | None = None) -> dict:
    return {"name": name, "args": args or {}}


def parse_tool_response(d: dict) -> object:
    if not isinstance(d, dict) or not d.get("ok"):
        raise RuntimeError((d or {}).get("error", "ide tool failed"))
    return d.get("result")


def call_ide_tool(name: str, args: dict | None = None, *,
                  base_url: str = DEFAULT_BRIDGE, timeout: int = 120) -> object:
    """调一个 IDE 控制面工具，返回 result（失败抛 RuntimeError）。需 ide-extension 宿主在跑。"""
    payload = json.dumps(build_tool_request(name, args)).encode()
    req = urllib.request.Request(base_url + "/tool", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse_tool_response(json.load(r))
