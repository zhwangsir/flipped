#!/usr/bin/env python3
"""重跑提取bug任务：HumanEval/10, 92, 129, 154。
修复 extract_completion：更鲁棒地剥离 ```python 标记。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import httpx

API_URL = "http://127.0.0.1:8002/v1/chat/completions"
API_KEY = "JdM8LcFzoPXjc9Xh2EI9YX5PykvCkNj5KDN51OYlAEVfYvDG"
MODEL_ID = "moonshotai/Kimi-K3"
TEMPERATURE = 0.0
MAX_TOKENS = 1024
REQUEST_TIMEOUT = 180
EXEC_TIMEOUT = 10
DATASET_FILE = "/data/humaneval.jsonl"
OUT_FILE = "/results/humaneval_rerun_bug.json"
BUG_TASKS = {10, 92, 129, 154}  # HumanEval task indices


def load_dataset():
    with open(DATASET_FILE) as f:
        return [json.loads(line) for line in f]


def call_model(prompt: str) -> dict:
    body = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": False,
        "enable_thinking": False,  # 关闭thinking加速
    }
    t0 = time.time()
    try:
        with httpx.Client(timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=15), trust_env=False) as client:
            r = client.post(API_URL, json=body, headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            })
        latency = time.time() - t0
        if r.status_code != 200:
            return {"ok": False, "latency": latency, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        data = r.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        return {"ok": True, "latency": latency, "content": msg.get("content", "") or ""}
    except Exception as e:
        return {"ok": False, "latency": time.time() - t0, "error": str(e)[:200]}


def extract_completion_fixed(content: str, entry_point: str) -> str:
    """修复版：更鲁棒地剥离 ```python 标记"""
    # 1. 尝试匹配 ```python ... ``` 或 ```Python ... ```（带闭合）
    m = re.search(r"```[pP]ython[^\n]*\n(.*?)```", content, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 2. 尝试匹配 ``` ... ```（不带语言标识）
    m = re.search(r"```\n(.*?)```", content, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 3. 没有闭合的 ``` —— 手动剥离开头的 ```python 标记
    # 先剥离开头的 ```python 或 ``` 标记
    code = re.sub(r"^```[pP]ython[^\n]*\n", "", content.strip())
    code = re.sub(r"^```[^\n]*\n", "", code)
    # 剥离结尾的 ```
    code = re.sub(r"\n```\s*$", "", code)
    # 如果还有残留的 ``` 开头（无换行情况）
    code = re.sub(r"^```[pP]ython\s*", "", code)
    code = re.sub(r"^```\s*", "", code)
    return code.strip()


def build_humaneval_prompt(problem: dict) -> str:
    prompt = problem["prompt"]
    entry_point = problem["entry_point"]
    instruction = (
        f"Complete the following Python function `{entry_point}`. "
        "Output ONLY the complete function (including the def line) in a Python code block. "
        "Do not include explanations or test code.\n\n"
        f"{prompt}"
    )
    return instruction


def run_test(problem: dict, completion: str) -> dict:
    prompt = problem["prompt"]
    test = problem["test"]
    entry_point = problem["entry_point"]
    if re.search(rf"\bdef\s+{entry_point}\s*\(", completion):
        full_code = completion + "\n\n" + test + f"\n\ncheck({entry_point})\n"
    else:
        full_code = prompt + completion + "\n\n" + test + f"\n\ncheck({entry_point})\n"
    result = {"passed": False, "error": ""}
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir="/tmp") as f:
            f.write(full_code)
            f_path = f.name
        r = subprocess.run(
            [sys.executable, f_path],
            capture_output=True, text=True, timeout=EXEC_TIMEOUT,
            env={"HOME": "/tmp", "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")},
        )
        if r.returncode == 0:
            result["passed"] = True
        else:
            result["error"] = (r.stderr.strip() or r.stdout.strip())[:300]
    except subprocess.TimeoutExpired:
        result["error"] = "TimeoutExpired"
    except Exception as e:
        result["error"] = str(e)[:200]
    finally:
        if "f_path" in locals():
            os.unlink(f_path)
    return result


def main():
    dataset = load_dataset()
    os.makedirs("/results", exist_ok=True)
    results = []
    for idx in sorted(BUG_TASKS):
        problem = dataset[idx]
        task_id = problem.get("task_id", f"HumanEval/{idx}")
        prompt = build_humaneval_prompt(problem)
        print(f"[{task_id}] calling model...", end=" ", flush=True)
        gen = call_model(prompt)
        if not gen["ok"]:
            print(f"GEN FAIL: {gen.get('error','')[:60]}")
            results.append({"task_id": task_id, "gen_ok": False, "error": gen.get("error", ""), "passed": False})
            continue
        completion = extract_completion_fixed(gen["content"], problem["entry_point"])
        test_result = run_test(problem, completion)
        status = "PASS" if test_result["passed"] else "FAIL"
        print(f"{status} ({gen['latency']:.1f}s) preview={repr(completion[:50])}")
        results.append({
            "task_id": task_id,
            "gen_ok": True,
            "latency": gen["latency"],
            "completion_preview": completion[:200],
            "passed": test_result["passed"],
            "error": test_result["error"],
        })
    with open(OUT_FILE, "w") as f:
        json.dump({"bug_tasks": list(sorted(BUG_TASKS)), "results": results}, f, indent=2, ensure_ascii=False)
    passed = sum(1 for r in results if r.get("passed"))
    print(f"\n重跑完成: {passed}/{len(results)} 通过，结果保存到 {OUT_FILE}")


if __name__ == "__main__":
    main()
