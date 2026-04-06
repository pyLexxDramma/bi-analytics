"""
Модуль для управления правами доступа к проектам
"""
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict

from config import DB_PATH


def grant_project_access(user_id: int, project_name: str, granted_by: Optional[str] = None) -> bool:
    """
    Выдача прав доступа пользователю к проекту
    
    Args:
        user_id: ID пользователя
        project_name: Название проекта
        granted_by: Пользователь, который выдал права
    
    Returns:
        True если успешно, False если ошибка
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO project_permissions (user_id, project_name, created_at, granted_by)
            VALUES (?, ?, ?, ?)
        """, (user_id, project_name, datetime.now().isoformat(), granted_by))
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        if success:
            try:
                from logger import log_action
                log_action(
                    granted_by or "system",
                    "access_granted",
                    f"user_id={user_id}, project={project_name}",
                )
            except Exception:
                pass
        return success
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ошибка при выдаче прав доступа: %s", e)
        return False


def revoke_project_access(user_id: int, project_name: str, revoked_by: Optional[str] = None) -> bool:
    """
    Отзыв прав доступа пользователя к проекту

    Args:
        user_id:     ID пользователя
        project_name: Название проекта
        revoked_by:  Кто отзывает (для лога)

    Returns:
        True если успешно, False если ошибка
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM project_permissions 
            WHERE user_id = ? AND project_name = ?
        """, (user_id, project_name))
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        if success:
            try:
                from logger import log_action
                log_action(
                    revoked_by or "system",
                    "access_revoked",
                    f"user_id={user_id}, project={project_name}",
                )
            except Exception:
                pass
        return success
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ошибка при отзыве прав доступа: %s", e)
        return False


def get_user_projects(user_id: int) -> List[str]:
    """
    Получение списка проектов, к которым у пользователя есть доступ
    
    Args:
        user_id: ID пользователя
    
    Returns:
        Список названий проектов
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT project_name FROM project_permissions 
            WHERE user_id = ?
        """, (user_id,))
        projects = [row[0] for row in cursor.fetchall()]
        conn.close()
        return projects
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ошибка при получении проектов пользователя: %s", e)
        return []


def get_project_users(project_name: str) -> List[int]:
    """
    Получение списка пользователей, имеющих доступ к проекту
    
    Args:
        project_name: Название проекта
    
    Returns:
        Список ID пользователей
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id FROM project_permissions 
            WHERE project_name = ?
        """, (project_name,))
        user_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        return user_ids
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ошибка при получении пользователей проекта: %s", e)
        return []


def get_all_project_permissions() -> List[Dict]:
    """
    Получение всех прав доступа к проектам
    
    Returns:
        Список словарей с информацией о правах доступа
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                pp.id,
                pp.user_id,
                pp.project_name,
                pp.created_at,
                pp.granted_by,
                u.username,
                u.role
            FROM project_permissions pp
            JOIN users u ON pp.user_id = u.id
            ORDER BY pp.project_name, u.username
        """)
        rows = cursor.fetchall()
        conn.close()
        
        permissions = []
        for row in rows:
            permissions.append({
                'id': row[0],
                'user_id': row[1],
                'project_name': row[2],
                'granted_at': row[3],
                'granted_by': row[4],
                'username': row[5],
                'role': row[6]
            })
        
        return permissions
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ошибка при получении всех прав доступа: %s", e)
        return []


def has_project_access(user_id: int, project_name: str) -> bool:
    """
    Проверка наличия прав доступа пользователя к проекту
    
    Args:
        user_id: ID пользователя
        project_name: Название проекта
    
    Returns:
        True если есть доступ, False если нет
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM project_permissions 
            WHERE user_id = ? AND project_name = ?
        """, (user_id, project_name))
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ошибка при проверке прав доступа: %s", e)
        return False


def get_all_projects() -> List[str]:
    """
    Получение списка всех проектов, к которым выданы права доступа
    
    Returns:
        Список уникальных названий проектов
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT project_name FROM project_permissions 
            ORDER BY project_name
        """)
        projects = [row[0] for row in cursor.fetchall()]
        conn.close()
        return projects
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Ошибка при получении всех проектов: %s", e)
        return []


