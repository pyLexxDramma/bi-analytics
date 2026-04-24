"""
etl/loader.py — оркестратор ETL: сканирует web/, парсит, маппит, кладёт в SQLite.

Основная точка входа: load_from_web_dir(web_dir)

Логика версионирования:
- Версия = дата среза (snapshot_date), извлечённая из имени файла
- Если версия с такой датой уже есть — перезаписываем (REPLACE)
- Справочники (KrStates и т.д.) не привязаны к версии, обновляются всегда
- Активной становится версия с самой свежей snapshot_date
"""

import json
import logging
from pathlib import Path
from typing import Optional

from etl.schema import (
    ETL_DB_PATH,
    get_etl_connection,
    init_etl_schema,
    activate_version,
    get_active_version,
    get_all_versions,
)
from etl.parser import scan_web_dir, group_by_snapshot
from etl.mapper import (
    map_msp,
    map_1c_budget,
    map_1c_dk,
    map_1c_sprav,
    map_tessa_rd,
    map_tessa_id,
    map_tessa_task,
    map_resources,
    map_rd_plan,
    map_kr_states,
)

log = logging.getLogger(__name__)

# Маппинг типа файла → функция маппера и таблица БД
_FILE_HANDLERS = {
    "msp":        (map_msp,        "msp_tasks"),
    "1c_budget":  (map_1c_budget,  "budget_1c"),
    "1c_dk":      (map_1c_dk,      "debit_credit_1c"),
    "1c_sprav":   (map_1c_sprav,   "contractors_1c"),
    "tessa_rd":   (map_tessa_rd,   "tessa_rd"),
    "tessa_id":   (map_tessa_id,   "tessa_id"),
    "tessa_task": (map_tessa_task, "tessa_tasks"),
    "resources":  (map_resources,  "resources"),
    "rd_plan":    (map_rd_plan,    "rd_plan"),
}

# Таблицы, которые нужно очистить при перезаписи версии
_VERSION_TABLES = [
    "msp_tasks", "budget_1c", "debit_credit_1c", "contractors_1c",
    "tessa_rd", "tessa_id", "tessa_tasks", "resources", "rd_plan",
]


def load_from_web_dir(web_dir: Path) -> dict:
    """
    Сканирует web_dir, парсит файлы, загружает в SQLite.

    Возвращает:
    {
        "versions_loaded": int,
        "files_loaded": int,
        "files_skipped": int,
        "rows_total": int,
        "errors": list[str],
        "active_version_id": int | None,
    }
    """
    init_etl_schema()

    result = {
        "versions_loaded": 0,
        "files_loaded":    0,
        "files_skipped":   0,
        "rows_total":      0,
        "errors":          [],
        "active_version_id": None,
    }

    # Сканируем все файлы
    all_files = scan_web_dir(web_dir)
    if not all_files:
        result["errors"].append(f"Папка {web_dir} пуста или не найдена")
        return result

    # Отделяем справочники от версионных данных
    reference_files = [m for m in all_files if m["file_type"] == "reference"]
    data_files = [m for m in all_files if m["file_type"] not in ("reference", "unknown")]
    unknown_files = [m for m in all_files if m["file_type"] == "unknown"]

    for meta in unknown_files:
        log.warning("Неизвестный тип файла: %s", meta["name"])
        result["files_skipped"] += 1

    # Загружаем справочники (KrStates и др.)
    _load_references(reference_files, result)

    # Группируем по дате среза
    groups = group_by_snapshot(data_files)

    # Версия в БД = одна `snapshot_date`; файлы без даты в имени — не к какой
    # версии не привязать: явно пропускаем (даты нет в `detect_file()`).
    _undated = groups.pop("__unknown__", [])
    for meta in _undated:
        nm = meta.get("name", "")
        result["errors"].append(
            f"ETL: в имени нет даты среза, файл пропущен: {nm}"
        )
        result["files_skipped"] += 1
    if _undated:
        log.warning(
            "Пропущено %d файлов без snapshot_date: %s",
            len(_undated),
            [m.get("name") for m in _undated],
        )

    latest_version_id = None
    latest_snapshot_date = None

    with get_etl_connection() as conn:
        for snapshot_date, file_metas in sorted(
            (k, v) for k, v in groups.items() if not k.startswith("__")
        ):

            version_id = _ensure_version(conn, snapshot_date, file_metas)

            # Очищаем старые данные этой версии (перезапись)
            _clear_version_data(conn, version_id)

            version_rows = 0
            version_errors = []

            for meta in file_metas:
                file_type = meta["file_type"]
                if file_type not in _FILE_HANDLERS:
                    result["files_skipped"] += 1
                    continue

                mapper_fn, table = _FILE_HANDLERS[file_type]
                try:
                    records = mapper_fn(meta["path"], meta)
                    if not records:
                        result["files_skipped"] += 1
                        continue

                    # Добавляем version_id ко всем записям
                    for r in records:
                        r["version_id"] = version_id

                    _insert_records(conn, table, records)
                    version_rows += len(records)
                    result["files_loaded"] += 1
                    log.info("Загружено %d строк из %s → %s", len(records), meta["name"], table)

                except Exception as e:
                    msg = f"{meta['name']}: {e}"
                    version_errors.append(msg)
                    result["errors"].append(msg)
                    result["files_skipped"] += 1
                    log.error("Ошибка при загрузке %s: %s", meta["name"], e, exc_info=True)

            # Обновляем kr_state_ru для TESSA данных
            _resolve_kr_states(conn, version_id)

            # Обновляем статус версии
            status = "partial" if version_errors else "success"
            error_log = "\n".join(version_errors) if version_errors else None
            conn.execute(
                "UPDATE data_versions SET status=?, error_log=?, source_files=? WHERE id=?",
                (
                    status,
                    error_log,
                    json.dumps([m["name"] for m in file_metas], ensure_ascii=False),
                    version_id,
                )
            )

            result["versions_loaded"] += 1
            result["rows_total"] += version_rows

            # Запоминаем самую свежую версию
            if latest_snapshot_date is None or snapshot_date > latest_snapshot_date:
                latest_snapshot_date = snapshot_date
                latest_version_id = version_id

        # Активируем самую свежую версию
        if latest_version_id:
            activate_version(conn, latest_version_id)
            result["active_version_id"] = latest_version_id

    return result


def _ensure_version(conn, snapshot_date: str, file_metas: list) -> int:
    """Возвращает id существующей версии или создаёт новую."""
    row = conn.execute(
        "SELECT id FROM data_versions WHERE snapshot_date=? LIMIT 1",
        (snapshot_date,)
    ).fetchone()
    if row:
        return row["id"]
    conn.execute(
        "INSERT INTO data_versions (snapshot_date, status) VALUES (?, 'pending')",
        (snapshot_date,)
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _clear_version_data(conn, version_id: int):
    """Удаляет все данные заданной версии из всех таблиц."""
    for table in _VERSION_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE version_id=?", (version_id,))


def _insert_records(conn, table: str, records: list[dict]):
    """Вставляет список записей в таблицу. Колонки берутся из первой записи."""
    if not records:
        return
    columns = list(records[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    col_str = ", ".join(columns)
    sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})"
    values = [[r.get(c) for c in columns] for r in records]
    conn.executemany(sql, values)


def _load_references(file_metas: list, result: dict):
    """Загружает статические справочники (KrStates и т.д.)."""
    with get_etl_connection() as conn:
        for meta in file_metas:
            fname_lower = meta["name"].lower().replace(".csv", "")
            try:
                if "krstates" in fname_lower or "kr_states" in fname_lower:
                    records = map_kr_states(meta["path"], meta)
                    if records:
                        conn.execute("DELETE FROM kr_states")
                        _insert_records(conn, "kr_states", records)
                        log.info("Обновлён справочник kr_states: %d записей", len(records))
                        result["files_loaded"] += 1
            except Exception as e:
                result["errors"].append(f"{meta['name']}: {e}")
                result["files_skipped"] += 1


def _resolve_kr_states(conn, version_id: int):
    """Заполняет kr_state_ru в tessa_rd и tessa_id по справочнику kr_states (без учёта регистра)."""
    for table in ("tessa_rd", "tessa_id"):
        conn.execute(f"""
            UPDATE {table}
            SET kr_state_ru = (
                SELECT COALESCE(ks.ru, {table}.kr_state)
                FROM kr_states ks
                WHERE lower(trim(COALESCE(ks.en, ''))) = lower(trim(COALESCE({table}.kr_state, '')))
                   OR lower(trim(COALESCE(ks.ru, ''))) = lower(trim(COALESCE({table}.kr_state, '')))
                   OR lower(trim(COALESCE(ks.name, ''))) = lower(trim(COALESCE({table}.kr_state, '')))
                LIMIT 1
            )
            WHERE version_id = ?
        """, (version_id,))


# ── Публичное API для Streamlit ───────────────────────────────────────────────

def get_etl_versions() -> list[dict]:
    """Возвращает список всех версий для UI."""
    with get_etl_connection() as conn:
        return get_all_versions(conn)


def set_active_version(version_id: int):
    """Делает версию активной."""
    with get_etl_connection() as conn:
        activate_version(conn, version_id)


def get_current_version_id() -> Optional[int]:
    """Возвращает id активной версии."""
    with get_etl_connection() as conn:
        v = get_active_version(conn)
        return v["id"] if v else None


def get_current_version_info() -> Optional[dict]:
    """Возвращает информацию об активной версии."""
    with get_etl_connection() as conn:
        v = get_active_version(conn)
        return dict(v) if v else None


def query_msp(version_id: int, filters: Optional[dict] = None) -> list[dict]:
    """
    Возвращает задачи MSP для заданной версии.
    filters: {"project_name": str, "block": str, "lot": str, "level_structure": int}
    """
    sql = "SELECT * FROM msp_tasks WHERE version_id=?"
    params = [version_id]
    if filters:
        for key in ("project_name", "block", "lot"):
            if filters.get(key):
                sql += f" AND {key}=?"
                params.append(filters[key])
        if filters.get("level_structure") is not None:
            sql += " AND level_structure=?"
            params.append(filters["level_structure"])
    with get_etl_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_budget(version_id: int, filters: Optional[dict] = None) -> list[dict]:
    """Возвращает данные БДДС/БДР для заданной версии."""
    sql = "SELECT * FROM budget_1c WHERE version_id=?"
    params = [version_id]
    if filters:
        for key in ("scenario", "article_type", "project"):
            if filters.get(key):
                sql += f" AND {key}=?"
                params.append(filters[key])
    with get_etl_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_debit_credit(version_id: int) -> list[dict]:
    """Возвращает данные ДЗ/КЗ для заданной версии."""
    with get_etl_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM debit_credit_1c WHERE version_id=?", (version_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def query_tessa_rd(version_id: int, filters: Optional[dict] = None) -> list[dict]:
    """Возвращает РД из TESSA для заданной версии."""
    sql = "SELECT * FROM tessa_rd WHERE version_id=?"
    params = [version_id]
    if filters:
        for key in ("project_id", "project_name", "contractor"):
            if filters.get(key):
                sql += f" AND {key}=?"
                params.append(filters[key])
    with get_etl_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_tessa_id(version_id: int, filters: Optional[dict] = None) -> list[dict]:
    """Возвращает ИД из TESSA для заданной версии."""
    sql = "SELECT * FROM tessa_id WHERE version_id=?"
    params = [version_id]
    if filters:
        for key in ("object_id", "object_name", "contractor_name", "kind_name"):
            if filters.get(key):
                sql += f" AND {key}=?"
                params.append(filters[key])
    with get_etl_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_resources(version_id: int, filters: Optional[dict] = None) -> list[dict]:
    """Возвращает данные ресурсов/ГДРС для заданной версии."""
    sql = "SELECT * FROM resources WHERE version_id=?"
    params = [version_id]
    if filters:
        for key in ("project", "contractor", "resource_type"):
            if filters.get(key):
                sql += f" AND {key}=?"
                params.append(filters[key])
    with get_etl_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
