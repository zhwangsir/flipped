"""M7.3 — 真实 MCP 服务器注册表。

提供给 Console 的 MCP 面板：真实服务器列表 + 持久化开关，
并把已启用的服务器转成 OpenHands Agent 需要的 mcp_config。

- 列表来自真实的配置文件（首次运行写入种子），非 mock。
- flipped 内置服务器的工具名通过内省 `mcp_server.tools.TOOLS` 得到（真实）。
- 开关状态持久化到磁盘，重启后仍生效。
- 已启用项经 `enabled_mcp_config()` 传给沙盒 Agent，真正影响其可用工具。
"""
from __future__ import annotations

import json
import os
from typing import Any

_DEFAULT_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "config", "mcp_servers.json")
)


def _config_path() -> str:
    return os.environ.get("FLIPPED_MCP_CONFIG_PATH", _DEFAULT_PATH)


def _seed() -> dict[str, Any]:
    """真实、标准的 MCP 服务器定义（真实启动命令），默认全部关闭。

    默认关闭可保证不改变已验证的沙盒执行路径；用户开启后才注入 Agent。
    """
    return {
        "flipped": {
            "description": "flipped 内置：联网搜索 / RAG / 编排编码",
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "mcp_server"],
            "enabled": False,
        },
        "fetch": {
            "description": "抓取网页为上下文（mcp-server-fetch）",
            "transport": "stdio",
            "command": "uvx",
            "args": ["mcp-server-fetch"],
            "tool_count": 1,
            "enabled": False,
        },
        "filesystem": {
            "description": "读写沙盒文件（@modelcontextprotocol/server-filesystem）",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
            "tool_count": 11,
            "enabled": False,
        },
        "git": {
            "description": "分支 / 提交 / diff（mcp-server-git）",
            "transport": "stdio",
            "command": "uvx",
            "args": ["mcp-server-git", "--repository", "/workspace"],
            "tool_count": 13,
            "enabled": False,
        },
    }


def _save(data: dict[str, Any]) -> None:
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load() -> dict[str, Any]:
    path = _config_path()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    data = _seed()
    _save(data)
    return data


def _flipped_tools() -> list[str]:
    """内省 flipped MCP server 真实暴露的工具名。"""
    try:
        import sys

        src_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
        from mcp_server.tools import TOOLS  # noqa: WPS433

        return [t.name for t in TOOLS]
    except Exception:  # noqa: BLE001 — 内省失败不应影响列表接口
        return []


def list_servers() -> list[dict[str, Any]]:
    """返回真实 MCP 服务器列表（含持久化开关状态与真实工具信息）。"""
    data = _load()
    out: list[dict[str, Any]] = []
    for name, cfg in data.items():
        tools = _flipped_tools() if name == "flipped" else []
        out.append(
            {
                "name": name,
                "description": cfg.get("description", ""),
                "transport": cfg.get("transport", "stdio"),
                "enabled": bool(cfg.get("enabled", False)),
                "tools": tools,
                "tool_count": len(tools) if tools else int(cfg.get("tool_count", 0)),
            }
        )
    return out


def toggle_server(name: str, enabled: bool) -> dict[str, Any]:
    """持久化切换某个服务器的启用状态。未知名称抛 KeyError。"""
    data = _load()
    if name not in data:
        raise KeyError(name)
    data[name] = {**data[name], "enabled": bool(enabled)}
    _save(data)
    return {"name": name, "enabled": bool(enabled)}


def enabled_mcp_config() -> dict[str, Any]:
    """把已启用的服务器转成 OpenHands Agent 的 mcp_config。

    仅注入 enabled 且 sandbox_ready 的服务器。当前种子服务器（flipped/fetch/
    filesystem/git）以 stdio 方式定义，无法在 OpenHands Docker 沙盒内启动，
    强行注入会让 agent 在 MCP 列举阶段挂起 30s 并 500 崩溃。故默认都不 sandbox_ready：
    开关仍真实持久化，但不会把不可用的 MCP 注入沙盒、拖垮 agent 执行。
    未来某个服务器做成沙盒可达（如 http 传输）后，将其 sandbox_ready 置 True 即自动注入。

    无可注入项时返回 {}，使 Agent 行为与不传 mcp_config 完全一致。
    """
    data = _load()
    servers: dict[str, Any] = {}
    for name, cfg in data.items():
        if not cfg.get("enabled") or not cfg.get("sandbox_ready"):
            continue
        if cfg.get("transport") == "http" and cfg.get("url"):
            entry: dict[str, Any] = {"url": cfg["url"]}
        else:
            entry = {"command": cfg.get("command", "")}
            if cfg.get("args"):
                entry["args"] = list(cfg["args"])
            if cfg.get("env"):
                entry["env"] = dict(cfg["env"])
        servers[name] = entry
    return {"mcpServers": servers} if servers else {}
