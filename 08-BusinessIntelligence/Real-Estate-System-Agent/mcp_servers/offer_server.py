"""mcp_servers/offer_server.py — Offer & Deal Agent (port 8005 · 8 tools)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2.extras
from mcp.server.fastmcp import FastMCP
from database.db import get_connection, init_db
from utils.email_service import send_offer_status_email

mcp = FastMCP("OfferServer", host="127.0.0.1", port=8005, stateless_http=True, json_response=True)


def _cur(conn): return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
def _fmt(p) -> str:
    try: v=float(p); return f"₹{v/10_000_000:.2f}Cr" if v>=10_000_000 else f"₹{v/100_000:.1f}L"
    except: return str(p)


@mcp.tool()
def submit_offer(listing_id: str, buyer_email: str, offer_amount: float,
                 validity_days: int = 7, conditions: str = "") -> dict:
    """Submit a purchase offer on a property."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT address, city, agent_email FROM properties WHERE listing_id=%s", (listing_id,))
    prop = cur.fetchone()
    if not prop: conn.close(); return {"success": False, "message": f"Listing {listing_id} not found."}
    cur.execute("""
        INSERT INTO offers (listing_id,buyer_email,offer_amount,conditions,validity_date,status)
        VALUES (%s,%s,%s,%s,CURRENT_DATE + %s,'pending') RETURNING id, validity_date
    """, (listing_id, buyer_email, offer_amount, conditions or "None", validity_days))
    row = cur.fetchone()
    cur.execute("UPDATE properties SET status='under_offer' WHERE listing_id=%s AND status='active'", (listing_id,))
    conn.commit(); conn.close()
    address = f"{prop['address']}, {prop['city']}"
    send_offer_status_email(buyer_email, prop["agent_email"], buyer_email.split("@")[0].title(),
                             address, offer_amount, "pending")
    return {"success": True, "offer_id": row["id"], "listing_id": listing_id,
            "buyer_email": buyer_email, "offer_amount": _fmt(offer_amount),
            "validity_date": str(row["validity_date"]),
            "message": f"✅ Offer #{row['id']} submitted: {_fmt(offer_amount)} on {listing_id}. Valid until {row['validity_date']}."}


@mcp.tool()
def update_offer_status(offer_id: int, new_status: str, notes: str = "") -> dict:
    """Update offer status: accepted, rejected, countered, withdrawn, expired."""
    valid = {"accepted","rejected","countered","withdrawn","expired"}
    if new_status not in valid:
        return {"success": False, "message": f"Invalid status. Choose: {', '.join(valid)}"}
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        UPDATE offers SET status=%s, resolved_at=NOW()
        WHERE id=%s RETURNING listing_id, buyer_email, offer_amount, countered_amount
    """, (new_status, offer_id))
    row = cur.fetchone()
    if not row: conn.close(); return {"success": False, "message": f"Offer #{offer_id} not found."}
    cur.execute("SELECT address, city, agent_email FROM properties WHERE listing_id=%s", (row["listing_id"],))
    prop = cur.fetchone()
    # Revert listing status if rejected/withdrawn
    if new_status in ("rejected","withdrawn"):
        cur.execute("UPDATE properties SET status='active' WHERE listing_id=%s AND status='under_offer'", (row["listing_id"],))
    conn.commit(); conn.close()
    address = f"{prop['address']}, {prop['city']}" if prop else row["listing_id"]
    send_offer_status_email(row["buyer_email"], prop["agent_email"] if prop else "",
                             row["buyer_email"].split("@")[0].title(),
                             address, row["offer_amount"], new_status, row["countered_amount"])
    return {"success": True, "offer_id": offer_id, "new_status": new_status,
            "message": f"✅ Offer #{offer_id} status → '{new_status}'."}


@mcp.tool()
def make_counteroffer(offer_id: int, counter_amount: float, counter_conditions: str = "") -> dict:
    """Record a seller's counteroffer."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        UPDATE offers SET status='countered', countered_amount=%s, counter_conditions=%s
        WHERE id=%s AND status='pending'
        RETURNING listing_id, buyer_email, offer_amount
    """, (counter_amount, counter_conditions, offer_id))
    row = cur.fetchone()
    if not row: conn.close(); return {"success": False, "message": f"Offer #{offer_id} not found or not in pending state."}
    cur.execute("SELECT address, city, agent_email FROM properties WHERE listing_id=%s", (row["listing_id"],))
    prop = cur.fetchone(); conn.commit(); conn.close()
    address = f"{prop['address']}, {prop['city']}" if prop else row["listing_id"]
    send_offer_status_email(row["buyer_email"], prop["agent_email"] if prop else "",
                             row["buyer_email"].split("@")[0].title(),
                             address, row["offer_amount"], "countered", counter_amount)
    return {"success": True, "offer_id": offer_id,
            "original_offer": _fmt(row["offer_amount"]),
            "counter_offer": _fmt(counter_amount),
            "message": f"✅ Counteroffer of {_fmt(counter_amount)} sent to buyer (original: {_fmt(row['offer_amount'])})."}


@mcp.tool()
def get_offer_history(listing_id: str) -> dict:
    """Full offer history for a property."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT address, city, price FROM properties WHERE listing_id=%s", (listing_id,))
    prop = cur.fetchone()
    cur.execute("""
        SELECT id, buyer_email, offer_amount, conditions, validity_date,
               status, countered_amount, submitted_at, resolved_at
        FROM offers WHERE listing_id=%s ORDER BY submitted_at DESC
    """, (listing_id,))
    rows = cur.fetchall(); conn.close()
    offers = []
    for r in rows:
        d = dict(r)
        d["offer_formatted"] = _fmt(d["offer_amount"])
        d["counter_formatted"] = _fmt(d["countered_amount"]) if d["countered_amount"] else None
        d["submitted_at"] = str(d["submitted_at"])[:16]
        d["resolved_at"] = str(d["resolved_at"])[:16] if d["resolved_at"] else None
        d["validity_date"] = str(d["validity_date"])
        offers.append(d)
    return {"listing_id": listing_id,
            "asking_price": _fmt(prop["price"]) if prop else "—",
            "address": prop["address"] if prop else "—",
            "total_offers": len(offers), "offers": offers}


@mcp.tool()
def get_deal_pipeline() -> list:
    """Overview of all active deals: stage, parties, amount, expected close."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        SELECT d.id, d.listing_id, d.buyer_email, d.seller_email, d.agreed_price,
               d.stage, d.expected_close, d.agent_email, d.created_at, p.address, p.city
        FROM deals d LEFT JOIN properties p ON p.listing_id=d.listing_id
        WHERE d.stage NOT IN ('completed','fallen_through')
        ORDER BY d.created_at DESC
    """)
    rows = cur.fetchall(); conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["agreed_price_formatted"] = _fmt(d["agreed_price"])
        d["created_at"] = str(d["created_at"])[:16]
        d["expected_close"] = str(d["expected_close"]) if d["expected_close"] else "TBD"
        result.append(d)
    return result or [{"message": "No active deals in pipeline."}]


@mcp.tool()
def accept_offer(offer_id: int, agent_email: str = "") -> dict:
    """Accept an offer, create a deal record, email all parties."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT * FROM offers WHERE id=%s", (offer_id,))
    offer = cur.fetchone()
    if not offer: conn.close(); return {"success": False, "message": f"Offer #{offer_id} not found."}
    cur.execute("UPDATE offers SET status='accepted', resolved_at=NOW() WHERE id=%s", (offer_id,))
    cur.execute("UPDATE properties SET status='under_offer' WHERE listing_id=%s", (offer["listing_id"],))
    # Create deal record
    cur.execute("""
        INSERT INTO deals (listing_id,buyer_email,agreed_price,stage,agent_email)
        VALUES (%s,%s,%s,'offer_accepted',%s) RETURNING id
    """, (offer["listing_id"], offer["buyer_email"], offer["offer_amount"], agent_email))
    deal_id = cur.fetchone()["id"]
    cur.execute("SELECT address, city, agent_email FROM properties WHERE listing_id=%s", (offer["listing_id"],))
    prop = cur.fetchone(); conn.commit(); conn.close()
    address = f"{prop['address']}, {prop['city']}" if prop else offer["listing_id"]
    seller_email = prop["agent_email"] if prop else ""
    send_offer_status_email(offer["buyer_email"], seller_email,
                             offer["buyer_email"].split("@")[0].title(),
                             address, offer["offer_amount"], "accepted")
    return {"success": True, "offer_id": offer_id, "deal_id": deal_id,
            "agreed_price": _fmt(offer["offer_amount"]),
            "message": f"✅ Offer #{offer_id} ACCEPTED. Deal #{deal_id} created. All parties notified."}


@mcp.tool()
def send_offer_status_email_tool(offer_id: int) -> dict:
    """Resend offer status update email to buyer and seller."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT * FROM offers WHERE id=%s", (offer_id,))
    offer = cur.fetchone()
    if not offer: conn.close(); return {"success": False, "message": f"Offer {offer_id} not found."}
    cur.execute("SELECT address, city, agent_email FROM properties WHERE listing_id=%s", (offer["listing_id"],))
    prop = cur.fetchone(); conn.close()
    address = f"{prop['address']}, {prop['city']}" if prop else offer["listing_id"]
    result = send_offer_status_email(offer["buyer_email"], prop["agent_email"] if prop else "",
                                      offer["buyer_email"].split("@")[0].title(),
                                      address, offer["offer_amount"], offer["status"],
                                      offer["countered_amount"])
    return {"success": result["success"], "offer_id": offer_id, "status": offer["status"],
            "message": result["message"]}


@mcp.tool()
def get_deal_statistics() -> dict:
    """Dashboard: total offers, acceptance rate, avg deal value, days to close."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        SELECT
          COUNT(*) AS total_offers,
          SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) AS accepted,
          SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected,
          AVG(offer_amount) AS avg_offer
        FROM offers
    """)
    s = dict(cur.fetchone())
    cur.execute("SELECT COUNT(*) AS total_deals, SUM(agreed_price) AS total_value FROM deals")
    ds = dict(cur.fetchone()); conn.close()
    total = int(s["total_offers"] or 0)
    accepted = int(s["accepted"] or 0)
    return {
        "total_offers": total,
        "accepted": accepted,
        "rejected": int(s["rejected"] or 0),
        "acceptance_rate_pct": round(accepted / total * 100, 1) if total else 0,
        "avg_offer_value": _fmt(float(s["avg_offer"] or 0)),
        "total_deals": int(ds["total_deals"] or 0),
        "total_deal_value": _fmt(float(ds["total_value"] or 0)),
    }


def main():
    init_db(); mcp.run(transport="streamable-http")

if __name__ == "__main__":
    main()
