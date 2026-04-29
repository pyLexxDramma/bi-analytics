# -*- coding: utf-8 -*-
"""
Подстановка план/факт бюджета из оборотов 1С (session reference_1c_dannye),
когда в MSP нет колонок budget plan / budget fact.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd


def _coerce_1c_money_series(raw: pd.Series) -> pd.Series:
    """Нормализация денежных сумм из выгрузки 1С (пробелы тысяч, скобки, ₽)."""
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


def try_synthetic_budget_from_1c_dannye(
    *,
    reference_1c_dannye: Optional[pd.DataFrame] = None,
) -> Optional[pd.DataFrame]:
    """
    Собирает DataFrame в формате дашборда БДДС: project name, plan end, budget plan, budget fact,
    plan_month / plan_quarter / plan_year, section.

    Строки без колонки периода или с неразобранной датой исключаются (не подставляются на max-дату).
    Статьи оборотов БДР не включаются в БДДС (как в прогнозном бюджете).

    Возвращает None, если в reference_1c_dannye нет сценария+суммы или не удаётся агрегировать.

    ``reference_1c_dannye``: если передан (например из CLI-скрипта), session_state не используется.
    """
    if reference_1c_dannye is not None:
        ref = reference_1c_dannye
    else:
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

    t["_amt"] = _coerce_1c_money_series(t[amt]).fillna(0.0)
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


def try_synthetic_bdr_from_1c_dannye(
    *,
    reference_1c_dannye: Optional[pd.DataFrame] = None,
) -> Optional[pd.DataFrame]:
    """
    Собирает БДР (доходы / расходы / сальдо) из `reference_1c_dannye`.

    Строки со статьёй/типом «БДР» — приоритет; если таких нет, используется разрез
    «Поступление» / «Расходование» по полю «РасходДоход» по всем оборотам (с пояснением в attrs).

    Предпочтительно сценарий «ФАКТ»; если фактовых строк нет — «ПЛАН»/«БЮДЖЕТ».

    ``reference_1c_dannye``: если передан, session_state не используется.
    """
    if reference_1c_dannye is not None:
        ref = reference_1c_dannye
    else:
        import streamlit as st

        ref = st.session_state.get("reference_1c_dannye")
    if ref is None or not isinstance(ref, pd.DataFrame) or ref.empty:
        return None
    t = ref.copy()
    scen = _pick_col(t, ("Сценарий", "scenario"))
    amt = _pick_col(
        t,
        ("Сумма", "amount", "суммаоборот", "сумма оборот", "суммавруб"),
    )
    per = _pick_col(t, ("Период", "period", "месяц", "дата", "date", "периодитогов"))
    proj = _pick_col(
        t,
        ("Проект", "project", "проект", "проектдляотчетов", "проект для отчетов"),
    )
    rd = _pick_col(
        t,
        ("РасходДоход", "Расходдоход", "ПриходРасход", "приходрасход"),
    )
    art = _pick_col(t, ("СтатьяОборотов", "Статья оборотов", "article"))
    typ = _pick_col(t, ("ТипСтатьи", "article_type", "Тип статьи"))
    if not scen or not amt or not per or not rd:
        return None

    def _bdr_article_or_type(fr: pd.DataFrame) -> pd.Series:
        m = pd.Series(False, index=fr.index)
        if art and art in fr.columns:
            a = fr[art].astype(str).fillna("")
            m = m | a.str.casefold().str.contains(r"\(бдр\)|^бдр$|^бдр\s", regex=True)
        if typ and typ in fr.columns:
            tl = fr[typ].astype(str).fillna("").str.casefold()
            m = m | (tl.str.contains("бдр", regex=False) & (~tl.str.contains("бддс", regex=False)))
        return m

    strict_m = _bdr_article_or_type(t)
    use_approx_split = True
    if bool(strict_m.any()):
        t = t.loc[strict_m].copy()
        use_approx_split = False
    if t.empty:
        return None

    scm = t[scen].astype(str).str.casefold()
    if scm.str.contains("факт", na=False).any():
        t = t.loc[scm.str.contains("факт", na=False)].copy()
    elif (
        scm.str.contains("план", na=False).any()
        or scm.str.contains("бюджет", na=False).any()
    ):
        m2 = scm.str.contains("план", na=False) | scm.str.contains(
            "бюджет", na=False
        )
        m2 = m2 & ~scm.str.contains("факт", na=False)
        t = t.loc[m2].copy()
    if t.empty:
        return None

    t["_amt"] = _coerce_1c_money_series(t[amt]).fillna(0.0)

    def _bucket(v: Any) -> str:
        s = str(v or "").strip().casefold()
        if not s:
            return ""
        if "поступ" in s:
            return "inc"
        if "расход" in s:
            return "exp"
        return ""

    b_inc = pd.Series(np.zeros(len(t), dtype=float), index=t.index)
    b_exp = pd.Series(np.zeros(len(t), dtype=float), index=t.index)
    for idx, row in t.iterrows():
        am = float(row["_amt"]) if pd.notna(row["_amt"]) else 0.0
        bk = _bucket(row[rd])
        if bk == "inc":
            b_inc.loc[idx] = abs(am)
        elif bk == "exp":
            b_exp.loc[idx] = abs(am)
        else:
            if am >= 0:
                b_inc.loc[idx] += am  # знак неклассифицированного трактуем как поступление
            else:
                b_exp.loc[idx] += abs(am)

    t["_inc"] = b_inc.values
    t["_exp"] = b_exp.values
    t["_d"] = pd.to_datetime(t[per], errors="coerce", dayfirst=True)
    t = t[t["_d"].notna()].copy()
    if t.empty:
        return None
    t["_m"] = t["_d"].dt.to_period("M")

    if proj and proj in t.columns:
        grp = (
            t.groupby([proj, "_m"], dropna=False, sort=True)[["_inc", "_exp"]]
            .sum()
            .reset_index()
        )
        grp = grp.rename(columns={proj: "project name"})
    else:
        grp = (
            t.groupby("_m", dropna=False, sort=True)[["_inc", "_exp"]].sum().reset_index()
        )
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
        inc = float(r["_inc"])
        exp = float(r["_exp"])
        out_rows.append(
            {
                "project name": r["project name"],
                "plan end": pe,
                "section": "—",
                "bdr_income": inc,
                "bdr_expense": exp,
                "bdr_saldo": inc - exp,
            }
        )
    if not out_rows:
        return None
    odf = pd.DataFrame(out_rows)
    _pe = pd.to_datetime(odf["plan end"], errors="coerce")
    odf["plan_month"] = _pe.dt.to_period("M")
    odf["plan_quarter"] = _pe.dt.to_period("Q")
    odf["plan_year"] = _pe.dt.to_period("Y")
    odf.attrs["data_source_1c_synthetic_bdr"] = True
    odf.attrs["bdr_approx_by_rd_split"] = use_approx_split
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


def ensure_bdr_frame_with_fallback(
    df: pd.DataFrame,
    *,
    show_caption: bool = True,
    restrict_projects_from_df: bool = True,
) -> tuple[pd.DataFrame, bool]:
    """
    Для БДР: если в входном MSP-фрейме нет столбцов доходов/расходов с данными —
    собирает доходы, расходы и сальдо из `*_dannye.json` через `reference_1c_dannye`.

    Не подмешивает логику БДДС (budget plan/fact).
    """
    work = df.copy()

    def _has_bdr_amounts(frame: pd.DataFrame) -> bool:
        for a, b in (
            ("bdr_income", "bdr_expense"),
            ("доходы", "расходы"),
            ("доход", "расход"),
            ("income", "expense"),
        ):
            if a in frame.columns and b in frame.columns:
                x = pd.to_numeric(frame[a], errors="coerce").fillna(0.0)
                y = pd.to_numeric(frame[b], errors="coerce").fillna(0.0)
                if float(x.abs().sum() + y.abs().sum()) > 0.0:
                    return True
        return False

    if _has_bdr_amounts(work):
        return work, False

    syn = try_synthetic_bdr_from_1c_dannye()
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

    if syn.empty:
        return work, False

    if show_caption:
        approx = bool(getattr(syn, "attrs", {}).get("bdr_approx_by_rd_split"))
        if approx:
            st.caption(
                "БДР из 1С: доходы и расходы по полю «РасходДоход» (поступления / расходования), "
                "т.к. в выгрузке нет отдельных строк типа «БДР»."
            )
        else:
            st.caption("БДР из оборотов 1С (`*_dannye.json`).")

    syn.attrs.setdefault("data_source_1c_synthetic_bdr", True)
    return syn, True
