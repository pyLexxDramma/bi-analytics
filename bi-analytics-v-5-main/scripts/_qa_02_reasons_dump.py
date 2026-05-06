"""Дамп уникальных значений `reason of deviation` для диагностики."""
from __future__ import annotations
import io, json, sqlite3, sys
from collections import Counter
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

from web_loader import WEB_DB_PATH
from web_schema import get_active_version_id

ver = get_active_version_id()
with sqlite3.connect(WEB_DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT row_data FROM web_data WHERE version_id=? AND source_file LIKE 'msp_%'",
        (ver,),
    ).fetchall()

df = pd.DataFrame([json.loads(r["row_data"]) for r in rows])
print("[INFO] active version:", ver, "rows:", len(df))
print("[INFO] columns с 'reason' в названии:")
for c in df.columns:
    if "reason" in c.lower() or "причин" in c.lower():
        print(f"   - {c!r}  dtype={df[c].dtype}")

col_name = "reason of deviation" if "reason of deviation" in df.columns else None
if col_name is None:
    sys.exit("колонки 'reason of deviation' нет")

s = df[col_name]
if isinstance(s, pd.DataFrame):
    s = s.iloc[:, 0]

print(f"\n[INFO] dtype col {col_name!r}: {s.dtype}")
print("[INFO] count notna():", int(s.notna().sum()))

# Какие типы внутри?
type_counter = Counter(type(v).__name__ for v in s)
print("[INFO] распределение типов значений:")
for k, v in type_counter.most_common():
    print(f"   {v:>5}  {k}")

# Уникальные значения с подсчётом
values = s.astype(object).fillna("__PD_NA__")
counter = Counter()
for v in values:
    sv = repr(v)[:80]
    counter[sv] += 1
print("\n[INFO] ТОП-20 уникальных литералов (repr):")
for v, c in counter.most_common(20):
    print(f"   {c:>5}  {v}")
