from __future__ import annotations

from agent.supervisor.mcp_client import get_mcp_tool_map
from agent._tool_runner import ainvoke_tool


async def run_reporting_agent(session_id: str) -> dict:
    tool_map = await get_mcp_tool_map()
    tool_calls: list[dict] = []
    report_res, tc = await ainvoke_tool(tool_map, "tool_generate_session_report", {"session_id": session_id})
    tool_calls.append(tc)

    if report_res.get("status") == "success":
        path = (report_res.get("data") or {}).get("report_path")
        output = f"Session report generated: {path}"
    else:
        output = "Report generation failed"

    artifact = {"type": "reporting", "session_id": session_id, "report": report_res.get("data")}
    return {"output": output, "tool_calls": tool_calls, "artifact": artifact}

