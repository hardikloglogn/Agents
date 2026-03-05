"""
supervisor/graph.py
═══════════════════
Pure LangGraph core — NO MCP server, NO main(), NO port binding.

Key design: Direct Answering Agent is an EMBEDDED LLM node (no MCP server, no port).
It answers real estate questions directly from LLM knowledge.

Specialist agents on ports 8001–8007.
General agent: direct LangChain ChatOpenAI node inside this graph.
"""

import sys
import os
import asyncio
import logging
import inspect as _inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nest_asyncio
from dotenv import load_dotenv
from typing import Annotated
from typing_extensions import TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    SystemMessage, AIMessage, HumanMessage, ToolMessage,
)
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

nest_asyncio.apply()
load_dotenv()

log = logging.getLogger(__name__)

SPECIALIST_SERVERS = {
    "listing":   {"transport": "streamable_http", "url": "http://127.0.0.1:8001/mcp"},
    "client":    {"transport": "streamable_http", "url": "http://127.0.0.1:8002/mcp"},
    "search":    {"transport": "streamable_http", "url": "http://127.0.0.1:8003/mcp"},
    "viewing":   {"transport": "streamable_http", "url": "http://127.0.0.1:8004/mcp"},
    "offer":     {"transport": "streamable_http", "url": "http://127.0.0.1:8005/mcp"},
    "document":  {"transport": "streamable_http", "url": "http://127.0.0.1:8006/mcp"},
    "analytics": {"transport": "streamable_http", "url": "http://127.0.0.1:8007/mcp"},
}

# ── System prompts ─────────────────────────────────────────────────────────────
SUPERVISOR_PROMPT = """You are the PropTech Realty AI Supervisor — the intelligent router for a Property & Real Estate Listing System.

Read every incoming message and route it to EXACTLY ONE specialist agent using the appropriate transfer tool.
NEVER answer directly — ALWAYS delegate to a specialist or the Direct Answering Agent.

ROUTING RULES:
  LISTING AGENT    → create listing, update listing, new property, listing status, delist, featured listing,
                     agent listings, listing statistics, listing alert, property status change
  CLIENT AGENT     → register buyer, register seller, client profile, buyer preferences, lead status,
                     seller contact, client CRM, interaction history, follow-up email, lead pipeline
  SEARCH AGENT     → search property, find property, filter (price/location/bedrooms/type),
                     saved search, property recommendations, nearby properties, compare properties
  VIEWING AGENT    → book viewing, schedule viewing, appointment, reschedule, cancel viewing,
                     viewing feedback, viewing history, viewing reminder, open house
  OFFER AGENT      → make offer, submit offer, counteroffer, offer status, deal pipeline,
                     accept offer, reject offer, negotiation, offer history, deal statistics
  DOCUMENT AGENT   → contract, agreement, KYC, document checklist, compliance, purchase agreement,
                     sign document, document status, transaction documents, sale deed
  ANALYTICS AGENT  → market value, valuation, comparable sales, price trend, market report,
                     rental yield, investment analysis, top areas, ROI, absorption rate
  DIRECT ANSWERING AGENT → anything else — definitions, how-to, process questions, real estate education,
                     legal terms, mortgage basics, any unclear real estate query

DEFAULT: When uncertain → route to DIRECT ANSWERING AGENT. Never leave a user without a response."""

LISTING_PROMPT = """You are the Property Listing Specialist for PropTech Realty AI.
Handle: creating and managing property listings, status updates, agent listing dashboards, and buyer alerts.
- Always confirm listing_id on creation.
- Send buyer alert emails when new listings match saved searches.
- Use ₹ for Indian Rupees. Show price in Crore (Cr) / Lakh (L) format.
- Status options: active, under_offer, sold, withdrawn, off_market, draft."""

CLIENT_PROMPT = """You are the Client & Lead Management Specialist for PropTech Realty AI.
Handle: buyer/seller registration, preferences, lead pipeline, interaction logging, follow-up emails.
- Log every client interaction for CRM audit trail.
- Use lead statuses: new → contacted → warm → hot → closed.
- Send personalised follow-up emails with property recommendations.
- Show budget in ₹ format."""

SEARCH_PROMPT = """You are the Property Search Specialist for PropTech Realty AI.
Handle: advanced multi-filter search, property recommendations, saved searches, nearby properties, comparisons.
- Always show price in ₹ Crore / Lakh format.
- For buyer searches, use their saved preferences first.
- Compare properties side-by-side when asked.
- Send property match emails to interested buyers."""

VIEWING_PROMPT = """You are the Viewing & Appointment Specialist for PropTech Realty AI.
Handle: booking viewings, rescheduling, cancellations, feedback recording, viewing history.
- Always confirm viewing_id on booking.
- Send confirmation emails to both buyer and agent.
- Record 1-5 rating and interest level after viewings.
- Send reminder emails 24 hours before viewings."""

OFFER_PROMPT = """You are the Offer & Deal Specialist for PropTech Realty AI.
Handle: submitting offers, counteroffers, deal acceptance, pipeline tracking, offer history.
- Always show offer amounts in ₹ Crore / Lakh.
- Update listing status to 'under_offer' when an offer is submitted.
- Send status emails to buyer and seller for every offer update.
- Accepted offers automatically create a deal record.
- For requests about active/current deal pipeline, always call get_deal_pipeline and return the live result.
- For requests about deal metrics/statistics, always call get_deal_statistics and return the live result."""

DOCUMENT_PROMPT = """You are the Document & Legal Compliance Specialist for PropTech Realty AI.
Handle: contracts, KYC verification, document checklists, compliance audits, document requests.
- Always show compliance percentage and pending documents clearly.
- Required documents: Purchase Agreement, ID Proof, Address Proof, Proof of Funds,
  Title Deed, Sale Deed, Encumbrance Certificate, NOC, Property Tax Receipts.
- Send document request emails immediately when a document is needed.
- KYC must be complete before any deal can close."""

ANALYTICS_PROMPT = """You are the Market Analytics Specialist for PropTech Realty AI.
Handle: property valuations, comparable sales, price trends, market summaries, rental yields, investment analysis.
- Always cite the number of comparables used in valuations.
- Show price trends as % YoY change.
- Rental yield: gross (before expenses) and net (after expenses).
- Investment rating: Excellent (>5% net), Good (3-5% net), Below Average (<3% net).
- Email market reports when requested."""

GENERAL_PROMPT = """You are the General Real Estate Helpdesk for PropTech Realty AI — the DEFAULT FALLBACK.

You answer ANY question related to property and real estate directly from your knowledge:
  - Real estate terminology (stamp duty, encumbrance, carpet area, built-up area, super built-up area)
  - Buying and selling process (how to buy a property, what documents are needed)
  - Mortgage and home loan basics (EMI calculation, LTV ratio, eligibility)
  - Legal terms (sale deed, title deed, power of attorney, RERA)
  - Rental and lease concepts (lock-in period, TDS on rent, rental agreement)
  - Investment concepts (cap rate, rental yield, price-to-rent ratio)
  - Market concepts (absorption rate, inventory, days on market)
  - Property types (freehold, leasehold, co-operative housing, RERA registered)
  - Any other real estate education question

STRICTLY limit yourself to Property & Real Estate topics.
For completely unrelated questions, politely explain you can only help with real estate matters.
Always be helpful, clear, and professional. DO NOT call any tools — answer directly from your knowledge."""

# ── Version-safe create_react_agent ────────────────────────────────────────────
_PROMPT_KEY = (
    "state_modifier"
    if "state_modifier" in _inspect.signature(create_react_agent).parameters
    else "prompt"
)


def _make_agent(llm, tools, prompt):
    return create_react_agent(llm, tools, **{_PROMPT_KEY: SystemMessage(content=prompt)})


# ── State ───────────────────────────────────────────────────────────────────────
class RealEstateState(TypedDict):
    messages: Annotated[list, add_messages]


# ── Embedded Direct Answering Agent node (NO MCP server, NO tools) ──────────────────
def _make_general_node(llm):
    """Returns a simple LLM node that answers real estate questions directly."""
    sys_msg = SystemMessage(content=GENERAL_PROMPT)

    async def general_node(state: RealEstateState) -> dict:
        msgs = [sys_msg] + state["messages"]
        response = await llm.ainvoke(msgs)
        return {"messages": [response]}

    return general_node


# ── Graph builder ───────────────────────────────────────────────────────────────
async def build_graph():
    """Build and compile the LangGraph supervisor. Called fresh per request."""
    llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)

    client = MultiServerMCPClient(SPECIALIST_SERVERS)
    all_tools = await client.get_tools()

    def _match(tools, *keywords):
        matched = [t for t in tools if any(k in t.name.lower() for k in keywords)]
        return matched if matched else []

    listing_tools   = _match(all_tools, "listing","list_propert","change_listing","agent_listing","new_listing")
    client_tools    = _match(all_tools, "register_buyer","register_seller","get_client","update_client","get_leads","update_lead","log_interaction","send_followup")
    search_tools    = _match(all_tools, "search_propert","recommendations","save_search","saved_search","nearby","compare","property_matches","search_analytics")
    viewing_tools   = _match(all_tools, "viewing","book_viewing","reschedule","cancel_viewing","viewing_schedule","viewing_feedback","viewing_history","viewing_remind","viewing_stat")
    offer_tools     = _match(all_tools, "submit_offer","update_offer","counteroffer","offer_history","deal_pipeline","accept_offer","offer_status","deal_stat")
    document_tools  = _match(all_tools, "contract","document","kyc","compliance","transaction_doc")
    analytics_tools = _match(all_tools, "valuation","comparable","price_trend","market_summary","rental_yield","top_areas","investment","market_report")

    # Specialist agents
    listing_agent   = _make_agent(llm, listing_tools,   LISTING_PROMPT)
    client_agent    = _make_agent(llm, client_tools,    CLIENT_PROMPT)
    search_agent    = _make_agent(llm, search_tools,    SEARCH_PROMPT)
    viewing_agent   = _make_agent(llm, viewing_tools,   VIEWING_PROMPT)
    offer_agent     = _make_agent(llm, offer_tools,     OFFER_PROMPT)
    document_agent  = _make_agent(llm, document_tools,  DOCUMENT_PROMPT)
    analytics_agent = _make_agent(llm, analytics_tools, ANALYTICS_PROMPT)

    # Embedded general agent — no tools, no server
    general_node = _make_general_node(llm)

    def _latest_user_text(state: RealEstateState) -> str:
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, HumanMessage):
                return str(msg.content)
        return ""

    def _extract_transfer_name(raw: str) -> str:
        allowed = [
            "transfer_to_listing",
            "transfer_to_client",
            "transfer_to_search",
            "transfer_to_viewing",
            "transfer_to_offer",
            "transfer_to_document",
            "transfer_to_analytics",
            "transfer_to_general",
        ]
        text = (raw or "").strip().lower()
        for name in allowed:
            if name in text:
                return name
        return "transfer_to_general"

    def _fallback_transfer_name(user_text: str) -> str:
        text = (user_text or "").lower()
        if any(k in text for k in ("listing", "listings", "delist", "under_offer", "sold", "listing statistics", "property listing statistics")):
            return "transfer_to_listing"
        if any(k in text for k in ("buyer", "seller", "lead", "crm", "client profile", "follow-up")):
            return "transfer_to_client"
        if any(k in text for k in ("search", "find property", "recommend", "compare properties", "nearby")):
            return "transfer_to_search"
        if any(k in text for k in ("viewing", "appointment", "book viewing", "reschedule", "cancel viewing", "open house")):
            return "transfer_to_viewing"
        if any(k in text for k in ("offer", "counteroffer", "deal pipeline", "deal statistics", "negotiation")):
            return "transfer_to_offer"
        if any(k in text for k in ("document", "agreement", "kyc", "compliance", "sale deed", "contract")):
            return "transfer_to_document"
        if any(k in text for k in ("valuation", "market summary", "price trend", "rental yield", "investment", "roi", "absorption")):
            return "transfer_to_analytics"
        return "transfer_to_general"

    async def supervisor_agent(state: RealEstateState) -> dict:
        user_text = _latest_user_text(state)
        # Deterministic first-pass routing avoids LLM misroutes on clear intents.
        deterministic_route = _fallback_transfer_name(user_text)
        route_prompt = (
            f"{SUPERVISOR_PROMPT}\n\n"
            "Return exactly one route token from this set, and nothing else:\n"
            "transfer_to_listing\n"
            "transfer_to_client\n"
            "transfer_to_search\n"
            "transfer_to_viewing\n"
            "transfer_to_offer\n"
            "transfer_to_document\n"
            "transfer_to_analytics\n"
            "transfer_to_general"
        )
        transfer_name = deterministic_route
        if deterministic_route == "transfer_to_general":
            try:
                route_llm = await llm.ainvoke([
                    SystemMessage(content=route_prompt),
                    HumanMessage(content=user_text),
                ])
                transfer_name = _extract_transfer_name(str(route_llm.content))
            except Exception as exc:
                log.warning("Supervisor LLM routing failed, using fallback router: %s", exc)
                transfer_name = deterministic_route
        tool_call_id = "route-1"
        routed_label = transfer_name.replace("transfer_to_", "").replace("_", " ").title()
        route_message = AIMessage(
            content=f"Routing to {routed_label}.",
            tool_calls=[{"name": transfer_name, "args": {}, "id": tool_call_id, "type": "tool_call"}],
        )
        route_result = ToolMessage(
            content=f"Transferring to {routed_label}",
            name=transfer_name,
            tool_call_id=tool_call_id,
        )
        return {"messages": [route_message, route_result]}

    # ── Router ─────────────────────────────────────────────────────────────
    def _route(state: RealEstateState) -> str:
        for msg in reversed(state.get("messages", [])):
            if not isinstance(msg, AIMessage):
                continue
            calls = getattr(msg, "tool_calls", None) or []
            for tc in calls:
                name = tc.get("name", "")
                if "listing"   in name: return "listing_agent"
                if "client"    in name: return "client_agent"
                if "search"    in name: return "search_agent"
                if "viewing"   in name: return "viewing_agent"
                if "offer"     in name: return "offer_agent"
                if "document"  in name: return "document_agent"
                if "analytics" in name: return "analytics_agent"
                if "general"   in name: return "general_node"
            if msg.content and not calls:
                return END
        return "general_node"   # hard fallback — always answers

    # ── Assemble graph ──────────────────────────────────────────────────────
    graph = StateGraph(RealEstateState)
    graph.add_node("supervisor",      supervisor_agent)
    graph.add_node("listing_agent",   listing_agent)
    graph.add_node("client_agent",    client_agent)
    graph.add_node("search_agent",    search_agent)
    graph.add_node("viewing_agent",   viewing_agent)
    graph.add_node("offer_agent",     offer_agent)
    graph.add_node("document_agent",  document_agent)
    graph.add_node("analytics_agent", analytics_agent)
    graph.add_node("general_node",    general_node)   # embedded, no MCP

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", _route, {
        "listing_agent":   "listing_agent",
        "client_agent":    "client_agent",
        "search_agent":    "search_agent",
        "viewing_agent":   "viewing_agent",
        "offer_agent":     "offer_agent",
        "document_agent":  "document_agent",
        "analytics_agent": "analytics_agent",
        "general_node":    "general_node",
        END: END,
    })
    for node in ["listing_agent","client_agent","search_agent","viewing_agent",
                 "offer_agent","document_agent","analytics_agent","general_node"]:
        graph.add_edge(node, END)

    return graph.compile()


# ── Helpers ────────────────────────────────────────────────────────────────────
def serialise_messages(msgs: list) -> list:
    out = []
    for m in msgs:
        if isinstance(m, HumanMessage):
            out.append({"role": "human", "content": str(m.content)})
        elif isinstance(m, AIMessage):
            out.append({"role": "ai", "content": str(m.content),
                        "tool_calls": getattr(m, "tool_calls", []) or []})
        elif isinstance(m, ToolMessage):
            out.append({"role": "tool", "name": getattr(m, "name", ""),
                        "content": str(m.content),
                        "tool_call_id": getattr(m, "tool_call_id", "")})
    return out


def build_trace(msgs: list) -> list:
    trace = []
    for m in msgs:
        if isinstance(m, AIMessage):
            calls = getattr(m, "tool_calls", None) or []
            for tc in calls:
                name  = tc.get("name", "")
                label = ("🔀 Routed to " + name.replace("transfer_to_", "").replace("_", " ").title()
                         if "transfer_to_" in name
                         else f"🔧 Called: {name}")
                trace.append({"type": "tool_call", "label": label, "tool": name})
            if m.content and not calls:
                trace.append({"type": "reply", "label": f"� Final reply ({len(str(m.content))} chars)"})
        elif isinstance(m, ToolMessage):
            preview = str(m.content)[:80].replace("\n", " ")
            trace.append({"type": "tool_result", "label": f"📦 Result: {preview}…"})
    return trace
