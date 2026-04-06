"""
Модуль для логирования действий пользователей (Streamlit Community Cloud, 2026)
"""
import logging
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

import pytz
import streamlit as st

from config import DB_PATH

UTC_TZ = pytz.UTC
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

# Словарь читаемых названий действий для отображения в UI
ACTION_LABELS = {
    "login": "Вход в систему",
    "logout": "Выход из системы",
    "password_reset": "Смена пароля",
    "user_created": "Создание пользователя",
    "user_deleted": "Удаление пользователя",
    "role_changed": "Изменение роли",
    "access_granted": "Выдача доступа к проекту",
    "access_revoked": "Отзыв доступа к проекту",
    "data_exported": "Экспорт данных",
    "data_loaded": "Загрузка данных",
}


def get_client_ip() -> Optional[str]:
    """Получение IP-адреса клиента в Streamlit Community Cloud."""
    try:
        if hasattr(st.context, "ip_address") and st.context.ip_address:
            return st.context.ip_address.strip()
        headers = getattr(st.context, "headers", {})
        for key in (
            "X-Forwarded-For",
            "x-forwarded-for",
            "X-Real-IP",
            "x-real-ip",
            "Remote-Addr",
            "remote-addr",
        ):
            value = headers.get(key)
            if value:
                return value.split(",")[0].strip()
        return None
    except Exception as e:
        logging.getLogger(__name__).debug("Не удалось получить IP: %s", e)
        return None


def log_action(
    username: str,
    action: str,
    details: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    """
    Записывает действие пользователя в базу (время в UTC).

    Args:
        username:   Имя пользователя
        action:     Тип действия (ключ из ACTION_LABELS или произвольный)
        details:    Дополнительная информация (необязательно)
        ip_address: IP клиента (определяется автоматически, если не передан)
    """
    if ip_address is None:
        ip_address = get_client_ip()

    now_utc = datetime.now(UTC_TZ)
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO user_activity_logs
            (username, action, details, ip_address, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, action, details, ip_address, now_utc.isoformat()),
        )
        conn.commit()
    except Exception as e:
        logging.getLogger(__name__).warning("Ошибка логирования: %s", e)
    finally:
        if conn is not None:
            conn.close()


def get_logs(
    limit: int = 100,
    username: Optional[str] = None,
    action: Optional[str] = None,
) -> List[Dict]:
    """Возвращает последние записи журнала (с фильтрами по пользователю и действию)."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        query = """
            SELECT id, username, action, details, ip_address, created_at
            FROM user_activity_logs
            WHERE 1=1
        """
        params: list = []

        if username:
            query += " AND username = ?"
            params.append(username)
        if action:
            query += " AND action = ?"
            params.append(action)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {
                "id": row[0],
                "username": row[1],
                "action": ACTION_LABELS.get(row[2], row[2]),
                "action_key": row[2],
                "details": row[3],
                "ip_address": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    except Exception as e:
        logging.getLogger(__name__).warning("Ошибка чтения логов: %s", e)
        return []
    finally:
        if conn is not None:
            conn.close()


def get_logs_count(
    username: Optional[str] = None,
    action: Optional[str] = None,
) -> int:
    """Возвращает количество записей журнала (с фильтрами)."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        query = "SELECT COUNT(*) FROM user_activity_logs WHERE 1=1"
        params: list = []

        if username:
            query += " AND username = ?"
            params.append(username)
        if action:
            query += " AND action = ?"
            params.append(action)

        cursor.execute(query, params)
        return cursor.fetchone()[0]

    except Exception as e:
        logging.getLogger(__name__).warning("Ошибка подсчёта логов: %s", e)
        return 0
    finally:
        if conn is not None:
            conn.close()
