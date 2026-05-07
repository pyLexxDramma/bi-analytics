"""B-12/13.2: проверка fallback-вью «План выдачи РД» при отсутствии MSP-колонок.

Ожидание:
    1. После загрузки `web/AI/other_*_rd.csv` в `rd_plan_data` появляется
       колонка `project name` (Дмитровский 1 / Есипово V / Ленинский).
    2. Из объединённого DataFrame можно построить агрегацию по проекту:
       строк × min/max плановой и прогнозной даты × количество просроченных.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import MSP_PROJECT_NAME_MAP  # type: ignore
from web_loader import _load_rd_plan_file, _parse_snapshot_date  # type: ignore


def _attach_project_name(df: pd.DataFrame, name: str) -> pd.DataFrame:
    stem = name.lower().replace(".csv", "")
    parts = stem.split("_")
    proj_token = parts[1] if len(parts) > 2 and parts[0] == "other" else ""
    proj_label = MSP_PROJECT_NAME_MAP.get(proj_token, "")
    if proj_label and "project name" not in df.columns:
        df = df.copy()
        df["project name"] = proj_label
    snap = None
    for p in reversed(parts):
        snap = _parse_snapshot_date(p)
        if snap is not None:
            break
    if snap is not None and "snapshot_date" not in df.columns:
        df["snapshot_date"] = pd.Timestamp(snap)
    return df


def main() -> int:
    web = ROOT / "web" / "AI"
    files = sorted(web.glob("other_*_rd.csv"))
    if not files:
        print("[FAIL] нет файлов other_*_rd.csv в web/AI/")
        return 1

    frames: list[pd.DataFrame] = []
    for f in files:
        df = _load_rd_plan_file(f)
        if df is None or df.empty:
            print(f"  [SKIP] {f.name}: пусто")
            continue
        df = _attach_project_name(df, f.name)
        frames.append(df)
        plab = df["project name"].iloc[0] if "project name" in df.columns else "—"
        snap = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else "—"
        print(f"  OK {f.name}: {len(df):>4} строк, project={plab!r}, snapshot={snap}")

    rd_plan = pd.concat(frames, ignore_index=True)
    print(f"\n[combined] rows={len(rd_plan)}, columns={list(rd_plan.columns)[:6]}...")

    if "project name" not in rd_plan.columns:
        print("[FAIL] нет 'project name' в combined")
        return 1

    plan_col = "Дата выдачи разделов по Договору"
    forecast_col = "Прогнозная дата выдачи разделов"

    rd_plan["_plan_dt"] = pd.to_datetime(rd_plan[plan_col], errors="coerce", dayfirst=True, format="mixed")
    rd_plan["_fact_dt"] = (
        pd.to_datetime(rd_plan[forecast_col], errors="coerce", dayfirst=True, format="mixed")
        if forecast_col in rd_plan.columns
        else pd.NaT
    )
    rd_plan["_delta_days"] = (rd_plan["_fact_dt"] - rd_plan["_plan_dt"]).dt.days

    print("\n[ Агрегация по проекту ]")
    agg = (
        rd_plan.groupby("project name", dropna=False)
        .agg(
            всего_разделов=("project name", "count"),
            план_min=("_plan_dt", "min"),
            план_max=("_plan_dt", "max"),
            прогноз_min=("_fact_dt", "min"),
            прогноз_max=("_fact_dt", "max"),
            просрочено=("_delta_days", lambda s: int((s > 0).sum())),
            ср_задержка_дн=("_delta_days", lambda s: round(float(s[s > 0].mean()), 1) if (s > 0).any() else 0),
        )
        .reset_index()
    )
    print(agg.to_string(index=False))

    expected = {"Дмитровский 1": 117 + 48, "Есипово V": 225 + 48, "Ленинский": 217 + 215 + 48}
    ok = True
    for proj, exp in expected.items():
        got = int(rd_plan[rd_plan["project name"] == proj].shape[0])
        marker = "OK" if got == exp else "FAIL"
        if got != exp:
            ok = False
        print(f"  [{marker}] {proj}: got={got}, expected={exp}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
