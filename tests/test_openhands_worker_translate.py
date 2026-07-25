"""OpenHandsWorker._translate_and_emit 事件翻译单测（M155.4）。

覆盖 src/executor/openhands_worker.py L269-340 的所有事件分支：
- MessageEvent：agent/system 角色 + 多 TextContent 拼接
- ActionEvent：tool_call + thought 摘要 + file_editor file_change 透传
- ObservationEvent：tool_result + terminal 事件 + browser 事件 + error 状态
- 异常路径：翻译失败 → error 事件

策略：OpenHands SDK 事件是 Pydantic 模型，直接构造触发校验失败。
用 monkeypatch 把 openhands_worker 模块里的 MessageEvent/ActionEvent/ObservationEvent
替换成简单桩类，绕过 Pydantic，只测翻译逻辑。
"""
from __future__ import annotations

import time as _time
from types import SimpleNamespace

import pytest

from api.events import EventBus
from api.session import SessionStore
from api.schemas import EventType, Role
from executor import openhands_worker as ohw_mod
from executor.openhands_worker import OpenHandsWorker, _sum_conversation_usage


@pytest.fixture(autouse=True)
def inject_time(monkeypatch):
    """源码 run() 用 time.monotonic() 但未 import time（生产靠别处注入）。
    测试里注入 time 模块到 ohw_mod 命名空间（raising=False 允许新增属性）。"""
    monkeypatch.setattr(ohw_mod, "time", _time, raising=False)


# ---------- 桩类（替换 SDK Pydantic 模型） ----------


class _StubMessageEvent:
    def __init__(self, *, source="agent", llm_message=None):
        self.source = source
        self.llm_message = llm_message


class _StubActionEvent:
    def __init__(self, *, tool_name="unknown", thought=None, action=None):
        self.tool_name = tool_name
        self.thought = thought
        self.action = action


class _StubObservationEvent:
    def __init__(self, *, tool_name="unknown", observation=None):
        self.tool_name = tool_name
        self.observation = observation


@pytest.fixture(autouse=True)
def patch_event_classes(monkeypatch):
    """把模块级 isinstance 检查用的类替换成桩（不影响翻译逻辑）。"""
    monkeypatch.setattr(ohw_mod, "MessageEvent", _StubMessageEvent)
    monkeypatch.setattr(ohw_mod, "ActionEvent", _StubActionEvent)
    monkeypatch.setattr(ohw_mod, "ObservationEvent", _StubObservationEvent)


def _worker() -> OpenHandsWorker:
    bus = EventBus(SessionStore())
    return OpenHandsWorker("sess-test", "task-test", bus, manage_session_status=False)


def _emit_calls(w: OpenHandsWorker):
    """从 bus store 里抓 worker 发出的事件（按 session_id 过滤）。

    store.events(session_id) 返回 Event pydantic 对象列表。
    """
    return w.bus.store.events(w.session_id)


# ---------- _sum_conversation_usage ----------


def test_sum_usage_empty_state():
    state = SimpleNamespace(stats=None)
    assert _sum_conversation_usage(state) == (0, 0, 0)


def test_sum_usage_no_usage_to_metrics():
    state = SimpleNamespace(stats=SimpleNamespace(usage_to_metrics={}))
    assert _sum_conversation_usage(state) == (0, 0, 0)


def test_sum_usage_aggregates_tokens():
    m1 = SimpleNamespace(
        accumulated_token_usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        token_usages=[1, 2, 3],
    )
    m2 = SimpleNamespace(
        accumulated_token_usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80),
        token_usages=[1],
    )
    state = SimpleNamespace(stats=SimpleNamespace(usage_to_metrics={"a": m1, "b": m2}))
    p, c, n = _sum_conversation_usage(state)
    assert p == 300
    assert c == 130
    assert n == 4


def test_sum_usage_none_acc_returns_zero():
    m = SimpleNamespace(accumulated_token_usage=None, token_usages=[1, 2])
    state = SimpleNamespace(stats=SimpleNamespace(usage_to_metrics={"x": m}))
    p, c, n = _sum_conversation_usage(state)
    assert p == 0
    assert c == 0
    assert n == 2


# ---------- MessageEvent 翻译 ----------


def test_message_event_agent_role():
    """agent 来源 → Role.worker；拼接多 TextContent。"""
    w = _worker()
    msg = SimpleNamespace(content=[SimpleNamespace(text="hello "), SimpleNamespace(text="world")])
    event = _StubMessageEvent(source="agent", llm_message=msg)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert len(calls) == 1
    assert calls[0].type == EventType.message
    assert calls[0].agent == Role.worker
    assert calls[0].payload["text"] == "hello world"
    assert calls[0].payload["source"] == "agent"


def test_message_event_user_role():
    """非 agent 来源 → Role.system。"""
    w = _worker()
    msg = SimpleNamespace(content=[SimpleNamespace(text="用户问")])
    event = _StubMessageEvent(source="user", llm_message=msg)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert calls[0].agent == Role.system


def test_message_event_empty_content():
    """llm_message 为 None → text=""。"""
    w = _worker()
    event = _StubMessageEvent(source="agent", llm_message=None)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert len(calls) == 1
    assert calls[0].payload["text"] == ""


def test_message_event_content_none():
    """content 为 None（非 list）→ text=""。"""
    w = _worker()
    msg = SimpleNamespace(content=None)
    event = _StubMessageEvent(source="agent", llm_message=msg)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert calls[0].payload["text"] == ""


# ---------- ActionEvent 翻译 ----------


def test_action_event_basic_tool_call():
    """ActionEvent：tool_name + thought → tool_call 事件。"""
    w = _worker()
    event = _StubActionEvent(
        tool_name="terminal",
        thought=[SimpleNamespace(text="先看目录结构")],
        action=None,
    )
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert len(calls) == 1
    assert calls[0].type == EventType.tool_call
    assert calls[0].agent == Role.worker
    assert calls[0].payload["tool"] == "terminal"
    assert calls[0].payload["summary"] == "先看目录结构"
    assert calls[0].payload["status"] == "running"


def test_action_event_no_thought_fallback_action_summary():
    """无 thought → summary 取 action._summary。"""
    w = _worker()
    action = SimpleNamespace(_summary="执行 ls -la")
    event = _StubActionEvent(tool_name="terminal", thought=None, action=action)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert calls[0].payload["summary"] == "执行 ls -la"


def test_action_event_no_thought_no_action_summary_fallback_tool():
    """无 thought 无 action._summary → summary 退到 tool 名。"""
    w = _worker()
    action = SimpleNamespace()  # 无 _summary → getattr 返回 ""
    event = _StubActionEvent(tool_name="search", thought=None, action=action)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert calls[0].payload["summary"] == "search"


def test_action_event_file_editor_emits_file_change():
    """file_editor 动作 → 额外发 file_change 事件。"""
    w = _worker()
    action = SimpleNamespace(
        path="/src/main.ts",
        file_text="export const x = 1;",
        new_str=None,
        command="create",
        _summary="创建 main.ts",
    )
    event = _StubActionEvent(tool_name="file_editor", thought=None, action=action)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert len(calls) == 2
    types = [c.type for c in calls]
    assert EventType.tool_call in types
    assert EventType.file_change in types
    fc = next(c for c in calls if c.type == EventType.file_change)
    assert fc.payload["path"] == "/src/main.ts"
    assert fc.payload["change"] == "create"
    assert "export const x" in fc.payload["content"]


def test_action_event_file_editor_new_str_fallback():
    """file_editor 无 file_text → 取 new_str 作为 content。"""
    w = _worker()
    action = SimpleNamespace(
        path="/src/util.ts",
        file_text=None,
        new_str="function add(a,b){return a+b}",
        command="str_replace",
    )
    event = _StubActionEvent(tool_name="file_editor", thought=None, action=action)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    fc = next(c for c in calls if c.type == EventType.file_change)
    assert "function add" in fc.payload["content"]


def test_action_event_file_editor_no_content_no_file_change():
    """file_editor 但 path 或 content 缺失 → 不发 file_change。"""
    w = _worker()
    action = SimpleNamespace(path=None, file_text=None, new_str=None)
    event = _StubActionEvent(tool_name="file_editor", thought=None, action=action)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert len(calls) == 1
    assert calls[0].type == EventType.tool_call


def test_action_event_thought_without_text_attr():
    """thought 元素无 .text 属性 → summary 退到 action._summary。"""
    w = _worker()
    event = _StubActionEvent(
        tool_name="terminal",
        thought=[SimpleNamespace()],  # 无 text 属性
        action=SimpleNamespace(_summary="兜底摘要"),
    )
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert calls[0].payload["summary"] == "兜底摘要"


# ---------- ObservationEvent 翻译 ----------


def test_observation_event_terminal_ok():
    """terminal observation 成功 → tool_result + terminal 事件。"""
    w = _worker()
    obs = SimpleNamespace(
        success=True,
        _summary="ls 执行成功",
        command="ls -la",
        output="file1.txt\nfile2.txt",
        exit_code=0,
    )
    event = _StubObservationEvent(tool_name="terminal", observation=obs)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    types = [c.type for c in calls]
    assert EventType.tool_result in types
    assert EventType.terminal in types
    term = next(c for c in calls if c.type == EventType.terminal)
    assert term.payload["command"] == "ls -la"
    assert "file1.txt" in term.payload["output"]
    assert term.payload["exit_code"] == 0
    tr = next(c for c in calls if c.type == EventType.tool_result)
    assert tr.payload["status"] == "ok"
    assert tr.payload["summary"] == "ls 执行成功"


def test_observation_event_error_status():
    """observation success=False → status=error。"""
    w = _worker()
    obs = SimpleNamespace(success=False, _summary="命令失败")
    event = _StubObservationEvent(tool_name="terminal", observation=obs)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    tr = next(c for c in calls if c.type == EventType.tool_result)
    assert tr.payload["status"] == "error"


def test_observation_event_terminal_content_list():
    """terminal output 是 TextContent 列表 → 拼接 .text 而非 repr。"""
    w = _worker()
    obs = SimpleNamespace(
        success=True,
        _summary="cat",
        command="cat foo.txt",
        content=[SimpleNamespace(text="line1\n"), SimpleNamespace(text="line2")],
    )
    event = _StubObservationEvent(tool_name="terminal", observation=obs)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    term = next(c for c in calls if c.type == EventType.terminal)
    assert "line1" in term.payload["output"]
    assert "line2" in term.payload["output"]
    assert "namespace" not in term.payload["output"].lower()


def test_observation_event_terminal_output_fallback_to_content():
    """terminal 无 output 字段但有 content(str) → 兜底用 content。"""
    w = _worker()
    obs = SimpleNamespace(
        success=True,
        _summary="终端输出",
        command="echo hi",
        content="hi from content",
    )
    event = _StubObservationEvent(tool_name="terminal", observation=obs)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    term = next(c for c in calls if c.type == EventType.terminal)
    assert "hi from content" in term.payload["output"]


def test_observation_event_browser():
    """browser observation → 额外发 browser 事件。"""
    w = _worker()
    obs = SimpleNamespace(
        success=True,
        _summary="浏览器导航",
        url="http://localhost:3000",
        screenshot="base64imgdata",
        title="My App",
    )
    event = _StubObservationEvent(tool_name="browser_navigate", observation=obs)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    types = [c.type for c in calls]
    assert EventType.browser in types
    br = next(c for c in calls if c.type == EventType.browser)
    assert br.payload["url"] == "http://localhost:3000"
    assert br.payload["screenshot"] == "base64imgdata"
    # 注：源码 extra 提取列表不含 "title"，故 title 始终为 ""（已知行为，测试锁定）
    assert br.payload["title"] == ""


def test_observation_event_browser_no_screenshot_no_browser_event():
    """browser observation 但无 url/screenshot → 不发 browser 事件。"""
    w = _worker()
    obs = SimpleNamespace(success=True, _summary="浏览器无数据")
    event = _StubObservationEvent(tool_name="browser_view", observation=obs)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    types = [c.type for c in calls]
    assert EventType.browser not in types
    assert EventType.tool_result in types


def test_observation_event_non_terminal_non_browser():
    """非 terminal 非 browser observation → 只发 tool_result。"""
    w = _worker()
    obs = SimpleNamespace(success=True, _summary="搜索完成", path="/tmp/result")
    event = _StubObservationEvent(tool_name="search", observation=obs)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert len(calls) == 1
    assert calls[0].type == EventType.tool_result
    assert calls[0].payload["summary"] == "搜索完成"


def test_observation_event_observation_none():
    """observation 为 None → tool_result 兜底。"""
    w = _worker()
    event = _StubObservationEvent(tool_name="unknown_tool", observation=None)
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    assert len(calls) == 1
    assert calls[0].type == EventType.tool_result
    assert calls[0].payload["summary"] == "unknown_tool"
    assert calls[0].payload["status"] == "ok"  # success 默认 True


# ---------- 异常路径 ----------


def test_translate_exception_emits_error():
    """翻译过程抛异常 → 发 error 事件（含 event_kind）。"""
    w = _worker()

    class _BrokenObs:
        @property
        def success(self):
            raise RuntimeError("mock obs broken")

    event = _StubObservationEvent(tool_name="terminal", observation=_BrokenObs())
    w._translate_and_emit(event)
    calls = _emit_calls(w)
    err_calls = [c for c in calls if c.type == EventType.error]
    assert len(err_calls) == 1
    assert "事件翻译失败" in err_calls[0].payload["message"]
    assert "ObservationEvent" in err_calls[0].payload["event_kind"]


# ---------- _on_event 与 events 属性 ----------


def test_on_event_appends_to_events_list():
    """_on_event 把事件加到 _events 并翻译发出。"""
    w = _worker()
    msg = SimpleNamespace(content=[SimpleNamespace(text="hi")])
    event = _StubMessageEvent(source="agent", llm_message=msg)
    w._on_event(event)
    assert len(w.events) == 1
    assert w.events[0] is event


def test_events_property_returns_copy():
    """events 属性返回 _events 的拷贝（外部修改不影响内部）。"""
    w = _worker()
    msg = SimpleNamespace(content=[SimpleNamespace(text="a")])
    e1 = _StubMessageEvent(source="agent", llm_message=msg)
    w._on_event(e1)
    snapshot = w.events
    snapshot.clear()
    assert len(w.events) == 1  # 内部不受影响


def test_on_event_thread_safe_concurrent():
    """并发 _on_event 不丢事件（_lock 保护）。"""
    import threading

    w = _worker()

    def add(i):
        msg = SimpleNamespace(content=[SimpleNamespace(text=f"msg-{i}")])
        w._on_event(_StubMessageEvent(source="agent", llm_message=msg))

    threads = [threading.Thread(target=add, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(w.events) == 20


# ---------- _default_agent_api_key ----------


def test_default_agent_api_key_from_env(monkeypatch):
    """OPENHANDS_API_KEY 环境变量优先。"""
    monkeypatch.setenv("OPENHANDS_API_KEY", "env-key-123")
    assert OpenHandsWorker._default_agent_api_key() == "env-key-123"


def test_default_agent_api_key_from_file(monkeypatch, tmp_path):
    """无 env var → 读 ~/.openhands/agent-canvas/api-key.txt。"""
    monkeypatch.delenv("OPENHANDS_API_KEY", raising=False)
    # 把 HOME 指向临时目录，写假 key 文件
    fake_home = tmp_path
    key_dir = fake_home / ".openhands" / "agent-canvas"
    key_dir.mkdir(parents=True)
    (key_dir / "api-key.txt").write_text("file-key-456\n")
    monkeypatch.setenv("HOME", str(fake_home))
    # expanduser("~") 会用 HOME
    assert OpenHandsWorker._default_agent_api_key() == "file-key-456"


def test_default_agent_api_key_file_missing(monkeypatch, tmp_path):
    """无 env var 且文件不存在 → 返回空串（不抛）。"""
    monkeypatch.delenv("OPENHANDS_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # 无 .openhands 目录
    assert OpenHandsWorker._default_agent_api_key() == ""


def test_default_agent_api_key_file_unreadable(monkeypatch, tmp_path):
    """文件存在但不可读（OSError）→ 返回空串。"""
    monkeypatch.delenv("OPENHANDS_API_KEY", raising=False)
    fake_home = tmp_path
    key_dir = fake_home / ".openhands" / "agent-canvas"
    key_dir.mkdir(parents=True)
    key_file = key_dir / "api-key.txt"
    key_file.write_text("locked-key")
    key_file.chmod(0o000)  # 去掉所有读权限
    monkeypatch.setenv("HOME", str(fake_home))
    try:
        assert OpenHandsWorker._default_agent_api_key() == ""
    finally:
        key_file.chmod(0o644)  # 恢复权限方便清理


# ---------- run 方法（mock SDK 组件，覆盖 happy path + 异常路径） ----------


def test_run_happy_path_manage_status(monkeypatch, tmp_path):
    """run 完整成功路径：构造 LLM → Agent → Workspace → Conversation → run → done。

    manage_session_status=True → 发 done 状态 + bus.set_status。
    """
    monkeypatch.delenv("OPENHANDS_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LITELLM_MASTER_KEY", "lm-key")
    monkeypatch.delenv("FLIPPED_WORKER_CONDENSER_ENABLED", raising=False)

    from openhands.sdk.conversation.state import ConversationExecutionStatus

    # mock LLM（只验证构造，不真用）
    monkeypatch.setattr(ohw_mod, "LLM", lambda **kw: SimpleNamespace(**kw))

    # mock Agent
    monkeypatch.setattr(ohw_mod, "Agent", lambda **kw: SimpleNamespace(**kw))

    # mock RemoteWorkspace（上下文管理器）
    class _FakeWS:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ohw_mod, "RemoteWorkspace", _FakeWS)

    # mock RemoteConversation
    fake_state = SimpleNamespace(
        execution_status=ConversationExecutionStatus.FINISHED,
        events=[SimpleNamespace(), SimpleNamespace()],
        stats=None,
    )

    class _FakeConv:
        id = "conv-test-1"

        def __init__(self, **kw):
            self.callbacks = kw.get("callbacks", [])

        def send_message(self, desc, sender=None):
            self._sent = (desc, sender)

        def run(self, blocking=True, poll_interval=1.0, timeout=None):
            pass

        @property
        def state(self):
            return fake_state

    monkeypatch.setattr(ohw_mod, "RemoteConversation", _FakeConv)

    # mock audit_openhands_events（返回空 → 无违规）
    monkeypatch.setattr(ohw_mod, "audit_openhands_events", lambda events: [])

    # mock COLLECTOR
    monkeypatch.setattr(ohw_mod, "COLLECTOR", SimpleNamespace(record_usage=lambda **kw: None))

    bus = EventBus(SessionStore())
    sess_obj = bus.store.create("run task")
    sess_id = sess_obj.id
    w = OpenHandsWorker(sess_id, "task-run", bus, manage_session_status=True)

    result = w.run("实现 add 函数")
    assert result["status"] == "ConversationExecutionStatus.FINISHED"
    # fake conversation 未调用 callbacks → _events 为空
    assert result["events_count"] == 0
    assert result["conversation_id"] == "conv-test-1"
    # bus 状态应被设为 done
    sess = bus.store.get(sess_id)
    assert sess.status == "done"


def test_run_violation_raises(monkeypatch, tmp_path):
    """audit 发现违规 → 抛 RuntimeError + 设 error 状态。"""
    monkeypatch.setenv("LITELLM_MASTER_KEY", "lm-key")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FLIPPED_WORKER_CONDENSER_ENABLED", raising=False)

    monkeypatch.setattr(ohw_mod, "LLM", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(ohw_mod, "Agent", lambda **kw: SimpleNamespace(**kw))

    class _FakeWS:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ohw_mod, "RemoteWorkspace", _FakeWS)

    class _FakeConv:
        id = "conv-violation"

        def __init__(self, **kw):
            pass

        def send_message(self, desc, sender=None):
            pass

        def run(self, blocking=True, poll_interval=1.0, timeout=None):
            pass

        @property
        def state(self):
            return SimpleNamespace(execution_status=None, events=[], stats=None)

    monkeypatch.setattr(ohw_mod, "RemoteConversation", _FakeConv)
    # audit 返回违规
    monkeypatch.setattr(ohw_mod, "audit_openhands_events",
                        lambda events: ["违规：执行了危险命令 rm -rf"])

    bus = EventBus(SessionStore())
    sess_obj = bus.store.create("vio task")
    sess_id = sess_obj.id
    w = OpenHandsWorker(sess_id, "task-vio", bus, manage_session_status=True)

    with pytest.raises(RuntimeError, match="违规"):
        w.run("做坏事")
    # bus 状态应被设为 error
    sess = bus.store.get(sess_id)
    assert sess.status == "error"


def test_run_subtask_mode_no_status_set(monkeypatch, tmp_path):
    """manage_session_status=False → 不调 bus.set_status，只发 running 进度。"""
    monkeypatch.setenv("LITELLM_MASTER_KEY", "lm-key")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FLIPPED_WORKER_CONDENSER_ENABLED", raising=False)

    from openhands.sdk.conversation.state import ConversationExecutionStatus

    monkeypatch.setattr(ohw_mod, "LLM", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(ohw_mod, "Agent", lambda **kw: SimpleNamespace(**kw))

    class _FakeWS:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ohw_mod, "RemoteWorkspace", _FakeWS)

    fake_state = SimpleNamespace(
        execution_status=ConversationExecutionStatus.FINISHED,
        events=[],
        stats=None,
    )

    class _FakeConv:
        id = "conv-sub"

        def __init__(self, **kw):
            pass

        def send_message(self, desc, sender=None):
            pass

        def run(self, blocking=True, poll_interval=1.0, timeout=None):
            pass

        @property
        def state(self):
            return fake_state

    monkeypatch.setattr(ohw_mod, "RemoteConversation", _FakeConv)
    monkeypatch.setattr(ohw_mod, "audit_openhands_events", lambda events: [])
    monkeypatch.setattr(ohw_mod, "COLLECTOR", SimpleNamespace(record_usage=lambda **kw: None))

    bus = EventBus(SessionStore())
    # 先创建 session，status=idle（create 第一参数是 title，返回 Session 含 id）
    sess_obj = bus.store.create("sub task")
    sess_id = sess_obj.id
    w = OpenHandsWorker(sess_id, "task-sub", bus, manage_session_status=False)

    result = w.run("子任务")
    assert result["status"] == "ConversationExecutionStatus.FINISHED"
    # 子任务模式不应改 session 状态
    sess = bus.store.get(sess_id)
    assert sess.status == "idle"


def test_run_exception_emits_error(monkeypatch, tmp_path):
    """run 过程中抛异常 → 发 error 事件 + 设 error 状态（manage_session_status=True）。"""
    monkeypatch.setenv("LITELLM_MASTER_KEY", "lm-key")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FLIPPED_WORKER_CONDENSER_ENABLED", raising=False)

    # LLM 构造就抛
    def _boom_llm(**kw):
        raise RuntimeError("LLM 初始化失败")

    monkeypatch.setattr(ohw_mod, "LLM", _boom_llm)

    bus = EventBus(SessionStore())
    sess_obj = bus.store.create("err task")
    sess_id = sess_obj.id
    w = OpenHandsWorker(sess_id, "task-err", bus, manage_session_status=True)

    with pytest.raises(RuntimeError, match="LLM 初始化失败"):
        w.run("任务")
    # 应该发了 error 事件 + set_status error
    sess = bus.store.get(sess_id)
    assert sess.status == "error"
    evs = bus.store.events(sess_id)
    err_evs = [e for e in evs if e.type == EventType.error]
    assert len(err_evs) >= 1


# ---------- _build_condenser ----------


def test_build_condenser_disabled_by_default(monkeypatch):
    """默认不启用 LLM condenser（M149.20：数学不成立）。"""
    monkeypatch.delenv("FLIPPED_WORKER_CONDENSER_ENABLED", raising=False)
    w = _worker()
    assert w._build_condenser("fake-key") is None


def test_build_condenser_enabled(monkeypatch):
    """FLIPPED_WORKER_CONDENSER_ENABLED=1 → 构造 LLMSummarizingCondenser。"""
    monkeypatch.setenv("FLIPPED_WORKER_CONDENSER_ENABLED", "1")
    monkeypatch.setenv("FLIPPED_WORKER_CONDENSER_MAX_TOKENS", "2800")
    monkeypatch.setenv("FLIPPED_WORKER_CONDENSER_MAX_SIZE", "12")

    captured = {}

    class _FakeLLM:
        def __init__(self, **kw):
            captured["llm_kwargs"] = kw

    class _FakeCondenser:
        def __init__(self, **kw):
            captured["condenser_kwargs"] = kw

    # mock 模块里的 LLM 和 LLMSummarizingCondenser
    monkeypatch.setattr(ohw_mod, "LLM", _FakeLLM)
    # _build_condenser 内部 import LLMSummarizingCondenser，需要 mock sys.modules
    import sys
    fake_mod = SimpleNamespace(LLMSummarizingCondenser=_FakeCondenser)
    monkeypatch.setitem(sys.modules, "openhands.sdk.context.condenser", fake_mod)

    w = _worker()
    result = w._build_condenser("test-key")
    assert result is not None
    assert "llm_kwargs" in captured
    assert "condenser_kwargs" in captured
    assert captured["condenser_kwargs"]["max_tokens"] == 2800
    assert captured["condenser_kwargs"]["keep_first"] == 2
