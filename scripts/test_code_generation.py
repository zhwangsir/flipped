#!/usr/bin/env python3
"""M131 代码生成能力深度评判 · 真正评估代码质量。

不只是检查关键字，而是：
  1. 实际执行生成的代码，验证正确性
  2. 评估代码质量（类型注解、docstring、错误处理、边界情况）
  3. 多种编程任务（算法、数据结构、API、错误处理）
  4. 多语言测试（Python、JavaScript）
  5. 给出量化评分（正确性、完整性、质量、边界处理）
"""
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

EXO_URL = os.environ.get("FLIPPED_MODEL_BASE_URL", "http://100.64.201.37:52415/v1")
API_KEY = os.environ.get("EXO_API_KEY", "dummy")

MODELS = {
    "GLM-5.2": "mlx-community/GLM-5.2-fp8",
    "Kimi-K2.7-Code": "mlx-community/Kimi-K2.7-Code-4bit",
}


# ---------- 代码任务定义 ----------
# 每个任务包含 prompt + 评估函数（运行代码 + 检查质量）
CODE_TASKS = [
    {
        "name": "fib_recursive",
        "desc": "递归斐波那契",
        "lang": "python",
        "prompt": (
            "Write a Python function `fib(n: int) -> int` that returns the nth Fibonacci number "
            "(fib(0)=0, fib(1)=1, fib(2)=1, ...). Use recursion with memoization. "
            "Include type hints and a docstring. Only output the code block."
        ),
        "test_cases": [(0, 0), (1, 1), (2, 1), (5, 5), (10, 55), (20, 6765)],
        "quality_checks": {
            "type_hints": r"def\s+fib\s*\(\s*n\s*:\s*int\s*\)\s*->\s*int",
            "docstring": r'("""|\'\'\')',
            "memoization": r"(cache|memo|lru_cache|functools|dict)",
            "recursion": r"fib\s*\(.*\)",  # 调用自身
        },
    },
    {
        "name": "binary_search",
        "desc": "二分查找",
        "lang": "python",
        "prompt": (
            "Write a Python function `binary_search(arr: list[int], target: int) -> int` "
            "that returns the index of target in a sorted array, or -1 if not found. "
            "Handle edge cases (empty array, target not found). "
            "Include type hints and a docstring. Only output the code block."
        ),
        "test_cases": [
            ([], 5, -1),
            ([1], 1, 0),
            ([1], 2, -1),
            ([1, 3, 5, 7, 9], 5, 2),
            ([1, 3, 5, 7, 9], 6, -1),
            ([1, 3, 5, 7, 9], 1, 0),
            ([1, 3, 5, 7, 9], 9, 4),
        ],
        "quality_checks": {
            "type_hints": r"def\s+binary_search\s*\(\s*arr\s*:\s*list\[int\]\s*,\s*target\s*:\s*int\s*\)\s*->\s*int",
            "docstring": r'("""|\'\'\')',
            "edge_empty": r"(len\s*\(\s*arr\s*\)\s*==\s*0|not\s+arr|if\s+not\s+arr)",
            "while_loop": r"while",
        },
    },
    {
        "name": "validate_email",
        "desc": "邮箱验证",
        "lang": "python",
        "prompt": (
            "Write a Python function `validate_email(email: str) -> bool` that validates "
            "an email address using regex. It should: check for exactly one @, "
            "valid local part (alphanumeric + . _ -), valid domain (alphanumeric + . and TLD >= 2 chars). "
            "Include type hints, docstring, and handle edge cases. Only output the code block."
        ),
        "test_cases": [
            ("user@example.com", True),
            ("user.name@example.com", True),
            ("user@sub.example.com", True),
            ("invalid", False),
            ("@example.com", False),
            ("user@", False),
            ("user@.com", False),
            ("user@example", False),
            ("", False),
        ],
        "quality_checks": {
            "type_hints": r"def\s+validate_email\s*\(\s*email\s*:\s*str\s*\)\s*->\s*bool",
            "docstring": r'("""|\'\'\')',
            "regex": r"re\.(match|fullmatch|compile|search)",
            "import_re": r"(import\s+re|from\s+re\s+import)",
        },
    },
    {
        "name": "stack_class",
        "desc": "栈数据结构",
        "lang": "python",
        "prompt": (
            "Write a Python class `Stack` with methods: push(item), pop() (raises IndexError if empty), "
            "peek() (raises IndexError if empty), is_empty(), and __len__. "
            "Include type hints, docstrings, and use a list internally. Only output the code block."
        ),
        "is_class": True,
        "test_cases": [],  # 特殊处理
        "quality_checks": {
            "class_def": r"class\s+Stack",
            "type_hints": r"->\s*(None|bool|int|Any|T)",
            "docstring": r'("""|\'\'\')',
            "push_method": r"def\s+push",
            "pop_method": r"def\s+pop",
            "peek_method": r"def\s+peek",
            "is_empty_method": r"def\s+is_empty",
            "index_error": r"IndexError",
        },
    },
    {
        "name": "js_debounce",
        "desc": "JS 防抖函数",
        "lang": "javascript",
        "prompt": (
            "Write a JavaScript `debounce(func, delay)` function that returns a debounced version. "
            "The debounced function should only execute after `delay` ms have elapsed since the last call. "
            "Include JSDoc comments. Only output the code block."
        ),
        "test_cases": [],
        "is_js": True,
        "quality_checks": {
            "function_def": r"function\s+debounce|const\s+debounce\s*=|debounce\s*=\s*(function|\()",
            "jsdoc": r"/\*\*",
            "clear_timeout": r"clearTimeout",
            "set_timeout": r"setTimeout",
            "apply_or_call": r"\.apply\(|\.call\(",
        },
    },
    {
        "name": "json_parser",
        "desc": "简易 JSON 解析器",
        "lang": "python",
        "prompt": (
            "Write a Python function `parse_json(s: str) -> Any` that parses a JSON string "
            "WITHOUT using the json module. Support: null, true, false, numbers, strings, "
            "arrays, and objects. Raise ValueError on invalid input. "
            "Include type hints and docstring. Only output the code block."
        ),
        "test_cases": [
            ("null", None),
            ("true", True),
            ("false", False),
            ("42", 42),
            ('"hello"', "hello"),
            ("[1, 2, 3]", [1, 2, 3]),
            ('{"a": 1, "b": 2}', {"a": 1, "b": 2}),
        ],
        "quality_checks": {
            "type_hints": r"def\s+parse_json\s*\(\s*s\s*:\s*str\s*\)\s*->\s*Any",
            "docstring": r'("""|\'\'\')',
            "no_json_import": r"^(?!.*import\s+json)(?!.*from\s+json\s+import)",
            "value_error": r"ValueError",
            "recursive": r"parse_json\s*\(.*\)|def\s+_parse",
        },
        "expect_fail": "invalid json",
    },
]


def call_model(model_id: str, prompt: str, max_tokens: int = None, timeout: float = 1800.0) -> dict:
    """调用模型生成代码。

    质量优先配置（用户要求：不追求速度，不限制 max_tokens 和超时，只追求质量和完整）：
    - enable_thinking=True：开启深度推理
    - max_tokens 不传（None）：让模型自然推理到完成，不人为截断
    - timeout=1800s：给复杂任务充足时间（30分钟），不人为限制
    - temperature=0.1：代码生成低温度，保持确定性
    """
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,  # 代码生成低温度
        "enable_thinking": True,  # 质量优先：开启深度推理
        "stream": False,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    # 不限制 max_tokens：让模型自然完成，不人为截断
    t0 = time.time()
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0), trust_env=False) as client:
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
        content = msg.get("content", "") or ""
        reasoning_content = msg.get("reasoning_content", "") or ""
        usage = data.get("usage", {})
        return {
            "ok": True,
            "latency": latency,
            "content": content,
            "reasoning_content": reasoning_content,
            "tokens": {
                "prompt": usage.get("prompt_tokens", 0),
                "completion": usage.get("completion_tokens", 0),
                "reasoning": usage.get("reasoning_tokens", 0) or 0,
            },
        }
    except Exception as e:
        return {"ok": False, "latency": time.time() - t0, "error": str(e)[:200]}


def extract_code(content: str, lang: str = "python") -> str:
    """从模型输出中提取代码块。"""
    # 优先取 markdown 代码块
    pattern = rf"```(?:{lang})?\n(.*?)```"
    m = re.search(pattern, content, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 退化：如果没有代码块，直接返回内容（可能是纯代码）
    return content.strip()


def run_python_code(code: str, task: dict) -> dict:
    """实际运行 Python 代码并执行测试用例。"""
    result = {"run_ok": False, "tests_passed": 0, "tests_total": 0, "errors": [], "output": ""}

    # 如果是类定义，加测试代码
    test_code = ""
    if task.get("is_class"):
        if task["name"] == "stack_class":
            test_code = """
# --- 测试 ---
try:
    s = Stack()
    assert s.is_empty() == True
    assert len(s) == 0
    s.push(1)
    s.push(2)
    s.push(3)
    assert len(s) == 3
    assert s.is_empty() == False
    assert s.peek() == 3
    assert s.pop() == 3
    assert s.pop() == 2
    assert len(s) == 1
    assert s.pop() == 1
    assert s.is_empty() == True
    # 空栈 pop 应该抛 IndexError
    try:
        s.pop()
        print("FAIL: pop on empty stack did not raise")
    except IndexError:
        pass  # 正确
    except Exception as e:
        print(f"FAIL: pop raised {type(e).__name__} instead of IndexError")
    try:
        s.peek()
        print("FAIL: peek on empty stack did not raise")
    except IndexError:
        pass  # 正确
    except Exception as e:
        print(f"FAIL: peek raised {type(e).__name__} instead of IndexError")
    print("ALL_TESTS_PASSED")
except Exception as e:
    print(f"TEST_ERROR: {type(e).__name__}: {e}")
"""
    else:
        # 普通函数测试
        func_name = _get_func_name(task["name"])
        test_lines = ["# --- 测试 ---", "try:"]
        for tc in task.get("test_cases", []):
            args = tc[:-1]
            expected = tc[-1]
            args_str = ", ".join(repr(a) for a in args)
            expected_repr = repr(expected)
            test_lines.append(f"    result = {func_name}({args_str})")
            test_lines.append(f'    assert result == {expected_repr}, "FAIL: got " + repr(result) + " expected " + repr(expected)')
            result["tests_total"] += 1
        test_lines.append("    print('ALL_TESTS_PASSED')")
        test_lines.append("except Exception as e:")
        test_lines.append("    print('TEST_ERROR: ' + type(e).__name__ + ': ' + str(e))")
        test_code = "\n".join(test_lines)

    full_code = code + "\n\n" + test_code

    # 写入临时文件执行
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(full_code)
        f.flush()
        f_path = f.name

    try:
        r = subprocess.run(
            [sys.executable, f_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = r.stdout.strip()
        result["output"] = output
        result["stderr"] = r.stderr.strip()[:500]
        result["run_ok"] = r.returncode == 0

        if "ALL_TESTS_PASSED" in output:
            result["tests_passed"] = result["tests_total"]
        elif "TEST_ERROR" in output:
            result["errors"].append(output.split("TEST_ERROR:")[-1].strip()[:200])
        else:
            # 解析部分通过
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


def _get_func_name(task_name: str) -> str:
    """从任务名推断函数名。"""
    mapping = {
        "fib_recursive": "fib",
        "binary_search": "binary_search",
        "validate_email": "validate_email",
        "json_parser": "parse_json",
    }
    return mapping.get(task_name, task_name)


def check_quality(code: str, task: dict) -> dict:
    """检查代码质量（类型注解、docstring、错误处理等）。"""
    checks = task.get("quality_checks", {})
    results = {}
    passed = 0
    for name, pattern in checks.items():
        found = bool(re.search(pattern, code, re.MULTILINE | re.DOTALL))
        results[name] = found
        if found:
            passed += 1
    return {
        "checks": results,
        "passed": passed,
        "total": len(checks),
        "score": passed / len(checks) if checks else 0.0,
    }


def evaluate_code_generation(model_id: str, task: dict) -> dict:
    """评估单个模型的代码生成能力。"""
    # 1. 生成代码
    gen = call_model(model_id, task["prompt"])
    if not gen["ok"]:
        return {
            "task": task["name"],
            "gen_ok": False,
            "error": gen.get("error", "unknown"),
            "latency": gen.get("latency", 0),
        }

    content = gen["content"]
    lang = task.get("lang", "python")
    code = extract_code(content, lang)

    # 2. 质量检查
    quality = check_quality(code, task)

    # 3. 运行测试（Python 类）
    run_result = {"run_ok": False, "tests_passed": 0, "tests_total": 0, "errors": []}
    if lang == "python":
        run_result = run_python_code(code, task)
    elif lang == "javascript":
        # JS 只做质量检查，不运行
        run_result = {"run_ok": True, "tests_passed": 0, "tests_total": 0, "errors": [], "note": "JS 不执行运行测试"}

    # 4. 综合评分
    correctness_score = 0.0
    if run_result["run_ok"] and run_result["tests_total"] > 0:
        correctness_score = run_result["tests_passed"] / run_result["tests_total"]
    elif run_result["run_ok"] and run_result.get("output", "").endswith("ALL_TESTS_PASSED"):
        correctness_score = 1.0
    elif task.get("is_class") and "ALL_TESTS_PASSED" in run_result.get("output", ""):
        correctness_score = 1.0

    quality_score = quality["score"]
    code_length = len(code)
    has_syntax_error = run_result.get("stderr", "") and "SyntaxError" in run_result.get("stderr", "")

    # 综合：正确性 50% + 质量 30% + 完整性 20%（无语法错误=1，有=0）
    completeness = 0.0 if has_syntax_error else 1.0
    total_score = (correctness_score * 0.5 + quality_score * 0.3 + completeness * 0.2)

    return {
        "task": task["name"],
        "desc": task["desc"],
        "gen_ok": True,
        "latency": gen["latency"],
        "tokens": gen["tokens"],
        "reasoning_length": len(gen.get("reasoning_content", "")),
        "reasoning_preview": gen.get("reasoning_content", "")[:200],
        "code_length": code_length,
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
        "scores": {
            "correctness": correctness_score,
            "quality": quality_score,
            "completeness": completeness,
            "total": total_score,
        },
    }


def main():
    print("=" * 90)
    print("M131 代码生成能力深度评判")
    print(f"Endpoint: {EXO_URL}")
    print("=" * 90)

    all_results = {}
    for model_name, model_id in MODELS.items():
        print(f"\n{'─' * 70}")
        print(f"模型: {model_name}")
        print(f"{'─' * 70}")
        all_results[model_name] = []

        for task in CODE_TASKS:
            print(f"\n  [{task['name']}] {task['desc']}...", end=" ", flush=True)
            r = evaluate_code_generation(model_id, task)
            all_results[model_name].append(r)

            if not r.get("gen_ok"):
                print(f"✗ 生成失败 ({r.get('latency', 0):.1f}s): {r.get('error', '')[:80]}")
                continue

            scores = r["scores"]
            quality = r["quality"]
            run = r["run"]
            print(f"✓ 总分 {scores['total']:.0%} "
                  f"(正确性 {scores['correctness']:.0%} / 质量 {scores['quality']:.0%} / 完整性 {scores['completeness']:.0%}) "
                  f"({r['latency']:.1f}s, {r['code_length']} chars)")

            # 详细
            if run["tests_total"] > 0:
                print(f"    测试: {run['tests_passed']}/{run['tests_total']} passed")
            elif run.get("output", "").endswith("ALL_TESTS_PASSED"):
                print(f"    测试: ALL PASSED (类测试)")
            if run["errors"]:
                for e in run["errors"][:2]:
                    print(f"    错误: {e}")
            qc = quality["checks"]
            passed_checks = [k for k, v in qc.items() if v]
            failed_checks = [k for k, v in qc.items() if not v]
            if failed_checks:
                print(f"    质量检查: {quality['passed']}/{quality['total']} "
                      f"(缺: {', '.join(failed_checks)})")

    # 汇总
    print(f"\n{'=' * 90}")
    print("汇总")
    print(f"{'=' * 90}")
    print(f"\n{'模型':<18} {'平均总分':>8} {'平均正确性':>10} {'平均质量':>8} {'平均延迟':>10} {'通过任务':>8}")
    print("─" * 75)
    for model_name, results in all_results.items():
        gen_ok = [r for r in results if r.get("gen_ok")]
        if not gen_ok:
            print(f"{model_name:<18} {'N/A':>8}")
            continue
        avg_total = sum(r["scores"]["total"] for r in gen_ok) / len(gen_ok)
        avg_correct = sum(r["scores"]["correctness"] for r in gen_ok) / len(gen_ok)
        avg_quality = sum(r["scores"]["quality"] for r in gen_ok) / len(gen_ok)
        avg_latency = sum(r["latency"] for r in gen_ok) / len(gen_ok)
        passed = sum(1 for r in gen_ok if r["scores"]["total"] >= 0.7)
        print(f"{model_name:<18} {avg_total:>8.0%} {avg_correct:>10.0%} "
              f"{avg_quality:>8.0%} {avg_latency:>9.1f}s {passed}/{len(gen_ok):>3}")

    # 按任务对比
    print(f"\n{'任务':<18} {'GLM-5.2 总分':>14} {'Kimi 总分':>14} {'胜者':>8}")
    print("─" * 60)
    for i, task in enumerate(CODE_TASKS):
        glm = all_results["GLM-5.2"][i]
        kimi = all_results["Kimi-K2.7-Code"][i]
        glm_s = glm.get("scores", {}).get("total", 0) if glm.get("gen_ok") else 0
        kimi_s = kimi.get("scores", {}).get("total", 0) if kimi.get("gen_ok") else 0
        winner = "GLM-5.2" if glm_s > kimi_s else ("Kimi" if kimi_s > glm_s else "平局")
        print(f"{task['desc']:<16} {glm_s:>14.0%} {kimi_s:>14.0%} {winner:>8}")

    # 保存 JSON
    out_path = "/Users/wangzhenyu/Desktop/ALLProject/flipped/scripts/code_gen_eval.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n详细结果已保存: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
