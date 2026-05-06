"""Проверка флага warn_pct и корректности применения класса cp-td-warn."""
from __future__ import annotations
import io, json, sqlite3, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import os
os.chdir(ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

from web_loader import WEB_DB_PATH
from web_schema import get_active_version_id
from dashboards.dev_projects_tz_matrix import (
    ensure_msp_df_for_dev_matrix,
    build_control_points_df,
    _is_orange_pct_milestone,
    get_control_point_milestones_effective,
)

vid = get_active_version_id()
print(f"[QA-04W] active vid={vid}")
with sqlite3.connect(WEB_DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT row_data FROM web_data WHERE version_id=? AND source_file LIKE 'msp_%'",
        (vid,),
    ).fetchall()
df = pd.DataFrame([json.loads(r["row_data"]) for r in rows])
df = df.loc[:, ~df.columns.duplicated(keep="first")]
work = ensure_msp_df_for_dev_matrix(df)
view = build_control_points_df(work, hide_completed=False)
print("[QA-04W] view rows:", len(view))
print("[QA-04W] view columns sample:", [c for c in view.columns if c.endswith("_warn_pct") or c.endswith("_ok") or c == "project"][:10])

ms = [(t, s) for t, s, _ in get_control_point_milestones_effective()]
for _, r in view.iterrows():
    proj = r["project"]
    print(f"\n--- {proj} ---")
    for title, slug in ms:
        warn_pct = bool(r.get(f"{slug}_warn_pct"))
        ok = bool(r.get(f"{slug}_ok"))
        is_orange = _is_orange_pct_milestone(slug, title)
        will_orange = is_orange and warn_pct and ok
        marker = " <<< ORANGE EXPECTED" if will_orange else ""
        if is_orange:
            print(f"  [{slug:>10}] {title:<22} warn_pct={warn_pct} ok={ok} is_orange_slug={is_orange} → orange={will_orange}{marker}")
