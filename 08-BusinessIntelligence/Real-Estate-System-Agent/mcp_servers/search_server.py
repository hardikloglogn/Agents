"""mcp_servers/search_server.py — Property Search Agent (port 8003 · 8 tools)"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2.extras
from mcp.server.fastmcp import FastMCP
from database.db import get_connection, init_db
from utils.email_service import send_new_listing_alert

mcp = FastMCP("SearchServer", host="127.0.0.1", port=8003, stateless_http=True, json_response=True)


def _cur(conn): return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
def _fmt(p) -> str:
    try: v=float(p); return f"₹{v/10_000_000:.2f}Cr" if v>=10_000_000 else f"₹{v/100_000:.1f}L"
    except: return str(p)


@mcp.tool()
def search_properties(
    city: str = "", property_type: str = "", min_price: float = 0,
    max_price: float = 999_999_999, bedrooms: int = 0, bathrooms: int = 0,
    min_area: int = 0, max_area: int = 99999, status: str = "active", limit: int = 10
) -> list:
    """Advanced property search with multiple filters. Returns matching listings."""
    conn = get_connection(); cur = _cur(conn)
    q = """SELECT listing_id,address,city,state,property_type,bedrooms,bathrooms,
                  area_sqft,price,status,features,description,days_on_market
           FROM properties WHERE 1=1"""
    p = []
    if city: q += " AND city ILIKE %s"; p.append(f"%{city}%")
    if property_type: q += " AND property_type ILIKE %s"; p.append(f"%{property_type}%")
    if status: q += " AND status=%s"; p.append(status)
    if min_price > 0: q += " AND price>=%s"; p.append(min_price)
    if max_price < 999_999_999: q += " AND price<=%s"; p.append(max_price)
    if bedrooms > 0: q += " AND bedrooms=%s"; p.append(bedrooms)
    if bathrooms > 0: q += " AND bathrooms>=%s"; p.append(bathrooms)
    if min_area > 0: q += " AND area_sqft>=%s"; p.append(min_area)
    if max_area < 99999: q += " AND area_sqft<=%s"; p.append(max_area)
    q += f" ORDER BY views_count DESC LIMIT {limit}"
    cur.execute(q, p); rows = cur.fetchall(); conn.close()
    result = [dict(r) | {"price_formatted": _fmt(r["price"])} for r in rows]
    return result or [{"message": "No properties found matching your search criteria. Try broader filters."}]


@mcp.tool()
def get_property_recommendations(client_email: str) -> list:
    """Find top properties matching a buyer's saved preferences from their profile."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT * FROM clients WHERE email=%s AND client_type='buyer'", (client_email,))
    client = cur.fetchone()
    if not client: conn.close(); return [{"message": f"No buyer profile found for {client_email}."}]
    q = "SELECT listing_id,address,city,property_type,bedrooms,bathrooms,area_sqft,price,features,description,views_count FROM properties WHERE status='active'"
    p = []
    if client["preferred_type"]: q += " AND property_type ILIKE %s"; p.append(f"%{client['preferred_type']}%")
    if client["budget_max"]: q += " AND price<=%s"; p.append(float(client["budget_max"]))
    if client["preferred_bedrooms"]: q += " AND bedrooms=%s"; p.append(client["preferred_bedrooms"])
    if client["preferred_location"]:
        locs = [l.strip() for l in client["preferred_location"].split(",")]
        loc_q = " OR ".join(["city ILIKE %s"] * len(locs))
        q += f" AND ({loc_q})"; p.extend([f"%{l}%" for l in locs])
    q += " ORDER BY views_count DESC LIMIT 5"
    cur.execute(q, p); rows = cur.fetchall(); conn.close()
    result = [dict(r) | {"price_formatted": _fmt(r["price"])} for r in rows]
    return result or [{"message": f"No matching properties for buyer {client_email} preferences."}]


@mcp.tool()
def save_search(client_email: str, search_name: str, city: str = "",
                property_type: str = "", budget_max: float = 0,
                bedrooms: int = 0) -> dict:
    """Save a buyer's search criteria for automatic re-running and match alerts."""
    criteria = {}
    if city: criteria["city"] = city
    if property_type: criteria["type"] = property_type
    if budget_max > 0: criteria["budget_max"] = budget_max
    if bedrooms > 0: criteria["bedrooms"] = bedrooms
    conn = get_connection(); cur = _cur(conn)
    # Count matches
    q = "SELECT COUNT(*) AS c FROM properties WHERE status='active'"
    pms = []
    if city: q += " AND city ILIKE %s"; pms.append(f"%{city}%")
    if property_type: q += " AND property_type ILIKE %s"; pms.append(f"%{property_type}%")
    if budget_max > 0: q += " AND price<=%s"; pms.append(budget_max)
    if bedrooms > 0: q += " AND bedrooms=%s"; pms.append(bedrooms)
    cur.execute(q, pms); matches = cur.fetchone()["c"]
    cur.execute("""
        INSERT INTO saved_searches (client_email,search_name,criteria_json,match_count)
        VALUES (%s,%s,%s,%s) RETURNING id
    """, (client_email, search_name, json.dumps(criteria), matches))
    sid = cur.fetchone()["id"]; conn.commit(); conn.close()
    return {"success": True, "search_id": sid, "search_name": search_name,
            "criteria": criteria, "current_matches": matches,
            "message": f"✅ Search '{search_name}' saved. {matches} current matching properties."}


@mcp.tool()
def get_saved_searches(client_email: str) -> list:
    """List all saved searches for a buyer."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("""
        SELECT id,search_name,criteria_json,last_run,match_count
        FROM saved_searches WHERE client_email=%s AND is_active=TRUE ORDER BY created_at DESC
    """, (client_email,))
    rows = cur.fetchall(); conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["criteria"] = json.loads(d["criteria_json"])
        d["last_run"] = str(d["last_run"])[:16]
        result.append(d)
    return result or [{"message": f"No saved searches for {client_email}."}]


@mcp.tool()
def get_nearby_properties(city: str, property_type: str = "", max_price: float = 0,
                          limit: int = 6) -> list:
    """Find properties in a city/area, optionally filtered by type and price."""
    conn = get_connection(); cur = _cur(conn)
    q = "SELECT listing_id,address,city,property_type,bedrooms,price,area_sqft,status,features FROM properties WHERE city ILIKE %s AND status='active'"
    p = [f"%{city}%"]
    if property_type: q += " AND property_type ILIKE %s"; p.append(f"%{property_type}%")
    if max_price > 0: q += " AND price<=%s"; p.append(max_price)
    q += f" ORDER BY listed_at DESC LIMIT {limit}"
    cur.execute(q, p); rows = cur.fetchall(); conn.close()
    result = [dict(r) | {"price_formatted": _fmt(r["price"])} for r in rows]
    return result or [{"message": f"No active properties found near {city}."}]


@mcp.tool()
def compare_properties(listing_ids: str) -> dict:
    """Side-by-side comparison of 2–4 properties. Pass comma-separated listing IDs."""
    ids = [i.strip() for i in listing_ids.split(",") if i.strip()][:4]
    if len(ids) < 2: return {"error": "Provide at least 2 listing IDs to compare."}
    conn = get_connection(); cur = _cur(conn)
    props = []
    for lid in ids:
        cur.execute("SELECT listing_id,address,city,property_type,bedrooms,bathrooms,area_sqft,price,features,status,days_on_market FROM properties WHERE listing_id=%s", (lid,))
        row = cur.fetchone()
        if row: props.append(dict(row) | {"price_formatted": _fmt(row["price"])})
    conn.close()
    if not props: return {"error": "No properties found for given IDs."}
    keys = ["address","city","property_type","bedrooms","bathrooms","area_sqft","price_formatted","features","days_on_market","status"]
    table = {k: [p.get(k,"—") for p in props] for k in keys}
    return {"comparison": table, "properties": props,
            "message": f"Comparison of {len(props)} properties."}


@mcp.tool()
def send_property_matches_email(client_email: str, message: str = "") -> dict:
    """Email top matching properties to a buyer based on their saved preferences."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT name FROM clients WHERE email=%s", (client_email,))
    client = cur.fetchone(); conn.close()
    recs = get_property_recommendations(client_email)
    if not recs or "message" in recs[0]:
        return {"success": False, "message": "No matching properties to send."}
    buyer_name = client["name"] if client else "Valued Buyer"
    prop_strs = [f"{r['listing_id']} — {r['address']} — {r.get('price_formatted','')}" for r in recs[:3]]
    from utils.email_service import send_followup_email
    text = message or "Based on your saved preferences, we found these properties for you:"
    result = send_followup_email(client_email, buyer_name, "PropTech Realty AI", text, prop_strs)
    return {"success": result["success"], "properties_sent": len(prop_strs), "message": result["message"]}


@mcp.tool()
def get_search_analytics() -> dict:
    """Analytics: most searched cities, popular property types, price bands."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT city, COUNT(*) AS count FROM properties WHERE status='active' GROUP BY city ORDER BY count DESC LIMIT 5")
    top_cities = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT property_type, COUNT(*) AS count FROM properties GROUP BY property_type ORDER BY count DESC")
    by_type = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) AS total_searches, SUM(match_count) AS total_matches FROM saved_searches WHERE is_active=TRUE")
    ss = dict(cur.fetchone()); conn.close()
    return {"top_cities_by_inventory": top_cities, "listings_by_type": by_type,
            "saved_searches": int(ss["total_searches"] or 0),
            "total_buyer_matches": int(ss["total_matches"] or 0)}


def main():
    init_db(); mcp.run(transport="streamable-http")

if __name__ == "__main__":
    main()
