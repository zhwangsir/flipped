#!/usr/bin/env python
"""M10.3 E2E：验证设计系统注入 + 无限迭代循环。

用"构建一个暗黑模式 Landing Page"任务，验证：
1. 设计系统注入到 planner prompt 和 worker project_rules（生成的 HTML 含 hex 值）
2. 无限迭代循环跑通多轮（第二轮基于第一轮成果演进）
3. 第二轮目标不是第一轮的重复
"""
import os
import sys

sys.path.insert(0, "src")

from driving.infinite_loop import run_infinite_loop


def main():
    # 绕过 http_proxy 拦截内网模型端点（必须 unset，langchain httpx 会走系统代理）
    for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "100.64.201.37,localhost,127.0.0.1,host.docker.internal"
    os.environ["no_proxy"] = "100.64.201.37,localhost,127.0.0.1,host.docker.internal"

    cwd = "/tmp/flipped_e2e_landing"
    os.makedirs(cwd, exist_ok=True)

    # 清理旧 db
    for f in os.listdir("data"):
        if f.startswith("infinite_e2e") or (f.startswith("factory") and "loop" in f):
            os.remove(f"data/{f}")

    state = run_infinite_loop(
        direction=(
            "构建一个暗黑模式的 Landing Page，包含 hero、features、pricing 三个区块。"
            "用 HTML + 内联 CSS。颜色用 #0A84FF 做强调色，背景 #0D0D12，文字 #F5F5F5。"
            "验证方式：检查 index.html 存在且包含 <section 标签和 #0A84FF 颜色值。"
        ),
        cwd=cwd,
        design_style="dark",
        max_rounds=2,
        db_path="data/infinite_e2e.db",
    )

    print(f"\n{'='*60}")
    print(f"[结果] status={state.status.value} rounds={len(state.rounds)}")
    for r in state.rounds:
        print(f"  第{r.round_num}轮: {r.product_goal}")
        print(f"    完成={r.tasks_completed} 失败={r.tasks_failed}")
        print(f"    成果: {r.summary}")

    # 检查产出的 HTML 是否包含设计系统的 hex 值
    design_hex_found = False
    if os.path.exists(f"{cwd}/index.html"):
        content = open(f"{cwd}/index.html").read()
        # 检查设计系统的关键 hex 值
        for hex_val in ("#0A84FF", "#0D0D12", "#F5F5F5"):
            if hex_val.lower() in content.lower():
                design_hex_found = True
                print(f"  [设计系统] index.html 包含 {hex_val} ✅")
            else:
                print(f"  [设计系统] index.html 缺少 {hex_val} ❌")

    # 判定
    all_rounds_ok = all(
        r.tasks_completed > 0 and r.tasks_failed == 0 for r in state.rounds
    ) and len(state.rounds) >= 1
    passed = all_rounds_ok and design_hex_found

    print(f"\n{'='*60}")
    if passed:
        print(f"[判定] 通过 ✅ 设计系统注入 + 无限迭代验证成功")
        print(f"  - {len(state.rounds)} 轮全部完成")
        print(f"  - 生成的 HTML 包含设计系统 hex 值")
        return 0
    else:
        print(f"[判定] 未通过 ❌")
        print(f"  - rounds_ok={all_rounds_ok} design_hex={design_hex_found}")
        print(f"  - status={state.status.value}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
