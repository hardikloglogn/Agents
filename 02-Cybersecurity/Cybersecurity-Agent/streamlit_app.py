import streamlit as st
import requests
import uuid
import time
import json
from streamlit_ui.styles import inject_custom_styles
from streamlit_ui.sidebar import render_sidebar
from streamlit_ui.chat import (
    render_chat_history,
    render_header,
    render_download_button_topright,
    upload_manifest_file,
)
from shared.config import settings

# API Configuration
API_BASE = "http://localhost:9000"
API_REQUEST_TIMEOUT_SECONDS = 300


def build_chat_history_with_traces(history: list[dict], artifacts: list[dict]) -> list[dict]:
    merged_history = []
    ai_idx = 0
    for msg in history:
        entry = {"role": msg["type"], "content": msg["content"]}
        if msg["type"] == "ai":
            artifact = artifacts[ai_idx] if ai_idx < len(artifacts) else {}
            entry["trace"] = {
                "agent_used": artifact.get("intent", ""),
                "tool_calls": artifact.get("tool_calls", []),
            }
            ai_idx += 1
        merged_history.append(entry)
    return merged_history


def load_history(session_id: str) -> None:
    try:
        response = requests.get(f"{API_BASE}/chat/history/{session_id}")
        if response.status_code == 200:
            data = response.json()
            history = data["history"]
            artifacts = []
            try:
                artifacts_response = requests.get(f"{API_BASE}/chat/artifacts/{session_id}")
                if artifacts_response.status_code == 200:
                    artifacts = artifacts_response.json().get("artifacts", [])
            except Exception:
                artifacts = []
            st.session_state.chat_history = build_chat_history_with_traces(history, artifacts)
            st.query_params["session_id"] = session_id
            st.success(f"Session set to: {session_id}")
        else:
            st.session_state.chat_history = []
            st.query_params["session_id"] = session_id
            st.error("Session not found, starting new")
    except Exception as e:
        st.session_state.chat_history = []
        st.query_params["session_id"] = session_id
        st.error(f"Error loading history: {str(e)}")


def load_session_settings(session_id: str) -> None:
    try:
        response = requests.get(f"{API_BASE}/chat/settings/{session_id}", timeout=15)
        if response.status_code == 200:
            data = response.json()
            st.session_state.openai_model = data.get("openai_model") or settings.OPENAI_MODEL
            loaded_key = (data.get("openai_api_key", "") or "").strip()
            if loaded_key:
                st.session_state.openai_api_key = loaded_key
        else:
            st.session_state.openai_model = st.session_state.openai_model or settings.OPENAI_MODEL
    except Exception as e:
        st.error(f"Error loading session settings: {str(e)}")


def save_session_settings(session_id: str) -> None:
    payload = {
        "openai_model": st.session_state.openai_model,
        "openai_api_key": st.session_state.openai_api_key,
    }
    try:
        response = requests.post(
            f"{API_BASE}/chat/settings/{session_id}",
            json=payload,
            timeout=15,
        )
        if response.status_code != 200:
            st.error(f"Failed to save OpenAI settings: {response.status_code} - {response.text}")
    except Exception as e:
        st.error(f"Error saving OpenAI settings: {str(e)}")


def process_user_prompt(prompt: str, chat_container) -> None:
    if not st.session_state.session_id:
        st.error("Please set a session first")
        return
    if not (st.session_state.openai_api_key or "").strip():
        st.error("OpenAI API key is empty. Set it in Sidebar > Settings > OpenAI Settings.")
        return

    st.session_state.chat_history.append({"role": "human", "content": prompt})
    with chat_container:
        st.chat_message("user").write(prompt)

    loading_messages = [
        "Supervisor is analyzing your request...",
        "Coordinating specialized agents...",
        "Gathering findings and preparing response...",
    ]

    payload = {
        "message": prompt,
        "session_id": st.session_state.session_id,
        "openai_model": st.session_state.openai_model,
        "openai_api_key": st.session_state.openai_api_key,
    }

    try:
        with chat_container:
            with st.chat_message("assistant"):
                loading_placeholder = st.empty()
                for msg in loading_messages:
                    loading_placeholder.markdown(f":hourglass_flowing_sand: {msg}")
                    time.sleep(0.25)
                
                response = requests.post(
                    f"{API_BASE}/chat",
                    json=payload,
                    timeout=API_REQUEST_TIMEOUT_SECONDS,
                )
                
                if response.status_code == 200:
                    data = response.json()
                    agent_response = data["output"]
                    st.session_state.chat_history.append({
                        "role": "ai",
                        "content": agent_response,
                        "trace": {
                            "agent_used": data.get("agent_used", ""),
                            "tool_calls": data.get("tool_calls", []),
                        },
                    })
                    loading_placeholder.write(agent_response)
                    st.rerun()
                else:
                    loading_placeholder.empty()
                    st.error(f"API Error: {response.status_code} - {response.text}")
    except Exception as e:
        st.error(f"Request failed: {str(e)}")


def main():
    st.set_page_config(page_title="Cybersecurity Agent Chat", layout="wide")
    inject_custom_styles()
    render_header()

    # Initialize session state
    if "session_id" not in st.session_state:
        existing_session_from_url = st.query_params.get("session_id")
        st.session_state.session_id = existing_session_from_url or str(uuid.uuid4())
        st.query_params["session_id"] = st.session_state.session_id

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "openai_model" not in st.session_state:
        st.session_state.openai_model = settings.OPENAI_MODEL
    if "openai_api_key" not in st.session_state:
        st.session_state.openai_api_key = ""
    if "openai_widget_nonce" not in st.session_state:
        st.session_state.openai_widget_nonce = 0
    if "last_uploaded_file" not in st.session_state:
        st.session_state.last_uploaded_file = None
    if "last_loaded_session_input" not in st.session_state:
        st.session_state.last_loaded_session_input = None
    if "session_input_nonce" not in st.session_state:
        st.session_state.session_input_nonce = 0
    if "session_history_loaded" not in st.session_state:
        st.session_state.session_history_loaded = False
    if "openai_settings_loaded" not in st.session_state:
        st.session_state.openai_settings_loaded = False

    # Load chat history and settings on page refresh (from URL session_id)
    if not st.session_state.session_history_loaded:
        load_session_settings(st.session_state.session_id)
        load_history(st.session_state.session_id)
        st.session_state.openai_settings_loaded = True
        st.session_state.session_history_loaded = True

    # Sidebar
    sidebar_state = render_sidebar(
        st.session_state.session_id,
        st.session_state.openai_model,
        st.session_state.openai_api_key,
        widget_nonce=st.session_state.openai_widget_nonce,
        input_nonce=st.session_state.session_input_nonce,
    )

    # Initialize tracking for session loading to prevent infinite loops
    if "last_loaded_session_input" not in st.session_state:
        st.session_state.last_loaded_session_input = None

    # Sidebar Actions - Auto-load session when input is provided
    if sidebar_state["load_session"] and sidebar_state["session_input"]:
        # Only load if this is a new session input (different from last time)
        if sidebar_state["session_input"] != st.session_state.last_loaded_session_input:
            st.session_state.session_id = sidebar_state["session_input"]
            st.session_state.last_loaded_session_input = sidebar_state["session_input"]
            st.session_state.session_history_loaded = False  # Reset flag to reload on next render
            load_history(sidebar_state["session_input"])
            load_session_settings(sidebar_state["session_input"])
            st.session_state.session_history_loaded = True
            st.session_state.openai_widget_nonce += 1
            st.session_state.session_input_nonce += 1  # Clear input field
            st.rerun()

    if sidebar_state["new_session"]:
        new_session = str(uuid.uuid4())
        current_model = st.session_state.openai_model
        current_api_key = st.session_state.openai_api_key
        st.session_state.session_id = new_session
        st.session_state.chat_history = []
        st.session_state.openai_model = current_model
        st.session_state.openai_api_key = current_api_key
        st.session_state.session_history_loaded = True  # New session has no history to load
        st.query_params["session_id"] = new_session
        save_session_settings(new_session)
        st.session_state.openai_widget_nonce += 1
        st.rerun()

    if sidebar_state["apply_openai_settings"]:
        st.session_state.openai_model = sidebar_state["openai_model"]
        st.session_state.openai_api_key = sidebar_state["openai_api_key"]
        save_session_settings(st.session_state.session_id)
        st.success(f"OpenAI settings updated: model={st.session_state.openai_model}")
        st.rerun()

    if sidebar_state["reset_openai_settings"]:
        st.session_state.openai_model = settings.OPENAI_MODEL
        st.session_state.openai_api_key = ""
        save_session_settings(st.session_state.session_id)
        st.success(f"OpenAI settings reset to defaults")
        st.session_state.openai_widget_nonce += 1
        st.rerun()

    # Render download button in top right corner
    render_download_button_topright(
        session_id=st.session_state.session_id,
        chat_history=st.session_state.chat_history,
        api_base=API_BASE
    )

    # Main Chat View
    chat_container = st.container()
    with chat_container:
        render_chat_history(st.session_state.chat_history)

    # Quick Actions
    if sidebar_state["quick_action"]:
        process_user_prompt(sidebar_state["quick_action"], chat_container)

    # Input Section (File Uploader + Chat Input)
    uploaded_file = st.file_uploader(
        "Upload Manifest File", type=["txt", "json", "xml", "gradle", "yaml", "yml"], key="manifest_uploader"
    )
    prompt = st.chat_input("Type your message...")

    if uploaded_file:
        if not (st.session_state.openai_api_key or "").strip():
            st.error("❌ OpenAI API key is required to analyze manifest files. Set it in Sidebar > Settings > OpenAI Settings.")
            st.session_state.last_uploaded_file = None
        else:
            file_key = f"{uploaded_file.name}_{uploaded_file.size}"
            if st.session_state.last_uploaded_file != file_key:
                st.session_state.last_uploaded_file = file_key
                with st.spinner(f"📌 Analyzing {uploaded_file.name}..."):
                    scan_result = upload_manifest_file(uploaded_file, API_BASE, st.session_state.session_id)
                    if scan_result:
                        manifest_info = f"📁 **Manifest Uploaded**: {uploaded_file.name}\n\n**Scan Summary:**\n{scan_result.get('summary', 'Scanning dependency manifest...')}"
                        st.session_state.chat_history.append({"role": "human", "content": manifest_info})
                        
                        scan_data = scan_result.get('scan', {})
                        scan_display = json.dumps(scan_data, indent=2) if isinstance(scan_data, dict) else str(scan_data)
                        st.session_state.chat_history.append({
                            "role": "ai",
                            "content": f"✅ I've analyzed **{uploaded_file.name}**.\n\n**Findings:**\n\n```json\n{scan_display}\n```",
                            "trace": {
                                "agent_used": "Dependency Scanner",
                                "tool_calls": scan_result.get("tool_calls", []),
                            }
                        })
                        st.rerun()
            else:
                st.session_state.last_uploaded_file = None

    if prompt:
        process_user_prompt(prompt, chat_container)


if __name__ == "__main__":
    main()