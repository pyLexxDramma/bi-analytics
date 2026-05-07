"""B-16/17 ГДРС — golden для марта 2026 (проверка парсера + агрегатора).

Эталон со скрина ТЗ заказчика 2026-05-07 (Скрин 11):

  Дмитровский-1   План=181  СКУД=67   Откл=-114  1н=67  2н=85  3н=73  4н=53  5н=59  6н=56   Δ=-63%
  Ленинский       План=216  СКУД=76   Откл=-140  1н=51  2н=104 3н=84  4н=70  5н=74  6н=73   Δ=-65%
  Есипово-5       План=345  СКУД=43   Откл=-302  1н=35  2н=52  3н=45  4н=41  5н=43  6н=42   Δ=-88%
  Итого           План=742  СКУД=185  Откл=-557  1н=153 2н=240 3н=202 4н=165 5н=176 6н=171  Δ=-75%

Источник: web/AI/other_30-03-2026_07-00_resursi.csv + web/1с_*_Dogovor.json + spravochniki.json
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WEB = ROOT / "web"

import pandas as pd  # noqa: E402

from dashboards.gdrs_resursi import (  # noqa: E402
    build_main_table,
    build_summary_table,
    load_plan_aggregate,
    load_resursi_files,
)


def main() -> int:
    march_csvs = list((WEB / "AI").glob("*30-03-2026*resursi*.csv"))
    if not march_csvs:
        march_csvs = list((WEB / "AI").glob("*-03-2026*resursi*.csv"))
    if not march_csvs:
        print("[FAIL] нет ресурсного CSV за март 2026")
        return 1
    print(f"[resursi] {[p.name for p in march_csvs]}")
    long_fact = load_resursi_files(march_csvs)
    print(f"[long_fact] {long_fact.shape}, проектов={long_fact['project_name'].nunique()}, "
          f"контрагентов={long_fact['contractor_name'].nunique()}, "
          f"vid={sorted(long_fact['vid_resursa'].unique().tolist())}, "
          f"дат={long_fact['date'].nunique()}, диапазон={long_fact['date'].min()}..{long_fact['date'].max()}")

    snapshot_date = pd.Timestamp("2026-03-31")
    dogovor_files = sorted(WEB.glob("*_Dogovor.json"))
    sprav_files = sorted(WEB.glob("*_spravochniki.json"))
    print(f"[Dogovor.json] {len(dogovor_files)} файлов (агрегируем все, snapshot 'не позже' {snapshot_date.date()})")
    print(f"[spravochniki.json] {len(sprav_files)} файлов (fallback)")

    plan = load_plan_aggregate(dogovor_files, sprav_files, snapshot_date=snapshot_date)
    print(f"[plan merged] {len(plan)} строк, "
          f"workers_total={plan['plan_workers'].sum() if not plan.empty else 0}, "
          f"equip_total={plan['plan_equipment'].sum() if not plan.empty else 0}")

    print("\n=== ГЛАВНАЯ ТАБЛИЦА (Скрин 11) — vid='Рабочие', март 2026, only_with_plan=True ===")
    main_t = build_main_table(long_fact, plan, vid="Рабочие", only_with_plan=True)
    if main_t.empty:
        print("[FAIL] таблица пуста")
        return 1
    sub = main_t[main_t["row_kind"].isin(("subtotal", "grand_total"))].copy()
    print(sub[[
        "project_name", "row_kind", "plan", "skud", "deviation",
        "w1", "w2", "w3", "w4", "w5", "w6", "delta_pct",
    ]].to_string(index=False, formatters={
        "plan": lambda x: f"{x:>7.0f}",
        "skud": lambda x: f"{x:>7.0f}",
        "deviation": lambda x: f"{x:>+8.0f}",
        "w1": lambda x: f"{x:>5.0f}", "w2": lambda x: f"{x:>5.0f}",
        "w3": lambda x: f"{x:>5.0f}", "w4": lambda x: f"{x:>5.0f}",
        "w5": lambda x: f"{x:>5.0f}", "w6": lambda x: f"{x:>5.0f}",
        "delta_pct": lambda x: "—" if pd.isna(x) else f"{x:>+6.1f}%",
    }))

    expected = {
        "Дмитровский-1": (181, 67, -114, [67, 85, 73, 53, 59, 56], -63),
        "Ленинский":     (216, 76, -140, [51, 104, 84, 70, 74, 73], -65),
        "Есипово-5":     (345, 43, -302, [35, 52, 45, 41, 43, 42], -88),
        "Итого":         (742, 185, -557, [153, 240, 202, 165, 176, 171], -75),
    }
    print("\n=== СВЕРКА С ЭТАЛОНОМ ТЗ (Скрин 11) ===")
    for proj, (e_plan, e_skud, e_dev, e_w, e_delta) in expected.items():
        row = sub[sub["project_name"] == proj]
        if row.empty:
            print(f"  ✗ {proj:18s} — НЕ НАЙДЕНО в результатах")
            continue
        r = row.iloc[0]
        ok_plan = abs(int(r["plan"]) - e_plan) <= 5
        ok_skud = abs(int(r["skud"]) - e_skud) <= 5
        ok_dev = abs(int(r["deviation"]) - e_dev) <= 5
        weeks = [int(r[f"w{w}"]) for w in (1, 2, 3, 4, 5, 6)]
        ok_w = all(abs(weeks[i] - e_w[i]) <= 5 for i in range(6))
        delta = float(r["delta_pct"]) if pd.notna(r["delta_pct"]) else None
        ok_d = delta is not None and abs(delta - e_delta) <= 5
        flag = "✓" if all([ok_plan, ok_skud, ok_dev, ok_w, ok_d]) else "✗"
        print(
            f"  {flag} {proj:18s}  План:{int(r['plan']):>4d}/{e_plan} "
            f"СКУД:{int(r['skud']):>4d}/{e_skud}  Откл:{int(r['deviation']):>+5d}/{e_dev}  "
            f"Нед:{weeks}/{e_w}  Δ%:{(int(delta) if delta else 0):>+4d}/{e_delta}"
        )

    print("\n=== СВОДКА ПО КОНТРАГЕНТАМ (vid='Рабочие') ===")
    summary = build_summary_table(long_fact, plan, vid="Рабочие")
    if not summary.empty:
        print(summary.to_string(index=False, formatters={
            "plan": lambda x: f"{x:>7.0f}",
            "mean_per_day": lambda x: f"{x:>7.0f}",
            "deviation": lambda x: f"{x:>+8.0f}",
        }))
        print(f"\n  Общий план: {summary['plan'].sum():.0f}")
        print(f"  Объём средних значений: {summary['mean_per_day'].sum():.0f}")
        print(f"  Общее отклонение: {summary['deviation'].sum():+.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
