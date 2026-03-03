from __future__ import annotations

from shared.models import RedisSessionStore


async def run_session_analysis_agent(session_id: str) -> dict:
    store = RedisSessionStore()
    artifacts = store.get_session_artifacts(session_id)
    risks = [a for a in artifacts if isinstance(a, dict) and a.get("type") == "risk" and a.get("risk_score") is not None]
    if not risks:
        # Fallback: if the session contains dependency scans, summarize the highest-impact dependency.
        dep_scans = [a for a in artifacts if isinstance(a, dict) and a.get("type") == "dependency_scan" and isinstance(a.get("result"), dict)]
        best = None
        best_score = -1
        best_ids: list[str] = []

        for scan in dep_scans:
            result = scan.get("result") or {}
            for file_res in result.get("results") or []:
                scan_obj = file_res.get("scan") or {}
                scan_data = (scan_obj.get("data") or {}) if isinstance(scan_obj, dict) else {}
                for dep in scan_data.get("dependencies") or []:
                    count = int(dep.get("vulnerability_count") or 0)
                    if count <= 0:
                        continue
                    ids = [v.get("id") for v in (dep.get("vulnerabilities") or []) if isinstance(v, dict) and v.get("id")]
                    if count > best_score:
                        best_score = count
                        best = dep
                        best_ids = ids

        if best is not None:
            output = "\n".join(
                [
                    "Highest Risk Dependency",
                    f"Package: {best.get('name')}",
                    f"Ecosystem: {best.get('ecosystem')}",
                    f"Vulnerabilities: {best_score}",
                    "Advisories: " + (", ".join(best_ids[:8]) if best_ids else "(none listed)"),
                ]
            )
            return {"output": output, "tool_calls": [], "artifact": {"type": "session_analysis", "highest_dependency": best}}

        return {"output": "No risk assessments found in this session.", "tool_calls": [], "artifact": {"type": "session_analysis"}}

    def _score(a: dict) -> float:
        try:
            return float(a.get("risk_score") or 0)
        except Exception:
            return 0.0

    highest = max(risks, key=_score)
    output = "\n".join(
        [
            "Highest Risk Issue",
            f"CVE: {highest.get('cve', '(unknown)')}",
            f"Domain: {highest.get('domain', '(unknown)')}",
            f"Risk: {str(highest.get('severity', '(unknown)')).upper()} ({highest.get('risk_score', '?')})",
        ]
    )
    return {"output": output, "tool_calls": [], "artifact": {"type": "session_analysis", "highest": highest}}
