"""
Модуль для управления настройками системы
"""
import sqlite3
from datetime import datetime
from typing import Optional, Dict

from config import DB_PATH

# Ключи настроек
SETTING_KEYS = {
    'finance_files_path': 'Путь к файлам финансовых данных',
    'plan_fact_files_path': 'Путь к файлам план-факт данных',
    'resources_files_path': 'Путь к файлам данных по ресурсам'
}


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Получение значения настройки
    
    Args:
        key: Ключ настройки
        default: Значение по умолчанию
    
    Returns:
        Значение настройки или default
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return result[0]
        return default
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ошибка при получении настройки: %s", e)
        return default


def set_setting(key: str, value: str, description: Optional[str] = None, updated_by: Optional[str] = None):
    """
    Установка значения настройки
    
    Args:
        key: Ключ настройки
        value: Значение настройки
        description: Описание настройки
        updated_by: Пользователь, который обновил настройку
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value, description, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?)
        """, (key, value, description, datetime.now().isoformat(), updated_by))
        conn.commit()
        conn.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ошибка при установке настройки: %s", e)


def get_all_settings() -> Dict[str, Dict]:
    """
    Получение всех настроек
    
    Returns:
        Словарь с настройками
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT key, value, description, updated_at, updated_by FROM settings")
        rows = cursor.fetchall()
        conn.close()
        
        settings = {}
        for row in rows:
            settings[row[0]] = {
                'value': row[1],
                'description': row[2],
                'updated_at': row[3],
                'updated_by': row[4]
            }
        
        return settings
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ошибка при получении всех настроек: %s", e)
        return {}


def delete_setting(key: str):
    """
    Удаление настройки
    
    Args:
        key: Ключ настройки
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
        conn.commit()
        conn.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ошибка при удалении настройки: %s", e)


