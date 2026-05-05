"""Сверка вех Дмитровский 1 напрямую с CSV msp_dmitrovsky1_28-04-2026.csv.

Для нескольких ключевых вех ищем подходящие задачи (по тем же critеriям, что и
build_dev_tz_matrix_rows: уровень, имя, родитель ур.2 и т.п.) и показываем
ID задачи, имя, level, base end, plan end.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_repo))

from web_loader import _apply_msp_column_mapping, _fill_section_from_task_tree

CSV = _repo / "web" / "AI" / "msp_dmitrovsky1_28-04-2026.csv"


def _load() -> pd.DataFrame:
    """Берём строки активной версии БД, отфильтрованные по нужному MSP-файлу.

    После фикса regex `_all_dates_in_stem` активная версия должна содержать
    msp_dmitrovsky1_28-04-2026.csv как самый свежий снимок.
    """
    import json
    import sqlite3

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
    df = df[df["__source_file"].astype(str) == "msp_dmitrovsky1_28-04-2026.csv"].reset_index(drop=True)
    print(f"Rows from msp_dmitrovsky1_28-04-2026.csv: {len(df)}")
    df = _fill_section_from_task_tree(df)
    return df


def _show(df: pd.DataFrame, kw: dict, title: str) -> None:
    from dashboards.dev_projects_tz_matrix import _match_tasks_like_msp_row, _msp_plan_fact_pct, _fmt_date_ru, _delta_days_plan_minus_fact, _fmt_delta_days

    sub = _match_tasks_like_msp_row(df, kw)
    print(f"\n=== {title} ===")
    print(f"matched rows: {0 if sub is None or sub.empty else len(sub)}")
    if sub is None or sub.empty:
        return
    cols_show = [c for c in ("task name", "outline level", "base end", "plan end", "actual finish", "pct complete", "section") if c in sub.columns]
    pd.set_option("display.max_colwidth", 80)
    pd.set_option("display.width", 200)
    print(sub[cols_show].head(10).to_string(index=False))
    from dashboards.dev_projects_tz_matrix import _pick_representative_milestone_row
    r = _pick_representative_milestone_row(sub, pct_scale_max=None)
    pdt, fdt, pct = _msp_plan_fact_pct(r)
    pl = _fmt_date_ru(pdt)
    fl = _fmt_date_ru(fdt)
    if pd.isna(pdt) or pd.isna(fdt):
        otk = "Н/Д"
    else:
        otk = _fmt_delta_days(_delta_days_plan_minus_fact(pdt, fdt))
    print(f"PICKED: task={r.get('task name')!r} level={r.get('outline level')} pct={pct} → План={pl}, Факт={fl}, Откл={otk}")


def main() -> None:
    df = _load()
    print(f"CSV rows: {len(df)}, columns sample: {[c for c in df.columns if 'name' in str(c).lower() or 'end' in str(c).lower() or 'level' in str(c).lower()][:15]}")
    if "project name" in df.columns:
        df = df[df["project name"].astype(str).str.strip() == "Дмитровский 1"].reset_index(drop=True)
        print(f"After project=Дмитровский 1: {len(df)} rows")

    # ГПЗУ
    _show(df, {
        "level": 5.0,
        "parent_l2_contains": "Ковенанты",
        "names_any": ["ГПЗУ", "гпзу", "Градплан", "градостроительн", "план территории", "градостроительного плана", "Согласование ГП"],
    }, "ГПЗУ")

    # ЗОС
    _show(df, {
        "level": 5.0,
        "parent_l2_contains": "Ковенанты",
        "names_any": ["ЗОС", "зос", "Заключение о соответствии", "ЗАКЛЮЧЕНИЕ О СООТВЕТСТВИИ"],
    }, "ЗОС")

    # Право 1
    _show(df, {
        "level": 5.0,
        "parent_l2_contains": "Ковенанты",
        "names_any": ["Право собственности", "Право 1", "право 1", "ПРАВО 1", "право собств"],
    }, "Право 1")

    # ПОС (1 вар)
    _show(df, {
        "level": 5.0,
        "names_any": ["ПОС", "пос ", "Проект организации строительства"],
    }, "ПОС (1 вар)")


if __name__ == "__main__":
    main()
