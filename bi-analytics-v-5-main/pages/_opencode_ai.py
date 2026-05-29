"""Embedded OpenCode chat inside BI Streamlit app."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
_app_root = _here.parent
_p = _here.parent
while _p != _p.parent:
    if (_p / "auth.py").exists() and (_p / "config.py").exists():
        _app_root = _p
        break
    _p = _p.parent
sys.path.insert(0, str(_app_root))

import streamlit as st

from auth import (
    get_current_user,
    has_report_access,
    init_db,
    require_auth,
    restore_session_from_query_params,
)
from config import switch_page_app
from utils import load_custom_css

init_db()
restore_session_from_query_params()

st.set_page_config(
    page_title="ИИ помощник - BI Analytics",
    page_icon="🤖",
    layout="wide",
    menu_items={"Get Help": None, "Report a bug": None, "About": None},
)
load_custom_css()
require_auth()

user = get_current_user()
if not user or not has_report_access(user["role"]):
    st.error("Нет доступа к ИИ помощнику.")
    st.stop()

_OW = _app_root / "opencode_web"
_CHAT = _OW / "ai_chat_app.py"
if not _CHAT.is_file():
    st.error(f"Chat module not found: {_CHAT}")
    st.stop()

if str(_OW) not in sys.path:
    sys.path.insert(0, str(_OW))

_spec = importlib.util.spec_from_file_location("opencode_chat", _CHAT)
if _spec is None or _spec.loader is None:
    st.error("Cannot load opencode_web/ai_chat_app.py")
    st.stop()
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_mod.main(
    on_back_requested=lambda: switch_page_app("project_visualization_app.py"),
    embedded=True,
)
