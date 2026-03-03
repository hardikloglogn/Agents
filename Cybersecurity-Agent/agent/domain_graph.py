from __future__ import annotations

import re

from shared.supervisor_intents import extract_domain
from agent.supervisor.mcp_client import get_mcp_tool_map
from agent._tool_runner import ainvoke_tool


def _is_ip_lookup(message: str) -> bool:
    m = (message or "").lower()
    return any(k in m for k in ("public ip", "ip address", "what is the ip", "resolve ip", "a record"))


async def run_domain_agent(message: str) -> dict:
    domain = extract_domain(message)
    if not domain:
        return {"output": "Need domain (e.g., example.com).", "tool_calls": [], "artifact": {"type": "domain"}}

    tool_map = await get_mcp_tool_map()
    tool_calls: list[dict] = []

    if _is_ip_lookup(message):
        dns_res, tc = await ainvoke_tool(tool_map, "tool_dns_lookup", {"domain": domain})
        tool_calls.append(tc)
        ips = []
        if dns_res.get("status") == "success":
            ips = (dns_res.get("data") or {}).get("ips") or []
        output = "Public IP(s): " + (", ".join(ips) if ips else "(not found)")
        artifact = {"type": "domain", "domain": domain, "ips": ips}
        return {"output": output, "tool_calls": tool_calls, "artifact": artifact}

    dns_res, tc = await ainvoke_tool(tool_map, "tool_dns_lookup", {"domain": domain})
    tool_calls.append(tc)

    whois_res, tc = await ainvoke_tool(tool_map, "tool_whois_lookup", {"domain": domain})
    tool_calls.append(tc)

    port_res, tc = await ainvoke_tool(tool_map, "tool_port_scan", {"host": domain})
    tool_calls.append(tc)

    headers_res, tc = await ainvoke_tool(tool_map, "tool_http_security_headers", {"host": domain})
    tool_calls.append(tc)

    ssl_res, tc = await ainvoke_tool(tool_map, "tool_ssl_info", {"host": domain, "port": 443})
    tool_calls.append(tc)

    # Strict outputs only (no narrative).
    ips = []
    if dns_res.get("status") == "success":
        ips = (dns_res.get("data") or {}).get("ips") or []

    open_ports = []
    port_warning = None
    if port_res.get("status") == "success":
        open_ports = (port_res.get("data") or {}).get("open_ports") or []
        port_warning = (port_res.get("data") or {}).get("warning")
        if port_warning:
            open_ports = []

    missing_headers = []
    if headers_res.get("status") == "success":
        missing_headers = (headers_res.get("data") or {}).get("missing_security_headers") or []

    tls_days = None
    tls_error = None
    if ssl_res.get("status") == "success":
        tls_days = (ssl_res.get("data") or {}).get("days_to_expiry")
    else:
        tls_error = ssl_res.get("error")

    lines = [f"Domain: {domain}"]
    if ips:
        lines.append("Public IP(s): " + ", ".join(ips))
    if port_warning:
        lines.append("Port scan: unreliable")
    elif open_ports:
        lines.append("Open ports: " + ", ".join(str(p) for p in open_ports))
    if missing_headers:
        lines.append("Missing headers: " + ", ".join(missing_headers[:8]) + (" ..." if len(missing_headers) > 8 else ""))
    if tls_days is not None:
        lines.append(f"TLS days to expiry: {tls_days}")
    if tls_error:
        lines.append("TLS check: error")

    artifact = {
        "type": "domain",
        "domain": domain,
        "ips": ips,
        "open_ports": open_ports,
        "port_scan_warning": port_warning,
        "missing_security_headers": missing_headers,
        "tls_days_to_expiry": tls_days,
        "tls_error": tls_error,
    }
    return {"output": "\n".join(lines), "tool_calls": tool_calls, "artifact": artifact}
