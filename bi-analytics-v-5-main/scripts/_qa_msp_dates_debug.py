"""Дебаг: что именно возвращают _max_date_in_stem / _all_dates_in_stem для MSP-стэмов."""
from __future__ import annotations

import sys
from pathlib import Path

_repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_repo))

from web_loader import _max_date_in_stem, _all_dates_in_stem, _msp_project_bucket

stems = [
    "msp_dmitrovsky1_28-04-2026",
    "msp_dmitrovsky1_30-03-2026",
    "msp_dmitrovsky1_13-04-2026",
    "msp_dmitrovsky1_16-03-2026",
    "msp_dmitrovsky1_02-03-2026",
]
for s in stems:
    print(
        f"{s}: max={_max_date_in_stem(s)}, "
        f"all={_all_dates_in_stem(s)}, "
        f"bucket={_msp_project_bucket(s)!r}"
    )
