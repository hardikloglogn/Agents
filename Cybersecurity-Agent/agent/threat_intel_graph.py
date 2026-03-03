from __future__ import annotations

from shared.supervisor_intents import extract_cve
from agent.supervisor.mcp_client import get_mcp_tool_map
from agent._tool_runner import ainvoke_tool


async def run_threat_intel_agent(message: str) -> dict:
    """
    Deterministic threat-only pipeline (no domain required).
    """
    cve = extract_cve(message)
    if not cve:
        return {"output": "Need CVE (e.g., CVE-2021-44228).", "tool_calls": [], "artifact": {"type": "threat"}}

    tool_map = await get_mcp_tool_map()
    tool_calls: list[dict] = []

    epss_res, tc = await ainvoke_tool(tool_map, "tool_get_epss", {"cve": cve})
    tool_calls.append(tc)
    epss = 0.0
    if epss_res.get("status") == "success":
        try:
            epss = float((epss_res.get("data") or {}).get("epss") or 0.0)
        except Exception:
            epss = 0.0

    kev_res, tc = await ainvoke_tool(tool_map, "tool_check_cisa_kev", {"cve": cve})
    tool_calls.append(tc)
    kev = False
    if kev_res.get("status") == "success":
        kev = bool((kev_res.get("data") or {}).get("in_kev"))

    exploit_res, tc = await ainvoke_tool(tool_map, "tool_check_exploit_available", {"cve": cve})
    tool_calls.append(tc)
    exploit = False
    if exploit_res.get("status") == "success":
        exploit = bool((exploit_res.get("data") or {}).get("exploit_available"))

    threat_status = "LOW"
    if kev or exploit or epss >= 0.7:
        threat_status = "HIGH"
    elif epss >= 0.3:
        threat_status = "MEDIUM"

    output = "\n".join(
        [
            f"Threat Status: {threat_status}",
            f"CVE: {cve}",
            f"EPSS: {int(round(epss * 100))}%",
            f"CISA KEV: {'Yes' if kev else 'No'}",
            f"Public exploit: {'Available' if exploit else 'Not found'}",
        ]
    )

    artifact = {"type": "threat", "cve": cve, "epss": epss, "kev": kev, "exploit": exploit}
    return {"output": output, "tool_calls": tool_calls, "artifact": artifact}

