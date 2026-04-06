"""
etl/schema.py — схема SQLite для хранения всех данных (MSP, 1С, TESSA, ресурсы).

Структура:
- data_versions      — версии загрузки (дата среза из имени файла)
- msp_tasks          — задачи из MSP (сроки, отклонения, иерархия)
- budget_1c          — БДДС/БДР данные из 1С (dannye.json)
- debit_credit_1c    — Дебиторка/Кредиторка из 1С (DK.json)
- contractors_1c     — Справочник контрагентов (spravochniki.json)
- tessa_rd           — Рабочая документация (TESSA rd.csv)
- tessa_id           — Исполнительная документация (TESSA id.csv)
- tessa_tasks        — Задачи TESSA (task.csv)
- kr_states          — Справочник статусов документов (KrStates.csv)
- resources          — ГДРС: ресурсы/техника (resursi.csv)
- rd_plan            — Плановая выдача РД (other_*_rd.csv)
"""

import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

_BASE_DIR = Path(__file__).resolve().parent.parent
ETL_DB_PATH = str(os.environ.get(
    "ETL_DB_PATH",
    _BASE_DIR / "data" / "etl.db"
))


@contextmanager
def get_etl_connection():
    Path(ETL_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ETL_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_etl_schema():
    """Создаёт все таблицы. Безопасно вызывать при каждом старте."""
    Path(ETL_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_etl_connection() as conn:
        cur = conn.cursor()

        # ── Версии загрузки ──────────────────────────────────────────────────
        # snapshot_date — дата среза из имени файла (например 2026-03-02)
        # loaded_at     — когда загрузили в БД
        # is_active     — 1 = активная (по умолчанию последняя)
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS data_versions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT    NOT NULL,          -- дата среза: YYYY-MM-DD
                label         TEXT,                      -- произвольная метка
                source_files  TEXT,                      -- JSON-список файлов
                loaded_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                status        TEXT    NOT NULL DEFAULT 'pending',
                error_log     TEXT,
                is_active     INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_versions_date
                ON data_versions(snapshot_date);

            -- ── MSP: задачи проектов ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS msp_tasks (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id              INTEGER NOT NULL REFERENCES data_versions(id),
                snapshot_date           TEXT    NOT NULL,
                project_id              TEXT,            -- ID_проекта из файла
                project_name            TEXT,            -- название проекта (из имени файла)
                task_id                 TEXT,            -- Ид
                unique_id               TEXT,            -- Уникальный_идентификатор
                name                    TEXT,            -- Название
                level_structure         INTEGER,         -- Уровень_структуры (число)
                level                   TEXT,            -- Уровень (текст-путь иерархии)
                block                   TEXT,            -- БЛОК
                lot                     TEXT,            -- ЛОТ
                task_type               TEXT,            -- Тип (Суммарная задача / Продукт / и т.д.)
                task_mode               TEXT,            -- Режим_задачи
                calendar                TEXT,            -- Календарь_задачи
                pct_complete            REAL,            -- Процент_завершения
                base_duration           TEXT,            -- Базовая_длительность (raw)
                duration                TEXT,            -- Длительность (raw)
                base_start              TEXT,            -- Базовое_начало (ISO)
                base_finish             TEXT,            -- Базовое_окончание (ISO)
                start                   TEXT,            -- Начало (ISO)
                finish                  TEXT,            -- Окончание (ISO)
                constraint_date         TEXT,            -- Дата_ограничения (ISO)
                predecessors            TEXT,            -- Предшественники (raw)
                successors              TEXT,            -- Последователи (raw)
                deviation_reason        TEXT,            -- Причины_отклонений
                notes                   TEXT,            -- Заметки
                cipher                  TEXT,            -- Шифр_ПД_и_РД
                deviation_start_days    REAL,            -- Отклонение_начала (дни, если есть)
                deviation_finish_days   REAL,            -- Отклонение_окончания (дни, если есть)
                source_file             TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_msp_version
                ON msp_tasks(version_id, project_name);
            CREATE INDEX IF NOT EXISTS idx_msp_snapshot
                ON msp_tasks(snapshot_date);

            -- ── 1С: БДДС / БДР ─────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS budget_1c (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id          INTEGER NOT NULL REFERENCES data_versions(id),
                snapshot_date       TEXT    NOT NULL,
                period              TEXT,            -- Период (дата операции)
                registrar           TEXT,            -- Регистратор
                scenario            TEXT,            -- Сценарий (ФАКТ / Бюджет / ...)
                cfo                 TEXT,            -- ЦФО
                article             TEXT,            -- СтатьяОборотов
                currency            TEXT,            -- Валюта
                contractor          TEXT,            -- Контрагент
                contractor_contract TEXT,            -- ДоговорКонтрагента
                project             TEXT,            -- Проект
                nomenclature_group  TEXT,            -- НоменклатурнаяГруппа
                bank_account        TEXT,            -- БанковскийСчет
                analytics_1         TEXT,            -- Аналитика_1
                organization        TEXT,            -- Организация
                amount              REAL,            -- Сумма
                flow_type           TEXT,            -- РасходДоход
                article_type        TEXT,            -- ТипСтатьи (БДДС / БДР)
                source_file         TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_budget_version
                ON budget_1c(version_id, scenario, article_type);
            CREATE INDEX IF NOT EXISTS idx_budget_project
                ON budget_1c(project);

            -- ── 1С: Дебиторка / Кредиторка ─────────────────────────────────
            CREATE TABLE IF NOT EXISTS debit_credit_1c (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id                  INTEGER NOT NULL REFERENCES data_versions(id),
                snapshot_date               TEXT    NOT NULL,
                org_id                      TEXT,
                org_name                    TEXT,
                contractor_id               TEXT,
                contractor_name             TEXT,
                contract_id                 TEXT,
                contract_number             TEXT,
                contract_date               TEXT,
                contract_amount             TEXT,            -- сырая строка (может быть "25,861,200")
                contract_amount_clean       REAL,            -- очищенное число
                balance_start               REAL,
                balance_start_period        REAL,
                balance_start_period_adv    REAL,
                total_payments              REAL,
                total_payments_adv          REAL,
                balance_end                 REAL,
                balance_end_period          REAL,
                balance_end_period_adv      REAL,
                source_file                 TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_dk_version
                ON debit_credit_1c(version_id);

            -- ── 1С: Справочник контрагентов ─────────────────────────────────
            CREATE TABLE IF NOT EXISTS contractors_1c (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id          INTEGER NOT NULL REFERENCES data_versions(id),
                contractor_id       TEXT,            -- ID_Контрагента
                contractor_name     TEXT,            -- Наименование_Контрагента
                inn                 TEXT,            -- ИНН
                kpp                 TEXT,            -- КПП
                source_file         TEXT
            );

            -- ── TESSA: Рабочая документация (РД) ────────────────────────────
            CREATE TABLE IF NOT EXISTS tessa_rd (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id              INTEGER NOT NULL REFERENCES data_versions(id),
                snapshot_date           TEXT    NOT NULL,
                import_date             TEXT,
                doc_id                  TEXT,            -- DocID
                doc_description         TEXT,            -- DocDescription
                internal_id             TEXT,            -- InternalID
                creation_date           TEXT,            -- CreationDate
                doc_number              TEXT,            -- DocNumber
                kr_state                TEXT,            -- KrState (raw)
                kr_state_ru             TEXT,            -- KrState → русское название
                object_id               TEXT,            -- ObjectID
                object_name             TEXT,            -- ObjectName
                project_id              TEXT,            -- ObjectProjectID
                project_name            TEXT,            -- ObjectProjectName
                division_id             TEXT,            -- DivisionID
                division_cipher         TEXT,            -- DivisionCipher
                subdivision_version_id  TEXT,
                subdivision_version     TEXT,
                contractor              TEXT,            -- CONTR
                lot                     TEXT,            -- Lot
                contractor_1c_id        TEXT,            -- 1C_ID_CONTR
                object_1c_id            TEXT,            -- 1C_ID_OBJECT
                source_file             TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_trd_version
                ON tessa_rd(version_id, project_id);

            -- ── TESSA: Исполнительная документация (ИД) ─────────────────────
            CREATE TABLE IF NOT EXISTS tessa_id (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id          INTEGER NOT NULL REFERENCES data_versions(id),
                snapshot_date       TEXT    NOT NULL,
                import_date         TEXT,
                doc_id              TEXT,
                doc_description     TEXT,
                internal_id         TEXT,
                creation_date       TEXT,
                doc_number          TEXT,
                kr_state            TEXT,
                kr_state_id         INTEGER,
                kr_state_ru         TEXT,
                contractor_id       TEXT,            -- CONTRID
                contractor_name     TEXT,            -- CONTR
                kind_id             TEXT,            -- KindID
                kind_name           TEXT,            -- KindName
                name                TEXT,            -- Name (описание документа)
                object_id           TEXT,            -- ObjectID
                object_name         TEXT,            -- ObjectName
                lot                 TEXT,
                podr_1c_id          TEXT,            -- 1C_ID_PODR
                contr_1c_id         TEXT,            -- 1C_ID_CONTR
                source_file         TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tid_version
                ON tessa_id(version_id, object_id);

            -- ── TESSA: Задачи ────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS tessa_tasks (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id          INTEGER NOT NULL REFERENCES data_versions(id),
                snapshot_date       TEXT    NOT NULL,
                import_date         TEXT,
                card_id             TEXT,            -- CardID
                card_name           TEXT,            -- CardName
                card_type_caption   TEXT,            -- CardTypeCaption
                type_id             TEXT,
                type_caption        TEXT,
                option_id           TEXT,
                option_caption      TEXT,
                result              TEXT,
                role_id             TEXT,
                role_name           TEXT,
                author_id           TEXT,
                author_name         TEXT,
                completed           TEXT,
                rn                  INTEGER,
                source_file         TEXT
            );

            -- ── TESSA: Справочник статусов (KrStates) ───────────────────────
            CREATE TABLE IF NOT EXISTS kr_states (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT,        -- Название (ключ)
                comment     TEXT,        -- Комментарий
                en          TEXT,        -- english
                ru          TEXT         -- русское название
            );

            -- ── Ресурсы / ГДРС ───────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS resources (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id      INTEGER NOT NULL REFERENCES data_versions(id),
                snapshot_date   TEXT    NOT NULL,
                period_label    TEXT,            -- "1 неделя", "2 неделя", ...
                date_col        TEXT,            -- конкретная дата из шапки (ISO)
                project         TEXT,            -- Проект
                contractor      TEXT,            -- Подрядчик
                resource_type   TEXT,            -- тип ресурсов (рабочие / техника)
                value           REAL,            -- числовое значение
                col_type        TEXT,            -- 'daily' / 'avg' / 'plan'
                source_file     TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_res_version
                ON resources(version_id, project, resource_type);

            -- ── Плановая выдача РД (other_*_rd.csv) ─────────────────────────
            CREATE TABLE IF NOT EXISTS rd_plan (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id          INTEGER NOT NULL REFERENCES data_versions(id),
                snapshot_date       TEXT    NOT NULL,
                project_name        TEXT,            -- из имени файла
                number              INTEGER,
                cipher              TEXT,            -- Шифр
                section_name        TEXT,            -- Наименование раздела
                count_plan          INTEGER,         -- Количество разделов по Договору
                date_plan           TEXT,            -- Дата выдачи по Договору (ISO)
                source_file         TEXT
            );
        """)

        # KrStates — заполняем один раз (статический справочник)
        cur.execute("SELECT COUNT(*) FROM kr_states")
        if cur.fetchone()[0] == 0:
            _seed_kr_states(cur)


def _seed_kr_states(cur):
    """Вставляет базовые статусы KrStates (из KrStates.csv если не пусто)."""
    defaults = [
        ("KrStates_Doc_Active",    "Активное согласование", "Approving",  "На согласовании"),
        ("KrStates_Doc_Approved",  "Согласован",            "Approved",   "Согласован"),
        ("KrStates_Doc_Declined",  "Отклонён",              "Declined",   "Отклонён"),
        ("KrStates_Doc_Signed",    "Подписан",              "Signed",     "На подписании"),
        ("KrStates_Doc_Draft",     "Черновик",              "Draft",      "Черновик"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO kr_states (name, comment, en, ru) VALUES (?,?,?,?)",
        defaults
    )


def get_active_version(conn) -> dict | None:
    row = conn.execute(
        "SELECT * FROM data_versions WHERE is_active=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def get_all_versions(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM data_versions ORDER BY snapshot_date DESC, id DESC LIMIT 100"
    ).fetchall()
    return [dict(r) for r in rows]


def activate_version(conn, version_id: int):
    conn.execute("UPDATE data_versions SET is_active=0")
    conn.execute("UPDATE data_versions SET is_active=1 WHERE id=?", (version_id,))


def get_kr_state_ru(conn, raw_state: str) -> str:
    """Переводит raw KrState → русское название."""
    if not raw_state:
        return raw_state or ""
    row = conn.execute(
        "SELECT ru FROM kr_states WHERE en=? OR ru=? OR name=? LIMIT 1",
        (raw_state, raw_state, raw_state)
    ).fetchone()
    return row["ru"] if row else raw_state
