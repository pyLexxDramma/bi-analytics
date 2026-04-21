"""
Страница для настройки фильтров отчетов
"""
import sys
from pathlib import Path

# App root: walk up until we find auth.py + config.py (works when __file__ or CWD is wrong)
_here = Path(__file__).resolve().parent

_app_root = _here.parent

_p = _here.parent

while _p != _p.parent:

    if (_p / "auth.py").exists() and (_p / "config.py").exists():

        _app_root = _p

        break
    _p = _p.parent

sys.path.insert(0, str(_app_root))

# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ CSS CONNECT ¤ Start                                                    │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

def load_custom_css():

    css_path = _app_root / "static" / "css" / "style.css"

    if css_path.exists():

        with open(css_path, encoding="utf-8") as f:

            css_content = f.read()

        st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)

    else:

        st.warning(f"CSS файл не найден: {css_path}")

# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ CSS CONNECT ¤ End                                                      │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

import streamlit as st
import pandas as pd

_TABLE_CSS = '<style>.ht-wrap{overflow-x:auto;margin:.5rem 0 1rem}.ht{width:100%;border-collapse:collapse;font-size:13px;font-family:Inter,system-ui,sans-serif}.ht th{position:sticky;top:0;background:#1a1c23;color:#fafafa;padding:8px 12px;text-align:left;border-bottom:2px solid #444;font-weight:600;white-space:nowrap}.ht td{padding:6px 12px;border-bottom:1px solid #333;color:#e0e0e0;white-space:nowrap;max-width:400px;overflow:hidden;text-overflow:ellipsis}.ht tr:hover td{background:#262833}</style>'

def _html_table(df, max_rows=300):
    show = df.head(max_rows).copy()
    for col in show.columns:
        show[col] = [str(v) if pd.notna(v) else "" for v in show[col]]
    html = show.to_html(index=False, classes="ht", escape=True, border=0)
    st.markdown(_TABLE_CSS + '<div class="ht-wrap">' + html + '</div>', unsafe_allow_html=True)

from auth import (
    check_authentication,
    get_current_user,
    require_auth,
    has_admin_access,
    get_user_role_display,
    ROLES,
    init_db,
    render_sidebar_menu
)
from config import switch_page_app
try:
    from filters import (
        get_default_filters,
        set_default_filter,
        delete_default_filter,
        get_all_default_filters,
        copy_filters_to_role,
        AVAILABLE_REPORTS,
        FILTER_TYPES
    )

except ImportError as e:

    AVAILABLE_REPORTS = []

    FILTER_TYPES = {}

    def get_default_filters(*args, **kwargs):

        return {}

    def set_default_filter(*args, **kwargs):

        return False

    def delete_default_filter(*args, **kwargs):

        return False

    def get_all_default_filters(*args, **kwargs):

        return []

    def copy_filters_to_role(*args, **kwargs):

        return False

    import warnings

    warnings.warn(f"Ошибка импорта модуля filters: {e}")

try:

    from logger import log_action

except ImportError:

    def log_action(*args, **kwargs):

        pass

# Инициализация базы данных
init_db()

# Проверка, что мы в контексте Streamlit
def is_streamlit_context():

    """Проверка, что код выполняется в контексте Streamlit"""

    try:

        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None

    except:

        return False

# Выполняем код только в контексте Streamlit
if is_streamlit_context():
    # Настройка страницы
    st.set_page_config(
        page_title="Параметры отчетов - BI Analytics",
        page_icon="⚙️",
        layout="wide",
        menu_items={
            'Get Help': None,
            'Report a bug': None,
            'About': None
        }
    )

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ CSS CONNECT ¤ Start                                                │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    load_custom_css()

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ CSS CONNECT ¤ End                                                  │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    # Проверка авторизации
    require_auth()

    user = get_current_user()

    # Проверка, что пользователь получен
    if not user:

        st.error("Ошибка получения данных пользователя")

        st.stop()

    # Проверка прав доступа - параметры отчетов доступны только администраторам
    if not has_admin_access(user['role']):

        st.error("У вас нет доступа к этой странице")

        st.info("Доступ к параметрам отчетов имеют только администраторы и суперадминистраторы.")

        if st.button("Вернуться к отчетам"):

            switch_page_app("project_visualization_app.py")

        st.stop()

    # Боковая панель с меню навигации
    render_sidebar_menu(current_page="analyst_params")

    # Заголовок
    st.title("⚙️ Параметры отчетов")

    st.markdown("---")

    # Информация о текущем пользователе
    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric("Пользователь", user['username'])

    with col2:

        st.metric("Роль", get_user_role_display(user['role']))

    with col3:

        if st.button("Выйти"):

            from auth import logout

            log_action(user['username'], 'logout', 'Выход из системы')

            logout()

            st.switch_page("project_visualization_app.py")

    st.markdown("---")

    st.info("""
    Здесь вы можете настроить фильтры по умолчанию для всех ролей и отчетов.
    Фильтры определяют значения по умолчанию для различных параметров отчетов.
    """)

    st.markdown("---")

    # Вкладки вместо radio
    tab_setup, tab_view_all, tab_copy = st.tabs([
        "Настроить фильтры",
        "Просмотр всех фильтров",
        "Копирование фильтров"
    ])

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 1: Настроить фильтры ¤ Start                                   │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab_setup:

        st.subheader("Настройка фильтров")

        with st.form("filter_form"):

            col1, col2 = st.columns(2)

            with col1:

                selected_role = st.selectbox(
                    "Роль *",
                    options=list(ROLES.keys()),
                    format_func=lambda x: ROLES[x],
                    key="setup_role"
                )
                selected_report = st.selectbox(
                    "Отчет *",
                    options=AVAILABLE_REPORTS,
                    key="setup_report"
                )

            with col2:

                filter_key = st.text_input(
                    "Ключ фильтра *",
                    help="Например: selected_project, date_range, etc.",
                    key="setup_key"
                )
                filter_type = st.selectbox(
                    "Тип фильтра *",
                    options=list(FILTER_TYPES.keys()),
                    format_func=lambda x: FILTER_TYPES[x],
                    key="setup_type"
                )

            filter_value = st.text_input(
                "Значение фильтра",
                help="Для select/multiselect — JSON: [\"значение1\", \"значение2\"]",
                key="setup_value"
            )

            submitted = st.form_submit_button("Сохранить фильтр", type="primary")

            if submitted:

                if filter_key and selected_role and selected_report:

                    if set_default_filter(
                        selected_role, selected_report, filter_key, filter_value,
                        filter_type, user['username']
                    ):
                        log_action(
                            user['username'],
                            'set_default_filter',
                            f'Установлен фильтр {filter_key} для роли {get_user_role_display(selected_role)} в отчете {selected_report}'
                        )

                        st.success("Фильтр успешно сохранен!")

                        st.rerun()

                    else:

                        st.error("Ошибка при сохранении фильтра")
                else:

                    st.warning("Заполните обязательные поля (отмечены *)")

        st.markdown("---")

        # Текущие фильтры
        st.subheader("Текущие фильтры")

        col1, col2 = st.columns(2)

        with col1:

            view_role = st.selectbox(
                "Роль для просмотра",
                options = ['Все'] + list(ROLES.keys()),
                format_func = lambda x: ROLES.get(x, x) if x != 'Все' else x,
                key = 'view_role_setup'
            )

        with col2:

            view_report = st.selectbox(
                "Отчет для просмотра",
                options = ['Все'] + AVAILABLE_REPORTS,
                key = 'view_report_setup'
            )

        filters = get_all_default_filters(
            role = None if view_role == 'Все' else view_role,
            report_name = None if view_report == 'Все' else view_report
        )

        if filters:

            filters_data = []

            for f in filters:

                filters_data.append({
                    'Роль': get_user_role_display(f['role']),
                    'Отчет': f['report_name'],
                    'Ключ': f['filter_key'],
                    'Значение': f['filter_value'] or '-',
                    'Тип': FILTER_TYPES.get(f['filter_type'], f['filter_type']),
                    'Обновлено': f['updated_at'] or '-',
                    'Обновил': f['updated_by'] or '-'
                })

            df_filters = pd.DataFrame(filters_data)

            _html_table(df_filters)

            # Удаление фильтров
            st.markdown("#### Удаление фильтра")

            with st.form("delete_filter_form"):

                del_col1, del_col2, del_col3 = st.columns(3)

                with del_col1:

                    del_role = st.selectbox(
                        "Роль",
                        options=list(ROLES.keys()),
                        format_func=lambda x: ROLES[x],
                        key='del_role_setup'
                    )

                with del_col2:

                    del_report = st.selectbox(
                        "Отчет",
                        options=AVAILABLE_REPORTS,
                        key='del_report_setup'
                    )

                with del_col3:

                    role_filters = get_default_filters(del_role, del_report)

                    del_filter_key = st.selectbox(
                        "Ключ фильтра",
                        options=list(role_filters.keys()) if role_filters else [],
                        key='del_key_setup'
                    )

                if st.form_submit_button("Удалить фильтр", type="primary"):

                    if del_filter_key:

                        if delete_default_filter(del_role, del_report, del_filter_key):

                            log_action(
                                user['username'],
                                'delete_default_filter',
                                f'Удален фильтр {del_filter_key} для роли {get_user_role_display(del_role)} в отчете {del_report}'
                            )

                            st.success("Фильтр успешно удален!")

                            st.rerun()

                        else:

                            st.error("Ошибка при удалении фильтра")
        else:

            st.info("Фильтры не найдены")

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 1: Настроить фильтры ¤ End                                     │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 2: Просмотр всех фильтров ¤ Start                              │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab_view_all:

        st.subheader("Все фильтры по умолчанию")

        all_filters = get_all_default_filters()

        if all_filters:

            filters_by_role_report = {}

            for f in all_filters:

                key = (f['role'], f['report_name'])

                filters_by_role_report.setdefault(key, []).append(f)

            for (role, report), filters_list in sorted(filters_by_role_report.items()):

                with st.expander(f"{get_user_role_display(role)} - {report} ({len(filters_list)} фильтров)"):

                    filters_data = []

                    for f in filters_list:

                        filters_data.append({
                            'Ключ': f['filter_key'],
                            'Значение': f['filter_value'] or '-',
                            'Тип': FILTER_TYPES.get(f['filter_type'], f['filter_type']),
                            'Обновлено': f['updated_at'] or '-',
                            'Обновил': f['updated_by'] or '-'
                        })

                    df = pd.DataFrame(filters_data)

                    _html_table(df)
        else:

            st.info("Фильтры не настроены")

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 2: Просмотр всех фильтров ¤ End                                │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 3: Копирование фильтров ¤ Start                                │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab_copy:

        st.subheader("Копирование фильтров")

        st.info("Скопируйте все фильтры из одной роли в другую. Можно для конкретного отчета или всех.")

        with st.form("copy_filters_form"):

            col1, col2 = st.columns(2)

            with col1:

                source_role = st.selectbox(
                    "Исходная роль",
                    options=list(ROLES.keys()),
                    format_func=lambda x: ROLES[x],
                    key="copy_source_role"
                )

            with col2:

                target_role = st.selectbox(
                    "Целевая роль",
                    options=list(ROLES.keys()),
                    format_func=lambda x: ROLES[x],
                    key="copy_target_role"
                )

            copy_report = st.selectbox(
                "Отчет (оставьте 'Все' для копирования всех)",
                options=['Все'] + AVAILABLE_REPORTS,
                key="copy_report"
            )

            if st.form_submit_button("Копировать фильтры", type="primary"):

                if source_role == target_role:

                    st.warning("⚠️ Исходная и целевая роли не могут быть одинаковыми")

                else:

                    report_name = None if copy_report == 'Все' else copy_report

                    if copy_filters_to_role(source_role, target_role, report_name):

                        log_action(
                            user['username'],
                            'copy_filters',
                            f'Скопированы фильтры из роли {get_user_role_display(source_role)} в роль {get_user_role_display(target_role)}' +
                            (f' для отчета {copy_report}' if report_name else ' для всех отчетов')
                        )

                        st.success("Фильтры успешно скопированы!")

                        st.rerun()

                    else:

                        st.error("Ошибка при копировании фильтров")

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 3: Копирование фильтров ¤ End                                  │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    st.markdown("---")

    if st.button("← Вернуться к отчетам"):

        switch_page_app("project_visualization_app.py")
