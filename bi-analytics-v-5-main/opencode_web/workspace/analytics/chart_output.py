"""Стабильные имена PNG для ответов ИИ (пути в AI_DATA_RULES.md)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def save_plan_fact_by_project_chart(frame: pd.DataFrame, target_png: Path) -> bool:
    """
    Столбчатый график план/факт по проектам (утверждённый бюджет, руб.).
    frame: колонки project (или project name), plan_total, fact_total.
    """
    if frame is None or frame.empty:
        return False
    work = frame.copy()
    project_col = "project" if "project" in work.columns else "project name"
    if project_col not in work.columns:
        return False
    work = work.sort_values("fact_total", ascending=False).head(20)
    labels = work[project_col].astype(str).tolist()
    plan_vals = pd.to_numeric(work["plan_total"], errors="coerce").fillna(0.0) / 1_000_000
    fact_vals = pd.to_numeric(work["fact_total"], errors="coerce").fillna(0.0) / 1_000_000

    fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.45)))
    y_pos = range(len(labels))
    height = 0.35
    ax.barh([y - height / 2 for y in y_pos], plan_vals, height=height, label="План", color="#4a90d9")
    ax.barh([y + height / 2 for y in y_pos], fact_vals, height=height, label="Факт", color="#e85d4c")
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels)
    ax.set_xlabel("млн руб.")
    ax.set_title("План и факт по проектам (утверждённый бюджет БДДС)")
    ax.legend(loc="lower right")
    fig.tight_layout()
    target_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target_png, dpi=140)
    plt.close(fig)
    return target_png.is_file() and target_png.stat().st_size > 0


def save_bddds_monthly_chart(monthly_frame: pd.DataFrame, target_png: Path) -> bool:
    """
    Динамика БДДС: суммарный план/факт по месяцам (млн руб.), линии + столбцы.
    monthly_frame: project, period_month, plan_total, fact_total.
    """
    if monthly_frame is None or monthly_frame.empty:
        return False
    if "period_month" not in monthly_frame.columns:
        return False
    work = monthly_frame.copy()
    work["period_month"] = work["period_month"].astype(str)
    agg = (
        work.groupby("period_month", dropna=False)[["plan_total", "fact_total"]]
        .sum()
        .reset_index()
        .sort_values("period_month")
    )
    if agg.empty:
        return False

    labels = agg["period_month"].tolist()
    plan_mln = pd.to_numeric(agg["plan_total"], errors="coerce").fillna(0.0) / 1_000_000
    fact_mln = pd.to_numeric(agg["fact_total"], errors="coerce").fillna(0.0) / 1_000_000

    fig, ax = plt.subplots(figsize=(11, 5))
    x = range(len(labels))
    width = 0.38
    ax.bar([i - width / 2 for i in x], plan_mln, width=width, label="План", color="#4a90d9")
    ax.bar([i + width / 2 for i in x], fact_mln, width=width, label="Факт", color="#e85d4c")
    ax.plot(list(x), plan_mln, color="#2f5f8f", marker="o", linewidth=1.5, label="_nolegend_")
    ax.plot(list(x), fact_mln, color="#b33a2c", marker="s", linewidth=1.5, label="_nolegend_")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.set_ylabel("млн руб.")
    ax.set_title("БДДС: план и факт по месяцам (сумма по проектам)")
    ax.legend(loc="upper left")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    target_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target_png, dpi=140)
    plt.close(fig)
    return target_png.is_file() and target_png.stat().st_size > 0
