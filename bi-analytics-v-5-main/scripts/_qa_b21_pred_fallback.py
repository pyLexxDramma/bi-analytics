"""B-2.1 sanity-check (2026-05-07).

Загружаем активную версию web_data.db (или делаем чтение `web/tessa_*.csv`)
и проверяем, что строка «ПРЕДПИСАНИЯ» в матрице «Девелоперские проекты»
больше не возвращает «Н/Д» благодаря фолбэку на `tessa_data` (`*-id.csv`).

Запуск:  python scripts/_qa_b21_pred_fallback.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_schema import WEB_DB_PATH, get_active_version_id  # noqa: E402
from dashboards.dev_projects_tz_matrix import (  # noqa: E402
    _resolve_tessa_pred_source,
    _tessa_counts,
    build_predpisaniya_detail_df,
    _predpisaniya_combined,
)


def _load_table_by_type(file_type: str) -> pd.DataFrame:
    """Собрать DataFrame из web_data.row_data (JSON-строки)."""
    db_path = Path(str(WEB_DB_PATH))
    if not db_path.exists():
        return pd.DataFrame()
    ver = get_active_version_id()
    if not ver:
        return pd.DataFrame()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT row_data FROM web_data WHERE version_id=? AND file_type=?",
            (ver, file_type),
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    parsed = []
    for r in rows:
        raw = r["row_data"]
        if not raw:
            continue
        try:
            parsed.append(json.loads(raw))
        except Exception:
            continue
    return pd.DataFrame(parsed) if parsed else pd.DataFrame()


def main() -> int:
    print("== B-2.1 ПРЕДПИСАНИЯ fallback check ==")
    db_path = Path(str(WEB_DB_PATH))
    print(f"WEB_DB_PATH = {db_path} (exists={db_path.exists()})")

    tasks = _load_table_by_type("tessa_tasks")
    ids = _load_table_by_type("tessa")
    print(f"  tessa_tasks_data rows = {len(tasks)} cols = {list(tasks.columns)[:12]}")
    print(f"  tessa_data        rows = {len(ids)}  cols = {list(ids.columns)[:12]}")

    class _SS:
        def __init__(self, mp):
            self._d = mp

        def get(self, k, default=None):
            return self._d.get(k, default)

    ss = _SS({"tessa_tasks_data": tasks, "tessa_data": ids})

    pred, kk, src = _resolve_tessa_pred_source(ss)
    print(f"\n_resolve_tessa_pred_source → src={src!r}, KindName col={kk!r}, rows={len(pred)}")
    if not pred.empty:
        print("  пример первой строки (KindName, ObjectName/Lot/CardId/Status):")
        for c in ("KindName", "ObjectName", "Lot", "CardId", "CardID", "DocID", "KrState", "KrStateName"):
            if c in pred.columns:
                v = pred[c].iloc[0]
                print(f"    {c} = {v!r}")

    print("\n_tessa_counts(ss, project_name_hint='') →")
    tp, tf, to, hint = _tessa_counts(ss, "")
    print(f"  План={tp!r}, Факт={tf!r}, Откл={to!r}, hint={hint!r}")

    for proj in ("Дмитровский 1", "Есипово V", "Ленинский"):
        tp, tf, to, hint = _tessa_counts(ss, proj)
        print(f"  [{proj}] План={tp!r}, Факт={tf!r}, Откл={to!r}, hint={hint!r}")

    print("\n_predpisaniya_combined(empty_msp, ss, '') →")
    tp, tf, to, warn, hint = _predpisaniya_combined(pd.DataFrame(), ss, "")
    print(f"  План={tp!r}, Факт={tf!r}, Откл={to!r}, warn={warn}, hint={hint!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
