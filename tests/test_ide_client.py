"""IDE 控制面桥客户端 · 纯逻辑单测（无需扩展宿主）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from driving.ide_client import build_tool_request, parse_tool_response  # noqa: E402


def test_build_request():
    assert build_tool_request("ide.runTask", {"name": "build"}) == {
        "name": "ide.runTask", "args": {"name": "build"}}
    assert build_tool_request("x") == {"name": "x", "args": {}}


def test_parse_ok():
    assert parse_tool_response({"ok": True, "result": {"a": 1}}) == {"a": 1}
    assert parse_tool_response({"ok": True}) is None


def test_parse_error_raises():
    for bad in ({"ok": False, "error": "boom"}, {"ok": False}, {}):
        try:
            parse_tool_response(bad)
        except RuntimeError:
            continue
        raise AssertionError(f"{bad} 应抛 RuntimeError")


if __name__ == "__main__":
    test_build_request()
    test_parse_ok()
    test_parse_error_raises()
    print("ide_client 单测: 全部通过 ✅（构建请求 / 解析成功 / 解析错误抛异常）")
