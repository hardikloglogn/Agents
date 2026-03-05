# ui/utils.py

import uuid
import streamlit as st

def _new_thread_id(user: dict) -> str:
    prefix = user.get("role", "user")
    return f"{prefix}-{uuid.uuid4().hex[:10]}"

def _set_quick_prompt(prompt: str):
    st.session_state.quick_prompt = prompt

def _set_selected_agent(agent_name: str):
    st.session_state.selected_agent = agent_name

def _clear_selected_agent():
    st.session_state.selected_agent = None

def _history_to_chat(history: list) -> list:
    chat = []
    for m in history or []:
        role = m.get("role")
        if role == "human":
            chat.append({"role": "user", "content": m.get("content", "")})
        elif role == "ai":
            chat.append({"role": "assistant", "content": m.get("content", "")})
    return chat
