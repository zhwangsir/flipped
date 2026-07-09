"""驾驭层 · 多 Agent 监督编排（D15 / M3.6）。

Supervisor(GLM 调度) + Worker(Kimi via cline 执行) + Overseer(GLM 专属监督效率/方向)。
- **Supervisor**：把目标拆成"下一步子任务"（干净结构化任务，**不传全量历史**，避免上下文污染），或判定相信已完成。
- **Worker**：cline headless 执行该子任务，产出可观测轨迹 + 动作签名（复用 observe / sidecar.action_signature）。
- **Overseer**：分层监督——先**确定性预检**(复用动作签名: 同动作重复=低效/卡死)，再 **GLM 方向判断**(产出结构化 verdict)，
  条件路由 continue / replan(回 supervisor) / abort。worker=Kimi、overseer=GLM **跨模型族**避免自偏(D15)。
- **末端强制验证**(复用 sidecar 思路: 跑验收命令判定 done)。checkpointer 支持崩溃恢复/审批中断。

所有 LLM/worker 节点可注入 → 单测确定性、无需真 LLM；默认实现用 GLM/Kimi 经 LiteLLM:4000。
"""
from __future__ import annotations

import os
import uuid
from typing import Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from driving.approval import APPROVE_WORDS, classify_risk
from driving.observe import run_and_observe
from driving.sidecar import action_signature
from metrics import MetricsCallbackHandler
from driving.context_manager import CheckpointRetention, compress_history
from driving.model_router import resolve_model_config, resolve_worker_model_config
from driving.safety import is_safe_command

from executor.openhands_worker import OpenHandsWorker


class NullEventBus:
    """在 LangGraph 同步节点中运行 OpenHands Worker 时，不需要向 WebSocket 广播。"""

    def emit(self, *args, **kwargs):  # noqa: ARG002
        pass

    def set_status(self, *args, **kwargs):  # noqa: ARG002
        pass


def _openhands_signature(events: list) -> str:
    """把 OpenHands 动作事件序列转成 sidecar 循环检测可比的签名。"""
    parts: set[str] = set()
    for event in events:
        if type(event).__name__ != "ActionEvent":
            continue
        tool = getattr(event, "tool_name", None) or "unknown"
        action = getattr(event, "action", None)
        target = ""
        if action is not None:
            for attr in ("path", "command", "file", "url"):
                val = getattr(action, attr, None)
                if val:
                    target = str(val)
                    break
            if not target:
                target = getattr(action, "_summary", "") or action.__class__.__name__
        parts.add(f"{tool}:{target[:80]}")
    return "|".join(sorted(parts))

DEFAULT_LOOP_THRESHOLD = 3


class OrchestratorState(TypedDict, total=False):
    goal: str
    cwd: str
    verify_cmd: list[str]
    project_rules: str
    repo_map: str
    data_dir: str
    max_iterations: int
    loop_threshold: int
    iteration: int
    current_subtask: str
    believe_done: bool
    require_approval: bool
    approval_decision: str   # approved / rejected / auto
    worker_error: bool       # 执行器(cline)报错/上游模型不可用 → 快速失败
    signatures: list[str]
    last_obs: dict
    verdict: dict          # overseer 最近裁决
    feedback: str          # 回灌给 supervisor 的(验收失败/overseer 问题)
    verified: bool
    done: bool
    stop_reason: str       # verified / overseer_abort / loop_detected / circuit_breaker
    history: list[dict]
    context_summary: dict | None
    max_context_tokens: int
    keep_recent: int


# 可注入节点：(state) -> state 增量
SupervisorFn = Callable[[OrchestratorState], dict]
WorkerFn = Callable[[OrchestratorState], dict]
OverseerFn = Callable[[OrchestratorState], dict]
VerifierFn = Callable[[list, str], "tuple[bool, str]"]


# 默认实现（GLM/Kimi 经 LiteLLM） ----------

def _make_llm(alias: str, temperature: float = 0, callbacks=None):
    """构建 ChatOpenAI（alias=architect/coder）。

    运行时根据 `model_router.resolve_model_config` 自动选择 LiteLLM proxy 或直连 exo。
    """
    from langchain_openai import ChatOpenAI

    base, model = resolve_model_config(alias)
    key = os.environ.get("EXO_API_KEY") or os.environ.get("LITELLM_MASTER_KEY", "dummy")
    return ChatOpenAI(model=model, base_url=base, api_key=key, temperature=temperature, timeout=300,
                      callbacks=callbacks)


def _parse_raw_response(raw, schema_cls):
    """从原始 AIMessage 中尽力解析出结构化对象（应对 GLM function calling 偶发异常）。"""
    import json
    import re

    # 1) 优先从 tool_calls 参数里取
    tool_calls = getattr(raw, "tool_calls", None) or []
    for tc in tool_calls:
        if isinstance(tc, dict):
            args = tc.get("function", {}).get("arguments")
            if args is None:
                args = tc.get("args")
        else:
            args = getattr(getattr(tc, "function", None), "arguments", None)
            if args is None:
                args = getattr(tc, "args", None)
        if args:
            try:
                data = json.loads(args) if isinstance(args, str) else dict(args)
                return schema_cls.model_validate(data)
            except Exception:
                pass

    # 2) 从 content 里抠 JSON / 键值对
    text = ""
    content = getattr(raw, "content", None)
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "".join(str(c) for c in content)

    # 2a) JSON object / markdown code block
    candidates = re.findall(r"\{[\s\S]*?\}", text)
    if not candidates:
        # 2b) 键值对：efficiency: 0.8
        pairs = re.findall(r"(\w+)\s*[:=]\s*([^\n,]+)", text)
        if pairs:
            data = {}
            for k, v in pairs:
                v = v.strip().strip('"\'')
                if k in ("efficiency", "direction"):
                    try:
                        v = float(v)
                    except ValueError:
                        continue
                data[k] = v
            return schema_cls.model_validate(data)
    for cand in candidates:
        try:
            return schema_cls.model_validate(json.loads(cand))
        except Exception:
            continue
    return None


def _invoke_structured(llm, schema_cls, prompt: str, *, max_retries: int = 2):
    """带重试 + 原始响应兜底的结构化输出调用。

    GLM-5.2 经 exo 的 function calling 偶尔返回 None / 缺字段 / 空响应，
    重试几次仍失败时，直接从 raw message 解析；再失败才抛异常让调用方 fail-open。
    """
    import json

    structured = llm.with_structured_output(schema_cls, method="function_calling", include_raw=True)
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = structured.invoke(prompt)
            parsed = resp.get("parsed") if isinstance(resp, dict) else getattr(resp, "parsed", None)
            if parsed is not None:
                return parsed
            raw = resp.get("raw") if isinstance(resp, dict) else getattr(resp, "raw", None)
            if raw is not None:
                parsed = _parse_raw_response(raw, schema_cls)
                if parsed is not None:
                    return parsed
            raise ValueError(f"structured output parsed=None, raw={getattr(raw, 'content', raw)!r}")
        except Exception as e:  # noqa: BLE001
            last_err = e
            # 空响应 / 解析失败 值得重试；参数格式错误重试也没用，但先统一重试
            if attempt < max_retries:
                import time as _time
                _time.sleep(0.5 * (attempt + 1))
    raise last_err or RuntimeError("structured output failed after retries")


def _build_supervisor_prompt(state: OrchestratorState) -> str:
    """构建 supervisor 拆解 prompt(含项目规则/反馈/历史摘要)。抽出便于单测。"""
    fb = state.get("feedback", "")
    summary_note = ""
    ctx_summary = state.get("context_summary")
    if ctx_summary:
        summary_note = f"\n历史摘要：{ctx_summary.get('digest', '')}"
    rules = state.get("project_rules", "")
    rules_note = f"\n项目规则(务必遵守项目约定)：\n{rules}\n" if rules else ""
    repo = state.get("repo_map", "")
    repo_note = f"\n项目结构(据此把代码放对位置、别重造已有模块)：\n{repo}\n" if repo else ""
    # 验收失败时，把错误输出注入反馈，并明确禁止“推倒重来”
    fb_prefix = ""
    if fb:
        if "验收命令退出非0" in fb or "监督意见" in fb:
            fb_prefix = (
                "反馈(上一轮失败/监督意见，必须据此做**最小精确修复**，\n"
                "严禁删除已写好的文件或重新创建整个项目；只允许改具体错误行/补缺失文件)：\n"
            )
        else:
            fb_prefix = "反馈(上一轮验收失败/监督意见，必须据此调整)："
    return (f"目标：{state['goal']}\n工作目录：{state['cwd']}\n{repo_note}{rules_note}"
            f"{fb_prefix}{fb if fb else '这是首轮。'}{summary_note}\n"
            "你是架构调度者。给出执行者下一步要做的【一个】自包含子任务；"
            "若相信目标已达成则 believe_done=true。")


def default_supervisor(state: OrchestratorState) -> dict:
    """GLM 调度：据目标 + 项目规则 + 反馈，给出下一步子任务（干净结构化），或相信已完成。"""
    from pydantic import BaseModel, Field

    class Plan(BaseModel):
        believe_done: bool = Field(description="是否相信目标已达成(将由强制验证核对)")
        subtask: str = Field(description="给执行者(coder)的下一步具体子任务，自包含、含必要上下文，勿引用历史")
        rationale: str = Field(description="一句话理由")

    msg = _build_supervisor_prompt(state)
    try:
        # method="function_calling"：GLM/exo 不支持 json_schema(langchain 默认)，但支持工具调用(M0.4)
        plan = _invoke_structured(_make_llm("architect", callbacks=[MetricsCallbackHandler()]), Plan, msg)
        sub, done, why = plan.subtask, plan.believe_done, plan.rationale
    except Exception as e:  # noqa: BLE001 失败兜底：直接把目标当子任务
        sub, done, why = state["goal"], False, f"(supervisor LLM 失败兜底: {e})"
    hist = state.get("history", []) + [{"step": "supervisor", "subtask": sub, "believe_done": done, "why": why}]
    return {"current_subtask": sub, "believe_done": done, "history": hist}


def cline_worker(state: OrchestratorState) -> dict:
    """Kimi via cline 执行当前子任务（干净上下文：只给子任务字符串）。"""
    obs = run_and_observe(state["current_subtask"], state["cwd"],
                          model="coder", data_dir=state.get("data_dir"))
    sig = action_signature(obs.get("records") or [])
    sigs = state.get("signatures", []) + [sig]
    summ = obs.get("summary") or {}
    # cline 退出非0 且一个工具都没调 = 执行器报错(常为上游模型不可用/429) → 快速失败, 别空转熔断
    werr = (not obs.get("ok")) and summ.get("tool_calls", 0) == 0
    hist = state.get("history", []) + [{"step": "worker", "summary": summ, "signature": sig, "error": werr}]
    return {"last_obs": obs, "signatures": sigs, "history": hist, "worker_error": werr}


def make_openhands_worker(bus=None, session_id: str | None = None) -> WorkerFn:
    """构建 OpenHands worker 节点(Kimi via SDK 在 Docker 沙盒执行子任务)。

    Supervisor(GLM) 拆子任务 -> 本 Worker(Kimi) -> Overseer(GLM) 监督;Worker 经
    `model_router` 动态选 LiteLLM proxy 或直连 exo。

    - bus/session_id 给定 → worker 沙盒轨迹事件推到**真实会话**(F2 全程可见);
    - 省略 → NullEventBus(默认,兼容直连编排/测试,不污染会话流)。
    """

    def node(state: OrchestratorState) -> dict:
        sid = session_id or f"orch-{uuid.uuid4().hex[:8]}"
        task_id = f"subtask-{uuid.uuid4().hex[:8]}"
        event_bus = bus if bus is not None else NullEventBus()
        worker_base_url, worker_model_alias = resolve_worker_model_config()
        worker = OpenHandsWorker(
            session_id=sid,
            task_id=task_id,
            bus=event_bus,
            agent_host=os.environ.get("OPENHANDS_AGENT_HOST", "http://localhost:8000"),
            working_dir=state["cwd"],
            model_alias=worker_model_alias,
            base_url=worker_base_url,
            # 子任务模式:不碰会话状态(F8 实测缺陷——曾提前把外层循环的会话覆盖成 done)
            manage_session_status=False,
        )
        try:
            summary = worker.run(state["current_subtask"])
        except Exception as e:  # noqa: BLE001
            err_text = str(e)
            tool_calls = sum(1 for ev in worker.events if type(ev).__name__ == "ActionEvent")
            # F8 大任务实测缺陷:MaxIterationsReached(子任务卡死在调试循环)/安全审计拦截
            # 是**任务性失败**——应回灌 supervisor 换更小方案重拆,而非当基础设施故障判死。
            # 真正的基础设施故障(连不上/模型不可用)特征是一个工具都没调成。
            task_level = ("MaxIterationsReached" in err_text or "blocked" in err_text
                          or tool_calls > 0)
            if task_level:
                return {
                    "last_obs": {"ok": False, "summary": {"tool_calls": tool_calls}, "error": err_text},
                    "signatures": state.get("signatures", []) + [f"stuck:{type(e).__name__}"],
                    "history": state.get("history", []) + [
                        {"step": "worker", "summary": {"tool_calls": tool_calls}, "stuck": True}],
                    "worker_error": False,
                    "feedback": (state.get("feedback", "")
                                 + f"\n[执行器未完成子任务({err_text[:180]})。"
                                   "请拆一个更小、更简单、避开上次卡点的子任务。]").strip(),
                }
            err_sig = f"error:{type(e).__name__}"
            return {
                "last_obs": {"ok": False, "summary": {"tool_calls": 0}, "error": err_text},
                "signatures": state.get("signatures", []) + [err_sig],
                "history": state.get("history", []) + [{"step": "worker", "summary": {"tool_calls": 0}, "error": True}],
                "worker_error": True,
            }

        sig = _openhands_signature(worker.events)
        tool_calls = sum(1 for e in worker.events if type(e).__name__ == "ActionEvent")
        ok = summary.get("status") == "done"
        werr = (not ok) and tool_calls == 0
        hist = state.get("history", []) + [
            {"step": "worker", "summary": {"tool_calls": tool_calls, **summary}, "signature": sig, "error": werr}
        ]
        return {
            "last_obs": {"ok": ok, "summary": {"tool_calls": tool_calls, **summary}},
            "signatures": state.get("signatures", []) + [sig],
            "history": hist,
            "worker_error": werr,
        }

    return node


# 默认 worker 节点(NullEventBus,不推事件)。F2 的可见 worker 由 make_openhands_worker(bus, sid) 构建。
openhands_worker = make_openhands_worker()
default_worker = openhands_worker


def default_overseer(state: OrchestratorState) -> dict:
    """专属监督：确定性预检(效率) + GLM 方向判断 → 结构化 verdict + 路由动作。"""
    sigs = state.get("signatures", [])
    last = sigs[-1] if sigs else None
    repeats = sigs.count(last) if last else 0
    threshold = state.get("loop_threshold", DEFAULT_LOOP_THRESHOLD)

    # 1) 确定性预检：同一动作重复达阈值 = 低效/卡死 → 直接 replan（省一次 LLM）
    if last and repeats >= threshold:
        verdict = {"efficiency": 0.1, "direction": 0.5, "action": "replan",
                   "issues": [f"同一动作签名重复 {repeats} 次(低效/卡死)"],
                   "rationale": "确定性预检命中重复动作"}
        return _overseer_ret(state, verdict)

    # 2) GLM 方向判断（是否偏离目标 / 效率如何）
    from pydantic import BaseModel, Field, field_validator

    class Verdict(BaseModel):
        efficiency: float = Field(description="0-1，worker 这步效率(是否绕路/低产)")
        direction: float = Field(description="0-1，是否朝目标正确方向推进")
        action: Literal["continue", "replan", "abort"] = Field(description="继续/回调度重规划/中止")
        issues: list[str] = Field(default_factory=list, description="发现的问题")
        rationale: str = Field(description="一句话理由")

        @field_validator("issues", mode="before")
        @classmethod
        def _coerce_issues(cls, v):
            """GLM 偶尔把 list[str] 返回为裸字符串 → 统一包成 list。"""
            if isinstance(v, str):
                return [v] if v else []
            return v or []

    summary = (state.get("last_obs") or {}).get("summary", {})
    msg = (f"目标：{state['goal']}\n子任务：{state.get('current_subtask','')}\n"
           f"执行者本步轨迹概览：{summary}\n"
           "你是专属监督者：评估执行者这一步的【效率】(有无绕路/重复/低产)与【方向】(是否朝目标)。"
           "方向明显跑偏→replan；严重无望/危险→abort；正常→continue。")
    try:
        v = _invoke_structured(_make_llm("architect", callbacks=[MetricsCallbackHandler()]), Verdict, msg)
        verdict = {"efficiency": v.efficiency, "direction": v.direction, "action": v.action,
                   "issues": v.issues, "rationale": v.rationale}
    except Exception as e:  # noqa: BLE001 监督失败 fail-open: 不阻塞，交给强制验证兜底
        verdict = {"efficiency": 0.5, "direction": 0.5, "action": "continue",
                   "issues": [], "rationale": f"(overseer LLM 失败 fail-open: {e})"}
    return _overseer_ret(state, verdict)


def _overseer_ret(state: OrchestratorState, verdict: dict) -> dict:
    hist = state.get("history", []) + [{"step": "overseer", "verdict": verdict}]
    upd = {"verdict": verdict, "history": hist}
    if verdict["action"] != "continue":
        upd["feedback"] = f"监督意见: {verdict.get('rationale')} 问题: {verdict.get('issues')}"
    return upd


def _safe_default_verifier(cmd: list, cwd: str) -> "tuple[bool, str]":
    from driving.approval import classify_risk
    command_str = " ".join(cmd)
    ok, reason = is_safe_command(command_str)
    if not ok:
        return False, f"command blocked: {reason}"
    if classify_risk(command_str) == "high":
        return False, "high-risk command requires approval"
    import subprocess
    p = subprocess.run(command_str, shell=True, cwd=cwd, capture_output=True, text=True, timeout=300)
    return p.returncode == 0, (p.stdout + p.stderr)[-2000:]


# ---------- 图 ----------

def build_orchestrator(supervisor: SupervisorFn = default_supervisor,
                       worker: WorkerFn = default_worker,
                       overseer: OverseerFn = default_overseer,
                       verifier: VerifierFn = _safe_default_verifier,
                       checkpointer=None,
                       max_context_tokens: int = 10000,
                       keep_recent: int = 4,
                       summarizer: Callable | None = None):
    """编译 Supervisor→Worker→Overseer→(条件)→Verify 多 agent 监督图。节点可注入。"""

    def verify(state: OrchestratorState) -> dict:
        # Worker 刚 finish 后沙箱可能还在清理 → 短暂等待 + 一次重试
        import time as _time
        ok, output = verifier(state["verify_cmd"], state["cwd"])
        if not ok and not output.strip():
            _time.sleep(3)
            ok, output = verifier(state["verify_cmd"], state["cwd"])
        it = state.get("iteration", 0) + 1
        hist = state.get("history", []) + [{"step": "verify", "ok": ok, "iteration": it}]
        upd = {"iteration": it, "verified": ok, "history": hist}
        if ok:
            upd["done"] = True
            upd["stop_reason"] = "verified"
        else:
            upd["feedback"] = (state.get("feedback", "") + f"\n验收命令退出非0:\n{output}").strip()
        return upd

    def route_overseer(state: OrchestratorState) -> str:
        action = (state.get("verdict") or {}).get("action", "continue")
        if action == "abort":
            return "abort"
        if action == "replan":
            return "replan"
        return "verify"

    def mark_abort(state: OrchestratorState) -> dict:
        return {"done": True, "stop_reason": "overseer_abort"}

    def route_verify(state: OrchestratorState) -> str:
        if state.get("verified"):
            return END
        sigs = state.get("signatures", [])
        last = sigs[-1] if sigs else None
        if last and sigs.count(last) >= state.get("loop_threshold", DEFAULT_LOOP_THRESHOLD):
            return "loop"
        if state.get("iteration", 0) >= state.get("max_iterations", 3):
            return "breaker"
        return "supervisor"

    def mark_loop(state: OrchestratorState) -> dict:
        return {"done": True, "stop_reason": "loop_detected"}

    def mark_breaker(state: OrchestratorState) -> dict:
        return {"done": True, "stop_reason": "circuit_breaker"}

    def compress_node(state: OrchestratorState) -> dict:
        history = state.get("history", [])
        if not history:
            return {}
        result = compress_history(
            history,
            max_tokens=max_context_tokens,
            keep_recent=keep_recent,
            summarizer=summarizer,
        )
        if not result.get("compressed"):
            return {}
        return {"history": result["history"], "context_summary": result.get("summary")}

    g = StateGraph(OrchestratorState)
    g.add_node("supervisor", supervisor)
    g.add_node("worker", worker)
    g.add_node("overseer", overseer)
    g.add_node("verify", verify)
    g.add_node("abort", mark_abort)
    g.add_node("loop", mark_loop)
    g.add_node("breaker", mark_breaker)
    g.add_node("compress", compress_node)
    def approval_gate(state: OrchestratorState) -> dict:
        # 高风险子任务（逸出沙箱/不可逆，§7）在派给 worker 前硬暂停审批；require_approval=False 时直通
        if state.get("require_approval") and classify_risk(state.get("current_subtask", "")) == "high":
            decision = interrupt({"subtask": state.get("current_subtask"),
                                  "reason": "高风险子任务，需人工放行（§7 沙箱外要审批）"})
            if str(decision).strip().lower() in APPROVE_WORDS:
                return {"approval_decision": "approved"}
            return {"approval_decision": "rejected",
                    "feedback": (state.get("feedback", "") + "\n[人工否决了上一子任务，请换方案]").strip()}
        return {"approval_decision": "auto"}

    def _route_sup(state: OrchestratorState) -> str:
        # supervisor 相信已完成 → 直接强制验证（跳过冗余 worker 步）
        return "verify" if state.get("believe_done") else "approval_gate"

    def _route_approval(state: OrchestratorState) -> str:
        # 被否决 → 回 supervisor 重规划；否则 → worker 执行
        return "supervisor" if state.get("approval_decision") == "rejected" else "worker"

    g.add_node("approval_gate", approval_gate)
    g.add_edge(START, "supervisor")
    g.add_edge("compress", "supervisor")
    g.add_conditional_edges("supervisor", _route_sup, {"approval_gate": "approval_gate", "verify": "verify"})
    g.add_conditional_edges("approval_gate", _route_approval, {"supervisor": "compress", "worker": "worker"})
    def mark_worker_error(state: OrchestratorState) -> dict:
        return {"done": True, "stop_reason": "worker_error"}

    def route_worker(state: OrchestratorState) -> str:
        # 执行器报错(上游模型不可用等) → 快速失败，不进 overseer/verify 空转
        return "worker_error" if state.get("worker_error") else "overseer"

    g.add_node("worker_error", mark_worker_error)
    g.add_conditional_edges("worker", route_worker, {"overseer": "overseer", "worker_error": "worker_error"})
    g.add_edge("worker_error", END)
    g.add_conditional_edges("overseer", route_overseer,
                            {"verify": "verify", "replan": "compress", "abort": "abort"})
    g.add_conditional_edges("verify", route_verify,
                            {"supervisor": "compress", "loop": "loop", "breaker": "breaker", END: END})
    g.add_edge("abort", END)
    g.add_edge("loop", END)
    g.add_edge("breaker", END)
    return g.compile(checkpointer=checkpointer)


def drive_orchestrated(goal: str, cwd: str, verify_cmd: list, *,
                       max_iterations: int = 4, loop_threshold: int = DEFAULT_LOOP_THRESHOLD,
                       thread_id: str = "default", db_path: str = ":memory:",
                       data_dir: str | None = None, require_approval: bool = False,
                       project_rules: str = "", repo_map: str = "",
                       max_context_tokens: int = 10000, keep_recent: int = 4,
                       summarizer: Callable | None = None,
                       max_checkpoints: int = 50,
                       supervisor: SupervisorFn = default_supervisor,
                       worker: WorkerFn = default_worker,
                       overseer: OverseerFn = default_overseer,
                       verifier: VerifierFn = _safe_default_verifier) -> OrchestratorState:
    """多 Agent 监督编排驱动一个目标到验收通过 / 监督中止 / 循环 / 熔断。

    require_approval=True：高风险子任务在执行前 interrupt 等人工放行（命中需用 Command(resume=...) 续跑）。
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    initial: OrchestratorState = {
        "goal": goal, "cwd": cwd, "verify_cmd": verify_cmd, "data_dir": data_dir,
        "project_rules": project_rules, "repo_map": repo_map,
        "max_iterations": max_iterations, "loop_threshold": loop_threshold,
        "require_approval": require_approval, "worker_error": False,
        "iteration": 0, "signatures": [], "feedback": "", "verified": False,
        "done": False, "stop_reason": "", "history": [],
        "context_summary": None, "max_context_tokens": max_context_tokens,
        "keep_recent": keep_recent,
    }
    with SqliteSaver.from_conn_string(db_path) as cp:
        graph = build_orchestrator(
            supervisor=supervisor,
            worker=worker,
            overseer=overseer,
            verifier=verifier,
            checkpointer=cp,
            max_context_tokens=max_context_tokens,
            keep_recent=keep_recent,
            summarizer=summarizer,
        )
        result = graph.invoke(initial, config={"configurable": {"thread_id": thread_id}})
        CheckpointRetention(cp, max_checkpoints=max_checkpoints).trim(thread_id)
        return result


def resume_orchestrated(thread_id: str, db_path: str = "data/checkpoints.db", *,
                        supervisor: SupervisorFn = default_supervisor,
                        worker: WorkerFn = default_worker,
                        overseer: OverseerFn = default_overseer,
                        verifier: VerifierFn = _safe_default_verifier,
                        max_context_tokens: int = 10000, keep_recent: int = 4,
                        summarizer: Callable | None = None,
                        max_checkpoints: int = 50) -> OrchestratorState | None:
    """从 LangGraph checkpoint 恢复并继续一次未完成的 orchestrator 运行。

    适用于：orchestration-api 崩溃重启后，扫描到 `status=running` 的会话，
    从持久化的 SqliteSaver 断点续跑。
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(db_path) as cp:
        # 先确认数据库里真的有该 thread 的 checkpoint，避免 LangGraph 把空状态当成新 run
        with cp.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1",
                (str(thread_id),),
            )
            if not cur.fetchone():
                return None

        graph = build_orchestrator(
            supervisor=supervisor,
            worker=worker,
            overseer=overseer,
            verifier=verifier,
            checkpointer=cp,
            max_context_tokens=max_context_tokens,
            keep_recent=keep_recent,
            summarizer=summarizer,
        )
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = graph.get_state(config)
        if snapshot is None:
            return None
        values = snapshot.values
        if values.get("done"):
            return values
        # 若上一 checkpoint 已被 interrupt（如审批断点），不自动恢复，等待外部 Command(resume=...)
        if "__interrupt__" in values:
            return values
        result = graph.invoke(None, config)
        CheckpointRetention(cp, max_checkpoints=max_checkpoints).trim(thread_id)
        return result
