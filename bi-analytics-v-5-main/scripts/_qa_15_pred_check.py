"""Эталон для дашборда «Неустранённые предписания» (B-15).

Проверяет:
  1) Сколько РЕАЛЬНО уникальных предписаний (после dedup и исключения «Проект»)
  2) Сколько из них устранённых (KrStateID=13) / неустранённых
  3) Заполненность ключевых полей: 1C_ID_DOG, id_Deadline, DocNumber
  4) Распределение по подрядчикам / объектам

Запуск:  python scripts/_qa_15_pred_check.py
Вывод:  scripts/_qa_15_pred_check.last.txt
"""
from __future__ import annotations
from pathlib import Path
import re
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OUT = Path(__file__).with_suffix(".last.txt")


def _all_id_csvs() -> list[Path]:
    files = sorted(WEB.glob("tessa_*-id.csv"))
    def _key(p: Path) -> tuple:
        m = re.search(r"tessa_(\d{2})-(\d{2})-(\d{4})-(\d{2})-(\d{2})", p.stem)
        if m:
            d, mo, y, h, mi = map(int, m.groups())
            return (y, mo, d, h, mi)
        return (0, 0, 0, 0, 0)
    return sorted(files, key=_key)


def _read_csv_any(fp: Path) -> pd.DataFrame | None:
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        for sep in (";", ",", "\t"):
            try:
                d = pd.read_csv(fp, encoding=enc, sep=sep, engine="python")
                if d.shape[1] >= 2:
                    return d
            except (UnicodeDecodeError, UnicodeError, pd.errors.ParserError):
                continue
    return None


def main() -> int:
    out: list[str] = []
    def w(s: str = "") -> None:
        print(s)
        out.append(s)

    files = _all_id_csvs()
    if not files:
        w("[FAIL] Нет файлов tessa_*-id.csv")
        OUT.write_text("\n".join(out), encoding="utf-8")
        return 1

    parts = []
    for fp in files:
        d = _read_csv_any(fp)
        if d is None or d.empty:
            continue
        d.columns = [str(c).strip() for c in d.columns]
        # нормализуем поле даты импорта (Import_data / Import_date) → одна колонка _imp
        if "Import_data" in d.columns:
            d["_imp"] = pd.to_datetime(d["Import_data"], errors="coerce", dayfirst=True)
        elif "Import_date" in d.columns:
            d["_imp"] = pd.to_datetime(d["Import_date"], errors="coerce", dayfirst=True)
        parts.append(d)

    df = pd.concat(parts, ignore_index=True, sort=False)
    df.columns = [str(c).strip() for c in df.columns]
    w(f"СУММАРНО строк tessa_*-id.csv: {len(df)}")

    # Только предписания
    if "KindName" not in df.columns:
        w("[FAIL] Нет колонки KindName")
        OUT.write_text("\n".join(out), encoding="utf-8")
        return 1
    pred = df[df["KindName"].astype(str).str.strip().str.lower().str.startswith("предпис")].copy()
    w(f"Из них предписания: {len(pred)}")

    # Исключаем «Проект» (KrStateID=0 или KrState текстом «Проект»)
    if "KrStateID" in pred.columns:
        krs = pd.to_numeric(pred["KrStateID"], errors="coerce")
        mask_proj_id = krs.eq(0)
    else:
        mask_proj_id = pd.Series(False, index=pred.index)
    if "KrState" in pred.columns:
        mask_proj_text = pred["KrState"].astype(str).str.strip().str.casefold().eq("проект")
    else:
        mask_proj_text = pd.Series(False, index=pred.index)
    pred = pred[~(mask_proj_id | mask_proj_text)].reset_index(drop=True)
    w(f"После исключения «Проект» (KrStateID=0): {len(pred)}")

    # Дедуп по DocID, оставляем последний snapshot
    if "DocID" in pred.columns:
        pred = pred.sort_values(["_imp"], na_position="last", kind="stable")
        pred = pred.drop_duplicates(subset=["DocID"], keep="last").reset_index(drop=True)
    w(f"После dedup по DocID: {len(pred)} уникальных предписаний")
    w("")

    # Распределение по KrStateID
    if "KrStateID" in pred.columns:
        krs = pd.to_numeric(pred["KrStateID"], errors="coerce")
        n_resolved = int((krs == 13).sum())
        n_unresolved = int((krs != 13).sum())
        w(f"# Статусы (по KrStateID):")
        w(f"  Устранённые (KrStateID=13 «Снято»): {n_resolved}")
        w(f"  Неустранённые (всё остальное):       {n_unresolved}")
        w("")
        w("# Распределение по KrState (имя):")
        if "KrState" in pred.columns:
            for k, v in pred["KrState"].astype(str).value_counts().head(20).items():
                w(f"  {str(k):40s} : {int(v):4d}")

    w("")
    w("# Заполненность ключевых полей:")
    for col in ("1C_ID_DOG", "id_Deadline", "DocNumber", "1C_ID_LOT", "Lot"):
        if col in pred.columns:
            n_filled = int(
                pred[col]
                .astype(str)
                .str.strip()
                .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "NaN": pd.NA, "NaT": pd.NA})
                .notna()
                .sum()
            )
            w(f"  {col:20s} : заполнено {n_filled} из {len(pred)} ({100*n_filled/max(1,len(pred)):.0f}%)")
        else:
            w(f"  {col:20s} : КОЛОНКИ НЕТ")

    w("")
    if "CONTR" in pred.columns:
        w("# Распределение по подрядчикам:")
        for k, v in pred["CONTR"].astype(str).str.strip().value_counts().items():
            w(f"  {str(k):40s} : {int(v):4d}")

    w("")
    if "ObjectName" in pred.columns:
        w("# Распределение по объектам:")
        for k, v in pred["ObjectName"].astype(str).str.strip().value_counts().items():
            w(f"  {str(k):40s} : {int(v):4d}")

    OUT.write_text("\n".join(out), encoding="utf-8")
    w("")
    w(f"[OK] Эталон записан: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
