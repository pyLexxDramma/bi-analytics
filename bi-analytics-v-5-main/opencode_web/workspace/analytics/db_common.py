from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_DB_CANDIDATES = (
    "/workspace/web_data.db",
    "/workspace/data/web_data.db",
    "/workspace/analytics/web_data.db",
)


def parse_db_args(default_output: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default="",
        help="Путь к SQLite web_data.db. Если пусто, берем первый существующий из дефолтных путей.",
    )
    parser.add_argument(
        "--output",
        default=default_output,
        help="Папка для выгрузки результатов.",
    )
    parser.add_argument(
        "--version-id",
        default=0,
        type=int,
        help="Явный version_id. Если 0, будет выбрана активная/последняя success-версия.",
    )
    return parser.parse_args()


def resolve_db_path(cli_path: str = "") -> Path:
    if cli_path:
        path = Path(cli_path)
        if not path.exists():
            raise FileNotFoundError(f"DB file not found: {path}")
        return path
    for candidate in DEFAULT_DB_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path
    raise FileNotFoundError(
        "web_data.db not found. Put DB into one of default locations: "
        + ", ".join(DEFAULT_DB_CANDIDATES)
    )


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def get_effective_version_id(conn: sqlite3.Connection, explicit_version_id: int = 0) -> int:
    if explicit_version_id > 0:
        return int(explicit_version_id)

    row = conn.execute(
        "SELECT id, status FROM web_versions WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row and str(row["status"]) == "success":
        return int(row["id"])

    row = conn.execute(
        "SELECT id FROM web_versions WHERE status = 'success' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row:
        return int(row["id"])

    row = conn.execute(
        "SELECT id FROM web_versions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row:
        return int(row["id"])
    raise RuntimeError("No versions found in web_versions table.")


def query_to_df(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)


def ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_table(df: pd.DataFrame, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(target_path, index=False, encoding="utf-8-sig")
