"""
Административная панель (прямой URL). Полный UI — в admin_panel_content.render_admin_panel_tabs.
"""
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

from admin_panel_content import render_admin_panel_tabs
from auth import (
    init_db,
    require_auth,
    get_current_user,
    has_admin_access,
    render_sidebar_menu,
    is_streamlit_context,
)
from config import switch_page_app
from utils import load_custom_css

init_db()

if is_streamlit_context():
    st.set_page_config(
        page_title="Настройки - BI Analytics",
        page_icon="",
        layout="wide",
        menu_items={"Get Help": None, "Report a bug": None, "About": None},
    )
    load_custom_css()
    require_auth()

    user = get_current_user()
    if not user:
        st.error("Ошибка получения данных пользователя")
        st.stop()

    if not has_admin_access(user["role"]):
        st.error("У вас нет доступа к административной панели")
        st.info("Доступ к настройкам имеют только администраторы и суперадминистраторы.")
        if st.button("Вернуться к отчетам"):
            switch_page_app("project_visualization_app.py")
        st.stop()

    render_sidebar_menu(current_page="admin")

    st.markdown("<h1 class='Buquhununee'>Административная панель</h1>", unsafe_allow_html=True)
    st.caption("Раздел доступен также на вкладке «Административная панель» в Настройках профиля.")
    if st.button("Открыть настройки профиля", key="admin_to_profile_btn"):
        switch_page_app("pages/profile.py")

    render_admin_panel_tabs(user)
