from __future__ import annotations

import re

from agent._tool_runner import ainvoke_tool
from agent.supervisor.mcp_client import get_mcp_tool_map


_GHSA_RE = re.compile(r"\bGHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}\b", re.IGNORECASE)
_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)


def extract_advisory_id(message: str) -> str | None:
    if not message:
        return None
    m = _GHSA_RE.search(message)
    if m:
        raw = m.group(0)
        return "GHSA-" + raw[5:].lower()
    m = _CVE_RE.search(message)
    if m:
        return m.group(0).upper()
    return None


async def run_advisory_agent(message: str) -> dict:
    """
    Deterministic advisory explanation using OSV /v1/vulns/<id>.
    """
    vid = extract_advisory_id(message)
    if not vid:
        return {"output": "Need an advisory ID (GHSA-… or CVE-…).", "tool_calls": [], "artifact": {"type": "advisory"}}

    tool_map = await get_mcp_tool_map()
    tool_calls: list[dict] = []

    adv_res, tc = await ainvoke_tool(tool_map, "tool_get_advisory", {"vuln_id": vid})
    tool_calls.append(tc)

    if adv_res.get("status") != "success":
        return {
            "output": f"Advisory lookup failed: {adv_res.get('error')}",
            "tool_calls": tool_calls,
            "artifact": {"type": "advisory", "id": vid},
        }

    data = adv_res.get("data") or {}
    summary = (data.get("summary") or "").strip()
    aliases = data.get("aliases") or []
    severity = data.get("severity") or []
    affected = data.get("affected") or []

    lines: list[str] = []
    lines.append(f"Advisory: {data.get('id', vid)}")
    if aliases:
        lines.append("Aliases: " + ", ".join(aliases[:8]) + (" ..." if len(aliases) > 8 else ""))
    if summary:
        lines.append("Summary: " + summary)
    if severity:
        # Keep strict: show what OSV provides, no extra mapping.
        parts = []
        for s in severity:
            t = s.get("type")
            sc = s.get("score")
            if t and sc:
                parts.append(f"{t}:{sc}")
        if parts:
            lines.append("Severity: " + ", ".join(parts))

    if affected:
        # Show first few affected packages.
        lines.append("Affected:")
        for a in affected[:5]:
            pkg = (a.get("package") or {})
            eco = pkg.get("ecosystem")
            name = pkg.get("name")
            lines.append(f"- {eco}:{name}")

    # References are helpful but can be long; include a few.
    refs = data.get("references") or []
    if refs:
        urls = [r.get("url") for r in refs if isinstance(r, dict) and r.get("url")]
        if urls:
            lines.append("References:")
            for u in urls[:5]:
                lines.append(f"- {u}")

    artifact = {"type": "advisory", "id": data.get("id", vid), "data": data}
    return {"output": "\n".join(lines), "tool_calls": tool_calls, "artifact": artifact}
