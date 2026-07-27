"""真实 E2E · 连续 10 任务不熔断验证。

用真实 GLM-5.2 planner + Kimi-K2.7 orchestrator + OpenHands 沙箱，
跑一个 10 任务的工厂循环，验证：
1. verify_cmd 单行约束生效（不再因多行 Python 熔断）
2. GLM 结构化输出兜底生效（偶发畸形不阻塞）
3. 连续执行不熔断

前置：模型端点在线、OpenHands 运行中。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# M164 · venv 自举：若 .venv 存在且当前不是 venv Python，自动重启自己。
# 否则用系统 Python 跑会因缺 langgraph 等依赖崩溃（scripts 设计为可 cron/直接跑，不能假设 venv 已激活）。
_VENV_PY = str(ROOT / ".venv" / "bin" / "python3")
if os.path.exists(_VENV_PY) and os.path.realpath(sys.executable) != os.path.realpath(_VENV_PY):
    os.execv(_VENV_PY, [_VENV_PY] + sys.argv)

sys.path.insert(0, str(ROOT / "src"))


def main():
    # 绕过 http_proxy 拦截内网模型端点（必须 unset，langchain httpx 会走系统代理）
    for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "100.64.201.37,localhost,127.0.0.1,host.docker.internal"
    os.environ["no_proxy"] = "100.64.201.37,localhost,127.0.0.1,host.docker.internal"

    from driving.factory_loop import run_factory_loop, FactoryStatus

    # 用有权限的目录（OpenHands 容器需能访问，/var/folders 在 macOS 上无权限）
    workdir = "/tmp/flipped_e2e_10"
    os.makedirs(workdir, exist_ok=True)
    print(f"[E2E] 工作目录: {workdir}")
    print(f"[E2E] 产品目标: 构建一个 Python 计算器库(calc.py)，含 add/sub/mul/div/sqrt/factorial，配 pytest 测试")
    print(f"[E2E] max_tasks=10")
    print()

    state = run_factory_loop(
        product_goal=(
            "构建一个 Python 计算器库 calc.py，包含函数: add(a,b), sub(a,b), mul(a,b), "
            "div(a,b,默认零除返回None), sqrt(x), factorial(n)。"
            "每个函数配对应的 pytest 测试。项目结构: calc.py + tests/test_calc.py。"
            "分 10 个小任务逐步实现，每个任务实现一个函数+其测试。"
        ),
        cwd=workdir,
        max_tasks=10,
        db_path="data/factory_e2e_10.db",
    )

    print()
    print("=" * 60)
    print(f"[E2E 结果]")
    print(f"  工厂 ID: {state.factory_id}")
    print(f"  最终状态: {state.status.value}")
    print(f"  迭代次数: {state.iteration_count}")
    print(f"  roadmap 任务数: {len(state.roadmap)}")
    print(f"  完成: {len(state.completed)}")
    print(f"  失败: {len(state.failed)}")
    print()
    print("[Roadmap]")
    for t in state.roadmap:
        print(f"  {t.id} [{t.status.value}] attempts={t.attempts}")
        print(f"    desc: {t.description[:80]}")
        print(f"    verify: {t.verify_cmd}")
        if t.feedback:
            print(f"    feedback: {t.feedback[:120]}")
    print()
    if state.completed:
        print("[完成的任务]")
        for r in state.completed:
            print(f"  {r.task.id}: verified={r.verified} iter={r.iteration} reason={r.stop_reason}")
    if state.failed:
        print("[失败的任务]")
        for r in state.failed:
            print(f"  {r.task.id}: verified={r.verified} reason={r.stop_reason}")
            print(f"    summary: {r.summary[:200]}")

    # 判定：status=done + 全部任务 verified + 无熔断（circuit_breaker）即通过。
    # 不硬编码"完成 ≥ N"——planner 自主决定拆成几个任务是合理的（如 6 函数+1 骨架=7），
    # 只要生成的任务全部 verified 且未熔断，就算"连续跑通真实任务不熔断"。
    circuit_broken = any(
        r.stop_reason == "circuit_breaker" for r in state.failed
    )
    all_verified = len(state.completed) == len(state.roadmap) and len(state.roadmap) > 0
    passed = (
        state.status == FactoryStatus.done
        and all_verified
        and not circuit_broken
        and len(state.failed) == 0
    )
    print()
    if passed:
        print(f"[判定] 通过 ✅ 工厂连续执行未熔断（{len(state.completed)}/{len(state.roadmap)} 任务全部 verified）")
        return 0
    else:
        print(f"[判定] 未通过 ❌ 状态={state.status.value} "
              f"完成={len(state.completed)}/{len(state.roadmap)} "
              f"失败={len(state.failed)} 熔断={'是' if circuit_broken else '否'}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
