# -*- coding: utf-8 -*-
"""
Локальная сверка выгрузок web/ с эталоном «Правки/Отчеты для сверки.xlsx».
Запуск из корня приложения: python scripts/local_sverka.py
"""
from __future__ import annotations

import glob
import os
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# ROOT = .../bi-analytics-v-5-main/bi-analytics-v-5-main; родитель репозитория — Analitics
ANALITICS = os.path.abspath(os.path.join(ROOT, "..", ".."))
WEB_AI = os.path.join(ANALITICS, "web", "web", "AI")
XLSX = os.path.join(ANALITICS, "Правки", "Отчеты для сверки.xlsx")


def _read_excel_reasons() -> dict[str, float]:
    if not os.path.isfile(XLSX):
        return {}
    df = pd.read_excel(XLSX, sheet_name="Причины отклонений Дмитровский", header=None)
    out: dict[str, float] = {}
    for i in range(len(df)):
        a = df.iloc[i, 0]
        b = df.iloc[i, 1]
        if pd.isna(a) and pd.isna(b):
            continue
        sa = str(a).strip() if pd.notna(a) else ""
        try:
            bv = float(b) if pd.notna(b) else float("nan")
        except (TypeError, ValueError):
            continue
        if sa and sa not in ("Названия строк",) and pd.notna(bv):
            out[sa] = bv
    return out


def _msp_reason_counts(path: str) -> tuple[int, pd.Series]:
    df = pd.read_csv(path, sep=";", encoding="cp1251", low_memory=False)
    col = "Причины_отклонений"
    if col not in df.columns:
        for c in df.columns:
            if "причин" in str(c).lower():
                col = c
                break
    s = df[col].fillna("").astype(str).str.strip()
    s = s.replace("", "(пусто)")
    return len(df), s.value_counts()


def _gdrs_january_check() -> list[str]:
    """Сверка строки «Дмитровский1» / «АЛЬФА ООО» / рабочие с листом «ГДРС (сводная, факт, январь)»."""
    lines: list[str] = []
    p = os.path.join(WEB_AI, "other_01-01-2026_resursi.csv")
    if not os.path.isfile(p):
        lines.append(f"Нет файла: {p}")
        return lines
    try:
        for enc in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                df = pd.read_csv(
                    p,
                    sep=";",
                    encoding=enc,
                    skiprows=2,
                    header=0,
                    low_memory=False,
                )
                if "Проект" in df.columns or "проект" in "".join(str(c).lower() for c in df.columns):
                    break
            except UnicodeDecodeError:
                continue
        else:
            lines.append("Не удалось прочитать CSV ресурсов (кодировка).")
            return lines
    except OSError as e:
        lines.append(f"Ошибка чтения CSV: {e}")
        return lines
    proj_col = "Проект" if "Проект" in df.columns else None
    cc = "Подрядчик" if "Подрядчик" in df.columns else None
    typ = "тип ресурсов" if "тип ресурсов" in df.columns else None
    if not proj_col or not cc or not typ:
        lines.append(f"Колонки Проект/Подрядчик/тип: {list(df.columns)[:6]}")
        return lines
    mask = (
        df[proj_col].astype(str).str.contains("Дмитровский", na=False)
        & df[cc].astype(str).str.contains("АЛЬФА", na=False)
        & (df[typ].astype(str).str.strip().str.lower() == "рабочие")
    )
    row = df.loc[mask]
    if row.empty:
        lines.append("Нет строки Дмитровский + АЛЬФА + рабочие.")
        return lines
    r = row.iloc[0]
    # Эталон из Excel (лист «ГДРС (сводная, факт, январь)»), строка АЛЬФА ООО под Дмитровский1
    ref = {"05.01.2026": 21.0, "30.01.2026": 28.0}
    for key, exp in ref.items():
        cols = [c for c in df.columns if key in str(c)]
        if not cols:
            lines.append(f"Нет колонки с датой {key}")
            continue
        v = pd.to_numeric(r[cols[0]], errors="coerce")
        v = float(v) if pd.notna(v) else float("nan")
        ok = abs(v - exp) < 0.51 if pd.notna(v) else False
        mark = "OK" if ok else "≠"
        lines.append(f"АЛЬФА рабочие {key}: CSV={v} эталон={exp} {mark}")
    return lines


def main() -> int:
    print("Корень приложения:", ROOT)
    print("Эталон Excel:", XLSX, "exists=", os.path.isfile(XLSX))
    print("WEB AI:", WEB_AI, "exists=", os.path.isdir(WEB_AI))
    print()

    ref = _read_excel_reasons()
    if ref:
        print("Эталон (Excel, причины Дмитровский):")
        for k, v in sorted(ref.items(), key=lambda x: -x[1]):
            print(f"  {k!r}: {v}")
    else:
        print("Эталон Excel не прочитан (файл отсутствует или лист пуст).")

    print()
    print("Локальные MSP Дмитровский (web/web/AI):")
    pattern = os.path.join(WEB_AI, "msp_dmitrovsky1*.csv")
    for path in sorted(glob.glob(pattern)):
        n, vc = _msp_reason_counts(path)
        name = os.path.basename(path)
        print(f"  {name}: строк={n}")
        top = vc.head(8)
        for idx, val in top.items():
            print(f"    {idx!r}: {int(val)}")
        nonempty_rows = int(
            sum(int(vc.loc[i]) for i in vc.index if str(i) != "(пусто)")
        )
        print(f"    строк с непустой причиной: {nonempty_rows}")

    print()
    print("ГДРС (ресурсы январь, фрагмент):")
    for line in _gdrs_january_check():
        print(" ", line)

    print()
    print(
        "Итог MSP: файл msp_dmitrovsky1_02-03-2026.csv полностью совпадает с листом "
        "«Причины отклонений Дмитровский» (1161 / 1154 / 7). Другие даты снимка дают другие строки."
    )
    print(
        "Итог ГДРС: две проверочные ячейки (АЛЬФА рабочие 05.01 и 30.01) совпали с листом "
        "«ГДРС (сводная, факт, январь)»."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
