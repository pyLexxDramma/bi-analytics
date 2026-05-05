"""Прогоняем build_dev_tz_matrix_rows для каждого проекта и смотрим, какие ячейки получаются."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_repo))


def _load() -> pd.DataFrame:
    db = _repo / "data" / "web_data.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    vid = int(cur.execute("SELECT id FROM web_versions WHERE is_active=1").fetchone()["id"])
    rows = []
    for r in cur.execute(
        "SELECT row_data, source_file FROM web_data WHERE version_id=? AND file_type='project'",
        (vid,),
    ).fetchall():
        try:
            obj = json.loads(r["row_data"]) if r["row_data"] else {}
        except Exception:
            obj = {}
        obj["__source_file"] = str(r["source_file"])
        rows.append(obj)
    return pd.DataFrame(rows)


def main() -> None:
    df = _load()
    from dashboards.dev_projects_tz_matrix import build_dev_tz_matrix_rows

    for plab in ["Дмитровский 1", "Есипово V", "Ленинский"]:
        print(f"\n========= {plab} =========")
        rows, cap = build_dev_tz_matrix_rows(df, None, {}, project_label_for_scope=plab)
        n_filled = sum(1 for r in rows if (r.get("plan") or "Н/Д") != "Н/Д")
        n_total = len(rows)
        print(f"cap={cap!r}, rows={n_total}, заполненных вех={n_filled}")
        for r in rows:
            print(
                f"  {r.get('label','')[:34]:<36} "
                f"План={r.get('plan','')!s:<12} "
                f"Факт={r.get('fact','')!s:<12} "
                f"Откл={r.get('otkl','')!s:<10}"
            )


if __name__ == "__main__":
    main()
