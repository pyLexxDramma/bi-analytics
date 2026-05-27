"""
План/факт в рублях — логика как на дашборде (finance_from_1c.py).

Основной срез для вопросов «план/факт по проекту/подрядчику»:
  approved budget (БДДС, сценарий ПЛАН/ФАКТ) → plan_fact_by_project.csv, plan_fact_by_contractor.csv

Динамика по месяцам (БДДС, лоты/подлоты, как синтетика дашборда):
  → plan_fact_by_project_month.csv

Авансы — debit_credit (тыс. руб. × 1000).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from dashboard_finance import (
    approved_budget_from_dannye,
    approved_budget_grouped,
    load_reference_dannye_dataframe,
    synthetic_budget_monthly_from_dannye,
    to_plan_fact_metrics,
    _coerce_1c_money_series,
    _pick_col,
)
from chart_output import save_bddds_monthly_chart, save_plan_fact_by_project_chart
from db_common import (
    connect_db,
    ensure_output_dir,
    get_effective_version_id,
    parse_db_args,
    resolve_db_path,
    save_table,
)
from workspace_paths import analytics_output_dir, resolve_output_dir, to_workspace_display_path


def _parse_money(raw: object) -> float:
    """ДК: те же правила, что _coerce_1c_money_series × 1000."""
    series = _coerce_1c_money_series(pd.Series([raw]))
    value = series.iloc[0] if len(series) else float("nan")
    if pd.isna(value):
        return 0.0
    return float(value) * 1000.0


def _load_advance_rows(conn, version_id: int) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT row_data
        FROM web_data
        WHERE version_id = ? AND file_type = 'debit_credit'
        """,
        (version_id,),
    ).fetchall()
    records: list[dict] = []
    for (raw,) in rows:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        contractor = str(
            payload.get("Название контрагента") or payload.get("Контрагент") or "unknown"
        ).strip()
        project_hint = str(payload.get("Номер договора") or "").strip()
        opening_adv = _parse_money(
            payload.get("ОстатокНаНачалоПериодаПоАвансам")
            or payload.get("ОстатокНаНачало")
            or 0
        )
        closing_adv = _parse_money(
            payload.get("ОстатокНаКонецПериодаПоАвансам")
            or payload.get("ОстатокНаКонец")
            or payload.get("Остаток на конец периода")
            or 0
        )
        contract_sum = _parse_money(payload.get("Сумма в договоре") or 0)
        paid = _parse_money(payload.get("Выплачено") or payload.get("Аванс") or 0)
        records.append(
            {
                "contractor": contractor,
                "contract_ref": project_hint,
                "opening_advance_balance": opening_adv,
                "unclosed_advance_balance": closing_adv,
                "contract_amount": contract_sum,
                "paid_amount": paid,
                "advance_headroom": max(contract_sum - paid - closing_adv, 0.0),
            }
        )
    return pd.DataFrame(records)


def _article_plan_fact_from_dannye(dannye: pd.DataFrame) -> pd.DataFrame:
    """Срез по статьям оборотов (утверждённый бюджет, для «почему ниже плана»)."""
    if dannye.empty:
        return pd.DataFrame()
    frame = dannye.copy()
    col_type = _pick_col(frame, ("ТипСтатьи", "article_type", "Тип статьи"))
    col_scenario = _pick_col(frame, ("Сценарий", "scenario"))
    col_article = _pick_col(frame, ("СтатьяОборотов", "Статья оборотов", "article"))
    col_amount = _pick_col(frame, ("Сумма", "amount"))
    if not (col_type and col_scenario and col_article and col_amount):
        return pd.DataFrame()

    type_norm = frame[col_type].astype(str).str.strip().str.casefold()
    bdds = frame[type_norm.eq("бддс")].copy()
    if bdds.empty:
        return pd.DataFrame()

    scenario_norm = bdds[col_scenario].astype(str).str.strip().str.casefold()
    article_norm = (
        bdds[col_article]
        .astype(str)
        .str.replace("\xa0", " ", regex=False)
        .str.strip()
        .str.casefold()
    )
    has_bdr = article_norm.str.contains(r"\(бдр\)", regex=True, na=False) | article_norm.eq("бдр")
    amount_rub = _coerce_1c_money_series(bdds[col_amount]).fillna(0.0) * 1000.0
    plan_mask = scenario_norm.eq("план") & ~has_bdr
    fact_mask = scenario_norm.eq("факт")
    bdds["plan_amount"] = amount_rub.where(plan_mask, 0.0)
    bdds["fact_amount"] = amount_rub.where(fact_mask, 0.0)
    bdds["article"] = bdds[col_article].astype(str).str.strip()

    grouped = (
        bdds.groupby("article", dropna=False)[["plan_amount", "fact_amount"]]
        .sum()
        .rename(columns={"plan_amount": "plan_total", "fact_amount": "fact_total"})
        .reset_index()
    )
    grouped["deviation_rub"] = grouped["plan_total"] - grouped["fact_total"]
    return grouped[grouped["plan_total"] + grouped["fact_total"] > 0].sort_values(
        "deviation_rub", ascending=False
    )


def main() -> None:
    default_out = analytics_output_dir() / "db_finance_plan_fact"
    args = parse_db_args(default_output=str(to_workspace_display_path(default_out)))
    db_path = resolve_db_path(args.db)
    output_dir = ensure_output_dir(resolve_output_dir(args.output))

    with connect_db(db_path) as conn:
        version_id = get_effective_version_id(conn, args.version_id)
        dannye = load_reference_dannye_dataframe(conn, version_id)
        advances = _load_advance_rows(conn, version_id)

    if dannye.empty:
        save_table(
            pd.DataFrame([{"version_id": version_id, "error": "no reference_dannye rows"}]),
            output_dir / "diagnostics.csv",
        )
        return

    approved_project = approved_budget_from_dannye(dannye)
    approved_contractor = approved_budget_grouped(
        dannye,
        ("Контрагент", "contractor", "контрагент"),
        "contractor",
    )
    synthetic_monthly = synthetic_budget_monthly_from_dannye(dannye)
    by_article = _article_plan_fact_from_dannye(dannye)

    chart_png_path = output_dir / "plan_fact_by_project.png"
    chart_monthly_path = output_dir / "plan_fact_bddds_monthly.png"
    if approved_project is not None and not approved_project.empty:
        project_metrics = to_plan_fact_metrics(approved_project, "project")
        save_table(project_metrics, output_dir / "plan_fact_by_project.csv")
        chart_frame = project_metrics.copy()
        if "plan_total" in chart_frame.columns:
            chart_frame = chart_frame[pd.to_numeric(chart_frame["plan_total"], errors="coerce").fillna(0.0) > 0]
        if not chart_frame.empty:
            save_plan_fact_by_project_chart(chart_frame, chart_png_path)
    else:
        save_table(
            pd.DataFrame([{"error": "approved_budget_empty"}]),
            output_dir / "plan_fact_by_project.csv",
        )

    if approved_contractor is not None and not approved_contractor.empty:
        save_table(
            to_plan_fact_metrics(approved_contractor, "contractor"),
            output_dir / "plan_fact_by_contractor.csv",
        )

    if synthetic_monthly is not None and not synthetic_monthly.empty:
        monthly = synthetic_monthly.copy()
        monthly["period_month"] = pd.to_datetime(monthly["plan end"], errors="coerce").dt.to_period("M").astype(str)
        monthly_out = monthly.rename(
            columns={
                "project name": "project",
                "budget plan": "plan_total",
                "budget fact": "fact_total",
            }
        )[["project", "period_month", "plan_total", "fact_total"]]
        monthly_out["deviation_rub"] = monthly_out["plan_total"] - monthly_out["fact_total"]
        save_table(monthly_out, output_dir / "plan_fact_by_project_month.csv")
        save_bddds_monthly_chart(monthly_out, chart_monthly_path)

    if not by_article.empty:
        save_table(by_article.head(500), output_dir / "plan_fact_by_article.csv")

    if not advances.empty:
        adv_contractor = (
            advances.groupby("contractor", dropna=False)[
                ["opening_advance_balance", "unclosed_advance_balance", "advance_headroom"]
            ]
            .sum()
            .reset_index()
            .sort_values("unclosed_advance_balance", ascending=False)
        )
        save_table(adv_contractor, output_dir / "advances_by_contractor.csv")
        save_table(advances, output_dir / "advances_detail.csv")

    plan_total = float(approved_project["budget plan"].sum()) if approved_project is not None and not approved_project.empty else 0.0
    fact_total = float(approved_project["budget fact"].sum()) if approved_project is not None and not approved_project.empty else 0.0
    diagnostics = pd.DataFrame(
        [
            {
                "version_id": int(version_id),
                "db_path": str(db_path),
                "dannye_rows": int(len(dannye)),
                "approved_projects": int(approved_project.shape[0]) if approved_project is not None else 0,
                "approved_plan_total_rub": round(plan_total, 2),
                "approved_fact_total_rub": round(fact_total, 2),
                "synthetic_monthly_rows": int(synthetic_monthly.shape[0]) if synthetic_monthly is not None else 0,
                "article_rows": int(by_article.shape[0]),
                "advance_rows": int(len(advances)),
                "dashboard_mode_project_contractor": "approved_bddds_plan_fact",
                "dashboard_mode_monthly": "synthetic_bddds_lot_sublot",
                "note": "Используйте plan_fact_by_project/contractor для KPI как «Утверждённый бюджет»; monthly — БДДС по лотам.",
                "chart_png": to_workspace_display_path(chart_png_path)
                if chart_png_path.is_file()
                else "",
                "chart_png_monthly": to_workspace_display_path(chart_monthly_path)
                if chart_monthly_path.is_file()
                else "",
            }
        ]
    )
    save_table(diagnostics, output_dir / "diagnostics.csv")


if __name__ == "__main__":
    main()
