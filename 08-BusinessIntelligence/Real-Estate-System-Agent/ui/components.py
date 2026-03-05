# ui/components.py

import json
import html
import streamlit as st
from utils.auth import ROLE_LABELS, ROLE_COLORS, ROLE_AGENTS
from ui.api import _list_sessions, _load_session
from ui.utils import _new_thread_id, _history_to_chat, _set_quick_prompt, _set_selected_agent, _clear_selected_agent
from ui.constants import QUICK_ACTIONS, AGENT_ICONS, AGENT_ACTION_HINTS

def _sidebar(user: dict):
    role   = user["role"]
    color  = ROLE_COLORS.get(role, "#1b4f72")
    with st.sidebar:
        st.markdown(f"""
        <div style='padding:12px; background: var(--secondary-bg); border-radius:8px; margin-bottom:12px; border:1px solid var(--border-color); text-align:center'>
          <p style='margin:0; font-weight:700; font-size:15px; color: var(--text-color)'>{user['name']}</p>
          <p style='margin:2px 0; font-size:11px; color: var(--muted-text)'>{user['email']}</p>
          {'<p style="margin:2px 0; font-size:11px; color: var(--button-hover)">ID: ' + (user.get("agent_id") or user.get("client_id") or "") + '</p>' if (user.get("agent_id") or user.get("client_id")) else ''}
          {'<p style="margin:2px 0; font-size:11px; color: var(--muted-text)">' + (user.get("agency") or "") + '</p>' if user.get("agency") else ''}
          <span class='role-badge' style='background:{color}20;color:{color};border:1px solid {color}40'>{ROLE_LABELS.get(role, role)}</span>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("---")
        st.markdown("<p style='color: var(--muted-text); font-size:10px; font-weight:700; letter-spacing:1px; text-transform:uppercase; margin-bottom:8px'>Session Management</p>", unsafe_allow_html=True)
        user_key = f"{user['role']}:{user['email']}"
        sessions, redis_enabled = _list_sessions(user_key)
        st.session_state.redis_enabled = redis_enabled

        current_thread = st.session_state.get("thread_id", _new_thread_id(user))
        if current_thread not in sessions:
            sessions = [current_thread] + sessions
        else:
            sessions = [current_thread] + [s for s in sessions if s != current_thread]
        sessions = sessions[:50]

        selected = st.selectbox(
            "Saved Sessions",
            options=sessions if sessions else [current_thread],
        )

        # Auto-load a saved session as soon as it is selected.
        target = (selected or "").strip()
        if target and target != current_thread:
            loaded = _load_session(target)
            st.session_state.thread_id = target
            st.session_state.history = loaded.get("messages", []) or []
            st.session_state.chat = _history_to_chat(st.session_state.history)
            st.session_state.trace = []
            st.rerun()

        if st.button("New", use_container_width=True):
            st.session_state.thread_id = _new_thread_id(user)
            st.session_state.chat = []
            st.session_state.history = []
            st.session_state.trace = []
            st.rerun()

        session_input = st.text_input("Session ID", value=current_thread, key="session_id_input")
        if st.button("Use ID", use_container_width=True):
            target = (session_input or "").strip()
            if target:
                loaded = _load_session(target)
                st.session_state.thread_id = target
                st.session_state.history = loaded.get("messages", []) or []
                st.session_state.chat = _history_to_chat(st.session_state.history)
                st.session_state.trace = []
                st.rerun()

        st.caption(f"Current session: `{st.session_state.get('thread_id', current_thread)}`")
        if not redis_enabled:
            st.caption("Redis unavailable: using in-memory chat only.")
        st.markdown("---")
        st.markdown("<p style='color: var(--muted-text); font-size:10px; font-weight:700; letter-spacing:1px; text-transform:uppercase; margin-bottom:8px'>Quick Actions</p>", unsafe_allow_html=True)
        for label, prompt in QUICK_ACTIONS.get(role, []):
            st.button(
                label,
                key=f"qa_{label}",
                on_click=_set_quick_prompt,
                args=(prompt,),
            )
        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🗑️ Clear", use_container_width=True):
                st.session_state.chat = []
                st.session_state.history = []
                st.session_state.trace = []
                st.rerun()
        with c2:
            if st.button("🚪 Logout", use_container_width=True):
                st.session_state.clear()
                st.rerun()

def _header(user: dict):
    role  = user["role"]
    color = ROLE_COLORS.get(role, "#1b4f72")
    agency = f" | Agency: {user['agency']}" if user.get("agency") else ""
    thread_id = st.session_state.get("thread_id", "N/A")
    st.markdown(f"""
    <div class="header-card">
      <h1>🏠 PropTech Realty AI — Property & Real Estate Listing System</h1>
      <p>Logged in as <strong style="color: var(--header-text)">{user["name"]}</strong>
         &nbsp;|&nbsp; Role: <strong style="color: {color}">{ROLE_LABELS.get(role, role)}</strong>
         {agency}
         &nbsp;|&nbsp; Access: {len(ROLE_AGENTS.get(role,[]))} agents
         &nbsp;|&nbsp; Session: <strong style="color: var(--header-text)">{thread_id}</strong></p>
    </div>
    """, unsafe_allow_html=True)

def _agent_quick_actions(role: str, agent_name: str) -> list[tuple]:
    all_actions = QUICK_ACTIONS.get(role, [])
    hints = AGENT_ACTION_HINTS.get(agent_name, [])
    if not hints:
        return all_actions

    filtered = []
    for label, prompt in all_actions:
        text = f"{label} {prompt}".lower()
        if any(h in text for h in hints):
            filtered.append((label, prompt))
    return filtered or all_actions

def _agent_action_panel(user: dict):
    role = user["role"]
    agents = ROLE_AGENTS.get(role, [])
    if not agents:
        return

    selected_agent = st.session_state.get("selected_agent")
    st.markdown(
        f"<p style='color: var(--muted-text); font-size:11px; font-weight:700; letter-spacing:1px; text-transform:uppercase; margin:4px 0 10px'>Your Agents ({len(agents)})</p>",
        unsafe_allow_html=True,
    )

    if selected_agent:
        s1, s2 = st.columns([4, 1])
        with s1:
            st.markdown(f"**{AGENT_ICONS.get(selected_agent, 'Agent')} {selected_agent} Quick Actions**")
        with s2:
            st.button(
                "< Back",
                key="main_back_to_agents",
                use_container_width=True,
                on_click=_clear_selected_agent,
            )

        actions = _agent_quick_actions(role, selected_agent)
        cols = st.columns(2)
        for idx, (label, prompt) in enumerate(actions):
            with cols[idx % 2]:
                st.button(
                    label,
                    key=f"main_qa_{selected_agent}_{idx}",
                    use_container_width=True,
                    on_click=_set_quick_prompt,
                    args=(prompt,),
                )
        st.markdown("---")
        return

    card_cols = st.columns(4 if len(agents) >= 4 else max(1, len(agents)))
    for idx, agent_name in enumerate(agents):
        with card_cols[idx % len(card_cols)]:
            st.button(
                f"{AGENT_ICONS.get(agent_name, 'Agent')} {agent_name}",
                key=f"main_agent_card_{idx}",
                use_container_width=True,
                on_click=_set_selected_agent,
                args=(agent_name,),
            )
    st.markdown("---")

def _trace(trace: list, title: str | None = None, expanded: bool = False):
    if not trace:
        return

    routed_count = sum(
        1 for s in trace
        if s.get("type") == "tool_call" and "transfer_to_" in str(s.get("tool", ""))
    )
    tool_calls_count = sum(
        1 for s in trace
        if s.get("type") == "tool_call" and "transfer_to_" not in str(s.get("tool", ""))
    )
    tool_results_count = sum(1 for s in trace if s.get("type") == "tool_result")

    expander_title = title or f"Show Supervisor Routing Trace ({len(trace)} steps)"
    with st.expander(expander_title, expanded=expanded):
        st.markdown(
            f"""
            <div class="trace-summary">
              <span class="trace-chip">{routed_count} routed</span>
              <span class="trace-chip">{tool_calls_count} tool calls</span>
              <span class="trace-chip">{tool_results_count} tool results</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for idx, step in enumerate(trace, start=1):
            step_type = step.get("type", "")
            tool_name = str(step.get("tool", ""))
            label = html.escape(str(step.get("label", "")))

            if step_type == "tool_call" and "transfer_to_" in tool_name:
                kind = "route"
                heading = "ROUTE"
                subtitle = "agent selected"
            elif step_type == "tool_call":
                kind = "tool"
                heading = "TOOL CALLED"
                subtitle = "waiting for MCP response"
            elif step_type == "tool_result":
                kind = "result"
                heading = "MCP RESULT"
                subtitle = "response returned to agent"
            elif step_type == "reply":
                kind = "reply"
                heading = "FINAL REPLY"
                subtitle = "response returned to user"
            else:
                kind = "error"
                heading = "ERROR"
                subtitle = "error returned"

            st.markdown(
                f"""
                <div class="trace-step {kind}">
                  <div class="meta">Step {idx} &nbsp;&nbsp; {heading}</div>
                  <div class="title">{label}</div>
                  <div class="sub">{subtitle}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.expander("View raw details", expanded=False):
                st.code(json.dumps(step, indent=2), language="json")
