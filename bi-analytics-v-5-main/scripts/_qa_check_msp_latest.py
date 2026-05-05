"""Проверяем, какие MSP-файлы видит сканер web/ и какие оставляет pick_latest_snapshot_files."""
from __future__ import annotations

import sys
from pathlib import Path

_repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_repo))

from web_loader import scan_web_files, pick_latest_snapshot_files

files = scan_web_files()
print(f"Scanned files total: {len(files)}")
msp = [f for f in files if str(f.get("name", "")).lower().startswith("msp_dmitrovsky1")]
print("Found MSP dmitrovsky1 files in scan:")
for f in msp:
    print(" ", f["rel_path"])

kept, warns = pick_latest_snapshot_files(files)
print(f"\nAfter pick_latest_snapshot_files: {len(kept)} kept (of {len(files)})")
msp_kept = [f for f in kept if str(f.get("name", "")).lower().startswith("msp_dmitrovsky1")]
print("MSP dmitrovsky1 kept:")
for f in msp_kept:
    print(" ", f["rel_path"])
