"""mcp_servers/analytics_server.py — Market Analytics Agent (port 8007 · 8 tools)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2.extras
from mcp.server.fastmcp import FastMCP
from database.db import get_connection, init_db
from utils.email_service import send_market_report_email

mcp = FastMCP("AnalyticsServer", host="127.0.0.1", port=8007, stateless_http=True, json_response=True)


def _cur(conn): return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
def _fmt(p) -> str:
    try: v=float(p); return f"₹{v/10_000_000:.2f}Cr" if v>=10_000_000 else f"₹{v/100_000:.1f}L"
    except: return str(p)


@mcp.tool()
def get_property_valuation(listing_id: str = "", city: str = "",
                            property_type: str = "", area_sqft: int = 0) -> dict:
    """Estimate market value based on comparables in same city/type. Can use listing_id directly."""
    conn = get_connection(); cur = _cur(conn)
    # Get property details if listing_id given
    if listing_id:
        cur.execute("SELECT city,property_type,area_sqft,price,address,bedrooms FROM properties WHERE listing_id=%s", (listing_id,))
        row = cur.fetchone()
        if row:
            city = row["city"]; property_type = row["property_type"]
            area_sqft = row["area_sqft"]; listed_price = float(row["price"])
            address = row["address"]; bedrooms = row["bedrooms"]
        else:
            conn.close(); return {"error": f"Listing {listing_id} not found."}
    else:
        listed_price = None; address = None; bedrooms = None
    # Get comparables
    cur.execute("""
        SELECT price, area_sqft FROM properties
        WHERE city ILIKE %s AND property_type ILIKE %s
          AND status IN ('active','sold') AND area_sqft>0
        ORDER BY listed_at DESC LIMIT 8
    """, (f"%{city}%", f"%{property_type}%"))
    comps = cur.fetchall()
    # Market data
    cur.execute("SELECT avg_price, price_trend_pct FROM market_data WHERE city ILIKE %s AND property_type ILIKE %s LIMIT 1",
                (f"%{city}%", f"%{property_type}%"))
    mkt = cur.fetchone(); conn.close()
    if comps and area_sqft:
        avg_price_sqft = sum(float(c["price"]) / int(c["area_sqft"]) for c in comps if c["area_sqft"]) / len(comps)
        estimated_value = avg_price_sqft * area_sqft
    elif mkt:
        estimated_value = float(mkt["avg_price"])
    else:
        estimated_value = listed_price or 0
    trend_pct = float(mkt["price_trend_pct"]) if mkt else 0
    return {
        "listing_id": listing_id, "address": address,
        "city": city, "property_type": property_type,
        "area_sqft": area_sqft, "bedrooms": bedrooms,
        "listed_price": _fmt(listed_price) if listed_price else "N/A",
        "estimated_market_value": _fmt(estimated_value),
        "price_per_sqft": f"₹{estimated_value/area_sqft:,.0f}" if area_sqft else "N/A",
        "market_trend": f"+{trend_pct}% YoY" if trend_pct >= 0 else f"{trend_pct}% YoY",
        "comparables_used": len(comps),
        "message": f"Estimated market value: {_fmt(estimated_value)} based on {len(comps)} comparable(s).",
    }


@mcp.tool()
def get_comparable_sales(city: str, property_type: str, bedrooms: int = 0,
                          limit: int = 5) -> list:
    """Recent comparable sales in the same area for price benchmarking."""
    conn = get_connection(); cur = _cur(conn)
    q = """SELECT listing_id, address, city, property_type, bedrooms, area_sqft,
                  price, status, days_on_market, listed_at
           FROM properties WHERE city ILIKE %s AND property_type ILIKE %s
             AND status IN ('sold','active')"""
    p = [f"%{city}%", f"%{property_type}%"]
    if bedrooms > 0: q += " AND bedrooms=%s"; p.append(bedrooms)
    q += f" ORDER BY listed_at DESC LIMIT {limit}"
    cur.execute(q, p); rows = cur.fetchall(); conn.close()
    result = [dict(r) | {"price_formatted": _fmt(r["price"]),
                          "listed_at": str(r["listed_at"])[:10]} for r in rows]
    return result or [{"message": f"No comparable sales data found for {property_type} in {city}."}]


@mcp.tool()
def get_price_trend(city: str, property_type: str = "") -> dict:
    """Price trend for an area over Q1-2026 with percentage change and market data."""
    conn = get_connection(); cur = _cur(conn)
    q = "SELECT * FROM market_data WHERE city ILIKE %s"
    p = [f"%{city}%"]
    if property_type: q += " AND property_type ILIKE %s"; p.append(f"%{property_type}%")
    cur.execute(q, p); rows = cur.fetchall(); conn.close()
    if not rows:
        return {"city": city, "message": f"No market data available for {city}."}
    trends = []
    for r in rows:
        trends.append({
            "property_type": r["property_type"],
            "avg_price": _fmt(r["avg_price"]),
            "median_price": _fmt(r["median_price"]),
            "price_trend_pct": f"+{r['price_trend_pct']}%" if float(r["price_trend_pct"]) >= 0 else f"{r['price_trend_pct']}%",
            "avg_days_on_market": r["avg_days_on_market"],
            "inventory": r["inventory_count"],
            "period": r["period"],
        })
    return {"city": city, "trends": trends,
            "message": f"Price trend data for {city}: {len(trends)} property type(s)."}


@mcp.tool()
def get_market_summary(city: str = "", limit: int = 5) -> dict:
    """Full market report: avg price, days on market, inventory, absorption rate."""
    conn = get_connection(); cur = _cur(conn)
    q = "SELECT * FROM market_data"
    p = []
    if city: q += " WHERE city ILIKE %s"; p.append(f"%{city}%")
    q += " ORDER BY city, property_type"
    cur.execute(q, p); rows = cur.fetchall()
    # Live listings stats
    cur.execute("""
        SELECT city, COUNT(*) AS active_listings, AVG(price) AS avg_price, AVG(days_on_market) AS avg_days
        FROM properties WHERE status='active' GROUP BY city ORDER BY active_listings DESC
    """)
    live = {r["city"]: dict(r) for r in cur.fetchall()}
    conn.close()
    markets = []
    for r in rows:
        d = dict(r)
        d["avg_price_formatted"] = _fmt(d["avg_price"])
        d["median_price_formatted"] = _fmt(d["median_price"])
        d["trend"] = f"+{d['price_trend_pct']}%" if float(d["price_trend_pct"]) >= 0 else f"{d['price_trend_pct']}%"
        live_d = live.get(d["city"], {})
        d["live_active_listings"] = int(live_d.get("active_listings", 0))
        markets.append(d)
    summary = {
        "total_markets_tracked": len(markets),
        "city_filter": city or "All cities",
        "markets": markets,
    }
    report_text = f"MARKET SUMMARY — {city or 'All Cities'}\n" + "="*40 + "\n"
    for m in markets[:8]:
        report_text += f"\n{m['city']} | {m['property_type']}\n"
        report_text += f"  Avg Price: {m['avg_price_formatted']}  |  Trend: {m['trend']}\n"
        report_text += f"  Days on Market: {m['avg_days_on_market']}  |  Inventory: {m['inventory_count']}\n"
    summary["report_text"] = report_text
    return summary


@mcp.tool()
def calculate_rental_yield(listing_id: str, monthly_rent: float,
                            annual_expenses: float = 0) -> dict:
    """Calculate gross and net rental yield for an investment property."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT address, city, price, area_sqft, property_type FROM properties WHERE listing_id=%s", (listing_id,))
    prop = cur.fetchone(); conn.close()
    if not prop: return {"error": f"Listing {listing_id} not found."}
    price = float(prop["price"])
    annual_rent = monthly_rent * 12
    gross_yield = (annual_rent / price * 100) if price > 0 else 0
    net_yield   = ((annual_rent - annual_expenses) / price * 100) if price > 0 else 0
    payback_years = price / (annual_rent - annual_expenses) if (annual_rent - annual_expenses) > 0 else 999
    return {
        "listing_id": listing_id,
        "address": prop["address"],
        "city": prop["city"],
        "purchase_price": _fmt(price),
        "monthly_rent": _fmt(monthly_rent),
        "annual_rent": _fmt(annual_rent),
        "annual_expenses": _fmt(annual_expenses),
        "gross_yield_pct": round(gross_yield, 2),
        "net_yield_pct": round(net_yield, 2),
        "payback_years": round(payback_years, 1),
        "investment_rating": ("🟢 Excellent" if net_yield > 5 else "🟡 Good" if net_yield > 3 else "🔴 Below Average"),
        "message": f"Gross yield: {gross_yield:.2f}% | Net yield: {net_yield:.2f}% | Payback: {payback_years:.1f} years.",
    }


@mcp.tool()
def get_top_areas(metric: str = "price_growth", limit: int = 5) -> list:
    """Top-performing areas by price growth, transaction volume, or demand."""
    conn = get_connection(); cur = _cur(conn)
    if metric == "price_growth":
        cur.execute("SELECT city, property_type, price_trend_pct AS score, avg_price FROM market_data ORDER BY price_trend_pct DESC LIMIT %s", (limit,))
    elif metric == "inventory":
        cur.execute("SELECT city, property_type, inventory_count AS score, avg_price FROM market_data ORDER BY inventory_count DESC LIMIT %s", (limit,))
    else:
        cur.execute("SELECT city, property_type, avg_price AS score, price_trend_pct FROM market_data ORDER BY avg_price DESC LIMIT %s", (limit,))
    rows = cur.fetchall(); conn.close()
    result = []
    for i, r in enumerate(rows, 1):
        d = dict(r)
        d["rank"] = i
        d["avg_price_formatted"] = _fmt(d.get("avg_price", 0))
        result.append(d)
    return result or [{"message": "No market data available."}]


@mcp.tool()
def get_investment_analysis(listing_id: str, monthly_rent: float = 0,
                             annual_expenses: float = 0) -> dict:
    """Full investment analysis: ROI, yield, payback, market position."""
    valuation = get_property_valuation(listing_id=listing_id)
    if monthly_rent > 0:
        yield_data = calculate_rental_yield(listing_id, monthly_rent, annual_expenses)
    else:
        yield_data = {"note": "Provide monthly_rent for yield calculation."}
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT city, property_type, price FROM properties WHERE listing_id=%s", (listing_id,))
    prop = cur.fetchone()
    mkt_trend = None
    if prop:
        cur.execute("SELECT price_trend_pct, avg_days_on_market FROM market_data WHERE city ILIKE %s AND property_type ILIKE %s LIMIT 1",
                    (f"%{prop['city']}%", f"%{prop['property_type']}%"))
        mkt_trend = cur.fetchone()
    conn.close()
    return {
        "listing_id": listing_id,
        "valuation": valuation,
        "rental_analysis": yield_data,
        "market_trend": f"+{mkt_trend['price_trend_pct']}% YoY" if mkt_trend else "N/A",
        "avg_days_on_market": mkt_trend["avg_days_on_market"] if mkt_trend else "N/A",
        "investment_verdict": ("✅ Strong investment opportunity" if float(mkt_trend["price_trend_pct"] or 0) > 8
                               else "⚠️ Moderate opportunity — research further"),
    }


@mcp.tool()
def send_market_report_email_tool(to_email: str, city: str) -> dict:
    """Email a formatted market report to a client or agent."""
    conn = get_connection(); cur = _cur(conn)
    cur.execute("SELECT name FROM clients WHERE email=%s UNION SELECT name FROM users WHERE email=%s",
                (to_email, to_email))
    row = cur.fetchone(); conn.close()
    recipient = row["name"] if row else to_email.split("@")[0].title()
    summary = get_market_summary(city)
    report_text = summary.get("report_text", f"Market report for {city}")
    result = send_market_report_email(to_email, recipient, city, report_text)
    return {"success": result["success"], "to_email": to_email, "city": city,
            "message": result["message"]}


def main():
    init_db(); mcp.run(transport="streamable-http")

if __name__ == "__main__":
    main()
