# ui/constants.py

QUICK_ACTIONS = {
    "admin": [
        ("📊 Listing Dashboard",      "Show me the overall property listing statistics"),
        ("👥 Hot Leads",               "Show all hot leads in the pipeline"),
        ("🔍 Mumbai 3BHK Search",     "Search for 3BHK apartments in Mumbai under ₹1.5 Crore"),
        ("📈 Market Summary",          "Show me the full market summary for all cities"),
        ("💼 Deal Pipeline",           "Show the current active deal pipeline"),
        ("⚠️  Compliance Audit",       "Check compliance status for listing LST-2026-004"),
    ],
    "agent": [
        ("🏠 My Listings",             "Show all listings for agent@realty.com"),
        ("👥 Register Buyer",          "Register a new buyer: Deepak Nair, deepak@example.com, budget ₹80L to ₹1.2Cr, Bangalore 2BHK"),
        ("📅 Book Viewing",            "Book a viewing for listing LST-2026-001 for buyer buyer@realty.com tomorrow at 11am"),
        ("📝 Submit Offer",            "Submit an offer of ₹1.15 Crore on listing LST-2026-001 for buyer buyer@realty.com, valid 7 days"),
        ("📊 Market Analytics",        "Get property valuation and market trend for listing LST-2026-001"),
        ("📋 Document Checklist",      "Show document checklist for listing LST-2026-004"),
    ],
    "manager": [
        ("📈 Full Market Report",      "Show the complete market summary for Mumbai"),
        ("💼 Deal Pipeline",           "Show all active deals in the pipeline"),
        ("👥 Lead Pipeline",           "Show all leads by status — hot, warm, and new"),
        ("📊 Offer Statistics",        "Show deal statistics — acceptance rate and average deal value"),
        ("🔍 Investment Analysis",     "Get investment analysis for listing LST-2026-008 with ₹25,000/month rent"),
        ("⚠️  KYC Check",              "Check KYC verification status for buyer@realty.com"),
    ],
    "buyer": [
        ("🔍 Search Properties",       "Search for 3BHK apartments in Mumbai under ₹1.5 Crore"),
        ("🏠 My Recommendations",      "Show properties that match my preferences"),
        ("📅 Book Viewing",            "I want to book a viewing for listing LST-2026-001 this Saturday at 11am"),
        ("💬 Make Offer",              "I want to submit an offer of ₹1.1 Crore on listing LST-2026-001"),
        ("📊 Compare Properties",      "Compare properties LST-2026-001 and LST-2026-002"),
        ("❓ What is Stamp Duty",       "What is stamp duty and how is it calculated when buying a property in India?"),
    ],
    "seller": [
        ("🏠 My Listing Status",       "Show details for listing LST-2026-001"),
        ("📋 Offers on My Property",   "Show all offers on listing LST-2026-001"),
        ("📈 Market Valuation",        "What is the current market value for listing LST-2026-001?"),
        ("📄 Document Status",         "Show the document checklist and compliance status for LST-2026-001"),
        ("💰 Rental Yield",            "Calculate rental yield for LST-2026-001 if I rent it at ₹45,000/month"),
        ("❓ Sale Deed Explained",     "What is a sale deed and what does it contain?"),
    ],
}

AGENT_ICONS = {
    "Property Listing": "🏠", "Client & Lead": "👥",
    "Property Search": "🔍", "Viewing & Appointment": "📅",
    "Offer & Deal": "💰", "Document & Legal": "📄",
    "Market Analytics": "📈", "Direct Answering Agent": "❓",
}

AGENT_ACTION_HINTS = {
    "Property Listing": ["listing", "valuation", "status"],
    "Client & Lead": ["lead", "buyer", "register"],
    "Property Search": ["search", "recommend", "compare"],
    "Viewing & Appointment": ["viewing", "appointment", "book"],
    "Offer & Deal": ["offer", "deal", "pipeline"],
    "Document & Legal": ["document", "compliance", "kyc", "deed"],
    "Market Analytics": ["market", "analytics", "statistics", "analysis", "report"],
    "Direct Answering Agent": ["what is", "explained", "checklist", "help"],
}
