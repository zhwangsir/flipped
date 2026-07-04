"""在 OpenHands 沙盒里跑验收命令(F1d · 自主循环的自我验证落地)。

自主循环的 Verify 步必须在**沙盒**执行——代码和依赖都在容器里(host 导入时还排除了
node_modules 等)。旧默认 verifier 在 host `subprocess` 跑、而 cwd 又是沙盒路径
`/projects/<名>`(host 上根本不存在)= 必错。本模块经 `RemoteWorkspace.execute_command`
在容器内执行,cwd=沙盒路径天然成立,cwd 不匹配的 bug 随之消失;并保留安全闸
(命令白/黑名单 + 高风险拦截),与 host 默认 verifier 同等约束。

verifier 签名与 orchestrator 的 `VerifierFn` 一致:`(cmd: list, cwd: str) -> (ok, output)`。
`workspace_factory` 可注入 → 单测无需真沙盒。
"""
from __future__ import annotations

from typing import Any, Callable, Protocol

from driving.approval import classify_risk
from driving.safety import is_safe_command

# verifier 返回 (是否通过, 尾部输出)
Verifier = Callable[[list, str], "tuple[bool, str]"]
_OUTPUT_TAIL = 2000


class _Workspace(Protocol):
    def execute_command(self, command: str, cwd: Any = None, timeout: float = ...) -> Any: ...
    def __enter__(self) -> Any: ...
    def __exit__(self, *exc: Any) -> Any: ...


def make_sandbox_verifier(
    agent_host: str,
    working_dir: str,
    api_key: str = "",
    *,
    timeout: float = 300.0,
    workspace_factory: Callable[..., _Workspace] | None = None,
) -> Verifier:
    """构建一个在沙盒内执行验收命令的 verifier。

    Args:
        agent_host: OpenHands agent-server 地址(容器暴露的 HTTP 端点)。
        working_dir: 沙盒内工作目录(/projects/<名>);cwd 缺省时用它。
        api_key: agent-server 鉴权。
        timeout: 单次验收命令超时(秒)。
        workspace_factory: RemoteWorkspace 构造器,测试可注入假实现。
    """

    def verify(cmd: list, cwd: str) -> "tuple[bool, str]":
        command_str = " ".join(cmd)
        ok, reason = is_safe_command(command_str)
        if not ok:
            return False, f"command blocked: {reason}"
        if classify_risk(command_str) == "high":
            return False, "high-risk command requires approval"

        factory = workspace_factory
        if factory is None:  # pragma: no cover - 真沙盒路径,单测走注入
            from openhands.sdk.workspace.remote.base import RemoteWorkspace
            factory = RemoteWorkspace

        ws = factory(host=agent_host, working_dir=working_dir, api_key=api_key)
        with ws:
            result = ws.execute_command(command_str, cwd=cwd or working_dir, timeout=timeout)

        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        output = (stdout + stderr)[-_OUTPUT_TAIL:]
        if getattr(result, "timeout_occurred", False):
            return False, (output + "\n[verify 超时]").strip()
        return getattr(result, "exit_code", 1) == 0, output

    return verify
