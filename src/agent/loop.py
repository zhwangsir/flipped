"""M1.3 最小 agent loop — LangGraph ReAct agent。

主 Agent = GLM-5.2(LiteLLM 别名 architect)，工具 = web_search。
链路: 本脚本 → LiteLLM(:4000) → exo → GLM-5.2；工具 → SearXNG(:8080)。
前置: LiteLLM 代理在跑(scripts/start_proxy.sh) + SearXNG 在跑。
用法: .venv/bin/python src/agent/loop.py "你的问题"
"""
from __future__ import annotations

import os
import sys
import warnings

# create_react_agent 在 LangGraph V1 已移到 langchain.agents.create_agent；
# M1 暂用旧 API(功能正常)，待 M3 落驾驭层时随 langchain 一并迁移。先静默该弃用告警。
warnings.filterwarnings("ignore", message=r".*create_react_agent has been moved.*")

# 让 tools 包可导入（src 加入 path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 防御性 NO_PROXY（localhost 本就不该走代理；显式设置以防 D5 类劫持）
os.environ.setdefault("NO_PROXY", "100.64.201.37,localhost,127.0.0.1,::1")
os.environ.setdefault("no_proxy", os.environ["NO_PROXY"])

from langchain_core.tools import tool  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402

from tools.web_search import format_for_llm  # noqa: E402
from tools.web_search import search as _search  # noqa: E402

LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000/v1")
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-local")


@tool
def web_search(query: str) -> str:
    """联网搜索实时/外部信息，返回带来源 URL 的结果。需要最新或外部信息时调用。"""
    try:
        return format_for_llm(_search(query, max_results=5))
    except Exception as e:  # noqa: BLE001 — 工具内吞错并回报给 agent，让其决定下一步
        return f"搜索失败: {e}"


def build_agent(model_alias: str = "architect"):
    model = ChatOpenAI(
        model=model_alias,
        base_url=LITELLM_URL,
        api_key=LITELLM_KEY,
        temperature=0,
    )
    return create_react_agent(
        model=model,
        tools=[web_search],
        prompt=(
            "你是架构师主 Agent。当问题涉及实时、最新或外部信息时，"
            "必须调用 web_search 工具获取信息，并在最终答案中用 [n] 标注并列出来源 URL。"
            "不要编造来源。"
        ),
    )


def run_query(question: str, model_alias: str = "architect") -> dict:
    """跑一轮 agent loop，返回 {answer, searched, n_messages}。"""
    agent = build_agent(model_alias)
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    msgs = result["messages"]
    searched = any(
        (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)) == "web_search"
        for m in msgs
        for tc in (getattr(m, "tool_calls", None) or [])
    )
    return {"answer": msgs[-1].content, "searched": searched, "n_messages": len(msgs)}


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "LangGraph 最新稳定版本是多少？给出来源 URL。"
    print(f"问题: {q}\n")
    out = run_query(q)
    print(f"[自主调用 web_search: {out['searched']} | 消息数: {out['n_messages']}]\n")
    print(out["answer"])
