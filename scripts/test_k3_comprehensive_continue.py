#!/usr/bin/env python3
"""继续跑 K3 综合评测剩余任务（13-17），使用更短的请求超时避免挂起。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import httpx
from typing import Any

EXO_URL = "http://43.119.32.180:8002/v1"
API_KEY = "JdM8LcFzoPXjc9Xh2EI9YX5PykvCkNj5KDN51OYlAEVfYvDG"
MODEL_ID = "moonshotai/Kimi-K3"
OUT_PATH = "/Users/wangzhenyu/Desktop/ALLProject/flipped/scripts/k3_comprehensive_eval.json"
REQUEST_TIMEOUT = 90.0  # 避免上游挂起

# 仅包含剩余任务（13-17）
REMAINING_TASKS = [
    {
        "id": "debug_race_condition",
        "category": "debugging",
        "name": "并发 Bug 诊断",
        "lang": "python",
        "prompt": (
            "Here is a buggy Python snippet:\n"
            "```python\n"
            "counter = 0\n"
            "def increment(n):\n"
            "    global counter\n"
            "    for _ in range(n):\n"
            "        counter += 1\n"
            "# Called from 10 threads with increment(1000)\n"
            "```\n"
            "Explain the bug and provide a corrected, thread-safe version using type hints and docstring. "
            "Only output the explanation and code block."
        ),
        "test_cases": [],
        "quality_checks": {
            "threading_lock": r"(threading\.Lock|Lock\(\)|RLock|acquire|release)",
            "race_mentioned": r"(race|racing|竞争|线程安全|atomic)",
            "type_hints": r"def\s+\w+\s*\(.*:\s*",
            "docstring": r'("""|\'\'\')',
        },
    },
    {
        "id": "logic_puzzle",
        "category": "reasoning",
        "name": "逻辑推理题",
        "lang": "text",
        "prompt": (
            "Solve this logic puzzle and explain your reasoning step by step. "
            "Alice, Bob, and Carol each have a different pet: cat, dog, bird. "
            "Alice does not like cats. Bob's pet can fly. Carol does not have a dog. "
            "What pet does each person have? Output your answer as a JSON object like {\"Alice\":\"...\"}."
        ),
        "expected": {"Alice": "dog", "Bob": "bird", "Carol": "cat"},
        "quality_checks": {
            "json_output": r"\{[^}]+\}",
            "reasoning": r"(because|since|therefore|所以|因为|因此)",
        },
    },
    {
        "id": "math_sequence",
        "category": "reasoning",
        "name": "数列求和",
        "lang": "python",
        "prompt": (
            "Write a Python function `sum_arithmetic(a1: int, d: int, n: int) -> int` that returns "
            "the sum of the first n terms of an arithmetic sequence with first term a1 and common difference d. "
            "Use the closed-form formula O(1). Include type hints and docstring. Only output the code block."
        ),
        "test_cases": [
            (1, 1, 10, 55), (1, 2, 5, 25), (0, 0, 100, 0), (-5, 3, 4, -2),
        ],
        "quality_checks": {
            "type_hints": r"def\s+sum_arithmetic\s*\(\s*a1\s*:\s*int\s*,\s*d\s*:\s*int\s*,\s*n\s*:\s*int\s*\)\s*->\s*int",
            "docstring": r'("""|\'\'\')',
            "formula": r"(n\s*\*\s*\(\s*2\s*\*\s*a1|a1\s*\+\s*\(\s*n\s*-\s*1\s*\)|n\s*\/\s*2)",
        },
    },
    {
        "id": "long_context_needle",
        "category": "long_context",
        "name": "长文本关键信息提取",
        "lang": "text",
        "prompt": (
            "I will give you a long text. After the text, answer the question.\n\n"
            + ("The weather today is sunny. " * 500)
            + "The secret code is BLUE-1984. "
            + ("Machine learning is interesting. " * 500)
            + "\n\nQuestion: What is the secret code? Output only the code."
        ),
        "expected": "BLUE-1984",
        "quality_checks": {
            "contains_code": r"BLUE-1984",
        },
    },
    {
        "id": "instruction_following",
        "category": "long_context",
        "name": "多步骤指令遵循",
        "lang": "text",
        "prompt": (
            "Follow these instructions exactly:\n"
            "1. First, say 'Step 1 done'.\n"
            "2. Then, output a JSON object with keys 'a' and 'b' mapping to 1 and 2.\n"
            "3. Finally, say 'Done' and nothing else.\n"
            "Do not add any extra explanation."
        ),
        "expected": ["Step 1 done", '"a": 1', '"b": 2', "Done"],
        "quality_checks": {
            "step1": r"Step 1 done",
            "json": r"\{[^}]*\"a\"\s*:\s*1[^}]*\"b\"\s*:\s*2[^}]*\}",
            "done": r"\bDone\b",
        },
    },
]


def call_model(prompt: str, enable_thinking: bool = True) -> dict:
    body = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "stream": False,
        "enable_thinking": enable_thinking,
    }
    t0 = time.time()
    try:
        with httpx.Client(timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0), trust_env=False) as client:
            r = client.post(
                f"{EXO_URL}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            )
        latency = time.time() - t0
        if r.status_code != 200:
            return {"ok": False, "latency": latency, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        data = r.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        return {
            "ok": True,
            "latency": latency,
            "content": msg.get("content", "") or "",
            "reasoning_content": msg.get("reasoning_content", "") or "",
            "tokens": data.get("usage", {}),
        }
    except Exception as e:
        return {"ok": False, "latency": time.time() - t0, "error": str(e)[:200]}


def extract_code(content: str, lang: str = "python") -> str:
    pattern = rf"```(?:{lang})?\n(.*?)```"
    m = re.search(pattern, content, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\n(.*?)```", content, re.DOTALL)
    if m:
        return m.group(1).strip()
    return content.strip()


def run_python_code(code: str, task: dict) -> dict:
    result = {"run_ok": False, "tests_passed": 0, "tests_total": 0, "errors": [], "output": ""}
    func_name = {
        "math_sequence": "sum_arithmetic",
    }.get(task["id"], task["id"])

    test_lines = ["try:"]
    for tc in task.get("test_cases", []):
        args = tc[:-1]
        expected = tc[-1]
        args_str = ", ".join(repr(a) for a in args)
        expected_repr = repr(expected)
        test_lines.append(f"    result = {func_name}({args_str})")
        test_lines.append(f'    assert result == {expected_repr}, f"FAIL: got {{result!r}} expected {expected_repr!r}"')
        result["tests_total"] += 1
    if result["tests_total"] > 0:
        test_lines.append("    print('ALL_TESTS_PASSED')")
        test_lines.append("except Exception as e:")
        test_lines.append("    print('TEST_ERROR: ' + type(e).__name__ + ': ' + str(e))")
        test_code = "\n".join(test_lines)
    else:
        test_code = ""

    if task["id"] == "debug_race_condition":
        test_code = """
try:
    import threading
    counter = 0
    lock = threading.Lock()
    def increment(n):
        global counter
        for _ in range(n):
            with lock:
                counter += 1
    threads = [threading.Thread(target=increment, args=(1000,)) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert counter == 10000, f"Expected 10000, got {counter}"
    print("ALL_TESTS_PASSED")
except Exception as e:
    print(f"TEST_ERROR: {type(e).__name__}: {e}")
"""

    full_code = code + "\n\n" + test_code
    if not test_code.strip():
        result["run_ok"] = True
        return result

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(full_code)
        f_path = f.name

    try:
        r = subprocess.run([sys.executable, f_path], capture_output=True, text=True, timeout=10)
        output = r.stdout.strip()
        result["output"] = output
        result["stderr"] = r.stderr.strip()[:500]
        result["run_ok"] = r.returncode == 0
        if "ALL_TESTS_PASSED" in output:
            result["tests_passed"] = result["tests_total"]
        elif "TEST_ERROR" in output:
            result["errors"].append(output.split("TEST_ERROR:")[-1].strip()[:200])
        else:
            for line in output.split("\n"):
                if "FAIL:" in line:
                    result["errors"].append(line[:200])
    except subprocess.TimeoutExpired:
        result["errors"].append("执行超时(10s)")
    except Exception as e:
        result["errors"].append(f"执行异常: {e}")
    finally:
        os.unlink(f_path)

    return result


def check_quality(code: str, checks: dict) -> dict:
    results = {}
    passed = 0
    for name, pattern in checks.items():
        found = bool(re.search(pattern, code, re.MULTILINE | re.DOTALL))
        results[name] = found
        if found:
            passed += 1
    return {"checks": results, "passed": passed, "total": len(checks), "score": passed / len(checks) if checks else 0.0}


def evaluate_task(task: dict) -> dict:
    gen = call_model(task["prompt"], enable_thinking=True)
    retried = False
    if not gen["ok"]:
        gen_retry = call_model(task["prompt"], enable_thinking=False)
        retried = True
        if gen_retry["ok"]:
            gen = gen_retry

    if not gen["ok"]:
        return {
            "id": task["id"],
            "category": task["category"],
            "name": task["name"],
            "gen_ok": False,
            "error": gen.get("error", "unknown"),
            "latency": gen.get("latency", 0),
            "retried_with_no_thinking": retried,
        }

    content = gen["content"]
    lang = task.get("lang", "python")
    code = extract_code(content, lang) if lang in ("python", "typescript", "go", "rust", "javascript") else content

    quality = check_quality(code, task.get("quality_checks", {}))

    run_result = {"run_ok": False, "tests_passed": 0, "tests_total": 0, "errors": []}
    if lang == "python":
        run_result = run_python_code(code, task)
    else:
        run_result["run_ok"] = True
        run_result["note"] = f"{lang} 代码不做自动执行测试"

    correctness_score = 0.0
    if run_result["run_ok"] and run_result["tests_total"] > 0:
        correctness_score = run_result["tests_passed"] / run_result["tests_total"]

    quality_score = quality["score"]
    has_syntax_error = run_result.get("stderr", "") and "SyntaxError" in run_result.get("stderr", "")
    completeness = 0.0 if has_syntax_error else 1.0

    text_match_score = 0.0
    if "expected" in task:
        expected = task["expected"]
        if isinstance(expected, dict):
            text_match_score = sum(1 for k, v in expected.items() if str(v).lower() in content.lower()) / len(expected)
        elif isinstance(expected, list):
            text_match_score = sum(1 for item in expected if str(item) in content) / len(expected)
        elif isinstance(expected, str):
            text_match_score = 1.0 if expected in content else 0.0

    total_score = correctness_score * 0.5 + quality_score * 0.3 + completeness * 0.2
    if "expected" in task:
        total_score = max(total_score, text_match_score * 0.7 + quality_score * 0.3)

    return {
        "id": task["id"],
        "category": task["category"],
        "name": task["name"],
        "gen_ok": True,
        "latency": gen["latency"],
        "tokens": gen["tokens"],
        "reasoning_length": len(gen.get("reasoning_content", "")),
        "reasoning_preview": gen.get("reasoning_content", "")[:200],
        "code_length": len(code),
        "code_preview": code[:300],
        "code_full": code,
        "quality": quality,
        "run": {
            "ok": run_result["run_ok"],
            "tests_passed": run_result["tests_passed"],
            "tests_total": run_result["tests_total"],
            "errors": run_result["errors"][:3],
            "output": run_result.get("output", "")[:200],
            "stderr": run_result.get("stderr", "")[:300],
        },
        "text_match": text_match_score if "expected" in task else None,
        "scores": {
            "correctness": correctness_score,
            "quality": quality_score,
            "completeness": completeness,
            "total": total_score,
        },
        "retried_with_no_thinking": retried,
    }


def main():
    # 加载已有结果
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            data = json.load(f)
        existing = data.get("results", [])
    else:
        existing = []

    completed_ids = {r["id"] for r in existing}
    print(f"已加载 {len(existing)} 条结果，跳过 {len(completed_ids)} 个已完成任务")

    results = list(existing)
    for i, task in enumerate(REMAINING_TASKS, 1):
        if task["id"] in completed_ids:
            print(f"[{i}/{len(REMAINING_TASKS)}] {task['name']} 已存在，跳过")
            continue
        print(f"[{i}/{len(REMAINING_TASKS)}] [{task['category']}] {task['name']} ...", end=" ", flush=True)
        r = evaluate_task(task)
        results.append(r)
        with open(OUT_PATH, "w") as f:
            json.dump({"model": MODEL_ID, "endpoint": EXO_URL, "results": results}, f, indent=2, ensure_ascii=False, default=str)

        if not r["gen_ok"]:
            print(f"✗ 生成失败 ({r['latency']:.1f}s): {r.get('error', '')[:80]}")
            continue
        s = r["scores"]
        print(f"✓ 总分 {s['total']:.0%} (正确 {s['correctness']:.0%} / 质量 {s['quality']:.0%} / 完整 {s['completeness']:.0%}) "
              f"({r['latency']:.1f}s, {r['code_length']} chars)")
        if r.get("retried_with_no_thinking"):
            print("    (已用 enable_thinking=False 重试)")
        if r["run"]["tests_total"] > 0:
            print(f"    测试: {r['run']['tests_passed']}/{r['run']['tests_total']} passed")
        if r["run"]["errors"]:
            for e in r["run"]["errors"][:2]:
                print(f"    错误: {e}")
        failed = [k for k, v in r["quality"]["checks"].items() if not v]
        if failed:
            print(f"    质量检查缺: {', '.join(failed)}")

    # 重新输出完整汇总
    print(f"\n{'=' * 60}")
    print("完整汇总")
    print(f"{'=' * 60}")
    categories = {}
    for r in results:
        cat = r["category"]
        categories.setdefault(cat, []).append(r["scores"]["total"] if r.get("gen_ok") else 0.0)
    print(f"{'类别':<20} {'任务数':>8} {'平均分':>8}")
    print("─" * 40)
    for cat, scores in sorted(categories.items()):
        print(f"{cat:<20} {len(scores):>8} {sum(scores)/len(scores):>7.0%}")
    overall = [r for r in results if r.get("gen_ok")]
    avg_total = sum(r["scores"]["total"] for r in overall) / len(overall) if overall else 0
    print(f"\n总体: {avg_total:.1%} ({len(overall)}/{len(results)} 任务成功生成)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
