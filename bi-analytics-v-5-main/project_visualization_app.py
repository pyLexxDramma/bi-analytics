import sys
from pathlib import Path

# Ensure app directory is first on path (for deployment when CWD may not be bi-analytics)
_app_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_app_dir))

# .env до импорта auth/config (иначе при прямом ``streamlit run project_visualization_app.py`` корневой .env не читается).
try:
    from dotenv import load_dotenv as _pv_load_dotenv

    _root_env = _app_dir.parent / ".env"
    if _root_env.is_file():
        _pv_load_dotenv(_root_env, override=False)
    _pv_load_dotenv(_app_dir / ".env", override=True)
except ImportError:
    pass

import streamlit as st
import pandas as pd
import os
import subprocess
from html import escape as _html_escape

# # ← Новые импорты для теста
# import datetime
# import pytz
# from utils import format_russian_datetime   # ← обязательно!

from auth import (
    check_authentication,
    get_current_user,
    has_admin_access,
    has_report_access,
    get_user_role_display,
    logout,
    init_db,
    render_sidebar_menu,
    authenticate,
    generate_reset_token,
    reset_password,
    verify_reset_token,
    get_user_by_username,
    filter_reports_for_role,
    restore_session_from_query_params,
)
from data_loader import (
    load_data,
    ensure_data_session_state,
    update_session_with_loaded_file,
    clear_all_data_for_removed_files,
)
from utils import load_custom_css
from dashboard_diagnostics import render_dashboard_diagnostics_tab

# # ← Добавь тестовый блок сразу после импортов (чтобы он отобразился на всех страницах)
# st.sidebar.markdown("**Отладка времени**")
# now_utc = datetime.datetime.now(pytz.UTC)
# now_msk = datetime.datetime.now(pytz.timezone("Europe/Moscow"))
#
# st.sidebar.write("Текущее серверное время (UTC):", now_utc.strftime("%Y-%m-%d %H:%M:%S"))
# st.sidebar.write("Москва (Europe/Moscow):", now_msk.strftime("%Y-%m-%d %H:%M:%S"))
# st.sidebar.write("Через format_russian_datetime:", format_russian_datetime(now_utc.isoformat()))

# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ CSS CONNECT ¤ Start                                                    │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

# def load_custom_css():
#     css_path = Path(__file__).parent / "static" / "css" / "style.css"
#     if css_path.exists():
#         with open(css_path, encoding="utf-8") as f:
#             css_content = f.read()
#         st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)
#     else:
#         st.warning("CSS файл не найден: " + str(css_path))

# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ CSS CONNECT ¤ End                                                      │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

# Инициализация БД — один раз на процесс (без st.info на каждом rerun).
_DB_INITIALIZED = False


def _ensure_db_initialized() -> None:
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    init_db(quiet=True)
    _DB_INITIALIZED = True


_ensure_db_initialized()

# Версия приложения (git-sha + время билда). Используется:
#  1) auto_ingest для детекции «код обновился, надо перевыкачать данные»;
#  2) для очистки st.cache_data / st.cache_resource в session_state, иначе
#     кэшированные DataFrame'ы из старого деплоя «застревают» и клиент
#     видит старые данные/правки;
#  3) для показа бейджа версии в sidebar (диагностика).
try:
    from app_version import get_app_version

    _APP_VERSION = get_app_version()
except Exception:
    _APP_VERSION = {"sha": "unknown", "ts": "", "label": "v unknown", "source": "fallback"}

# Авто-ingest при холодном старте инстанса (Streamlit Cloud / прод): за флагом
# BI_ANALYTICS_AUTO_INGEST=1. См. docstring в auto_ingest.py — переменные:
#   BI_ANALYTICS_AUTO_INGEST_FTP=1 (default)        → сначала FTP-sync в web/
#   BI_ANALYTICS_AUTO_INGEST_AGE_H=12               → не повторять чаще раза в N часов
#   BI_ANALYTICS_AUTO_INGEST_FORCE=1                → игнорировать маркер
#   BI_ANALYTICS_AUTO_INGEST_PURGE_DB=1 (default)   → удалять web_data.db при смене app_version
# Ошибки логируются в stderr; UI запустится в любом случае.
try:
    from auto_ingest import maybe_run_auto_ingest_on_startup

    maybe_run_auto_ingest_on_startup()
except Exception as _e:  # noqa: BLE001
    try:
        from auto_ingest import safe_stderr_log

        safe_stderr_log(f"[auto_ingest] init failed: {_e!r}")
    except Exception:
        pass

# Сессия с прошлой версии приложения → инвалидируем кэши и рабочее состояние,
# чтобы клиент НЕ видел старые DataFrame'ы / данные после деплоя.
# (Streamlit-кэш живёт на уровне процесса, session_state — на уровне сессии.)
def _invalidate_caches_on_version_drift() -> None:
    try:
        prev = str(st.session_state.get("_bi_app_version_sha") or "")
        cur = str(_APP_VERSION.get("sha") or "")
        if not cur:
            return
        if prev and prev != cur:
            for fn_name in ("cache_data", "cache_resource"):
                try:
                    obj = getattr(st, fn_name, None)
                    clear = getattr(obj, "clear", None) if obj is not None else None
                    if callable(clear):
                        clear()
                except Exception:
                    pass
            # Сбрасываем тяжёлые кэшированные DataFrame'ы (matrix-кэш и т.п.).
            for k in [
                "_dev_matrix_cache_v1",
                "_pending_web_folder_load",
                "_deeplink_applied_once",
            ]:
                st.session_state.pop(k, None)
            try:
                st.toast(
                    f"Загружена новая версия приложения ({cur}). Кэши сброшены.",
                    icon="🔄",
                )
            except Exception:
                pass
        st.session_state["_bi_app_version_sha"] = cur
    except Exception:
        pass


_invalidate_caches_on_version_drift()

# Persistent auth: если в URL ?sid=<token> валиден — восстанавливаем сессию
# до set_page_config, чтобы корректно выбрать состояние сайдбара (expanded
# для авторизованного пользователя). Безопасно при отсутствии токена / БД.
try:
    restore_session_from_query_params()
except Exception:
    pass

# Page configuration (должно быть первым)
_sidebar_state = "expanded" if st.session_state.get("authenticated") else "collapsed"

st.set_page_config(
    page_title="Панель аналитики проектов",
    page_icon="",
    layout="wide",
    initial_sidebar_state=_sidebar_state,
    menu_items={"Get Help": None, "Report a bug": None, "About": None},
)

# Главная страница в списке Streamlit скрывается через static/css/style.css (п. «Главная»).
# Админ и параметры отчётов — страницы ``pages/_*.py`` (не в авто-меню); переходы — из бокового меню приложения.
st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] {
        overflow-x: auto;
        min-width: 0;
    }
    [data-testid="stMain"] {
        overflow-x: auto;
        min-width: 0;
    }
    [data-testid="stMainBlockContainer"] {
        min-width: 1180px;
        max-width: none;
        overflow-x: auto;
    }
    section.main, [data-testid="stMain"] {
        overflow-x: auto !important;
        min-width: 0;
    }
    .stPlotlyChart,
    [data-testid="stPlotlyChart"] {
        overflow-x: auto;
        overflow-y: hidden;
        max-width: 100%;
        min-width: 0;
    }
    .stPlotlyChart > div,
    [data-testid="stPlotlyChart"] > div {
        min-width: 1180px;
    }
    [data-testid="stDataFrame"] {
        overflow-x: auto;
        min-width: 0;
    }
    [data-testid="stDataFrame"] > div {
        min-width: max-content;
    }
    /* R23-08: скрыть встроенные англоязычные пресеты (Past Week/Month/Year/...) */
    /* в попапе st.date_input — внутри попапа используется вложенный select,       */
    /* который мы прячем, чтобы не смешивался с нашим русским селектором.           */
    [data-baseweb="popover"] [data-baseweb="calendar"] ~ div [data-baseweb="select"],
    [data-baseweb="popover"] [data-baseweb="calendar"] + div [data-baseweb="select"],
    [data-baseweb="popover"] [aria-label="Choose a date range"],
    [data-baseweb="popover"] label[for^="range-calendar"],
    [data-baseweb="popover"] [data-baseweb="calendar"] ~ label {
        display: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Скрываем сайдбар полностью если не авторизован
if not st.session_state.get("authenticated"):
    st.markdown("""
        <style>
        [data-testid="stSidebarNav"] { display: none !important; }
        section[data-testid="stSidebar"] { display: none !important; }
        button[data-testid="collapsedControl"] { display: none !important; }
        </style>
    """, unsafe_allow_html=True)

# Файлы с префиксом _ уже скрыты из меню автоматически Streamlit
# Дополнительная попытка скрыть через st.navigation (может быть недоступно в версии 1.52.1)
# Удаляем этот вызов, так как он может вызывать ошибки

# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ CSS CONNECT ¤ Start                                                    │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

load_custom_css()

_RU_LABELS_INJECTED_THIS_RUN = False
_TABLE_SORT_INJECTED_THIS_RUN = False


def _inject_ru_labels_once() -> None:
    """Один iframe на rerun: multiselect Select all → Выбрать все (BI_ANALYTICS_RU_INJECT=0 отключает)."""
    global _RU_LABELS_INJECTED_THIS_RUN
    if _RU_LABELS_INJECTED_THIS_RUN:
        return
    try:
        from dashboards.streamlit_ru_inject import inject_multiselect_ru_translations, ru_inject_enabled

        if not ru_inject_enabled():
            return
        inject_multiselect_ru_translations()
        _RU_LABELS_INJECTED_THIS_RUN = True
    except Exception:
        pass


def _inject_table_sort_once() -> None:
    global _TABLE_SORT_INJECTED_THIS_RUN
    if _TABLE_SORT_INJECTED_THIS_RUN:
        return
    try:
        from dashboards.table_sort_inject import inject_sortable_tables_script

        inject_sortable_tables_script()
        _TABLE_SORT_INJECTED_THIS_RUN = True
    except Exception as _e:
        import logging

        logging.getLogger(__name__).warning("table sort inject failed: %s", _e)


def _render_active_dashboard(
    selected_dashboard: str,
    df_for_render: "pd.DataFrame",
    *,
    release_mode: bool,
) -> None:
    """Тело отчёта (в st.fragment — фильтры не перезапускают всё приложение)."""
    from dashboards import get_dashboards

    dashboards = get_dashboards()
    render_fn = dashboards.get(selected_dashboard)
    if not render_fn:
        st.warning(
            f"График '{selected_dashboard}' не найден. Выберите другой отчёт в боковом меню."
        )
        st.info(f"Текущий выбор: {selected_dashboard}")
        return
    if df_for_render is None or (
        isinstance(df_for_render, pd.DataFrame) and df_for_render.empty
    ):
        st.warning(
            f"Нет данных для отчёта «{selected_dashboard}». "
            "Загрузите данные (вручную, web/ или FTP) или выберите другой отчёт "
            "в боковом меню."
        )
        return
    if release_mode:
        render_fn(df_for_render)
        return
    tab_dash, tab_diag = st.tabs(["Дашборд", "Диагностика (dev)"])
    with tab_dash:
        render_fn(df_for_render)
    with tab_diag:
        render_dashboard_diagnostics_tab(
            selected_dashboard,
            df_for_render,
            st.session_state,
        )


if hasattr(st, "fragment"):
    _render_active_dashboard = st.fragment(_render_active_dashboard)

# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ CSS CONNECT ¤ End                                                      │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

# ==================== MAIN APP ====================
def main():

    # Persistent auth: восстанавливаем сессию из URL ?sid=<token>
    # ДО первой проверки `check_authentication()`. Иначе при пересоздании
    # websocket Streamlit Cloud (после долгой обработки) пользователя сбрасывает
    # на форму входа.
    try:
        restore_session_from_query_params()
    except Exception:
        pass

    # Проверка авторизации - если не авторизован, показываем форму входа
    if not check_authentication():

        # Заголовок страницы входа
        st.markdown(
            """
            <div style="text-align: center; margin-bottom: 2rem;">
                <h1 style="color: #ffffff; font-size: 2rem; margin-bottom: 0.5rem;">BI Analytics</h1>
            </div>
        """,
            unsafe_allow_html=True,
        )

        # Инициализация переменных для восстановления пароля
        if "reset_mode" not in st.session_state:
            st.session_state.reset_mode = False
        if "reset_token" not in st.session_state:
            st.session_state.reset_token = None

        # Режим восстановления пароля по токену
        if st.session_state.reset_mode and st.session_state.reset_token:
            st.subheader("Восстановление пароля")

            token = st.session_state.reset_token
            username = verify_reset_token(token)

            if not username:
                st.error("Токен восстановления недействителен или истек")
                st.session_state.reset_mode = False
                st.session_state.reset_token = None
                if st.button("Вернуться к входу"):
                    st.rerun()
                st.stop()

            st.info(f"Восстановление пароля для пользователя: **{username}**")

            new_password = st.text_input(
                "Новый пароль", type="password", key="new_password"
            )
            confirm_password = st.text_input(
                "Подтвердите пароль", type="password", key="confirm_password"
            )

            col1, col2 = st.columns(2)

            with col1:

                if st.button("Сбросить пароль", type="primary"):

                    if not new_password or len(new_password) < 6:

                        st.error("Пароль должен содержать минимум 6 символов")

                    elif new_password != confirm_password:

                        st.error("Пароли не совпадают")

                    else:

                        if reset_password(token, new_password):

                            st.success("Пароль успешно изменен!")

                            st.info("Теперь вы можете войти с новым паролем")

                            st.session_state.reset_mode = False

                            st.session_state.reset_token = None

                            if st.button("Перейти к входу"):

                                st.rerun()

                        else:

                            st.error("Ошибка при сбросе пароля")

            with col2:

                if st.button("Отмена"):

                    st.session_state.reset_mode = False

                    st.session_state.reset_token = None

                    st.rerun()

            st.stop()

        # Режим запроса восстановления пароля
        elif st.session_state.reset_mode:

            st.subheader("Восстановление пароля")

            tab1, tab2 = st.tabs(["По имени пользователя", "По токену"])

            with tab1:

                username = st.text_input("Введите имя пользователя", key="reset_username")

                col1, col2 = st.columns(2)

                with col1:

                    if st.button("Создать токен восстановления", type="primary"):

                        if username:

                            user = get_user_by_username(username)

                            if user:

                                token = generate_reset_token(username)

                                if token:

                                    st.success("Токен восстановления создан!")

                                    st.info(f"**Токен восстановления:** `{token}`")

                                    st.warning("В реальном приложении токен будет отправлен на email пользователя")

                                    st.info("Для демонстрации скопируйте токен и используйте вкладку 'По токену'")

                                    st.session_state.reset_token = token

                                    st.rerun()

                                else:

                                    st.error("Ошибка при создании токена")

                            else:

                                st.error("Пользователь не найден")

                        else:

                            st.warning("Введите имя пользователя")

                with col2:

                    if st.button("Отмена"):

                        st.session_state.reset_mode = False

                        st.rerun()

            with tab2:

                token_input = st.text_input("Введите токен восстановления", key="token_input")

                col1, col2 = st.columns(2)

                with col1:

                    if st.button("Использовать токен", type="primary"):

                        if token_input:

                            username = verify_reset_token(token_input)

                            if username:

                                st.session_state.reset_token = token_input

                                st.rerun()

                            else:

                                st.error("Токен недействителен или истек")

                        else:

                            st.warning("Введите токен")

                with col2:

                    if st.button("Отмена", key="cancel_token"):

                        st.session_state.reset_mode = False

                        st.rerun()

            st.markdown("---")

            if st.button("← Вернуться к входу"):

                st.session_state.reset_mode = False

                st.rerun()

            st.stop()

        # Режим входа
        else:

            # Форма входа в центрированном контейнере (уже)
            col_left, col_center, col_right = st.columns([2, 1.5, 2])

            with col_center:

                with st.form("login_form", clear_on_submit=False):

                    # Скрытое поле-ловушка для браузера
                    st.markdown('<input type="text" style="display:none" autocomplete="username">', unsafe_allow_html=True)

                    st.markdown('<input type="password" style="display:none" autocomplete="new-password">', unsafe_allow_html=True)

                    username = st.text_input(
                        "Имя пользователя",
                        key="login_username",
                        placeholder="Имя пользователя",
                        autocomplete="off",
                        value="",
                        label_visibility="collapsed",
                    )

                    password = st.text_input(
                        "Пароль",
                        type="password",
                        key="login_password",
                        placeholder="Пароль",
                        autocomplete="new-password",
                        value="",
                        label_visibility="collapsed",
                    )

                    st.markdown("""
                    <style>
                    div[data-testid="stForm"]{
                        padding: 0 .875rem !important;
                        border: 0 solid black !important;
                        border-radius: .25rem !important;
                    }
                    div[data-testid="stForm"] > div[data-testid="stVerticalBlock"]{
                        height: auto !important;
                        padding: 0 !important;
                        margin: 0 !important;
                        border: 0 !important;
                        box-shadow: 0 0 0 0 hotpink !important;
                    }
                    div[data-testid="stTextInput"] > label{
                        height: 0 !important;
                        min-height: 0 !important;
                        padding: 0 !important;
                        margin: 0 !important;
                        overflow: hidden !important;
                    }
                    div[data-testid="stTextInput"] > label > span{
                        display: none !important;
                    }
                    </style>
                    """, unsafe_allow_html=True)

                    # ИСПРАВЛЕНИЕ: убираем колонки, делаем кнопки одна под другой
                    st.markdown("<br>", unsafe_allow_html=True)

                    submit_button = st.form_submit_button("Войти", type="primary", width="stretch")

                    submit_reset = st.form_submit_button("Забыли пароль?", width="stretch")

                    st.markdown("<br>", unsafe_allow_html=True)

                    if submit_button:

                        if username and password:

                            success, user = authenticate(username, password)

                            if success and user:

                                st.session_state.authenticated = True

                                st.session_state.user = user

                                # Persistent-сессия: токен в URL ?sid=...
                                # позволит восстановить логин при разрыве
                                # websocket Streamlit Cloud (длинная обработка
                                # → сессия пересоздаётся → пользователя
                                # выкидывало). См. auth.restore_session_from_query_params.
                                try:
                                    from auth import issue_session_token_for_user

                                    issue_session_token_for_user(user)
                                except Exception:
                                    pass

                                st.success(f"Добро пожаловать, {user['username']}!")

                                import time

                                time.sleep(1)

                                st.rerun()

                            else:

                                st.error("Неверное имя пользователя или пароль")

                        else:

                            st.warning("Заполните все поля")

                    if submit_reset:

                        st.session_state.reset_mode = True

                        st.rerun()

                st.markdown("<br>", unsafe_allow_html=True)

                with st.container(border=True):

                    st.markdown("""
                    **Тестовые учетные данные:**
                    - **Имя пользователя:** `admin`
                    - **Пароль:** `admin123`
                    - **Роль:** Суперадминистратор
                    """)

        st.stop()

    user = get_current_user()

    # Проверка, что пользователь получен
    if not user:
        st.error("Ошибка получения данных пользователя")
        st.info("Пожалуйста, войдите в систему заново.")
        if st.button("Перейти к авторизации", type="primary"):
            logout()
            st.rerun()
        st.stop()

    # Проверка прав доступа к отчетам
    if not has_report_access(user["role"]):
        st.error("У вас нет доступа к отчетам")
        st.info("Доступ к отчетам имеют менеджеры, аналитики и администраторы.")
        if st.button("Выйти"):
            logout()
            st.rerun()
        st.stop()

    _inject_ru_labels_once()
    _inject_table_sort_once()

    _dash_title = str(st.session_state.get("current_dashboard") or "").strip()
    _h1_text = (
        _html_escape(_dash_title) if _dash_title else "Панель аналитики проектов"
    )
    st.markdown(
        f'<h1 class="main-header">{_h1_text}</h1>',
        unsafe_allow_html=True,
    )

    # Боковая панель с меню навигации
    render_sidebar_menu(current_page="reports")

    ensure_data_session_state()

    def _is_release_client_mode() -> bool:
        try:
            from config import is_release_client_mode as _cfg_is_release
            return bool(_cfg_is_release())
        except Exception:
            return os.environ.get(
                "BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS", ""
            ).strip().lower() in ("1", "true", "yes", "on")

    def _show_data_ops_ui() -> bool:
        try:
            from config import show_data_ops_ui_for_role

            return bool(show_data_ops_ui_for_role(user.get("role")))
        except Exception:
            return not _is_release_client_mode()

    def _read_deeplink_params() -> dict:
        """
        Deep-link для автотестов/быстрого открытия:
        - ?source=manual|web|ftp_web
        - ?report=<точное имя отчёта, например БДДС>
        """
        try:
            qp = st.query_params
        except Exception:
            return {}

        def _pick(k: str) -> str:
            try:
                v = qp.get(k, "")
            except Exception:
                return ""
            if isinstance(v, list):
                return str(v[0]).strip() if v else ""
            return str(v).strip()

        return {
            "source": _pick("source").lower(),
            "report": _pick("report"),
        }

    _dl = _read_deeplink_params()
    if not st.session_state.get("_deeplink_applied_once", False):
        _src_map = {
            "manual": "Загрузить вручную",
            "web": "Из папки web/",
            "ftp_web": "FTP → web/",
            "ftp": "FTP → web/",
        }
        _dl_source = _src_map.get(_dl.get("source", ""))
        if _dl_source:
            st.session_state["data_mode_radio"] = _dl_source
            if _dl_source in ("Из папки web/", "FTP → web/"):
                st.session_state["_pending_web_folder_load"] = True
        if _dl.get("report"):
            st.session_state["current_dashboard"] = _dl["report"]
        if _dl_source or _dl.get("report"):
            st.session_state["_deeplink_applied_once"] = True

    _admin_data_ops_sidebar = _show_data_ops_ui()

    # Источник данных: UI только в сайдбаре у admin; клиент release — тихий web/.
    st.session_state.setdefault("data_mode_radio", "Из папки web/")
    data_mode = str(st.session_state.get("data_mode_radio") or "Из папки web/")
    if not _admin_data_ops_sidebar and data_mode in ("Из папки web/", "FTP → web/"):
        if st.session_state.get("project_data") is None:
            st.session_state["_pending_web_folder_load"] = True

    if data_mode in ("Из папки web/", "FTP → web/"):

        from data_health import save_schema_health_report, build_environment_fingerprint
        from data_readiness import build_data_readiness_report, render_data_readiness_expander
        from web_schema import init_web_schema, get_all_versions, get_active_version_id, activate_version
        from web_loader import load_all_from_web, web_dir_exists, read_version_to_session, get_web_dir

        init_web_schema()

        # ── Helper: построить псевдо-`last_load_result` из web_files БД ────
        # evaluate_data_contract проверяет наличие типов файлов через
        # load_result["diagnostics"]. Без него считает «ничего не загружено»
        # и пишет «Не найдены tessa csv / 1C dannye» — даже если session_state
        # уже наполнен через read_version_to_session.
        def _build_pseudo_lr_from_db(version_id: int) -> "Optional[dict]":
            try:
                import sqlite3 as _sql
                from web_schema import WEB_DB_PATH as _WDP

                _conn = _sql.connect(_WDP)
                _conn.row_factory = _sql.Row
                _rows = _conn.execute(
                    "SELECT file_name, rel_path, file_type, rows_count "
                    "FROM web_files WHERE version_id=?",
                    (int(version_id),),
                ).fetchall()
                _conn.close()
                _diags = []
                _types_in_db = set()
                for _r in _rows:
                    _ft = str(_r["file_type"] or "")
                    _types_in_db.add(_ft)
                    _diags.append(
                        {
                            "file": str(_r["rel_path"] or _r["file_name"] or ""),
                            "type": _ft,
                            "rows": int(_r["rows_count"] or 0),
                            "columns": [],
                        }
                    )
                print(
                    f"[auto_hydrate] pseudo_lr: version_id={version_id}, "
                    f"types={sorted(_types_in_db)}, files={len(_rows)}",
                    file=sys.stderr,
                )
                return {
                    "loaded": len(_rows),
                    "skipped": 0,
                    "errors": [],
                    "warnings": [],
                    "diagnostics": _diags,
                    "version_id": int(version_id),
                }
            except Exception as _e:
                print(f"[auto_hydrate] pseudo_lr failed: {_e}", file=sys.stderr)
                return None

        # ── Auto-hydrate сессии из активной версии БД ────────────────────
        # Зачем: auto_ingest при cold start пишет данные в web_data.db, но
        # st.session_state у него нет (нет ScriptRunContext). Без этого
        # клиент при первом script_run видит project_data/tessa_data/... = None,
        # и контракт жалуется «не найдены TESSA / 1C dannye», хотя в БД
        # лежат свежие 24-29 файлов.
        #
        # Условие специально мягкое (project_data is None ИЛИ
        # last_load_result is None). Раньше требовалось одновременное None
        # для 5 ключей — но web_version_id мог быть уже выставлен
        # selectbox'ом «Версия данных» из предыдущего rerun, и блок
        # auto-hydrate перестал срабатывать → контракт оставался пустым.
        _need_hydrate = (
            st.session_state.get("project_data") is None
            or st.session_state.get("last_load_result") is None
        )
        if _need_hydrate:
            try:
                _hydrate_active_id = get_active_version_id()
            except Exception as _e:
                print(f"[auto_hydrate] get_active_version_id failed: {_e}", file=sys.stderr)
                _hydrate_active_id = None

            _hydrate_ok = False
            if _hydrate_active_id:
                try:
                    if st.session_state.get("project_data") is None:
                        read_version_to_session(int(_hydrate_active_id))
                    st.session_state["web_version_id"] = int(_hydrate_active_id)
                    st.session_state["web_version_pick_id"] = int(_hydrate_active_id)
                    _hydrate_ok = True
                except Exception as _e:
                    print(f"[auto_hydrate] read_version_to_session failed: {_e}", file=sys.stderr)

            if _hydrate_ok:
                _pseudo_lr = _build_pseudo_lr_from_db(int(_hydrate_active_id))
                if _pseudo_lr:
                    st.session_state["last_load_result"] = _pseudo_lr
                    try:
                        from data_contract import evaluate_data_contract
                        from data_health import build_environment_fingerprint
                        from data_readiness import build_data_readiness_report

                        st.session_state["last_data_contract"] = evaluate_data_contract(_pseudo_lr)
                        st.session_state["last_data_readiness"] = build_data_readiness_report(_pseudo_lr)
                        st.session_state["last_env_fingerprint"] = build_environment_fingerprint(_pseudo_lr)
                    except Exception as _e:
                        print(f"[auto_hydrate] data_contract/readiness failed: {_e}", file=sys.stderr)
                    st.session_state["_auto_hydrated_from_db"] = True

            # Fallback: если auto-hydrate не справился (нет active_id, или
            # БД повреждена, или session_state по-прежнему пуст по всем
            # ключевым типам) — делаем полноценный load_all_from_web().
            _need_fallback = (
                (not _hydrate_ok)
                or (
                    st.session_state.get("project_data") is None
                    and st.session_state.get("tessa_data") is None
                    and st.session_state.get("reference_1c_dannye") is None
                    and st.session_state.get("debit_credit_data") is None
                    and st.session_state.get("resources_data") is None
                )
            )
            if _need_fallback and web_dir_exists():
                try:
                    print("[auto_hydrate] fallback to load_all_from_web()", file=sys.stderr)
                    with st.spinner("Первичная загрузка данных из web/…"):
                        _fb_result = load_all_from_web()
                    st.session_state["last_load_result"] = _fb_result
                    try:
                        st.session_state["last_data_readiness"] = build_data_readiness_report(_fb_result)
                        st.session_state["last_env_fingerprint"] = build_environment_fingerprint(_fb_result)
                        from data_contract import evaluate_data_contract as _edc
                        st.session_state["last_data_contract"] = _edc(_fb_result)
                    except Exception:
                        pass
                    try:
                        from web_schema import get_active_version_id as _gav2
                        _na2 = _gav2()
                        if _na2 is not None:
                            st.session_state["web_version_id"] = int(_na2)
                            st.session_state["web_version_pick_id"] = int(_na2)
                    except Exception:
                        pass
                    st.session_state["_auto_hydrated_from_web"] = True
                except Exception as _e:
                    print(f"[auto_hydrate] fallback load_all_from_web failed: {_e}", file=sys.stderr)

        def _perform_load_from_web_folder(*, quiet: bool = False) -> None:
            """Сканирование web/, запись в SQLite и обновление session_state (как кнопка «Загрузить из web/»)."""
            if not web_dir_exists():
                st.error(
                    "Не найден ни локальный каталог web/ рядом с приложением, "
                    "ни папка Analitics/web (уровнем выше репозитория), "
                    "ни пути из переменной BI_ANALYTICS_WEB_EXTRA_PATHS."
                )
                return

            if quiet:
                result = load_all_from_web()
            else:
                with st.spinner("Читаю файлы из web/..."):
                    result = load_all_from_web()
            try:
                st.session_state["last_load_result"] = result
                st.session_state["last_data_readiness"] = build_data_readiness_report(result)
                st.session_state["last_data_schema_health"] = save_schema_health_report(load_result=result)
                st.session_state["last_env_fingerprint"] = build_environment_fingerprint(result)
                from data_contract import evaluate_data_contract

                st.session_state["last_data_contract"] = evaluate_data_contract(result)
            except Exception:
                st.session_state["last_data_readiness"] = None
                st.session_state["last_data_schema_health"] = None
                st.session_state["last_env_fingerprint"] = None
                st.session_state["last_data_contract"] = None

            st.cache_data.clear()
            st.session_state.pop("web_version_id", None)
            try:
                from web_schema import get_active_version_id

                _na = get_active_version_id()
                if _na is not None:
                    st.session_state["web_version_pick_id"] = int(_na)
            except Exception:
                pass

            _release_quiet = _is_release_client_mode()
            if not _release_quiet:
                for w in result.get("warnings", []):
                    st.warning(w)

            if result["errors"]:
                st.warning(f"Загружено: {result['loaded']}, пропущено: {result['skipped']}")
                for err in result["errors"]:
                    st.error(err)
            elif not _release_quiet:
                try:
                    st.toast(f"Загружено файлов: {result['loaded']}", icon="✅")
                except Exception:
                    pass
            try:
                from logger import log_action
                u = get_current_user()
                if u:
                    log_action(
                        u["username"],
                        "data_loaded",
                        f"web/: loaded={result.get('loaded')}, skipped={result.get('skipped')}",
                    )
            except Exception:
                pass
            if not _release_quiet:
                with st.expander("Справка: колонки загрузки из web/", expanded=False):
                    for row in result.get("diagnostics", [])[:40]:
                        st.json(row)

            st.rerun()

        if (
            _is_release_client_mode()
            and data_mode == "Из папки web/"
            and not get_all_versions()
            and st.session_state.get("project_data") is None
            and not st.session_state.get("_release_web_autoload_tried", False)
        ):
            # Release-клиент при первом заходе: ставим флаги первыми, чтобы при любом
            # сбое FTP / зависании не зацикливаться и не блокировать UI на каждом
            # rerun. Если FTP сработает — данные подтянутся; если нет — клиент увидит
            # данные из локального web/ (закоммиченные снимки).
            #
            # Управление: BI_ANALYTICS_AUTO_FTP_ON_START=0 — отключить авто-FTP даже если настроен.
            st.session_state["_release_web_autoload_tried"] = True
            st.session_state["_pending_web_folder_load"] = True
            try:
                _auto_ftp_off = str(os.environ.get("BI_ANALYTICS_AUTO_FTP_ON_START", "")).strip().lower() in (
                    "0",
                    "false",
                    "no",
                    "off",
                )
            except Exception:
                _auto_ftp_off = False
            if not _auto_ftp_off:
                try:
                    from ftp_sync import (
                        merge_ftp_config,
                        streamlit_secrets_to_config,
                        sync_ftp_to_web,
                    )

                    _ftp_cfg = merge_ftp_config(streamlit_secrets_to_config())
                    # Жёсткий потолок таймаута, чтобы при недоступном FTP клиент
                    # не висел на спиннере вечно (по умолчанию ftplib timeout=60s).
                    _ftp_cfg["timeout"] = float(_ftp_cfg.get("timeout") or 30) or 30
                    if _ftp_cfg.get("host") and _ftp_cfg.get("user"):
                        with st.spinner("Загружаю свежие данные…"):
                            sync_ftp_to_web(
                                get_web_dir(),
                                config=_ftp_cfg,
                                extensions=(".csv", ".json"),
                                progress=lambda _m: None,
                            )
                except Exception:
                    # Без шумовых ошибок: на release клиенту нечего показывать,
                    # упадём в чтение того, что уже лежит локально в web/.
                    pass

        if (
            data_mode in ("Из папки web/", "FTP → web/")
            and st.session_state.pop("_pending_web_folder_load", False)
        ):
            _load_quiet = bool(st.session_state.pop("_pending_web_load_quiet", True))
            _perform_load_from_web_folder(quiet=_load_quiet)

        if _admin_data_ops_sidebar:
            try:
                from data_ops_sidebar import apply_web_version_pick

                apply_web_version_pick(st, build_pseudo_lr_from_db=_build_pseudo_lr_from_db)
            except Exception:
                pass

        if _is_release_client_mode():
            _panel_tab = "Дашборды"
        else:
            _panel_tab = st.radio(
                "Вкладка панели",
                ["Дашборды", "Проверка данных"],
                horizontal=True,
                key="main_panel_view_tab",
            )
        if _panel_tab == "Проверка данных":
            render_data_readiness_expander()
            if st.session_state.get("last_data_schema_health"):
                _fsch = (st.session_state.get("last_data_schema_health") or {}).get("file_checks") or []
                if _fsch:
                    with st.expander("Проверка файлов и колонок (что отсутствует/не распознано)", expanded=True):
                        _fd = pd.DataFrame(_fsch).copy()
                        _prio = {"err": 0, "warn": 1, "ok": 2}
                        _fd["_p"] = _fd["level"].map(lambda x: _prio.get(str(x).lower(), 9))
                        _fd = _fd.sort_values(["_p", "target"], kind="stable").drop(columns=["_p"])

                        def _style_level(row):
                            lv = str(row.get("level", "")).lower()
                            if lv == "err":
                                return ["background-color: #5a1f1f; color: #ffe3e3;"] * len(row)
                            if lv == "warn":
                                return ["background-color: #5a4b1f; color: #fff3d6;"] * len(row)
                            if lv == "ok":
                                return ["background-color: #1f4a2a; color: #e7ffe7;"] * len(row)
                            return [""] * len(row)

                        st.dataframe(
                            _fd.style.apply(_style_level, axis=1),
                            use_container_width=True,
                            hide_index=True,
                            height=min(720, 40 + max(1, len(_fd)) * 34),
                        )
                from data_health import REPORT_JSON, REPORT_MD

                c1, c2 = st.columns(2)
                with c1:
                    if REPORT_MD.exists():
                        st.download_button(
                            "Скачать data_health_report.md",
                            data=REPORT_MD.read_text(encoding="utf-8"),
                            file_name="data_health_report.md",
                            mime="text/markdown",
                            key="download_data_health_md",
                        )
                with c2:
                    if REPORT_JSON.exists():
                        st.download_button(
                            "Скачать data_health_report.json",
                            data=REPORT_JSON.read_text(encoding="utf-8"),
                            file_name="data_health_report.json",
                            mime="application/json",
                            key="download_data_health_json",
                        )
            _env = st.session_state.get("last_env_fingerprint")
            if _env:
                with st.expander("Environment fingerprint (для сравнения local vs deploy)", expanded=False):
                    st.json(_env)
            st.stop()

    else:

        # Ручная загрузка файлов (существующая логика)
        uploaded_files =         st.file_uploader(
            "Загрузите файлы с данными (можно несколько)",
            type=["csv", "xlsx", "xls"],
            accept_multiple_files=True,
        )

        current_file_names = [f.name for f in uploaded_files] if uploaded_files else []

        if uploaded_files is not None and len(uploaded_files) > 0:

            files_to_remove = [
                f
                for f in st.session_state.loaded_files_info.keys()
                if f not in current_file_names
            ]

            clear_all_data_for_removed_files(files_to_remove)

            for uploaded_file in uploaded_files:

                file_id = uploaded_file.name

                if file_id in st.session_state.loaded_files_info:

                    continue

                df_loaded = load_data(uploaded_file, file_id)

                if df_loaded is not None:

                    update_session_with_loaded_file(df_loaded, file_id)

    _dm_radio = st.session_state.get("data_mode_radio", "Загрузить вручную")
    if _dm_radio in ("Из папки web/", "FTP → web/"):
        from data_contract import evaluate_data_contract, render_contract_banner, should_enforce_data_contract_stop

        _had_data_attempt = (
            st.session_state.get("last_load_result") is not None
            or st.session_state.get("web_version_id") is not None
        )
        if _had_data_attempt:
            _ctr = evaluate_data_contract(st.session_state.get("last_load_result"))
            st.session_state["last_data_contract"] = _ctr
            if _admin_data_ops_sidebar:
                render_contract_banner(_ctr)
            elif not _ctr.get("ok"):
                for _bl in (_ctr.get("blocking") or [])[:5]:
                    st.error(str(_bl))
            if should_enforce_data_contract_stop(release_client_mode=_is_release_client_mode()) and not _ctr.get(
                "ok"
            ):
                st.stop()

    # Use project data as main df for backward compatibility
    df = st.session_state.project_data

    # Dashboard selection — данные есть, если загружен MSP/ресурсы/TESSA/1С ДЗ/обороты (web_loader).
    has_project_data = df is not None and not df.empty
    resources_data = st.session_state.get("resources_data")
    technique_data = st.session_state.get("technique_data")
    tessa_data = st.session_state.get("tessa_data")
    tessa_tasks_data = st.session_state.get("tessa_tasks_data")
    debit_credit_data = st.session_state.get("debit_credit_data")
    ref_dannye = st.session_state.get("reference_1c_dannye")
    has_resources_data = resources_data is not None and not resources_data.empty
    has_technique_data = technique_data is not None and not technique_data.empty
    has_tessa_data = tessa_data is not None and not getattr(tessa_data, "empty", True)
    has_tessa_tasks = tessa_tasks_data is not None and not getattr(tessa_tasks_data, "empty", True)
    has_debit_credit = debit_credit_data is not None and not getattr(debit_credit_data, "empty", True)
    has_ref_dannye = ref_dannye is not None and not getattr(ref_dannye, "empty", True)
    has_any_data = (
        has_project_data
        or has_resources_data
        or has_technique_data
        or has_tessa_data
        or has_tessa_tasks
        or has_debit_credit
        or has_ref_dannye
    )

    if has_any_data:
        # Выбор отчёта только из бокового меню (блок «Выбор панели» в основной области снят).
        from dashboards import get_dashboards, get_main_panel_report_lists

        _role = user.get("role") or "analyst"
        reason_options, budget_options, other_options = get_main_panel_report_lists(_role)
        if not reason_options and not budget_options and not other_options:
            st.error("Для вашей роли нет доступных отчётов. Обратитесь к администратору.")
            st.stop()

        all_allowed = list(reason_options) + list(budget_options) + list(other_options)
        all_allowed_set = set(all_allowed)

        if "current_dashboard" not in st.session_state:
            if (has_resources_data or has_technique_data) and not has_project_data:
                if has_technique_data and "ГДРС (техника)" in all_allowed_set:
                    st.session_state.current_dashboard = "ГДРС (техника)"
                elif has_resources_data and "ГДРС (люди)" in all_allowed_set:
                    st.session_state.current_dashboard = "ГДРС (люди)"
                elif "ГДРС" in all_allowed_set:
                    st.session_state.current_dashboard = "ГДРС"
                elif "ГДРС Техника" in all_allowed_set and has_technique_data:
                    st.session_state.current_dashboard = "ГДРС Техника"
                else:
                    st.session_state.current_dashboard = all_allowed[0]
            elif not has_project_data and (has_tessa_data or has_tessa_tasks):
                if "Неустраненные предписания" in all_allowed_set:
                    st.session_state.current_dashboard = "Неустраненные предписания"
                elif "Исполнительная документация" in all_allowed_set:
                    st.session_state.current_dashboard = "Исполнительная документация"
                else:
                    st.session_state.current_dashboard = all_allowed[0]
            elif not has_project_data and has_debit_credit:
                if "Дебиторская и кредиторская задолженность" in all_allowed_set:
                    st.session_state.current_dashboard = "Дебиторская и кредиторская задолженность"
                elif "Дебиторская и кредиторская задолженность подрядчиков" in all_allowed_set:
                    st.session_state.current_dashboard = (
                        "Дебиторская и кредиторская задолженность подрядчиков"
                    )
                else:
                    st.session_state.current_dashboard = all_allowed[0]
            else:
                st.session_state.current_dashboard = "Причины отклонений"

        cur = st.session_state.get("current_dashboard", "")
        if cur not in all_allowed_set:
            st.session_state.current_dashboard = all_allowed[0]
        # Повторно применяем report из deep-link после валидации доступных отчётов.
        _dl_report = (_dl.get("report") or "").strip()
        if _dl_report and _dl_report in all_allowed_set:
            st.session_state.current_dashboard = _dl_report

        st.session_state.dashboard_selected_from_menu = False

        selected_dashboard = st.session_state.current_dashboard

        dashboards_using_technique = (
            "ГДРС",
            "ГДРС (люди)",
            "ГДРС (техника)",
            "ГДРС Техника",
        )

        if selected_dashboard in dashboards_using_technique:
            if selected_dashboard in ("ГДРС (техника)", "ГДРС Техника"):
                df_for_render = (
                    technique_data
                    if has_technique_data
                    else (resources_data if has_resources_data else df)
                )
            elif selected_dashboard == "ГДРС (люди)":
                df_for_render = (
                    resources_data
                    if has_resources_data
                    else (technique_data if has_technique_data else df)
                )
            else:
                df_for_render = resources_data if has_resources_data else (
                    technique_data if has_technique_data else df
                )
        elif selected_dashboard in (
            "Неустраненные предписания",
            "Предписания по подрядчикам",
            "Исполнительная документация",
        ) and (not has_project_data) and has_tessa_data:
            df_for_render = tessa_data
        elif selected_dashboard in (
            "Дебиторская и кредиторская задолженность",
            "Дебиторская и кредиторская задолженность подрядчиков",
        ) and (not has_project_data) and has_debit_credit:
            df_for_render = debit_credit_data
        else:
            df_for_render = df

        try:
            with st.spinner("Загрузка отчёта…"):
                _render_active_dashboard(
                    selected_dashboard,
                    df_for_render,
                    release_mode=_is_release_client_mode(),
                )
        except Exception as e:
            st.error(f"Ошибка при отображении графика '{selected_dashboard}': {str(e)}")
            st.exception(e)
    else:
        # Welcome message
        st.info(
            """
        **Добро пожаловать в Панель аналитики проектов!**

        Эта панель предоставляет комплексную аналитику для управления проектами:

        **Доступные панели:**

        **Сроки (по правкам):**
        - **Причины отклонений** (вкладки: доли причин, динамика отклонений по месяцам, динамика причин), **Отклонение от базового плана**, **Контрольные точки**, **График проекта**

        **Финансы:**
        - **БДДС**, **БДР**, **Бюджет план/факт**, **Утверждённый бюджет**, **Прогнозный бюджет**, **ДЗ/КЗ подрядчиков**

        **Прочее (порядок в меню):**
        - **Девелоперские проекты**, **Сроки**, **Финансы**, **Проектные работы** (рабочая/проектная документация), **ГДРС** (в т.ч. график движения рабочей силы, СКУД), **Исполнительная документация**, **Предписания по подрядчикам**

        **Для начала работы:**
        1. Загрузите файл с данными (CSV или Excel) через боковую панель
        2. Выберите панель из меню боковой панели
        3. Используйте фильтры для фокусировки на конкретных данных
        """
        )


if __name__ == "__main__":
    main()
