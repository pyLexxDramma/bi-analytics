"""
web_schema.py — схема SQLite для хранения данных из папки web/.

БД: data/web_data.db (отдельно от users.db)

Таблицы:
- web_versions   — версии загрузки (каждый запуск парсинга = новая версия)
- web_files      — файлы, вошедшие в версию (метаданные)
- web_data       — сами данные (строки из всех файлов)
"""
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

# Путь к БД
_BASE_DIR = Path(__file__).resolve().parent
WEB_DB_PATH = str(os.environ.get("WEB_DB_PATH", _BASE_DIR / "data" / "web_data.db"))


@contextmanager
def get_web_connection():
    """Контекстный менеджер подключения к web_data.db."""
    conn = sqlite3.connect(WEB_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_web_schema():
    """
    Создаёт все таблицы если их нет.
    Безопасно вызывать при каждом старте приложения.
    """
    # Убедимся что папка data/ существует
    Path(WEB_DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    with get_web_connection() as conn:
        cur = conn.cursor()

        # ── Версии загрузки ──────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS web_versions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                label       TEXT,           -- опциональная метка, например 'декабрь 2025'
                status      TEXT    NOT NULL DEFAULT 'pending',
                                            -- pending | success | partial | error
                files_count INTEGER DEFAULT 0,
                rows_count  INTEGER DEFAULT 0,
                error_log   TEXT,
                is_active   INTEGER DEFAULT 0   -- 1 = текущая активная версия
            )
        """)

        # ── Файлы внутри версии ──────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS web_files (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id  INTEGER NOT NULL REFERENCES web_versions(id),
                file_name   TEXT    NOT NULL,   -- 'sample_project_data_fixed.csv'
                rel_path    TEXT    NOT NULL,   -- 'MSProject/Dmitrovsky/file.csv'
                file_type   TEXT    NOT NULL,   -- 'project' | 'resources' | 'technique' | 'budget' | 'debit_credit' | 'unknown'
                rows_count  INTEGER DEFAULT 0,
                loaded_at   TEXT    DEFAULT (datetime('now'))
            )
        """)

        # ── Данные (строки из всех файлов) ───────────────────────────────────
        # Храним как JSON-строку — гибко, не нужно менять схему при добавлении колонок.
        # source_file нужен для будущих правил приоритета по имени файла.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS web_data (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id  INTEGER NOT NULL REFERENCES web_versions(id),
                file_id     INTEGER NOT NULL REFERENCES web_files(id),
                file_type   TEXT    NOT NULL,
                source_file TEXT    NOT NULL,   -- имя файла-источника (для правил приоритета)
                row_data    TEXT    NOT NULL    -- JSON строки данных
            )
        """)

        # Индексы для быстрых выборок по версии
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_data_version
            ON web_data(version_id, file_type)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_files_version
            ON web_files(version_id)
        """)


def get_active_version_id() -> int | None:
    """Возвращает id активной версии или None."""
    with get_web_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id FROM web_versions WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            return row["id"]
        # Если нет явно активной — берём последнюю успешную
        row = cur.execute(
            "SELECT id FROM web_versions WHERE status IN ('success','partial') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None


def get_all_versions() -> list[dict]:
    """Возвращает все версии для селектора в UI (новые сверху)."""
    with get_web_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute("""
            SELECT id, created_at, label, status, files_count, rows_count, is_active
            FROM web_versions
            ORDER BY id DESC
            LIMIT 50
        """).fetchall()
        return [dict(r) for r in rows]


def activate_version(version_id: int):
    """Делает указанную версию активной, сбрасывает флаг у остальных."""
    with get_web_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE web_versions SET is_active = 0")
        cur.execute("UPDATE web_versions SET is_active = 1 WHERE id = ?", (version_id,))
