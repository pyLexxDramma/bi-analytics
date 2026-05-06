"""QA E-step для дашборда «04 Контрольные точки».

Сценарий:
  1) берём активную версию из web_data.db (msp_*),
  2) для каждого проекта (project name) и каждой вехи из CONTROL_POINT_MILESTONES
     выводим: задача, level, base_end (План), plan_end (Факт), Откл (дни), pct.

Запуск:
  python scripts/_qa_04_control_points.py > scripts/_qa_04_control_points.last.txt
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Привязываем UTF-8 stdout (windows cp1251 ломает кириллицу при перенаправлении).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)


def _load_active_msp_df() -> pd.DataFrame:
    """Читаем активную версию web_data из web_db (sqlite, JSON-rows) и
    оставляем MSP-источники."""
    import json
    import sqlite3

    from web_loader import WEB_DB_PATH
    from web_schema import get_active_version_id

    vid = get_active_version_id()
    print(f"[QA-04] active version_id = {vid}")
    if not vid:
        return pd.DataFrame()

    with sqlite3.connect(WEB_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT row_data FROM web_data "
            "WHERE version_id = ? AND source_file LIKE 'msp_%'",
            (vid,),
        ).fetchall()
    if not rows:
        print("[QA-04] FAIL: нет MSP-строк в активной версии")
        return pd.DataFrame()

    df = pd.DataFrame([json.loads(r["row_data"]) for r in rows])
    df = df.loc[:, ~df.columns.duplicated(keep="first")]
    print(f"[QA-04] MSP rows = {len(df)}")

    # Применяем dev-matrix маппинг колонок (как в дашборде).
    from dashboards.dev_projects_tz_matrix import ensure_msp_df_for_dev_matrix

    work = ensure_msp_df_for_dev_matrix(df)
    print(f"[QA-04] sample cols: {list(work.columns)[:25]} ...")
    return work


def main() -> int:
    from dashboards.dev_projects_tz_matrix import (
        CONTROL_POINT_MILESTONES,
        _match_milestone_tasks,
        _msp_plan_fact_pct,
        _delta_days_plan_minus_fact,
        _fmt_date_ru,
        _fmt_delta_days,
        _pick_representative_milestone_row,
    )

    work = _load_active_msp_df()
    if work.empty:
        print("[QA-04] FAIL: нет данных")
        return 1

    if "project name" not in work.columns:
        print("[QA-04] FAIL: нет колонки 'project name'")
        return 2

    projects = sorted(
        p
        for p in work["project name"].astype(str).str.strip().unique().tolist()
        if p and p.lower() not in ("nan", "none", "—")
    )
    print(f"\n[QA-04] projects ({len(projects)}): {projects}\n")

    # Группируем по проекту, потом по вехе.
    for proj in projects:
        sub = work[work["project name"].astype(str).str.strip() == proj].copy()
        print("=" * 100)
        print(f"PROJECT: {proj}   (rows={len(sub)})")
        print("=" * 100)
        for title, slug, kw in CONTROL_POINT_MILESTONES:
            hits = _match_milestone_tasks(sub, kw)
            n = len(hits) if hits is not None else 0
            if not n:
                print(f"  · [{slug:>10}] {title:<28} → 0 строк (Н/Д)")
                continue
            r = _pick_representative_milestone_row(hits)
            pdt, fdt, pct = _msp_plan_fact_pct(r)
            pl = _fmt_date_ru(pdt)
            fl = _fmt_date_ru(fdt)
            dd = _delta_days_plan_minus_fact(pdt, fdt) if (pd.notna(pdt) and pd.notna(fdt)) else None
            otk = _fmt_delta_days(dd) if dd is not None else "Н/Д"
            tn = str(r.get("task name", "")).strip()
            lvl = r.get("level")
            try:
                lvl_str = f"{int(float(lvl))}" if pd.notna(lvl) else "?"
            except Exception:
                lvl_str = str(lvl)
            pct_str = f"{pct:g}" if pd.notna(pct) else "—"
            warn = ""
            if pd.notna(pct) and float(pct) < 100.0:
                warn += " [%<100]"
            if dd is not None and dd < 0:
                warn += " [LATE]"
            print(
                f"  · [{slug:>10}] {title:<28} hits={n:<3} "
                f"task='{tn[:60]}' lvl={lvl_str} План={pl} Факт={fl} Откл={otk} pct={pct_str}{warn}"
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
