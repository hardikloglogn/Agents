from __future__ import annotations

from shared.supervisor_intents import extract_cve, extract_domain
from agent.supervisor.mcp_client import get_mcp_tool_map
from agent._tool_runner import ainvoke_tool


async def run_risk_agent(message: str) -> dict:
    """
    Deterministic Phase-1 risk assessment pipeline:
    CVSS -> EPSS/KEV/exploit -> exposure (ports) -> risk engine.
    """
    cve = extract_cve(message)
    domain = extract_domain(message)

    if not cve:
        return {"output": "Need CVE (e.g., CVE-2021-44228).", "tool_calls": [], "artifact": {"type": "risk"}}
    if not domain:
        return {"output": "Need domain (e.g., example.com).", "tool_calls": [], "artifact": {"type": "risk", "cve": cve}}

    tool_map = await get_mcp_tool_map()
    tool_calls: list[dict] = []

    cvss_res, tc = await ainvoke_tool(tool_map, "tool_get_cvss", {"cve": cve})
    tool_calls.append(tc)
    cvss_val = None
    if cvss_res.get("status") == "success":
        cvss_val = (cvss_res.get("data") or {}).get("cvss")
    try:
        cvss = float(cvss_val) if cvss_val is not None else 5.0
    except Exception:
        cvss = 5.0

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

    port_res, tc = await ainvoke_tool(tool_map, "tool_port_scan", {"host": domain})
    tool_calls.append(tc)
    ports: list[int] = []
    internet_exposed = False
    if port_res.get("status") == "success":
        d = port_res.get("data") or {}
        ports = list(d.get("open_ports") or [])
        # If the scan is flagged unreliable, treat exposure as unknown.
        if d.get("warning"):
            ports = []
        internet_exposed = bool(ports)

    risk_res, tc = await ainvoke_tool(
        tool_map,
        "tool_calculate_risk",
        {
            "cvss": cvss,
            "epss": epss,
            "exploit_available": exploit,
            "in_kev": kev,
            "internet_exposed": internet_exposed,
            "open_ports": ports,
        },
    )
    tool_calls.append(tc)

    risk_data = {}
    if risk_res.get("status") == "success":
        risk_data = risk_res.get("data") or {}
    else:
        # Fallback (deterministic) if risk service is down.
        score = min(10.0, round(cvss, 1))
        risk_data = {
            "overall_score": score,
            "severity": "Critical" if score >= 9 else "High" if score >= 7 else "Medium" if score >= 4 else "Low",
            "recommended_priority": "Patch immediately" if score >= 9 else "Patch ASAP" if score >= 7 else "Patch soon" if score >= 4 else "Monitor / schedule fix",
        }

    severity = str(risk_data.get("severity") or "Unknown").upper()
    score = risk_data.get("overall_score", "?")
    action = risk_data.get("recommended_priority") or "Patch"

    ports_text = ", ".join(str(p) for p in ports) if ports else "(none)"
    output = "\n".join(
        [
            f"Risk: {severity} ({score})",
            "",
            f"CVE: {cve}",
            f"Domain: {domain}",
            "",
            "Reasons:",
            f"- CVSS: {cvss}",
            f"- EPSS: {int(round(epss * 100))}%",
            f"- CISA KEV: {'Yes' if kev else 'No'}",
            f"- Public exploit: {'Available' if exploit else 'Not found'}",
            f"- Internet exposed (ports: {ports_text})" if internet_exposed else "- Internet exposed: No",
            "",
            "Action:",
            f"{action}.",
        ]
    )

    artifact = {
        "type": "risk",
        "cve": cve,
        "domain": domain,
        "cvss": cvss,
        "epss": epss,
        "kev": kev,
        "exploit": exploit,
        "ports": ports,
        "risk_score": risk_data.get("overall_score"),
        "severity": risk_data.get("severity"),
    }
    return {"output": output, "tool_calls": tool_calls, "artifact": artifact}

