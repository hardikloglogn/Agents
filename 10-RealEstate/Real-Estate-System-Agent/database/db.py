"""
database/db.py
══════════════
PostgreSQL schema + seed data for the Property & Real Estate Listing Agent System.

11 Tables:
  users            – RBAC logins (5 roles: admin, agent, manager, buyer, seller)
  properties       – Full property listings catalogue
  clients          – Buyer and seller profiles with preferences
  viewings         – Property viewing appointments
  offers           – Purchase offer records and negotiation history
  deals            – Active deal pipeline from offer to close
  documents        – Transaction document tracking
  interactions     – Client interaction / CRM log
  saved_searches   – Saved buyer search preferences
  market_data      – Market analytics data by area and type
  analytics_log    – Audit and analytics event log
"""

import os
import hashlib
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

_SALT = "realty_salt_2026"


def _hash(pw: str) -> str:
    return hashlib.sha256((pw + _SALT).encode()).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    return _hash(plain) == hashed


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "property_listing"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )


def _ensure_db():
    try:
        c = get_connection(); c.close()
    except psycopg2.OperationalError:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            dbname="postgres",
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
        )
        conn.autocommit = True
        conn.cursor().execute(f"CREATE DATABASE {os.getenv('DB_NAME','property_listing')}")
        conn.close()


def init_db():
    """Create all tables and seed data. Safe to call multiple times."""
    _ensure_db()
    conn = get_connection()
    cur  = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id            SERIAL PRIMARY KEY,
        name          VARCHAR(120) NOT NULL,
        email         VARCHAR(120) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        role          VARCHAR(20)  NOT NULL
                        CHECK (role IN ('admin','agent','manager','buyer','seller')),
        agent_id      VARCHAR(20),
        client_id     VARCHAR(20),
        agency        VARCHAR(120),
        is_active     BOOLEAN DEFAULT TRUE,
        created_at    TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS properties (
        id            SERIAL PRIMARY KEY,
        listing_id    VARCHAR(20) UNIQUE NOT NULL,
        address       TEXT NOT NULL,
        city          VARCHAR(80),
        state         VARCHAR(80),
        pincode       VARCHAR(20),
        property_type VARCHAR(40),
        bedrooms      INTEGER DEFAULT 0,
        bathrooms     INTEGER DEFAULT 0,
        area_sqft     INTEGER DEFAULT 0,
        price         NUMERIC(14,2),
        status        VARCHAR(30) DEFAULT 'active'
                        CHECK (status IN ('active','under_offer','sold','withdrawn','off_market','draft')),
        agent_email   VARCHAR(120),
        features      TEXT,
        description   TEXT,
        listed_at     TIMESTAMP DEFAULT NOW(),
        sold_at       TIMESTAMP,
        days_on_market INTEGER,
        views_count   INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS clients (
        id                 SERIAL PRIMARY KEY,
        client_id          VARCHAR(20) UNIQUE NOT NULL,
        name               VARCHAR(120) NOT NULL,
        email              VARCHAR(120) UNIQUE NOT NULL,
        client_type        VARCHAR(10) CHECK (client_type IN ('buyer','seller','both')),
        budget_min         NUMERIC(14,2),
        budget_max         NUMERIC(14,2),
        preferred_location TEXT,
        preferred_type     VARCHAR(40),
        preferred_bedrooms INTEGER,
        lead_status        VARCHAR(20) DEFAULT 'new'
                             CHECK (lead_status IN ('new','contacted','warm','hot','closed')),
        assigned_agent     VARCHAR(120),
        notes              TEXT,
        created_at         TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS viewings (
        id              SERIAL PRIMARY KEY,
        listing_id      VARCHAR(20) NOT NULL,
        client_email    VARCHAR(120),
        agent_email     VARCHAR(120),
        scheduled_at    TIMESTAMP,
        status          VARCHAR(20) DEFAULT 'scheduled'
                          CHECK (status IN ('scheduled','completed','cancelled','no_show','rescheduled')),
        feedback        TEXT,
        rating          INTEGER CHECK (rating BETWEEN 1 AND 5),
        interest_level  VARCHAR(20) CHECK (interest_level IN ('low','medium','high','very_high')),
        created_at      TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS offers (
        id             SERIAL PRIMARY KEY,
        listing_id     VARCHAR(20) NOT NULL,
        buyer_email    VARCHAR(120),
        offer_amount   NUMERIC(14,2),
        conditions     TEXT,
        validity_date  DATE,
        status         VARCHAR(20) DEFAULT 'pending'
                         CHECK (status IN ('pending','accepted','rejected','countered','withdrawn','expired')),
        countered_amount NUMERIC(14,2),
        counter_conditions TEXT,
        submitted_at   TIMESTAMP DEFAULT NOW(),
        resolved_at    TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS deals (
        id              SERIAL PRIMARY KEY,
        listing_id      VARCHAR(20),
        buyer_email     VARCHAR(120),
        seller_email    VARCHAR(120),
        agreed_price    NUMERIC(14,2),
        stage           VARCHAR(30) DEFAULT 'offer_accepted'
                          CHECK (stage IN ('offer_accepted','documents_pending','under_review',
                                           'due_diligence','closing','completed','fallen_through')),
        expected_close  DATE,
        agent_email     VARCHAR(120),
        notes           TEXT,
        created_at      TIMESTAMP DEFAULT NOW(),
        completed_at    TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS documents (
        id              SERIAL PRIMARY KEY,
        deal_id         INTEGER REFERENCES deals(id),
        listing_id      VARCHAR(20),
        doc_type        VARCHAR(80),
        status          VARCHAR(20) DEFAULT 'pending'
                          CHECK (status IN ('pending','requested','received','signed','rejected','expired')),
        requested_from  VARCHAR(120),
        sent_to         VARCHAR(120),
        notes           TEXT,
        created_at      TIMESTAMP DEFAULT NOW(),
        updated_at      TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS interactions (
        id              SERIAL PRIMARY KEY,
        client_email    VARCHAR(120),
        agent_email     VARCHAR(120),
        interaction_type VARCHAR(30),
        notes           TEXT,
        follow_up_date  DATE,
        created_at      TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS saved_searches (
        id              SERIAL PRIMARY KEY,
        client_email    VARCHAR(120),
        search_name     VARCHAR(120),
        criteria_json   TEXT,
        last_run        TIMESTAMP DEFAULT NOW(),
        match_count     INTEGER DEFAULT 0,
        is_active       BOOLEAN DEFAULT TRUE,
        created_at      TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS market_data (
        id              SERIAL PRIMARY KEY,
        city            VARCHAR(80),
        property_type   VARCHAR(40),
        avg_price       NUMERIC(14,2),
        median_price    NUMERIC(14,2),
        price_trend_pct NUMERIC(5,2),
        avg_days_on_market INTEGER,
        inventory_count INTEGER,
        period          VARCHAR(20),
        recorded_at     TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS analytics_log (
        id              SERIAL PRIMARY KEY,
        event_type      VARCHAR(60),
        entity_id       VARCHAR(40),
        entity_type     VARCHAR(40),
        notes           TEXT,
        user_email      VARCHAR(120),
        created_at      TIMESTAMP DEFAULT NOW()
    );
    """)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] > 0:
        conn.close()
        return

    # ── Users (5 roles) ─────────────────────────────────────────────────────
    cur.execute("""
    INSERT INTO users (name,email,password_hash,role,agent_id,client_id,agency) VALUES
      ('System Admin',       'admin@realty.com',    %s, 'admin',   'ADM-001', NULL,       'PropTech Realty'),
      ('Rahul Sharma',       'agent@realty.com',    %s, 'agent',   'AGT-001', NULL,       'PropTech Realty'),
      ('Meena Broker',       'manager@realty.com',  %s, 'manager', 'MGR-001', NULL,       'PropTech Realty'),
      ('Arjun Buyer',        'buyer@realty.com',    %s, 'buyer',   NULL,      'CLT-2026-001', NULL),
      ('Priya Seller',       'seller@realty.com',   %s, 'seller',  NULL,      'CLT-2026-005', NULL)
    """, (_hash("admin123"), _hash("agent123"), _hash("mgr123"), _hash("buy123"), _hash("sell123")))

    # ── Properties (8 demo listings) ────────────────────────────────────────
    cur.execute("""
    INSERT INTO properties
      (listing_id,address,city,state,pincode,property_type,bedrooms,bathrooms,
       area_sqft,price,status,agent_email,features,description,days_on_market,views_count)
    VALUES
      ('LST-2026-001','14 Park Avenue, Bandra West','Mumbai','Maharashtra','400050',
       'apartment',3,2,1200,12000000,'active','agent@realty.com',
       'Swimming Pool,Gym,Parking,Security','Spacious 3BHK in prime Bandra West with sea view',18,124),
      ('LST-2026-002','7 Green Park, Koramangala','Bangalore','Karnataka','560034',
       'apartment',2,2,980,7500000,'active','agent@realty.com',
       'Clubhouse,Gym,Power Backup,24hr Security','Modern 2BHK in tech hub Koramangala',25,89),
      ('LST-2026-003','22 Rose Lane, Jubilee Hills','Hyderabad','Telangana','500033',
       'villa',4,3,3200,28000000,'active','agent@realty.com',
       'Private Pool,Garden,Modular Kitchen,5-car Parking','Luxurious 4BHK villa in Jubilee Hills',12,210),
      ('LST-2026-004','9 Sector 62, Noida','Noida','UP','201309',
       'apartment',3,2,1450,8500000,'under_offer','agent@realty.com',
       'Metro Connectivity,Gym,Parking','3BHK near Noida Expressway with excellent connectivity',45,312),
      ('LST-2026-005','55 Anna Nagar, Chennai','Chennai','Tamil Nadu','600040',
       'house',3,2,1800,9000000,'active','agent@realty.com',
       'Garden,Covered Parking,Vastu Compliant','Independent 3BHK house in sought-after Anna Nagar',8,56),
      ('LST-2026-006','31 Alipore Road, Kolkata','Kolkata','West Bengal','700027',
       'apartment',2,1,850,5500000,'active','agent@realty.com',
       'Security,Lift,Power Backup','Well-maintained 2BHK in prestigious Alipore',30,78),
      ('LST-2026-007','Plot 12, Whitefield','Bangalore','Karnataka','560066',
       'commercial',0,2,2800,35000000,'active','agent@realty.com',
       'Corner Plot,Main Road Facing,Industrial Zone','Prime commercial plot on Whitefield main road',60,145),
      ('LST-2026-008','Flat 4B, Powai Lake View','Mumbai','Maharashtra','400076',
       'apartment',1,1,520,5800000,'active','agent@realty.com',
       'Lake View,Gym,Pool','Premium 1BHK studio with Powai Lake view — ideal for investment',15,198)
    """)

    # ── Clients (8 demo clients) ─────────────────────────────────────────────
    cur.execute("""
    INSERT INTO clients
      (client_id,name,email,client_type,budget_min,budget_max,preferred_location,
       preferred_type,preferred_bedrooms,lead_status,assigned_agent)
    VALUES
      ('CLT-2026-001','Arjun Buyer','buyer@realty.com','buyer',8000000,15000000,
       'Mumbai,Bandra','apartment',3,'hot','agent@realty.com'),
      ('CLT-2026-002','Sunita Mehta','sunita@example.com','buyer',6000000,9000000,
       'Bangalore,Koramangala','apartment',2,'warm','agent@realty.com'),
      ('CLT-2026-003','Vikram Joshi','vikram@example.com','buyer',20000000,35000000,
       'Hyderabad,Jubilee Hills','villa',4,'hot','agent@realty.com'),
      ('CLT-2026-004','Kavya Reddy','kavya@example.com','buyer',5000000,8000000,
       'Noida,Gurgaon','apartment',2,'contacted','agent@realty.com'),
      ('CLT-2026-005','Priya Seller','seller@realty.com','seller',NULL,NULL,
       'Mumbai','apartment',3,'warm','agent@realty.com'),
      ('CLT-2026-006','Rajesh Kumar','rajesh@example.com','seller',NULL,NULL,
       'Bangalore','commercial',NULL,'hot','agent@realty.com'),
      ('CLT-2026-007','Ananya Singh','ananya@example.com','buyer',4000000,7000000,
       'Chennai,Anna Nagar','house',3,'new','agent@realty.com'),
      ('CLT-2026-008','Dev Patel','dev@example.com','buyer',5000000,7000000,
       'Mumbai,Powai','apartment',1,'warm','agent@realty.com')
    """)

    # ── Viewings ─────────────────────────────────────────────────────────────
    cur.execute("""
    INSERT INTO viewings
      (listing_id,client_email,agent_email,scheduled_at,status,feedback,rating,interest_level)
    VALUES
      ('LST-2026-001','buyer@realty.com','agent@realty.com','2026-03-05 11:00:00',
       'completed','Loved the sea view. Price slightly high.', 4,'high'),
      ('LST-2026-002','sunita@example.com','agent@realty.com','2026-03-06 14:00:00',
       'completed','Good location but parking space limited.',3,'medium'),
      ('LST-2026-003','vikram@example.com','agent@realty.com','2026-03-08 10:00:00',
       'scheduled',NULL,NULL,NULL),
      ('LST-2026-004','kavya@example.com','agent@realty.com','2026-03-04 15:00:00',
       'completed','Very interested. Making an offer.',5,'very_high')
    """)

    # ── Offers ───────────────────────────────────────────────────────────────
    cur.execute("""
    INSERT INTO offers
      (listing_id,buyer_email,offer_amount,conditions,validity_date,status,countered_amount)
    VALUES
      ('LST-2026-004','kavya@example.com',8200000,
       'Subject to bank loan approval','2026-03-15','countered',8400000),
      ('LST-2026-001','buyer@realty.com',11500000,
       'Cash purchase, quick close','2026-03-20','pending',NULL)
    """)

    # ── Market Data ──────────────────────────────────────────────────────────
    cur.execute("""
    INSERT INTO market_data
      (city,property_type,avg_price,median_price,price_trend_pct,avg_days_on_market,inventory_count,period)
    VALUES
      ('Mumbai','apartment',11500000,10800000,8.2,28,145,'Q1-2026'),
      ('Bangalore','apartment',7200000,6800000,12.5,22,210,'Q1-2026'),
      ('Hyderabad','villa',25000000,23000000,15.1,35,48,'Q1-2026'),
      ('Noida','apartment',8200000,7800000,6.3,40,187,'Q1-2026'),
      ('Chennai','house',8800000,8200000,5.8,33,132,'Q1-2026'),
      ('Kolkata','apartment',5200000,4900000,4.1,45,98,'Q1-2026'),
      ('Mumbai','villa',45000000,40000000,9.4,55,32,'Q1-2026'),
      ('Bangalore','commercial',32000000,28000000,11.2,65,67,'Q1-2026')
    """)

    # ── Saved Searches ───────────────────────────────────────────────────────
    import json as _json
    cur.execute("""
    INSERT INTO saved_searches (client_email,search_name,criteria_json,match_count) VALUES
      ('buyer@realty.com','Mumbai 3BHK Under 1.5Cr',
       %s, 3),
      ('sunita@example.com','Bangalore 2BHK Budget',
       %s, 2)
    """, (
        _json.dumps({"city": "Mumbai", "bedrooms": 3, "budget_max": 15000000, "type": "apartment"}),
        _json.dumps({"city": "Bangalore", "bedrooms": 2, "budget_max": 9000000, "type": "apartment"}),
    ))

    conn.commit()
    conn.close()
    print("✅  Property Listing DB initialised with seed data.")