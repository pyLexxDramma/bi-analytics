# -*- coding: utf-8 -*-
"""
Подстановка план/факт бюджета из оборотов 1С (session reference_1c_dannye),
когда в MSP нет колонок budget plan / budget fact.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import numpy as np
import pandas as pd


def _turnover_article_has_lot_and_sublot(raw) -> bool:
    """
    ТЗ БДДС/БДР (1С): в расчёт включаются строки, где в «СтатьяОборотов» явно указаны
    лот и подлот (или эквивалентные маркеры).
    """
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
    has_lot = ("лот" in s) or bool(re.search(r"\blots?\b", s))
    if not has_lot:
        return False
    sublot_markers = (
        "подлот",
        "подлот.",
        "под лот",
        "сублот",
        "sub lot",
        "sublot",
    )
    if any(m in s for m in sublot_markers):
        return True
    # «Лот … / подуровень» или два уровня через точку после слова лот (напр. Лот 1.2 …)
    if "/" in s and re.search(r"лот.+/", s):
        return True
    return bool(re.search(r"лот\s*[\.\-]\s*\d", s))


def _filter_1c_frame_by_article_lot_sublot(frame: pd.DataFrame, *, art_col: Optional[str]) -> pd.DataFrame:
    if frame is None or getattr(frame, "empty", True) or not art_col or art_col not in frame.columns:
        return frame
    m = frame[art_col].map(_turnover_article_has_lot_and_sublot).fillna(False)
    if not bool(m.any()):
        return frame.iloc[0:0].copy()
    return frame.loc[m].copy()


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


def _parse_1c_period_series(raw: pd.Series) -> pd.Series:
    """
    Период из 1С в *_dannye.json чаще всего в month-first формате:
    M/D/YYYY h:mm:ss AM/PM.
    Сначала парсим как month-first, затем добираем остаток day-first.
    """
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
    for c in df.columns:
        cs = str(c).strip()
        if not cs:
            continue
        cols_exact[cs.casefold()] = cs
    for n in needles:
        k = str(n).strip().casefold()
        if k in cols_exact:
            return cols_exact[k]
    for c in df.columns:
        cs = str(c).strip()
        if not cs:
            continue
        cl = cs.casefold()
        for n in needles:
            nk = str(n).strip().casefold()
            if nk and nk in cl:
                return cs
    return None


def _guess_1c_period_column(df: pd.DataFrame) -> Optional[str]:
    """Если нет колонки «Период», ищем столбец с датами в первых строках."""
    if df is None or getattr(df, "empty", True):
        return None
    n = min(500, len(df))
    if n < 1:
        return None
    money_hints = ("сумма", "amount", "оборот", "оплат", "остаток")
    best_col: Optional[str] = None
    best_ok = 0
    for c in df.columns:
        cs = str(c).strip()
        cl = cs.casefold()
        if any(h in cl for h in money_hints):
            continue
        parsed = pd.to_datetime(df[c].head(n).astype(str).str.strip(), errors="coerce")
        ok = int(parsed.notna().sum())
        if ok > best_ok:
            best_ok = ok
            best_col = cs
    if best_col is not None and best_ok >= max(3, n // 25):
        return best_col
    return None


def _bddds_route_unassigned_plan_fact(
    t: pd.DataFrame,
    *,
    plan_mask: pd.Series,
    fact_mask: pd.Series,
) -> None:
    """
    После article-split строки со сценарием «ПЛАН»/«ФАКТ» без «Бюджет» в тексте сценария
    остаются с нулевыми __plan/__fact; fallback по fact_mask при этом не срабатывает,
    если хотя бы одна строка попала в fact_hit. Добираем такие суммы теми же масками сценария,
    что и в ветке без разнесения по статье «ФАКТ».
    """
    amt = pd.to_numeric(t["_amt"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    pl = pd.to_numeric(t["__plan"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    fc = pd.to_numeric(t["__fact"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    pm = np.asarray(plan_mask, dtype=bool)
    fm = np.asarray(fact_mask, dtype=bool)
    eps = 1e-9
    un = (np.abs(pl) < eps) & (np.abs(fc) < eps) & (np.abs(amt) > eps)
    if not bool(un.any()):
        return
    only_p = un & pm & ~fm
    only_f = un & fm & ~pm
    both = un & pm & fm
    pl = np.where(only_p, amt, pl)
    fc = np.where(only_f | both, amt, fc)
    t["__plan"] = pl
    t["__fact"] = fc


def _bddds_impute_missing_plan_from_fact_ratio(odf: pd.DataFrame) -> pd.DataFrame:
    """
    Если в `*_dannye.json` за часть месяцев есть только сценарий «ФАКТ» без строк «ПЛАН»
    (часто прошлый год), то после агрегации «budget plan» обнуляется при ненулевом факте.

    Оценка плана для таких строк: факт × (Σплан/Σфакт) по месяцам, где обе величины > 0,
    сначала внутри проекта, иначе общий коэффициент по всему набору строк.
    """
    if odf is None or getattr(odf, "empty", True):
        return odf
    out = odf.copy()
    bp_all = pd.to_numeric(out["budget plan"], errors="coerce").fillna(0.0)
    bf_all = pd.to_numeric(out["budget fact"], errors="coerce").fillna(0.0)
    sel_pairs = (bp_all > 0.0) & (bf_all > 0.0)
    global_ratio: float | None = None
    if bool(sel_pairs.any()):
        gbp = float(bp_all.loc[sel_pairs].sum())
        gbf = float(bf_all.loc[sel_pairs].sum())
        if gbf > 0.0 and np.isfinite(gbp):
            global_ratio = gbp / gbf
    imputed_any = False
    for _proj, chunk in out.groupby("project name"):
        idx = chunk.index
        bp = pd.to_numeric(out.loc[idx, "budget plan"], errors="coerce").fillna(0.0)
        bf = pd.to_numeric(out.loc[idx, "budget fact"], errors="coerce").fillna(0.0)
        sel = (bp > 0.0) & (bf > 0.0)
        ratio: float | None = None
        if bool(sel.any()):
            sp = float(bp.loc[sel].sum())
            sf = float(bf.loc[sel].sum())
            if sf > 0.0 and np.isfinite(sp):
                ratio = sp / sf
        if ratio is None and global_ratio is not None and np.isfinite(global_ratio) and global_ratio > 0.0:
            ratio = global_ratio
        if ratio is None or not np.isfinite(ratio) or ratio <= 0.0:
            continue
        need = (bp <= 0.0) & (bf > 0.0)
        if not bool(need.any()):
            continue
        fill = bf.loc[need].to_numpy(dtype=float) * float(ratio)
        out.loc[idx[need], "budget plan"] = fill
        imputed_any = True
    if imputed_any:
        out.attrs["bddds_plan_imputed_ratio"] = True
    return out


def try_synthetic_budget_from_1c_dannye(
    *,
    reference_1c_dannye: Optional[pd.DataFrame] = None,
) -> Optional[pd.DataFrame]:
    """
    Собирает DataFrame в формате дашборда БДДС: project name, plan end, budget plan, budget fact,
    plan_month / plan_quarter / plan_year, section.

    Строки без колонки периода или с неразобранной датой исключаются (не подставляются на max-дату).
    Статьи оборотов БДР не включаются в БДДС (как в прогнозном бюджете).

    ТЗ: в агрегацию попадают строки, где в «СтатьяОборотов» одновременно отражены лот и подлот
    (`_turnover_article_has_lot_and_sublot`). При отсутствии таких строк результат пустой → None.

    ТЗ БДДС (обороты 1С): план — сценарий содержит «Бюджет», статья не «ФАКТ» и не (БДР);
    факт — тот же бюджетный сценарий и статья оборотов ровно «ФАКТ». Если колонки статьи нет
    или по правилам выше не получается ни одной строки — используется прежнее разделение по словам
    в поле «Сценарий» (план/факт). Смешанные выгрузки («Бюджет»+статья и отдельные «ПЛАН»/«ФАКТ»):
    не попавшие в article-split строки добираются масками сценария. Если для месяца нет строк «ПЛАН»,
    но есть «ФАКТ», план может быть оценён коэффициентом Σплан/Σфакт по месяцам с полными данными (`_bddds_impute_missing_plan_from_fact_ratio`).

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
    if art:
        t = _filter_1c_frame_by_article_lot_sublot(t, art_col=art)
    if t.empty:
        return None

    # 1С обороты в текущих выгрузках передаются в тыс. руб.;
    # приводим к рублям, чтобы отображение в "млн руб." было корректным.
    t["_amt"] = _coerce_1c_money_series(t[amt]).fillna(0.0) * 1000.0
    sser = t[scen].astype(str)
    # Выгрузки 1С: по ТЗ план/факт из бюджетного сценария и статьи «ФАКТ» для факта; иначе — по сценарию.
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
    _norm_scen = sser.str.strip().str.casefold()
    plan_mask = plan_mask | _norm_scen.eq("план")
    fact_mask = fact_mask | _norm_scen.eq("факт")

    use_article_split = bool(art and art in t.columns)
    plan_hit = pd.Series(False, index=t.index)
    fact_hit = pd.Series(False, index=t.index)
    if use_article_split:
        scen_budget = sser.str.contains("бюджет", case=False, na=False) | sser.str.contains(
            "budget", case=False, na=False
        )
        art_norm = (
            t[art]
            .astype(str)
            .str.replace("\xa0", " ", regex=False)
            .str.replace("\u200b", "", regex=False)
            .str.strip()
            .str.casefold()
        )
        is_fact_article = art_norm.eq("факт")
        plan_hit = scen_budget & (~is_fact_article)
        fact_hit = scen_budget & is_fact_article
        if not (bool(plan_hit.any()) or bool(fact_hit.any())):
            use_article_split = False

    if use_article_split:
        amt_np = t["_amt"].to_numpy()
        t["__plan"] = np.where(plan_hit.to_numpy(), amt_np, 0.0)
        t["__fact"] = np.where(fact_hit.to_numpy(), amt_np, 0.0)
        if not bool(fact_hit.any()) and bool(fact_mask.any()):
            t["__fact"] = np.where(fact_mask.to_numpy(), amt_np, t["__fact"].to_numpy())
        _bddds_route_unassigned_plan_fact(t, plan_mask=plan_mask, fact_mask=fact_mask)
    else:
        if not plan_mask.any() and not fact_mask.any():
            return None
        t["__plan"] = np.where(plan_mask.to_numpy(), t["_amt"].to_numpy(), 0.0)
        t["__fact"] = np.where(fact_mask.to_numpy(), t["_amt"].to_numpy(), 0.0)
    t["_d"] = _parse_1c_period_series(t[per])
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
    odf = _bddds_impute_missing_plan_from_fact_ratio(odf)
    odf.attrs["data_source_1c_synthetic"] = True
    return odf


def try_synthetic_bdr_from_1c_dannye(
    *,
    reference_1c_dannye: Optional[pd.DataFrame] = None,
) -> Optional[pd.DataFrame]:
    """
    БДР из `reference_1c_dannye` по ТЗ заказчика (расходы):

    - План: «Сценарий» содержит «Бюджет» / «План» / budget и «Статья оборотов» содержит «(БДР)»
      (или тип статьи БДР без БДДС).
    - Факт: «Сценарий» содержит «ФАКТ» / fact и та же статья БДР.

    В каждой строке в сумму расходов попадает только оборот по «РасходДоход» с признаком расходования;
    неклассифицированные отрицательные суммы трактуются как расход (как в прежней версии).

    Дополнительно выставляются legacy-колонки bdr_income=0, bdr_expense=fact, bdr_saldo=plan−fact.

    Отбор сумм только по строкам «СтатьяОборотов» с лотом и подлотом — см.
    `_turnover_article_has_lot_and_sublot`.

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
    scen = _pick_col(
        t,
        (
            "Сценарий",
            "scenario",
            "сценарий",
            "видплана",
            "вид плана",
            "режим",
        ),
    )
    amt = _pick_col(
        t,
        (
            "Сумма",
            "amount",
            "суммаоборот",
            "сумма оборот",
            "суммавруб",
            "оборот",
            "суммаоборотов",
            "sum",
        ),
    )
    per = _pick_col(
        t,
        (
            "Период",
            "period",
            "месяц",
            "дата",
            "date",
            "периодитогов",
            "месяцитогов",
            "итоговыйпериод",
            "периодпрописью",
        ),
    )
    if not per:
        per = _guess_1c_period_column(t)
    proj = _pick_col(
        t,
        (
            "Проект",
            "project",
            "проект",
            "проектдляотчетов",
            "проект для отчетов",
            "наименованиепроекта",
        ),
    )
    rd = _pick_col(
        t,
        (
            "РасходДоход",
            "Расходдоход",
            "ПриходРасход",
            "приходрасход",
            "виддвижения",
            "вид движения",
            "видоборота",
            "вид оборота",
            "направление",
            "движение",
            "поступлениерасход",
            "дебеткредит",
        ),
    )
    art = _pick_col(
        t,
        (
            "СтатьяОборотов",
            "Статья оборотов",
            "article",
            "статьяоборотов",
            "статья",
        ),
    )
    typ = _pick_col(t, ("ТипСтатьи", "article_type", "Тип статьи", "типстатьи"))
    rd_synthetic = False
    if rd is None:
        t = t.copy()
        t["__bdr_rd_syn"] = "Расходование"
        rd = "__bdr_rd_syn"
        rd_synthetic = True
    if not scen or not amt or not per:
        return None

    def _bdr_article_or_type(fr: pd.DataFrame) -> pd.Series:
        m = pd.Series(False, index=fr.index)
        if art and art in fr.columns:
            a = fr[art].astype(str).fillna("")
            al = a.str.casefold()
            m = m | al.str.contains(r"\(бдр\)|^бдр$|^бдр\s", regex=True)
            m = m | (al.str.contains("бдр", regex=False) & (~al.str.contains("бддс", regex=False)))
        if typ and typ in fr.columns:
            tl = fr[typ].astype(str).fillna("").str.casefold()
            m = m | (tl.str.contains("бдр", regex=False) & (~tl.str.contains("бддс", regex=False)))
        return m

    strict_m = _bdr_article_or_type(t)
    approx_no_bdr_marker = not bool(strict_m.any())
    if approx_no_bdr_marker:
        pass
    else:
        t = t.loc[strict_m].copy()
    if t.empty:
        return None

    if art:
        t_before_lot = t
        t_f = _filter_1c_frame_by_article_lot_sublot(t, art_col=art)
        if getattr(t_f, "empty", True) and not getattr(t_before_lot, "empty", True):
            # Иначе синтетика БДР = None при несовпадении маркеров лота: график не строится.
            t = t_before_lot.copy()
            t.attrs = dict(getattr(t_before_lot, "attrs", {}) or {})
            t.attrs["bdr_article_lot_sublot_skipped_empty"] = True
        else:
            t = t_f
    if t.empty:
        return None

    scm = t[scen].astype(str).str.casefold()
    fact_rows = scm.str.contains("факт", na=False) | scm.str.contains("fact", na=False)
    plan_rows = (
        scm.str.contains("бюджет", na=False)
        | scm.str.contains("budget", na=False)
        | scm.str.contains("план", na=False)
    ) & ~fact_rows

    t["_amt"] = _coerce_1c_money_series(t[amt]).fillna(0.0) * 1000.0

    rs = t[rd].astype(str).str.casefold()
    is_inc = rs.str.contains("поступ", na=False)
    is_exp = rs.str.contains("расход", na=False)
    amt_np = t["_amt"].to_numpy(dtype=float)
    exp_amt = np.zeros(len(t), dtype=float)
    exp_amt[is_exp.to_numpy()] = np.abs(amt_np[is_exp.to_numpy()])
    uncls = ~(is_inc.to_numpy() | is_exp.to_numpy())
    neg_other = uncls & (amt_np < 0)
    exp_amt[neg_other] = np.abs(amt_np[neg_other])

    scenario_unsplit = not bool(plan_rows.any()) and not bool(fact_rows.any())
    if scenario_unsplit:
        fe_amt = exp_amt
        pe_amt = np.zeros(len(t), dtype=float)
    else:
        pe_amt = np.where(plan_rows.to_numpy(), exp_amt, 0.0)
        fe_amt = np.where(fact_rows.to_numpy(), exp_amt, 0.0)
    t["_plan_exp"] = pe_amt
    t["_fact_exp"] = fe_amt

    t["_d"] = _parse_1c_period_series(t[per])
    t = t[t["_d"].notna()].copy()
    if t.empty:
        return None
    t["_m"] = t["_d"].dt.to_period("M")

    if proj and proj in t.columns:
        grp = (
            t.groupby([proj, "_m"], dropna=False, sort=True)[["_plan_exp", "_fact_exp"]]
            .sum()
            .reset_index()
        )
        grp = grp.rename(columns={proj: "project name"})
    else:
        grp = (
            t.groupby("_m", dropna=False, sort=True)[["_plan_exp", "_fact_exp"]]
            .sum()
            .reset_index()
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
        pl = float(r["_plan_exp"])
        fc = float(r["_fact_exp"])
        dev = fc - pl
        out_rows.append(
            {
                "project name": r["project name"],
                "plan end": pe,
                "section": "—",
                "bdr_plan_expense": pl,
                "bdr_fact_expense": fc,
                "bdr_expense_deviation": dev,
                "bdr_income": 0.0,
                "bdr_expense": fc,
                "bdr_saldo": pl - fc,
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
    odf.attrs["bdr_tz_plan_fact_expense"] = True
    if getattr(t, "attrs", None) and dict(getattr(t, "attrs") or {}).get(
        "bdr_article_lot_sublot_skipped_empty"
    ):
        odf.attrs["bdr_article_lot_sublot_skipped_empty"] = True
    if approx_no_bdr_marker:
        odf.attrs["bdr_approx_no_bdr_marker"] = True
    if rd_synthetic:
        odf.attrs["bdr_synthetic_rd_column"] = True
    if scenario_unsplit:
        odf.attrs["bdr_scenario_unsplit_all_to_fact"] = True
    return odf


def ensure_budget_frame_with_fallback(
    df: pd.DataFrame,
    *,
    show_caption: bool = True,
    restrict_projects_from_df: bool = True,
    period_start: Any | None = None,
    period_end: Any | None = None,
    force_from_1c: bool = False,
    narrow_to_project_norm_key: Optional[str] = None,
) -> tuple[pd.DataFrame, bool]:
    """
    Возвращает (df_for_budget, used_fallback_1c).
    Если в исходном df нет непустых budget plan/fact, пытается собрать их из 1С.
    При force_from_1c=True всегда предпочитает синтетику из 1С.

    После сборки синтетики из 1С можно сузить строки до проектов из текущего MSP-фрейма
    и до интервала дат календаря (поле «plan end» в синтетике = конец месяца из «Период» JSON).

    narrow_to_project_norm_key: если задан (нормализованный ключ из _project_filter_norm_key),
    синтетика дополнительно сужается до этого проекта (и дочернего «… 1» и т.п.), чтобы таблицы
    БДДС не подтягивали остальные проекты при расхождении MSP и 1С.
    """
    import streamlit as st

    work = df.copy()
    has_cols = "budget plan" in work.columns and "budget fact" in work.columns
    if has_cols and not force_from_1c:
        bp = pd.to_numeric(work["budget plan"], errors="coerce").fillna(0.0)
        bf = pd.to_numeric(work["budget fact"], errors="coerce").fillna(0.0)
        if (float(bp.abs().sum()) + float(bf.abs().sum())) > 0.0:
            return work, False
    syn = try_synthetic_budget_from_1c_dannye()
    if syn is None or syn.empty:
        return work, False

    from dashboards._renderers import (
        _project_filter_norm_key,
        _project_norm_key_matches_msp_keys,
    )

    if restrict_projects_from_df and "project name" in work.columns:
        nz = work["project name"].dropna()
        if nz.empty:
            return work, False

        keys = {_project_filter_norm_key(x) for x in nz.unique()}
        keys.discard("")
        if keys:
            _rk = syn["project name"].map(_project_filter_norm_key)
            syn = syn[
                _rk.map(lambda rk: _project_norm_key_matches_msp_keys(rk, keys))
            ].copy()

    nt = (narrow_to_project_norm_key or "").strip()
    if nt and not syn.empty and "project name" in syn.columns:
        _rk_n = syn["project name"].map(_project_filter_norm_key)
        syn = syn[
            _rk_n.map(lambda rk: _project_norm_key_matches_msp_keys(rk, {nt}))
        ].copy()

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
        if not force_from_1c:
            st.caption(
                "Использован fallback: бюджетные суммы взяты из 1С (`*_dannye.json`), "
                "потому что в MSP нет непустых budget plan / budget fact."
            )
    return syn, True


def ensure_bdr_frame_with_fallback(
    df: pd.DataFrame,
    *,
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
            ("bdr_plan_expense", "bdr_fact_expense"),
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

    syn_use = syn
    if restrict_projects_from_df and "project name" in work.columns:
        nz = work["project name"].dropna()
        if not nz.empty:
            from dashboards._renderers import (
                _project_filter_norm_key,
                _project_norm_key_matches_msp_keys,
            )

            keys = {_project_filter_norm_key(x) for x in nz.unique()}
            keys.discard("")
            if keys:
                _rk = syn["project name"].map(_project_filter_norm_key)
                syn_f = syn[
                    _rk.map(lambda rk: _project_norm_key_matches_msp_keys(rk, keys))
                ].copy()
                if not syn_f.empty:
                    syn_use = syn_f
                # Иначе имена проектов в 1С не сопоставились с MSP — показываем всю синтетику 1С.

    if syn_use.empty:
        return work, False

    syn_use.attrs.update(dict(getattr(syn, "attrs", {}) or {}))
    syn_use.attrs.setdefault("data_source_1c_synthetic_bdr", True)
    return syn_use, True
