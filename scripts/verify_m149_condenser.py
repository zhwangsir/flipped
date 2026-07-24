"""M149.20 真实验证：NoOp condenser + 无 ThinkTool + 短会话，跑多轮任务。

判别标准：
1. agent-server 接受配置（无 ThinkTool，不报序列化/校验错）
2. 多轮（≥3 轮工具调用）后 LLM 输出仍正常（无 arg_key 碎片 / thought 泄漏）
3. 文件真实生成（config.py + tests/test_config.py）
4. pytest 通过

用法: PYTHONPATH=src .venv/bin/python3 scripts/verify_m149_condenser.py
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 加载 .env（LITELLM_MASTER_KEY）
for raw in (ROOT / ".env").read_text().splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ["FLIPPED_WORKER_ENABLE_THINKING"] = "0"
os.environ["FLIPPED_WORKER_TIMEOUT"] = "2400"  # 40min 上限

from api.events import EventBus
from api.session import SessionStore
from executor.openhands_worker import OpenHandsWorker

WORKDIR = os.path.expanduser("~/projects/flipped_m149_verify")
shutil.rmtree(WORKDIR, ignore_errors=True)
os.makedirs(WORKDIR)
subprocess.run(["git", "init", "-q"], cwd=WORKDIR, check=True)

bus = EventBus(SessionStore())
worker = OpenHandsWorker(
    "m149-verify", "task-condenser-1", bus,
    working_dir=WORKDIR, manage_session_status=False,
)

TASK = (
    "在工作目录下创建一个小型 Python 配置管理模块：\n"
    "1. config.py：实现 load_config(path) 读 JSON、save_config(path, data) 写 JSON、"
    "get(key, default) 支持环境变量覆盖（前缀 CONFIG_），含类型注解。\n"
    "2. tests/test_config.py：pytest 测试以上三个函数（至少 4 个用例）。\n"
    "3. 运行 python -m pytest tests/ -q 确认全部通过。\n"
    "完成后调用 finish 工具。"
)

print(f"[verify] workdir={WORKDIR}", flush=True)
print(f"[verify] 任务: {TASK[:60]}...", flush=True)
t0 = time.monotonic()
try:
    result = worker.run(TASK)
    wall = time.monotonic() - t0
    print(f"[verify] worker 返回: {result}  墙钟 {wall:.0f}s", flush=True)
except Exception as exc:
    wall = time.monotonic() - t0
    print(f"[verify] worker 异常: {type(exc).__name__}: {exc}  墙钟 {wall:.0f}s", flush=True)

# 检查文件是否真实生成（容器 /projects 挂载 = 宿主机 ~/projects）
print("[verify] 生成的文件:", flush=True)
for p in sorted(Path(WORKDIR).rglob("*")):
    if p.is_file() and ".git" not in p.parts:
        print(f"  {p.relative_to(WORKDIR)} ({p.stat().st_size}B)", flush=True)
