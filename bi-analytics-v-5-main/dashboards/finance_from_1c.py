# -*- coding: utf-8 -*-
"""
Подстановка план/факт бюджета из оборотов 1С (session reference_1c_dannye),
когда в MSP нет колонок budget plan / budget fact.
"""
from __future__ import annotations

from typing import Any, Optional

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

    Строки без колонки периода или с неразобранной датой исключаются (не подставляются на max-дату).
    Статьи оборотов БДР не включаются в БДДС (как в прогнозном бюджете).

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
    art = _pick_col(t, ("СтатьяОборотов", "Статья оборотов", "article"))
    typ = _pick_col(t, ("ТипСтатьи", "article_type", "Тип статьи"))
    per = _pick_col(
        t,
        ("Период", "period", "месяц", "дата", "date", "периодитогов"),
    )
    proj = _pick_col(
        t,
        ("Проект", "project", "проект", "проектдляотчетов", "проект для отчетов"),
    )
    if not per:
        return None

    def _no_bdr(row) -> bool:
        a = str(row.get(art, "") if art else "").casefold()
        if "(бдр)" in a or a.strip() == "бдр":
            return False
        if typ and typ in row.index:
            tl = str(row.get(typ, "")).casefold()
            if "бдр" in tl and "бддс" not in tl:
                return False
        return True

    t = t[t.apply(_no_bdr, axis=1)].copy()
    if t.empty:
        return None

    t["_amt"] = pd.to_numeric(t[amt], errors="coerce").fillna(0.0)
    sser = t[scen].astype(str)
    # Выгрузки 1С: «БЮДЖЕТ …» или отдельное «ПЛАН» (без подстроки «ФАКТ» в том же слове сценария).
    plan_mask = (
        sser.str.contains("бюджет", case=False, na=False)
        | sser.str.contains("budget", case=False, na=False)
        | (
            sser.str.contains("план", case=False, na=False)
            & ~sser.str.contains("факт", case=False, na=False)
        )
    )
    fact_mask = sser.str.contains("факт", case=False, na=False) | sser.str.contains(
        "fact", case=False, na=False
    )
    if not plan_mask.any() and not fact_mask.any():
        return None
    t["__plan"] = np.where(plan_mask.to_numpy(), t["_amt"].to_numpy(), 0.0)
    t["__fact"] = np.where(fact_mask.to_numpy(), t["_amt"].to_numpy(), 0.0)
    t["_d"] = pd.to_datetime(t[per], errors="coerce", dayfirst=True)
    t = t[t["_d"].notna()].copy()
    if t.empty:
        return None
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
    restrict_projects_from_df: bool = True,
    period_start: Any | None = None,
    period_end: Any | None = None,
) -> tuple[pd.DataFrame, bool]:
    """
    Возвращает (df_for_budget, used_fallback_1c).
    Если в исходном df нет непустых budget plan/fact, пытается собрать их из 1С.

    После сборки синтетики из 1С можно сузить строки до проектов из текущего MSP-фрейма
    и до интервала дат календаря (поле «plan end» в синтетике = конец месяца из «Период» JSON).
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
    if syn is None or syn.empty:
        return work, False

    if restrict_projects_from_df and "project name" in work.columns:
        nz = work["project name"].dropna()
        if nz.empty:
            return work, False
        from dashboards._renderers import _project_filter_norm_key

        keys = {_project_filter_norm_key(x) for x in nz.unique()}
        keys.discard("")
        if keys:
            syn = syn[syn["project name"].map(_project_filter_norm_key).isin(keys)].copy()

    ps = period_start
    pe = period_end
    if ps is not None and pe is not None and not syn.empty:
        ts = pd.to_datetime(ps, errors="coerce")
        te = pd.to_datetime(pe, errors="coerce")
        if pd.notna(ts) and pd.notna(te):
            pe_col = pd.to_datetime(syn["plan end"], errors="coerce")
            syn = syn[
                pe_col.notna()
                & (pe_col >= ts.normalize())
                & (
                    pe_col
                    <= (te.normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
                )
            ].copy()

    if syn.empty:
        return work, False

    if show_caption:
        st.caption(
            "Использован fallback: бюджетные суммы взяты из 1С (`*_dannye.json`), "
            "потому что в MSP нет непустых budget plan / budget fact."
        )
    return syn, True
