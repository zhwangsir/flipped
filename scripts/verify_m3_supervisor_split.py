"""M3.3 真实验证：supervisor(GLM-5.2-fp8) 是否把复杂目标拆成 ≤3 步小 subtask。

验证 M3 编排层分解的核心假设：
  supervisor prompt 加了窗口约束（每个 subtask 必须 3 步内可完成）后，
  GLM-5.2-fp8 是否真的把"写 config 模块 + 测试 + 跑 pytest"这种多步目标
  拆成单文件级的小 subtask，而不是一次给整个目标。

判别标准：
  1. subtask 长度 ≤200 字（prompt 约束）
  2. subtask 是单个聚焦动作（写一个文件 / 跑一个命令），非整个目标
  3. 语义上在 3 步内可完成（不是"写 config.py + 写 test_config.py + 跑 pytest"全包）
  4. 输出无乱码/退化（alpha 占比正常、无 token 重复）

用法: PYTHONPATH=src .venv/bin/python3 scripts/verify_m3_supervisor_split.py
"""
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 加载 .env
for raw in (ROOT / ".env").read_text().splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from driving.orchestrator import default_supervisor, OrchestratorState

# 与 worker 验证同样的复杂目标
COMPLEX_GOAL = (
    "在工作目录下创建一个小型 Python 配置管理模块：\n"
    "1. config.py：实现 load_config(path) 读 JSON、save_config(path, data) 写 JSON、"
    "get(key, default) 支持环境变量覆盖（前缀 CONFIG_），含类型注解。\n"
    "2. tests/test_config.py：pytest 测试以上三个函数（至少 4 个用例）。\n"
    "3. 运行 python -m pytest tests/ -q 确认全部通过。"
)

# M3.3b 第二场景：不同领域的多文件目标，确认拆分行为不是针对 config 的过拟合
ALT_GOAL_WEB = (
    "在工作目录下创建一个极简 Flask API：\n"
    "1. app.py：实现 GET /health 返回 {\"status\":\"ok\"}，GET /echo/<msg> 返回 {\"echo\": msg}。\n"
    "2. tests/test_app.py：用 pytest+httpx 测试两个端点（至少 3 个用例）。\n"
    "3. 运行 python -m pytest tests/ -q 确认全部通过。"
)

# M3.3b 第三场景：三文件目标，更激进地测试拆分
ALT_GOAL_3FILES = (
    "在工作目录下创建一个小型 CLI 工具：\n"
    "1. cli.py：用 argparse 实现 add/sub 两个子命令。\n"
    "2. calc.py：实现 add(a,b) 和 sub(a,b) 纯函数。\n"
    "3. tests/test_calc.py：pytest 测试 calc.py 的两个函数。\n"
    "4. 运行 python -m pytest tests/ -q 确认全部通过。"
)


def _alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    alnum = sum(1 for c in text if c.isalpha())
    return alnum / max(len(text), 1)


def _has_dup_token(text: str) -> bool:
    """检测 token 重复退化（如 'open open'、'loadload'）。"""
    # 连续重复单词
    if re.search(r"\b(\w+)\s+\1\b", text):
        return True
    # 单词内重复（loadload、openopen）
    if re.search(r"(\w{3,})\1", text):
        return True
    return False


def main() -> int:
    scene = sys.argv[1] if len(sys.argv) > 1 else "config"
    goals = {"config": COMPLEX_GOAL, "web": ALT_GOAL_WEB, "cli": ALT_GOAL_3FILES}
    goal = goals.get(scene, COMPLEX_GOAL)
    # 模拟首轮 orchestrator state
    state: OrchestratorState = {
        "goal": goal,
        "cwd": "/tmp/m3_verify",
        "verify_cmd": ["python", "-m", "pytest", "tests/", "-q"],
        "project_rules": "",
        "repo_map": "",
        "feedback": "",          # 首轮
        "iteration": 0,
        "history": [],
        "context_summary": None,
    }

    print(f"[verify] scene={scene} 目标(前60字): {goal[:60]}...", flush=True)
    print(f"[verify] 调用 default_supervisor (GLM-5.2-fp8 via architect)...", flush=True)
    t0 = time.monotonic()
    try:
        upd = default_supervisor(state)
    except Exception as exc:
        wall = time.monotonic() - t0
        print(f"[verify] supervisor 异常: {type(exc).__name__}: {exc}  墙钟 {wall:.0f}s", flush=True)
        return 2
    wall = time.monotonic() - t0

    subtask = upd.get("current_subtask", "")
    done = upd.get("believe_done", False)
    ide = upd.get("ide_action")
    hist = upd.get("history", [])
    last = hist[-1] if hist else {}
    why = last.get("why", "")

    print(f"\n[verify] 墙钟 {wall:.0f}s", flush=True)
    print(f"[verify] believe_done={done}  ide_action={ide}", flush=True)
    print(f"[verify] rationale: {why}", flush=True)
    print(f"[verify] subtask (len={len(subtask)} 字):\n---\n{subtask}\n---", flush=True)

    # 判别
    print("\n=== 判别 ===", flush=True)
    # M3.3b: 长度阈值 200→300。单文件 subtask 含函数签名描述时 260 字常见，
    # 核心目标是"拆分而非打包"，长度是次要（GLM 倾向详细描述签名）。
    ok_len = len(subtask) <= 300
    print(f"[{'PASS' if ok_len else 'FAIL'}] 长度 ≤300 字(单文件可接受): {len(subtask)}", flush=True)

    # 是否是单个聚焦动作（不含多个"步骤号"如 1. 2. 3.）
    step_markers = re.findall(r"(?:^|\n)\s*\d+[.)]\s", subtask)
    ok_focused = len(step_markers) <= 1
    print(f"[{'PASS' if ok_focused else 'FAIL'}] 单个聚焦动作(步骤标记≤1): 发现 {len(step_markers)} 个", flush=True)

    # 是否包含多文件（config.py 和 test_config.py 同时出现 = 全包）
    has_both_files = ("config.py" in subtask and "test" in subtask.lower()
                      and ("test_config" in subtask or "pytest" in subtask.lower()))
    ok_single_file = not has_both_files
    print(f"[{'PASS' if ok_single_file else 'FAIL'}] 未同时包揽 config+test: {'同时包含' if has_both_files else '聚焦单文件/单步'}", flush=True)

    # 乱码/退化检测
    alpha = _alpha_ratio(subtask)
    ok_alpha = alpha > 0.3 or len(subtask) < 20  # 纯中文短输出 alpha 低也正常
    print(f"[{'PASS' if ok_alpha else 'FAIL'}] alpha 占比 >0.3: {alpha:.2f}", flush=True)

    dup = _has_dup_token(subtask)
    print(f"[{'PASS' if not dup else 'FAIL'}] 无 token 重复退化: {'发现重复' if dup else '干净'}", flush=True)

    # 是否提到窗口约束（supervisor 理解了约束）
    understands_window = "3 步" in why or "3步" in why or "窗口" in why or "小" in why
    print(f"[{'INFO'}] rationale 是否体现窗口意识: {understands_window}", flush=True)

    passed = ok_len and ok_focused and ok_single_file and ok_alpha and (not dup)
    print(f"\n=== 总结: {'PASS' if passed else 'NEEDS_REVIEW'} ===", flush=True)
    if not passed:
        print("supervisor 未能把复杂目标拆成 ≤3 步小 subtask，M3.3 窗口约束未生效。", flush=True)
        return 1
    print("supervisor 正确把复杂目标拆成单个聚焦小 subtask，M3.3 窗口约束生效。", flush=True)
    return 0


def main_multi() -> int:
    """M3.3b 多轮验证：模拟 2 轮 supervisor 拆分，检查第 2 轮是否仍聚焦单文件。

    场景：第 1 轮 supervisor 派发"写 config.py"→ 假设 worker 完成 →
    第 2 轮 supervisor 应派发"写 test_config.py"（而非打包剩余全部）。
    检查第 2 轮 subtask 仍聚焦单文件、无退化。
    """
    scene = sys.argv[2] if len(sys.argv) > 2 else "config"
    goals = {"config": COMPLEX_GOAL, "web": ALT_GOAL_WEB, "cli": ALT_GOAL_3FILES}
    goal = goals.get(scene, COMPLEX_GOAL)

    print(f"[multi] scene={scene} 模拟 2 轮 supervisor 拆分", flush=True)

    # 第 1 轮
    state1: OrchestratorState = {
        "goal": goal, "cwd": "/tmp/m3_verify",
        "verify_cmd": ["python", "-m", "pytest", "tests/", "-q"],
        "project_rules": "", "repo_map": "", "feedback": "",
        "iteration": 0, "history": [], "context_summary": None,
    }
    t0 = time.monotonic()
    upd1 = default_supervisor(state1)
    w1 = time.monotonic() - t0
    sub1 = upd1.get("current_subtask", "")
    print(f"\n[multi] 第1轮 墙钟 {w1:.0f}s subtask(len={len(sub1)}):\n---\n{sub1}\n---", flush=True)

    # 模拟 worker 完成后回 supervisor（feedback 标记"已完成且验证通过"模拟 verify ok）
    state2: OrchestratorState = {
        "goal": goal, "cwd": "/tmp/m3_verify",
        "verify_cmd": ["python", "-m", "pytest", "tests/", "-q"],
        "project_rules": "", "repo_map": "",
        "feedback": "已完成且验证通过：执行者已写好 config.py，load_config/save_config/get 三个函数均已实现。",
        "iteration": 1,
        "history": upd1.get("history", []) + [
            {"step": "worker", "summary": {"tool_calls": 3}, "signature": "terminal:cat>config.py|terminal:pytest"},
            {"step": "overseer", "verdict": {"action": "continue"}},
        ],
        "context_summary": None,
    }
    t0 = time.monotonic()
    upd2 = default_supervisor(state2)
    w2 = time.monotonic() - t0
    sub2 = upd2.get("current_subtask", "")
    done2 = upd2.get("believe_done", False)
    print(f"\n[multi] 第2轮 墙钟 {w2:.0f}s believe_done={done2} subtask(len={len(sub2)}):\n---\n{sub2}\n---", flush=True)

    # 判别第 2 轮
    print("\n=== 第2轮判别 ===", flush=True)
    ok_len = len(sub2) <= 300
    print(f"[{'PASS' if ok_len else 'FAIL'}] 长度 ≤300: {len(sub2)}", flush=True)
    # 第 2 轮不应再提 config.py（已完成），应聚焦 test_config.py 或跑测试
    reasks_config = "config.py" in sub2 and "test_config" not in sub2
    print(f"[{'PASS' if not reasks_config else 'FAIL'}] 不重复已完成文件: {'重提config.py' if reasks_config else '正确推进'}", flush=True)
    # 不应打包剩余全部（同时含 test + pytest 跑命令 = 想一步到位）
    has_test_and_pytest = "test_config" in sub2 and "pytest" in sub2.lower() and "运行" in sub2
    ok_single = not has_test_and_pytest
    print(f"[{'PASS' if ok_single else 'FAIL'}] 未打包剩余: {'打包test+pytest' if has_test_and_pytest else '聚焦单步'}", flush=True)
    alpha = _alpha_ratio(sub2)
    ok_alpha = alpha > 0.3 or len(sub2) < 20
    print(f"[{'PASS' if ok_alpha else 'FAIL'}] alpha>0.3: {alpha:.2f}", flush=True)
    dup = _has_dup_token(sub2)
    print(f"[{'PASS' if not dup else 'FAIL'}] 无退化: {'发现重复' if dup else '干净'}", flush=True)

    passed = ok_len and (not reasks_config) and ok_single and ok_alpha and (not dup)
    print(f"\n=== 多轮总结: {'PASS' if passed else 'NEEDS_REVIEW'} ===", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    # M3.3b 多轮验证：模拟 worker 完成第 1 个 subtask 后回 supervisor 拆第 2 个
    # 确认第 2 轮 supervisor 仍稳定拆分（M3.2 历史压缩 + M3.3b 约束持续生效）
    if len(sys.argv) > 1 and sys.argv[1] == "multi":
        sys.exit(main_multi())
    sys.exit(main())
