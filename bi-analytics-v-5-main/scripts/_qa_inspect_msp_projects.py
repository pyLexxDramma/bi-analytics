"""Быстрый инспектор колонки 'Проект' и нормализованных групп MSP-файлов."""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import pandas as pd

_repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_repo))

from dashboards.dev_projects_tz_matrix import (  # type: ignore
    _control_points_project_group_key,
    _control_points_project_label,
    _norm_dev_project_key,
)


def _read(path: Path) -> pd.DataFrame:
    last_err = None
    for enc in ("cp1251", "utf-8-sig", "utf-8"):
        for sep in (";", ","):
            try:
                return pd.read_csv(
                    path,
                    sep=sep,
                    encoding=enc,
                    on_bad_lines="skip",
                    low_memory=False,
                    dtype=str,
                )
            except Exception as e:
                last_err = e
    raise RuntimeError(f"Failed to read {path}: {last_err}")


def main() -> None:
    files = sorted(glob.glob(str(_repo / "web" / "AI" / "msp_*_28-04-2026.csv")))
    if not files:
        files = sorted(glob.glob(str(_repo / "web" / "AI" / "msp_*.csv")))[-3:]
    print(f"Files inspected ({len(files)}):")
    for f in files:
        print(" -", Path(f).name)

    all_projects: set[str] = set()
    all_norm: dict[str, set[str]] = {}
    all_groups: dict[tuple[str, str], set[str]] = {}

    for f in files:
        df = _read(Path(f))
        col = None
        for c in df.columns:
            if str(c).strip().lower() in ("проект", "project", "project name", "project_name"):
                col = c
                break
        print(f"\n=== {Path(f).name} ===")
        print(f"  columns: {len(df.columns)}; rows: {len(df)}; project_col: {col!r}")
        print(f"  all columns: {list(df.columns)}")
        if not col:
            for c in df.columns:
                low = str(c).strip().lower().replace(" ", "")
                if "проект" in low or "project" in low:
                    col = c
                    print(f"  -> fallback project_col guess: {col!r}")
                    break
        if not col:
            continue
        vals = df[col].fillna("").astype(str).str.strip()
        vc = vals[vals != ""].value_counts()
        print(f"  unique 'Проект' values ({len(vc)}):")
        for v, n in vc.items():
            nk = _norm_dev_project_key(v)
            gk = _control_points_project_group_key(v)
            gl = _control_points_project_label(v)
            print(f"    {n:5d}  raw={v!r}  norm={nk!r}  group_key={gk!r}  group_label={gl!r}")
            all_projects.add(v)
            all_norm.setdefault(nk, set()).add(v)
            all_groups.setdefault((gk, gl), set()).add(v)

    print("\n=== Aggregated across files ===")
    print(f"unique raw project labels: {len(all_projects)}")
    for v in sorted(all_projects):
        print("  -", v)
    print(f"\nnorm keys ({len(all_norm)}):")
    for k, v in sorted(all_norm.items()):
        print(f"  {k!r:30}  ← {sorted(v)}")
    print(f"\ngroup keys ({len(all_groups)}):")
    for (gk, gl), v in sorted(all_groups.items()):
        print(f"  group_key={gk!r:30} label={gl!r:30}  ← {sorted(v)}")


if __name__ == "__main__":
    main()
