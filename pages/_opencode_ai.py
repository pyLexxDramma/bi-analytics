"""Proxy for Streamlit Cloud root pages/."""
from __future__ import annotations

import runpy
from pathlib import Path

_INNER = (
    Path(__file__).resolve().parent.parent
    / "bi-analytics-v-5-main"
    / "pages"
    / "_opencode_ai.py"
)
if not _INNER.is_file():
    import streamlit as st
    st.error(f"Page not found: {_INNER}")
    st.stop()
runpy.run_path(str(_INNER), run_name="__main__")
