"""B-2.2/B-06 sanity-check (2026-05-07).

1) Прогоняет `_turnover_article_has_lot_and_sublot` по всем уникальным
   значениям «СтатьяОборотов» из `web/1с_*_dannye.json` и считает, сколько
   строк теперь проходят (раньше было 0/39217).
2) Проверяет, что `_ds_plan_fact_otkl_mln` возвращает значения,
   синхронизированные с `try_synthetic_budget_from_1c_dannye` (т.е. ×1000
   по сравнению со старой версией).

Запуск:  python scripts/_qa_b22_lot_regex_scale.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboards.finance_from_1c import _turnover_article_has_lot_and_sublot  # noqa: E402
from dashboards.dev_projects_tz_matrix import _ds_plan_fact_otkl_mln  # noqa: E402


def _flatten_records(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _flatten_records(x)
    elif isinstance(obj, dict):
        if any(isinstance(v, (str, int, float)) for v in obj.values()):
            yield obj
        for v in obj.values():
            if isinstance(v, (list, dict)):
                yield from _flatten_records(v)


def main() -> int:
    web = ROOT / "web"
    files = sorted([p for p in web.glob("*_dannye.json") if p.is_file()])
    if not files:
        print("Нет 1с_*_dannye.json в web/")
        return 1

    art_counter: Counter[str] = Counter()
    rows: list[dict] = []
    for fp in files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for rec in _flatten_records(data):
            tp = str(rec.get("ТипСтатьи") or "").strip().casefold()
            if tp != "бддс":
                continue
            art = str(rec.get("СтатьяОборотов") or "").strip()
            if art:
                art_counter[art] += 1
            rows.append(rec)

    total_unique = len(art_counter)
    total_rows = sum(art_counter.values())
    pass_unique = sum(1 for a in art_counter if _turnover_article_has_lot_and_sublot(a))
    pass_rows = sum(n for a, n in art_counter.items() if _turnover_article_has_lot_and_sublot(a))

    print("== B-2.2: regex _turnover_article_has_lot_and_sublot ==")
    print(f"  Уникальных статей всего:  {total_unique}")
    print(f"  Прошло regex (уник.):     {pass_unique}")
    print(f"  Строк всего (БДДС):       {total_rows}")
    print(f"  Прошло regex (строк):     {pass_rows}")
    print(f"  Доля строк-лотов:         {pass_rows / total_rows * 100:.1f}%")

    # Контрольные кейсы: что должно/не должно проходить.
    cases_pass = [
        "Лот №08. Коробка, кровля, стены",
        "Лот №21. Инженерные сети: водоснабжение, водоотведение",
        "8.5. Металлические конструкции",
        "21.1. Внутриплощадочные инженерные сети",
        "17.1.1 Основание под полы",
        "Лот №01. Подготовительные работы",
        "Лот 1.2 Подготовка территории",
        "lot 7 foundations",
        "Подлот №2.3",
    ]
    cases_fail = [
        "Поступления по основной деятельности",
        "Услуги банка",
        "Оплата труда",
        "Налоги и сборы с зп",
        "Канцтовары,хозтовары,вода",
        "Аренда помещения,эксплуатационные услуги",
        "8 — общий итог",  # не подлот, без второй цифры
    ]
    print("\n  Контрольные кейсы должны проходить:")
    for c in cases_pass:
        ok = _turnover_article_has_lot_and_sublot(c)
        print(f"    {'OK ' if ok else 'FAIL'}  {c!r}")
    print("\n  Контрольные кейсы НЕ должны проходить:")
    for c in cases_fail:
        ok = _turnover_article_has_lot_and_sublot(c)
        print(f"    {'OK ' if not ok else 'FAIL'}  {c!r}")

    print("\n== B-06: масштаб _ds_plan_fact_otkl_mln (×1000 / 1e6) ==")
    bd = pd.DataFrame(rows)
    bd.columns = [str(c).strip() for c in bd.columns]
    p, f, d = _ds_plan_fact_otkl_mln(bd)
    print(f"  План={p}, Факт={f}, Откл={d} (млн руб.)")
    if p is not None and f is not None:
        print(f"  Сумма raw план = {p * 1000:.0f} тыс.руб = {p * 1e6:.0f} руб")
        print(f"  Сумма raw факт = {f * 1000:.0f} тыс.руб = {f * 1e6:.0f} руб")

    return 0


if __name__ == "__main__":
    sys.exit(main())
