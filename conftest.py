"""Root conftest.py — 统一为所有测试注入 src/ 到 sys.path。

之前部分测试（test_resume_factory_script.py）自己 sys.path.insert(src)，
部分（test_factory_health.py）靠别的测试先加 path 才能跑——单独跑会
ModuleNotFoundError。本 conftest 在 collection 前统一注入，消除该脆弱依赖。

对齐 AGENTS.md §1.6"遇错即工程化"：加机制让问题不再发生，而非逐文件 patch。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
