"""
Страница настроек профиля пользователя
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

from auth import (
    require_auth,
    get_current_user,
    get_user_role_display,
    change_password,
    update_user_email,
    is_streamlit_context,
    render_sidebar_menu,
)

from logger import log_action


def _profile_settings_ui(user) -> None:
    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:

        st.metric("Пользователь", user["username"])

    with col2:

        st.metric("Роль", get_user_role_display(user["role"]))

    st.markdown("---")

    tab1, tab2 = st.tabs(["Изменить пароль", "Изменить email"])

    with tab1:

        st.subheader("Изменение пароля")

        st.info("Для изменения пароля необходимо ввести текущий пароль и новый пароль.")

        with st.form("change_password_form"):

            old_password = st.text_input("Текущий пароль", type="password")

            new_password = st.text_input("Новый пароль", type="password")

            confirm_password = st.text_input("Подтвердите новый пароль", type="password")

            submitted = st.form_submit_button("Изменить пароль", type="primary")

            if submitted:

                if not old_password:

                    st.error("Введите текущий пароль")

                elif not new_password:

                    st.error("Введите новый пароль")

                elif len(new_password) < 6:

                    st.error("Новый пароль должен содержать минимум 6 символов")

                elif new_password != confirm_password:

                    st.error("Новый пароль и подтверждение не совпадают")

                else:

                    success, message = change_password(user["username"], old_password, new_password)

                    if success:

                        st.success(f"{message}")

                        log_action(user["username"], "change_password", "Пароль успешно изменен")

                        st.rerun()

                    else:

                        st.error(f"{message}")

    with tab2:

        st.subheader("Изменение email")

        st.info("Вы можете изменить или добавить email адрес для вашего профиля.")

        current_email = user.get("email", "Не указан")

        st.write(f"**Текущий email:** {current_email if current_email else 'Не указан'}")

        with st.form("change_email_form"):

            new_email = st.text_input(

                "Новый email",

                value=current_email if current_email and current_email != "Не указан" else "",

            )

            submitted = st.form_submit_button("Изменить email", type="primary")

            if submitted:

                email_value = new_email.strip() if new_email else None

                if email_value and "@" not in email_value:

                    st.error("Введите корректный email адрес")

                else:

                    success, message = update_user_email(user["username"], email_value)

                    if success:

                        st.success(f"{message}")

                        log_action(user["username"], "change_email", f"Email изменен на: {email_value or 'удален'}")

                        user["email"] = email_value

                        st.session_state["user"] = user

                        st.rerun()

                    else:

                        st.error(f"{message}")

    st.markdown("---")

    st.info(
        "Для возврата к отчетам используйте меню в боковой панели. Для выхода из системы нажмите «Выйти» внизу боковой панели."
    )


if is_streamlit_context():

    st.set_page_config(
        page_title="Настройки профиля - BI Analytics",
        page_icon="",
        layout="wide",
        menu_items={
            'Get Help': None,
            'Report a bug': None,
            'About': None
        }
    )

    from utils import load_custom_css

    load_custom_css()

    try:
        from dashboards.light_theme import sync_light_preview_theme

        sync_light_preview_theme(st)
    except Exception:
        pass

    require_auth()

    user = get_current_user()

    if not user:
        st.error("Ошибка получения данных пользователя")
        st.stop()

    try:
        from dashboards.light_theme import (
            ADMIN_LIGHT_PREVIEW_SESSION_KEY,
            PROFILE_LIGHT_PREVIEW_SESSION_KEY,
        )

        st.session_state.pop(PROFILE_LIGHT_PREVIEW_SESSION_KEY, None)
        st.session_state.pop(ADMIN_LIGHT_PREVIEW_SESSION_KEY, None)
    except Exception:
        pass

    render_sidebar_menu(current_page="profile")

    _profile_light = False
    try:
        from dashboards.light_theme import (
            PROFILE_SETTINGS_LABEL,
            is_light_preview_active,
            light_preview_heading_html,
        )

        _profile_light = is_light_preview_active()
        if _profile_light:
            st.markdown(
                light_preview_heading_html(PROFILE_SETTINGS_LABEL),
                unsafe_allow_html=True,
            )
        else:
            st.title(PROFILE_SETTINGS_LABEL)
    except Exception:
        st.title("Настройки профиля")

    _profile_settings_ui(user)
