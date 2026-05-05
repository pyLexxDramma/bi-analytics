#!/usr/bin/env python3
# noqa: INP001 — утилита запускается напрямую
"""Offline-сверка таблиц отчёта «Причины отклонений» с файлами msp_*.csv под web/.

Запуск (из каталога bi-analytics-v-5-main/bi-analytics-v-5-main):
  python scripts/verify_deviations_tables_web.py
  python scripts/verify_deviations_tables_web.py --web web --sample-rows 500   # выборка

Проверяется:
  - число строк полной таблицы = числу строк после фильтра отчёта;
  - «Отклонение начала/окончания» и длительности совпадают с тем же кодом, что в UI;
  - строки выгрузки «по макету»: уровень 5, непустая причина, отрицательное отклонение окончания.

Не воспроизводит session_state фильтров (Проект/Период/блок) — только сценарий «все снимки MSP под web», как источник для вкладки с историей снимков.
"""

from __future__ import annotations

import argparse
import io
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_loader import load_data  # noqa: E402

try:
    from web_loader import (  # noqa: E402
        _apply_msp_column_mapping,
        _parse_snapshot_date,
    )
except ImportError as e:  # pragma: no cover
    raise SystemExit(f"Не удалось импортировать web_loader: {e}") from e

from dashboards._renderers import (  # noqa: E402
    build_deviations_maket_export_df,
    build_deviations_reasons_full_table_export_df,
    _dev_days_diff,
    _find_column_by_keywords,
    _project_column_apply_canonical,
)


def _load_msp_snapshots(web_root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    paths = sorted(web_root.rglob("msp_*.csv"))
    for fp in paths:
        name = fp.name
        stem = name.replace(".csv", "").replace(".CSV", "")
        parts = stem.split("_")
        project_slug = parts[1] if len(parts) > 1 else stem
        bio = io.BytesIO(fp.read_bytes())
        bio.name = name
        df = load_data(bio, file_name=name)
        if df is None or getattr(df, "empty", True):
            continue
        df = _apply_msp_column_mapping(df, project_slug)
        snap = _parse_snapshot_date(parts[-1]) if len(parts) > 2 else None
        if snap is not None and "snapshot_date" not in df.columns:
            df["snapshot_date"] = pd.Timestamp(snap)
        frames.append(df)
    if not frames:
        raise SystemExit(f"Под {web_root} не найдено ни одного msp_*.csv")
    return pd.concat(frames, ignore_index=True)


def _reasons_row_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Как во вкладке: задачи с deviation ИЛИ с заполненной причиной."""
    has_deviation_col = "deviation" in df.columns
    has_reason_col = "reason of deviation" in df.columns
    if not (has_deviation_col or has_reason_col):
        return df.copy()
    if has_deviation_col:
        deviation_flag = (
            (df["deviation"] == True)  # noqa: E712
            | (df["deviation"] == 1)
            | (df["deviation"].astype(str).str.lower() == "true")
            | (df["deviation"].astype(str).str.strip() == "1")
        )
    else:
        deviation_flag = pd.Series(False, index=df.index)
    if has_reason_col:
        reason_filled = df["reason of deviation"].notna() & (
            df["reason of deviation"].astype(str).str.strip() != ""
        )
    else:
        reason_filled = pd.Series(False, index=df.index)
    return df[deviation_flag | reason_filled].copy()


def _parse_dd_mm_yyyy(s) -> pd.Timestamp:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return pd.NaT
    t = str(s).strip()
    if not t:
        return pd.NaT
    try:
        return pd.to_datetime(t, format="%d.%m.%Y", errors="coerce")
    except Exception:
        return pd.NaT


def _verify_full_export_matches(filtered: pd.DataFrame, full_csv: pd.DataFrame, sample_rows: int) -> None:
    n = len(filtered)
    if len(full_csv) != n:
        raise AssertionError(f"полная таблица: строк в экспорте {len(full_csv)} ≠ строк после фильтра {n}")

    cols_need = (
        "Начало",
        "Базовое начало",
        "Отклонение начала",
        "Окончание",
        "Базовое окончание",
        "Отклонение окончания",
        "Базовая длительность",
        "Длительность",
    )
    for c in cols_need:
        if c not in full_csv.columns:
            raise AssertionError(f"нет колонки экспорта: {c}")

    rng = random.Random(42)
    idxs = list(range(n))
    if sample_rows > 0 and n > sample_rows:
        idxs = rng.sample(idxs, sample_rows)

    bad = 0
    for i in idxs:
        raw = filtered.iloc[i]
        ex = full_csv.iloc[i]
        ps = raw.get("plan start")
        pe = raw.get("plan end")
        bs = raw.get("base start")
        be = raw.get("base end")
        sd = _dev_days_diff(ps, bs)
        ed = _dev_days_diff(be, pe)
        dur_b = _dev_days_diff(pe, ps)
        dur_f = _dev_days_diff(be, bs)

        def _cmp(exp_txt: str, val: float) -> bool:
            if exp_txt == "" or (isinstance(exp_txt, float) and pd.isna(exp_txt)):
                return pd.isna(val)
            try:
                return int(exp_txt) == int(round(float(val), 0))
            except Exception:
                return False

        # Даты в экспорте — строки dd.mm.yyyy; допускаем расхождение только если обе стороны «пусто»
        def _dcmp(exp_txt: str, ts) -> bool:
            tp = _parse_dd_mm_yyyy(exp_txt)
            tt = pd.to_datetime(ts, errors="coerce", dayfirst=True)
            if (pd.isna(tp) or tp is pd.NaT) and (pd.isna(tt) or tt is pd.NaT):
                return True
            if pd.isna(tp) or pd.isna(tt):
                return False
            try:
                return tp.normalize() == tt.normalize()
            except Exception:
                return False

        ok = True
        ok &= _dcmp(str(ex["Начало"]), bs)
        ok &= _dcmp(str(ex["Базовое начало"]), ps)
        ok &= _cmp(str(ex["Отклонение начала"]), sd)
        ok &= _dcmp(str(ex["Окончание"]), be)
        ok &= _dcmp(str(ex["Базовое окончание"]), pe)
        ok &= _cmp(str(ex["Отклонение окончания"]), ed)
        ok &= _cmp(str(ex["Базовая длительность"]), dur_b)
        ok &= _cmp(str(ex["Длительность"]), dur_f)
        if not ok:
            bad += 1
            print(f"  строка {i}: расхождение формул/дат; фильтр-ряд vs экспорт")

    if bad:
        raise AssertionError(f"выборочная сверка: проблемных строк из проверенных: {bad} / {len(idxs)}")


def _verify_maket_constraints(filtered: pd.DataFrame, maket_csv: pd.DataFrame) -> None:
    if maket_csv.empty:
        print(
            "  maket: 0 строк (ожидаемо, если нет ур.5 с причиной "
            "и отрицательным отклонением окончания)"
        )
        return

    work_m = filtered.copy()
    if "plan end" in work_m.columns:
        work_m["plan end"] = pd.to_datetime(
            work_m["plan end"], errors="coerce", dayfirst=True
        )
    if "base end" in work_m.columns:
        work_m["base end"] = pd.to_datetime(
            work_m["base end"], errors="coerce", dayfirst=True
        )
    work_m["_end_diff"] = np.nan
    if "plan end" in work_m.columns and "base end" in work_m.columns:
        _m = work_m["plan end"].notna() & work_m["base end"].notna()
        work_m.loc[_m, "_end_diff"] = (
            work_m.loc[_m, "base end"] - work_m.loc[_m, "plan end"]
        ).dt.total_seconds() / 86400.0

    mask_r = pd.Series(True, index=work_m.index)
    if "reason of deviation" in work_m.columns:
        mask_r = (
            work_m["reason of deviation"].notna()
            & (work_m["reason of deviation"].astype(str).str.strip() != "")
        )
    mask_l = pd.Series(True, index=work_m.index)
    if "level" in work_m.columns:
        _ln = pd.to_numeric(work_m["level"], errors="coerce")
        mask_l = _ln == 5
    mask_neg = work_m["_end_diff"].notna() & (work_m["_end_diff"] < 0)
    mak_mask_cnt = int((mask_r & mask_l & mask_neg).sum())
    if len(maket_csv) != mak_mask_cnt:
        raise AssertionError(
            f"maket: строк в экспорте {len(maket_csv)} ≠ ожидаемых по фильтрам {mak_mask_cnt}"
        )

    # Отклонение в экспорте — целые дни, должно быть < 0
    for _, r in maket_csv.iterrows():
        v = r.get("Отклонение")
        if v == "" or pd.isna(v):
            raise AssertionError("maket: пустое отклонение при наличии строки")
        if int(v) >= 0:
            raise AssertionError(f"maket: отклонение должно быть < 0, получено {v}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--web",
        type=Path,
        default=ROOT / "web",
        help="Каталог web/ (рекурсивный поиск msp_*.csv)",
    )
    ap.add_argument(
        "--sample-rows",
        type=int,
        default=0,
        help="Сколько случайных строк полной таблицы сверять по формулам (по умолчанию 0 = все строки)",
    )
    args = ap.parse_args()

    web_root: Path = args.web
    if not web_root.is_dir():
        raise SystemExit(f"Нет каталога: {web_root}")

    raw = _load_msp_snapshots(web_root)
    if "project name" in raw.columns:
        raw = _project_column_apply_canonical(raw, "project name")

    filt = _reasons_row_filter(raw)
    notes_col = _find_column_by_keywords(
        filt, ("note", "заметк", "comment", "remark", "notes")
    )
    building_col = _find_column_by_keywords(
        filt, ("building", "строение", "лот", "lot", "bldg")
    )

    full_csv = build_deviations_reasons_full_table_export_df(filt, notes_col)
    maket_csv = build_deviations_maket_export_df(filt, building_col, notes_col)

    print(f"web_root: {web_root}")
    print(f"msp concat rows: {len(raw)}")
    print(f"after deviation|reason filter: {len(filt)}")
    print(f"full table export rows: {len(full_csv)}")
    print(f"maket export rows: {len(maket_csv)}")

    sample_n = args.sample_rows
    if sample_n <= 0:
        sample_n = len(full_csv)
    _verify_full_export_matches(
        filt, full_csv, sample_rows=min(sample_n, len(full_csv))
    )
    _verify_maket_constraints(filt, maket_csv)
    print("OK: сверка таблиц пройдена.")


if __name__ == "__main__":
    main()
