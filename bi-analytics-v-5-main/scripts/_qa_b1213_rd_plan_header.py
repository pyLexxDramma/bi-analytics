"""B-12/13 sanity-check (2026-05-07).

Проходит по всем `web/AI/other_*_rd.csv` и проверяет, что новый
`_load_rd_plan_file` корректно подбирает строку заголовка (нет `Unnamed: 0..7`)
и опознаёт характерные колонки RD: `ID_проекта`, `Шифр`, `Блок`,
«Наименование работ», «№ Договора».

Запуск:  python scripts/_qa_b1213_rd_plan_header.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_loader import _load_rd_plan_file  # noqa: E402


KEY_COLS = ("ID_проекта", "Шифр", "Блок", "Наименование", "№ Договора")


def main() -> int:
    web_ai = ROOT / "web" / "AI"
    files = sorted(web_ai.glob("other_*_rd.csv"))
    if not files:
        print("Нет файлов other_*_rd.csv в", web_ai)
        return 1
    overall_ok = True
    for fp in files:
        df = _load_rd_plan_file(fp)
        if df is None or df.empty:
            overall_ok = False
            print(f"\n[FAIL] {fp.name}: вернулся None / empty")
            continue
        cols = list(df.columns)
        unnamed = [c for c in cols if str(c).lower().startswith("unnamed")]
        empty = [c for c in cols if not str(c).strip()]
        keys_found = [k for k in KEY_COLS if any(k.lower() in str(c).lower() for c in cols)]
        # Критерий OK:
        #   • нашёлся хотя бы 1 ключ Шифр/Наименование (RD-таблица распознана);
        #   • нет Unnamed > 4 (≤4 — допустимо для месячных групп с пустыми пропусками);
        #   • нет колонок без имени.
        ok = (
            len(empty) == 0
            and len(unnamed) <= 4
            and any(k in keys_found for k in ("Шифр", "Наименование"))
        )
        marker = "OK  " if ok else "FAIL"
        if not ok:
            overall_ok = False
        note = df.attrs.get("rd_plan_header_note", "")
        print(f"\n[{marker}] {fp.name}  rows={len(df)}  cols={len(cols)}")
        print(f"      header: {note}")
        print(f"      Unnamed: {len(unnamed)}; empty-named: {len(empty)}")
        print(f"      keys_found ({len(keys_found)}/{len(KEY_COLS)}): {keys_found}")
        print(f"      first 8 cols: {cols[:8]}")
    print(f"\nИтого: {'OK' if overall_ok else 'WARN'}")
    return 0 if overall_ok else 2


if __name__ == "__main__":
    sys.exit(main())
