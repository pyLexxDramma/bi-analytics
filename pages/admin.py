"""
Прокси-страница для Streamlit: точка входа в корне репозитория (streamlit_app.py)
видит только ``pages/`` рядом с собой. Реальная логика — во вложенном пакете приложения.
"""
from __future__ import annotations

import runpy
from pathlib import Path

_INNER = (
    Path(__file__).resolve().parent.parent
    / "bi-analytics-v-5-main"
    / "pages"
    / "admin.py"
)
if not _INNER.is_file():
    import streamlit as st

    st.error(f"Не найден файл страницы: {_INNER}")
    st.stop()

runpy.run_path(str(_INNER), run_name="__main__")
