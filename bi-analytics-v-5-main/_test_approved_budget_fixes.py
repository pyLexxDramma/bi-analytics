# -*- coding: utf-8 -*-
"""Регрессия: отклонения план/факт и распределение A/B/C прогнозного бюджета."""
import sys

sys.path.insert(0, ".")
import pandas as pd
from dashboards._renderers import (
    _bdds_distribute_row_abc,
    _finance_fmt_signed_million_deviation,
    _approved_budget_cumulative_by_project,
)
from utils import budget_table_to_html, DEVIATION_CLASS_RED, DEVIATION_CLASS_GREEN


def test_signed_deviation_cells():
    assert _finance_fmt_signed_million_deviation(55.3e6).startswith("+")
    assert _finance_fmt_signed_million_deviation(-45.6e6).startswith("-")

    df = pd.DataFrame(
        [
            {
                "Проект": "ИТОГО",
                "План, млн руб.": "892.00",
                "Факт, млн руб.": "1222.70",
                "Отклонение, млн руб.": "+330.7 млн. руб.",
            }
        ]
    )
    html = budget_table_to_html(
        df,
        finance_deviation_column="Отклонение, млн руб.",
        deviation_color_fact_vs_plan=True,
    )
    assert "bd-cell-green" in html

    df2 = pd.DataFrame(
        [
            {
                "Проект": "X",
                "План, млн руб.": "156.30",
                "Факт, млн руб.": "110.70",
                "Отклонение, млн руб.": "-45.6 млн. руб.",
            }
        ]
    )
    html2 = budget_table_to_html(
        df2,
        finance_deviation_column="Отклонение, млн руб.",
        deviation_color_fact_vs_plan=True,
    )
    assert "bd-cell-red" in html2


def test_abc_distribution_10_months():
    """01.01.2026–01.10.2026: A=34%, B=33% на 8 месяцев между, C=33%."""
    total = 100.0
    start = pd.Timestamp("2026-01-01")
    end = pd.Timestamp("2026-10-01")
    out = _bdds_distribute_row_abc(total, start, end, 34, 33, 33)
    months = sorted(out.keys())
    assert len(months) == 10
    assert abs(out[months[0]] - 34.0) < 1e-6
    assert abs(out[months[-1]] - 33.0) < 1e-6
    interior = [m for m in months if m > months[0] and m < months[-1]]
    assert len(interior) == 8
    b_share = 33.0 / 8.0
    for m in interior:
        assert abs(out[m] - b_share) < 1e-6
    assert abs(sum(out.values()) - total) < 1e-6


def test_cumulative_by_project_matches_gauge_total():
    rows = []
    for i, (p, f) in enumerate([(10.0, 11.0), (20.0, 22.0), (30.0, 33.0)], start=1):
        rows.append(
            {
                "project name": "P1",
                "budget plan": p * 1e6,
                "budget fact": f * 1e6,
                "plan_month": pd.Period(f"2026-0{i}", freq="M"),
            }
        )
    rows.append(
        {
            "project name": "P2",
            "budget plan": 5e6,
            "budget fact": 6e6,
            "plan_month": pd.Period("2026-01", freq="M"),
        }
    )
    monthly = pd.DataFrame(rows)
    cum_proj = _approved_budget_cumulative_by_project(monthly)
    assert len(cum_proj) == 2
    p1 = cum_proj.loc[cum_proj["project name"] == "P1"].iloc[0]
    assert p1["budget plan"] == 60e6
    assert p1["budget fact"] == 66e6
    assert float(cum_proj["budget plan"].sum()) == 65e6
    assert float(cum_proj["budget fact"].sum()) == 72e6


def test_cumulative_totals_from_msp_rows():
    rows = []
    for i, amt in enumerate([10.0, 20.0, 30.0], start=1):
        rows.append(
            {
                "project name": "P1",
                "budget plan": amt * 1e6,
                "budget fact": (amt + 1) * 1e6,
                "plan_month": pd.Period(f"2026-0{i}", freq="M"),
            }
        )
    df = pd.DataFrame(rows)
    cum_proj = _approved_budget_cumulative_by_project(df)
    assert len(cum_proj) == 1
    assert cum_proj.iloc[0]["budget plan"] == 60e6
    assert cum_proj.iloc[0]["budget fact"] == 63e6


if __name__ == "__main__":
    test_signed_deviation_cells()
    test_abc_distribution_10_months()
    test_cumulative_by_project_matches_gauge_total()
    test_cumulative_totals_from_msp_rows()
    print("ALL OK")
