#!/usr/bin/env python3
"""M131 模型能力全方位测试 · 最大化放大模型能力。

针对 GLM-5.2-fp8 和 Kimi-K2.7-Code-4bit 做全方位对比测试，
关键优化：GLM-5.2 关闭 reasoning 模式(enable_thinking=false)，
避免 reasoning tokens 占满 max_tokens 导致 content 为空。

测试维度：
  1. 简单问答（基础推理）
  2. 代码生成（执行能力）
  3. 工具调用（function calling）
  4. 中文理解
  5. 架构规划（GLM-5.2 强项）
  6. 长上下文处理
"""
from __future__ import annotations

import json
import os
import sys
import time
import httpx

EXO_URL = os.environ.get("FLIPPED_MODEL_BASE_URL", "http://100.64.201.37:52415/v1")
API_KEY = os.environ.get("EXO_API_KEY", "dummy")

MODELS = {
    "GLM-5.2": "mlx-community/GLM-5.2-fp8",
    "Kimi-K2.7-Code": "mlx-community/Kimi-K2.7-Code-4bit",
}

# 不同任务的参数配置（关键：GLM-5.2 关闭 reasoning）
TASK_CONFIGS = {
    "qa": {"max_tokens": 1024, "temperature": 0.3, "enable_thinking": False},
    "code": {"max_tokens": 2048, "temperature": 0.1, "enable_thinking": False},
    "tool": {"max_tokens": 1024, "temperature": 0.0, "enable_thinking": False},
    "chinese": {"max_tokens": 1024, "temperature": 0.3, "enable_thinking": False},
    "architect": {"max_tokens": 2048, "temperature": 0.2, "enable_thinking": False},
    "long_ctx": {"max_tokens": 1536, "temperature": 0.2, "enable_thinking": False},
}

TESTS = [
    {
        "name": "qa",
        "desc": "简单问答",
        "messages": [{"role": "user", "content": "What is 17 * 23? Answer with just the number."}],
        "expect_contains": ["391"],
        "weight": 1.0,
    },
    {
        "name": "code",
        "desc": "代码生成",
        "messages": [{"role": "user", "content": (
            "Write a Python function `fib(n)` that returns the nth Fibonacci number. "
            "Include type hints and a docstring. Only output the code block."
        )}],
        "expect_contains": ["def fib", "return"],
        "weight": 2.0,
    },
    {
        "name": "tool",
        "desc": "工具调用",
        "messages": [{"role": "user", "content": "Search the web for the latest Python 3.13 release notes."}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for information",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Search query"}},
                    "required": ["query"],
                },
            },
        }],
        "expect_tool_call": "web_search",
        "weight": 1.5,
    },
    {
        "name": "chinese",
        "desc": "中文理解",
        "messages": [{"role": "user", "content": "请用中文解释什么是闭包(closure)，并给出一个简单的 JavaScript 例子。"}],
        "expect_contains": ["闭包", "function"],
        "weight": 1.0,
    },
    {
        "name": "architect",
        "desc": "架构规划",
        "messages": [{"role": "user", "content": (
            "Design a microservice architecture for an e-commerce platform. "
            "List the key services, their responsibilities, and how they communicate. "
            "Be concise (max 300 words)."
        )}],
        "expect_contains": ["service", "API"],
        "weight": 2.0,
    },
    {
        "name": "long_ctx",
        "desc": "长上下文",
        "messages": [{"role": "user", "content": (
            "Summarize the following in 3 bullet points:\n\n"
            + "\n".join(f"Point {i}: " + ("Lorem ipsum dolor sit amet. " * 20)
                        for i in range(1, 11))
        )}],
        "expect_contains": ["•"],
        "weight": 1.0,
    },
]


def call_model(model_id: str, test: dict, timeout: float = 120.0) -> dict:
    """调用模型，返回 {ok, latency, content, tool_calls, error, tokens}."""
    cfg = TASK_CONFIGS.get(test["name"], {})
    body = {
        "model": model_id,
        "messages": test["messages"],
        "max_tokens": cfg.get("max_tokens", 1024),
        "temperature": cfg.get("temperature", 0.3),
        "enable_thinking": cfg.get("enable_thinking", False),
        "stream": False,
    }
    if "tools" in test:
        body["tools"] = test["tools"]
        body["tool_choice"] = "auto"

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
        tool_calls = msg.get("tool_calls", []) or []

        # 统计 token
        usage = data.get("usage", {})
        prompt_t = usage.get("prompt_tokens", 0)
        completion_t = usage.get("completion_tokens", 0)
        reasoning_t = usage.get("reasoning_tokens", 0) or 0

        return {
            "ok": True,
            "latency": latency,
            "content": content,
            "tool_calls": tool_calls,
            "tokens": {"prompt": prompt_t, "completion": completion_t, "reasoning": reasoning_t},
        }
    except Exception as e:
        return {"ok": False, "latency": time.time() - t0, "error": str(e)[:200]}


def evaluate(result: dict, test: dict) -> dict:
    """评估结果，返回 {passed, score, details}."""
    if not result["ok"]:
        return {"passed": False, "score": 0.0, "details": f"ERROR: {result.get('error', 'unknown')}"}

    passed = True
    details = []

    # 内容检查
    content = result.get("content", "")
    if "expect_contains" in test:
        for kw in test["expect_contains"]:
            if kw.lower() not in content.lower():
                passed = False
                details.append(f"missing: {kw}")

    # 工具调用检查
    if "expect_tool_call" in test:
        tcs = result.get("tool_calls", [])
        found = any(
            tc.get("function", {}).get("name") == test["expect_tool_call"]
            or tc.get("function", {}).get("name", "").endswith(test["expect_tool_call"])
            for tc in tcs if isinstance(tc, dict)
        )
        if not found:
            # exo 可能把 tool call 放 content 里
            if test["expect_tool_call"] not in content:
                passed = False
                details.append(f"no tool_call: {test['expect_tool_call']}")

    # 长度检查（代码类至少 50 字符）
    if test["name"] == "code" and len(content) < 50:
        passed = False
        details.append(f"code too short: {len(content)} chars")

    # reasoning token 占比检查（GLM-5.2 关键指标）
    tokens = result.get("tokens", {})
    total_completion = tokens.get("completion", 0) + tokens.get("reasoning", 0)
    reasoning_ratio = tokens.get("reasoning", 0) / total_completion if total_completion > 0 else 0

    score = test.get("weight", 1.0) if passed else 0.0
    return {
        "passed": passed,
        "score": score,
        "details": "; ".join(details) if details else "OK",
        "reasoning_ratio": reasoning_ratio,
    }


def main():
    print("=" * 80)
    print("M131 模型能力全方位测试 · 最大化放大模型能力")
    print(f"Endpoint: {EXO_URL}")
    print("=" * 80)

    results = {}
    for model_name, model_id in MODELS.items():
        print(f"\n{'─' * 60}")
        print(f"模型: {model_name} ({model_id})")
        print(f"{'─' * 60}")
        results[model_name] = {"tests": [], "total_score": 0.0, "max_score": 0.0}

        for test in TESTS:
            print(f"\n  [{test['name']}] {test['desc']}...", end=" ", flush=True)
            result = call_model(model_id, test)
            eval_ = evaluate(result, test)

            results[model_name]["tests"].append({
                "name": test["name"],
                "desc": test["desc"],
                "passed": eval_["passed"],
                "score": eval_["score"],
                "latency": result.get("latency", 0),
                "details": eval_.get("details", ""),
                "tokens": result.get("tokens", {}),
                "reasoning_ratio": eval_.get("reasoning_ratio", 0),
                "content_preview": (result.get("content", "") or "")[:150],
                "tool_calls": result.get("tool_calls", []),
            })
            results[model_name]["total_score"] += eval_["score"]
            results[model_name]["max_score"] += test.get("weight", 1.0)

            status = "✓ PASS" if eval_["passed"] else "✗ FAIL"
            latency = result.get("latency", 0)
            tokens = result.get("tokens", {})
            r_ratio = eval_.get("reasoning_ratio", 0)
            print(f"{status} ({latency:.1f}s, tokens: p={tokens.get('prompt',0)} "
                  f"c={tokens.get('completion',0)} r={tokens.get('reasoning',0)} "
                  f"r_ratio={r_ratio:.0%})")
            if not eval_["passed"]:
                print(f"    → {eval_['details']}")
                print(f"    preview: {result.get('content', '')[:100]}")

    # 汇总
    print(f"\n{'=' * 80}")
    print("汇总")
    print(f"{'=' * 80}")
    print(f"{'模型':<20} {'得分':>8} {'满分':>8} {'通过率':>8} {'平均延迟':>10}")
    print("─" * 60)
    for model_name, data in results.items():
        total = data["total_score"]
        max_s = data["max_score"]
        passed = sum(1 for t in data["tests"] if t["passed"])
        total_tests = len(data["tests"])
        avg_latency = sum(t["latency"] for t in data["tests"]) / total_tests if total_tests else 0
        print(f"{model_name:<20} {total:>8.1f} {max_s:>8.1f} "
              f"{passed}/{total_tests:>4} {avg_latency:>9.1f}s")

    # 维度对比
    print(f"\n{'维度':<15} {'GLM-5.2':>30} {'Kimi-K2.7-Code':>30}")
    print("─" * 80)
    for i, test in enumerate(TESTS):
        glm = results["GLM-5.2"]["tests"][i]
        kimi = results["Kimi-K2.7-Code"]["tests"][i]
        glm_s = "✓" if glm["passed"] else "✗"
        kimi_s = "✓" if kimi["passed"] else "✗"
        glm_str = f"{glm_s} ({glm['latency']:.1f}s, r={glm['reasoning_ratio']:.0%})"
        kimi_str = f"{kimi_s} ({kimi['latency']:.1f}s, r={kimi['reasoning_ratio']:.0%})"
        print(f"{test['desc']:<13} {glm_str:>30} {kimi_str:>30}")

    # 保存 JSON
    out_path = "/Users/wangzhenyu/Desktop/ALLProject/flipped/scripts/model_test_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n详细结果已保存: {out_path}")

    # 推荐分工
    print(f"\n{'=' * 80}")
    print("推荐模型分工（基于测试结果）")
    print(f"{'=' * 80}")
    glm_score = results["GLM-5.2"]["total_score"]
    kimi_score = results["Kimi-K2.7-Code"]["total_score"]

    # 按维度找各自强项
    dim_results = {}
    for i, test in enumerate(TESTS):
        glm = results["GLM-5.2"]["tests"][i]
        kimi = results["Kimi-K2.7-Code"]["tests"][i]
        dim_results[test["name"]] = {
            "glm": {"passed": glm["passed"], "latency": glm["latency"], "score": glm["score"]},
            "kimi": {"passed": kimi["passed"], "latency": kimi["latency"], "score": kimi["score"]},
        }

    # 推荐
    recommendations = []
    for dim, r in dim_results.items():
        if r["glm"]["passed"] and r["kimi"]["passed"]:
            if r["glm"]["latency"] < r["kimi"]["latency"]:
                recommendations.append(f"  {dim}: GLM-5.2 更快 ({r['glm']['latency']:.1f}s vs {r['kimi']['latency']:.1f}s)")
            else:
                recommendations.append(f"  {dim}: Kimi 更快 ({r['kimi']['latency']:.1f}s vs {r['glm']['latency']:.1f}s)")
        elif r["glm"]["passed"]:
            recommendations.append(f"  {dim}: GLM-5.2 通过，Kimi 失败 → GLM-5.2")
        elif r["kimi"]["passed"]:
            recommendations.append(f"  {dim}: Kimi 通过，GLM-5.2 失败 → Kimi")
        else:
            recommendations.append(f"  {dim}: 都未通过")

    print("\n".join(recommendations))
    return 0


if __name__ == "__main__":
    sys.exit(main())
