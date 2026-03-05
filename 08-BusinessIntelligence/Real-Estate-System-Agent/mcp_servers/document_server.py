"""mcp_servers/document_server.py — Document & Legal Agent (port 8006 · 8 tools)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2.extras
from mcp.server.fastmcp import FastMCP
from database.db import get_connection, init_db
from utils.email_service import send_document_request, send_contract_email

mcp = FastMCP("DocumentServer", host="127.0.0.1", port=8006, stateless_http=True, json_response=True)


def _cur(conn): return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

REQUIRED_DOCS = [
    "Purchase Agreement", "Identity Proof (Aadhar/Passport)",
    "Address Proof", "Proof of Funds / Bank Statement",
    "Property Title Deed", "Sale Deed", "Encumbrance Certificate",
    "NOC from Builder/Society", "Property Tax Receipts",
]

KYC_DOCS = ["Identity Proof (Aadhar/Passport)", "Address Proof", "Proof of Funds / Bank Statement"]


@mcp.tool()
def create_contract(deal_id: int, listing_id: str, contract_type: str,
                    buyer_email: str, seller_email: str,
                    agent_email: str = "") -> dict:
    """Generate a purchase agreement / contract record for an accepted offer."""
    conn = get_connection(); cur = _cur(conn)
    # Create doc record
    cur.execute("""
        INSERT INTO documents (deal_id,listing_id,doc_type,status,requested_from,sent_to)
        VALUES (%s,%s,%s,'draft',%s,%s) RETURNING id
    """, (deal_id, listing_id, contract_type, buyer_email, f"{buyer_email},{seller_email}"))
    doc_id = cur.fetchone()["id"]
    cur.execute("SELECT address,city FROM properties WHERE listing_id=%s", (listing_id,))
    prop = cur.fetchone(); conn.commit(); conn.close()
    address = f"{prop['address']}, {prop['city']}" if prop else listing_id
    send_contract_email(f"{buyer_email},{seller_email}", "All Parties", contract_type, address)
    return {"success": True, "document_id": doc_id, "contract_type": contract_type,
            "listing_id": listing_id, "deal_id": deal_id, "status": "draft",
            "parties": [buyer_email, seller_email],
            "message": f"✅ Contract '{contract_type}' created (Doc #{doc_id}). Emailed to buyer and seller."}


@mcp.tool()
def update_document_status(doc_id: int, new_status: str, notes: str = "") -> dict:
    """Update document status: draft, sent, signed, expired, rejected."""
    valid = {"draft","sent","signed","expired","rejected","received","pending"}
    if new_status not in valid:
        return {"success": False, "message": f"Invalid status. Choose: {', '.join(valid)}"}
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        UPDATE documents SET status=%s, notes=%s, updated_at=NOW()
        WHERE id=%s RETURNING doc_type, listing_id
    """, (new_status, notes, doc_id))
    row = cur.fetchone()
    if not row: conn.close(); return {"success": False, "message": f"Document #{doc_id} not found."}
    conn.commit(); conn.close()
    return {"success": True, "document_id": doc_id, "doc_type": row["doc_type"],
            "new_status": new_status,
            "message": f"✅ Document #{doc_id} ({row['doc_type']}) → '{new_status}'."}


@mcp.tool()
def get_document_checklist(listing_id: str) -> dict:
    """All required documents for a transaction with completion status."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT id,doc_type,status,updated_at FROM documents WHERE listing_id=%s ORDER BY created_at", (listing_id,))
    existing = {r["doc_type"]: {"id": r["id"], "status": r["status"],
                                  "updated_at": str(r["updated_at"])[:16] if r["updated_at"] else None}
                for r in cur.fetchall()}
    conn.close()
    checklist = []
    for doc in REQUIRED_DOCS:
        e = existing.get(doc)
        checklist.append({
            "document": doc,
            "status": e["status"] if e else "not_started",
            "doc_id": e["id"] if e else None,
            "updated_at": e["updated_at"] if e else None,
            "completed": e["status"] == "signed" if e else False,
        })
    completed = sum(1 for c in checklist if c["completed"])
    return {"listing_id": listing_id,
            "total_documents": len(REQUIRED_DOCS),
            "completed": completed,
            "pending": len(REQUIRED_DOCS) - completed,
            "completion_pct": round(completed / len(REQUIRED_DOCS) * 100, 1),
            "checklist": checklist}


@mcp.tool()
def request_document(listing_id: str, doc_type: str, from_email: str,
                      agent_name: str = "Your Agent") -> dict:
    """Send an email requesting a specific document from a client."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT address, city FROM properties WHERE listing_id=%s", (listing_id,))
    prop = cur.fetchone()
    address = f"{prop['address']}, {prop['city']}" if prop else listing_id
    # Create/update document record
    cur.execute("""
        INSERT INTO documents (listing_id,doc_type,status,requested_from,sent_to)
        VALUES (%s,%s,'pending',%s,%s)
        ON CONFLICT DO NOTHING RETURNING id
    """, (listing_id, doc_type, from_email, from_email))
    conn.commit(); conn.close()
    result = send_document_request(from_email, agent_name, doc_type, address)
    return {"success": result["success"], "listing_id": listing_id,
            "doc_type": doc_type, "requested_from": from_email,
            "message": result["message"]}


@mcp.tool()
def get_transaction_documents(listing_id: str = "", deal_id: int = 0) -> list:
    """All documents associated with a deal/transaction."""
    conn = get_connection(); cur = _cur(conn)
    q = "SELECT * FROM documents WHERE 1=1"
    p = []
    if listing_id: q += " AND listing_id=%s"; p.append(listing_id)
    if deal_id: q += " AND deal_id=%s"; p.append(deal_id)
    q += " ORDER BY created_at DESC"
    cur.execute(q, p); rows = cur.fetchall(); conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["created_at"] = str(d["created_at"])[:16]
        d["updated_at"] = str(d["updated_at"])[:16] if d["updated_at"] else None
        result.append(d)
    return result or [{"message": "No documents found."}]


@mcp.tool()
def verify_kyc(client_email: str) -> dict:
    """Check KYC completion status for a client — ID, proof of funds, address."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT name FROM clients WHERE email=%s", (client_email,))
    client = cur.fetchone()
    # Check by email in documents requested_from
    cur.execute("SELECT doc_type, status FROM documents WHERE requested_from=%s", (client_email,))
    docs = {r["doc_type"]: r["status"] for r in cur.fetchall()}; conn.close()
    kyc_status = []
    for doc in KYC_DOCS:
        status = docs.get(doc, "not_submitted")
        kyc_status.append({
            "document": doc,
            "status": status,
            "verified": status == "signed",
        })
    verified = sum(1 for k in kyc_status if k["verified"])
    kyc_complete = verified == len(KYC_DOCS)
    return {
        "client_email": client_email,
        "client_name": client["name"] if client else "Unknown",
        "kyc_complete": kyc_complete,
        "verified_count": verified,
        "total_required": len(KYC_DOCS),
        "kyc_documents": kyc_status,
        "status": "✅ KYC Complete" if kyc_complete else f"⚠️ KYC Incomplete — {len(KYC_DOCS)-verified} document(s) pending",
    }


@mcp.tool()
def send_contract_email_tool(listing_id: str, contract_type: str,
                              to_emails: str, party_name: str = "All Parties") -> dict:
    """Email a contract or document to relevant parties."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT address, city FROM properties WHERE listing_id=%s", (listing_id,))
    prop = cur.fetchone(); conn.close()
    address = f"{prop['address']}, {prop['city']}" if prop else listing_id
    result = send_contract_email(to_emails, party_name, contract_type, address)
    return {"success": result["success"], "listing_id": listing_id,
            "sent_to": to_emails, "message": result["message"]}


@mcp.tool()
def get_compliance_status(listing_id: str) -> dict:
    """Full compliance audit for a transaction — which documents are pending."""
    checklist = get_document_checklist(listing_id)
    pending = [c for c in checklist.get("checklist", []) if not c["completed"]]
    signed  = [c for c in checklist.get("checklist", []) if c["completed"]]
    risk = "🔴 High Risk" if len(pending) > 6 else "🟡 Medium Risk" if len(pending) > 2 else "🟢 Low Risk"
    return {
        "listing_id": listing_id,
        "compliance_score": checklist.get("completion_pct", 0),
        "risk_level": risk,
        "signed_documents": [c["document"] for c in signed],
        "pending_documents": [c["document"] for c in pending],
        "recommendation": ("Transaction can proceed" if len(pending) <= 2
                           else f"Resolve {len(pending)} pending documents before closing"),
    }


def main():
    init_db(); mcp.run(transport="streamable-http")

if __name__ == "__main__":
    main()
