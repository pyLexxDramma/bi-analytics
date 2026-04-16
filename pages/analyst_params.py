"""
Прокси-страница (см. pages/admin.py в этом каталоге).
"""
from __future__ import annotations

import runpy
from pathlib import Path

_INNER = (
    Path(__file__).resolve().parent.parent
    / "bi-analytics-v-5-main"
    / "pages"
    / "analyst_params.py"
)
if not _INNER.is_file():
    import streamlit as st

    st.error(f"Не найден файл страницы: {_INNER}")
    st.stop()

runpy.run_path(str(_INNER), run_name="__main__")
