"""Диагностика: почему по другим проектам в матрице много Н/Д.

Берём активную версию БД, для каждого проекта проверяем:
- сколько строк есть вообще;
- сколько строк подпадает под критерии каждой ключевой вехи;
- если подпадает 0 — почему (нет имени? нет родителя ур.2 «Ковенанты»? нет нужного уровня?).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_repo))


def _load(version_id: int | None = None) -> pd.DataFrame:
    db = _repo / "data" / "web_data.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if version_id is None:
        version_id = int(cur.execute("SELECT id FROM web_versions WHERE is_active=1").fetchone()["id"])
    rows = []
    for r in cur.execute(
        "SELECT row_data, source_file FROM web_data WHERE version_id=? AND file_type='project'",
        (version_id,),
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
    print(f"Active version rows: {len(df)}")
    print(f"Source files: {sorted(df['__source_file'].dropna().unique().tolist())}")

    if "project name" not in df.columns:
        print("NO 'project name' column!")
        return

    pcounts = df["project name"].fillna("").astype(str).str.strip().value_counts()
    print(f"\nproject name → row counts (top 15):")
    print(pcounts.head(15).to_string())

    from dashboards.dev_projects_tz_matrix import (
        _match_tasks_like_msp_row,
        _control_points_project_group_key,
    )
    from web_loader import _fill_section_from_task_tree

    # Группируем по нормализованному ключу (как UI «Все проекты»)
    df["__pkey"] = df["project name"].map(_control_points_project_group_key)
    keys = [k for k in df["__pkey"].unique() if k]

    # Несколько эталонных вех
    specs = [
        ("ГПЗУ", {
            "level": 5.0,
            "parent_l2_contains": "Ковенанты",
            "names_any": ["ГПЗУ", "гпзу", "Градплан", "градостроительн", "план территории", "Согласование ГП"],
        }),
        ("Аренда ЗУ", {
            "level": 5.0,
            "names_any": ["Регистрация договора субаренды", "Подготовка договора аренды", "договор субаренды", "субаренд"],
            "phase_needles": ["Аренда ЗУ", "субаренд", "Инвестиционная. Аренда", "аренда зу", "договор субаренды"],
        }),
        ("ЗОС", {
            "level": 5.0,
            "parent_l2_contains": "Ковенанты",
            "names_any": ["ЗОС", "Заключение о соответствии"],
        }),
        ("РС", {
            "level": 5.0,
            "parent_l2_contains": "Ковенанты",
            "names_any": ["РС", "Разрешение на строительство", "разрешение на строительство"],
        }),
    ]

    for k in keys:
        sub_all = df[df["__pkey"] == k].reset_index(drop=True)
        if sub_all.empty:
            continue
        plabels = sorted(sub_all["project name"].fillna("").astype(str).str.strip().unique())
        src_files = sorted(sub_all["__source_file"].dropna().unique())
        print(f"\n=== KEY={k!r} (project labels: {plabels}, files: {src_files}, rows: {len(sub_all)}) ===")
        try:
            sub_all = _fill_section_from_task_tree(sub_all)
        except Exception as e:
            print(f"  fill_section error: {e}")

        # outline level distribution
        if "outline level" in sub_all.columns:
            try:
                lv = pd.to_numeric(sub_all["outline level"], errors="coerce").dropna()
                print(f"  outline_level distribution: {lv.value_counts().sort_index().to_dict()}")
            except Exception:
                pass

        # parent l2 unique
        if "section" in sub_all.columns:
            top_sections = sub_all["section"].fillna("").astype(str).str.strip().value_counts().head(8)
            print(f"  top sections: {top_sections.to_dict()}")

        for label, kw in specs:
            try:
                sub = _match_tasks_like_msp_row(sub_all, kw)
                n = 0 if sub is None or getattr(sub, "empty", True) else len(sub)
                print(f"  {label}: matches={n}", end="")
                if n > 0 and "task name" in sub.columns:
                    names = sub["task name"].astype(str).head(3).tolist()
                    print(f"  e.g. {names}")
                else:
                    print()
            except Exception as e:
                print(f"  {label}: ERROR {e}")


if __name__ == "__main__":
    main()
