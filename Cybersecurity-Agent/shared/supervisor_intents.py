from __future__ import annotations

import re
from dataclasses import dataclass

INTENTS = {
    "risk_assessment",
    "threat_only",
    "advisory_explain",
    "session_analysis",
    "report_generation",
    "domain_assessment",
    "dependency_scan",
    "recon_only",
    "direct_answer",
}

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
_DOMAIN_RE = re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b")


def extract_cve(text: str) -> str | None:
    m = _CVE_RE.search(text or "")
    return m.group(0).upper() if m else None


def extract_domain(text: str) -> str | None:
    if not text:
        return None
    # Prefer URL hostnames.
    m = re.search(r"https?://([^/\s]+)", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip().strip(".,;:()[]{}<>\"'")
    d = _DOMAIN_RE.search(text)
    if d:
        return d.group(0).strip().strip(".,;:()[]{}<>\"'")
    return None


def extract_github_repo_url(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"(https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text)
    return m.group(1) if m else None


def extract_advisory_id(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"\bGHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}\b", text, flags=re.IGNORECASE)
    if m:
        raw = m.group(0)
        # OSV vuln IDs are case-sensitive in the path; normalize GHSA suffix to lowercase.
        # Example: GHSA-4342-x723-ch2f
        return "GHSA-" + raw[5:].lower()
    m = re.search(r"\bCVE-\d{4}-\d{4,7}\b", text, flags=re.IGNORECASE)
    if m:
        return m.group(0).upper()
    return None


@dataclass(frozen=True)
class IntentMatch:
    intent: str
    cve: str | None = None
    domain: str | None = None

    @property
    def repo_url(self) -> str | None:
        # For dependency_scan, we store the repo URL in domain for compatibility.
        return self.domain if self.intent == "dependency_scan" else None


def detect_intent(message: str) -> IntentMatch:
    """
    Deterministic Phase-1 intent detection (SOC-grade, keyword based).
    """
    msg = (message or "").lower()
    cve = extract_cve(message)
    domain = extract_domain(message)

    # report_generation
    if "generate report" in msg:
        return IntentMatch("report_generation", cve=cve, domain=domain)

    # advisory_explain (strictly tool-driven; avoids hallucinated summaries)
    if extract_advisory_id(message) and any(k in msg for k in ("explain", "details", "what is", "tell me about")):
        return IntentMatch("advisory_explain", cve=cve, domain=domain)

    # dependency_scan (include common typos like "dependecy")
    repo = extract_github_repo_url(message)
    if repo and any(
        k in msg
        for k in (
            "dependency",
            "dependencies",
            "dependecy",
            "dependancy",
            "dependncy",
            "deps",
            "sbom",
            "requirements.txt",
            "package.json",
            "scan repo",
            "repo scan",
            "scan depend",
            "audit",
        )
    ):
        return IntentMatch("dependency_scan", cve=None, domain=repo)

    # session_analysis
    if any(
        k in msg
        for k in (
            "which vulnerability",
            "most critical",
            "highest risk",
            "fix first",
            "what should we fix first",
        )
    ):
        return IntentMatch("session_analysis", cve=cve, domain=domain)

    # threat_only (must NOT require domain)
    if any(k in msg for k in ("actively exploited", "exploit available", "is this exploited")):
        return IntentMatch("threat_only", cve=cve, domain=domain)

    # IP lookup for a domain should be deterministic and tool-driven.
    if domain and any(k in msg for k in ("public ip", "ip address", "what is the ip", "resolve ip", "a record")):
        return IntentMatch("domain_assessment", cve=None, domain=domain)

    # risk_assessment
    if any(k in msg for k in ("analyze risk", "risk for cve", "affected by")):
        return IntentMatch("risk_assessment", cve=cve, domain=domain)
    if cve and domain:
        return IntentMatch("risk_assessment", cve=cve, domain=domain)

    # If a user asks "any vulnerabilities for <domain>" but provides no CVE,
    # treat this as recon (exposure discovery) rather than threat/risk scoring.
    if domain and not cve and any(k in msg for k in ("vulnerability", "vulnerable", "vuln", "security issue", "security issues", "any vulnerability")):
        return IntentMatch("domain_assessment", cve=None, domain=domain)

    # recon_only (basic)
    if any(
        k in msg
        for k in (
            "scan ports",
            "port scan",
            "dns",
            "whois",
            "recon",
            "public ip",
            "ip address",
            "what is the ip",
            "resolve ip",
            "resolve",
            "a record",
        )
    ):
        return IntentMatch("recon_only", cve=cve, domain=domain)

    return IntentMatch("direct_answer", cve=cve, domain=domain)
