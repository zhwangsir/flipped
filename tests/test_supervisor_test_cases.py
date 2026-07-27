"""M157.11 · 测试设计独立阶段 TDD 单测。

对标 Trae-Agent 第 2.1 节：Supervisor 输出强制加 test_cases 字段，
覆盖 normal/boundary/error/concurrency 四类（Karpathy 风格）。

验证：
- Plan schema 含 test_cases 字段（向后兼容，默认 []）
- supervisor prompt 要求四类测试覆盖
- default_supervisor 把 plan.test_cases 传到 state（mock LLM）
- test_cases 字符串容忍（GLM 偶发返回裸字符串 → 包成 list）
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from driving.orchestrator import (  # noqa: E402
    Plan,
    _build_supervisor_prompt,
    default_supervisor,
)


# ---------- Plan schema: test_cases 字段 ----------


def test_plan_schema_has_test_cases_field():
    """Plan 必须含 test_cases 字段。"""
    fields = Plan.model_fields
    assert "test_cases" in fields, "Plan schema 必须含 test_cases 字段"


def test_plan_schema_test_cases_defaults_empty_list():
    """test_cases 默认空 list（向后兼容：老路径不传时不报错）。"""
    plan = Plan(believe_done=False, subtask="s", rationale="r")
    assert plan.test_cases == [], "test_cases 默认应为空 list"


def test_plan_schema_accepts_test_cases_list():
    """Plan 接受 test_cases list[str]。"""
    plan = Plan(believe_done=False, subtask="s", rationale="r",
                test_cases=[
                    "pytest tests/test_x.py::test_normal",
                    "pytest tests/test_x.py::test_boundary_empty",
                    "pytest tests/test_x.py::test_error_handling",
                    "pytest tests/test_x.py::test_concurrency_race",
                ])
    assert len(plan.test_cases) == 4
    assert "pytest tests/test_x.py::test_normal" in plan.test_cases


def test_plan_schema_coerces_string_to_list():
    """GLM 偶发把 list[str] 返回为裸字符串 → 应被包成 list[str]。

    这是 _coerce_schema / field_validator 的职责，验证不破。
    """
    # 裸字符串应被 field_validator 包成单元素 list
    plan = Plan(believe_done=False, subtask="s", rationale="r",
                test_cases="pytest tests/test_x.py::test_normal")
    # field_validator 应把字符串包成 list
    assert isinstance(plan.test_cases, list)
    assert len(plan.test_cases) >= 1


# ---------- supervisor prompt: 四类测试覆盖要求 ----------


def test_supervisor_prompt_requires_four_test_categories():
    """supervisor prompt 必须明确要求四类测试覆盖：normal/boundary/error/concurrency。"""
    state = {"goal": "g", "cwd": "/tmp", "repo_map": "", "project_rules": "",
             "feedback": "", "context_summary": None}
    prompt = _build_supervisor_prompt(state)
    assert "test_cases" in prompt, "prompt 必须提及 test_cases 字段"
    assert "normal" in prompt.lower(), "prompt 必须要求 normal 类测试"
    assert "boundary" in prompt.lower(), "prompt 必须要求 boundary 类测试"
    assert "error" in prompt.lower(), "prompt 必须要求 error 类测试"
    assert "concurrency" in prompt.lower(), "prompt 必须要求 concurrency 类测试"


def test_supervisor_prompt_mentions_test_design_phase():
    """prompt 应明确'测试设计独立阶段'理念（先于开发）。"""
    state = {"goal": "g", "cwd": "/tmp", "repo_map": "", "project_rules": "",
             "feedback": "", "context_summary": None}
    prompt = _build_supervisor_prompt(state)
    # 必须提到测试设计是硬性要求（不是可选）
    assert "测试设计" in prompt or "测试用例" in prompt


# ---------- default_supervisor: 传递 test_cases 到 state ----------


class _FakeStructuredLLM:
    """假 LLM：with_structured_output 返回预设 Plan（绕过真 GLM）。"""

    def __init__(self, plan: Plan):
        self._plan = plan

    def with_structured_output(self, schema_cls, method, include_raw):
        outer = self

        class _Inner:
            def invoke(self, prompt):
                return {"parsed": outer._plan, "raw": None}

        return _Inner()


def test_default_supervisor_passes_test_cases_to_state(monkeypatch):
    """default_supervisor 应把 plan.test_cases 传到 state 增量。"""
    expected_tc = [
        "pytest tests/test_x.py::test_normal",
        "pytest tests/test_x.py::test_boundary_empty",
        "pytest tests/test_x.py::test_error_handling",
        "pytest tests/test_x.py::test_concurrency_race",
    ]
    plan = Plan(believe_done=False, subtask="写 foo.py", rationale="需要 foo",
                test_cases=expected_tc)
    fake_llm = _FakeStructuredLLM(plan)

    # 默认走 _direct_glm_tool_call（绕过 langchain）→ mock 它返回 plan
    monkeypatch.setattr("driving.orchestrator._direct_glm_tool_call",
                        lambda llm, schema_cls, prompt, **kw: plan)
    # 同时 mock _make_llm 避免真连 LiteLLM
    monkeypatch.setattr("driving.orchestrator._make_llm",
                        lambda alias, callbacks=None, **kw: fake_llm)

    state = {"goal": "实现 foo 函数", "cwd": "/tmp", "repo_map": "", "project_rules": "",
             "feedback": "", "context_summary": None, "history": []}
    upd = default_supervisor(state)
    assert upd.get("test_cases") == expected_tc, \
        f"default_supervisor 应把 plan.test_cases 传到 state, 实: {upd.get('test_cases')}"


def test_default_supervisor_empty_test_cases_on_llm_failure(monkeypatch):
    """LLM 失败兜底时 test_cases 应为空 list（不崩，向后兼容）。"""
    # _direct_glm_tool_call 抛异常 → default_supervisor 走 except 兜底
    def _boom(*a, **kw):
        raise RuntimeError("GLM 不可达")

    monkeypatch.setattr("driving.orchestrator._direct_glm_tool_call", _boom)
    monkeypatch.setattr("driving.orchestrator._make_llm",
                        lambda alias, callbacks=None, **kw: None)

    state = {"goal": "g", "cwd": "/tmp", "repo_map": "", "project_rules": "",
             "feedback": "", "context_summary": None, "history": []}
    upd = default_supervisor(state)
    assert upd.get("test_cases") == [], "LLM 失败兜底时 test_cases 应为空 list"
    assert "兜底" in upd.get("history", [])[-1].get("why", "") or "失败" in upd.get("history", [])[-1].get("why", "")


def test_default_supervisor_test_cases_with_ide_action(monkeypatch):
    """supervisor 选 ide_action 路径时 test_cases 也应正确传递（三态互斥不影响 test_cases）。"""
    from driving.orchestrator import IdeActionSpec
    expected_tc = ["pytest tests/test_x.py::test_normal"]
    plan = Plan(believe_done=False, subtask="", rationale="读 IDE 设置",
                ide_action=IdeActionSpec(name="ide.getSetting", args={"section": "x"}),
                test_cases=expected_tc)
    monkeypatch.setattr("driving.orchestrator._direct_glm_tool_call",
                        lambda llm, schema_cls, prompt, **kw: plan)
    monkeypatch.setattr("driving.orchestrator._make_llm",
                        lambda alias, callbacks=None, **kw: None)

    state = {"goal": "g", "cwd": "/tmp", "repo_map": "", "project_rules": "",
             "feedback": "", "context_summary": None, "history": []}
    upd = default_supervisor(state)
    assert upd.get("test_cases") == expected_tc
    assert upd.get("ide_action") is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
