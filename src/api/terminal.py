"""Stage 5 — 真实 pty 终端桥（WebSocket ↔ 交互式 shell）。

在项目根目录起一个交互式 shell，把 pty master 与 WebSocket 双向桥接：
- 前端发 {"d": "<input>"}  → 写入 pty
- 前端发 {"r": [cols,rows]} → 调整窗口大小（TIOCSWINSZ）
- pty 输出 → 原样 send_text 回前端（xterm.js 渲染）

仅监听 127.0.0.1、作用域限定项目根，等价于编辑器内置终端。
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import signal
import struct
import subprocess
import termios
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TIOCSCTTY = getattr(termios, "TIOCSCTTY", None)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def _preexec() -> None:  # 在子进程 exec 前：新会话 + 取得控制终端，令 Ctrl-C 等生效
    os.setsid()
    if _TIOCSCTTY is not None:
        try:
            fcntl.ioctl(0, _TIOCSCTTY, 0)
        except OSError:
            pass


def _spawn_shell() -> tuple[int, subprocess.Popen]:
    master_fd, slave_fd = pty.openpty()
    _set_winsize(master_fd, 24, 80)
    shell = os.environ.get("SHELL", "/bin/bash")
    proc = subprocess.Popen(
        [shell, "-i"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=str(_REPO_ROOT),
        env={**os.environ, "TERM": "xterm-256color"},
        preexec_fn=_preexec,
        close_fds=True,
    )
    os.close(slave_fd)
    return master_fd, proc


async def terminal_bridge(websocket: WebSocket) -> None:
    await websocket.accept()
    master_fd, proc = _spawn_shell()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def _on_readable() -> None:
        try:
            data = os.read(master_fd, 8192)
        except OSError:
            data = b""
        queue.put_nowait(data)
        if not data:
            loop.remove_reader(master_fd)

    loop.add_reader(master_fd, _on_readable)

    async def _sender() -> None:
        while True:
            data = await queue.get()
            if not data:  # EOF → shell 退出
                try:
                    await websocket.close()
                except Exception:  # noqa: BLE001
                    pass
                break
            try:
                await websocket.send_text(data.decode(errors="replace"))
            except Exception:  # noqa: BLE001
                break

    sender_task = asyncio.create_task(_sender())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if "d" in msg:
                os.write(master_fd, str(msg["d"]).encode())
            elif "r" in msg and isinstance(msg["r"], list) and len(msg["r"]) == 2:
                _set_winsize(master_fd, int(msg["r"][1]), int(msg["r"][0]))
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            loop.remove_reader(master_fd)
        except (OSError, ValueError):
            pass
        sender_task.cancel()
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
