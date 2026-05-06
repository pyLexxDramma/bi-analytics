"""QA E-step для дашборда «02 Причины отклонений».

Считает по активной версии web_data.db (как видит UI) и сверяет с эталоном
напрямую из последних MSP-снимков в `web/AI/msp_*.csv`. Печатает:

  * ТОП-5 причин (количество и %) — для UI должно совпадать с тем что в
    «Доли причин отклонений по проекту» при фильтре «Все проекты».
  * Кол-во строк уровня 5 с непустой причиной и `Окончание − Базовое окончание < 0`
    (детальная таблица «по макету»).
  * Распределение по проектам.

Запуск: `python scripts/_qa_02_reasons_check.py`.
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import traceback
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

from web_loader import WEB_DB_PATH  # noqa: E402
from web_schema import get_active_version_id  # noqa: E402
from utils import smart_to_datetime_series  # noqa: E402


def _load_active_msp() -> pd.DataFrame:
    """Все строки MSP активной версии, склеенные в один DataFrame."""
    ver = get_active_version_id()
    print(f"[INFO] active version_id = {ver}")
    with sqlite3.connect(WEB_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT source_file, COUNT(*) FROM web_data WHERE version_id=? "
            "AND source_file LIKE 'msp_%' GROUP BY source_file",
            (ver,),
        )
        sources = cur.fetchall()
        print(f"[INFO] MSP-источники в активной версии: {len(sources)}")
        for s in sources:
            print(f"   - {s['source_file']}: {s[1]} строк")
        rows = cur.execute(
            "SELECT row_data FROM web_data WHERE version_id=? AND source_file LIKE 'msp_%'",
            (ver,),
        ).fetchall()
    df = pd.DataFrame([json.loads(r["row_data"]) for r in rows])
    return df


def _load_msp_csv_history() -> pd.DataFrame:
    """Все snapshot-ы msp_*.csv из web/AI (за всю историю файлов)."""
    msp_dir = ROOT / "web" / "AI"
    files = sorted(msp_dir.glob("msp_*.csv"))
    print(f"[INFO] всего snapshot-файлов msp_*.csv в web/AI: {len(files)}")
    dfs = []
    encodings = ("utf-8-sig", "cp1251", "windows-1251", "utf-8")
    seps = (";", ",", "\t")
    for fp in files:
        loaded = None
        last_err: Exception | None = None
        for enc in encodings:
            for sep in seps:
                try:
                    loaded = pd.read_csv(
                        fp, sep=sep, encoding=enc, on_bad_lines="skip", low_memory=False
                    )
                    if loaded.shape[1] > 1:
                        break
                except Exception as e:
                    last_err = e
            if loaded is not None and loaded.shape[1] > 1:
                break
        if loaded is None or loaded.empty or loaded.shape[1] <= 1:
            print(f"   ! пропущен {fp.name}: {last_err}")
            continue
        loaded["_snapshot_file"] = fp.name
        dfs.append(loaded)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True, sort=False)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Привести имена колонок к ключам `project name / reason of deviation / ...`."""
    if df is None or df.empty:
        return df
    rename = {}
    cols = {c.lower().strip(): c for c in df.columns}
    candidates = {
        "project name": [
            "project name", "проект", "проект (наименование)", "project_name",
        ],
        "reason of deviation": [
            "reason of deviation", "причины_отклонений", "причины отклонений",
            "причина", "deviation reasons",
        ],
        "level": ["level", "уровень_структуры", "уровень структуры", "уровень"],
        "plan end": ["plan end", "окончание", "окончание (план)", "plan_end"],
        "base end": [
            "base end", "базовое_окончание", "базовое окончание", "base_end",
        ],
        "task name": [
            "task name", "задача", "название задачи", "наименование задачи",
        ],
    }
    for canon, opts in candidates.items():
        for o in opts:
            key = o.lower()
            if key in cols and cols[key] != canon:
                rename[cols[key]] = canon
                break
    if rename:
        df = df.rename(columns=rename)
    return df


def main() -> int:
    print("=" * 78)
    print("QA E-step · «02 Причины отклонений»")
    print("=" * 78)

    df_active = _load_active_msp()
    df_active = _normalize_columns(df_active)
    print(f"\n[ACTIVE DB] всего строк MSP в активной версии: {len(df_active)}")
    print(f"[ACTIVE DB] колонки (фрагмент): {list(df_active.columns)[:14]}")

    if "project name" in df_active.columns:
        proj_counts = df_active["project name"].value_counts(dropna=False)
        print("[ACTIVE DB] распределение по project name (top-15):")
        for p, c in proj_counts.head(15).items():
            print(f"   {c:>6}  {p}")

    if "reason of deviation" in df_active.columns:
        col = df_active["reason of deviation"]
        if isinstance(col, pd.DataFrame):
            col = col.iloc[:, 0]
        rs = col.astype(str).str.strip()
        empties = {"", "nan", "none", "nat", "nd", "—"}
        rs = rs[~rs.str.lower().isin(empties)]
        print(f"\n[ACTIVE DB] непустых причин: {len(rs)} (из {len(df_active)})")
        top = rs.value_counts().head(10)
        denom = float(len(rs) or 1.0)
        print("[ACTIVE DB] ТОП-10 причин (значение / % от непустых):")
        for reason, cnt in top.items():
            pct = cnt / denom * 100.0
            print(f"   {cnt:>5}  ({pct:5.1f}%)  {reason}")
        # Распределение по проектам внутри непустых причин
        if "project name" in df_active.columns:
            print("\n[ACTIVE DB] непустые причины по project name:")
            sub = df_active.loc[rs.index]
            for p, c in sub["project name"].value_counts().items():
                print(f"   {c:>5}  {p}")
    else:
        print("[ACTIVE DB] колонки 'reason of deviation' нет — проверь нормализацию имён.")

    # E-сверка: история snapshot-ов
    print("\n" + "-" * 78)
    print("Сверка с эталоном — все snapshot-ы web/AI/msp_*.csv (что видит визуал 1)")
    print("-" * 78)
    df_hist = _load_msp_csv_history()
    df_hist = _normalize_columns(df_hist)
    print(f"[HIST CSV] всего строк (по всем snapshot-ам): {len(df_hist)}")

    if "reason of deviation" in df_hist.columns:
        col = df_hist["reason of deviation"]
        if isinstance(col, pd.DataFrame):
            col = col.iloc[:, 0]
        rs = col.astype(str).str.strip()
        empties = {"", "nan", "none", "nat", "nd", "—"}
        rs = rs[~rs.str.lower().isin(empties)]
        print(f"[HIST CSV] непустых причин: {len(rs)}")
        top_h = rs.value_counts().head(10)
        denom = float(len(rs) or 1.0)
        print("[HIST CSV] ТОП-10 причин (за всю историю snapshot-ов):")
        for reason, cnt in top_h.items():
            pct = cnt / denom * 100.0
            print(f"   {cnt:>5}  ({pct:5.1f}%)  {reason}")

    # «Детальные данные» по макету: уровень 5 + причина непустая + Окончание − База < 0
    print("\n" + "-" * 78)
    print("«Детальные данные» по макету (UI ожидает то же)")
    print("-" * 78)
    work = df_active.copy()
    work = work.loc[:, ~work.columns.duplicated(keep="first")]

    def _ser(name: str) -> pd.Series:
        if name not in work.columns:
            return pd.Series([float("nan")] * len(work), index=work.index)
        col = work[name]
        if isinstance(col, pd.DataFrame):
            col = col.iloc[:, 0]
        return col

    if "level" in work.columns:
        ln = pd.to_numeric(_ser("level"), errors="coerce")
    else:
        ln = pd.Series([float("nan")] * len(work), index=work.index)
    if "plan end" in work.columns and "base end" in work.columns:
        pe = smart_to_datetime_series(_ser("plan end"))
        be = smart_to_datetime_series(_ser("base end"))
        diff = (be - pe).dt.total_seconds() / 86400.0
    else:
        diff = pd.Series([float("nan")] * len(work), index=work.index)
    if "reason of deviation" in work.columns:
        rs_col = _ser("reason of deviation").astype(str).str.strip()
        empties = {"", "nan", "none", "nat", "nd", "—"}
        rs_filled = ~rs_col.str.lower().isin(empties)
    else:
        rs_filled = pd.Series([False] * len(work), index=work.index)
    mask = (ln == 5) & rs_filled & diff.notna() & (diff < 0)
    print(f"[ACTIVE DB] строк уровня 5 с причиной и Окончание<База: {int(mask.sum())}")
    if int(mask.sum()) > 0:
        sub = work[mask].copy()
        sub["_diff_days"] = diff[mask].astype(int)
        sub = sub.sort_values("_diff_days")
        print("[ACTIVE DB] ТОП-15 самых больших отклонений (отрицательное → опаздывание):")
        for _, r in sub.head(15).iterrows():
            print(
                f"   {r['_diff_days']:>5} дн.  "
                f"{str(r.get('project name',''))[:18]:<18}  "
                f"{str(r.get('task name',''))[:60]}"
            )
            print(
                f"          причина: {str(r.get('reason of deviation',''))[:90]}"
            )

    print("\n[OK] E-сверка по «02 Причины отклонений» завершена.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
