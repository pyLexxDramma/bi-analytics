"""Заполненность колонок «Детальные данные» (UI «Причины отклонений»).

Фильтр UI: уровень 5 + reason of deviation непустой + (Окончание − База) < 0.
"""
from __future__ import annotations
import io, json, sqlite3, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

from web_loader import WEB_DB_PATH
from web_schema import get_active_version_id
from utils import smart_to_datetime_series

ver = get_active_version_id()
print(f"[INFO] active version_id: {ver}")
with sqlite3.connect(WEB_DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT row_data FROM web_data WHERE version_id=? AND source_file LIKE 'msp_%'",
        (ver,),
    ).fetchall()
df = pd.DataFrame([json.loads(r["row_data"]) for r in rows])
df = df.loc[:, ~df.columns.duplicated(keep="first")]
print(f"[INFO] всего строк: {len(df)}, колонки: {len(df.columns)}")

# Имитация UI-фильтра
ln = pd.to_numeric(df.get("level"), errors="coerce") if "level" in df.columns else pd.Series([float("nan")] * len(df))
pe = smart_to_datetime_series(df["plan end"]) if "plan end" in df.columns else pd.Series([pd.NaT] * len(df))
be = smart_to_datetime_series(df["base end"]) if "base end" in df.columns else pd.Series([pd.NaT] * len(df))
diff = (be - pe).dt.total_seconds() / 86400.0
rs = df.get("reason of deviation")
rs_filled = rs.notna() & (rs.astype(str).str.strip() != "") if rs is not None else pd.Series([False] * len(df))

mask = (ln == 5) & rs_filled & diff.notna() & (diff < 0)
sub = df[mask].copy()
print(f"\n[FILTER] уровень 5 + причина + Окончание<База: {len(sub)} строк")
print(f"[FILTER] распределение по project name:")
for p, c in sub["project name"].value_counts().items():
    print(f"   {c:>5}  {p}")

# Заполненность ключевых колонок
def _fillrate(s: pd.Series) -> tuple[int, int, float]:
    if s is None:
        return (0, 0, 0.0)
    sv = s.astype(str).str.strip()
    notempty = sv.ne("") & ~sv.str.lower().isin({"nan", "none", "nat", "—", "nd"})
    cnt = int(notempty.sum())
    return (cnt, len(s), 100.0 * cnt / max(1, len(s)))

print("\n[FILL] заполненность колонок таблицы (UI):")

def _find(df_, names):
    for n in names:
        for c in df_.columns:
            if c.lower() == n.lower():
                return c
    # fuzzy: подстрока
    for n in names:
        for c in df_.columns:
            if n.lower() in c.lower():
                return c
    return None

cols_check = {
    "Проект": ["project name", "проект"],
    "Функциональный блок": ["block", "функциональный блок", "блок"],
    "Строение": ["building", "строение", "лот", "lot", "bldg"],
    "Базовое окончание": ["base end", "базовое окончание"],
    "Окончание": ["plan end", "окончание"],
    "Причина отклонения": ["reason of deviation", "причины_отклонений", "причины отклонений"],
    "Заметки": ["notes", "заметки", "comment", "remark"],
}
for label, names in cols_check.items():
    col = _find(sub, names)
    if col is None:
        print(f"   [---]  {label:<22}  колонки нет в данных")
    else:
        f, t, p = _fillrate(sub[col])
        print(f"   {p:5.1f}%  {label:<22}  {f}/{t}  (колонка: {col!r})")

# Покажу примеры строк с пустыми «Строение»/«Заметки»
print("\n[EXAMPLES] первые 10 строк фильтра (для глаза):")
out_cols = []
for label, names in cols_check.items():
    c = _find(sub, names)
    if c:
        out_cols.append((label, c))
print("  | " + " | ".join(l for l, _ in out_cols))
for i, (_, r) in enumerate(sub.head(10).iterrows(), start=1):
    parts = []
    for _, c in out_cols:
        v = r.get(c)
        s = "" if pd.isna(v) else str(v)
        if len(s) > 28:
            s = s[:25] + "..."
        parts.append(s)
    print(f"  {i:>2}| " + " | ".join(parts))
