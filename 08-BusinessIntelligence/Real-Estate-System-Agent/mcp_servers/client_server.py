"""mcp_servers/client_server.py — Client & Lead Agent (port 8002 · 8 tools)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2.extras
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from database.db import get_connection, init_db
from utils.email_service import send_followup_email

mcp = FastMCP("ClientServer", host="127.0.0.1", port=8002, stateless_http=True, json_response=True)


def _cur(conn): return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _gen_id() -> str:
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT COUNT(*) AS c FROM clients")
    n = cur.fetchone()["c"] + 1; conn.close()
    return f"CLT-{datetime.now().year}-{n:04d}"


@mcp.tool()
def register_buyer(name: str, email: str, budget_min: float, budget_max: float,
                   preferred_location: str, preferred_type: str = "apartment",
                   preferred_bedrooms: int = 2, assigned_agent: str = "") -> dict:
    """Register a new buyer profile with budget and property preferences."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT id FROM clients WHERE email=%s", (email,))
    if cur.fetchone(): conn.close(); return {"success": False, "message": f"Client {email} already exists."}
    cid = _gen_id()
    cur.execute("""
        INSERT INTO clients
          (client_id,name,email,client_type,budget_min,budget_max,
           preferred_location,preferred_type,preferred_bedrooms,assigned_agent)
        VALUES (%s,%s,%s,'buyer',%s,%s,%s,%s,%s,%s)
    """, (cid, name, email, budget_min, budget_max, preferred_location,
          preferred_type, preferred_bedrooms, assigned_agent))
    conn.commit(); conn.close()
    return {"success": True, "client_id": cid, "name": name, "email": email,
            "type": "buyer", "budget_max": budget_max,
            "message": f"✅ Buyer '{name}' registered with ID {cid}."}


@mcp.tool()
def register_seller(name: str, email: str, property_address: str,
                    expected_price: float, timeline: str = "flexible",
                    reason: str = "", assigned_agent: str = "") -> dict:
    """Register a new seller profile with their property details."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT id FROM clients WHERE email=%s", (email,))
    if cur.fetchone(): conn.close(); return {"success": False, "message": f"Client {email} already exists."}
    cid = _gen_id()
    notes = f"Property: {property_address} | Expected: ₹{expected_price:,.0f} | Timeline: {timeline} | Reason: {reason}"
    cur.execute("""
        INSERT INTO clients (client_id,name,email,client_type,preferred_location,assigned_agent,notes)
        VALUES (%s,%s,%s,'seller',%s,%s,%s)
    """, (cid, name, email, property_address, assigned_agent, notes))
    conn.commit(); conn.close()
    return {"success": True, "client_id": cid, "name": name, "email": email,
            "type": "seller", "property": property_address,
            "message": f"✅ Seller '{name}' registered with ID {cid}."}


@mcp.tool()
def get_client_profile(client_id: str = "", email: str = "") -> dict:
    """Get full client profile by client ID or email."""
    if not client_id and not email:
        return {"found": False, "message": "Provide client_id or email."}
    conn = get_connection(); cur = _cur(conn)
    if client_id: cur.execute("SELECT * FROM clients WHERE client_id=%s", (client_id,))
    else: cur.execute("SELECT * FROM clients WHERE email=%s", (email,))
    row = cur.fetchone(); conn.close()
    if not row: return {"found": False, "message": "Client not found."}
    d = dict(row); d["found"] = True
    d["created_at"] = str(d["created_at"])[:16]
    return d


@mcp.tool()
def update_client_preferences(client_id: str, field: str, new_value: str) -> dict:
    """Update buyer preferences: preferred_location, preferred_type, budget_min, budget_max, preferred_bedrooms."""
    allowed = {"preferred_location","preferred_type","budget_min","budget_max","preferred_bedrooms","notes"}
    if field not in allowed:
        return {"success": False, "message": f"Cannot update '{field}'."}
    conn = get_connection(); cur = _cur(conn)
    numeric = {"budget_min","budget_max","preferred_bedrooms"}
    val = float(new_value) if field in numeric else new_value
    cur.execute(f"UPDATE clients SET {field}=%s WHERE client_id=%s RETURNING name",
                (val, client_id))
    row = cur.fetchone()
    if not row: conn.close(); return {"success": False, "message": f"Client {client_id} not found."}
    conn.commit(); conn.close()
    return {"success": True, "client_id": client_id, "field": field, "new_value": new_value,
            "message": f"✅ Updated {field} for {row['name']}."}


@mcp.tool()
def get_leads(status: str = "hot", limit: int = 20) -> list:
    """List leads by pipeline status: new, contacted, warm, hot, closed."""
    conn = get_connection(); cur = _cur(conn)
    q = "SELECT client_id,name,email,client_type,lead_status,preferred_location,budget_max,assigned_agent,created_at FROM clients WHERE 1=1"
    p = []
    if status and status != "all": q += " AND lead_status=%s"; p.append(status)
    q += f" ORDER BY created_at DESC LIMIT {limit}"
    cur.execute(q, p); rows = cur.fetchall(); conn.close()
    result = [dict(r) | {"created_at": str(r["created_at"])[:16]} for r in rows]
    return result or [{"message": f"No {status} leads found."}]


@mcp.tool()
def update_lead_status(client_id: str, new_status: str, notes: str = "") -> dict:
    """Move a lead through the pipeline: new → contacted → warm → hot → closed."""
    valid = {"new","contacted","warm","hot","closed"}
    if new_status not in valid:
        return {"success": False, "message": f"Invalid status. Choose: {', '.join(valid)}"}
    conn = get_connection(); cur = _cur(conn)
    cur.execute("UPDATE clients SET lead_status=%s WHERE client_id=%s RETURNING name,email",
                (new_status, client_id))
    row = cur.fetchone()
    if not row: conn.close(); return {"success": False, "message": f"Client {client_id} not found."}
    if notes:
        cur.execute("UPDATE clients SET notes=COALESCE(notes,'') || %s WHERE client_id=%s",
                    (f"\n[{datetime.now().strftime('%Y-%m-%d')}] {notes}", client_id))
    conn.commit(); conn.close()
    return {"success": True, "client_id": client_id, "name": row["name"],
            "new_status": new_status, "message": f"✅ {row['name']} lead status → '{new_status}'."}


@mcp.tool()
def log_interaction(client_email: str, agent_email: str, interaction_type: str,
                    notes: str, follow_up_date: str = "") -> dict:
    """Record a client interaction: call, email, viewing, meeting."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        INSERT INTO interactions (client_email,agent_email,interaction_type,notes,follow_up_date)
        VALUES (%s,%s,%s,%s,%s) RETURNING id
    """, (client_email, agent_email, interaction_type, notes, follow_up_date or None))
    iid = cur.fetchone()["id"]; conn.commit(); conn.close()
    return {"success": True, "interaction_id": iid, "client_email": client_email,
            "type": interaction_type, "follow_up": follow_up_date or "None set",
            "message": f"✅ Interaction logged (#{iid}). Follow-up: {follow_up_date or 'None'}."}


@mcp.tool()
def send_followup_email_tool(client_email: str, agent_email: str,
                              message: str, property_ids: str = "") -> dict:
    """Send a personalised follow-up email to a client with optional property recommendations."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT name FROM clients WHERE email=%s", (client_email,))
    client = cur.fetchone()
    cur.execute("SELECT name FROM users WHERE email=%s", (agent_email,))
    agent = cur.fetchone()
    props = []
    if property_ids:
        for pid in property_ids.split(","):
            cur.execute("SELECT address, price FROM properties WHERE listing_id=%s", (pid.strip(),))
            p = cur.fetchone()
            if p: props.append(f"{p['address']} — ₹{float(p['price'])/10_000_000:.2f}Cr")
    conn.close()
    client_name = client["name"] if client else "Valued Client"
    agent_name  = agent["name"]  if agent  else agent_email
    result = send_followup_email(client_email, client_name, agent_name, message, props)
    return {"success": result["success"], "client_email": client_email,
            "properties_included": len(props), "message": result["message"]}


def main():
    init_db(); mcp.run(transport="streamable-http")

if __name__ == "__main__":
    main()
