"""api.terminal 单元测试 — 真 pty 终端桥（WebSocket ↔ 交互式 shell）。

覆盖目标函数（src/api/terminal.py）：
  - _set_winsize(fd, rows, cols): TIOCSWINSZ ioctl + OSError 吞掉
  - _preexec(): os.setsid + TIOCSCTTY + OSError 吞掉
  - _spawn_shell(): pty.openpty + subprocess.Popen + cwd/SHELL/env/preexec_fn
  - terminal_bridge(ws): accept / 输入 'd' 写 pty / resize 'r' / 坏 JSON 忽略 /
    WebSocketDisconnect 清理 / EOF 关闭 ws / cleanup（killpg+close）

设计原则（呼应 AGENTS.md §3）：
  - 不起真 pty、不开真 WebSocket；全部用 monkeypatch + AsyncMock 注入
  - 不写空壳断言；每个用例验证 ≥1 个真实行为
  - 失败不准注释、不准改宽断言
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import WebSocketDisconnect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api import terminal  # noqa: E402


# ===========================================================================
# _set_winsize
# ===========================================================================

def test_set_winsize_packs_rows_cols_via_ioctl(monkeypatch):
    """正常路径：fcntl.ioctl 被调用，参数是 struct.pack('HHHH', rows, cols, 0, 0)。"""
    captured: list = []
    monkeypatch.setattr(terminal.fcntl, "ioctl", lambda fd, cmd, payload: captured.append((fd, cmd, payload)))

    terminal._set_winsize(fd=42, rows=30, cols=120)

    assert len(captured) == 1
    fd, cmd, payload = captured[0]
    assert fd == 42
    assert cmd == terminal.termios.TIOCSWINSZ
    # struct.pack("HHHH", rows, cols, 0, 0) —— 注意函数签名是 (fd, rows, cols)
    expected = struct.pack("HHHH", 30, 120, 0, 0)
    assert payload == expected, f"打包应为 rows=30, cols=120；实际 {payload!r}"


def test_set_winsize_default_args_zero(monkeypatch):
    """边界：rows/cols=0 也应正常打包（不抛）。"""
    captured: list = []
    monkeypatch.setattr(terminal.fcntl, "ioctl", lambda fd, cmd, payload: captured.append(payload))
    terminal._set_winsize(fd=1, rows=0, cols=0)
    assert captured == [struct.pack("HHHH", 0, 0, 0, 0)]


def test_set_winsize_swallows_oserror(monkeypatch):
    """异常场景：fcntl.ioctl 抛 OSError 时必须被吞掉（不传播到调用方）。"""
    def _raise(*a, **kw):
        raise OSError("invalid fd")
    monkeypatch.setattr(terminal.fcntl, "ioctl", _raise)
    # 不抛即通过
    terminal._set_winsize(fd=999, rows=24, cols=80)


# ===========================================================================
# _preexec
# ===========================================================================

def test_preexec_calls_setsid_and_tty(monkeypatch):
    """正常路径：os.setsid() + fcntl.ioctl(0, TIOCSCTTY, 0) 都被调用。"""
    calls: list = []
    monkeypatch.setattr(terminal.os, "setsid", lambda: calls.append("setsid"))
    monkeypatch.setattr(terminal.fcntl, "ioctl", lambda fd, cmd, arg: calls.append(("ioctl", fd, cmd, arg)))

    terminal._preexec()

    assert "setsid" in calls
    assert any(c[0] == "ioctl" and c[1] == 0 for c in calls), f"TIOCSCTTY 应在 fd=0 上调用；实际 {calls}"
    # 验证 TIOCSCTTY 是从 termios 取的常量
    ioctl_call = next(c for c in calls if isinstance(c, tuple) and c[0] == "ioctl")
    assert ioctl_call[2] == terminal._TIOCSCTTY
    assert ioctl_call[3] == 0


def test_preexec_swallows_oserror_on_tty(monkeypatch):
    """异常场景：TIOCSCTTY ioctl 抛 OSError（如容器无 controlling tty）时不应传播。"""
    monkeypatch.setattr(terminal.os, "setsid", lambda: None)

    def _raise(fd, cmd, arg):
        raise OSError("no controlling terminal")
    monkeypatch.setattr(terminal.fcntl, "ioctl", _raise)

    # 不抛即通过
    terminal._preexec()


def test_preexec_skips_tty_when_no_tiocsctty(monkeypatch):
    """边界：termios 没有 TIOCSCTTY 时（_TIOCSCTTY=None）应跳过 ioctl(0, TIOCSCTTY, 0)。"""
    monkeypatch.setattr(terminal.os, "setsid", lambda: None)
    ioctl_calls: list = []
    monkeypatch.setattr(terminal.fcntl, "ioctl", lambda fd, cmd, arg: ioctl_calls.append((fd, cmd, arg)))
    monkeypatch.setattr(terminal, "_TIOCSCTTY", None)

    terminal._preexec()

    assert ioctl_calls == [], "TIOCSCTTY 为 None 时不应调 fcntl.ioctl"


# ===========================================================================
# _spawn_shell
# ===========================================================================

def test_spawn_shell_returns_master_fd_and_proc(monkeypatch):
    """正常路径：返回 (master_fd, proc)，slave_fd 被关闭。"""
    monkeypatch.setattr(terminal.pty, "openpty", lambda: (123, 124))
    monkeypatch.setattr(terminal, "_set_winsize", lambda fd, r, c: None)
    close_calls: list = []
    monkeypatch.setattr(terminal.os, "close", lambda fd: close_calls.append(fd))

    fake_proc = MagicMock()
    captured: dict = {}

    def _popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return fake_proc

    monkeypatch.setattr(terminal.subprocess, "Popen", _popen)
    monkeypatch.delenv("SHELL", raising=False)

    master_fd, proc = terminal._spawn_shell()

    assert master_fd == 123
    assert proc is fake_proc
    assert close_calls == [124], "slave_fd 必须被关闭，避免父进程读写出错"
    assert captured["argv"] == ["/bin/bash", "-i"], "SHELL 未设置时应回退 /bin/bash"


def test_spawn_shell_respects_shell_env(monkeypatch, monkeypatch_env_shell="/bin/zsh"):
    """边界：SHELL 环境变量覆盖默认 /bin/bash。"""
    monkeypatch.setattr(terminal.pty, "openpty", lambda: (10, 11))
    monkeypatch.setattr(terminal, "_set_winsize", lambda fd, r, c: None)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setenv("SHELL", "/bin/zsh")

    captured: dict = {}
    monkeypatch.setattr(
        terminal.subprocess, "Popen",
        lambda argv, **kw: (captured.update(argv=argv, kwargs=kw), MagicMock())[1],
    )

    terminal._spawn_shell()
    assert captured["argv"] == ["/bin/zsh", "-i"]


def test_spawn_shell_sets_term_env_and_preexec(monkeypatch):
    """边界：env 含 TERM=xterm-256color；preexec_fn=_preexec 被传入（保证 Ctrl-C 生效）。"""
    monkeypatch.setattr(terminal.pty, "openpty", lambda: (10, 11))
    monkeypatch.setattr(terminal, "_set_winsize", lambda fd, r, c: None)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)

    captured: dict = {}
    monkeypatch.setattr(
        terminal.subprocess, "Popen",
        lambda argv, **kw: (captured.update(argv=argv, kwargs=kw), MagicMock())[1],
    )

    terminal._spawn_shell()

    env = captured["kwargs"]["env"]
    assert env["TERM"] == "xterm-256color"
    assert captured["kwargs"]["preexec_fn"] is terminal._preexec
    assert captured["kwargs"]["stdin"] == 11
    assert captured["kwargs"]["stdout"] == 11
    assert captured["kwargs"]["stderr"] == 11
    assert captured["kwargs"]["close_fds"] is True


def test_spawn_shell_initial_winsize_24x80(monkeypatch):
    """边界：初始 _set_winsize 调用 (master_fd, 24, 80)。"""
    monkeypatch.setattr(terminal.pty, "openpty", lambda: (777, 778))
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    winsize_calls: list = []
    monkeypatch.setattr(terminal, "_set_winsize", lambda fd, r, c: winsize_calls.append((fd, r, c)))
    monkeypatch.setattr(terminal.subprocess, "Popen", lambda argv, **kw: MagicMock())

    terminal._spawn_shell()

    assert winsize_calls == [(777, 24, 80)], "初始窗口大小应为 24 行 80 列"


# ===========================================================================
# terminal_bridge
# ===========================================================================

class _FakeWebSocket:
    """轻量 WebSocket 替身：accept/close 是 AsyncMock；receive_text 按队列返回，空了抛 WebSocketDisconnect。"""

    def __init__(self, messages: list[str]):
        self._messages = list(messages)
        self.accept = AsyncMock()
        self.close = AsyncMock()
        self.send_text = AsyncMock()
        self.sent_texts: list[str] = []

    async def receive_text(self) -> str:
        if not self._messages:
            raise WebSocketDisconnect()
        return self._messages.pop(0)


def _patch_spawn_shell(monkeypatch, master_fd: int = 555, proc_pid: int = 4321) -> MagicMock:
    """让 terminal_bridge 用假 (master_fd, proc)，不真起 pty。"""
    fake_proc = MagicMock()
    fake_proc.pid = proc_pid
    monkeypatch.setattr(terminal, "_spawn_shell", lambda: (master_fd, fake_proc))
    return fake_proc


def _disable_loop_reader(monkeypatch):
    """禁用 loop.add_reader / remove_reader，避免真 fd 注册（测试用假 fd）。"""
    loop = asyncio.get_event_loop()
    monkeypatch.setattr(loop, "add_reader", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(loop, "remove_reader", lambda *a, **kw: False, raising=False)


def test_bridge_accepts_websocket_and_cleans_up_on_disconnect(monkeypatch):
    """正常路径：无消息直接断开 → accept 被调用，cleanup 关闭 master_fd、killpg 进程组。"""
    fake_proc = _patch_spawn_shell(monkeypatch, master_fd=42, proc_pid=999)
    close_calls: list = []
    killpg_calls: list = []
    monkeypatch.setattr(terminal.os, "close", lambda fd: close_calls.append(fd))
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig)))
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 8888)

    ws = _FakeWebSocket(messages=[])

    async def _run():
        _disable_loop_reader(monkeypatch)
        await terminal.terminal_bridge(ws)

    asyncio.run(_run())

    ws.accept.assert_awaited_once()
    assert close_calls == [42], f"master_fd 必须在 finally 关闭；实际 {close_calls}"
    assert killpg_calls == [(8888, terminal.signal.SIGTERM)], f"应 SIGTERM 进程组；实际 {killpg_calls}"


def test_bridge_input_d_writes_to_pty(monkeypatch):
    """输入路径：前端发 {"d": "ls\\n"} → os.write(master_fd, b"ls\\n")。"""
    _patch_spawn_shell(monkeypatch, master_fd=77)
    write_calls: list = []
    monkeypatch.setattr(terminal.os, "write", lambda fd, data: write_calls.append((fd, data)))
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    ws = _FakeWebSocket(messages=[json.dumps({"d": "ls\n"})])

    async def _run():
        _disable_loop_reader(monkeypatch)
        await terminal.terminal_bridge(ws)

    asyncio.run(_run())

    assert write_calls == [(77, b"ls\n")], f"输入应被写入 master_fd；实际 {write_calls}"


def test_bridge_resize_r_calls_set_winsize(monkeypatch):
    """resize 路径：前端发 {"r": [cols, rows]} → _set_winsize(master_fd, rows, cols)。

    注意参数顺序：msg["r"][0]=cols, msg["r"][1]=rows；函数签名是 (fd, rows, cols)。
    """
    _patch_spawn_shell(monkeypatch, master_fd=88)
    winsize_calls: list = []
    monkeypatch.setattr(terminal, "_set_winsize", lambda fd, r, c: winsize_calls.append((fd, r, c)))
    monkeypatch.setattr(terminal.os, "write", lambda fd, data: None)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    ws = _FakeWebSocket(messages=[json.dumps({"r": [120, 40]})])  # [cols=120, rows=40]

    async def _run():
        _disable_loop_reader(monkeypatch)
        await terminal.terminal_bridge(ws)

    asyncio.run(_run())

    assert winsize_calls == [(88, 40, 120)], (
        "msg['r']=[cols, rows] 应转成 _set_winsize(fd, rows, cols)；"
        f"实际 {winsize_calls}"
    )


def test_bridge_invalid_json_is_ignored(monkeypatch):
    """异常场景：坏 JSON 应被静默忽略（continue），下一条合法消息仍能处理。"""
    _patch_spawn_shell(monkeypatch, master_fd=11)
    write_calls: list = []
    monkeypatch.setattr(terminal.os, "write", lambda fd, data: write_calls.append((fd, data)))
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    ws = _FakeWebSocket(messages=[
        "not a json {{{",
        json.dumps({"d": "echo hi"}),
        "@@@another-bad-json@@@",
        json.dumps({"d": "ls"}),
    ])

    async def _run():
        _disable_loop_reader(monkeypatch)
        await terminal.terminal_bridge(ws)

    asyncio.run(_run())

    # 只有两条合法消息被写入 pty
    assert write_calls == [(11, b"echo hi"), (11, b"ls")], (
        f"坏 JSON 应被忽略，只处理合法消息；实际 {write_calls}"
    )


def test_bridge_resize_with_wrong_shape_ignored(monkeypatch):
    """边界：{"r": [...]} 长度不为 2 应被忽略，不调 _set_winsize。"""
    _patch_spawn_shell(monkeypatch, master_fd=33)
    winsize_calls: list = []
    monkeypatch.setattr(terminal, "_set_winsize", lambda fd, r, c: winsize_calls.append((fd, r, c)))
    monkeypatch.setattr(terminal.os, "write", lambda fd, data: None)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    ws = _FakeWebSocket(messages=[
        json.dumps({"r": [120]}),           # 长度 1 → 忽略
        json.dumps({"r": [120, 40, 99]}),   # 长度 3 → 忽略
        json.dumps({"r": "not-a-list"}),    # 非 list → 忽略
    ])

    async def _run():
        _disable_loop_reader(monkeypatch)
        await terminal.terminal_bridge(ws)

    asyncio.run(_run())

    assert winsize_calls == [], f"形状不对的 r 应被忽略；实际 {winsize_calls}"


def test_bridge_pty_output_forwarded_to_websocket(monkeypatch):
    """输出路径：pty 读出数据 → websocket.send_text 转发。

    模拟方式：禁用 loop.add_reader，但用真事件循环直接往 bridge 的内部 queue 注入数据
    不可行（queue 是局部变量）；改为 monkeypatch loop.add_reader，让它立即回调 _on_readable，
    而 os.read 返回预设数据 → 数据进入 queue → sender 任务 send_text 出去。
    """
    _patch_spawn_shell(monkeypatch, master_fd=222)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    # os.read 第一次返回数据，第二次返回 b"" (EOF)
    read_seq: list[bytes] = [b"hello from pty", b""]

    def _fake_read(fd, n):
        return read_seq.pop(0) if read_seq else b""

    monkeypatch.setattr(terminal.os, "read", _fake_read)

    # 关键：receive_text 必须等 sender 把数据送出后再断开，否则 finally 会取消 sender
    # 导致 send_text 没机会执行。用 event 同步：
    #   callback_done = _on_readable 已把数据塞进 queue
    #   再 await asyncio.sleep(0) 两次让 sender 任务跑完 send_text
    callback_done = asyncio.Event()

    class _WS:
        def __init__(self):
            self.accept = AsyncMock()
            self.close = AsyncMock()
            self.send_text = AsyncMock()

        async def receive_text(self):
            await callback_done.wait()
            # 让 sender 任务有机会处理 queue 里的数据
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            raise WebSocketDisconnect()

    ws = _WS()

    async def _run():
        loop = asyncio.get_running_loop()

        def _fake_add_reader(fd, cb, *args):
            def _wrap():
                try:
                    cb()
                finally:
                    callback_done.set()
            loop.call_soon(_wrap)

        monkeypatch.setattr(loop, "add_reader", _fake_add_reader, raising=False)
        monkeypatch.setattr(loop, "remove_reader", lambda *a, **kw: False, raising=False)

        await terminal.terminal_bridge(ws)

    asyncio.run(_run())

    sent = [c.args[0] for c in ws.send_text.call_args_list]
    assert "hello from pty" in sent, f"pty 输出应转发到前端；实际 send_text: {sent}"


def test_bridge_pty_eof_closes_websocket(monkeypatch):
    """EOF 路径：pty 读出 b"" → sender 调 websocket.close()。"""
    _patch_spawn_shell(monkeypatch, master_fd=333)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    # os.read 立即返回 b"" → EOF
    monkeypatch.setattr(terminal.os, "read", lambda fd, n: b"")

    # ws 不发任何消息，但 receive_text 必须能 await 直到 sender 触发 close
    # 简化：让 receive_text 在被调用时立即 await 一个 event，sender close 后再 raise
    received_event = asyncio.Event()

    class _WS:
        def __init__(self):
            self.accept = AsyncMock()
            self.close = AsyncMock()
            self.send_text = AsyncMock()

        async def receive_text(self):
            # 等 sender 处理完 EOF 并 close；超时则失败
            await asyncio.wait_for(received_event.wait(), timeout=1.0)
            raise WebSocketDisconnect()

    ws = _WS()

    async def _run():
        loop = asyncio.get_running_loop()

        # add_reader 立即调度回调（call_soon）→ _on_readable → queue.put(b"") → sender 收到 EOF → close
        def _fake_add_reader(fd, cb, *args):
            def _wrap():
                try:
                    cb()
                finally:
                    received_event.set()
            loop.call_soon(_wrap)

        monkeypatch.setattr(loop, "add_reader", _fake_add_reader, raising=False)
        monkeypatch.setattr(loop, "remove_reader", lambda *a, **kw: False, raising=False)

        await terminal.terminal_bridge(ws)

    asyncio.run(_run())

    ws.close.assert_awaited_once(), "pty EOF 时 sender 必须调 websocket.close()"


def test_bridge_cleanup_swallows_processlookuperror(monkeypatch):
    """异常场景：进程已退出时 killpg 抛 ProcessLookupError，cleanup 不应传播。"""
    _patch_spawn_shell(monkeypatch, master_fd=44)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: (_ for _ in ()).throw(ProcessLookupError("gone")))
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    ws = _FakeWebSocket(messages=[])

    async def _run():
        _disable_loop_reader(monkeypatch)
        await terminal.terminal_bridge(ws)

    # 不抛即通过
    asyncio.run(_run())


def test_bridge_cleanup_swallows_oserror_on_close(monkeypatch):
    """异常场景：os.close 抛 OSError（如 fd 已被 sender 关闭），cleanup 不应传播。"""
    _patch_spawn_shell(monkeypatch, master_fd=55)
    monkeypatch.setattr(terminal.os, "close", lambda fd: (_ for _ in ()).throw(OSError("bad fd")))
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    ws = _FakeWebSocket(messages=[])

    async def _run():
        _disable_loop_reader(monkeypatch)
        await terminal.terminal_bridge(ws)

    asyncio.run(_run())


def test_bridge_on_readable_swallows_oserror_from_os_read(monkeypatch):
    """异常场景：_on_readable 中 os.read 抛 OSError 时，应把 data 设为 b"" 并走 EOF 路径。

    覆盖 terminal.py 第 72-73 行：except OSError: data = b""
    """
    _patch_spawn_shell(monkeypatch, master_fd=66)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    # os.read 抛 OSError → _on_readable 应捕获并 put b""
    def _raise_read(fd, n):
        raise OSError("fd closed")
    monkeypatch.setattr(terminal.os, "read", _raise_read)

    callback_done = asyncio.Event()

    class _WS:
        def __init__(self):
            self.accept = AsyncMock()
            self.close = AsyncMock()  # 不应被调用，因为 sender 收到 b"" 才 close
            self.send_text = AsyncMock()

        async def receive_text(self):
            await callback_done.wait()
            await asyncio.sleep(0)
            raise WebSocketDisconnect()

    ws = _WS()

    async def _run():
        loop = asyncio.get_running_loop()

        def _fake_add_reader(fd, cb, *args):
            def _wrap():
                try:
                    cb()  # _on_readable 内部吞 OSError，把 b"" 塞进 queue
                finally:
                    callback_done.set()
            loop.call_soon(_wrap)

        monkeypatch.setattr(loop, "add_reader", _fake_add_reader, raising=False)
        monkeypatch.setattr(loop, "remove_reader", lambda *a, **kw: False, raising=False)

        await terminal.terminal_bridge(ws)

    asyncio.run(_run())

    # OSError 被吞 → data=b"" 进 queue → sender 调 websocket.close()
    ws.close.assert_awaited_once(), (
        "os.read 抛 OSError 时 _on_readable 应吞掉并把 b"" 塞进 queue，触发 sender close"
    )


def test_bridge_sender_swallows_exception_from_websocket_close(monkeypatch):
    """异常场景：sender 收到 EOF 后调 websocket.close()，若 close 抛异常应被吞掉。

    覆盖 terminal.py 第 86-87 行：except Exception: pass
    """
    _patch_spawn_shell(monkeypatch, master_fd=77)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)
    monkeypatch.setattr(terminal.os, "read", lambda fd, n: b"")  # 立即 EOF

    callback_done = asyncio.Event()

    class _WS:
        def __init__(self):
            self.accept = AsyncMock()
            # close 抛异常 → sender 应吞掉，不传播
            self.close = AsyncMock(side_effect=RuntimeError("ws already closed"))
            self.send_text = AsyncMock()

        async def receive_text(self):
            await callback_done.wait()
            await asyncio.sleep(0)
            raise WebSocketDisconnect()

    ws = _WS()

    async def _run():
        loop = asyncio.get_running_loop()

        def _fake_add_reader(fd, cb, *args):
            def _wrap():
                try:
                    cb()
                finally:
                    callback_done.set()
            loop.call_soon(_wrap)

        monkeypatch.setattr(loop, "add_reader", _fake_add_reader, raising=False)
        monkeypatch.setattr(loop, "remove_reader", lambda *a, **kw: False, raising=False)

        # 不抛即通过
        await terminal.terminal_bridge(ws)

    asyncio.run(_run())

    ws.close.assert_awaited_once(), "sender 应在 EOF 时调用 websocket.close()"


def test_bridge_sender_breaks_on_send_text_failure(monkeypatch):
    """异常场景：sender 调 websocket.send_text 抛异常时应 break 退出循环，不再尝试。

    覆盖 terminal.py 第 91-92 行：except Exception: break
    """
    _patch_spawn_shell(monkeypatch, master_fd=88)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    # os.read 持续返回数据（不让它 EOF），逼 sender 反复 send_text
    monkeypatch.setattr(terminal.os, "read", lambda fd, n: b"chunk")

    callback_done = asyncio.Event()

    class _WS:
        def __init__(self):
            self.accept = AsyncMock()
            self.close = AsyncMock()
            # send_text 第一次就抛异常 → sender 应 break
            self.send_text = AsyncMock(side_effect=ConnectionError("ws gone"))
            self.send_call_count = 0

        async def receive_text(self):
            await callback_done.wait()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            raise WebSocketDisconnect()

    ws = _WS()

    async def _run():
        loop = asyncio.get_running_loop()

        def _fake_add_reader(fd, cb, *args):
            def _wrap():
                try:
                    cb()
                finally:
                    callback_done.set()
            loop.call_soon(_wrap)

        monkeypatch.setattr(loop, "add_reader", _fake_add_reader, raising=False)
        monkeypatch.setattr(loop, "remove_reader", lambda *a, **kw: False, raising=False)

        await terminal.terminal_bridge(ws)

    asyncio.run(_run())

    # send_text 抛异常 → sender break；不应反复重试
    assert ws.send_text.await_count >= 1, "send_text 至少应被调用一次"
    # 关键：close 不应被调用（因为 sender 在 send_text 失败后 break，没走到 EOF close 分支）
    ws.close.assert_not_awaited(), "send_text 失败应 break，不应走 EOF close 路径"


def test_bridge_receive_loop_swallows_non_disconnect_exception(monkeypatch):
    """异常场景：receive_text 抛非 WebSocketDisconnect 异常时，bridge 不应传播。

    覆盖 terminal.py 第 108-109 行：except Exception: pass
    """
    _patch_spawn_shell(monkeypatch, master_fd=99)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    class _WS:
        def __init__(self):
            self.accept = AsyncMock()
            self.close = AsyncMock()
            self.send_text = AsyncMock()

        async def receive_text(self):
            raise ConnectionResetError("peer reset")  # 非 WebSocketDisconnect

    ws = _WS()

    async def _run():
        _disable_loop_reader(monkeypatch)
        # 不抛即通过
        await terminal.terminal_bridge(ws)

    asyncio.run(_run())


def test_bridge_cleanup_swallows_oserror_from_remove_reader(monkeypatch):
    """异常场景：finally 中 loop.remove_reader 抛 OSError/ValueError 时不应传播。

    覆盖 terminal.py 第 113-114 行：except (OSError, ValueError): pass
    """
    _patch_spawn_shell(monkeypatch, master_fd=111)
    monkeypatch.setattr(terminal.os, "close", lambda fd: None)
    monkeypatch.setattr(terminal.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(terminal.os, "getpgid", lambda pid: 1)

    ws = _FakeWebSocket(messages=[])

    async def _run():
        loop = asyncio.get_event_loop()

        def _raise_remove_reader(*a, **kw):
            raise OSError("loop closed")
        monkeypatch.setattr(loop, "add_reader", lambda *a, **kw: None, raising=False)
        monkeypatch.setattr(loop, "remove_reader", _raise_remove_reader, raising=False)

        # 不抛即通过
        await terminal.terminal_bridge(ws)

    asyncio.run(_run())
