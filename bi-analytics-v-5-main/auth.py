"""
Модуль авторизации для BI Analytics приложения
"""
import sys
from pathlib import Path

# Ensure app directory is first on path (for deployment: pages may add repo root, we need app root first)
_app_dir = Path(__file__).resolve().parent
_app_dir_str = str(_app_dir)
sys.path.insert(0, _app_dir_str)

import sqlite3
import hashlib
import secrets
import string
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import streamlit as st

from config import DB_PATH, switch_page_app

# Роли пользователей
ROLES = {
    "superadmin": "Суперадминистратор",
    "admin": "Администратор",
    "analyst": "Аналитик",
    "rp": "Руководитель проекта (РП)",
    "financier": "Финансист",
    "gip": "Главный инженер проекта (ГИП)",
    "manager": "Менеджер",
}

# Роли с доступом к настройкам
ADMIN_ROLES = ["superadmin", "admin"]

# Роли с доступом к отчетам
REPORT_ROLES = ["manager", "analyst", "rp", "financier", "gip", "admin", "superadmin"]

# RBAC: для роли перечислите отчёты (имена как в меню), которые скрыть.
# Администраторы и суперадмины всегда видят все отчёты.
# typing.FrozenSet не используем — на части окружений (Streamlit Cloud) импорт падает.
_ROLE_REPORT_DENYLIST: Dict[str, frozenset] = {
    "manager": frozenset(
        {
            "БДДС",
            "БДР",
            "Бюджет план/факт",
            "Утвержденный бюджет",
            "Прогнозный бюджет",
            "Дебиторская и кредиторская задолженность подрядчиков",
        }
    ),
    "analyst": frozenset(),
    "rp": frozenset(),
    "financier": frozenset(),
    "gip": frozenset(),
}

# Если для отчёта задан allowlist — отчёт виден только перечисленным ролям (плюс admin/superadmin).
_REPORT_ROLE_ALLOWLIST: Dict[str, frozenset] = {
    "Девелоперские проекты": frozenset({"manager", "analyst", "rp", "financier", "admin", "superadmin"}),
    "БДДС": frozenset({"analyst", "rp", "financier", "admin", "superadmin"}),
    "БДР": frozenset({"analyst", "rp", "financier", "admin", "superadmin"}),
    "Бюджет план/факт": frozenset({"analyst", "rp", "financier", "admin", "superadmin"}),
    "Утвержденный бюджет": frozenset({"analyst", "rp", "financier", "admin", "superadmin"}),
    "Прогнозный бюджет": frozenset({"analyst", "rp", "financier", "admin", "superadmin"}),
    "Дебиторская и кредиторская задолженность подрядчиков": frozenset({"analyst", "rp", "financier", "admin", "superadmin"}),
    "Причины отклонений": frozenset({"manager", "analyst", "rp", "gip", "financier", "admin", "superadmin"}),
    "Отклонение от базового плана": frozenset({"manager", "analyst", "rp", "gip", "financier", "admin", "superadmin"}),
    "Контрольные точки": frozenset({"manager", "analyst", "rp", "gip", "financier", "admin", "superadmin"}),
    "График проекта": frozenset({"manager", "analyst", "rp", "gip", "financier", "admin", "superadmin"}),
    "Рабочая документация": frozenset({"manager", "analyst", "rp", "gip", "admin", "superadmin"}),
    "Проектная документация": frozenset({"manager", "analyst", "rp", "gip", "admin", "superadmin"}),
    "ГДРС": frozenset({"manager", "analyst", "rp", "admin", "superadmin"}),
    "График движения рабочей силы": frozenset({"manager", "analyst", "rp", "admin", "superadmin"}),
    "ГДРС Техника": frozenset({"manager", "analyst", "rp", "admin", "superadmin"}),
    "Исполнительная документация": frozenset({"manager", "analyst", "rp", "admin", "superadmin"}),
    "Предписания по подрядчикам": frozenset({"manager", "analyst", "rp", "admin", "superadmin"}),
    "Неустраненные предписания": frozenset({"manager", "analyst", "rp", "admin", "superadmin"}),
    "Просрочка выдачи РД": frozenset({"manager", "analyst", "rp", "gip", "financier", "admin", "superadmin"}),
    "Просрочка выдачи ПД": frozenset({"manager", "analyst", "rp", "gip", "financier", "admin", "superadmin"}),
}


def user_can_open_report(role: str, report_name: str) -> bool:
    """Проверка доступа к одному отчёту по роли."""
    if role in ("superadmin", "admin"):
        return True
    if report_name in _ROLE_REPORT_DENYLIST.get(role, frozenset()):
        return False
    allowed_only = _REPORT_ROLE_ALLOWLIST.get(report_name)
    if allowed_only is not None and role not in allowed_only:
        return False
    return True


def filter_reports_for_role(role: str, report_names: List[str]) -> List[str]:
    """Список отчётов, доступных роли (меню, радиокнопки)."""
    return [n for n in report_names if user_can_open_report(role, n)]


def init_db():
    """Инициализация базы данных: создание всех таблиц (делегируется в db)."""
    from db import init_all_tables
    def _show(msg):
        try:
            st.info(msg)
        except Exception:
            pass
    init_all_tables(_show)


def hash_password(password: str) -> str:
    """Хеширование пароля"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Проверка пароля"""
    return hash_password(password) == password_hash


def create_user(
    username: str,
    password: str,
    role: str,
    email: Optional[str] = None,
    created_by: Optional[str] = None,
) -> bool:
    """Создание нового пользователя"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        if role == "superadmin":
            cursor.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'superadmin' AND is_active = 1"
            )
            if cursor.fetchone()[0] >= 1:
                conn.close()
                return False

        password_hash = hash_password(password)
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, role, email)
            VALUES (?, ?, ?, ?)
        """,
            (username, password_hash, role, email),
        )

        conn.commit()
        conn.close()

        try:
            from logger import log_action
            log_action(
                created_by or "system",
                "user_created",
                f"username={username}, role={role}",
            )
        except Exception:
            pass

        return True
    except sqlite3.IntegrityError:
        return False
    except Exception:
        return False


def authenticate(username: str, password: str) -> Tuple[bool, Optional[dict]]:
    """Аутентификация пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, username, password_hash, role, email, is_active
        FROM users
        WHERE username = ?
    """,
        (username,),
    )

    user = cursor.fetchone()

    if user and user[5] == 1:  # is_active
        user_id, username_db, password_hash, role, email, is_active = user

        if verify_password(password, password_hash):
            # Обновляем время последнего входа
            cursor.execute(
                """
                UPDATE users
                SET last_login = ?
                WHERE id = ?
            """,
                (datetime.now(), user_id),
            )
            conn.commit()

            conn.close()

            try:
                from logger import log_action
                log_action(username_db, "login")
            except Exception:
                pass

            return True, {
                "id": user_id,
                "username": username_db,
                "role": role,
                "email": email,
            }

    conn.close()
    return False, None


def get_user_by_username(username: str) -> Optional[dict]:
    """Получение пользователя по имени"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, username, role, email, is_active
        FROM users
        WHERE username = ?
    """,
        (username,),
    )

    user = cursor.fetchone()
    conn.close()

    if user:
        return {
            "id": user[0],
            "username": user[1],
            "role": user[2],
            "email": user[3],
            "is_active": user[4],
        }
    return None


def generate_reset_token(username: str) -> Optional[str]:
    """Генерация токена для восстановления пароля"""
    user = get_user_by_username(username)
    if not user:
        return None

    # Генерируем случайный токен
    token = "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(32)
    )

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Удаляем старые неиспользованные токены для этого пользователя
    cursor.execute(
        """
        DELETE FROM password_reset_tokens
        WHERE username = ? AND used = 0
    """,
        (username,),
    )

    # Создаем новый токен (действителен 1 час)
    expires_at = datetime.now() + timedelta(hours=1)
    cursor.execute(
        """
        INSERT INTO password_reset_tokens (username, token, expires_at)
        VALUES (?, ?, ?)
    """,
        (username, token, expires_at),
    )

    conn.commit()
    conn.close()

    return token


def verify_reset_token(token: str) -> Optional[str]:
    """Проверка токена восстановления пароля"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT username, expires_at, used
        FROM password_reset_tokens
        WHERE token = ?
    """,
        (token,),
    )

    result = cursor.fetchone()
    conn.close()

    if result:
        username, expires_at, used = result
        expires_at = datetime.fromisoformat(expires_at)

        if not used and datetime.now() < expires_at:
            return username

    return None


def reset_password(token: str, new_password: str) -> bool:
    """Сброс пароля по токену"""
    username = verify_reset_token(token)
    if not username:
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Обновляем пароль
    password_hash = hash_password(new_password)
    cursor.execute(
        """
        UPDATE users
        SET password_hash = ?
        WHERE username = ?
    """,
        (password_hash, username),
    )

    # Помечаем токен как использованный
    cursor.execute(
        """
        UPDATE password_reset_tokens
        SET used = 1
        WHERE token = ?
    """,
        (token,),
    )

    conn.commit()
    conn.close()

    try:
        from logger import log_action
        log_action(username, "password_reset", "сброс через токен")
    except Exception:
        pass

    return True


def delete_user(user_id: int, deleted_by: str) -> Tuple[bool, str]:
    """Полное удаление пользователя и всех связанных данных."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT role FROM users WHERE username = ? AND is_active = 1",
        (deleted_by,),
    )
    actor = cursor.fetchone()
    if not actor or actor[0] != "superadmin":
        conn.close()
        return False, "Удалять пользователей может только суперадминистратор"

    cursor.execute("SELECT username, role FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "Пользователь не найден"

    target_username, target_role = row

    if target_username == deleted_by:
        conn.close()
        return False, "Нельзя удалить самого себя"

    if target_role == "superadmin":
        conn.close()
        return False, "Нельзя удалить суперадминистратора"

    try:
        cursor.execute("DELETE FROM project_permissions WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM password_reset_tokens WHERE username = ?", (target_username,))
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, f"Ошибка базы данных: {e}"

    conn.close()

    try:
        from logger import log_action
        log_action(deleted_by, "user_deleted", f"Удалён пользователь {target_username} (id={user_id}, role={target_role})")
    except Exception:
        pass

    return True, f"Пользователь «{target_username}» удалён"


def has_admin_access(user_role: str) -> bool:
    """Проверка доступа к административной панели"""
    return user_role in ADMIN_ROLES


def has_report_access(user_role: str) -> bool:
    """Проверка доступа к отчетам"""
    return user_role in REPORT_ROLES


def get_user_role_display(role: str) -> str:
    """Получение отображаемого названия роли"""
    return ROLES.get(role, role)


def check_authentication() -> bool:
    """Проверка авторизации пользователя в сессии"""
    if "authenticated" not in st.session_state:
        return False
    return st.session_state.get("authenticated", False)


def get_current_user() -> Optional[dict]:
    """Получение текущего пользователя из сессии"""
    if check_authentication():
        return st.session_state.get("user", None)
    return None

def logout():
    """Выход из системы"""

    try:
        user = st.session_state.get("user")
        if user and user.get("username"):
            try:
                from logger import log_action

                log_action(str(user["username"]), "logout", "Выход из системы")
            except Exception:
                pass
    except Exception:
        pass

    st.session_state.pop("authenticated", None)
    st.session_state.pop("user", None)
    st.session_state["hide_sidebar"] = True


def change_password(
    username: str, old_password: str, new_password: str
) -> Tuple[bool, str]:
    """
    Изменение пароля пользователя

    Args:
        username: Имя пользователя
        old_password: Текущий пароль
        new_password: Новый пароль

    Returns:
        Tuple[bool, str]: (успех, сообщение)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Проверяем текущий пароль
    cursor.execute(
        """
        SELECT password_hash FROM users
        WHERE username = ? AND is_active = 1
    """,
        (username,),
    )

    result = cursor.fetchone()
    if not result:
        conn.close()
        return False, "Пользователь не найден"

    password_hash = result[0]
    if not verify_password(old_password, password_hash):
        conn.close()
        return False, "Неверный текущий пароль"

    # Обновляем пароль
    new_password_hash = hash_password(new_password)
    cursor.execute(
        """
        UPDATE users
        SET password_hash = ?
        WHERE username = ?
    """,
        (new_password_hash, username),
    )

    conn.commit()
    conn.close()

    try:
        from logger import log_action
        log_action(username, "password_changed", "смена пароля в профиле")
    except Exception:
        pass

    return True, "Пароль успешно изменен"


def update_user_email(username: str, new_email: Optional[str]) -> Tuple[bool, str]:
    """
    Обновление email пользователя

    Args:
        username: Имя пользователя
        new_email: Новый email (может быть None)

    Returns:
        Tuple[bool, str]: (успех, сообщение)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Проверяем существование пользователя
    cursor.execute(
        """
        SELECT id FROM users
        WHERE username = ? AND is_active = 1
    """,
        (username,),
    )

    result = cursor.fetchone()
    if not result:
        conn.close()
        return False, "Пользователь не найден"

    # Обновляем email
    cursor.execute(
        """
        UPDATE users
        SET email = ?
        WHERE username = ?
    """,
        (new_email, username),
    )

    conn.commit()
    conn.close()

    return True, "Email успешно обновлен"


def is_streamlit_context():
    """Проверка, что код выполняется в контексте Streamlit"""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except:
        return False

def require_auth():
    """Проверка авторизации с автоматическим редиректом"""
    if not check_authentication():
        switch_page_app("project_visualization_app.py")
        st.stop()


def render_sidebar_menu(current_page: str = "reports"):
    """
    Отображение боковой панели с меню навигации

    Args:
        current_page: Текущая страница ("reports", "admin", "profile", "analyst_params")
    """
    if not is_streamlit_context():
        return

    # Проверка авторизации - меню показывается только авторизованным пользователям
    if not check_authentication():
        return

    user = get_current_user()
    if not user:
        return

    with st.sidebar:
        # F2: скрываем системную мульти-страничную навигацию Streamlit
        # (streamlit app / admin / analyst params), оставляем только наше меню.
        st.markdown(
            """
            <style>
            [data-testid="stSidebarNav"] { display: none !important; }
            section[data-testid="stSidebar"] [data-testid="stPopover"] { display: none !important; }
            </style>
            """,
            unsafe_allow_html=True,
        )
        # Меню навигации
        st.markdown("### Меню")

        # 1. Отчёты (отдельный визуальный блок от настроек)
        if has_report_access(user["role"]) and current_page != "reports":
            if st.button("К дашбордам", width="stretch", key="menu_go_reports"):
                switch_page_app("project_visualization_app.py")
            st.markdown("---")

        if has_report_access(user["role"]) and current_page == "reports":
            from dashboards import REPORT_CATEGORIES

            st.markdown('<p class="sidebar-section-title">Отчёты</p>', unsafe_allow_html=True)
            st.markdown("---")
            current_dashboard = st.session_state.get("current_dashboard", "")
            for cat_name, reports in REPORT_CATEGORIES:
                visible = filter_reports_for_role(user["role"], list(reports))
                if not visible:
                    continue
                _expand_here = any(current_dashboard == r for r in visible)
                with st.expander(cat_name, expanded=_expand_here):
                    for report in visible:
                        button_type = (
                            "primary" if current_dashboard == report else "secondary"
                        )
                        if st.button(
                            f"• {report}",
                            width="stretch",
                            key=f"menu_report_{report}",
                            type=button_type,
                        ):
                            st.session_state.current_dashboard = report
                            st.rerun()
            st.markdown("---")

        st.markdown('<p class="sidebar-section-title">Настройки</p>', unsafe_allow_html=True)

        # Настройки профиля (для всех ролей)
        if current_page == "profile":
            st.button(
                "Настройки профиля",
                width="stretch",
                type="primary",
                disabled=True,
            )
        else:
            if st.button("Настройки профиля", width="stretch"):
                switch_page_app("pages/profile.py")

        # Административная панель: только внутри «Настройки профиля» (вторая вкладка) или прямой URL pages/_admin.py

        if current_page != "analyst_params":
            if st.button("Параметры отчётов", width="stretch", key="menu_go_analyst_params"):
                switch_page_app("pages/_analyst_params.py")

        # F2: встроенная навигация Streamlit скрыта.

        # ── Admin-only тумблер «Демо-данные» (только в dev, на release недоступно) ──
        try:
            from config import is_release_client_mode as _cfg_is_release
            from config import ignore_demo_data_files as _cfg_ignore_demo
            _is_release = bool(_cfg_is_release())
        except Exception:
            _is_release = False
            _cfg_ignore_demo = lambda: False  # type: ignore[assignment]
        if not _is_release and has_admin_access(user.get("role", "")):
            st.markdown("---")
            st.markdown(
                '<p class="sidebar-section-title">Dev-инструменты</p>',
                unsafe_allow_html=True,
            )
            _demo_now_on = not bool(_cfg_ignore_demo())
            _new_val = st.toggle(
                "Подмешивать демо-данные",
                value=_demo_now_on,
                key="_admin_demo_toggle",
                help=(
                    "Демо: sample_*.csv и файлы из new_csv/. Включён — подмешиваются "
                    "при загрузке из web/. Выключен — игнорируются (как на release). "
                    "Только для admin/superadmin на dev. На release недоступно."
                ),
            )
            _prev_pref = str(st.session_state.get("_admin_demo_pref", "") or "")
            _new_pref = "include" if _new_val else "ignore"
            if _new_pref != _prev_pref:
                st.session_state["_admin_demo_pref"] = _new_pref
                st.cache_data.clear()
                # Прямая перезагрузка из web/ — гарантирует, что новая версия БД
                # будет содержать (или не содержать) демо в соответствии с тумблером,
                # без зависимости от того, на какой странице сейчас находится admin.
                try:
                    from web_loader import load_all_from_web
                    from data_loader import ensure_data_session_state
                    ensure_data_session_state()
                    with st.spinner("Перечитываю web/ с новыми настройками демо…"):
                        result = load_all_from_web()
                    st.session_state["last_load_result"] = result
                    st.session_state.pop("web_version_id", None)
                    try:
                        from web_schema import get_active_version_id as _gav
                        _na = _gav()
                        if _na is not None:
                            st.session_state["web_version_pick_id"] = int(_na)
                    except Exception:
                        pass
                except Exception as _e:
                    st.warning(f"Не удалось перечитать web/ автоматически: {_e}")
                st.session_state.pop("_pending_web_folder_load", None)
                st.rerun()

        # 3. Выход (для всех ролей)
        st.markdown("---")

        if st.button("Выйти", width="stretch"):

            logout()

            st.rerun()  # success не нужен — после rerun этой строки уже не будет
