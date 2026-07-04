"""交付步:验收通过后在沙盒内自动提交成果(F7 · 自主开发闭环的产出)。

自主循环拆→写→测→修→验收通过后,成果若停在未提交状态就少了"有形产物"。本模块在沙盒内
`git add -A && git commit`(必要时先 git init、带兜底身份),把通过强制验收的变更固化成一次提交
(Devin/Codex 式)。commit 是本地可逆动作(非 push,push 属高风险已被 approval 拦),适合自主执行。

经 RemoteWorkspace.execute_command 在容器内跑(代码在沙盒);提交信息单引号转义防注入;
workspace_factory 可注入 → 单测无需真沙盒。
"""
from __future__ import annotations

from typing import Any, Callable

_SUBJECT_CAP = 72
_OUTPUT_TAIL = 1500
_COMMIT_TRAILER = "由 flipped 自主循环完成并通过强制验收。"


def _shell_single_quote(s: str) -> str:
    """把字符串安全包进单引号(经典 '\\'' 转义,可含换行/特殊字符)。"""
    return "'" + s.replace("'", "'\\''") + "'"


def build_commit_message(goal: str) -> str:
    """据目标生成规范提交信息(subject + trailer)。"""
    first = (goal or "").strip().splitlines()[0].strip() if (goal or "").strip() else ""
    subject = (first[:_SUBJECT_CAP] or "自主开发变更")
    return f"feat: {subject}\n\n{_COMMIT_TRAILER}"


def build_commit_command(message: str) -> str:
    """构建沙盒内提交命令:无 git 则 init,无变更则 __NOCHANGE__,否则提交并 __COMMITTED__。

    F8 实测:无 .gitignore 时 `git add -A` 会把 __pycache__/*.pyc 等垃圾提交进去,
    故项目没有 .gitignore 时先写一份常见垃圾模式。
    """
    ident = "-c user.name='flipped' -c user.email='flipped@local'"
    m = _shell_single_quote(message)
    gitignore = (
        "[ -f .gitignore ] || printf '__pycache__/\\n*.pyc\\n.pytest_cache/\\n"
        "node_modules/\\n.venv/\\ndist/\\nbuild/\\n.DS_Store\\n' > .gitignore; "
    )
    return (
        "git init -q 2>/dev/null; " + gitignore + "git add -A && "
        "(git diff --cached --quiet && echo __NOCHANGE__ || "
        f"(git {ident} commit -q -m {m} && echo __COMMITTED__))"
    )


def make_sandbox_deliver(
    agent_host: str,
    working_dir: str,
    api_key: str = "",
    *,
    timeout: float = 120.0,
    workspace_factory: Callable[..., Any] | None = None,
) -> Callable[[str], dict[str, Any]]:
    """构建一个在沙盒内提交成果的 deliver(goal) -> {committed, nochange, message, output}。"""

    def deliver(goal: str) -> dict[str, Any]:
        message = build_commit_message(goal)
        command = build_commit_command(message)

        factory = workspace_factory
        if factory is None:  # pragma: no cover - 真沙盒路径,单测走注入
            from openhands.sdk.workspace.remote.base import RemoteWorkspace
            factory = RemoteWorkspace

        ws = factory(host=agent_host, working_dir=working_dir, api_key=api_key)
        with ws:
            result = ws.execute_command(command, cwd=working_dir, timeout=timeout)

        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        out = stdout + stderr
        return {
            "committed": "__COMMITTED__" in out,
            "nochange": "__NOCHANGE__" in out,
            "message": message,
            "output": out[-_OUTPUT_TAIL:],
        }

    return deliver
