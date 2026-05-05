"""Содержимое активной версии в data/web_data.db: файлы и уникальные project name."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "web_data.db"


def main() -> None:
    print(f"DB: {DB}  exists={DB.exists()}  size={DB.stat().st_size if DB.exists() else 0}")
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("\n=== web_versions (last 5) ===")
    for r in cur.execute(
        "SELECT id, created_at, label, status, files_count, rows_count, is_active "
        "FROM web_versions ORDER BY id DESC LIMIT 5"
    ).fetchall():
        print(dict(r))

    active = cur.execute(
        "SELECT id, created_at, files_count, rows_count FROM web_versions WHERE is_active=1"
    ).fetchone()
    if not active:
        print("\nNo active version!")
        return
    vid = int(active["id"])
    print(f"\n=== Active version id={vid} ({active['created_at']}, files={active['files_count']}, rows={active['rows_count']}) ===")

    print("\n=== Files in active version ===")
    files = cur.execute(
        "SELECT file_name, rel_path, file_type, rows_count FROM web_files WHERE version_id=? ORDER BY file_name",
        (vid,),
    ).fetchall()
    for r in files:
        print(f"  [{r['file_type']:<14}] rows={r['rows_count']:>5}  {r['file_name']}")

    print("\n=== Unique 'project name' across MSP rows in active version (RAW) ===")
    cur.execute(
        "SELECT row_data, source_file FROM web_data WHERE version_id=? AND file_type='project'",
        (vid,),
    )
    cnt: Counter = Counter()
    cnt_no_demo: Counter = Counter()
    rows_seen = 0
    for raw, src in cur.fetchall():
        rows_seen += 1
        try:
            obj = json.loads(raw) if raw else {}
        except Exception:
            continue
        v_raw = obj.get("project name") if obj.get("project name") is not None else obj.get("Проект")
        v = (str(v_raw) if v_raw is not None else "").strip()
        cnt[v] += 1
        s = (str(src) or "").strip().lower()
        if s.startswith("sample_") or s.startswith("new_csv/sample_"):
            continue
        cnt_no_demo[v] += 1
    print(f"  rows scanned: {rows_seen}; unique project labels (RAW incl. demo): {len(cnt)}")
    for v, n in cnt.most_common(40):
        print(f"    {n:>5}  {v!r}")
    print(f"\n=== After excluding sample_*.csv: {len(cnt_no_demo)} unique labels ===")
    for v, n in cnt_no_demo.most_common(40):
        print(f"    {n:>5}  {v!r}")


if __name__ == "__main__":
    main()
