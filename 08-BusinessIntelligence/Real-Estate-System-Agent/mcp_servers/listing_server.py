"""mcp_servers/listing_server.py — Property Listing Agent (port 8001 · 8 tools)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2.extras
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from database.db import get_connection, init_db
from utils.email_service import send_new_listing_alert

mcp = FastMCP("ListingServer", host="127.0.0.1", port=8001, stateless_http=True, json_response=True)


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _gen_id() -> str:
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT COUNT(*) AS c FROM properties")
    n = cur.fetchone()["c"] + 1; conn.close()
    return f"LST-{datetime.now().year}-{n:04d}"


def _fmt(p) -> str:
    try:
        v = float(p)
        return f"₹{v/10_000_000:.2f} Cr" if v >= 10_000_000 else f"₹{v/100_000:.1f} L"
    except Exception: return str(p)


@mcp.tool()
def create_listing(
    address: str, city: str, state: str, pincode: str,
    property_type: str, bedrooms: int, bathrooms: int,
    area_sqft: int, price: float, agent_email: str,
    features: str = "", description: str = ""
) -> dict:
    """Create a new property listing and send alert emails to matched buyers."""
    conn = get_connection(); cur = _cur(conn)
    listing_id = _gen_id()
    cur.execute("""
        INSERT INTO properties
          (listing_id,address,city,state,pincode,property_type,bedrooms,bathrooms,
           area_sqft,price,status,agent_email,features,description,days_on_market,views_count)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,0,0) RETURNING id
    """, (listing_id, address, city, state, pincode, property_type, bedrooms,
          bathrooms, area_sqft, price, agent_email, features, description))
    conn.commit()
    # Alert matched buyers from saved searches
    import json
    cur.execute("SELECT client_email,search_name,criteria_json FROM saved_searches WHERE is_active=TRUE")
    searches = cur.fetchall()
    alerts_sent = 0
    for s in searches:
        try:
            criteria = json.loads(s["criteria_json"])
            match = True
            if criteria.get("city") and criteria["city"].lower() not in city.lower(): match = False
            if criteria.get("bedrooms") and int(criteria["bedrooms"]) != bedrooms: match = False
            if criteria.get("budget_max") and price > float(criteria["budget_max"]): match = False
            if criteria.get("type") and criteria["type"].lower() not in property_type.lower(): match = False
            if match:
                cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur2.execute("SELECT name FROM clients WHERE email=%s", (s["client_email"],))
                c_row = cur2.fetchone()
                buyer_name = c_row["name"] if c_row else "Valued Buyer"
                send_new_listing_alert(s["client_email"], buyer_name, listing_id, address, price, bedrooms, city)
                alerts_sent += 1
        except Exception:
            pass
    conn.close()
    return {
        "success": True, "listing_id": listing_id, "address": address,
        "city": city, "property_type": property_type, "bedrooms": bedrooms,
        "price": _fmt(price), "status": "active",
        "buyer_alerts_sent": alerts_sent,
        "message": f"✅ Listing {listing_id} created at {address}. {_fmt(price)}. {alerts_sent} buyer alert(s) sent.",
    }


@mcp.tool()
def update_listing(listing_id: str, field: str, new_value: str) -> dict:
    """Update a listing field: price, description, features, status, agent_email, area_sqft, bedrooms."""
    allowed = {"price","description","features","agent_email","area_sqft","bedrooms","bathrooms"}
    if field not in allowed:
        return {"success": False, "message": f"Cannot update '{field}'. Allowed: {', '.join(allowed)}"}
    conn = get_connection(); cur = _cur(conn)
    numeric = {"price","area_sqft","bedrooms","bathrooms"}
    val = float(new_value) if field == "price" else (int(new_value) if field in numeric else new_value)
    cur.execute(f"UPDATE properties SET {field}=%s WHERE listing_id=%s RETURNING address",
                (val, listing_id))
    row = cur.fetchone()
    if not row:
        conn.close(); return {"success": False, "message": f"Listing {listing_id} not found."}
    conn.commit(); conn.close()
    disp = _fmt(val) if field == "price" else str(new_value)
    return {"success": True, "listing_id": listing_id, "field": field,
            "new_value": disp, "message": f"✅ Updated {field} on {listing_id} to {disp}."}


@mcp.tool()
def get_listing_details(listing_id: str = "", address: str = "") -> dict:
    """Get full listing details by listing ID or address."""
    if not listing_id and not address:
        return {"found": False, "message": "Provide listing_id or address."}
    conn = get_connection(); cur = _cur(conn)
    if listing_id:
        cur.execute("SELECT * FROM properties WHERE listing_id=%s", (listing_id,))
    else:
        cur.execute("SELECT * FROM properties WHERE address ILIKE %s", (f"%{address}%",))
    row = cur.fetchone(); conn.close()
    if not row:
        return {"found": False, "message": "Listing not found."}
    d = dict(row); d["found"] = True
    d["listed_at"] = str(d["listed_at"])[:16]
    d["price_formatted"] = _fmt(d["price"])
    return d


@mcp.tool()
def list_properties(
    city: str = "", property_type: str = "", status: str = "active",
    min_price: float = 0, max_price: float = 999_999_999,
    bedrooms: int = 0, limit: int = 10
) -> list:
    """List properties with optional filters."""
    conn = get_connection(); cur = _cur(conn)
    q = "SELECT listing_id,address,city,property_type,bedrooms,bathrooms,area_sqft,price,status,features,days_on_market,views_count FROM properties WHERE 1=1"
    p = []
    if city: q += " AND city ILIKE %s"; p.append(f"%{city}%")
    if property_type: q += " AND property_type ILIKE %s"; p.append(f"%{property_type}%")
    if status: q += " AND status=%s"; p.append(status)
    if min_price > 0: q += " AND price>=%s"; p.append(min_price)
    if max_price < 999_999_999: q += " AND price<=%s"; p.append(max_price)
    if bedrooms > 0: q += " AND bedrooms=%s"; p.append(bedrooms)
    q += f" ORDER BY listed_at DESC LIMIT {limit}"
    cur.execute(q, p); rows = cur.fetchall(); conn.close()
    result = []
    for r in rows:
        d = dict(r); d["price_formatted"] = _fmt(d["price"]); result.append(d)
    return result or [{"message": "No properties found matching criteria."}]


@mcp.tool()
def change_listing_status(listing_id: str, new_status: str, reason: str = "") -> dict:
    """Set listing status: active, under_offer, sold, withdrawn, off_market, draft."""
    valid = {"active","under_offer","sold","withdrawn","off_market","draft"}
    if new_status not in valid:
        return {"success": False, "message": f"Invalid status. Choose: {', '.join(valid)}"}
    conn = get_connection(); cur = _cur(conn)
    extra = "sold_at=NOW()," if new_status == "sold" else ""
    cur.execute(f"UPDATE properties SET status=%s,{extra} WHERE listing_id=%s RETURNING address",
                (new_status, listing_id))
    row = cur.fetchone()
    if not row: conn.close(); return {"success": False, "message": f"Listing {listing_id} not found."}
    conn.commit(); conn.close()
    return {"success": True, "listing_id": listing_id, "new_status": new_status,
            "address": row["address"], "reason": reason,
            "message": f"✅ Listing {listing_id} status → '{new_status}'."}


@mcp.tool()
def get_agent_listings(agent_email: str) -> dict:
    """All listings for a specific agent with key performance metrics."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        SELECT listing_id,address,city,property_type,bedrooms,price,status,
               days_on_market,views_count
        FROM properties WHERE agent_email=%s ORDER BY listed_at DESC
    """, (agent_email,))
    rows = cur.fetchall()
    cur.execute("""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active_count,
          SUM(CASE WHEN status='sold' THEN 1 ELSE 0 END) AS sold_count,
          AVG(price) AS avg_price,
          AVG(days_on_market) AS avg_days
        FROM properties WHERE agent_email=%s
    """, (agent_email,))
    stats = dict(cur.fetchone()); conn.close()
    listings = [dict(r) | {"price_formatted": _fmt(r["price"])} for r in rows]
    return {"agent_email": agent_email, "stats": {k: float(v or 0) for k, v in stats.items()},
            "listings": listings}


@mcp.tool()
def send_new_listing_alert_tool(listing_id: str, buyer_email: str) -> dict:
    """Manually send a new listing alert email to a specific buyer."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT address,city,price,bedrooms FROM properties WHERE listing_id=%s", (listing_id,))
    prop = cur.fetchone()
    cur.execute("SELECT name FROM clients WHERE email=%s", (buyer_email,))
    client = cur.fetchone(); conn.close()
    if not prop: return {"success": False, "message": f"Listing {listing_id} not found."}
    buyer_name = client["name"] if client else "Valued Buyer"
    result = send_new_listing_alert(buyer_email, buyer_name, listing_id,
                                    prop["address"], prop["price"], prop["bedrooms"], prop["city"])
    return {"success": result["success"], "listing_id": listing_id,
            "buyer_email": buyer_email, "message": result["message"]}


@mcp.tool()
def get_listing_statistics() -> dict:
    """Dashboard: total active listings, average price, avg days on market, sold count."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active,
          SUM(CASE WHEN status='sold' THEN 1 ELSE 0 END) AS sold,
          SUM(CASE WHEN status='under_offer' THEN 1 ELSE 0 END) AS under_offer,
          AVG(price) AS avg_price,
          AVG(days_on_market) AS avg_days_on_market,
          SUM(views_count) AS total_views
        FROM properties
    """)
    s = dict(cur.fetchone())
    cur.execute("SELECT city, COUNT(*) AS count FROM properties WHERE status='active' GROUP BY city ORDER BY count DESC LIMIT 5")
    top_cities = [dict(r) for r in cur.fetchall()]; conn.close()
    return {
        "total_listings": int(s["total"] or 0),
        "active": int(s["active"] or 0),
        "sold": int(s["sold"] or 0),
        "under_offer": int(s["under_offer"] or 0),
        "avg_price": _fmt(float(s["avg_price"] or 0)),
        "avg_days_on_market": round(float(s["avg_days_on_market"] or 0), 1),
        "total_views": int(s["total_views"] or 0),
        "top_cities": top_cities,
    }


def main():
    init_db()
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
