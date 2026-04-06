"""
Модуль для работы с фильтрами по умолчанию (роль + отчёт).
Таблица: default_filters (role, report_name, filter_key, filter_value, filter_type, updated_at, updated_by).
"""
import json
from typing import Any, Dict, List, Optional

from db import get_connection

try:
    from dashboards import get_all_report_names
    AVAILABLE_REPORTS = get_all_report_names()
except ImportError:
    AVAILABLE_REPORTS = []

FILTER_TYPES = {
    "string": "Текст",
    "number": "Число",
    "date": "Дата",
    "select": "Выбор из списка",
    "multiselect": "Множественный выбор",
    "boolean": "Да/Нет",
}


def get_default_filters(role: str, report_name: str) -> Dict[str, Any]:
    """
    Возвращает словарь фильтров по умолчанию для роли и отчёта.
    Ключ — filter_key, значение — filter_value (для select/multiselect парсится из JSON).
    """
    result = {}
    try:
        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            cur = conn.cursor()
            cur.execute(
                """
                SELECT filter_key, filter_value, filter_type
                FROM default_filters
                WHERE role = ? AND report_name = ?
                """,
                (role, report_name),
            )
            for row in cur.fetchall():
                key = row["filter_key"]
                val = row["filter_value"]
                ftype = (row.get("filter_type") or "string").lower()
                if val is not None and ftype in ("select", "multiselect"):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
                elif ftype == "number" and val is not None:
                    try:
                        val = float(val) if "." in str(val) else int(val)
                    except (ValueError, TypeError):
                        pass
                elif ftype == "boolean" and val is not None:
                    val = str(val).strip().lower() in ("1", "true", "yes", "да")
                result[key] = val
    except Exception:
        pass
    return result


def set_default_filter(
    role: str,
    report_name: str,
    filter_key: str,
    filter_value: Any,
    filter_type: str = "string",
    updated_by: Optional[str] = None,
) -> bool:
    """Сохраняет или обновляет значение фильтра по умолчанию."""
    if not role or not report_name or not filter_key:
        return False
    value_str = filter_value
    if isinstance(filter_value, (list, dict)):
        try:
            value_str = json.dumps(filter_value, ensure_ascii=False)
        except (TypeError, ValueError):
            value_str = str(filter_value)
    else:
        value_str = str(filter_value) if filter_value is not None else None
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO default_filters (role, report_name, filter_key, filter_value, filter_type, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(role, report_name, filter_key) DO UPDATE SET
                    filter_value = excluded.filter_value,
                    filter_type = excluded.filter_type,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = excluded.updated_by
                """,
                (role, report_name, filter_key, value_str, filter_type or "string", updated_by),
            )
        return True
    except Exception:
        return False


def delete_default_filter(role: str, report_name: str, filter_key: str) -> bool:
    """Удаляет фильтр по умолчанию."""
    if not role or not report_name or not filter_key:
        return False
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                DELETE FROM default_filters
                WHERE role = ? AND report_name = ? AND filter_key = ?
                """,
                (role, report_name, filter_key),
            )
        return True
    except Exception:
        return False


def get_all_default_filters(
    role: Optional[str] = None,
    report_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Возвращает список всех записей фильтров (для админки).
    Каждая запись: role, report_name, filter_key, filter_value, filter_type, updated_at, updated_by.
    """
    result: List[Dict[str, Any]] = []
    try:
        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            cur = conn.cursor()
            if role is not None and report_name is not None:
                cur.execute(
                    """
                    SELECT role, report_name, filter_key, filter_value, filter_type, updated_at, updated_by
                    FROM default_filters WHERE role = ? AND report_name = ?
                    """,
                    (role, report_name),
                )
            elif role is not None:
                cur.execute(
                    """
                    SELECT role, report_name, filter_key, filter_value, filter_type, updated_at, updated_by
                    FROM default_filters WHERE role = ?
                    """,
                    (role,),
                )
            elif report_name is not None:
                cur.execute(
                    """
                    SELECT role, report_name, filter_key, filter_value, filter_type, updated_at, updated_by
                    FROM default_filters WHERE report_name = ?
                    """,
                    (report_name,),
                )
            else:
                cur.execute(
                    """
                    SELECT role, report_name, filter_key, filter_value, filter_type, updated_at, updated_by
                    FROM default_filters
                    ORDER BY role, report_name, filter_key
                    """
                )
            rows = cur.fetchall()
            result = list(rows) if rows else []
    except Exception:
        pass
    return result


def copy_filters_to_role(
    source_role: str,
    target_role: str,
    report_name: Optional[str] = None,
) -> bool:
    """
    Копирует фильтры по умолчанию из source_role в target_role.
    Если report_name задан — только для этого отчёта, иначе для всех отчётов.
    """
    if not source_role or not target_role or source_role == target_role:
        return False
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            if report_name:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO default_filters (role, report_name, filter_key, filter_value, filter_type, updated_at, updated_by)
                    SELECT ?, report_name, filter_key, filter_value, filter_type, CURRENT_TIMESTAMP, updated_by
                    FROM default_filters WHERE role = ? AND report_name = ?
                    """,
                    (target_role, source_role, report_name),
                )
            else:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO default_filters (role, report_name, filter_key, filter_value, filter_type, updated_at, updated_by)
                    SELECT ?, report_name, filter_key, filter_value, filter_type, CURRENT_TIMESTAMP, updated_by
                    FROM default_filters WHERE role = ?
                    """,
                    (target_role, source_role),
                )
        return True
    except Exception:
        return False
