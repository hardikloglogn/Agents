"""
app.py
══════
PropTech Realty AI — Property & Real Estate Listing Agent System
Streamlit UI with Role-Based Access Control (RBAC)
"""

import sys
import os
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.db import init_db
from ui.pages import _login_page, _chat_page

def _page_config():
    st.set_page_config(
        page_title="PropTech Realty AI",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded",
    )

def main():
    _page_config()
    init_db()
    if "user" not in st.session_state or not st.session_state.user:
        _login_page()
    else:
        _chat_page(st.session_state.user)

if __name__ == "__main__":
    main()
