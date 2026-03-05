"""utils/auth.py — RBAC authentication helpers for Real Estate system."""

import psycopg2.extras
from database.db import get_connection, verify_password

ROLE_AGENTS: dict[str, list[str]] = {
    "admin": [
        "Property Listing", "Client & Lead", "Property Search",
        "Viewing & Appointment", "Offer & Deal",
        "Document & Legal", "Market Analytics", "Direct Answering Agent",
    ],
    "agent": [
        "Property Listing", "Client & Lead", "Property Search",
        "Viewing & Appointment", "Offer & Deal",
        "Document & Legal", "Market Analytics", "Direct Answering Agent",
    ],
    "manager": [
        "Property Listing", "Client & Lead", "Property Search",
        "Viewing & Appointment", "Offer & Deal",
        "Document & Legal", "Market Analytics", "Direct Answering Agent",
    ],
    "buyer": [
        "Property Search", "Viewing & Appointment",
        "Offer & Deal", "Direct Answering Agent",
    ],
    "seller": [
        "Property Listing", "Offer & Deal",
        "Document & Legal", "Market Analytics", "Direct Answering Agent",
    ],
}

ROLE_LABELS = {
    "admin":   "🛡️  Admin",
    "agent":   "🏠  Realtor",
    "manager": "💼  Broker",
    "buyer":   "🔍  Buyer",
    "seller":  "🏷️  Seller",
}

ROLE_COLORS = {
    "admin":   "#f59e0b",
    "agent":   "#1d5fa6",
    "manager": "#0b7b6b",
    "buyer":   "#5b21b6",
    "seller":  "#c2410c",
}


def authenticate(email: str, password: str) -> dict | None:
    try:
        conn = get_connection()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id,name,email,password_hash,role,agent_id,client_id,agency "
            "FROM users WHERE email=%s AND is_active=TRUE",
            (email.strip().lower(),),
        )
        user = cur.fetchone(); conn.close()
        if user and verify_password(password, user["password_hash"]):
            return {
                "id":        user["id"],
                "name":      user["name"],
                "email":     user["email"],
                "role":      user["role"],
                "agent_id":  user["agent_id"],
                "client_id": user["client_id"],
                "agency":    user["agency"],
            }
        return None
    except Exception:
        return None