from __future__ import annotations

from shared.supervisor_intents import extract_domain
from agent.supervisor.mcp_client import get_mcp_tool_map
from agent._tool_runner import ainvoke_tool


def _wants_ports(message: str) -> bool:
    m = (message or "").lower()
    return any(k in m for k in ("port", "ports", "port scan", "scan ports", "open ports"))


def _wants_whois(message: str) -> bool:
    m = (message or "").lower()
    return "whois" in m


def _wants_dns(message: str) -> bool:
    m = (message or "").lower()
    return any(k in m for k in ("dns", "resolve", "a record", "public ip", "ip address", "what is the ip", "resolve ip"))


async def run_recon_deterministic_agent(message: str) -> dict:
    """
    Deterministic recon pipeline for domain/IP questions.

    Uses MCP tools directly (no LLM), producing strict outputs.
    """
    domain = extract_domain(message)
    if not domain:
        return {"output": "Need domain (e.g., example.com).", "tool_calls": [], "artifact": {"type": "recon"}}

    tool_map = await get_mcp_tool_map()
    tool_calls: list[dict] = []
    lines: list[str] = [f"Target: {domain}"]

    if _wants_dns(message):
        dns_res, tc = await ainvoke_tool(tool_map, "tool_dns_lookup", {"domain": domain})
        tool_calls.append(tc)
        ips = []
        if dns_res.get("status") == "success":
            ips = (dns_res.get("data") or {}).get("ips") or []
        lines.append("Public IP(s): " + (", ".join(ips) if ips else "(not found)"))

    if _wants_whois(message):
        whois_res, tc = await ainvoke_tool(tool_map, "tool_whois_lookup", {"domain": domain})
        tool_calls.append(tc)
        registrar = None
        if whois_res.get("status") == "success":
            registrar = (whois_res.get("data") or {}).get("registrar")
        if registrar:
            lines.append(f"Registrar: {registrar}")

    if _wants_ports(message):
        port_res, tc = await ainvoke_tool(tool_map, "tool_port_scan", {"host": domain})
        tool_calls.append(tc)
        if port_res.get("status") == "success":
            d = port_res.get("data") or {}
            warning = d.get("warning")
            if warning:
                lines.append("Open ports: (unreliable scan)")
            else:
                ports = d.get("open_ports") or []
                lines.append("Open ports: " + (", ".join(str(p) for p in ports) if ports else "(none)"))
        else:
            lines.append("Open ports: (scan failed)")

    # If user asked for generic recon, include headers/TLS too.
    m = (message or "").lower()
    if any(k in m for k in ("recon", "assess", "assessment", "security headers", "tls", "ssl")) and not _wants_ports(message):
        headers_res, tc = await ainvoke_tool(tool_map, "tool_http_security_headers", {"host": domain})
        tool_calls.append(tc)
        if headers_res.get("status") == "success":
            missing = (headers_res.get("data") or {}).get("missing_security_headers") or []
            if missing:
                lines.append("Missing headers: " + ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else ""))

        ssl_res, tc = await ainvoke_tool(tool_map, "tool_ssl_info", {"host": domain, "port": 443})
        tool_calls.append(tc)
        if ssl_res.get("status") == "success":
            days = (ssl_res.get("data") or {}).get("days_to_expiry")
            if days is not None:
                lines.append(f"TLS days to expiry: {days}")

    artifact = {"type": "recon", "domain": domain}
    return {"output": "\n".join(lines), "tool_calls": tool_calls, "artifact": artifact}

