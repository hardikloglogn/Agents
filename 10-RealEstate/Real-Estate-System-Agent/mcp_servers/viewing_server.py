"""mcp_servers/viewing_server.py — Viewing & Appointment Agent (port 8004 · 8 tools)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2.extras
from mcp.server.fastmcp import FastMCP
from database.db import get_connection, init_db
from utils.email_service import send_viewing_confirmation, send_viewing_reminder

mcp = FastMCP("ViewingServer", host="127.0.0.1", port=8004, stateless_http=True, json_response=True)


def _cur(conn): return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


@mcp.tool()
def book_viewing(listing_id: str, client_email: str, agent_email: str,
                 scheduled_at: str) -> dict:
    """Schedule a property viewing. Send confirmation emails to buyer and agent."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT address, city FROM properties WHERE listing_id=%s", (listing_id,))
    prop = cur.fetchone()
    if not prop: conn.close(); return {"success": False, "message": f"Listing {listing_id} not found."}
    # Check for double-booking (same client, same property, same date)
    cur.execute("""
        SELECT id FROM viewings WHERE listing_id=%s AND client_email=%s
        AND status IN ('scheduled','rescheduled')
        AND DATE(scheduled_at)=DATE(%s::timestamp)
    """, (listing_id, client_email, scheduled_at))
    if cur.fetchone():
        conn.close()
        return {"success": False, "message": "This buyer already has a viewing booked for this property on that date."}
    cur.execute("""
        INSERT INTO viewings (listing_id,client_email,agent_email,scheduled_at,status)
        VALUES (%s,%s,%s,%s,'scheduled') RETURNING id
    """, (listing_id, client_email, agent_email, scheduled_at))
    vid = cur.fetchone()["id"]
    cur.execute("UPDATE properties SET views_count=views_count+1 WHERE listing_id=%s", (listing_id,))
    conn.commit(); conn.close()
    address = f"{prop['address']}, {prop['city']}"
    email_result = send_viewing_confirmation(client_email, agent_email, client_email.split("@")[0].title(),
                                              address, scheduled_at)
    return {"success": True, "viewing_id": vid, "listing_id": listing_id,
            "client_email": client_email, "scheduled_at": scheduled_at,
            "email_sent": email_result["success"],
            "message": f"✅ Viewing #{vid} booked for {address} at {scheduled_at}. Confirmation emails sent."}


@mcp.tool()
def reschedule_viewing(viewing_id: int, new_datetime: str, reason: str = "") -> dict:
    """Change viewing date/time. Notify all parties by email."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        UPDATE viewings SET scheduled_at=%s, status='rescheduled'
        WHERE id=%s RETURNING listing_id, client_email, agent_email
    """, (new_datetime, viewing_id))
    row = cur.fetchone()
    if not row: conn.close(); return {"success": False, "message": f"Viewing #{viewing_id} not found."}
    cur.execute("SELECT address, city FROM properties WHERE listing_id=%s", (row["listing_id"],))
    prop = cur.fetchone(); conn.commit(); conn.close()
    address = f"{prop['address']}, {prop['city']}" if prop else row["listing_id"]
    send_viewing_confirmation(row["client_email"], row["agent_email"],
                               row["client_email"].split("@")[0].title(),
                               address, new_datetime)
    return {"success": True, "viewing_id": viewing_id, "new_datetime": new_datetime,
            "message": f"✅ Viewing #{viewing_id} rescheduled to {new_datetime}. Parties notified."}


@mcp.tool()
def cancel_viewing(viewing_id: int, reason: str = "") -> dict:
    """Cancel a viewing and notify all parties."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        UPDATE viewings SET status='cancelled'
        WHERE id=%s AND status IN ('scheduled','rescheduled')
        RETURNING listing_id, client_email, agent_email, scheduled_at
    """, (viewing_id,))
    row = cur.fetchone()
    if not row: conn.close(); return {"success": False, "message": f"Viewing #{viewing_id} not found or already resolved."}
    cur.execute("UPDATE properties SET views_count=GREATEST(0,views_count-1) WHERE listing_id=%s", (row["listing_id"],))
    conn.commit(); conn.close()
    return {"success": True, "viewing_id": viewing_id, "reason": reason,
            "client_email": row["client_email"],
            "message": f"✅ Viewing #{viewing_id} cancelled. Slot freed."}


@mcp.tool()
def get_viewing_schedule(agent_email: str = "", listing_id: str = "",
                          date_filter: str = "") -> list:
    """List all viewings for a property or agent."""
    conn = get_connection(); cur = _cur(conn)
    q = "SELECT v.id,v.listing_id,v.client_email,v.agent_email,v.scheduled_at,v.status,v.rating,v.interest_level,p.address,p.city FROM viewings v LEFT JOIN properties p ON p.listing_id=v.listing_id WHERE 1=1"
    p = []
    if agent_email: q += " AND v.agent_email=%s"; p.append(agent_email)
    if listing_id: q += " AND v.listing_id=%s"; p.append(listing_id)
    if date_filter: q += " AND DATE(v.scheduled_at)=%s"; p.append(date_filter)
    q += " ORDER BY v.scheduled_at ASC"
    cur.execute(q, p); rows = cur.fetchall(); conn.close()
    result = []
    for r in rows:
        d = dict(r); d["scheduled_at"] = str(d["scheduled_at"])[:16]; result.append(d)
    return result or [{"message": "No viewings found."}]


@mcp.tool()
def record_viewing_feedback(viewing_id: int, rating: int, feedback: str,
                             interest_level: str = "medium") -> dict:
    """Record buyer feedback after a viewing: 1–5 rating, notes, interest level."""
    if rating < 1 or rating > 5:
        return {"success": False, "message": "Rating must be between 1 and 5."}
    valid_interest = {"low","medium","high","very_high"}
    if interest_level not in valid_interest:
        return {"success": False, "message": f"interest_level must be: {', '.join(valid_interest)}"}
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        UPDATE viewings SET rating=%s, feedback=%s, interest_level=%s, status='completed'
        WHERE id=%s RETURNING listing_id, client_email
    """, (rating, feedback, interest_level, viewing_id))
    row = cur.fetchone()
    if not row: conn.close(); return {"success": False, "message": f"Viewing #{viewing_id} not found."}
    conn.commit(); conn.close()
    interest_emoji = {"low":"😐","medium":"🙂","high":"😊","very_high":"🤩"}.get(interest_level,"")
    return {"success": True, "viewing_id": viewing_id, "rating": rating,
            "interest_level": f"{interest_emoji} {interest_level}",
            "message": f"✅ Feedback recorded for viewing #{viewing_id}. Rating: {rating}/5. Interest: {interest_level}."}


@mcp.tool()
def get_viewing_history(listing_id: str = "", client_email: str = "") -> list:
    """Full viewing history for a property or buyer."""
    conn = get_connection(); cur = _cur(conn)
    q = "SELECT v.*,p.address,p.city FROM viewings v LEFT JOIN properties p ON p.listing_id=v.listing_id WHERE 1=1"
    p = []
    if listing_id: q += " AND v.listing_id=%s"; p.append(listing_id)
    if client_email: q += " AND v.client_email=%s"; p.append(client_email)
    q += " ORDER BY v.scheduled_at DESC"
    cur.execute(q, p); rows = cur.fetchall(); conn.close()
    result = []
    for r in rows:
        d = dict(r); d["scheduled_at"] = str(d["scheduled_at"])[:16]; result.append(d)
    return result or [{"message": "No viewing history found."}]


@mcp.tool()
def send_viewing_reminder_tool(viewing_id: int) -> dict:
    """Send a 24-hour reminder email to the buyer before their scheduled viewing."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        SELECT v.client_email, v.scheduled_at, p.address, p.city
        FROM viewings v LEFT JOIN properties p ON p.listing_id=v.listing_id
        WHERE v.id=%s
    """, (viewing_id,))
    row = cur.fetchone(); conn.close()
    if not row: return {"success": False, "message": f"Viewing #{viewing_id} not found."}
    address = f"{row['address']}, {row['city']}"
    result = send_viewing_reminder(row["client_email"],
                                    row["client_email"].split("@")[0].title(),
                                    address, str(row["scheduled_at"])[:16])
    return {"success": result["success"], "viewing_id": viewing_id,
            "client_email": row["client_email"], "message": result["message"]}


@mcp.tool()
def get_viewing_statistics() -> dict:
    """Stats: total viewings, conversion to offer rate, avg feedback score."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
          SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) AS cancelled,
          AVG(CASE WHEN rating IS NOT NULL THEN rating END) AS avg_rating,
          SUM(CASE WHEN interest_level IN ('high','very_high') THEN 1 ELSE 0 END) AS high_interest
        FROM viewings
    """)
    s = dict(cur.fetchone())
    cur.execute("SELECT COUNT(DISTINCT listing_id) AS viewed, COUNT(DISTINCT v.listing_id) AS offered FROM viewings v JOIN offers o ON o.listing_id=v.listing_id")
    conv = dict(cur.fetchone()); conn.close()
    total = int(s["total"] or 0)
    completed = int(s["completed"] or 0)
    return {
        "total_viewings": total,
        "completed": completed,
        "cancelled": int(s["cancelled"] or 0),
        "high_interest_count": int(s["high_interest"] or 0),
        "avg_feedback_rating": round(float(s["avg_rating"] or 0), 1),
        "properties_that_received_offers": int(conv["offered"] or 0),
    }


def main():
    init_db(); mcp.run(transport="streamable-http")

if __name__ == "__main__":
    main()
