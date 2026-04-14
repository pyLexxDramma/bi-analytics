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


def _series_first_value(row: pd.Series, col: str) -> Any:
    """
    Скаляр из ячейки: при дублирующихся именах колонок (напр. два «plan end» после
    ремапа «Окончание» и «План окончание») берётся первое непустое значение.
    """
    if col not in row.index:
        return pd.NaT
    v = row[col]
    if isinstance(v, pd.Series):
        v2 = v.dropna()
        if v2.empty:
            return pd.NaT
        return v2.iloc[0]
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return pd.NaT
    return v


def _msp_plan_fact_pct(row: pd.Series) -> Tuple[Any, Any, Any]:
    """
    По ТЗ: План = «Базовое окончание» (base end), Факт = «Окончание»;
    если в выгрузке есть «Фактическое окончание» — используем его как факт.
    Canonical после web_loader: base end, plan end (из «Окончание»), actual finish.
    """
    be = _series_first_value(row, "base end")
    fe = pd.NaT
    af = _series_first_value(row, "actual finish")
    if not (af is None or (isinstance(af, float) and pd.isna(af))):
        fe = af
    if pd.isna(fe):
        fe = _series_first_value(row, "plan end")
    pc = _series_first_value(row, "pct complete") if "pct complete" in row.index else pd.NaT
    pnum = pd.to_numeric(pc, errors="coerce")
    return be, fe, pnum


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

    tp, tf, to, _tessa_hint = _tessa_counts(ss)
    warn_t = False
    try:
        warn_t = int(str(to).strip()) > 0
    except (TypeError, ValueError):
        warn_t = False
    add_row("TESSA", "Предписания", tp, tf, to, warn_t)

    cap = ""
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


# ── Контрольные точки (Сроки / макет file-009): проекты × вехи ───────────────

CONTROL_POINT_MILESTONES: List[Tuple[str, str, dict]] = [
    # title, slug, kwargs для _match_msp (+ ослабление родителя в _match_milestone_tasks)
    ("ГПЗУ", "gpzu", {"level": 5.0, "name_contains": "ГПЗУ", "parent_l2_contains": "Ковенанты"}),
    (
        "Экспертиза стадии П",
        "exp_p",
        {"level": 5.0, "name_contains": "Экспертиза ПД", "parent_l2_contains": "Ковенанты"},
    ),
    (
        "Начало финансирования",
        "fin",
        {"level": 5.0, "name_contains": "Начало финансирования", "parent_l2_contains": "Ковенанты"},
    ),
    (
        "Стадия РД",
        "rd",
        {"level": 5.0, "name_contains": "Рабочая Документация (РД)", "parent_l2_contains": "Ковенанты"},
    ),
]


def _project_name_column(df: pd.DataFrame) -> Optional[str]:
    if "project name" in df.columns:
        return "project name"
    return _find_col(df, ["Проект", "Project", "project"])


def _match_milestone_tasks(mdf: pd.DataFrame, kw: dict) -> pd.DataFrame:
    """Как _match_msp; если с фильтром «Ковенанты» пусто — пробуем без родителя."""
    if mdf is None or getattr(mdf, "empty", True):
        return mdf.iloc[0:0].copy()
    out = _match_msp(mdf, **kw)
    if out.empty and kw.get("parent_l2_contains"):
        kw2 = {k: v for k, v in kw.items() if k != "parent_l2_contains"}
        out = _match_msp(mdf, **kw2)
    return out


def _one_milestone_cell(rows: pd.DataFrame) -> Tuple[str, str, str, bool]:
    """
    План = базовое окончание (base end), Факт = окончание / actual finish.
    Откл. = План − Факт (календарные дни), согласно ТЗ и матрице девелоперских проектов.
    """
    if rows is None or rows.empty:
        return "Н/Д", "Н/Д", "Н/Д", False
    tc = _task_name_col(rows)
    if tc and tc in rows.columns:
        r = rows.sort_values(by=tc).iloc[0]
    else:
        r = rows.iloc[0]
    pdt, fdt, _pct = _msp_plan_fact_pct(r)
    pl = _fmt_date_ru(pdt)
    fl = _fmt_date_ru(fdt)
    if pd.isna(pdt) or pd.isna(fdt):
        return pl, fl, "Н/Д", False
    dev_days = _delta_days_plan_minus_fact(pdt, fdt)
    otk = _fmt_delta_days(dev_days)
    ok = bool(dev_days == 0) if dev_days is not None else False
    return pl, fl, otk, ok


def build_control_points_df(mdf: pd.DataFrame) -> pd.DataFrame:
    """Одна строка на проект; столбцы project, row_ok, {slug}_plan|_fact|_otkl."""
    pcol = _project_name_column(mdf)
    if pcol is None or mdf is None or mdf.empty:
        return pd.DataFrame()
    work = mdf.copy()
    projects = sorted(work[pcol].dropna().astype(str).str.strip().unique())
    rows_out: List[Dict[str, Any]] = []
    for proj in projects:
        sub = work[work[pcol].astype(str).str.strip() == proj]
        rec: Dict[str, Any] = {"project": proj, "row_ok": True}
        for title, slug, kw in CONTROL_POINT_MILESTONES:
            m = _match_milestone_tasks(sub, kw)
            pl, fl, otk, ok = _one_milestone_cell(m)
            rec[f"{slug}_plan"] = pl
            rec[f"{slug}_fact"] = fl
            rec[f"{slug}_otkl"] = otk
            rec[f"{slug}_ok"] = ok
            if not ok:
                rec["row_ok"] = False
        rows_out.append(rec)
    return pd.DataFrame(rows_out)


_CONTROL_POINTS_CSS = """
<style>
.cp-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:8px; vertical-align:middle; }
.cp-dot-ok { background:#22c55e; box-shadow:0 0 6px rgba(34,197,94,0.45); }
.cp-dot-bad { background:#ef4444; box-shadow:0 0 6px rgba(239,68,68,0.45); }
.rendered-table th.cp-ghead { text-align:center; background:#1f232d; font-size:12px; padding:6px 8px; }
.rendered-table th.cp-sub { font-size:11px; color:#c9d1d9; font-weight:500; }
</style>
"""


def render_control_points_dashboard(st, mdf: pd.DataFrame, table_css: str) -> None:
    """Таблица «Контрольные точки проектов» + фильтр проектов + выгрузка CSV."""
    esc = html_module.escape
    df = build_control_points_df(mdf)
    if df.empty:
        st.warning("Нет строк проектов в данных MSP.")
        return
    projs = sorted(df["project"].astype(str).unique().tolist())
    sel = st.multiselect("Проект", options=projs, default=projs, key="cp_projects_ms")
    view = df[df["project"].isin(sel)].copy()
    if view.empty:
        st.caption("Выберите хотя бы один проект.")
        return

    ms_specs = [(t, s) for t, s, _k in CONTROL_POINT_MILESTONES]
    thead1 = ['<th rowspan="2" style="min-width:180px">Проект</th>']
    for title, slug in ms_specs:
        thead1.append(f'<th colspan="3" class="cp-ghead">{esc(title)}</th>')
    sub_headers: List[str] = []
    for _title, slug in ms_specs:
        sub_headers.extend(
            [
                f'<th class="cp-sub">{esc("План")}</th>',
                f'<th class="cp-sub">{esc("Факт")}</th>',
                f'<th class="cp-sub">{esc("Откл.")}</th>',
            ]
        )
    thead_html = (
        "<thead><tr>"
        + "".join(thead1)
        + "</tr><tr>"
        + "".join(sub_headers)
        + "</tr></thead>"
    )
    body: List[str] = ["<tbody>"]
    for _, r in view.iterrows():
        ok_row = bool(r.get("row_ok", True))
        dot = "cp-dot-ok" if ok_row else "cp-dot-bad"
        cells = [
            f'<td><span class="cp-dot {dot}" title="{"OK" if ok_row else "Есть отклонения"}"></span>'
            f"{esc(str(r.get('project', '')))}</td>"
        ]
        for _t, slug in ms_specs:
            cells.append(f"<td>{esc(str(r.get(f'{slug}_plan', '')))}</td>")
            cells.append(f"<td>{esc(str(r.get(f'{slug}_fact', '')))}</td>")
            cells.append(f"<td>{esc(str(r.get(f'{slug}_otkl', '')))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    body.append("</tbody>")
    html_tbl = (
        '<table class="rendered-table" border="0">'
        + thead_html
        + "".join(body)
        + "</table>"
    )
    st.markdown(
        table_css + _CONTROL_POINTS_CSS + '<div class="rendered-table-wrap">' + html_tbl + "</div>",
        unsafe_allow_html=True,
    )

    drop_ok = [c for c in view.columns if str(c).endswith("_ok")]
    export = view.drop(columns=drop_ok, errors="ignore")
    csv_bytes = export.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "Скачать таблицу (CSV)",
        csv_bytes,
        "control_points.csv",
        "text/csv",
        key="cp_csv_dl",
    )
