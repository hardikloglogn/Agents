# ui/api.py

import json
import httpx

SUPERVISOR_URL = "http://127.0.0.1:9001/mcp"
HTTP_TIMEOUT   = 120

def _mcp_call(tool_name: str, arguments: dict) -> dict:
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method":  "tools/call",
        "params":  {
            "name": tool_name,
            "arguments": arguments,
        },
    }
    headers = {"Accept": "application/json"}
    try:
        resp = httpx.post(
            SUPERVISOR_URL,
            json=payload,
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("result", {})
        if isinstance(raw, str):
            raw = json.loads(raw)
        content = raw.get("content", []) if isinstance(raw, dict) else []
        if isinstance(content, list) and content:
            inner = content[0].get("text", "{}")
            return json.loads(inner) if isinstance(inner, str) else inner
        if isinstance(raw, dict) and "final_reply" in raw:
            return raw
        return raw if isinstance(raw, dict) else {"result": str(raw)}
    except httpx.ReadTimeout as exc:
        return {
            "final_reply": (
                "?? **Timeout Error** ? The supervisor did not respond in time.\n\n"
                "This usually means the backend is busy or stuck in a long tool/LLM loop.\n"
                "Check `logs/supervisor_agent.log` and restart services:\n"
                "```\npython start_servers.py --stop\npython start_servers.py\n```\n\n"
                f"Error: `{exc}`"
            ),
            "trace": [{"type": "error", "label": "? supervisor request timed out"}],
            "messages": [],
        }
    except httpx.ConnectError as exc:
        return {
            "final_reply": (
                "?? **Connection Error** ? Could not connect to the PropTech Realty supervisor.\n\n"
                "Make sure all servers are running:\n"
                "```\npython start_servers.py\n```\n\n"
                f"Error: `{exc}`"
            ),
            "trace": [{"type": "error", "label": "? supervisor connection failed"}],
            "messages": [],
        }
    except Exception as exc:
        return {
            "final_reply": (
                f"?? **Connection Error** ? Could not reach the PropTech Realty supervisor.\n\n"
                f"Make sure all servers are running:\n```\npython start_servers.py\n```\n\nError: `{exc}`"
            ),
            "trace": [{"type": "error", "label": f"? {str(exc)[:80]}"}],
            "messages": [],
        }

def _call_supervisor(history: list, thread_id: str, user_key: str, latest_user_input: str) -> dict:
    return _mcp_call("chat", {
        "messages_json": json.dumps(history),
        "thread_id": thread_id,
        "user_key": user_key,
        "latest_user_input": latest_user_input,
    })

def _list_sessions(user_key: str) -> tuple[list[str], bool]:
    out = _mcp_call("list_sessions", {"user_key": user_key, "limit": 50})
    return out.get("sessions", []) or [], bool(out.get("redis_enabled", False))

def _load_session(thread_id: str) -> dict:
    return _mcp_call("get_session", {"thread_id": thread_id})

def _touch_session(thread_id: str, user_key: str) -> dict:
    return _mcp_call("touch_session", {"thread_id": thread_id, "user_key": user_key})
