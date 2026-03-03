import json
import logging
import re
import ast
from typing import TypedDict, Annotated, List

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, BaseMessage, AIMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END

from shared.config import settings
from shared.models import RedisSessionStore
from shared.supervisor_intents import detect_intent, extract_cve, extract_domain, extract_github_repo_url
from agent.recon_graph import run_recon_agent
from agent.vulnerability_graph import run_vulnerability_agent
from agent.threat_intel_graph import run_threat_intel_agent
from agent.dependency_graph import run_dependency_agent
from agent.domain_graph import run_domain_agent
from agent.risk_graph import run_risk_agent
from agent.session_graph import run_session_analysis_agent
from agent.reporting_graph import run_reporting_agent
from agent.recon_deterministic_graph import run_recon_deterministic_agent
from agent.advisory_graph import run_advisory_agent
from .mcp_client import get_mcp_tools, get_mcp_tool_map

logger = logging.getLogger("supervisor")


# =========================================================
# State
# =========================================================

class SupervisorState(TypedDict, total=False):
    messages: Annotated[List[BaseMessage], add_messages]
    selected_agent: str
    intent: str
    output: str
    tool_calls: list
    session_id: str
    artifact: dict


def _now_ts() -> int:
    import time

    return int(time.time())


def _as_dict(result) -> dict:
    """
    Normalize LangChain-MCP tool outputs into a dict.

    MCP adapters sometimes return:
    - dict (already structured)
    - list[{"text": "...json..."}]
    - string that is JSON or a Python-literal list containing {"text": "..."}
    """
    if isinstance(result, dict):
        return result

    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict) and "text" in first:
            text = first.get("text")
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except Exception:
                    return {"raw": text}

    if isinstance(result, str):
        s = result.strip()
        if not s:
            return {"raw": ""}
        try:
            return json.loads(s)
        except Exception:
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and "text" in parsed[0]:
                    text = parsed[0].get("text")
                    if isinstance(text, str):
                        try:
                            return json.loads(text)
                        except Exception:
                            return {"raw": text}
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return {"raw": s}

    return {"raw": str(result)}


async def _ainvoke_tool(tool_map: dict, name: str, args: dict) -> tuple[dict, dict]:
    tool = tool_map.get(name)
    if tool is None:
        out = {"status": "error", "data": None, "error": f"Missing tool: {name}"}
        return out, {"tool_name": name, "tool_input": args, "tool_output": json.dumps(out)}
    try:
        logger.info("supervisor_tool_call name=%s args_keys=%s", name, sorted(list(args.keys())))
    except Exception:
        pass
    res = await tool.ainvoke(args)
    out = _as_dict(res)
    try:
        logger.info("supervisor_tool_result name=%s status=%s", name, out.get("status"))
    except Exception:
        pass
    return out, {"tool_name": name, "tool_input": args, "tool_output": json.dumps(out)}


async def _run_threat_only(message: str) -> dict:
    return await run_threat_intel_agent(message)


async def _run_domain_assessment(message: str) -> dict:
    return await run_domain_agent(message)


async def _run_dependency_scan(message: str) -> dict:
    return await run_dependency_agent(message)


# =========================================================
# Nodes
# =========================================================

async def reasoning_node(state: SupervisorState) -> SupervisorState:
    # Get the last human message
    last_message = state["messages"][-1]
    user_message = last_message.content if hasattr(last_message, 'content') else str(last_message)
    match = detect_intent(user_message)
    logger.info("Intent %s", match.intent)
    return {"intent": match.intent, "selected_agent": match.intent}


# ---------------------------------------------------------

async def execute_node(state: SupervisorState) -> SupervisorState:
    intent = state.get("intent", state.get("selected_agent", "direct_answer"))
    # Get the last human message
    last_message = state["messages"][-1]
    message = last_message.content if hasattr(last_message, 'content') else str(last_message)
    session_id = state.get("session_id", "")

    # Load MCP tools once
    recon_tools, vuln_tools = await get_mcp_tools()

    def _looks_like_vuln_query(msg: str) -> bool:
        m = (msg or "").lower()
        return any(k in m for k in ("cve search", "vulnerability", "osv", "pypi", "npm", "maven", "dependency", "@"))

    def _looks_like_recon_query(msg: str) -> bool:
        m = (msg or "").lower()
        if extract_domain(msg):
            return any(
                k in m
                for k in (
                    "public ip",
                    "ip address",
                    "what is the ip",
                    "resolve",
                    "dns",
                    "whois",
                    "scan ports",
                    "port scan",
                )
            )
        return False

    async def _direct_answer() -> dict:
        # Preserve existing vuln agent usefulness without mixing intents.
        if _looks_like_vuln_query(message):
            return await run_vulnerability_agent(state["messages"], vuln_tools)
        if _looks_like_recon_query(message):
            return await run_recon_agent(state["messages"], recon_tools)
        llm = ChatOpenAI(model=settings.OPENAI_MODEL, api_key=settings.OPENAI_API_KEY, temperature=0)
        resp = await llm.ainvoke(state["messages"])
        return {"output": resp.content, "tool_calls": [], "artifact": {"type": "direct_answer"}}

    handlers = {
        "risk_assessment": lambda: run_risk_agent(message),
        "threat_only": lambda: _run_threat_only(message),
        "advisory_explain": lambda: run_advisory_agent(message),
        "session_analysis": lambda: run_session_analysis_agent(session_id),
        "report_generation": lambda: run_reporting_agent(session_id),
        "domain_assessment": lambda: _run_domain_assessment(message),
        "dependency_scan": lambda: _run_dependency_scan(message),
        "recon_only": lambda: run_recon_deterministic_agent(message),
        "direct_answer": _direct_answer,
    }

    handler = handlers.get(intent, _direct_answer)
    result = await handler()

    return {
        "output": result.get("output", ""),
        "tool_calls": result.get("tool_calls", []),
        "artifact": result.get("artifact", {}),
    }


# ---------------------------------------------------------

async def finalize_node(state: SupervisorState) -> SupervisorState:
    output = state.get("output", "").strip()
    if not output:
        output = "Unable to process request."

    # Add AI response to messages
    return {
        "output": output,
        "messages": [AIMessage(content=output)]
    }


# =========================================================
# Graph
# =========================================================

def build_supervisor_graph(checkpointer=None):
    graph = StateGraph(SupervisorState)

    graph.add_node("reasoning", reasoning_node)
    graph.add_node("execute", execute_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "reasoning")
    graph.add_edge("reasoning", "execute")
    graph.add_edge("execute", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)


# =========================================================
# Entry
# =========================================================

async def run_supervisor(user_message: str, session_id: str, graph):
    session_store = RedisSessionStore()

    # Load existing history
    history = session_store.get_session_history(session_id)
    messages = [HumanMessage(content=msg["content"]) if msg["type"] == "human" else AIMessage(content=msg["content"]) for msg in history]

    # Add new human message
    messages.append(HumanMessage(content=user_message))

    # Run graph with messages
    final = await graph.ainvoke({

        "messages": messages,
        "session_id": session_id,
    }, {"configurable": {"thread_id": session_id}})

    # Save updated history
    updated_messages = final.get("messages", messages)
    history_data = [{"type": "human" if isinstance(msg, HumanMessage) else "ai", "content": msg.content} for msg in updated_messages]
    session_store.save_session_history(session_id, history_data)

    # Persist structured artifacts for reporting.
    try:
        artifact = final.get("artifact") or {}
        tool_calls = final.get("tool_calls") or []
        intent = final.get("intent", final.get("selected_agent", ""))

        entry = {"intent": intent, "tool_calls": tool_calls}
        if isinstance(artifact, dict):
            entry.update(artifact)
        if "timestamp" not in entry:
            entry["timestamp"] = _now_ts()
        if "cve" not in entry:
            entry["cve"] = extract_cve(user_message)
        if "domain" not in entry:
            entry["domain"] = extract_domain(user_message)

        session_store.append_session_artifact(session_id, entry)
    except Exception:
        logger.exception("Failed to persist artifacts")

    return {
        "output": final.get("output", ""),
        "agent_used": final.get("intent", final.get("selected_agent", "")),
        "tool_calls": final.get("tool_calls", []),
    }
