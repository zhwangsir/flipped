#!/usr/bin/env python3
"""K3 综合能力深度评测：代码、算法、多语言、调试、推理、长上下文。

设计目标：用尽可能多的维度验证模型能力，并与 K2.7-Code / GLM-5.2 对比。
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

EXO_URL = "http://43.119.32.180:8002/v1"
API_KEY = "JdM8LcFzoPXjc9Xh2EI9YX5PykvCkNj5KDN51OYlAEVfYvDG"
MODEL_ID = "moonshotai/Kimi-K3"
OUT_PATH = "/Users/wangzhenyu/Desktop/ALLProject/flipped/scripts/k3_comprehensive_eval.json"


# ---------- 评测任务定义 ----------
TASKS = [
    # ===== Python 基础代码生成（保留原 6 题作为基准） =====
    {
        "id": "fib_recursive",
        "category": "python_basic",
        "name": "递归斐波那契",
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
            "recursion": r"fib\s*\(.*\)",
        },
    },
    {
        "id": "binary_search",
        "category": "python_basic",
        "name": "二分查找",
        "lang": "python",
        "prompt": (
            "Write a Python function `binary_search(arr: list[int], target: int) -> int` "
            "that returns the index of target in a sorted array, or -1 if not found. "
            "Handle edge cases (empty array, target not found). "
            "Include type hints and a docstring. Only output the code block."
        ),
        "test_cases": [
            ([], 5, -1), ([1], 1, 0), ([1], 2, -1),
            ([1, 3, 5, 7, 9], 5, 2), ([1, 3, 5, 7, 9], 6, -1),
            ([1, 3, 5, 7, 9], 1, 0), ([1, 3, 5, 7, 9], 9, 4),
        ],
        "quality_checks": {
            "type_hints": r"def\s+binary_search\s*\(\s*arr\s*:\s*list\[int\]\s*,\s*target\s*:\s*int\s*\)\s*->\s*int",
            "docstring": r'("""|\'\'\')',
            "edge_empty": r"(len\s*\(\s*arr\s*\)\s*==\s*0|not\s+arr|if\s+not\s+arr)",
            "while_loop": r"while",
        },
    },
    {
        "id": "validate_email",
        "category": "python_basic",
        "name": "邮箱验证",
        "lang": "python",
        "prompt": (
            "Write a Python function `validate_email(email: str) -> bool` that validates "
            "an email address using regex. It should: check for exactly one @, "
            "valid local part (alphanumeric + . _ -), valid domain (alphanumeric + . and TLD >= 2 chars). "
            "Include type hints, docstring, and handle edge cases. Only output the code block."
        ),
        "test_cases": [
            ("user@example.com", True), ("user.name@example.com", True),
            ("user@sub.example.com", True), ("invalid", False),
            ("@example.com", False), ("user@", False),
            ("user@.com", False), ("user@example", False), ("", False),
        ],
        "quality_checks": {
            "type_hints": r"def\s+validate_email\s*\(\s*email\s*:\s*str\s*\)\s*->\s*bool",
            "docstring": r'("""|\'\'\')',
            "regex": r"re\.(match|fullmatch|compile|search)",
            "import_re": r"(import\s+re|from\s+re\s+import)",
        },
    },
    {
        "id": "stack_class",
        "category": "python_basic",
        "name": "栈数据结构",
        "lang": "python",
        "prompt": (
            "Write a Python class `Stack` with methods: push(item), pop() (raises IndexError if empty), "
            "peek() (raises IndexError if empty), is_empty(), and __len__. "
            "Include type hints, docstrings, and use a list internally. Only output the code block."
        ),
        "is_class": True,
        "test_cases": [],
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
        "id": "json_parser",
        "category": "python_basic",
        "name": "简易 JSON 解析器",
        "lang": "python",
        "prompt": (
            "Write a Python function `parse_json(s: str) -> Any` that parses a JSON string "
            "WITHOUT using the json module. Support: null, true, false, numbers, strings, "
            "arrays, and objects. Raise ValueError on invalid input. "
            "Include type hints and docstring. Only output the code block."
        ),
        "test_cases": [
            ("null", None), ("true", True), ("false", False),
            ("42", 42), ('"hello"', "hello"),
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
    },

    # ===== Python 进阶算法与数据结构 =====
    {
        "id": "quick_sort",
        "category": "python_advanced",
        "name": "快速排序",
        "lang": "python",
        "prompt": (
            "Write a Python function `quick_sort(arr: list[int]) -> list[int]` that returns a new sorted list "
            "using the quicksort algorithm. Do not mutate the input. Include type hints, docstring, "
            "and handle empty list. Only output the code block."
        ),
        "test_cases": [
            ([], []), ([3], [3]), ([3, 1, 4, 1, 5, 9, 2, 6], [1, 1, 2, 3, 4, 5, 6, 9]),
            ([5, 4, 3, 2, 1], [1, 2, 3, 4, 5]),
        ],
        "quality_checks": {
            "type_hints": r"def\s+quick_sort\s*\(\s*arr\s*:\s*list\[int\]\s*\)\s*->\s*list\[int\]",
            "docstring": r'("""|\'\'\')',
            "partition": r"(pivot|partition|quick_sort|recursive)",
            "no_mutation": r"(copy|sorted\(|\[\s*\])",
        },
    },
    {
        "id": "lru_cache",
        "category": "python_advanced",
        "name": "手写 LRU 缓存",
        "lang": "python",
        "prompt": (
            "Write a Python class `LRUCache` with `get(key: Any) -> Any` and `put(key: Any, value: Any) -> None`. "
            "When capacity is exceeded, evict the least recently used item. Use OrderedDict or a linked list + dict. "
            "Include type hints, docstrings, and raise KeyError on missing key in get. Only output the code block."
        ),
        "is_class": True,
        "test_cases": [],
        "quality_checks": {
            "class_def": r"class\s+LRUCache",
            "type_hints": r"->\s*(None|Any|int|T)",
            "docstring": r'("""|\'\'\')',
            "get_method": r"def\s+get",
            "put_method": r"def\s+put",
            "ordered_dict_or_linked": r"(OrderedDict|collections\.OrderedDict|_Node|Node|prev|next)",
            "key_error": r"KeyError",
        },
    },
    {
        "id": "trie",
        "category": "python_advanced",
        "name": "Trie 前缀树",
        "lang": "python",
        "prompt": (
            "Write a Python class `Trie` supporting `insert(word: str)`, `search(word: str) -> bool`, "
            "and `starts_with(prefix: str) -> bool`. Include type hints, docstrings. Only output the code block."
        ),
        "is_class": True,
        "test_cases": [],
        "quality_checks": {
            "class_def": r"class\s+Trie",
            "type_hints": r"->\s*(None|bool)",
            "docstring": r'("""|\'\'\')',
            "insert": r"def\s+insert",
            "search": r"def\s+search",
            "starts_with": r"def\s+starts_with",
            "dict_node": r"(dict|defaultdict|children)",
        },
    },
    {
        "id": "graph_bfs",
        "category": "python_advanced",
        "name": "图 BFS 最短路径",
        "lang": "python",
        "prompt": (
            "Write a Python function `shortest_path(graph: dict[str, list[str]], start: str, end: str) -> int` "
            "that returns the shortest path length from start to end in an unweighted directed graph. "
            "Return -1 if no path. Use BFS. Include type hints, docstring. Only output the code block."
        ),
        "test_cases": [
            ({"a": ["b"], "b": ["c"], "c": []}, "a", "c", 2),
            ({"a": ["b"], "b": ["c"], "c": []}, "a", "d", -1),
            ({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}, "a", "d", 2),
            ({"a": []}, "a", "a", 0),
        ],
        "quality_checks": {
            "type_hints": r"def\s+shortest_path\s*\(\s*graph\s*:\s*dict\[str,\s*list\[str\]\]",
            "docstring": r'("""|\'\'\')',
            "bfs": r"(deque|queue|collections\.deque|pop\s*\(\s*0\s*\))",
            "visited": r"(visited|seen)",
        },
    },

    # ===== 多语言能力 =====
    {
        "id": "typescript_promise_all",
        "category": "multi_language",
        "name": "TypeScript Promise.all",
        "lang": "typescript",
        "prompt": (
            "Write a TypeScript generic function `promiseAll<T>(promises: Promise<T>[]): Promise<T[]>` "
            "that behaves like Promise.all (resolve when all succeed, reject with first error). "
            "Do not use the native Promise.all. Include JSDoc/TSDoc comments. Only output the code block."
        ),
        "test_cases": [],
        "quality_checks": {
            "generic": r"promiseAll\s*<\s*T\s*>",
            "jsdoc": r"/\*\*",
            "promise": r"Promise",
            "reject": r"reject",
            "resolve": r"resolve",
        },
    },
    {
        "id": "go_worker_pool",
        "category": "multi_language",
        "name": "Go Worker Pool",
        "lang": "go",
        "prompt": (
            "Write a Go function `WorkerPool(jobs []int, workers int) map[int]int` that processes each job "
            "by squaring it using `workers` goroutines. Use channels for coordination. Include package main, "
            "comments, and handle workers <= 0. Only output the code block."
        ),
        "test_cases": [],
        "quality_checks": {
            "package_main": r"package\s+main",
            "goroutine": r"go\s+",
            "channel": r"chan",
            "sync_or_wait": r"(sync\.WaitGroup|WaitGroup|close\s*\()",
            "comment": r"//",
        },
    },
    {
        "id": "rust_result",
        "category": "multi_language",
        "name": "Rust Result 处理",
        "lang": "rust",
        "prompt": (
            "Write a Rust function `parse_numbers(lines: Vec<String>) -> Result<Vec<i32>, String>` that parses "
            "each line as i32 and returns Err with the first invalid line. Use ? operator. Include doc comments. "
            "Only output the code block."
        ),
        "test_cases": [],
        "quality_checks": {
            "function_def": r"fn\s+parse_numbers",
            "result_type": r"Result\s*<",
            "question_mark": r"\?",
            "doc_comment": r"///",
            "parse": r"parse\s*\(\s*\)",
        },
    },

    # ===== 调试与代码审查 =====
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

    # ===== 推理与数学 =====
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

    # ===== 长上下文 / 指令遵循 =====
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


def call_model(prompt: str, max_tokens: int = None, timeout: float = 1800.0, enable_thinking: bool = True) -> dict:
    body = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "stream": False,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if enable_thinking is not None:
        body["enable_thinking"] = enable_thinking
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
    # Fallback: try any code block
    m = re.search(r"```\n(.*?)```", content, re.DOTALL)
    if m:
        return m.group(1).strip()
    return content.strip()


def run_python_code(code: str, task: dict) -> dict:
    result = {"run_ok": False, "tests_passed": 0, "tests_total": 0, "errors": [], "output": ""}

    test_code = ""
    if task.get("is_class"):
        if task["id"] == "stack_class":
            test_code = """
try:
    s = Stack()
    assert s.is_empty() == True
    assert len(s) == 0
    s.push(1); s.push(2); s.push(3)
    assert len(s) == 3
    assert s.peek() == 3
    assert s.pop() == 3 and s.pop() == 2
    assert s.pop() == 1
    assert s.is_empty() == True
    try: s.pop()
    except IndexError: pass
    else: print("FAIL: pop did not raise IndexError")
    try: s.peek()
    except IndexError: pass
    else: print("FAIL: peek did not raise IndexError")
    print("ALL_TESTS_PASSED")
except Exception as e:
    print(f"TEST_ERROR: {type(e).__name__}: {e}")
"""
        elif task["id"] == "lru_cache":
            test_code = """
try:
    cache = LRUCache(2)
    cache.put(1, 10)
    cache.put(2, 20)
    assert cache.get(1) == 10
    cache.put(3, 30)  # evicts 2
    try:
        cache.get(2)
        print("FAIL: did not evict key 2")
    except KeyError:
        pass
    assert cache.get(3) == 30
    cache.put(4, 40)  # evicts 1
    try:
        cache.get(1)
        print("FAIL: did not evict key 1")
    except KeyError:
        pass
    print("ALL_TESTS_PASSED")
except Exception as e:
    print(f"TEST_ERROR: {type(e).__name__}: {e}")
"""
        elif task["id"] == "trie":
            test_code = """
try:
    t = Trie()
    t.insert("apple")
    assert t.search("apple") == True
    assert t.search("app") == False
    assert t.starts_with("app") == True
    t.insert("app")
    assert t.search("app") == True
    print("ALL_TESTS_PASSED")
except Exception as e:
    print(f"TEST_ERROR: {type(e).__name__}: {e}")
"""
    else:
        func_name = _get_func_name(task["id"])
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


def _get_func_name(task_id: str) -> str:
    mapping = {
        "fib_recursive": "fib",
        "binary_search": "binary_search",
        "validate_email": "validate_email",
        "json_parser": "parse_json",
        "quick_sort": "quick_sort",
        "graph_bfs": "shortest_path",
        "math_sequence": "sum_arithmetic",
    }
    return mapping.get(task_id, task_id)


def check_quality(code: str, checks: dict) -> dict:
    results = {}
    passed = 0
    for name, pattern in checks.items():
        found = bool(re.search(pattern, code, re.MULTILINE | re.DOTALL))
        results[name] = found
        if found:
            passed += 1
    return {"checks": results, "passed": passed, "total": len(checks), "score": passed / len(checks) if checks else 0.0}


def evaluate_task(task: dict, attempt_thinking: bool = True) -> dict:
    """评估单个任务，失败时可选关闭 thinking 重试一次。"""
    gen = call_model(task["prompt"], enable_thinking=attempt_thinking)
    if not gen["ok"] and attempt_thinking:
        # 用关闭 thinking 重试一次，排除超时是否由长思考导致
        gen_retry = call_model(task["prompt"], enable_thinking=False)
        if gen_retry["ok"]:
            gen = gen_retry
            gen["retried_with_no_thinking"] = True
        else:
            gen["retried_with_no_thinking"] = True
            gen["retry_error"] = gen_retry.get("error", "")

    if not gen["ok"]:
        return {
            "id": task["id"],
            "category": task["category"],
            "name": task["name"],
            "gen_ok": False,
            "error": gen.get("error", "unknown"),
            "latency": gen.get("latency", 0),
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
    elif run_result["run_ok"] and "ALL_TESTS_PASSED" in run_result.get("output", ""):
        correctness_score = 1.0
    elif task.get("is_class") and "ALL_TESTS_PASSED" in run_result.get("output", ""):
        correctness_score = 1.0

    quality_score = quality["score"]
    has_syntax_error = run_result.get("stderr", "") and "SyntaxError" in run_result.get("stderr", "")
    completeness = 0.0 if has_syntax_error else 1.0

    # 文本类任务额外检查 expected
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
        "retried_with_no_thinking": gen.get("retried_with_no_thinking", False),
    }


def save_incremental(results: list):
    with open(OUT_PATH, "w") as f:
        json.dump({"model": MODEL_ID, "endpoint": EXO_URL, "results": results}, f, indent=2, ensure_ascii=False, default=str)


def main():
    print("=" * 90)
    print("Kimi-K3 综合能力深度评测")
    print(f"Endpoint: {EXO_URL}")
    print(f"Model: {MODEL_ID}")
    print("=" * 90)

    results = []
    for i, task in enumerate(TASKS, 1):
        print(f"\n[{i}/{len(TASKS)}] [{task['category']}] {task['name']} ...", end=" ", flush=True)
        r = evaluate_task(task)
        results.append(r)
        save_incremental(results)

        if not r["gen_ok"]:
            print(f"✗ 生成失败 ({r['latency']:.1f}s): {r.get('error', '')[:80]}")
            continue

        s = r["scores"]
        print(f"✓ 总分 {s['total']:.0%} (正确 {s['correctness']:.0%} / 质量 {s['quality']:.0%} / 完整 {s['completeness']:.0%}) "
              f"({r['latency']:.1f}s, {r['code_length']} chars)")
        if r.get("retried_with_no_thinking"):
            print("    (首次失败，已用 enable_thinking=False 重试)")
        if r["run"]["tests_total"] > 0:
            print(f"    测试: {r['run']['tests_passed']}/{r['run']['tests_total']} passed")
        elif r["run"].get("output", "").endswith("ALL_TESTS_PASSED"):
            print("    测试: ALL PASSED (类测试)")
        if r["run"]["errors"]:
            for e in r["run"]["errors"][:2]:
                print(f"    错误: {e}")
        failed = [k for k, v in r["quality"]["checks"].items() if not v]
        if failed:
            print(f"    质量检查缺: {', '.join(failed)}")

    # 汇总
    print(f"\n{'=' * 90}")
    print("分类汇总")
    print(f"{'=' * 90}")
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = []
        if r.get("gen_ok"):
            categories[cat].append(r["scores"]["total"])

    print(f"{'类别':<20} {'完成数':>8} {'平均分':>8}")
    print("─" * 40)
    for cat, scores in sorted(categories.items()):
        avg = sum(scores) / len(scores) if scores else 0
        print(f"{cat:<20} {len(scores):>8} {avg:>7.0%}")

    overall_gen_ok = [r for r in results if r.get("gen_ok")]
    if overall_gen_ok:
        avg_total = sum(r["scores"]["total"] for r in overall_gen_ok) / len(overall_gen_ok)
        print(f"\n总体平均分: {avg_total:.1%}  ({len(overall_gen_ok)}/{len(results)} 任务成功生成)")

    print(f"\n详细结果已保存: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
