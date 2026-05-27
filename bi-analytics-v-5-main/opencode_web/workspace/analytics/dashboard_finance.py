"""
Логика план/факт в рублях — зеркало dashboards/finance_from_1c.py (bi-analytics-v-5).

Используется analyze_db_finance_plan_fact.py, чтобы цифры ИИ совпадали с дашбордом:
- «Утверждённый бюджет»: БДДС, сценарий ПЛАН/ФАКТ, план без статей (БДР).
- «БДДС по лотам» (синтетика): фильтр лот/подлот, бюджетный сценарий + статья ФАКТ, по месяцам.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Optional

import numpy as np
import pandas as pd


def load_reference_dannye_dataframe(conn: sqlite3.Connection, version_id: int) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT row_data
        FROM web_data
        WHERE version_id = ? AND file_type = 'reference_dannye'
        """,
        (version_id,),
    ).fetchall()
    records: list[dict[str, Any]] = []
    for (raw,) in rows:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


def _turnover_article_has_lot_and_sublot(raw: object) -> bool:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return False
    s = (
        str(raw)
        .replace("\xa0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .strip()
        .casefold()
        .replace("ё", "е")
    )
    if not s:
        return False
    if re.search(r"\bлот\b\s*[№#]?\s*\d", s):
        return True
    if re.search(r"\blots?\b\s*[#№]?\s*\d", s):
        return True
    if re.match(r"^\d+\.\d+(?:\.\d+)?\b", s):
        return True
    sublot_markers = ("подлот", "под лот", "сублот", "sub lot", "sublot")
    if any(m in s for m in sublot_markers):
        return True
    return False


def _filter_1c_frame_by_article_lot_sublot(frame: pd.DataFrame, *, art_col: Optional[str]) -> pd.DataFrame:
    if frame is None or getattr(frame, "empty", True) or not art_col or art_col not in frame.columns:
        return frame
    mask = frame[art_col].map(_turnover_article_has_lot_and_sublot).fillna(False)
    if not bool(mask.any()):
        return frame.iloc[0:0].copy()
    return frame.loc[mask].copy()


def _coerce_1c_money_series(raw: pd.Series) -> pd.Series:
    if raw is None:
        return pd.Series(dtype="float64")
    s = raw.astype(str).str.strip()
    s = s.replace({"": np.nan, "nan": np.nan, "None": np.nan, "null": np.nan})
    s = s.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    s = s.str.replace(r"[^0-9,\.\-]", "", regex=True)
    mixed = s.str.contains(",", na=False) & s.str.contains(r"\.", na=False)
    s.loc[mixed] = s.loc[mixed].str.replace(".", "", regex=False)
    only_comma = s.str.contains(",", na=False) & ~s.str.contains(r"\.", na=False)
    s.loc[only_comma] = s.loc[only_comma].str.replace(",", ".", regex=False)
    multi_dot = s.str.count(r"\.").fillna(0) > 1
    if bool(multi_dot.any()):
        s.loc[multi_dot] = s.loc[multi_dot].str.replace(r"\.(?=.*\.)", "", regex=True)
    return pd.to_numeric(s, errors="coerce")


def _parse_1c_period_series(raw: pd.Series) -> pd.Series:
    if raw is None:
        return pd.Series(dtype="datetime64[ns]")
    s = raw.astype(str).str.strip()
    dt = pd.to_datetime(s, errors="coerce", dayfirst=False)
    need_fallback = dt.isna()
    if bool(need_fallback.any()):
        dt_fb = pd.to_datetime(s[need_fallback], errors="coerce", dayfirst=True)
        dt.loc[need_fallback] = dt_fb
    return dt


def _pick_col(df: pd.DataFrame, needles: tuple[str, ...]) -> Optional[str]:
    cols_exact: dict[str, str] = {}
    for col in df.columns:
        cs = str(col).strip()
        if cs:
            cols_exact[cs.casefold()] = cs
    for needle in needles:
        key = str(needle).strip().casefold()
        if key in cols_exact:
            return cols_exact[key]
    for col in df.columns:
        cs = str(col).strip()
        if not cs:
            continue
        cl = cs.casefold()
        for needle in needles:
            nk = str(needle).strip().casefold()
            if nk and nk in cl:
                return cs
    return None


def _bddds_route_unassigned_plan_fact(
    frame: pd.DataFrame,
    *,
    plan_mask: pd.Series,
    fact_mask: pd.Series,
) -> None:
    amt = pd.to_numeric(frame["_amt"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    plan_vals = pd.to_numeric(frame["__plan"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    fact_vals = pd.to_numeric(frame["__fact"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    pm = np.asarray(plan_mask, dtype=bool)
    fm = np.asarray(fact_mask, dtype=bool)
    eps = 1e-9
    unassigned = (np.abs(plan_vals) < eps) & (np.abs(fact_vals) < eps) & (np.abs(amt) > eps)
    if not bool(unassigned.any()):
        return
    only_plan = unassigned & pm & ~fm
    only_fact = unassigned & fm & ~pm
    both = unassigned & pm & fm
    plan_vals = np.where(only_plan, amt, plan_vals)
    fact_vals = np.where(only_fact | both, amt, fact_vals)
    frame["__plan"] = plan_vals
    frame["__fact"] = fact_vals


def _bddds_impute_missing_plan_from_fact_ratio(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or getattr(frame, "empty", True):
        return frame
    out = frame.copy()
    plan_all = pd.to_numeric(out["budget plan"], errors="coerce").fillna(0.0)
    fact_all = pd.to_numeric(out["budget fact"], errors="coerce").fillna(0.0)
    pairs = (plan_all > 0.0) & (fact_all > 0.0)
    global_ratio: float | None = None
    if bool(pairs.any()):
        plan_sum = float(plan_all.loc[pairs].sum())
        fact_sum = float(fact_all.loc[pairs].sum())
        if fact_sum > 0.0 and np.isfinite(plan_sum):
            global_ratio = plan_sum / fact_sum
    imputed = False
    for _, chunk in out.groupby("project name"):
        idx = chunk.index
        plan_chunk = pd.to_numeric(out.loc[idx, "budget plan"], errors="coerce").fillna(0.0)
        fact_chunk = pd.to_numeric(out.loc[idx, "budget fact"], errors="coerce").fillna(0.0)
        selected = (plan_chunk > 0.0) & (fact_chunk > 0.0)
        ratio: float | None = None
        if bool(selected.any()):
            plan_sel = float(plan_chunk.loc[selected].sum())
            fact_sel = float(fact_chunk.loc[selected].sum())
            if fact_sel > 0.0 and np.isfinite(plan_sel):
                ratio = plan_sel / fact_sel
        if ratio is None and global_ratio is not None and global_ratio > 0.0:
            ratio = global_ratio
        if ratio is None or ratio <= 0.0:
            continue
        need = (plan_chunk <= 0.0) & (fact_chunk > 0.0)
        if not bool(need.any()):
            continue
        out.loc[idx[need], "budget plan"] = fact_chunk.loc[need].to_numpy(dtype=float) * float(ratio)
        imputed = True
    if imputed:
        out.attrs["bddds_plan_imputed_ratio"] = True
    return out


def approved_budget_from_dannye(reference_1c_dannye: pd.DataFrame) -> pd.DataFrame | None:
    """
    Утверждённый бюджет (как try_approved_budget_from_1c_dannye на дашборде).
    Колонки: project name, budget plan, budget fact (руб.).
    """
    if reference_1c_dannye is None or reference_1c_dannye.empty:
        return None
    frame = reference_1c_dannye.copy()
    col_type = _pick_col(frame, ("ТипСтатьи", "article_type", "Тип статьи"))
    col_scenario = _pick_col(frame, ("Сценарий", "scenario"))
    col_article = _pick_col(frame, ("СтатьяОборотов", "Статья оборотов", "article"))
    col_amount = _pick_col(frame, ("Сумма", "amount"))
    col_project = _pick_col(
        frame,
        ("Проект", "project", "проект", "проектдляотчетов", "проект для отчетов", "ИмяПроекта"),
    )
    if not (col_type and col_scenario and col_article and col_amount):
        return None

    type_norm = frame[col_type].astype(str).str.strip().str.casefold()
    bdds = frame[type_norm.eq("бддс")].copy()
    if bdds.empty:
        return None

    scenario_norm = bdds[col_scenario].astype(str).str.strip().str.casefold()
    article_norm = (
        bdds[col_article]
        .astype(str)
        .str.replace("\xa0", " ", regex=False)
        .str.replace("\u200b", "", regex=False)
        .str.strip()
        .str.casefold()
    )
    has_bdr = article_norm.str.contains(r"\(бдр\)", regex=True, na=False) | article_norm.eq("бдр")
    amount_rub = _coerce_1c_money_series(bdds[col_amount]).fillna(0.0) * 1000.0

    plan_mask = scenario_norm.eq("план") & ~has_bdr
    fact_mask = scenario_norm.eq("факт")

    bdds["__plan"] = np.where(plan_mask.to_numpy(), amount_rub.to_numpy(), 0.0)
    bdds["__fact"] = np.where(fact_mask.to_numpy(), amount_rub.to_numpy(), 0.0)

    if col_project and col_project in bdds.columns:
        grouped = (
            bdds.groupby(col_project, dropna=False, sort=True)[["__plan", "__fact"]]
            .sum()
            .reset_index()
            .rename(columns={col_project: "project name"})
        )
    else:
        grouped = pd.DataFrame(
            [
                {
                    "project name": "—",
                    "__plan": float(bdds["__plan"].sum()),
                    "__fact": float(bdds["__fact"].sum()),
                }
            ]
        )

    return pd.DataFrame(
        {
            "project name": grouped["project name"],
            "budget plan": grouped["__plan"].astype(float),
            "budget fact": grouped["__fact"].astype(float),
        }
    )


def approved_budget_grouped(
    reference_1c_dannye: pd.DataFrame,
    group_column_needles: tuple[str, ...],
    output_name: str,
) -> pd.DataFrame | None:
    """Те же фильтры, что у утверждённого бюджета, группировка по другому полю (например Контрагент)."""
    if reference_1c_dannye is None or reference_1c_dannye.empty:
        return None
    frame = reference_1c_dannye.copy()
    col_type = _pick_col(frame, ("ТипСтатьи", "article_type", "Тип статьи"))
    col_scenario = _pick_col(frame, ("Сценарий", "scenario"))
    col_article = _pick_col(frame, ("СтатьяОборотов", "Статья оборотов", "article"))
    col_amount = _pick_col(frame, ("Сумма", "amount"))
    col_group = _pick_col(frame, group_column_needles)
    if not (col_type and col_scenario and col_article and col_amount and col_group):
        return None

    type_norm = frame[col_type].astype(str).str.strip().str.casefold()
    bdds = frame[type_norm.eq("бддс")].copy()
    if bdds.empty:
        return None

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
    bdds["__plan"] = np.where(plan_mask.to_numpy(), amount_rub.to_numpy(), 0.0)
    bdds["__fact"] = np.where(fact_mask.to_numpy(), amount_rub.to_numpy(), 0.0)

    grouped = (
        bdds.groupby(col_group, dropna=False, sort=True)[["__plan", "__fact"]]
        .sum()
        .reset_index()
        .rename(columns={col_group: output_name})
    )
    return pd.DataFrame(
        {
            output_name: grouped[output_name],
            "budget plan": grouped["__plan"].astype(float),
            "budget fact": grouped["__fact"].astype(float),
        }
    )


def synthetic_budget_monthly_from_dannye(reference_1c_dannye: pd.DataFrame) -> pd.DataFrame | None:
    """
    БДДС синтетика по месяцам (try_synthetic_budget_from_1c_dannye): лот/подлот, период обязателен.
    """
    if reference_1c_dannye is None or reference_1c_dannye.empty:
        return None
    frame = reference_1c_dannye.copy()
    col_scenario = _pick_col(frame, ("Сценарий", "scenario"))
    col_amount = _pick_col(frame, ("Сумма", "amount", "суммаоборот", "сумма оборот"))
    if not col_scenario or not col_amount:
        return None
    col_article = _pick_col(frame, ("СтатьяОборотов", "Статья оборотов", "article"))
    col_type = _pick_col(frame, ("ТипСтатьи", "article_type", "Тип статьи"))
    col_period = _pick_col(frame, ("Период", "period", "месяц", "дата", "date", "периодитогов"))
    col_project = _pick_col(frame, ("Проект", "project", "проект", "проектдляотчетов", "проект для отчетов"))
    if not col_period:
        return None

    def _no_bdr(row: pd.Series) -> bool:
        article_value = str(row.get(col_article, "") if col_article else "").casefold()
        if "(бдр)" in article_value or article_value.strip() == "бдр":
            return False
        if col_type and col_type in row.index:
            type_value = str(row.get(col_type, "")).casefold()
            if "бдр" in type_value and "бддс" not in type_value:
                return False
        return True

    frame = frame[frame.apply(_no_bdr, axis=1)].copy()
    if frame.empty:
        return None
    if col_article:
        frame = _filter_1c_frame_by_article_lot_sublot(frame, art_col=col_article)
    if frame.empty:
        return None

    frame["_amt"] = _coerce_1c_money_series(frame[col_amount]).fillna(0.0) * 1000.0
    scenario_series = frame[col_scenario].astype(str)
    plan_mask = (
        scenario_series.str.contains("бюджет", case=False, na=False)
        | scenario_series.str.contains("budget", case=False, na=False)
        | (
            scenario_series.str.contains("план", case=False, na=False)
            & ~scenario_series.str.contains("факт", case=False, na=False)
        )
    )
    fact_mask = scenario_series.str.contains("факт", case=False, na=False) | scenario_series.str.contains(
        "fact", case=False, na=False
    )
    norm_scenario = scenario_series.str.strip().str.casefold()
    plan_mask = plan_mask | norm_scenario.eq("план")
    fact_mask = fact_mask | norm_scenario.eq("факт")

    use_article_split = bool(col_article and col_article in frame.columns)
    plan_hit = pd.Series(False, index=frame.index)
    fact_hit = pd.Series(False, index=frame.index)
    if use_article_split:
        budget_scenario = scenario_series.str.contains("бюджет", case=False, na=False) | scenario_series.str.contains(
            "budget", case=False, na=False
        )
        article_norm = (
            frame[col_article]
            .astype(str)
            .str.replace("\xa0", " ", regex=False)
            .str.strip()
            .str.casefold()
        )
        is_fact_article = article_norm.eq("факт")
        plan_hit = budget_scenario & (~is_fact_article)
        fact_hit = budget_scenario & is_fact_article
        if not (bool(plan_hit.any()) or bool(fact_hit.any())):
            use_article_split = False

    amount_np = frame["_amt"].to_numpy()
    if use_article_split:
        frame["__plan"] = np.where(plan_hit.to_numpy(), amount_np, 0.0)
        frame["__fact"] = np.where(fact_hit.to_numpy(), amount_np, 0.0)
        if not bool(fact_hit.any()) and bool(fact_mask.any()):
            frame["__fact"] = np.where(fact_mask.to_numpy(), amount_np, frame["__fact"].to_numpy())
        _bddds_route_unassigned_plan_fact(frame, plan_mask=plan_mask, fact_mask=fact_mask)
    else:
        if not plan_mask.any() and not fact_mask.any():
            return None
        frame["__plan"] = np.where(plan_mask.to_numpy(), amount_np, 0.0)
        frame["__fact"] = np.where(fact_mask.to_numpy(), amount_np, 0.0)

    frame["_d"] = _parse_1c_period_series(frame[col_period])
    frame = frame[frame["_d"].notna()].copy()
    if frame.empty:
        return None
    frame["_m"] = frame["_d"].dt.to_period("M")

    if col_project and col_project in frame.columns:
        grouped = frame.groupby([col_project, "_m"], dropna=False, sort=True)[["__plan", "__fact"]].sum().reset_index()
        grouped = grouped.rename(columns={col_project: "project name"})
    else:
        grouped = frame.groupby("_m", dropna=False, sort=True)[["__plan", "__fact"]].sum().reset_index()
        grouped["project name"] = "—"

    output_rows: list[dict[str, Any]] = []
    for _, row in grouped.iterrows():
        month = row["_m"]
        if pd.isna(month):
            continue
        try:
            plan_end = month.to_timestamp(how="end")
        except Exception:
            continue
        output_rows.append(
            {
                "project name": row["project name"],
                "plan end": plan_end,
                "budget plan": float(row["__plan"]),
                "budget fact": float(row["__fact"]),
            }
        )
    if not output_rows:
        return None
    result = pd.DataFrame(output_rows)
    result = _bddds_impute_missing_plan_from_fact_ratio(result)
    return result


def to_plan_fact_metrics(frame: pd.DataFrame, entity_col: str) -> pd.DataFrame:
    """Приводит budget plan/fact к plan_total, fact_total, deviation_rub (как на дашборде: план − факт)."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    if entity_col == "project" and "project name" in out.columns:
        out = out.rename(columns={"project name": "project"})
    out = out.rename(columns={"budget plan": "plan_total", "budget fact": "fact_total"})
    out["deviation_rub"] = out["plan_total"] - out["fact_total"]
    out["deviation_pct"] = out.apply(
        lambda row: round(100.0 * row["deviation_rub"] / row["plan_total"], 2) if row["plan_total"] else None,
        axis=1,
    )
    out["underutilization_rub"] = out["deviation_rub"].clip(lower=0)
    out["overspend_rub"] = (-out["deviation_rub"]).clip(lower=0)
    return out.sort_values("deviation_rub", ascending=False)
