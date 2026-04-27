# -*- coding: utf-8 -*-
"""
Подстановка план/факт бюджета из оборотов 1С (session reference_1c_dannye),
когда в MSP нет колонок budget plan / budget fact.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _pick_col(df: pd.DataFrame, needles: tuple[str, ...]) -> Optional[str]:
    cols = {str(c).strip().casefold(): c for c in df.columns}
    for n in needles:
        k = str(n).strip().casefold()
        if k in cols:
            return cols[k]
    for c in df.columns:
        cl = str(c).casefold()
        for n in needles:
            if str(n).casefold() in cl:
                return str(c)
    return None


def try_synthetic_budget_from_1c_dannye() -> Optional[pd.DataFrame]:
    """
    Собирает DataFrame в формате дашборда БДДС: project name, plan end, budget plan, budget fact,
    plan_month / plan_quarter / plan_year, section.

    Возвращает None, если в reference_1c_dannye нет сценария+суммы или не удаётся агрегировать.
    """
    import streamlit as st

    ref = st.session_state.get("reference_1c_dannye")
    if ref is None or not isinstance(ref, pd.DataFrame) or ref.empty:
        return None
    t = ref.copy()
    scen = _pick_col(t, ("Сценарий", "scenario"))
    amt = _pick_col(
        t,
        ("Сумма", "amount", "суммаоборот", "сумма оборот", "суммавруб", "суммавруб"),
    )
    if not scen or not amt:
        return None
    per = _pick_col(
        t,
        ("Период", "period", "месяц", "дата", "date", "периодитогов"),
    )
    proj = _pick_col(
        t,
        ("Проект", "project", "проект", "проектдляотчетов", "проект для отчетов"),
    )
    t["_amt"] = pd.to_numeric(t[amt], errors="coerce").fillna(0.0)
    sser = t[scen].astype(str)
    plan_mask = sser.str.contains("бюджет", case=False, na=False) | sser.str.contains(
        "budget", case=False, na=False
    )
    fact_mask = sser.str.contains("факт", case=False, na=False) | sser.str.contains(
        "fact", case=False, na=False
    )
    if not plan_mask.any() and not fact_mask.any():
        return None
    t["__plan"] = np.where(plan_mask.to_numpy(), t["_amt"].to_numpy(), 0.0)
    t["__fact"] = np.where(fact_mask.to_numpy(), t["_amt"].to_numpy(), 0.0)
    if per:
        t["_d"] = pd.to_datetime(t[per], errors="coerce", dayfirst=True)
    else:
        t["_d"] = pd.NaT
    if t["_d"].notna().any():
        fill = t["_d"].max()
        t["_d"] = t["_d"].fillna(fill)
    else:
        t["_d"] = pd.Timestamp.now()
    t["_m"] = t["_d"].dt.to_period("M")
    if proj and proj in t.columns:
        grp = t.groupby([proj, "_m"], dropna=False, sort=True)[["__plan", "__fact"]].sum().reset_index()
        grp = grp.rename(columns={proj: "project name"})
    else:
        grp = t.groupby("_m", dropna=False, sort=True)[["__plan", "__fact"]].sum().reset_index()
        grp["project name"] = "—"
    out_rows = []
    for _, r in grp.iterrows():
        m = r["_m"]
        if pd.isna(m):
            continue
        try:
            pe = m.to_timestamp(how="end")
        except Exception:
            continue
        out_rows.append(
            {
                "project name": r["project name"],
                "plan end": pe,
                "section": "—",
                "budget plan": float(r["__plan"]),
                "budget fact": float(r["__fact"]),
            }
        )
    if not out_rows:
        return None
    odf = pd.DataFrame(out_rows)
    _pe = pd.to_datetime(odf["plan end"], errors="coerce")
    odf["plan_month"] = _pe.dt.to_period("M")
    odf["plan_quarter"] = _pe.dt.to_period("Q")
    odf["plan_year"] = _pe.dt.to_period("Y")
    odf.attrs["data_source_1c_synthetic"] = True
    return odf


def ensure_budget_frame_with_fallback(
    df: pd.DataFrame,
    *,
    show_caption: bool = True,
) -> tuple[pd.DataFrame, bool]:
    """
    Возвращает (df_for_budget, used_fallback_1c).
    Если в исходном df нет непустых budget plan/fact, пытается собрать их из 1С.
    """
    import streamlit as st

    work = df.copy()
    has_cols = "budget plan" in work.columns and "budget fact" in work.columns
    if has_cols:
        bp = pd.to_numeric(work["budget plan"], errors="coerce").fillna(0.0)
        bf = pd.to_numeric(work["budget fact"], errors="coerce").fillna(0.0)
        if (float(bp.abs().sum()) + float(bf.abs().sum())) > 0.0:
            return work, False
    syn = try_synthetic_budget_from_1c_dannye()
    if syn is not None and not syn.empty:
        if show_caption:
            st.caption(
                "Использован fallback: бюджетные суммы взяты из 1С (`*_dannye.json`), "
                "потому что в MSP нет непустых budget plan / budget fact."
            )
        return syn, True
    return work, False
