import streamlit as st
import requests
import json
import time
from shared.dependency_scan import canonicalize_manifest_type, supported_manifest_types

# API base URL
API_BASE = "http://localhost:9000"

st.title("Cybersecurity Agent Chat")

# Initialize session state
if "session_id" not in st.session_state:
    st.session_state.session_id = ""

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Check query params for session_id on load
query_params = st.query_params
if "session_id" in query_params and not st.session_state.session_id:
    st.session_state.session_id = query_params["session_id"]
    # Load history
    try:
        response = requests.get(f"{API_BASE}/chat/history/{st.session_state.session_id}")
        if response.status_code == 200:
            data = response.json()
            history = data["history"]
            st.session_state.chat_history = [{"role": msg["type"], "content": msg["content"]} for msg in history]
    except:
        pass

# Sidebar for session
with st.sidebar:
    st.header("Session Management")
    session_input = st.text_input("Session ID", value=st.session_state.session_id, key="session_input")
    if st.button("Set Session"):
        st.session_state.session_id = session_input
        # Load history from API
        try:
            response = requests.get(f"{API_BASE}/chat/history/{session_input}")
            if response.status_code == 200:
                data = response.json()
                history = data["history"]
                st.session_state.chat_history = [{"role": msg["type"], "content": msg["content"]} for msg in history]
                st.query_params["session_id"] = session_input
                st.success(f"Session set to: {session_input}")
            else:
                st.session_state.chat_history = []
                st.query_params["session_id"] = session_input
                st.error("Session not found, starting new")
        except Exception as e:
            st.session_state.chat_history = []
            st.query_params["session_id"] = session_input
            st.error(f"Error loading history: {str(e)}")

    if st.button("New Session"):
        import uuid
        new_session = str(uuid.uuid4())
        st.session_state.session_id = new_session
        st.session_state.chat_history = []
        st.query_params["session_id"] = new_session
        st.success(f"New session: {new_session}")

# Main chat interface
st.header("Chat")

# Display chat history
chat_container = st.container()
with chat_container:
    for msg in st.session_state.chat_history:
        if msg["role"] == "human":
            st.chat_message("user").write(msg["content"])
        elif msg["role"] == "ai":
            st.chat_message("assistant").write(msg["content"])

# Chat input
if prompt := st.chat_input("Type your message..."):
    if not st.session_state.session_id:
        st.error("Please set a session first")
    else:
        # Add user message
        st.session_state.chat_history.append({"role": "human", "content": prompt})
        with chat_container:
            st.chat_message("user").write(prompt)

        # Get response
        payload = {"message": prompt, "session_id": st.session_state.session_id}
        try:
            response = requests.post(f"{API_BASE}/chat", json=payload, timeout=60)
            if response.status_code == 200:
                data = response.json()
                agent_response = data["output"]
                st.session_state.chat_history.append({"role": "ai", "content": agent_response})
                with chat_container:
                    st.chat_message("assistant").write(agent_response)
            else:
                st.error(f"API Error: {response.status_code} - {response.text}")
        except Exception as e:
            st.error(f"Request failed: {str(e)}")


manifest_types = supported_manifest_types()

st.header("Dependency Manifest Scan")
st.caption("Paste manifest text or upload a supported file (package.json, pubspec.yaml, pom.xml, build.gradle, requirements.txt)")
manifest_type = st.selectbox("Manifest type", manifest_types, index=0, key="manifest_type_select")
manifest_text = st.text_area("Paste manifest content", height=180, key="manifest_text_input")
uploaded_manifest = st.file_uploader(
    "Upload manifest file",
    type=["txt", "json", "yaml", "yml", "xml", "gradle"],
    key="manifest_file_uploader",
)

scan_trigger = st.button("Scan manifest", key="manifest_scan_button")
if scan_trigger:
    response = None
    error_message = None
    if uploaded_manifest is not None:
        file_bytes = uploaded_manifest.read()
        final_type = canonicalize_manifest_type(manifest_type, uploaded_manifest.name) or manifest_type
        files = {
            "file": (
                uploaded_manifest.name,
                file_bytes,
                uploaded_manifest.type or "application/octet-stream",
            )
        }
        data = {"file_type": final_type}
        try:
            with st.spinner("Running manifest scan..."):
                response = requests.post(
                    f"{API_BASE}/dependency/manifest/upload",
                    data=data,
                    files=files,
                    timeout=120,
                )
        except Exception as exc:
            error_message = str(exc)
    elif manifest_text and manifest_text.strip():
        final_type = canonicalize_manifest_type(manifest_type, None) or manifest_type
        payload = {"file_type": final_type, "content": manifest_text}
        try:
            with st.spinner("Running manifest scan..."):
                response = requests.post(
                    f"{API_BASE}/dependency/manifest",
                    json=payload,
                    timeout=120,
                )
        except Exception as exc:
            error_message = str(exc)
    else:
        st.warning("Provide manifest text or upload a supported file before scanning.")

    if response is not None:
        if response.status_code == 200:
            st.subheader("Manifest scan result")
            st.json(response.json())
        else:
            st.error(f"API Error: {response.status_code} - {response.text}")
    elif error_message:
        st.error(f"Request failed: {error_message}")
