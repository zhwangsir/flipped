#!/usr/bin/env python3
"""重跑 9 个超时任务：HumanEval/23, 37, 57, 58, 87, 139, 140, 142, 143。
策略：每个任务最多重试 6 次，直到生成成功（排除网络因素，只测模型能力）。
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
REQUEST_TIMEOUT = 300  # 加大到 300s 给足生成时间
EXEC_TIMEOUT = 10
MAX_RETRIES = 6  # 每个任务最多重试 6 次
DATASET_FILE = "/data/humaneval.jsonl"
OUT_FILE = "/results/humaneval_rerun_timeout.json"
TIMEOUT_TASKS = {23, 37, 57, 58, 87, 139, 140, 142, 143}


def load_dataset():
    with open(DATASET_FILE) as f:
        return [json.loads(line) for line in f]


def call_model_once(prompt: str, enable_thinking: bool) -> dict:
    body = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": False,
        "enable_thinking": enable_thinking,
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
        content = msg.get("content", "") or ""
        if not content.strip():
            return {"ok": False, "latency": latency, "error": "empty content"}
        return {"ok": True, "latency": latency, "content": content}
    except Exception as e:
        return {"ok": False, "latency": time.time() - t0, "error": str(e)[:200]}


def call_model_with_retry(prompt: str, task_id: str) -> dict:
    """重试直到成功，交替开/关 thinking"""
    attempts = []
    for i in range(MAX_RETRIES):
        enable_thinking = (i % 2 == 0)  # 交替开/关
        r = call_model_once(prompt, enable_thinking)
        attempts.append({"attempt": i + 1, "thinking": enable_thinking,
                         "ok": r["ok"], "latency": r["latency"], "error": r.get("error", "")})
        if r["ok"]:
            r["attempts"] = attempts
            return r
        print(f"    retry {i+1}/{MAX_RETRIES} thinking={enable_thinking} FAIL ({r['latency']:.0f}s): {r.get('error','')[:50]}", flush=True)
        time.sleep(3)  # 间隔 3s 避免限流
    r["attempts"] = attempts
    return r


def extract_completion(content: str, entry_point: str) -> str:
    """鲁棒提取代码块"""
    m = re.search(r"```[pP]ython[^\n]*\n(.*?)```", content, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\n(.*?)```", content, re.DOTALL)
    if m:
        return m.group(1).strip()
    code = re.sub(r"^```[pP]ython[^\n]*\n", "", content.strip())
    code = re.sub(r"^```[^\n]*\n", "", code)
    code = re.sub(r"\n```\s*$", "", code)
    code = re.sub(r"^```[pP]ython\s*", "", code)
    code = re.sub(r"^```\s*", "", code)
    return code.strip()


def build_humaneval_prompt(problem: dict) -> str:
    prompt = problem["prompt"]
    entry_point = problem["entry_point"]
    return (
        f"Complete the following Python function `{entry_point}`. "
        "Output ONLY the complete function (including the def line) in a Python code block. "
        "Do not include explanations or test code.\n\n"
        f"{prompt}"
    )


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
    for idx in sorted(TIMEOUT_TASKS):
        problem = dataset[idx]
        task_id = problem.get("task_id", f"HumanEval/{idx}")
        prompt = build_humaneval_prompt(problem)
        print(f"[{task_id}] retrying...", flush=True)
        gen = call_model_with_retry(prompt, task_id)
        if not gen["ok"]:
            print(f"  GEN FAIL after {MAX_RETRIES} attempts: {gen.get('error','')[:60]}", flush=True)
            results.append({"task_id": task_id, "gen_ok": False,
                            "attempts": gen.get("attempts", []), "passed": False})
        else:
            completion = extract_completion(gen["content"], problem["entry_point"])
            test_result = run_test(problem, completion)
            status = "PASS" if test_result["passed"] else "FAIL"
            n_att = len(gen.get("attempts", []))
            print(f"  {status} (attempts={n_att}, {gen['latency']:.1f}s)", flush=True)
            results.append({
                "task_id": task_id, "gen_ok": True, "latency": gen["latency"],
                "attempts": gen.get("attempts", []),
                "completion_preview": completion[:200],
                "passed": test_result["passed"], "error": test_result["error"],
            })
        # 增量保存
        with open(OUT_FILE, "w") as f:
            json.dump({"timeout_tasks": list(sorted(TIMEOUT_TASKS)), "results": results}, f, indent=2, ensure_ascii=False)
    passed = sum(1 for r in results if r.get("passed"))
    gen_ok = sum(1 for r in results if r.get("gen_ok"))
    print(f"\n重跑完成: gen_ok={gen_ok}/{len(results)}, passed={passed}/{len(results)}")
    print(f"结果保存: {OUT_FILE}")


if __name__ == "__main__":
    main()
