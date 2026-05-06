import sys
from pathlib import Path

# Ensure app directory is first on path (for deployment when CWD may not be bi-analytics)
_app_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_app_dir))

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

# Инициализация базы данных (все таблицы создаются в db.init_all_tables)
init_db()

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

# R23-08: перевод подписей встроенных пресетов st.date_input на русский.
# Streamlit вырезает <script> из st.markdown, поэтому используем components.html
# с height=0 — невидимый iframe, внутри которого скрипт меняет текст у родителя.
try:
    import streamlit.components.v1 as _components
    _components.html(
        """
        <script>
        (function() {
            try {
                const root = window.parent && window.parent.document ? window.parent.document : document;
                const map = {
                    'Choose a date range': 'Выберите период',
                    'Past Week': 'Прошлая неделя',
                    'Past Month': 'Прошлый месяц',
                    'Past 3 Months': 'Последние 3 месяца',
                    'Past 6 Months': 'Последние 6 месяцев',
                    'Past Year': 'Последний год',
                    'Past 2 Years': 'Последние 2 года'
                };
                const translate = (r) => {
                    if (!r || !r.body) return;
                    const walker = r.createTreeWalker(r.body, NodeFilter.SHOW_TEXT, null);
                    let node;
                    while ((node = walker.nextNode())) {
                        const val = (node.nodeValue || '').trim();
                        if (val && Object.prototype.hasOwnProperty.call(map, val)) {
                            node.nodeValue = node.nodeValue.replace(val, map[val]);
                        }
                    }
                };
                translate(root);
                if (window._ruDateObs) { try { window._ruDateObs.disconnect(); } catch (e) {} }
                const obs = new MutationObserver(() => translate(root));
                obs.observe(root.body, { childList: true, subtree: true });
                window._ruDateObs = obs;
            } catch (e) { /* cross-origin or unsupported */ }
        })();
        </script>
        """,
        height=0,
    )
except Exception:
    pass

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

try:
    from dashboards.ui_quiet import inject_unified_filters_css

    inject_unified_filters_css(st)
except Exception:
    pass

# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ CSS CONNECT ¤ End                                                      │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

# ==================== MAIN APP ====================
def main():

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
                        "",
                        key="login_username",
                        placeholder="Имя пользователя",
                        autocomplete="off",
                        value=""
                    )

                    password = st.text_input(
                        "",
                        type="password",
                        key="login_password",
                        placeholder="Пароль",
                        autocomplete="new-password",
                        value=""
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

    # Переключатель режима источника данных
    data_mode_options = ["Загрузить вручную", "Из папки web/", "FTP → web/"]
    if _is_release_client_mode():
        # На release: ручная загрузка убрана для обычных пользователей
        # (грузит файл только в session_state — клиент путается, куда «делись» данные).
        # Админу/суперадмину оставляем «Загрузить вручную» как страховку,
        # если FTP/web/ недоступны и нужно срочно подсунуть свежий MSP/1С/TESSA.
        try:
            _u = get_current_user()
            _is_admin = bool(_u and has_admin_access(_u.get("role", "")))
        except Exception:
            _is_admin = False
        if _is_admin:
            data_mode_options = ["Из папки web/", "FTP → web/", "Загрузить вручную"]
        else:
            data_mode_options = ["Из папки web/", "FTP → web/"]

    def _queue_web_folder_load_on_mode_change():
        try:
            v = st.session_state.get("data_mode_radio")
            # Локальная папка web/ читается и в режиме «Из папки web/», и в «FTP → web/»
            # (FTP-скачивание — отдельная кнопка; до неё показываем уже лежащие в web/ файлы).
            if v in ("Из папки web/", "FTP → web/"):
                st.session_state["_pending_web_folder_load"] = True
        except Exception:
            pass

    data_mode = st.radio(
        "Источник данных",
        data_mode_options,
        horizontal=True,
        key="data_mode_radio",
        on_change=_queue_web_folder_load_on_mode_change,
    )

    if data_mode in ("Из папки web/", "FTP → web/"):

        from config import ignore_demo_data_files
        from data_health import save_schema_health_report, build_environment_fingerprint
        from data_readiness import build_data_readiness_report, render_data_readiness_expander
        from web_schema import init_web_schema, get_all_versions, get_active_version_id, activate_version
        from web_loader import load_all_from_web, web_dir_exists, read_version_to_session, get_web_dir

        if ignore_demo_data_files() and not _is_release_client_mode():
            st.caption(
                "На сервере задано BI_ANALYTICS_IGNORE_DEMO: не загружаются демо "
                "sample_*.csv и файлы в каталогах new_csv/; используйте боевые MSP/1С/TESSA в web/."
            )

        init_web_schema()

        def _perform_load_from_web_folder() -> None:
            """Сканирование web/, запись в SQLite и обновление session_state (как кнопка «Загрузить из web/»)."""
            if not web_dir_exists():
                st.error(
                    "Не найден ни локальный каталог web/ рядом с приложением, "
                    "ни папка Analitics/web (уровнем выше репозитория), "
                    "ни пути из переменной BI_ANALYTICS_WEB_EXTRA_PATHS."
                )
                return

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
                st.success(f"Загружено файлов: {result['loaded']}")
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
            # Release-клиент при первом заходе: пробуем подтянуть свежие файлы с FTP
            # (если в st.secrets[ftp] / env BI_FTP_* настроены host+user), затем читаем web/.
            # Управление: BI_ANALYTICS_AUTO_FTP_ON_START=0 — отключить авто-FTP даже если настроен.
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
            st.session_state["_pending_web_folder_load"] = True
            st.session_state["_release_web_autoload_tried"] = True

        if (
            data_mode in ("Из папки web/", "FTP → web/")
            and st.session_state.pop("_pending_web_folder_load", False)
        ):
            _perform_load_from_web_folder()

        if data_mode == "FTP → web/":
            from ftp_sync import merge_ftp_config, streamlit_secrets_to_config, sync_ftp_to_web

            st.caption(
                "**Как обновить данные с FTP для клиента:**  \n"
                "1) Задайте доступ: секреты Streamlit `[ftp]`, либо переменные окружения "
                "`BI_FTP_HOST`, `BI_FTP_USER`, `BI_FTP_PASSWORD` (или пароль в `FTP_AI_PASSWORD`). "
                "Каталог на сервере — `BI_FTP_REMOTE_DIR` (типично **`/web`**).  \n"
                "2) Режим **«FTP → web/»** → кнопка **«Скачать CSV и JSON с FTP в web/ и загрузить в БД»** "
                "скачивает файлы в локальную папку `web/` и сразу выполняет то же чтение в SQLite, что и кнопка ниже.  \n"
                "3) **«Загрузить из web/»** — только перечитать уже лежащие на диске файлы (без FTP).  \n"
                "Актуальные снимки по дате в именах файлов включаются политикой `BI_ANALYTICS_WEB_LATEST_ONLY` "
                "(по умолчанию последний снимок; полная история — `=0`)."
            )

            with st.expander("Параметры FTP вручную (если нет secrets)", expanded=False):
                _h = st.text_input("FTP host", key="ftp_host_override")
                _u = st.text_input("FTP user", key="ftp_user_override")
                _p = st.text_input("FTP password", type="password", key="ftp_pass_override")
                _d = st.text_input("Удалённая папка", value="/web", key="ftp_remote_dir_override")

            cfg = merge_ftp_config(streamlit_secrets_to_config())
            if _h.strip():
                cfg["host"] = _h.strip()
            if _u.strip():
                cfg["user"] = _u.strip()
            if _p:
                cfg["password"] = _p
            if _d.strip():
                cfg["remote_dir"] = _d.strip()

            b_ftp = st.button("Скачать CSV и JSON с FTP в web/ и загрузить в БД")
            if b_ftp:
                if not cfg.get("host") or not cfg.get("user"):
                    st.error("Задайте host и user (secrets, env BI_FTP_* или поля выше).")
                else:
                    web_p = get_web_dir()
                    web_p.mkdir(parents=True, exist_ok=True)
                    with st.spinner("FTP: скачивание в web/…"):
                        ftp_res = sync_ftp_to_web(
                            web_p,
                            config=cfg,
                            extensions=(".csv", ".json"),
                            progress=lambda m: None,
                        )
                    if ftp_res.get("errors"):
                        for e in ftp_res["errors"]:
                            st.error(e)
                    else:
                        st.success(
                            f"С FTP скачано файлов: {len(ftp_res.get('downloaded', []))}, "
                            f"пропуск (не CSV/JSON): {ftp_res.get('skipped', 0)}"
                        )
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
                        from web_schema import get_active_version_id as _gav_ftp

                        _na_ftp = _gav_ftp()
                        if _na_ftp is not None:
                            st.session_state["web_version_pick_id"] = int(_na_ftp)
                    except Exception:
                        pass
                    _release_quiet_ftp = _is_release_client_mode()
                    if not _release_quiet_ftp:
                        for w in result.get("warnings", []):
                            st.warning(w)
                    if result.get("errors"):
                        st.warning(
                            f"Загружено: {result['loaded']}, пропущено: {result['skipped']}"
                        )
                        for err in result["errors"]:
                            st.error(err)
                    elif not _release_quiet_ftp:
                        st.success(f"В БД загружено файлов: {result['loaded']}")
                    try:
                        from logger import log_action
                        u = get_current_user()
                        if u:
                            log_action(
                                u["username"],
                                "data_loaded",
                                f"web+FTP: loaded={result.get('loaded')}, skipped={result.get('skipped')}",
                            )
                    except Exception:
                        pass
                    if not _release_quiet_ftp:
                        with st.expander("Справка: колонки загрузки (первые файлы)", expanded=False):
                            for row in result.get("diagnostics", [])[:40]:
                                st.json(row)
                    st.rerun()

        col1, col2 = st.columns([1, 3])

        with col1:

            if data_mode in ("Из папки web/", "FTP → web/") and st.button("Загрузить из web/"):
                _perform_load_from_web_folder()

        # Селектор версий
        versions = get_all_versions()

        if versions:
            # Опции — по id: стабильные подписи (без «✅» в ключе), иначе при смене active все строки
            # пересобираются и selectbox теряет выбор.
            active_id = get_active_version_id()
            ids_ordered = [int(v["id"]) for v in versions]
            by_id = {int(v["id"]): v for v in versions}

            def _fmt_version_option(vid: int) -> str:
                v = by_id.get(int(vid)) or {}
                base = (
                    f"{v.get('created_at', '')}  |  файлов: {v.get('files_count', 0)}, "
                    f"строк: {v.get('rows_count', 0)}"
                )
                try:
                    cur = get_active_version_id()
                except Exception:
                    cur = active_id
                if cur is not None and int(vid) == int(cur):
                    return f"{base}  ✅"
                return base

            if "web_version_pick_id" not in st.session_state:
                st.session_state["web_version_pick_id"] = (
                    int(active_id)
                    if active_id is not None and int(active_id) in ids_ordered
                    else ids_ordered[0]
                )
            elif int(st.session_state["web_version_pick_id"]) not in ids_ordered:
                st.session_state["web_version_pick_id"] = (
                    int(active_id)
                    if active_id is not None and int(active_id) in ids_ordered
                    else ids_ordered[0]
                )

            selected_version_id = st.selectbox(
                "Версия данных",
                ids_ordered,
                format_func=_fmt_version_option,
                key="web_version_pick_id",
            )

            # Загружаем данные версии в session_state если ещё не загружены или версия сменилась
            if selected_version_id != st.session_state.get("web_version_id") or st.session_state.get("project_data") is None:
                activate_version(selected_version_id)
                read_version_to_session(selected_version_id)
                st.session_state["web_version_id"] = selected_version_id
                try:
                    st.session_state["last_data_readiness"] = build_data_readiness_report()
                    st.session_state["last_data_schema_health"] = save_schema_health_report(
                        load_result=st.session_state.get("last_load_result")
                    )
                    st.session_state["last_env_fingerprint"] = build_environment_fingerprint(
                        st.session_state.get("last_load_result")
                    )
                    from data_contract import evaluate_data_contract

                    st.session_state["last_data_contract"] = evaluate_data_contract(
                        st.session_state.get("last_load_result")
                    )
                except Exception:
                    pass

        else:
            st.info(
                "При первом включении режима файлы считываются автоматически. "
                "Повторно нажмите «Загрузить из web/», если обновили файлы на диске."
            )

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
                st.caption("Сформирован отчёт схем: `data_health_report.md` и `data_health_report.json` в корне приложения.")
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
            render_contract_banner(_ctr)
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
                if "ГДРС" in all_allowed_set:
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
                if "Дебиторская и кредиторская задолженность подрядчиков" in all_allowed_set:
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
            "ГДРС Техника",
        )

        if selected_dashboard in dashboards_using_technique:
            df_for_render = resources_data if has_resources_data else (
                technique_data if has_technique_data else df
            )
        elif selected_dashboard in (
            "Неустраненные предписания",
            "Предписания по подрядчикам",
            "Исполнительная документация",
        ) and (not has_project_data) and has_tessa_data:
            df_for_render = tessa_data
        elif selected_dashboard == "Дебиторская и кредиторская задолженность подрядчиков" and (
            not has_project_data
        ) and has_debit_credit:
            df_for_render = debit_credit_data
        else:
            df_for_render = df

        try:
            dashboards = get_dashboards()
            render_fn = dashboards.get(selected_dashboard)
            if render_fn:
                if df_for_render is None or (
                    isinstance(df_for_render, pd.DataFrame) and df_for_render.empty
                ):
                    st.warning(
                        f"Нет данных для отчёта «{selected_dashboard}». "
                        "Загрузите данные (вручную, web/ или FTP) или выберите другой отчёт "
                        "в боковом меню."
                    )
                else:
                    if _is_release_client_mode():
                        render_fn(df_for_render)
                    else:
                        tab_dash, tab_diag = st.tabs(["Дашборд", "Диагностика (dev)"])
                        with tab_dash:
                            render_fn(df_for_render)
                        with tab_diag:
                            render_dashboard_diagnostics_tab(
                                selected_dashboard,
                                df_for_render,
                                st.session_state,
                            )
            else:
                st.warning(
                    f"График '{selected_dashboard}' не найден. Выберите другой отчёт в боковом меню."
                )
                st.info(f"Текущий выбор: {selected_dashboard}")
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
