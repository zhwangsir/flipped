"""tui.__main__ 入口单测 — 验证 `python -m tui` 派发到 tui.app.main()。

覆盖目标（src/tui/__main__.py）：
  - 模块导入时应调用 tui.app.main()（`python -m tui` 的入口契约）

设计原则（呼应 AGENTS.md §3）：
  - 不真启动 TUI（会阻塞事件循环）；用 importlib.reload + monkeypatch 注入
  - 验证 main 被调用且仅调用一次（入口契约不可破坏）
"""
from __future__ import annotations

import importlib
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tui.app  # noqa: E402


def test_tui_main_entry_calls_app_main(monkeypatch):
    """正常路径：导入 tui.__main__ 时必须调用 tui.app.main()。

    用 monkeypatch 把 tui.app.main 替换成计数器，再 reload __main__ 模块。
    reload 会重新执行模块顶层代码 `from tui.app import main; main()`，
    其中 `main` 是 reload 时新绑定的（来自已 patch 的 tui.app.main）。
    """
    call_count = [0]

    def _fake_main():
        call_count[0] += 1

    # 关键：patch tui.app.main 后再 reload，让 __main__ 重新 from ... import main
    monkeypatch.setattr(tui.app, "main", _fake_main)

    # 若 __main__ 已被之前的测试导入过，先清理 sys.modules 让 reload 生效
    sys.modules.pop("tui.__main__", None)

    try:
        importlib.import_module("tui.__main__")
    finally:
        sys.modules.pop("tui.__main__", None)

    assert call_count[0] == 1, (
        f"`python -m tui` 应调用 tui.app.main() 一次；实际 {call_count[0]} 次"
    )


def test_tui_main_entry_does_not_crash_when_main_raises(monkeypatch):
    """异常场景：tui.app.main 抛异常时，__main__ 不应吞掉（让进程退出码非 0）。

    锁定行为：入口不对 main() 做异常包装，异常应直接传播（让 python -m tui 失败时
    有可见 traceback，而不是静默退出）。
    """
    def _boom():
        raise RuntimeError("tui crashed")

    monkeypatch.setattr(tui.app, "main", _boom)
    sys.modules.pop("tui.__main__", None)

    try:
        importlib.import_module("tui.__main__")
        raise AssertionError("main 抛异常时应直接传播，不应被吞掉")
    except RuntimeError as e:
        assert "tui crashed" in str(e)
    finally:
        sys.modules.pop("tui.__main__", None)
