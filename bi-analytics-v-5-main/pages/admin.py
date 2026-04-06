"""
Административная панель
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

# def load_custom_css():
#     css_path = _app_root / "static" / "css" / "style.css"
#     if css_path.exists():
#         with open(css_path, encoding="utf-8") as f:
#             css_content = f.read()
#         st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)
#     else:
#         st.warning(f"CSS файл не найден: {css_path}")

# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ CSS CONNECT ¤ End                                                      │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

import streamlit as st
import pandas as pd
from datetime import datetime
import sqlite3

from auth import (
    check_authentication,
    get_current_user,
    has_admin_access,
    require_auth,
    get_user_role_display,
    ROLES,
    init_db,
    render_sidebar_menu,
)
from config import DB_PATH
from logger import log_action, get_logs, get_logs_count
from settings import get_setting, set_setting, get_all_settings, SETTING_KEYS
from utils import format_dataframe_as_html, load_custom_css
from permissions import (
    grant_project_access,
    revoke_project_access,
    get_user_projects,
    get_project_users,
    get_all_project_permissions,
    has_project_access,
    get_all_projects,
)

try:
    from filters import (
        get_default_filters,
        set_default_filter,
        delete_default_filter,
        get_all_default_filters,
        copy_filters_to_role,
        AVAILABLE_REPORTS,
        FILTER_TYPES,
    )
except ImportError as e:
    # Определяем заглушки для избежания ошибок
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

    # Логируем ошибку, но не используем st, так как он может быть не инициализирован
    import warnings

    warnings.warn(f"Ошибка импорта модуля filters: {e}")

# Инициализация базы данных
init_db()


# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ Красивый формат даты ¤ Start                                           │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

def format_russian_datetime(dt_str):

    """Преобразует ISO-строку в формат '12 фев. 2026, 14:35' с неразрывными пробелами"""

    if not dt_str or dt_str in ("-", None, ""):

        return "-"

    try:
        import pytz
        from datetime import timezone

        dt_str_clean = dt_str.split('.')[0]
        dt = datetime.fromisoformat(dt_str_clean)

        # Если дата без timezone — считаем её UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Конвертируем в московское время
        moscow_tz = pytz.timezone("Europe/Moscow")
        dt = dt.astimezone(moscow_tz)

        months_ru = ["янв.", "фев.", "мар.", "апр.", "май", "июн.",
                     "июл.", "авг.", "сен.", "окт.", "ноя.", "дек."]
        month = months_ru[dt.month - 1]
        nbsp = "\u00A0"
        return f"{dt.day}{nbsp}{month}{nbsp}{dt.year},{nbsp}{dt:%H:%M}"

    except Exception:

        return dt_str

# ┌──────────────────────────────────────────────────────────────────────────┐ #
# │ ⊗ Красивый формат даты ¤ End                                             │ #
# └──────────────────────────────────────────────────────────────────────────┘ #

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
        page_title="Настройки - BI Analytics",
        page_icon="",
        layout="wide",
        menu_items={"Get Help": None, "Report a bug": None, "About": None},
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

    # Проверка прав доступа
    if not has_admin_access(user["role"]):

        st.error("У вас нет доступа к административной панели")

        st.info("Доступ к настройкам имеют только администраторы и суперадминистраторы.")

        if st.button("Вернуться к отчетам"):

            st.switch_page("project_visualization_app.py")

        st.stop()

    # Если пользователь прошел проверку, продолжаем выполнение

else:

    # Если не в контексте Streamlit, создаем заглушку для user
    user = None

# Весь остальной код выполняется только если user определен (т.е. в контексте Streamlit)
if user is not None:

    # Боковая панель с меню навигации
    render_sidebar_menu(current_page="admin")

    # Заголовок
    st.markdown("<h1 class='Buquhununee'>Административная панель</h1>", unsafe_allow_html=True)

    # JavaScript для автоматического скролла к содержимому выбранной вкладки
    st.markdown(
        """
        <script>
        (function() {
            function scrollToActiveTabContent() {
                setTimeout(function() {
                    // Находим активную панель вкладки (содержимое, не заголовок)
                    const activePanel = document.querySelector('[role="tabpanel"][aria-hidden="false"]');
                    if (!activePanel) return;

                    // Находим первый значимый элемент контента внутри панели
                    // Пропускаем заголовки вкладок и ищем реальное содержимое
                    const contentElements = activePanel.querySelectorAll('div[data-testid="stVerticalBlock"] > div, h1, h2, h3, .stSubheader');
                    let targetElement = null;

                    // Ищем первый элемент, который не является частью заголовка вкладки
                    for (let i = 0; i < contentElements.length; i++) {
                        const elem = contentElements[i];
                        // Проверяем, что элемент не находится в заголовке вкладки
                        if (!elem.closest('[data-baseweb="tab-list"]') &&
                            !elem.closest('[data-baseweb="tab"]')) {
                            targetElement = elem;
                            break;
                        }
                    }

                    // Если не нашли, используем саму панель, но с отступом
                    if (!targetElement) {
                        targetElement = activePanel;
                    }

                    // Вычисляем позицию с учетом отступа от верха
                    const elementPosition = targetElement.getBoundingClientRect().top;
                    const offsetPosition = elementPosition + window.pageYOffset - 100; // 100px отступ от верха

                    // Плавный скролл
                    window.scrollTo({
                        top: offsetPosition,
                        behavior: 'smooth'
                    });
                }, 200);
            }

            // Выполняем скролл при загрузке
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', scrollToActiveTabContent);
            } else {
                scrollToActiveTabContent();
            }

            // Отслеживаем клики по вкладкам
            document.addEventListener('click', function(e) {
                if (e.target.closest('[data-baseweb="tab"]')) {
                    scrollToActiveTabContent();
                }
            });

            // Отслеживаем изменения активной вкладки через MutationObserver
            const observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    if (mutation.type === 'attributes') {
                        // Проверяем изменения aria-selected или aria-hidden
                        if ((mutation.attributeName === 'aria-selected' &&
                             mutation.target.getAttribute('aria-selected') === 'true') ||
                            (mutation.attributeName === 'aria-hidden' &&
                             mutation.target.getAttribute('aria-hidden') === 'false' &&
                             mutation.target.getAttribute('role') === 'tabpanel')) {
                            scrollToActiveTabContent();
                        }
                    }
                });
            });

            // Наблюдаем за вкладками и панелями
            setTimeout(function() {
                const tabs = document.querySelectorAll('[data-baseweb="tab"]');
                const panels = document.querySelectorAll('[role="tabpanel"]');

                tabs.forEach(tab => {
                    observer.observe(tab, {
                        attributes: true,
                        attributeFilter: ['aria-selected']
                    });
                });

                panels.forEach(panel => {
                    observer.observe(panel, {
                        attributes: true,
                        attributeFilter: ['aria-hidden']
                    });
                });
            }, 500);
        })();
        </script>
    """,
        unsafe_allow_html=True,
    )

    # Вкладки административной панели
    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "Пользователи",
            "Статистика",
            "Логи",
            "Права доступа",
        ]
    )

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 1: Управление пользователями ¤ Start                           │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab1:

        st.markdown("<h2 class='Duquhununee'>Управление пользователями</h2>", unsafe_allow_html=True)

        # Список пользователей
        st.markdown("<h3 class='Muquhununee'>Список пользователей</h3>", unsafe_allow_html=True)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, username, role, email, created_at, last_login, is_active
            FROM users
            ORDER BY created_at DESC
        """
        )

        users = cursor.fetchall()

        conn.close()

        if users:
            users_data = []
            for u in users:
                created_formatted = format_russian_datetime(u[4]) if u[4] else "-"
                last_login_formatted = format_russian_datetime(u[5]) if u[5] else "Никогда"

                users_data.append(
                    {
                        "ID": u[0],
                        "Имя пользователя": u[1],
                        "Роль": get_user_role_display(u[2]),
                        "Email": u[3] or "-",
                        "Создан": created_formatted,
                        "Последний вход": last_login_formatted,
                        "Активен": "✅" if u[6] else "❌",
                    }
                )

            df_users = pd.DataFrame(users_data)
            html_table = format_dataframe_as_html(df_users)
            st.markdown(html_table, unsafe_allow_html=True)
        else:
            st.info("Пользователи не найдены")

        # st.markdown("---")

        # Добавление нового пользователя
        st.markdown("### Добавить нового пользователя")

        with st.form("add_user_form"):

            # ─── Ловушки для автозаполнения браузера ────────────────────────────────
            st.markdown('<input type="text"     name="fake_username"    style="display:none" autocomplete="username">',     unsafe_allow_html=True)
            st.markdown('<input type="password" name="fake_password"    style="display:none" autocomplete="new-password">', unsafe_allow_html=True)

            col1, col2 = st.columns(2)

            with col1:
                new_username = st.text_input("Имя пользователя *")
                new_email = st.text_input("Email")

            with col2:
                new_password = st.text_input("Пароль *", type="password")
                new_role = st.selectbox(
                    "Роль *", options=list(ROLES.keys()), format_func=lambda x: ROLES[x]
                )

            submitted = st.form_submit_button("Добавить пользователя", type="primary")

            if submitted:
                if new_username and new_password:
                    from auth import create_user

                    if create_user(
                        new_username,
                        new_password,
                        new_role,
                        new_email if new_email else None,
                        user["username"],
                    ):
                        st.success(f"Пользователь {new_username} успешно создан!")
                        st.rerun()
                    else:
                        st.error(
                            "Ошибка при создании пользователя. Возможно, пользователь с таким именем уже существует."
                        )
                else:
                    st.warning("Заполните обязательные поля (отмечены *)")

        # st.markdown("---")

        # Изменение роли пользователя
        st.markdown("### Изменить роль пользователя")

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, role FROM users WHERE is_active = 1 ORDER BY username"
        )
        active_users = cursor.fetchall()
        conn.close()

        if active_users:
            with st.form("change_role_form"):
                user_options = {
                    f"{u[1]} ({get_user_role_display(u[2])})": u[0]
                    for u in active_users
                }
                selected_user_display = st.selectbox(
                    "Выберите пользователя", options=list(user_options.keys())
                )
                selected_user_id = user_options[selected_user_display]

                # Получаем текущую роль
                selected_username = selected_user_display.split(" (")[0]
                current_role = None
                for u in active_users:
                    if u[0] == selected_user_id:
                        current_role = u[2]
                        break

                new_role = st.selectbox(
                    "Новая роль *",
                    options=list(ROLES.keys()),
                    format_func=lambda x: ROLES[x],
                    index=list(ROLES.keys()).index(current_role) if current_role else 0,
                )

                submitted = st.form_submit_button("Изменить роль", type="primary")

                if submitted:
                    if new_role != current_role:
                        conn = sqlite3.connect(DB_PATH)
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE users SET role = ? WHERE id = ?",
                            (new_role, selected_user_id),
                        )
                        conn.commit()
                        conn.close()

                        log_action(
                            user["username"],
                            "change_role",
                            f"Изменена роль пользователя {selected_username} с {get_user_role_display(current_role)} на {get_user_role_display(new_role)}",
                        )
                        st.success(
                            # f"✅ Роль пользователя {selected_username} успешно изменена на {get_user_role_display(new_role)}!"
                            f"Роль пользователя {selected_username} успешно изменена на {get_user_role_display(new_role)}!"
                        )
                        st.rerun()
                    else:
                        st.warning("Выберите другую роль")
        else:

            st.info("Нет активных пользователей")

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 1: Управление пользователями ¤ End                             │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 2: Статистика ¤ Start                                          │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab2:

        st.markdown("<h2 class='Duquhununee'>Статистика системы</h2>", unsafe_allow_html=True)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Общая статистика
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        active_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE last_login IS NOT NULL")
        users_with_login = cursor.fetchone()[0]

        # Статистика по ролям
        cursor.execute(
            """
            SELECT role, COUNT(*) as count
            FROM users
            GROUP BY role
        """
        )
        role_stats = cursor.fetchall()

        # Статистика логов
        total_logs = get_logs_count()
        recent_logs = get_logs_count(action="login")

        conn.close()

        col1, col2, col3, col4 = st.columns(4)

        with col1:

            st.metric("Всего пользователей", total_users)

        with col2:

            st.metric("Активных пользователей", active_users)

        with col3:

            st.metric("Пользователей с входом", users_with_login)

        with col4:

            st.metric("Всего действий в логах", total_logs)

        st.markdown("---")

        # Статистика по ролям
        st.markdown("### Распределение по ролям")
        if role_stats:
            role_data = [
                {"Роль": get_user_role_display(r[0]), "Количество": r[1]}
                for r in role_stats
            ]
            df_roles = pd.DataFrame(role_data)
            html_table = format_dataframe_as_html(df_roles)
            st.markdown(html_table, unsafe_allow_html=True)
        else:
            st.info("Нет данных")

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 2: Статистика ¤ End                                            │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 3: Логи действий ¤ Start                                       │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab3:

        st.markdown("<h2 class='Duquhununee'>Логи действий пользователей</h2>", unsafe_allow_html=True)

        # Фильтры
        col1, col2, col3 = st.columns(3)

        with col1:

            conn = sqlite3.connect(DB_PATH)

            usernames = pd.read_sql_query(
                "SELECT DISTINCT username FROM user_activity_logs ORDER BY username",
                conn
            )["username"].tolist()

            conn.close()

            filter_username = st.selectbox("Фильтр по пользователю", ["Все"] + usernames)

        with col2:

            conn = sqlite3.connect(DB_PATH)

            actions = pd.read_sql_query(
                "SELECT DISTINCT action FROM user_activity_logs ORDER BY action",
                conn
            )["action"].tolist()

            conn.close()

            filter_action = st.selectbox("Фильтр по действию", ["Все"] + actions)

        with col3:

            log_limit = st.number_input("Количество записей", 10, 1000, 100, 10)

        username_filter = None if filter_username == "Все" else filter_username
        action_filter = None if filter_action == "Все" else filter_action

        # Получаем логи
        logs = get_logs(limit=log_limit, username=username_filter, action=action_filter)

        if logs:

            logs_data = []

            for log in logs:

                created_at = log.get("created_at", None)

                formatted_time = format_russian_datetime(log.get("created_at")) if log.get("created_at") else "-"

                ip = log.get("ip_address") or "-"

                logs_data.append({
                    "ID": log.get("id", "-"),
                    "Пользователь": log.get("username", "-"),
                    "Действие": log.get("action", "-"),
                    "Детали": log.get("details") or "-",
                    "IP\u00A0адрес": ip,
                    "Дата\u00A0и\u00A0время": formatted_time,
                })

            df_logs = pd.DataFrame(logs_data)

            # Если хочешь красивую дату ещё и в сортировке — можно добавить скрытую колонку
            # df_logs["sort_time"] = pd.to_datetime(df_logs["Время"], format=..., errors="coerce")
            # но обычно достаточно просто сортировки по строке

            html_table = format_dataframe_as_html(df_logs)
            st.markdown(html_table, unsafe_allow_html=True)

            # Экспорт
            csv = df_logs.to_csv(index=False, encoding="utf-8-sig")
            st.download_button(
                label="Скачать логи (CSV)",
                data=csv,
                file_name=f"logs_{datetime.now():%Y%m%d_%H%M%S}.csv",
                mime="text/csv",
            )

        else:
            st.info("Логи не найдены")

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 3: Логи действий ¤ End                                         │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 4: Права доступа к проектам ¤ Start                            │ #
    # └──────────────────────────────────────────────────────────────────────┘ #

    with tab4:

        st.markdown("<h2 class='Duquhununee'>Управление правами доступа к проектам</h2>", unsafe_allow_html=True)

        st.info(
            """
        Здесь можно управлять правами доступа пользователей к определенным проектам в отчетах.
        """
        )

        st.markdown("---")

        # Выдача прав доступа
        st.markdown("### Выдать права доступа к проекту")

        with st.form("grant_permission_form"):

            col1, col2 = st.columns(2)

            with col1:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, username FROM users WHERE is_active = 1 ORDER BY username"
                )
                active_users_list = cursor.fetchall()
                conn.close()

                user_options = {f"{u[1]}": u[0] for u in active_users_list}
                selected_user_display = st.selectbox(
                    "Выберите пользователя", options=list(user_options.keys())
                )
                selected_user_id = user_options[selected_user_display]

            with col2:
                project_name = st.text_input(
                    "Название проекта *", help="Введите название проекта"
                )

            submitted = st.form_submit_button("Выдать права", type="primary")

            if submitted:
                if project_name:
                    if grant_project_access(
                        selected_user_id, project_name, user["username"]
                    ):
                        log_action(
                            user["username"],
                            "grant_project_access",
                            f"Выданы права доступа пользователю {selected_user_display} к проекту {project_name}",
                        )
                        st.success(
                            f"Пользователю {selected_user_display} выданы права доступа к проекту {project_name}!"
                        )
                        st.rerun()
                    else:
                        st.warning(
                            "Права доступа уже существуют или произошла ошибка"
                        )
                else:
                    st.warning("Введите название проекта")

        st.markdown("---")

        # Список прав доступа
        st.markdown("### Текущие права доступа к проектам")

        permissions = get_all_project_permissions()

        if permissions:
            # Группировка по проектам
            projects_dict = {}
            for perm in permissions:
                project = perm["project_name"]
                if project not in projects_dict:
                    projects_dict[project] = []
                projects_dict[project].append(perm)

            # Отображение по проектам
            for project_name, project_perms in sorted(projects_dict.items()):
                with st.expander(
                    f"{project_name} ({len(project_perms)} пользователей)"
                ):
                    perms_data = []
                    for perm in project_perms:
                        perms_data.append(
                            {
                                "Пользователь": perm["username"],
                                "Роль": get_user_role_display(perm["role"]),
                                "Выдано": (
                                    perm["granted_at"] if perm["granted_at"] else "-"
                                ),
                                "Выдал": perm["granted_by"] or "-",
                                "Действие": f"revoke_{perm['user_id']}_{project_name}",
                            }
                        )

                    df_perms = pd.DataFrame(perms_data)
                    st.dataframe(
                        df_perms[["Пользователь", "Роль", "Выдано", "Выдал"]],
                        use_container_width=True,
                        hide_index=True,
                    )

                    # Кнопки отзыва прав
                    for perm in project_perms:
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.text(f"Пользователь: {perm['username']}")
                        with col2:
                            if st.button("Отозвать", key=f"revoke_{perm['id']}"):
                                if revoke_project_access(perm["user_id"], project_name):
                                    log_action(
                                        user["username"],
                                        "revoke_project_access",
                                        f'Отозваны права доступа пользователя {perm["username"]} к проекту {project_name}',
                                    )
                                    st.success(
                                        f"Права доступа пользователя {perm['username']} к проекту {project_name} отозваны!"
                                    )
                                    st.rerun()
        else:
            st.info("Права доступа к проектам не выданы")

    # ┌──────────────────────────────────────────────────────────────────────┐ #
    # │ ⊗ TAB 4: Права доступа к проектам ¤ End                              │ #
    # └──────────────────────────────────────────────────────────────────────┘ #
