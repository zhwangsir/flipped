#!/usr/bin/env python3
"""
HumanEval 官方评测：OpenAI HumanEval 164 题 pass@1
直接在云服务器上运行，访问 localhost:8002 的 K3 API。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import signal
import httpx
from pathlib import Path

API_URL = "http://127.0.0.1:8002/v1/chat/completions"
API_KEY = "JdM8LcFzoPXjc9Xh2EI9YX5PykvCkNj5KDN51OYlAEVfYvDG"
MODEL_ID = "moonshotai/Kimi-K3"
TEMPERATURE = 0.0
MAX_TOKENS = 1024
REQUEST_TIMEOUT = 180  # 3 分钟，避免上游 63s 504 但给足机会
EXEC_TIMEOUT = 10  # 代码执行超时 10s
OUT_FILE = "/results/humaneval_results.json"
DATASET_FILE = "/data/humaneval.jsonl"


def load_dataset():
    """加载 HumanEval 数据集（优先从 GitHub 下载 JSONL 格式）"""
    if os.path.exists(DATASET_FILE):
        with open(DATASET_FILE) as f:
            return [json.loads(line) for line in f]
    print("Downloading HumanEval dataset from GitHub...")
    urls = [
        "https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl",
        "https://ghp.ci/https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl",
    ]
    with httpx.Client(timeout=60) as client:
        for url in urls:
            try:
                r = client.get(url)
                if r.status_code == 200 and r.text.strip():
                    os.makedirs("/data", exist_ok=True)
                    with open(DATASET_FILE, "w") as f:
                        f.write(r.text)
                    data = [json.loads(line) for line in r.text.strip().split("\n")]
                    print(f"Downloaded {len(data)} problems from {url}")
                    return data
            except Exception as e:
                print(f"  Failed {url}: {e}")
    raise RuntimeError("Failed to download HumanEval dataset from all sources")


def call_model(prompt: str, retry_no_thinking: bool = True) -> dict:
    """调用 K3 API 生成代码"""
    body = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": False,
        "enable_thinking": True,
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
            # 如果失败，尝试关闭 thinking
            if retry_no_thinking:
                return call_model_with_no_thinking(prompt)
            return {"ok": False, "latency": latency, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        data = r.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        return {
            "ok": True,
            "latency": latency,
            "content": msg.get("content", "") or "",
            "reasoning": msg.get("reasoning_content", "") or "",
            "tokens": data.get("usage", {}),
        }
    except Exception as e:
        latency = time.time() - t0
        if retry_no_thinking:
            return call_model_with_no_thinking(prompt)
        return {"ok": False, "latency": latency, "error": str(e)[:200]}


def call_model_with_no_thinking(prompt: str) -> dict:
    """关闭 thinking 重试"""
    body = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": False,
        "enable_thinking": False,
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
            return {"ok": False, "latency": latency, "error": f"HTTP {r.status_code}: {r.text[:200]}", "retried": True}
        data = r.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        return {
            "ok": True,
            "latency": latency,
            "content": msg.get("content", "") or "",
            "reasoning": "",
            "tokens": data.get("usage", {}),
            "retried": True,
        }
    except Exception as e:
        return {"ok": False, "latency": time.time() - t0, "error": str(e)[:200], "retried": True}


def extract_completion(content: str, entry_point: str) -> str:
    """从模型回复中提取代码补全"""
    # 如果有 ```python 代码块，提取代码块内容
    m = re.search(r"```python\n(.*?)```", content, re.DOTALL)
    if m:
        code = m.group(1).strip()
    else:
        m = re.search(r"```\n(.*?)```", content, re.DOTALL)
        if m:
            code = m.group(1).strip()
        else:
            code = content.strip()
    return code


def build_humaneval_prompt(problem: dict) -> str:
    """构建 HumanEval 标准提示（chat 模型适配版）"""
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
    """执行 HumanEval 测试"""
    prompt = problem["prompt"]
    test = problem["test"]
    entry_point = problem["entry_point"]

    # 如果 completion 已包含 def <entry_point>，直接使用 completion
    # 否则将 prompt + completion 拼接（标准 HumanEval 方式）
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
            err = r.stderr.strip()[:300] or r.stdout.strip()[:300]
            result["error"] = err
    except subprocess.TimeoutExpired:
        result["error"] = "TimeoutExpired"
    except Exception as e:
        result["error"] = str(e)[:200]
    finally:
        if "f_path" in locals():
            os.unlink(f_path)
    return result


def main():
    os.makedirs("/results", exist_ok=True)
    os.makedirs("/data", exist_ok=True)

    dataset = load_dataset()
    total = len(dataset)
    print(f"{'='*80}")
    print(f"HumanEval 官方评测 — pass@1")
    print(f"模型: {MODEL_ID}")
    print(f"接口: {API_URL}")
    print(f"温度: {TEMPERATURE}  max_tokens: {MAX_TOKENS}")
    print(f"任务数: {total}")
    print(f"{'='*80}\n")

    results = []
    passed = 0
    failed_gen = 0
    failed_test = 0
    start_time = time.time()

    for i, problem in enumerate(dataset):
        task_id = problem.get("task_id", f"HumanEval/{i}")
        prompt = build_humaneval_prompt(problem)

        print(f"[{i+1}/{total}] {task_id} ...", end=" ", flush=True)

        gen = call_model(prompt)
        if not gen["ok"]:
            failed_gen += 1
            print(f"GEN FAIL ({gen['latency']:.1f}s): {gen.get('error','')[:60]}")
            results.append({
                "task_id": task_id,
                "gen_ok": False,
                "error": gen.get("error", ""),
                "latency": gen.get("latency", 0),
                "passed": False,
            })
            # 增量保存
            with open(OUT_FILE, "w") as f:
                json.dump({"model": MODEL_ID, "total": total, "results": results}, f, indent=2, ensure_ascii=False)
            continue

        completion = extract_completion(gen["content"], problem["entry_point"])
        test_result = run_test(problem, completion)

        if test_result["passed"]:
            passed += 1
            print(f"PASS ({gen['latency']:.1f}s)")
        else:
            failed_test += 1
            print(f"FAIL ({gen['latency']:.1f}s): {test_result['error'][:60]}")

        results.append({
            "task_id": task_id,
            "gen_ok": True,
            "latency": gen["latency"],
            "tokens": gen.get("tokens", {}),
            "completion_preview": completion[:200],
            "passed": test_result["passed"],
            "error": test_result["error"],
            "retried": gen.get("retried", False),
        })

        # 增量保存
        with open(OUT_FILE, "w") as f:
            json.dump({"model": MODEL_ID, "total": total, "results": results}, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start_time
    pass_rate = passed / total if total > 0 else 0

    print(f"\n{'='*80}")
    print(f"评测完成")
    print(f"{'='*80}")
    print(f"总任务数: {total}")
    print(f"生成成功: {total - failed_gen}")
    print(f"生成失败: {failed_gen}")
    print(f"测试通过: {passed}")
    print(f"测试失败: {total - failed_gen - passed}")
    print(f"pass@1: {pass_rate:.2%}")
    print(f"总耗时: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"平均延迟: {sum(r['latency'] for r in results if r.get('gen_ok'))/max(1, sum(1 for r in results if r.get('gen_ok'))):.1f}s")

    # 保存最终结果
    final = {
        "model": MODEL_ID,
        "endpoint": API_URL,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "total": total,
        "gen_ok": total - failed_gen,
        "gen_failed": failed_gen,
        "passed": passed,
        "failed": total - failed_gen - passed,
        "pass_at_1": pass_rate,
        "elapsed_seconds": elapsed,
        "avg_latency": sum(r['latency'] for r in results if r.get('gen_ok')) / max(1, sum(1 for r in results if r.get('gen_ok'))),
        "results": results,
    }
    with open(OUT_FILE, "w") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {OUT_FILE}")


if __name__ == "__main__":
    main()
