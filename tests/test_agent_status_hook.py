"""M127 · Agent 状态 hook 模块测试。

覆盖：
- AgentStatus 枚举值
- AgentState.to_dict
- StatusHook 注册/更新/获取
- list_active / list_waiting / list_finished
- subscribe / unsubscribe 回调（含 fail-open）
- webhook relay（真实本地 HTTP 服务 + fail-open 失败不阻塞）
- stats 统计
- 状态转换（active→finished, active→failed, active→waiting→finished 等）
- 多 Agent 并发追踪（线程安全）
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from driving.agent_status_hook import AgentStatus, AgentState, StatusHook


# --------------------------------------------------------------------------- 枚举

class TestAgentStatus:
    def test_enum_values(self):
        """五态枚举值符合预期。"""
        assert AgentStatus.active.value == "active"
        assert AgentStatus.waiting.value == "waiting"
        assert AgentStatus.finished.value == "finished"
        assert AgentStatus.failed.value == "failed"
        assert AgentStatus.idle.value == "idle"

    def test_enum_is_string(self):
        """枚举继承 str，便于 JSON 序列化。"""
        assert isinstance(AgentStatus.active, str)
        assert AgentStatus.active == "active"


# --------------------------------------------------------------------------- AgentState

class TestAgentState:
    def test_to_dict_contains_all_fields(self):
        """to_dict 包含全部字段且 status 为字符串值。"""
        state = AgentState(
            agent_id="agent-1",
            status=AgentStatus.active,
            task_id="task-1",
            worktree_path="/tmp/wt-1",
            timestamp="2026-07-16T00:00:00+00:00",
            metadata={"iteration": 3},
        )
        d = state.to_dict()
        assert d["agent_id"] == "agent-1"
        assert d["status"] == "active"
        assert d["task_id"] == "task-1"
        assert d["worktree_path"] == "/tmp/wt-1"
        assert d["timestamp"] == "2026-07-16T00:00:00+00:00"
        assert d["metadata"] == {"iteration": 3}

    def test_to_dict_metadata_is_copy(self):
        """to_dict 返回的 metadata 是副本，修改不影响原对象。"""
        meta = {"k": "v"}
        state = AgentState(agent_id="a", status=AgentStatus.idle, metadata=meta)
        d = state.to_dict()
        d["metadata"]["k"] = "changed"
        assert state.metadata["k"] == "v"

    def test_default_timestamp_and_metadata(self):
        """未提供 timestamp/metadata 时有合理默认值。"""
        state = AgentState(agent_id="a", status=AgentStatus.idle)
        assert state.timestamp != ""
        assert state.metadata == {}


# --------------------------------------------------------------------------- 注册/更新/获取

class TestRegisterUpdateGet:
    def test_register_sets_idle(self):
        """新注册的 Agent 初始状态为 idle。"""
        hook = StatusHook()
        state = hook.register("agent-1", task_id="t1", worktree_path="/tmp/wt")
        assert state.agent_id == "agent-1"
        assert state.status == AgentStatus.idle
        assert state.task_id == "t1"
        assert state.worktree_path == "/tmp/wt"

    def test_register_is_idempotent(self):
        """重复注册返回已有状态，不重置。"""
        hook = StatusHook()
        hook.register("agent-1")
        hook.update("agent-1", AgentStatus.active)
        # 再次注册：应返回 active 而非重置为 idle
        again = hook.register("agent-1")
        assert again.status == AgentStatus.active

    def test_get_state_unregistered_returns_none(self):
        """未注册的 Agent 查询返回 None。"""
        hook = StatusHook()
        assert hook.get_state("nope") is None

    def test_update_changes_status_and_preserves_fields(self):
        """更新状态后 task_id/worktree_path 保留，metadata 合并。"""
        hook = StatusHook()
        hook.register("agent-1", task_id="t1", worktree_path="/tmp/wt",
                      metadata={"env": "dev"})
        new = hook.update("agent-1", AgentStatus.active, metadata={"iter": 1})
        assert new.status == AgentStatus.active
        assert new.task_id == "t1"
        assert new.worktree_path == "/tmp/wt"
        assert new.metadata["env"] == "dev"
        assert new.metadata["iter"] == 1

    def test_update_unregistered_auto_registers(self):
        """对未注册 Agent 调 update 自动注册到目标状态（fail-open）。"""
        hook = StatusHook()
        new = hook.update("ghost", AgentStatus.active)
        assert new is not None
        assert new.status == AgentStatus.active
        assert hook.get_state("ghost").status == AgentStatus.active

    def test_update_same_status_no_op(self):
        """状态未变且无新 metadata 时不触发通知（返回旧状态对象）。"""
        hook = StatusHook()
        hook.register("agent-1")
        hook.update("agent-1", AgentStatus.active)
        first = hook.get_state("agent-1")
        returned = hook.update("agent-1", AgentStatus.active)
        assert returned.status == AgentStatus.active
        # 未变化时不分发：用一个回调验证不会触发
        called = []
        hook.subscribe(lambda aid, old, new: called.append(aid))
        hook.update("agent-1", AgentStatus.active)  # 同状态、无 metadata
        assert called == []


# --------------------------------------------------------------------------- 列表查询

class TestListByStatus:
    def test_list_active_waiting_finished(self):
        """list_active/waiting/finished 正确分桶。"""
        hook = StatusHook()
        hook.register("a1"); hook.update("a1", AgentStatus.active)
        hook.register("a2"); hook.update("a2", AgentStatus.active)
        hook.register("a3"); hook.update("a3", AgentStatus.waiting)
        hook.register("a4"); hook.update("a4", AgentStatus.finished)
        hook.register("a5")  # idle

        active = hook.list_active()
        waiting = hook.list_waiting()
        finished = hook.list_finished()

        assert {s.agent_id for s in active} == {"a1", "a2"}
        assert {s.agent_id for s in waiting} == {"a3"}
        assert {s.agent_id for s in finished} == {"a4"}
        # idle 不在任何上述列表中
        assert all(s.status == AgentStatus.active for s in active)


# --------------------------------------------------------------------------- 订阅

class TestSubscribe:
    def test_subscribe_receives_state_change(self):
        """订阅者在状态变化时收到回调，含 old/new。"""
        hook = StatusHook()
        hook.register("a1")
        events = []
        hook.subscribe(lambda aid, old, new: events.append((aid, old, new)))
        hook.update("a1", AgentStatus.active)

        assert len(events) == 1
        aid, old, new = events[0]
        assert aid == "a1"
        assert old is not None and old.status == AgentStatus.idle
        assert new.status == AgentStatus.active

    def test_unsubscribe_stops_callbacks(self):
        """取消订阅后不再收到回调。"""
        hook = StatusHook()
        hook.register("a1")
        events = []

        def cb(aid, old, new):
            events.append(aid)

        hook.subscribe(cb)
        hook.update("a1", AgentStatus.active)
        assert len(events) == 1

        assert hook.unsubscribe(cb) is True
        hook.update("a1", AgentStatus.waiting)
        assert len(events) == 1  # 没有新增

    def test_unsubscribe_unknown_returns_false(self):
        """取消未订阅的回调返回 False。"""
        hook = StatusHook()
        assert hook.unsubscribe(lambda *a: None) is False

    def test_subscriber_exception_fail_open(self):
        """订阅者抛异常不影响主流程与其他订阅者（fail-open）。"""
        hook = StatusHook()
        hook.register("a1")
        ok_events = []

        def bad(aid, old, new):
            raise RuntimeError("boom")

        def good(aid, old, new):
            ok_events.append(aid)

        hook.subscribe(bad)
        hook.subscribe(good)
        # 不应抛异常
        result = hook.update("a1", AgentStatus.active)
        assert result.status == AgentStatus.active
        # good 仍被调用
        assert ok_events == ["a1"]


# --------------------------------------------------------------------------- webhook

def _start_capture_server(captured: list[dict]) -> tuple[HTTPServer, str]:
    """启动一个本地 HTTP 服务，把收到的 POST body 记录到 captured 列表。"""
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            try:
                captured.append(json.loads(body))
            except Exception:
                captured.append({"raw": body})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *args):  # 静默
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/hook"
    return server, url


class TestWebhookRelay:
    def test_relay_to_webhook_posts_state_change(self):
        """状态变化时 webhook 收到正确的 JSON 载荷。"""
        captured: list[dict] = []
        server, url = _start_capture_server(captured)
        try:
            hook = StatusHook()
            hook.relay_to_webhook(url)
            hook.register("a1", task_id="t1")
            hook.update("a1", AgentStatus.active)

            assert len(captured) == 1
            payload = captured[0]
            assert payload["event"] == "agent_status_changed"
            assert payload["agent_id"] == "a1"
            assert payload["old_status"] == "idle"
            assert payload["new_status"] == "active"
            assert payload["state"]["task_id"] == "t1"
            assert payload["state"]["status"] == "active"
        finally:
            server.shutdown()

    def test_webhook_failure_does_not_block(self):
        """webhook 不可达时状态更新仍成功（fail-open）。"""
        hook = StatusHook()
        # 指向一个未监听的端口，必然连接失败
        hook.relay_to_webhook("http://127.0.0.1:1/nonexistent")
        hook.register("a1")
        result = hook.update("a1", AgentStatus.active)
        # 不抛异常，状态已更新
        assert result is not None
        assert result.status == AgentStatus.active
        assert hook.get_state("a1").status == AgentStatus.active


# --------------------------------------------------------------------------- stats

class TestStats:
    def test_stats_counts_by_status(self):
        """stats 按状态分桶统计，含订阅者/webhook 计数。"""
        hook = StatusHook()
        hook.register("a1"); hook.update("a1", AgentStatus.active)
        hook.register("a2"); hook.update("a2", AgentStatus.active)
        hook.register("a3"); hook.update("a3", AgentStatus.waiting)
        hook.register("a4"); hook.update("a4", AgentStatus.finished)
        hook.register("a5"); hook.update("a5", AgentStatus.failed)
        hook.register("a6")  # idle
        hook.subscribe(lambda *a: None)
        hook.relay_to_webhook("http://127.0.0.1:1/x")

        s = hook.stats()
        assert s["total"] == 6
        assert s["active"] == 2
        assert s["waiting"] == 1
        assert s["finished"] == 1
        assert s["failed"] == 1
        assert s["idle"] == 1
        assert s["subscribers"] == 1
        assert s["webhooks"] == 1

    def test_stats_empty(self):
        """空 hook 的 stats 全零。"""
        hook = StatusHook()
        s = hook.stats()
        assert s["total"] == 0
        assert s["active"] == 0
        assert s["subscribers"] == 0
        assert s["webhooks"] == 0


# --------------------------------------------------------------------------- 状态转换

class TestStateTransitions:
    def test_active_to_finished(self):
        """active → finished 转换。"""
        hook = StatusHook()
        hook.register("a1")
        hook.update("a1", AgentStatus.active)
        assert hook.get_state("a1").status == AgentStatus.active
        hook.update("a1", AgentStatus.finished)
        assert hook.get_state("a1").status == AgentStatus.finished
        # finished 后出现在 list_finished
        assert any(s.agent_id == "a1" for s in hook.list_finished())
        # 不再出现在 list_active
        assert all(s.agent_id != "a1" for s in hook.list_active())

    def test_active_to_failed(self):
        """active → failed 转换。"""
        hook = StatusHook()
        hook.register("a1")
        hook.update("a1", AgentStatus.active)
        hook.update("a1", AgentStatus.failed)
        assert hook.get_state("a1").status == AgentStatus.failed

    def test_active_to_waiting_to_finished(self):
        """active → waiting（等人类）→ finished 完整审批链。"""
        hook = StatusHook()
        hook.register("a1")
        transitions = []
        hook.subscribe(lambda aid, old, new: transitions.append(
            (old.status.value if old else None, new.status.value)
        ))

        hook.update("a1", AgentStatus.active)
        hook.update("a1", AgentStatus.waiting)
        hook.update("a1", AgentStatus.finished)

        assert hook.get_state("a1").status == AgentStatus.finished
        assert transitions == [
            ("idle", "active"),
            ("active", "waiting"),
            ("waiting", "finished"),
        ]


# --------------------------------------------------------------------------- 并发

class TestConcurrency:
    def test_concurrent_multi_agent_tracking(self):
        """多线程并发注册/更新多个 Agent，最终状态一致（线程安全）。"""
        hook = StatusHook()
        n_agents = 20
        barrier = threading.Barrier(n_agents)

        def worker(i: int):
            agent_id = f"agent-{i}"
            barrier.wait()  # 尽量同时起步
            hook.register(agent_id, task_id=f"task-{i}")
            hook.update(agent_id, AgentStatus.active)
            hook.update(agent_id, AgentStatus.finished)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_agents)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 全部应处于 finished
        assert len(hook.list_finished()) == n_agents
        assert len(hook.list_active()) == 0
        s = hook.stats()
        assert s["total"] == n_agents
        assert s["finished"] == n_agents
        # 每个 agent 都有独立且正确的 task_id
        for i in range(n_agents):
            st = hook.get_state(f"agent-{i}")
            assert st is not None
            assert st.status == AgentStatus.finished
            assert st.task_id == f"task-{i}"

    def test_concurrent_subscribe_and_update(self):
        """并发订阅 + 并发更新（各自独立 agent）不抛异常，回调总数正确。

        每个 updater 线程独占一个 agent，避免跨线程对同一 agent 的
        相同状态更新被去重（no-op 优化是预期行为）。
        """
        hook = StatusHook()
        n_threads = 4
        for i in range(n_threads):
            hook.register(f"a{i}")  # idle，不触发通知

        counter = {"n": 0}
        lock = threading.Lock()

        def cb(aid, old, new):
            with lock:
                counter["n"] += 1

        # 并发订阅同一个回调（幂等，最终只注册一个）
        for _ in range(5):
            hook.subscribe(cb)

        n_updates = 10

        def updater(idx: int):
            agent_id = f"a{idx}"
            for _ in range(n_updates):
                # 在 active/waiting 间反复切换以触发通知
                hook.update(agent_id, AgentStatus.waiting)
                hook.update(agent_id, AgentStatus.active)

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 每线程 10 轮 × 2 次切换 = 20 次通知；4 线程共 80 次
        assert counter["n"] == n_threads * n_updates * 2
        for i in range(n_threads):
            assert hook.get_state(f"a{i}").status == AgentStatus.active
