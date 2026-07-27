"""flipped · Locust 并发性能测试（TEST_STRATEGY_OPTIMIZATION.md §2.3）.

模拟并发用户压测后端 assistant API，采集 P50/P95/P99 响应时间与失败率。

测试场景（每用户循环）：
  1. POST /api/v1/assistant/sessions            创建助手会话
  2. POST /api/v1/assistant/sessions/{id}/messages 发消息（mock orchestrator 后台跑）
  3. GET  /api/v1/sessions/{id}                  轮询会话状态（直到 done/error）
  4. GET  /api/v1/assistant/sessions/{id}/history 取对话 turns
  5. DELETE /api/v1/sessions/{id}                清理会话（避免 store 膨胀）

辅助流量：GET /api/v1/sessions（列表）、GET /api/v1/health（探活）。

前置条件（mock 模式，确保可重复）：
  # 1. 关掉真实后端
  pkill -f 'uvicorn api.main:app' || true
  # 2. 启动 mock 后端（独立 session store，避免污染 .sessions.json）
  FLIPPED_MOCK_ORCHESTRATOR=1 FLIPPED_MOCK_WORKER=1 \\
    FLIPPED_SESSION_STORE_PATH=$PWD/.sessions.perf.json \\
    PYTHONPATH=src .venv/bin/python -m uvicorn api.main:app \\
    --host 127.0.0.1 --port 8011 --log-level warning &

跑法（无头模式 60 秒）：
  .venv/bin/locust -f tests/performance/locustfile.py \\
    --host=http://localhost:8011 --headless -u 3 -r 1 -t 60s \\
    --html=reports/perf/locust.html --csv=reports/perf/locust

UI 模式（交互式调参）：
  .venv/bin/locust -f tests/performance/locustfile.py --host=http://localhost:8011

断言（mock 模式下，由 test_stop 钩子强制检查）：
  - 整体失败率 < 1%
  - 任意端点 P95 < 500ms
  - 创建会话 P95 < 100ms（store.create 是纯内存 + 一次 JSON 写）
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from locust import HttpUser, between, events, task


# ---------- 配置 ----------

# 端点 P95 阈值（ms）。mock 模式下理应远低于这些值；超出即判失败。
PER_ENDPOINT_P95_MS: dict[str, int] = {
    "POST /api/v1/assistant/sessions": 100,
    "POST /api/v1/assistant/sessions/{id}/messages": 200,
    "GET /api/v1/sessions/{id} (poll)": 100,
    "GET /api/v1/assistant/sessions/{id}/history": 150,
    "DELETE /api/v1/sessions/{id}": 100,
    "GET /api/v1/sessions": 100,
    "GET /api/v1/health": 80,
}

OVERALL_FAILURE_RATE = 0.01  # 1%
POLL_MAX_ROUNDS = 20
POLL_INTERVAL_SEC = 0.3
TERMINAL_STATUSES = {"done", "error", "review", "idle"}


# ---------- 用户行为 ----------


class FlippedAssistantUser(HttpUser):
    """模拟一个并发用户：创建会话 → 发消息 → 轮询 → 取历史 → 清理。

    wait_time = between(1, 2)：与 task 要求一致，每用户两次请求间隔 1-2 秒。
    """

    wait_time = between(1, 2)

    def on_start(self) -> None:
        # 每个 user 启动时探活一次，确保后端可达（避免后续 503 雪崩）
        with self.client.get("/api/v1/health", name="GET /api/v1/health",
                             catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"health check failed: {resp.status_code}")
            else:
                resp.success()

    @task(5)
    def full_assistant_flow(self) -> None:
        """主流程：create → message → poll → history → delete。"""
        # 1. 创建会话
        with self.client.post(
            "/api/v1/assistant/sessions",
            json={
                "title": f"perf-{uuid.uuid4().hex[:6]}",
                "mode": "agent",
                "model_alias": "coder",
            },
            name="POST /api/v1/assistant/sessions",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"create session: status={resp.status_code} body={resp.text[:200]}")
                return
            try:
                session_id = resp.json()["id"]
            except (KeyError, json.JSONDecodeError) as exc:
                resp.failure(f"create session parse: {exc}")
                return
            resp.success()

        # 2. 发消息（mock orchestrator 后台跑，立即返回 task_id）
        with self.client.post(
            f"/api/v1/assistant/sessions/{session_id}/messages",
            json={
                "text": "create app.py with print(hello)",
                "mode": "agent",
                # 关掉审批门，避免 mock 跑挂起等用户决策
                "orchestrator": {"require_approval": False, "max_iterations": 5},
            },
            name="POST /api/v1/assistant/sessions/{id}/messages",
            catch_response=True,
        ) as resp:
            if resp.status_code == 409:
                # 并发守卫：同会话已有未完成任务。视为业务正常，不挂红。
                resp.success()
                return
            if resp.status_code != 200:
                resp.failure(f"send message: status={resp.status_code} body={resp.text[:200]}")
                return
            resp.success()

        # 3. 轮询状态直到终态（最多 POLL_MAX_ROUNDS * POLL_INTERVAL_SEC 秒）
        final_status: str | None = None
        for _ in range(POLL_MAX_ROUNDS):
            time.sleep(POLL_INTERVAL_SEC)
            with self.client.get(
                f"/api/v1/sessions/{session_id}",
                name="GET /api/v1/sessions/{id} (poll)",
                catch_response=True,
            ) as resp:
                if resp.status_code != 200:
                    continue
                try:
                    final_status = resp.json().get("status")
                except json.JSONDecodeError:
                    continue
                if final_status in TERMINAL_STATUSES:
                    break

        # 4. 取对话历史（即使状态没到终态也取一次，验证 store.events 通路）
        with self.client.get(
            f"/api/v1/assistant/sessions/{session_id}/history",
            name="GET /api/v1/assistant/sessions/{id}/history",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"history: status={resp.status_code}")
            elif not isinstance(resp.json(), list):
                resp.failure("history: response is not a list")
            else:
                resp.success()

        # 5. 清理：删除会话，避免 store 无限膨胀影响后续轮的测量
        with self.client.delete(
            f"/api/v1/sessions/{session_id}",
            name="DELETE /api/v1/sessions/{id}",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"delete: status={resp.status_code}")

    @task(2)
    def list_sessions(self) -> None:
        """读流量：列会话。混合读写比例 ≈ 5:2，模拟前端 Sidebar 刷新。"""
        with self.client.get(
            "/api/v1/sessions",
            name="GET /api/v1/sessions",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"list: status={resp.status_code}")
            elif not isinstance(resp.json(), list):
                resp.failure("list: response is not a list")
            else:
                resp.success()


# ---------- 断言钩子（test_stop 时统一检查 P95 / 失败率） ----------


def _format_stats_table(stats: Any) -> str:
    """把 locust stats 渲染成 markdown 表，便于贴到 TEST_LOG.md。

    name 参数已含 "METHOD /path" 前缀（便于断言字典对齐），这里直接用 entry.name，
    不再前缀 method，避免 "GET GET /..." 双重前缀。
    """
    rows = [
        "| endpoint | reqs | fails | P50(ms) | P95(ms) | P99(ms) | RPS |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in stats.entries.values():
        if entry.method is None or entry.num_requests == 0:
            continue
        p50 = entry.get_response_time_percentile(0.50) or 0
        p95 = entry.get_response_time_percentile(0.95) or 0
        p99 = entry.get_response_time_percentile(0.99) or 0
        fail_ratio = entry.fail_ratio or 0.0
        fails = int(entry.num_requests * fail_ratio)
        rows.append(
            f"| {entry.name} | {entry.num_requests} | {fails} | "
            f"{p50:.0f} | {p95:.0f} | {p99:.0f} | {entry.total_rps:.2f} |"
        )
    return "\n".join(rows)


@events.test_stop.add_listener
def _assert_perf_baseline(environment: Any, **kwargs: Any) -> None:
    """测试结束时强制断言 P95 + 失败率，不达标则让 locust 退出码非零。"""
    stats = environment.stats
    failures: list[str] = []

    # 1. 端点级 P95 检查
    # locust stats.entries 的 key 是 (name, method) —— name 在前，method 在后
    # （见 locust.stats.RequestStats.log_request）。本文件里 name 已含 "METHOD /path" 前缀。
    for name, threshold_ms in PER_ENDPOINT_P95_MS.items():
        # 三种 method 都试一遍，匹配上即取（name 在前，method 在后）
        entry = (
            stats.entries.get((name, "POST"))
            or stats.entries.get((name, "GET"))
            or stats.entries.get((name, "DELETE"))
            or stats.entries.get((name, "PUT"))
        )
        if entry is None or entry.num_requests == 0:
            continue
        p95 = entry.get_response_time_percentile(0.95) or 0
        if p95 > threshold_ms:
            failures.append(
                f"P95 violation: {name} P95={p95:.0f}ms > threshold={threshold_ms}ms"
            )

    # 2. 整体失败率检查（locust StatsEntry 没有 .failures 属性，用 fail_ratio 反推）
    total_reqs = stats.total.num_requests
    fail_ratio = stats.total.fail_ratio or 0.0
    total_fails = int(total_reqs * fail_ratio)
    if total_reqs > 0:
        if fail_ratio > OVERALL_FAILURE_RATE:
            failures.append(
                f"failure rate {fail_ratio:.2%} > threshold {OVERALL_FAILURE_RATE:.2%}"
                f" (fails={total_fails} / reqs={total_reqs})"
            )

    # 3. 输出汇总（无论成败，便于 TEST_LOG 留痕）
    print("\n" + "=" * 60)
    print("Locust 性能基线汇总（mock 模式）")
    print("=" * 60)
    print(_format_stats_table(stats))
    print(f"\n总请求数: {total_reqs} | 总失败: {total_fails} | 整体 RPS: {stats.total.total_rps:.2f}")

    if failures:
        print("\n❌ 性能基线未达标：")
        for f in failures:
            print(f"  - {f}")
        # 把失败标记进 environment，让 locust 进程退出码非零
        environment.process_exit_code = 1
    else:
        print("\n✅ 性能基线达标（所有端点 P95 < 阈值 & 失败率 < 1%）")


@events.test_start.add_listener
def _on_test_start(environment: Any, **kwargs: Any) -> None:
    """启动时打印一行环境信息，便于复盘。"""
    print(
        f"\n[locust] 开始压测 host={environment.host} "
        f"users={environment.parsed_options.num_users} "
        f"spawn_rate={environment.parsed_options.spawn_rate} "
        f"run_time={environment.parsed_options.run_time}s"
    )
    # 友好提示：mock 后端必须开着
    if os.environ.get("FLIPPED_MOCK_ORCHESTRATOR") != "1":
        # 不阻断（用户可能用了别的方式 mock），只提示
        print("[locust] 提示：当前进程未设置 FLIPPED_MOCK_ORCHESTRATOR=1，"
              "若后端非 mock 会真调 LLM，结果不可重复。")
