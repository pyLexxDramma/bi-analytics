# -*- coding: utf-8 -*-
"""
Матрица «Девелоперские проекты» по ТЗ (правки): строки-показатели, колонки План / Факт / Откл.
Источники: MSP (canonical колонки после web_loader), project_data (БДДС), tessa_tasks_data.
"""
from __future__ import annotations

import html as html_module
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    if df is None or not hasattr(df, "columns"):
        return None
    cols = list(df.columns)
    for cand in candidates:
        c0 = cand.strip().lower()
        for c in cols:
            if str(c).strip().lower() == c0:
                return c
    for cand in candidates:
        c0 = cand.strip().lower()
        for c in cols:
            if c0 in str(c).strip().lower():
                return c
    return None


def _krstate_bucket(raw: Any) -> str:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "other"
    s = str(raw).strip()
    sl = s.lower()
    if "declined" in sl or "отказ" in sl:
        return "declined"
    if "active" in sl or "doc_active" in sl:
        return "active"
    if "signed" in sl:
        return "signed"
    return "other"


def _norm_join_key(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    try:
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            fv = float(val)
            if fv == int(fv):
                return str(int(fv))
    except (TypeError, ValueError, OverflowError):
        pass
    s = str(val).strip()
    if len(s) > 2 and s.endswith(".0") and s[:-2].replace("-", "").isdigit():
        return s[:-2]
    return s


def _fmt_date_ru(v: Any) -> str:
    if v is None:
        return "Н/Д"
    try:
        if pd.isna(v):
            return "Н/Д"
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and pd.isna(v):
        return "Н/Д"
    if isinstance(v, pd.Timestamp):
        return v.strftime("%d.%m.%Y")
    from datetime import date, datetime

    if isinstance(v, datetime):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    ts = pd.to_datetime(v, errors="coerce", dayfirst=True)
    if pd.isna(ts):
        return "Н/Д"
    return ts.strftime("%d.%m.%Y")


def _level_series(df: pd.DataFrame) -> pd.Series:
    if "level" in df.columns:
        return pd.to_numeric(df["level"], errors="coerce")
    if "level structure" in df.columns:
        return pd.to_numeric(df["level structure"], errors="coerce")
    return pd.Series(np.nan, index=df.index)


def _task_name_col(df: pd.DataFrame) -> Optional[str]:
    if "task name" in df.columns:
        return "task name"
    return _find_col(df, ["Название задачи", "Название", "Task Name"])


def _msp_plan_fact_pct(row: pd.Series) -> Tuple[Any, Any, Any]:
    be = row.get("base end") if "base end" in row.index else pd.NaT
    pe = row.get("plan end") if "plan end" in row.index else pd.NaT
    pc = row.get("pct complete")
    pnum = pd.to_numeric(pc, errors="coerce")
    return be, pe, pnum


def _delta_days_plan_minus_fact(plan_d: Any, fact_d: Any) -> Optional[int]:
    if pd.isna(plan_d) or pd.isna(fact_d):
        return None
    try:
        return int((pd.Timestamp(plan_d).normalize() - pd.Timestamp(fact_d).normalize()).days)
    except Exception:
        return None


def _fmt_delta_days(d: Optional[int]) -> str:
    if d is None:
        return "Н/Д"
    if d == 0:
        return "0 дн."
    sign = "+" if d > 0 else ""
    return f"{sign}{d} дн."


def _match_msp(
    mdf: pd.DataFrame,
    *,
    level: Optional[float],
    name_contains: Optional[str] = None,
    names_any: Optional[List[str]] = None,
    parent_l2_contains: Optional[str] = None,
    block_contains: Optional[str] = None,
) -> pd.DataFrame:
    if mdf is None or mdf.empty:
        return mdf.iloc[0:0].copy()
    out = mdf
    nm = _task_name_col(out)
    if nm is None:
        return out.iloc[0:0].copy()
    lvl = _level_series(out)
    if level is not None and lvl.notna().any():
        out = out[lvl == float(level)]
    if block_contains and "block" in out.columns:
        out = out[out["block"].astype(str).str.contains(block_contains, case=False, na=False)]
    if parent_l2_contains:
        if "section" not in out.columns:
            return out.iloc[0:0].copy()
        out = out[out["section"].astype(str).str.contains(parent_l2_contains, case=False, na=False)]
    if names_any:
        masks = []
        for needle in names_any:
            if needle:
                masks.append(out[nm].astype(str).str.contains(str(needle), case=False, na=False))
        if masks:
            mm = masks[0]
            for x in masks[1:]:
                mm = mm | x
            out = out[mm]
    elif name_contains:
        out = out[out[nm].astype(str).str.contains(name_contains, case=False, na=False)]
    return out


def _agg_plan_fact_otkl(rows: pd.DataFrame) -> Tuple[str, str, str, bool]:
    if rows is None or rows.empty:
        return "Н/Д", "Н/Д", "Н/Д", False
    plan_parts: List[str] = []
    fact_parts: List[str] = []
    otkl_parts: List[str] = []
    warns: List[bool] = []
    for _, r in rows.iterrows():
        pdt, fdt, pct = _msp_plan_fact_pct(r)
        plan_parts.append(_fmt_date_ru(pdt))
        fact_parts.append(_fmt_date_ru(fdt))
        otkl_parts.append(_fmt_delta_days(_delta_days_plan_minus_fact(pdt, fdt)))
        warns.append(bool(pd.notna(pct) and float(pct) < 100.0))
    sep = " / "
    return sep.join(plan_parts), sep.join(fact_parts), sep.join(otkl_parts), any(warns)


def _ds_plan_fact_otkl_mln(project_data: Optional[pd.DataFrame]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if project_data is None or project_data.empty:
        return None, None, None
    bd = project_data.copy()
    bd.columns = [str(c).strip() for c in bd.columns]
    scen_col = _find_col(bd, ["Сценарий", "Scenario"])
    sum_col = _find_col(bd, ["Сумма", "Sum", "Amount", "СуммаОборота"])
    art_col = _find_col(bd, ["Статья оборотов", "СтатьяОборотов", "Статья"])
    if not scen_col or not sum_col:
        return None, None, None
    b = bd[bd[scen_col].notna()].copy()
    b = b[b[scen_col].astype(str).str.strip() != ""]
    if b.empty:
        return None, None, None
    scen_s = b[scen_col].astype(str)
    art_s = b[art_col].astype(str) if art_col and art_col in b.columns else pd.Series("", index=b.index)
    plan_mask = (
        scen_s.str.contains("бюджет", case=False, na=False)
        & art_s.astype(str).str.strip().ne("")
        & ~art_s.str.contains("бдр", case=False, na=False)
    )
    fact_mask = scen_s.str.contains("факт", case=False, na=False)
    plan_sum = pd.to_numeric(b.loc[plan_mask, sum_col], errors="coerce").fillna(0).sum()
    fact_sum = pd.to_numeric(b.loc[fact_mask, sum_col], errors="coerce").fillna(0).sum()
    return float(plan_sum) / 1e6, float(fact_sum) / 1e6, float(plan_sum - fact_sum) / 1e6


def _tessa_to_dt(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)


def _tessa_counts(ss: Any) -> Tuple[str, str, str, str]:
    tdf = ss.get("tessa_tasks_data") if hasattr(ss, "get") else None
    if tdf is None or getattr(tdf, "empty", True):
        return "Н/Д", "Н/Д", "Н/Д", ""
    tk = tdf.copy()
    tk.columns = [str(c).strip() for c in tk.columns]
    kk = _find_col(tk, ["KindName", "kindname", "Вид"])
    if not kk:
        return "Н/Д", "Н/Д", "Н/Д", ""
    pred = tk[tk[kk].astype(str).str.contains("предписан", case=False, na=False)].copy()
    if pred.empty:
        return "0", "0", "0", ""
    card_c = _find_col(pred, ["CardId", "CardID", "cardId"])
    state_c = _find_col(pred, ["KrStateName", "KrState", "State", "Состояние", "Статус"])
    due_c = _find_col(pred, ["PlanDate", "DueDate", "Срок", "Крайний срок"])
    if not card_c:
        return str(len(pred)), "—", "—", ""
    pred = pred.assign(_card=pred[card_c].map(_norm_join_key))
    pred = pred[pred["_card"].astype(str).str.len() > 0]
    n_cards = int(pred["_card"].nunique())
    if state_c and state_c in pred.columns:
        signed_any = pred.groupby("_card", group_keys=False)[state_c].agg(
            lambda s: any(_krstate_bucket(x) == "signed" for x in s.astype(str))
        )
        n_signed = int(signed_any.sum())
    else:
        n_signed = 0
    n_open = int(max(0, n_cards - n_signed))
    hint = ""
    if due_c and due_c in pred.columns and state_c and state_c in pred.columns:
        now = pd.Timestamp.now().normalize()

        def _open_row(r: pd.Series) -> bool:
            return _krstate_bucket(r.get(state_c)) != "signed"

        om = pred.apply(_open_row, axis=1)
        dts = _tessa_to_dt(pred.loc[om, due_c])
        overdue_n = int(((dts.dt.normalize() < now) & dts.notna()).sum())
        if overdue_n:
            hint = f"Просрочено по сроку (строки неподпис.): {overdue_n}"
    return str(n_cards), str(n_signed), str(n_open), hint


def build_dev_tz_matrix_rows(
    mdf: pd.DataFrame,
    project_data: Optional[pd.DataFrame],
    ss: Any,
) -> Tuple[List[Dict[str, Any]], str]:
    rows: List[Dict[str, Any]] = []

    def add_row(group: str, label: str, plan_s: str, fact_s: str, otkl_s: str, warn: bool = False) -> None:
        rows.append({"group": group, "label": label, "plan": plan_s, "fact": fact_s, "otkl": otkl_s, "warn": warn})

    pid = "Н/Д"
    pname = "Н/Д"
    if "project id" in mdf.columns and mdf["project id"].notna().any():
        pid = str(mdf["project id"].dropna().astype(str).iloc[0]).strip() or "Н/Д"
    if "project name" in mdf.columns and mdf["project name"].notna().any():
        pname = str(mdf["project name"].dropna().astype(str).iloc[0]).strip() or "Н/Д"
    add_row("Проект", "Проект", pid, pname, "—", False)

    specs: List[Tuple[str, str, dict]] = [
        ("ЗУ / Ковенанты", "Аренда ЗУ", {"level": 5.0, "name_contains": "Регистрация договора субаренды", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "Готовый продукт", {"level": 5.0, "name_contains": "инвестиционном комитете", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "ГПЗУ", {"level": 5.0, "name_contains": "ГПЗУ", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "Экспертиза (стП)", {"level": 5.0, "name_contains": "Экспертиза ПД", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "Команда РП", {"level": 5.0, "name_contains": "Подбор команды", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "РС", {"level": 5.0, "name_contains": "Разрешение на строительство", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "РД (1 вар)", {"level": 5.0, "name_contains": "Рабочая Документация (РД)", "parent_l2_contains": "Ковенанты"}),
        ("ИРД", "Подготовительный этап (ТУ, ЭВ-ВО)", {"level": 4.0, "name_contains": "Электроснабжение", "block_contains": "ИРД"}),
        ("ИРД", "Подготовительный этап (Примыкания)", {"level": 4.0, "name_contains": "Примыкания к УДС", "block_contains": "ИРД"}),
        ("Проектные работы", "ПОС (1 вар)", {"level": None, "name_contains": "Согласование ПЗУ", "block_contains": "ПРОЕКТ"}),
        ("Ковенанты", "Начало финансирования СМР", {"level": 5.0, "name_contains": "Начало финансирования", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "Начало СМР", {"level": 5.0, "name_contains": "Начало СМР", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "Тех. присоединения", {"level": 5.0, "names_any": ["Пуск электричества", "Пуск газа"], "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "ЗОС", {"level": 5.0, "name_contains": "Заключение о соответствии", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "РВ", {"level": 5.0, "name_contains": "Разрешение на ввод", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "Право 1", {"level": 5.0, "name_contains": "Право 1", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "Выкуп ЗУ", {"level": 5.0, "name_contains": "Выкуп земельного участка", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "Право 2 на застройщика", {"level": 5.0, "name_contains": "Право 2", "parent_l2_contains": "Ковенанты"}),
        ("Ковенанты", "Передача боксов резидентам", {"level": 5.0, "name_contains": "Передача боксов", "parent_l2_contains": "Ковенанты"}),
    ]

    for group, label, kw in specs:
        sub = _match_msp(
            mdf,
            level=kw.get("level"),
            name_contains=kw.get("name_contains"),
            names_any=kw.get("names_any"),
            parent_l2_contains=kw.get("parent_l2_contains"),
            block_contains=kw.get("block_contains"),
        )
        ps, fs, os, w = _agg_plan_fact_otkl(sub)
        add_row(group, label, ps, fs, os, w)

    pm, fm, om = _ds_plan_fact_otkl_mln(project_data)
    if pm is None:
        add_row("Финансы", "Выборка ДС, млн руб.", "Н/Д", "Н/Д", "Н/Д", False)
    else:

        def _fmtml(v: float) -> str:
            return f"{v:.3f}".replace(".", ",")

        add_row("Финансы", "Выборка ДС, млн руб.", _fmtml(pm), _fmtml(fm), _fmtml(om), False)

    tp, tf, to, hint = _tessa_counts(ss)
    warn_t = False
    try:
        warn_t = int(str(to).strip()) > 0
    except (TypeError, ValueError):
        warn_t = False
    add_row("TESSA", "Предписания", tp, tf, to, warn_t)

    cap = (
        "По ТЗ: для MSP План = «Базовое окончание» (base end), Факт = «Окончание» (plan end после ремапа), "
        "Откл. = План − Факт, дни. ДС: млн руб., статья не пустая и без «БДР». Предписания: уник. CardId / подписано / не устранено."
    )
    if hint:
        cap = cap + " " + hint
    return rows, cap


_DEV_TZ_MATRIX_CSS = """
<style>
.rendered-table tr.dev-tz-row-warn td {
  background: rgba(220, 53, 69, 0.22) !important;
  color: #ffd6d6;
}
.rendered-table td.dev-tz-group { color:#9aa4b2; font-size:12px; vertical-align:middle; }
</style>
"""


def render_dev_tz_matrix(rows: List[Dict[str, Any]], table_css: str) -> None:
    import streamlit as st

    esc = html_module.escape
    thead = (
        "<thead><tr>"
        "<th>Группа</th><th>Показатель</th><th>План</th><th>Факт</th><th>Откл.</th>"
        "</tr></thead>"
    )
    body_parts = ["<tbody>"]
    for r in rows:
        cls = ' class="dev-tz-row-warn"' if r.get("warn") else ""
        grp = r.get("group") or ""
        lab = r.get("label") or ""
        pl = r.get("plan") or ""
        fc = r.get("fact") or ""
        ot = r.get("otkl") or ""
        body_parts.append(
            f"<tr{cls}>"
            f'<td class="dev-tz-group">{esc(str(grp))}</td>'
            f"<td>{esc(str(lab))}</td>"
            f"<td>{esc(str(pl))}</td>"
            f"<td>{esc(str(fc))}</td>"
            f"<td>{esc(str(ot))}</td>"
            "</tr>"
        )
    body_parts.append("</tbody>")
    html_tbl = '<table class="rendered-table" border="0">' + thead + "".join(body_parts) + "</table>"
    st.markdown(
        table_css + _DEV_TZ_MATRIX_CSS + '<div class="rendered-table-wrap">' + html_tbl + "</div>",
        unsafe_allow_html=True,
    )
