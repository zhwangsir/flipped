"""Tests for the MCP server registry (M7.3)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.mcp_registry import (  # noqa: E402
    enabled_mcp_config,
    list_servers,
    toggle_server,
)


@pytest.fixture
def tmp_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIPPED_MCP_CONFIG_PATH", str(tmp_path / "mcp_servers.json"))


def test_list_servers_seed_has_real_flipped_tools(tmp_cfg):
    servers = list_servers()
    names = {s["name"] for s in servers}
    assert {"flipped", "fetch", "filesystem", "git"} <= names
    flipped = next(s for s in servers if s["name"] == "flipped")
    # flipped 工具名来自真实内省 mcp_server.tools.TOOLS
    assert "web_search" in flipped["tools"]
    assert flipped["tool_count"] == len(flipped["tools"]) >= 3
    # 种子默认全部关闭，保证不改变已验证的执行路径
    assert all(s["enabled"] is False for s in servers)


def test_enabled_config_empty_by_default(tmp_cfg):
    assert enabled_mcp_config() == {}


def test_toggle_persists_and_builds_config(tmp_cfg):
    toggle_server("flipped", True)
    # 持久化：重新读取仍启用
    assert next(s["enabled"] for s in list_servers() if s["name"] == "flipped") is True
    assert enabled_mcp_config() == {
        "mcpServers": {"flipped": {"command": "python", "args": ["-m", "mcp_server"]}}
    }
    # 关闭后回到空配置
    toggle_server("flipped", False)
    assert enabled_mcp_config() == {}


def test_toggle_unknown_raises(tmp_cfg):
    with pytest.raises(KeyError):
        toggle_server("does-not-exist", True)
