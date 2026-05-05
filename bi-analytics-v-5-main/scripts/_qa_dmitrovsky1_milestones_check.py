"""Шаг 1.2 QA: сверка вех Дмитровский 1 с эталоном из активной БД.

Использует ту же функцию, что и UI-renderer: build_dev_tz_matrix_rows.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_repo))


def _load_active_msp_dmitrovsky1() -> pd.DataFrame:
    db = _repo / "data" / "web_data.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    vid = int(cur.execute("SELECT id FROM web_versions WHERE is_active=1").fetchone()["id"])
    print(f"Active version id = {vid}")
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
    df = pd.DataFrame(rows)
    print(f"Loaded {len(df)} project rows from active version")
    src_files = sorted(df["__source_file"].dropna().unique().tolist())
    print(f"Source files: {src_files}")
    msp_files = [s for s in src_files if str(s).startswith("msp_dmitrovsky1")]
    print(f"MSP files for Dmitrovsky1: {msp_files}")

    pcol = next(
        (
            c
            for c in df.columns
            if str(c).strip().lower() in ("project name", "проект", "project")
        ),
        None,
    )
    if not pcol:
        raise SystemExit("No project name column")
    mask = df[pcol].fillna("").astype(str).str.strip() == "Дмитровский 1"
    return df[mask].reset_index(drop=True)


def main() -> None:
    df = _load_active_msp_dmitrovsky1()
    print(f"\n=== Дмитровский 1: {len(df)} строк ===")

    from dashboards.dev_projects_tz_matrix import build_dev_tz_matrix_rows

    rows, cap = build_dev_tz_matrix_rows(
        df, None, {}, project_label_for_scope="Дмитровский 1"
    )
    print(f"\ncap (project label) = {cap!r}")
    print(f"matrix rows = {len(rows)}\n")

    print(f"{'group':<22} {'title':<36} {'План':<12} {'Факт':<12} {'Откл':<10}")
    print("-" * 100)
    for r in rows:
        group = str(r.get("group") or "")
        title = str(r.get("label") or r.get("title") or "")
        plan = r.get("plan") or ""
        fact = r.get("fact") or ""
        delta = r.get("otkl") or ""
        print(f"{group[:20]:<22} {title[:34]:<36} {str(plan):<12} {str(fact):<12} {str(delta):<10}")


if __name__ == "__main__":
    main()
