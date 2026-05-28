"""OpenCode launcher page inside BI Streamlit app."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import streamlit as st

_APP = Path(__file__).resolve().parent.parent
_OW = _APP / "opencode_web"
_LAUNCHER = _OW / "streamlit_app.py"

if not _LAUNCHER.is_file():
    st.set_page_config(page_title="AI", layout="wide")
    st.error(f"Launcher not found: {_LAUNCHER}")
    st.stop()

if str(_OW) not in sys.path:
    sys.path.insert(0, str(_OW))

_spec = importlib.util.spec_from_file_location("opencode_launcher", _LAUNCHER)
if _spec is None or _spec.loader is None:
    st.error("Cannot load opencode_web/streamlit_app.py")
    st.stop()
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_mod.app()
