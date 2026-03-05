"""
supervisor/supervisor_server.py
PropTech Realty AI Supervisor MCP Server on port 9001.
"""

import asyncio
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nest_asyncio
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from mcp.server.fastmcp import FastMCP

from mcp_servers.listing_server import get_listing_statistics
from supervisor.graph import build_graph, build_trace, serialise_messages
from utils.redis_memory import RedisConversationStore

nest_asyncio.apply()
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [PropSupervisor]  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

mcp = FastMCP(
    "PropTechRealtySupervisor",
    host="127.0.0.1",
    port=9001,
    stateless_http=True,
    json_response=True,
)

GRAPH_TIMEOUT_SECONDS = 45
_GRAPH = None
_GRAPH_LOCK = asyncio.Lock()
_STORE = RedisConversationStore.from_env()


def _decode_messages(raw_msgs: list) -> list:
    out = []
    for m in raw_msgs:
        role = m.get("role", "human")
        content = m.get("content", "")
        if role == "human":
            out.append(HumanMessage(content=content))
        elif role == "ai":
            out.append(AIMessage(content=content, tool_calls=m.get("tool_calls", [])))
        elif role == "tool":
            out.append(
                ToolMessage(
                    content=content,
                    name=m.get("name", "unknown"),
                    tool_call_id=m.get("tool_call_id", ""),
                )
            )
        elif role == "system":
            out.append(SystemMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


def _latest_user_text(raw_msgs: list) -> str:
    for m in reversed(raw_msgs):
        if m.get("role") == "human":
            return str(m.get("content", ""))
    return ""


async def _get_graph():
    global _GRAPH
    if _GRAPH is not None:
        return _GRAPH

    async with _GRAPH_LOCK:
        if _GRAPH is None:
            t0 = time.perf_counter()
            _GRAPH = await build_graph()
            log.info("Graph initialised in %.2fs", time.perf_counter() - t0)
    return _GRAPH


@mcp.tool()
def chat(
    messages_json: str,
    thread_id: str = "",
    user_key: str = "",
    latest_user_input: str = "",
) -> str:
    try:
        raw_msgs: list = json.loads(messages_json)
    except Exception as exc:
        log.error("JSON parse error: %s", exc)
        return json.dumps(
            {
                "error": str(exc),
                "final_reply": "Could not parse your message. Please try again.",
                "trace": [],
            }
        )

    if not isinstance(raw_msgs, list):
        return json.dumps(
            {
                "error": "messages_json must be a JSON array",
                "final_reply": "Invalid message format.",
                "trace": [],
            }
        )

    t0 = time.perf_counter()
    redis_mode = bool(_STORE.enabled and thread_id)
    latest_user_text = (latest_user_input or "").strip() or _latest_user_text(raw_msgs).strip()
    lc_messages = _decode_messages(raw_msgs)
    base_len = len(lc_messages)

    if redis_mode and not latest_user_text:
        return json.dumps(
            {
                "error": "No user message found for Redis-backed chat",
                "final_reply": "Please send a valid message.",
                "trace": [],
                "messages": _STORE.get_messages(thread_id),
                "thread_id": thread_id,
            }
        )

    if redis_mode:
        _STORE.touch_session(thread_id, user_key=user_key)
        cached = _STORE.get_cached_response(thread_id, latest_user_text)
        if cached:
            _STORE.append_turn(thread_id, latest_user_text, cached, user_key=user_key)
            _STORE.compact_if_needed(thread_id)
            return json.dumps(
                {
                    "final_reply": cached,
                    "trace": [
                        {
                            "type": "tool_call",
                            "label": "Cache hit: response served from Redis",
                            "message_index": 1,
                            "message_role": "assistant",
                        }
                    ],
                    "messages": _STORE.get_messages(thread_id),
                    "thread_id": thread_id,
                    "cache_hit": True,
                    "redis_enabled": _STORE.enabled,
                }
            )

        session = _STORE.get_session(thread_id)
        lc_messages = _decode_messages(session.get("messages", []))
        summary = str(session.get("summary", "")).strip()
        if summary:
            lc_messages = [SystemMessage(content=f"Session memory summary:\n{summary}")] + lc_messages
        lc_messages.append(HumanMessage(content=latest_user_text))
        base_len = len(lc_messages)

    try:
        loop = asyncio.get_event_loop()
        graph = loop.run_until_complete(_get_graph())
        result = loop.run_until_complete(
            asyncio.wait_for(
                graph.ainvoke({"messages": lc_messages}, config={"recursion_limit": 20}),
                timeout=GRAPH_TIMEOUT_SECONDS,
            )
        )
    except asyncio.TimeoutError:
        log.error("Graph timeout after %ss", GRAPH_TIMEOUT_SECONDS)
        return json.dumps(
            {
                "error": "graph_timeout",
                "final_reply": (
                    "Timeout: The supervisor took too long to complete this request.\n\n"
                    "Try a narrower prompt, for example:\n"
                    "- 'Show listing stats for Mumbai only'\n"
                    "- 'Show active vs sold listing count'\n\n"
                    "Check logs: logs/supervisor_agent.log"
                ),
                "trace": [{"type": "error", "label": "Supervisor timeout"}],
            }
        )
    except Exception as exc:
        user_text = latest_user_text.lower()
        if (
            "connection error" in str(exc).lower()
            and any(k in user_text for k in ("overall property listing statistics", "listing statistics", "listing dashboard"))
        ):
            stats = get_listing_statistics()
            city_lines = "\n".join([f"- {c['city']}: {c['count']} active" for c in stats.get("top_cities", [])]) or "- No city data"
            fallback_reply = (
                "## Overall Property Listing Statistics\n\n"
                f"- Total listings: **{stats.get('total_listings', 0)}**\n"
                f"- Active: **{stats.get('active', 0)}**\n"
                f"- Sold: **{stats.get('sold', 0)}**\n"
                f"- Under offer: **{stats.get('under_offer', 0)}**\n"
                f"- Average price: **{stats.get('avg_price', '₹0')}**\n"
                f"- Avg days on market: **{stats.get('avg_days_on_market', 0)}**\n"
                f"- Total views: **{stats.get('total_views', 0)}**\n\n"
                "### Top Active Cities\n"
                f"{city_lines}\n\n"
                "_Note: Served from local fallback because model API was unreachable._"
            )
            if redis_mode:
                _STORE.set_cached_response(thread_id, latest_user_text, fallback_reply)
                _STORE.append_turn(thread_id, latest_user_text, fallback_reply, user_key=user_key)
                _STORE.compact_if_needed(thread_id)
            return json.dumps(
                {
                    "final_reply": fallback_reply,
                    "trace": [
                        {"type": "error", "label": "LLM route unavailable"},
                        {"type": "tool_call", "label": "Fallback listing stats", "tool": "get_listing_statistics"},
                    ],
                    "messages": _STORE.get_messages(thread_id) if redis_mode else raw_msgs,
                    "thread_id": thread_id,
                    "redis_enabled": _STORE.enabled,
                }
            )

        log.error("Graph error: %s", exc, exc_info=True)
        return json.dumps(
            {
                "error": str(exc),
                "final_reply": (
                    "System error in supervisor. "
                    "Ensure agents on ports 8001-8007 are running, then retry."
                ),
                "trace": [{"type": "error", "label": f"ERROR {str(exc)[:120]}"}],
            }
        )

    msgs = result.get("messages", [])

    final_reply = None
    for msg in reversed(msgs):
        if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            final_reply = msg.content
            break

    if not final_reply:
        final_reply = (
            "I processed your request but did not produce a final reply. "
            "Please rephrase your query."
        )

    # Only return trace for the current turn so UI trace is separated per message.
    turn_msgs = msgs[max(base_len - 1, 0):]
    trace = build_trace(turn_msgs)
    history = serialise_messages(msgs)

    if redis_mode:
        _STORE.set_cached_response(thread_id, latest_user_text, final_reply)
        _STORE.append_turn(thread_id, latest_user_text, final_reply, user_key=user_key)
        _STORE.compact_if_needed(thread_id)
        history = _STORE.get_messages(thread_id)

    log.info(
        "chat() reply=%d chars trace=%d history=%d elapsed=%.2fs",
        len(final_reply),
        len(trace),
        len(history),
        time.perf_counter() - t0,
    )

    return json.dumps(
        {
            "final_reply": final_reply,
            "trace": trace,
            "messages": history,
            "thread_id": thread_id or "",
            "redis_enabled": _STORE.enabled,
        }
    )


@mcp.tool()
def list_sessions(user_key: str, limit: int = 30) -> str:
    sessions = _STORE.list_sessions(user_key, limit=limit) if _STORE.enabled else []
    return json.dumps(
        {
            "sessions": sessions,
            "redis_enabled": _STORE.enabled,
        }
    )


@mcp.tool()
def get_session(thread_id: str) -> str:
    if not _STORE.enabled:
        return json.dumps({"thread_id": thread_id, "summary": "", "messages": [], "redis_enabled": False})
    session = _STORE.get_session(thread_id)
    return json.dumps(
        {
            "thread_id": thread_id,
            "summary": session.get("summary", ""),
            "messages": session.get("messages", []),
            "redis_enabled": True,
        }
    )


@mcp.tool()
def touch_session(thread_id: str, user_key: str = "") -> str:
    if _STORE.enabled and thread_id:
        _STORE.touch_session(thread_id, user_key=user_key)
    return json.dumps(
        {
            "thread_id": thread_id,
            "redis_enabled": _STORE.enabled,
        }
    )


def main() -> None:
    from database.db import init_db

    init_db()
    log.info(
        "Redis init: enabled=%s url=%s namespace=%s text_limit=%s keep_turns=%s",
        _STORE.enabled,
        os.getenv("REDIS_URL", ""),
        os.getenv("REDIS_NAMESPACE", ""),
        os.getenv("REDIS_TEXT_LIMIT", ""),
        os.getenv("REDIS_SUMMARY_KEEP_TURNS", ""),
    )
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_get_graph())
    except Exception as exc:
        log.error("Graph warmup failed: %s", exc, exc_info=True)

    log.info("PropTech Supervisor -> http://127.0.0.1:9001/mcp")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
