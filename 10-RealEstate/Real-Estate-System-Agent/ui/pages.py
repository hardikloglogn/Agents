# ui/pages.py

import streamlit as st
from utils.auth import authenticate, ROLE_LABELS
from ui.styles import _CSS
from ui.utils import _new_thread_id, _set_quick_prompt
from ui.api import _call_supervisor
from ui.components import _sidebar, _header, _agent_action_panel, _trace

def _login_page():
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown("""
    <div style='text-align:center;padding:28px 0 8px'>
      <h1 style='color: var(--text-color); font-size:36px; margin-bottom:4px'>🏠 PropTech Realty AI</h1>
      <p style='color: var(--muted-text); font-size:15px'>Property & Real Estate Listing Agent System</p>
    </div>
    """, unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown('<div class="login-box">', unsafe_allow_html=True)
        st.markdown('<p style="text-align:center; color: var(--button-hover); font-size:18px; font-weight:700; margin-bottom:20px">Sign In to Your Portal</p>', unsafe_allow_html=True)
        with st.form("login"):
            email    = st.text_input("Email Address", placeholder="agent@realty.com")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("Sign In →")
            if submitted:
                if not email or not password:
                    st.error("Please enter email and password.")
                else:
                    user = authenticate(email, password)
                    if user:
                        st.session_state.user    = user
                        st.session_state.chat    = []
                        st.session_state.history = []
                        st.session_state.trace   = []
                        st.session_state.thread_id = _new_thread_id(user)
                        st.session_state.redis_enabled = False
                        st.rerun()
                    else:
                        st.error("❌ Invalid credentials. Please try again.")
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("🔑 Demo Credentials", expanded=False):
        st.markdown("""
| Role | Email | Password | Access |
|------|-------|----------|--------|
| 🛡️ Admin | `admin@realty.com` | admin123 | All 7 agents + General |
| 🏠 Realtor | `agent@realty.com` | agent123 | All 7 agents + General |
| 💼 Broker | `manager@realty.com` | mgr123 | All 7 agents + General |
| 🔍 Buyer | `buyer@realty.com` | buy123 | Search + Viewing + Offer + General |
| 🏷️ Seller | `seller@realty.com` | sell123 | Listing + Offer + Document + Analytics + General |
        """)

def _chat_page(user: dict):
    st.markdown(_CSS, unsafe_allow_html=True)
    for k in ("chat", "history", "trace"):
        if k not in st.session_state: st.session_state[k] = []
    if "thread_id" not in st.session_state or not st.session_state.thread_id:
        st.session_state.thread_id = _new_thread_id(user)
    _sidebar(user)
    _header(user)
    _agent_action_panel(user)
    for idx, msg in enumerate(st.session_state.chat, start=1):
        with st.chat_message(msg["role"], avatar="👤" if msg["role"] == "user" else "🏠"):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and msg.get("trace"):
                _trace(
                    msg["trace"],
                    title=f"Show Supervisor Routing Trace ({len(msg['trace'])} steps) · Msg {idx}",
                    expanded=False,
                )
    default = st.session_state.pop("quick_prompt", None)
    user_input = st.chat_input("Ask about properties, listings, viewings, offers, documents…") or default
    if user_input:
        st.session_state.chat.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)
        enriched = (
            f"[User: {user['name']} | Role: {user['role']} | Email: {user['email']}"
            + (f" | AgentID: {user['agent_id']}" if user.get("agent_id") else "")
            + (f" | ClientID: {user['client_id']}" if user.get("client_id") else "")
            + f"]\n\n{user_input}"
        )
        st.session_state.history.append({"role": "human", "content": enriched})
        with st.chat_message("assistant", avatar="🏠"):
            with st.spinner("Processing…"):
                result = _call_supervisor(
                    st.session_state.history,
                    st.session_state.thread_id,
                    f"{user['role']}:{user['email']}",
                    user_input,
                )
            reply = result.get("final_reply", "⚠️ No response received.")
            full_trace = result.get("trace", []) or []
            msg_trace = full_trace
            st.markdown(reply)
            if msg_trace:
                _trace(
                    msg_trace,
                    title=f"Show Supervisor Routing Trace ({len(msg_trace)} steps)",
                    expanded=False,
                )
        st.session_state.chat.append({
            "role": "assistant",
            "content": reply,
            "trace": msg_trace,
        })
        st.session_state.history.append({"role": "ai", "content": reply})
        st.session_state.trace = full_trace
        if result.get("messages"):
            st.session_state.history = result["messages"]
