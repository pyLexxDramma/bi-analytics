"""Sanity-check: распознавание типа `pd_plan` для гипотетических other_*_pd.csv."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_loader import _infer_file_type_by_name  # type: ignore

cases = [
    ("other_dmitrovsky1_01.04.2025_pd.csv", "pd_plan"),
    ("other_esipovo5_10.04.2025_pd.csv", "pd_plan"),
    ("other_leninsky_30.04.2026_pd.csv", "pd_plan"),
    ("other_dmitrovsky1_01.04.2025_rd.csv", "rd_plan"),
    ("other_leninsky_10.04.2025_rd.csv", "rd_plan"),
    ("msp_dmitrovsky1_28-04-2026.csv", "msp"),
    ("other_01-02-2026_resursi.csv", "resources"),
]

ok = True
for name, expected in cases:
    got = _infer_file_type_by_name(name)
    mark = "OK" if got == expected else "FAIL"
    if got != expected:
        ok = False
    print(f"  [{mark}] {name:48s}: got={got!r}, expected={expected!r}")

sys.exit(0 if ok else 1)
