import sys
from pathlib import Path

# Ensure app directory is first on path (for deployment when CWD may not be bi-analytics)
_app_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_app_dir))

import streamlit as st
import pandas as pd

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

                    submit_button = st.form_submit_button("Войти", type="primary", use_container_width=True)

                    submit_reset = st.form_submit_button("Забыли пароль?", use_container_width=True)

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

    st.markdown(
        '<h1 class="main-header">Панель аналитики проектов</h1>',
        unsafe_allow_html=True,
    )

    # Боковая панель с меню навигации
    render_sidebar_menu(current_page="reports")

    ensure_data_session_state()

    # Переключатель режима источника данных
    data_mode = st.radio(
        "Источник данных",
        ["Загрузить вручную", "Из папки web/", "FTP → web/"],
        horizontal=True,
        key="data_mode_radio",
    )

    if data_mode in ("Из папки web/", "FTP → web/"):

        from web_schema import init_web_schema, get_all_versions, get_active_version_id, activate_version
        from web_loader import load_all_from_web, web_dir_exists, read_version_to_session, get_web_dir

        init_web_schema()

        if data_mode == "FTP → web/":
            from ftp_sync import merge_ftp_config, streamlit_secrets_to_config, sync_ftp_to_web

            st.caption(
                "Секреты: файл `.streamlit/secrets.toml`, секция `[ftp]` "
                "(host, user, password, remote_dir, port, use_tls) "
                "или переменные окружения BI_FTP_HOST / BI_FTP_USER / BI_FTP_PASSWORD."
            )
            with st.expander("Параметры FTP вручную (если нет secrets)", expanded=False):
                _h = st.text_input("FTP host", key="ftp_host_override")
                _u = st.text_input("FTP user", key="ftp_user_override")
                _p = st.text_input("FTP password", type="password", key="ftp_pass_override")
                _d = st.text_input("Удалённая папка", value="/", key="ftp_remote_dir_override")

            cfg = merge_ftp_config(streamlit_secrets_to_config())
            if _h.strip():
                cfg["host"] = _h.strip()
            if _u.strip():
                cfg["user"] = _u.strip()
            if _p:
                cfg["password"] = _p
            if _d.strip():
                cfg["remote_dir"] = _d.strip()

            b_ftp = st.button("Скачать CSV с FTP в web/ и загрузить в БД")
            if b_ftp:
                if not cfg.get("host") or not cfg.get("user"):
                    st.error("Задайте host и user (secrets, env BI_FTP_* или поля выше).")
                else:
                    web_p = get_web_dir()
                    web_p.mkdir(parents=True, exist_ok=True)
                    with st.spinner("FTP: скачивание в web/…"):
                        ftp_res = sync_ftp_to_web(web_p, config=cfg, progress=lambda m: None)
                    if ftp_res.get("errors"):
                        for e in ftp_res["errors"]:
                            st.error(e)
                    else:
                        st.success(
                            f"С FTP скачано файлов: {len(ftp_res.get('downloaded', []))}, "
                            f"пропуск (не .csv): {ftp_res.get('skipped', 0)}"
                        )
                    with st.spinner("Читаю файлы из web/..."):
                        result = load_all_from_web()
                    st.cache_data.clear()
                    st.session_state.pop("web_version_id", None)
                    for w in result.get("warnings", []):
                        st.warning(w)
                    if result.get("errors"):
                        st.warning(
                            f"Загружено: {result['loaded']}, пропущено: {result['skipped']}"
                        )
                        for err in result["errors"]:
                            st.error(err)
                    else:
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
                    with st.expander("Диагностика колонок (первые файлы)", expanded=False):
                        for row in result.get("diagnostics", [])[:40]:
                            st.json(row)
                    st.rerun()

        col1, col2 = st.columns([1, 3])

        with col1:

            if data_mode == "Из папки web/" and st.button("Загрузить из web/"):

                if not web_dir_exists():

                    st.error("Папка web/ не найдена в корне проекта.")

                else:

                    with st.spinner("Читаю файлы из web/..."):
                        result = load_all_from_web()

                    st.cache_data.clear()
                    # Сбрасываем web_version_id чтобы принудительно перечитать данные
                    st.session_state.pop("web_version_id", None)

                    for w in result.get("warnings", []):
                        st.warning(w)

                    if result["errors"]:

                        st.warning(f"Загружено: {result['loaded']}, пропущено: {result['skipped']}")

                        for err in result["errors"]:

                            st.error(err)
                    else:

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
                    with st.expander("Диагностика колонок", expanded=False):
                        for row in result.get("diagnostics", [])[:40]:
                            st.json(row)

                    st.rerun()

        # Селектор версий
        versions = get_all_versions()

        if versions:
            version_labels = {
                f"{v['created_at']}  |  файлов: {v['files_count']}, строк: {v['rows_count']}  {'✅' if v['is_active'] else ''}": v["id"]
                for v in versions
            }

            active_id = get_active_version_id()
            active_label = next((k for k, v in version_labels.items() if v == active_id), list(version_labels.keys())[0])
            selected_label = st.selectbox("Версия данных", list(version_labels.keys()), index=list(version_labels.keys()).index(active_label))
            selected_version_id = version_labels[selected_label]

            # Загружаем данные версии в session_state если ещё не загружены или версия сменилась
            if selected_version_id != st.session_state.get("web_version_id") or st.session_state.get("project_data") is None:
                activate_version(selected_version_id)
                read_version_to_session(selected_version_id)
                st.session_state["web_version_id"] = selected_version_id

        else:
            st.info("Нажмите «Загрузить из web/» чтобы прочитать файлы из папки web/.")

    else:

        # Ручная загрузка файлов (существующая логика)
        uploaded_files = st.file_uploader(
            "Загрузите файлы с данными (можно несколько)",
            type=["csv", "xlsx", "xls"],
            accept_multiple_files=True,
            help="Загрузите CSV или Excel файлы с данными проекта, ресурсов или техники",
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

    # Use project data as main df for backward compatibility
    df = st.session_state.project_data

    # ── Ролевая фильтрация проектов ────────────────────────────────────────────
    # manager видит только проекты, к которым ему явно выдан доступ
    if user.get("role") == "manager":
        from permissions import get_user_projects
        allowed = get_user_projects(user["id"])
        if not allowed:
            st.warning(
                "У вас нет доступа ни к одному проекту. "
                "Обратитесь к администратору."
            )
            st.stop()
        proj_col = "project name"
        if df is not None and not df.empty and proj_col in df.columns:
            df = df[df[proj_col].isin(allowed)].copy()
            if df.empty:
                st.warning(
                    "У вас нет доступа ни к одному из загруженных проектов. "
                    "Обратитесь к администратору."
                )
                st.stop()
    # ── Конец ролевой фильтрации ───────────────────────────────────────────────

    # Dashboard selection - allow access if any data is loaded (project, resources, or technique)
    has_project_data = df is not None and not df.empty
    resources_data = st.session_state.get("resources_data")
    technique_data = st.session_state.get("technique_data")
    has_resources_data = resources_data is not None and not resources_data.empty
    has_technique_data = technique_data is not None and not technique_data.empty
    has_any_data = has_project_data or has_resources_data or has_technique_data

    if has_any_data:
        # Check if dashboard was selected from sidebar menu
        dashboard_selected_from_menu = st.session_state.get(
            "dashboard_selected_from_menu", False
        )
        current_dashboard = st.session_state.get("current_dashboard", "")

        # Initialize session state for dashboard selection
        if "current_dashboard" not in st.session_state:

            if (has_resources_data or has_technique_data) and not has_project_data:

                st.session_state.current_dashboard = "ГДРС"

            else:

                st.session_state.current_dashboard = "Динамика отклонений"

        # If dashboard was selected from sidebar menu, show only the selected dashboard
        # without the selection panels
        if dashboard_selected_from_menu and current_dashboard:
            # Display only the selected dashboard
            selected_dashboard = current_dashboard
            # Reset the flag after processing (will be reset after rerun if button clicked)
            st.session_state.dashboard_selected_from_menu = False

            dashboards_using_technique = ("ГДРС",)

            dashboards_using_resources = ("График движения рабочей силы", "СКУД стройка")

            if selected_dashboard == "ГДРС":

                # Табы используют ресурсы и/или технику из session_state; передаём что есть для fallback

                df_for_render = resources_data if has_resources_data else (technique_data if has_technique_data else df)

            elif selected_dashboard in dashboards_using_technique:

                df_for_render = technique_data if has_technique_data else df

            elif selected_dashboard in dashboards_using_resources:

                df_for_render = resources_data if has_resources_data else (technique_data if has_technique_data else df)

            else:

                df_for_render = df

            # Route to selected dashboard (локальный словарь, без импорта из dashboards)
            try:
                from dashboards import get_dashboards
                dashboards = get_dashboards()
                render_fn = dashboards.get(selected_dashboard)
                if render_fn:
                    if df_for_render is None or (
                        isinstance(df_for_render, pd.DataFrame) and df_for_render.empty
                    ):
                        st.warning(
                            f"Нет данных для отчёта «{selected_dashboard}». "
                            "Загрузите данные (вручную, папка web/ или FTP), "
                            "либо выберите другой отчёт."
                        )
                    else:
                        render_fn(df_for_render)
                else:
                    st.warning(
                        f"График '{selected_dashboard}' не найден. Пожалуйста, выберите другой график."
                    )
            except Exception as e:
                st.error(
                    f"Ошибка при отображении графика '{selected_dashboard}': {str(e)}"
                )
                st.exception(e)

            # Stop here - don't show selection panels
            st.stop()

        # Выбор панели - перенесен в основную область
        st.markdown("### Выбор панели")

        # Единый источник списка отчётов — dashboards.REPORT_CATEGORIES (4 категории)
        from dashboards import REPORT_CATEGORIES
        _role = user.get("role") or "analyst"
        reason_options = filter_reports_for_role(_role, list(REPORT_CATEGORIES[0][1]))
        budget_options = filter_reports_for_role(_role, list(REPORT_CATEGORIES[1][1]))
        # Объединяем категории 2 ("Здоровье проектов") и 3 ("Прочее") в один раздел
        other_options = filter_reports_for_role(
            _role,
            list(REPORT_CATEGORIES[2][1])
            + (list(REPORT_CATEGORIES[3][1]) if len(REPORT_CATEGORIES) > 3 else []),
        )
        if not reason_options and not budget_options and not other_options:
            st.error("Для вашей роли нет доступных отчётов. Обратитесь к администратору.")
            st.stop()

        # Determine current selection indices based on current_dashboard
        # Also sync radio button values in session_state when dashboard is selected from menu
        dashboard_selected_from_menu = st.session_state.get(
            "dashboard_selected_from_menu", False
        )

        # Determine indices and sync session_state for radio buttons
        # When dashboard is selected from menu, we need to ensure radio buttons reflect the selection
        current_dashboard = st.session_state.get("current_dashboard", "")

        # If dashboard was selected from menu, sync all radio buttons
        # We need to set the actual option value, not the index, for Streamlit radio buttons
        if dashboard_selected_from_menu and current_dashboard:
            # Set the selected radio button to the correct value (not index)
            if current_dashboard in reason_options:
                st.session_state.reason_radio = current_dashboard
                if budget_options:
                    st.session_state.budget_radio = budget_options[0]
                if other_options:
                    st.session_state.other_radio = other_options[0]
            elif current_dashboard in budget_options:
                st.session_state.budget_radio = current_dashboard
                if reason_options:
                    st.session_state.reason_radio = reason_options[0]
                if other_options:
                    st.session_state.other_radio = other_options[0]
            elif current_dashboard in other_options:
                st.session_state.other_radio = current_dashboard
                if reason_options:
                    st.session_state.reason_radio = reason_options[0]
                if budget_options:
                    st.session_state.budget_radio = budget_options[0]

        # Синхронизируем радиокнопки с current_dashboard при каждой загрузке,
        # чтобы после выбора отчёта из бокового меню (например БДДС) отображался правильный пункт
        if current_dashboard:
            if current_dashboard in reason_options:
                st.session_state.reason_radio = current_dashboard
            if current_dashboard in budget_options:
                st.session_state.budget_radio = current_dashboard
            if current_dashboard in other_options:
                st.session_state.other_radio = current_dashboard

        # Determine indices from session_state or current_dashboard
        # Streamlit radio stores the actual option value, not the index
        reason_index = 0
        if current_dashboard in reason_options:
            reason_index = reason_options.index(current_dashboard)
        elif "reason_radio" in st.session_state:
            try:
                # session_state contains the actual option value, not index
                if st.session_state.reason_radio in reason_options:
                    reason_index = reason_options.index(st.session_state.reason_radio)
                else:
                    # If value is not in options, use default
                    reason_index = 0
            except (ValueError, TypeError, IndexError):
                reason_index = 0

        budget_index = 0
        if current_dashboard in budget_options:
            budget_index = budget_options.index(current_dashboard)
        elif "budget_radio" in st.session_state:
            try:
                if st.session_state.budget_radio in budget_options:
                    budget_index = budget_options.index(st.session_state.budget_radio)
                else:
                    budget_index = 0
            except (ValueError, TypeError, IndexError):
                budget_index = 0

        other_index = 0
        if current_dashboard in other_options:
            other_index = other_options.index(current_dashboard)
        elif "other_radio" in st.session_state:
            try:
                if st.session_state.other_radio in other_options:
                    other_index = other_options.index(st.session_state.other_radio)
                else:
                    other_index = 0
            except (ValueError, TypeError, IndexError):
                other_index = 0

        # Определяем, какой expander должен быть развернут при выборе из меню
        current_dashboard = st.session_state.get("current_dashboard", "")

        # Определяем, какой expander разворачивать
        expand_reason = True  # По умолчанию разворачиваем первый
        expand_budget = False
        expand_other = False

        if dashboard_selected_from_menu and current_dashboard:
            if current_dashboard in reason_options:
                expand_reason = True
                expand_budget = False
                expand_other = False
            elif current_dashboard in budget_options:
                expand_reason = False
                expand_budget = True
                expand_other = False
            elif current_dashboard in other_options:
                expand_reason = False
                expand_budget = False
                expand_other = True

        # Section 1: Причины отклонений
        with st.expander("Причины отклонений", expanded=expand_reason):
            reason_dashboard = st.radio(
                "",
                reason_options,
                key="reason_radio",
                label_visibility="collapsed",
                index=reason_index,
            )

        # Section 2: Аналитика по финансам
        with st.expander("Аналитика по финансам", expanded=expand_budget):
            budget_dashboard = st.radio(
                "",
                budget_options,
                key="budget_radio",
                label_visibility="collapsed",
                index=budget_index,
            )

        # Section 3: Прочее
        with st.expander("Прочее", expanded=expand_other):
            other_dashboard = st.radio(
                "",
                other_options,
                key="other_radio",
                label_visibility="collapsed",
                index=other_index,
            )

            # Determine selected dashboard based on radio button values
            # Note: Selection from sidebar menu is handled earlier and stops execution with st.stop()
            # So this code only runs when user selects dashboard via radio buttons in main area
            # Always use current radio button values to determine selected dashboard
            # This ensures that clicking on a radio button (even if already selected) works correctly
            if reason_dashboard != st.session_state.get(
                "prev_reason", reason_options[0]
            ):
                selected_dashboard = reason_dashboard
                st.session_state.current_dashboard = reason_dashboard
                st.session_state.prev_reason = reason_dashboard
                st.session_state.prev_budget = budget_options[0]
                st.session_state.prev_other = other_options[0]
            elif budget_dashboard != st.session_state.get(
                "prev_budget", budget_options[0]
            ):
                selected_dashboard = budget_dashboard
                st.session_state.current_dashboard = budget_dashboard
                st.session_state.prev_budget = budget_dashboard
                st.session_state.prev_reason = reason_options[0]
                st.session_state.prev_other = other_options[0]
            elif other_dashboard != st.session_state.get(
                "prev_other", other_options[0]
            ):
                selected_dashboard = other_dashboard
                st.session_state.current_dashboard = other_dashboard
                st.session_state.prev_other = other_dashboard
                st.session_state.prev_reason = reason_options[0]
                st.session_state.prev_budget = budget_options[0]
            else:
                # Сохраняем текущий выбор из меню/радио: приоритет у current_dashboard,
                # чтобы после выбора из бокового меню (например БДДС) не переключалось на первый пункт «Причины отклонений»
                current = st.session_state.current_dashboard
                if current and (
                    current in reason_options
                    or current in budget_options
                    or current in other_options
                ):
                    selected_dashboard = current
                elif reason_dashboard in reason_options:
                    selected_dashboard = reason_dashboard
                elif budget_dashboard in budget_options:
                    selected_dashboard = budget_dashboard
                elif other_dashboard in other_options:
                    selected_dashboard = other_dashboard
                else:
                    selected_dashboard = current or reason_dashboard
                st.session_state.current_dashboard = selected_dashboard

        dashboards_using_technique = ("ГДРС",)

        dashboards_using_resources = ("График движения рабочей силы", "СКУД стройка")

        if selected_dashboard == "ГДРС":

            df_for_render = resources_data if has_resources_data else (technique_data if has_technique_data else df)

        elif selected_dashboard in dashboards_using_technique:

            df_for_render = technique_data if has_technique_data else df

        elif selected_dashboard in dashboards_using_resources:

            df_for_render = resources_data if has_resources_data else (technique_data if has_technique_data else df)

        else:

            df_for_render = df

        # Route to selected dashboard via registry
        try:
            from dashboards import get_dashboards
            dashboards = get_dashboards()
            render_fn = dashboards.get(selected_dashboard)
            if render_fn:
                if df_for_render is None or (
                    isinstance(df_for_render, pd.DataFrame) and df_for_render.empty
                ):
                    st.warning(
                        f"Нет данных для отчёта «{selected_dashboard}». "
                        "Загрузите данные (вручную, web/ или FTP) или выберите другой отчёт."
                    )
                else:
                    render_fn(df_for_render)
            else:
                st.warning(
                    f"График '{selected_dashboard}' не найден. Пожалуйста, выберите другой график."
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

        **Причины отклонений:**
        - **Динамика отклонений** (табы: по месяцам, динамика, причины)
        - **Отклонение текущего срока от базового плана**, **Значения отклонений от базового плана**

        **💰 Аналитика по финансам:**
        - **БДДС** (табы: по периодам, по лотам); **БДР**, **Бюджет план/факт**, **Утвержденный бюджет**, **Прогнозный бюджет**

        **Прочее:**
        - **Выдача рабочей/проектной документации** (включая просрочку выдачи РД), **ГДРС** (табы: ГДРС люди/техника, динамика), **Исполнительная документация**

        **Для начала работы:**
        1. Загрузите файл с данными (CSV или Excel) через боковую панель
        2. Выберите панель из меню боковой панели
        3. Используйте фильтры для фокусировки на конкретных данных
        """
        )


if __name__ == "__main__":
    main()
