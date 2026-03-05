import streamlit as st


QUICK_ACTIONS = [
    "Scan dependencies for https://github.com/Log-LogN/ask-db",
    "Explain GHSA-j288-q9x7-2f5v",
    "Check vulnerabilities for next@15.0.8",
]

DEFAULT_OPENAI_MODELS = [
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o-mini",
]


def render_sidebar(
    current_session_id: str,
    current_openai_model: str,
    current_openai_api_key: str,
    widget_nonce: int = 0,
    input_nonce: int = 0,
) -> dict:
    state = {
        "load_session": False,
        "new_session": False,
        "session_input": "",
        "quick_action": None,
        "apply_openai_settings": False,
        "reset_openai_settings": False,
        "openai_model": current_openai_model,
        "openai_api_key": current_openai_api_key,
    }

    with st.sidebar:
        st.markdown("### Control Center")
        if current_session_id:
            st.markdown(
                f"<div class='session-badge'>Active Session: <code>{current_session_id}</code></div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("No active session")

        st.markdown("#### &#9881; Settings", unsafe_allow_html=True)
        with st.expander("Session Controls", expanded=False):
            session_input_key = f"session_input_{input_nonce}"
            session_input = st.text_input(
                "Load Session ID",
                value="",
                key=session_input_key,
                placeholder="Enter session ID to load",
            )
            new_session = st.button("New Session", use_container_width=True)

            # Auto-load session when input is not empty and differs from current session
            if session_input and session_input.strip() and session_input.strip() != current_session_id:
                state["session_input"] = session_input.strip()
                state["load_session"] = True

            state["new_session"] = new_session

        with st.expander("OpenAI Settings", expanded=False):
            model_options = list(DEFAULT_OPENAI_MODELS)
            if current_openai_model and current_openai_model not in model_options:
                model_options.append(current_openai_model)

            default_idx = model_options.index(current_openai_model) if current_openai_model in model_options else 0
            model_widget_key = f"openai_model_select_{widget_nonce}"
            key_widget_key = f"openai_api_key_input_{widget_nonce}"
            selected_model = st.selectbox(
                "OpenAI Model",
                options=model_options,
                index=default_idx,
                key=model_widget_key,
            )
            entered_api_key = st.text_input(
                "OpenAI API Key",
                value=current_openai_api_key,
                type="password",
                key=key_widget_key,
                placeholder="sk-...",
            )
            if not (entered_api_key or "").strip():
                st.caption("OpenAI API key is required before sending a chat message.")
            apply_openai_settings = st.button("Apply OpenAI Settings", use_container_width=True)
            reset_openai_settings = st.button("Reset OpenAI Settings", use_container_width=True)

            state["openai_model"] = selected_model
            state["openai_api_key"] = entered_api_key
            state["apply_openai_settings"] = apply_openai_settings
            state["reset_openai_settings"] = reset_openai_settings

        st.markdown("<div class='section-title'>Quick Actions</div>", unsafe_allow_html=True)
        for idx, action in enumerate(QUICK_ACTIONS):
            if st.button(action, key=f"qa_{idx}", use_container_width=True):
                state["quick_action"] = action

    return state
