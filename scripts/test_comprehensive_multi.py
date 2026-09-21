#!/usr/bin/env python3
"""通用综合能力评测：支持任意 OpenAI 兼容端点。
用法:
  python3 test_comprehensive_multi.py --model "mlx-community/GLM-5.2-fp8" \
    --endpoint "http://192.168.71.109:52415/v1" --api-key dummy \
    --out glm52_comprehensive_eval.json --label "GLM-5.2-fp8"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import httpx
from typing import Any

# ---- 从 test_k3_comprehensive 导入任务定义和评估函数 ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from test_k3_comprehensive import (
    TASKS,
    extract_code,
    run_python_code,
    check_quality,
    _get_func_name,
)


def call_model(prompt: str, endpoint: str, api_key: str, model_id: str,
               max_tokens: int = None, timeout: float = 1800.0,
               enable_thinking: bool = True) -> dict:
    body = {
        "model": model_id,
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
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0), trust_env=False) as client:
            r = client.post(
                f"{endpoint}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
        latency = time.time() - t0
        if r.status_code != 200:
            return {"ok": False, "latency": latency, "error": f"HTTP {r.status_code}: {r.text[:300]}"}
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
        return {"ok": False, "latency": time.time() - t0, "error": str(e)[:300]}


def evaluate_task(task: dict, endpoint: str, api_key: str, model_id: str,
                  attempt_thinking: bool = True) -> dict:
    gen = call_model(task["prompt"], endpoint, api_key, model_id, enable_thinking=attempt_thinking)
    if not gen["ok"] and attempt_thinking:
        gen_retry = call_model(task["prompt"], endpoint, api_key, model_id, enable_thinking=False)
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


def main():
    parser = argparse.ArgumentParser(description="通用综合能力评测")
    parser.add_argument("--model", required=True, help="模型 ID")
    parser.add_argument("--endpoint", required=True, help="API 端点 (如 http://192.168.71.109:52415/v1)")
    parser.add_argument("--api-key", default="dummy", help="API Key")
    parser.add_argument("--out", required=True, help="输出 JSON 路径")
    parser.add_argument("--label", default="", help="模型显示名称")
    args = parser.parse_args()

    label = args.label or args.model
    print("=" * 90)
    print(f"综合能力深度评测: {label}")
    print(f"Endpoint: {args.endpoint}")
    print(f"Model: {args.model}")
    print("=" * 90)

    results = []
    for i, task in enumerate(TASKS, 1):
        print(f"\n[{i}/{len(TASKS)}] [{task['category']}] {task['name']} ...", end=" ", flush=True)
        r = evaluate_task(task, args.endpoint, args.api_key, args.model)
        results.append(r)
        with open(args.out, "w") as f:
            json.dump({"model": args.model, "label": label, "endpoint": args.endpoint, "results": results},
                      f, indent=2, ensure_ascii=False, default=str)

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

    print(f"\n详细结果已保存: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
