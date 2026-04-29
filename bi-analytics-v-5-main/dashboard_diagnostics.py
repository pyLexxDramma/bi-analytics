from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
import streamlit as st


_DASHBOARD_REQUIRED_COLUMNS: Dict[str, Dict[str, List[str]]] = {
    "Девелоперские проекты": {
        "required": ["project name", "task name", "plan start", "plan end"],
        "date": ["plan start", "plan end", "base start", "base end"],
        "numeric": ["pct complete", "deviation in days", "deviation start days"],
    },
    "Причины отклонений": {
        "required": ["project name", "task name", "reason of deviation"],
        "date": ["plan end", "base end"],
        "numeric": ["deviation in days"],
    },
    "Отклонение от базового плана": {
        "required": ["project name", "task name", "plan start", "plan end", "base start", "base end"],
        "date": ["plan start", "plan end", "base start", "base end"],
        "numeric": ["deviation in days", "deviation start days", "pct complete"],
    },
    "Контрольные точки": {
        "required": ["project name", "task name", "plan end", "base end"],
        "date": ["plan end", "base end", "actual finish"],
        "numeric": ["pct complete"],
    },
    "График проекта": {
        "required": ["project name", "task name", "plan start", "plan end"],
        "date": ["plan start", "plan end", "base start", "base end"],
        "numeric": [],
    },
    "БДДС": {
        "required": ["Период", "Проект", "Сумма"],
        "date": ["Период"],
        "numeric": ["Сумма"],
    },
    "БДР": {
        "required": ["Период", "Проект", "Сумма"],
        "date": ["Период"],
        "numeric": ["Сумма"],
    },
    "Бюджет план/факт": {
        "required": ["project name", "task name"],
        "date": [],
        "numeric": ["budget plan", "budget fact"],
    },
    "Утвержденный бюджет": {
        "required": ["Период", "Проект", "Сумма"],
        "date": ["Период"],
        "numeric": ["Сумма"],
    },
    "Прогнозный бюджет": {
        "required": ["Период", "Проект", "Сумма"],
        "date": ["Период"],
        "numeric": ["Сумма"],
    },
    "Дебиторская и кредиторская задолженность подрядчиков": {
        "required": ["Контрагент", "Договор"],
        "date": [],
        "numeric": ["ОстатокНаНачалоПериода", "ОстатокНаКонецПериода"],
    },
}


def _colmap(df: pd.DataFrame) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for c in df.columns:
        out[str(c).strip().lower()] = str(c)
    return out


def _sample_parse_rate_date(s: pd.Series) -> float:
    x = s.dropna()
    if x.empty:
        return 1.0
    y = pd.to_datetime(x, errors="coerce", dayfirst=True)
    return float(y.notna().mean())


def _sample_parse_rate_num(s: pd.Series) -> float:
    x = s.dropna()
    if x.empty:
        return 1.0
    z = x.astype(str).str.strip()
    z = z.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    z = z.str.replace(r"[^0-9,\.\-]", "", regex=True)
    mixed = z.str.contains(",", na=False) & z.str.contains(r"\.", na=False)
    z.loc[mixed] = z.loc[mixed].str.replace(".", "", regex=False)
    only_comma = z.str.contains(",", na=False) & ~z.str.contains(r"\.", na=False)
    z.loc[only_comma] = z.loc[only_comma].str.replace(",", ".", regex=False)
    multi_dot = z.str.count(r"\.").fillna(0) > 1
    if bool(multi_dot.any()):
        z.loc[multi_dot] = z.loc[multi_dot].str.replace(r"\.(?=.*\.)", "", regex=True)
    y = pd.to_numeric(z, errors="coerce")
    return float(y.notna().mean())


def build_dashboard_diagnostics(selected_dashboard: str, df: pd.DataFrame, state: Any) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    if df is None or getattr(df, "empty", True):
        rows.append({"level": "err", "check": "dataset", "target": selected_dashboard, "detail": "Пустой набор данных для выбранного дашборда"})
        return {"dashboard": selected_dashboard, "generated_at": datetime.now().isoformat(), "rows": rows}

    cdict = _colmap(df)
    spec = _DASHBOARD_REQUIRED_COLUMNS.get(selected_dashboard, {"required": [], "date": [], "numeric": []})

    for req in spec.get("required", []):
        ok = req.strip().lower() in cdict
        rows.append({
            "level": "ok" if ok else "err",
            "check": "required_column",
            "target": req,
            "detail": "найдена" if ok else "не найдена",
        })

    for dcol in spec.get("date", []):
        key = dcol.strip().lower()
        if key not in cdict:
            continue
        rate = _sample_parse_rate_date(df[cdict[key]])
        lvl = "ok" if rate >= 0.9 else "warn" if rate >= 0.6 else "err"
        rows.append({
            "level": lvl,
            "check": "date_format",
            "target": dcol,
            "detail": f"успешный парсинг: {rate:.0%}",
        })

    for ncol in spec.get("numeric", []):
        key = ncol.strip().lower()
        if key not in cdict:
            continue
        rate = _sample_parse_rate_num(df[cdict[key]])
        lvl = "ok" if rate >= 0.9 else "warn" if rate >= 0.6 else "err"
        rows.append({
            "level": lvl,
            "check": "numeric_format",
            "target": ncol,
            "detail": f"успешный парсинг: {rate:.0%}",
        })

    if selected_dashboard in ("ГДРС", "ГДРС Техника"):
        has_res = state.get("resources_data") is not None and not getattr(state.get("resources_data"), "empty", True)
        rows.append({"level": "ok" if has_res else "err", "check": "source_dataset", "target": "resources_data", "detail": "доступен" if has_res else "не загружен"})
    if selected_dashboard in ("Исполнительная документация", "Неустраненные предписания"):
        has_tessa = state.get("tessa_data") is not None and not getattr(state.get("tessa_data"), "empty", True)
        has_task = state.get("tessa_tasks_data") is not None and not getattr(state.get("tessa_tasks_data"), "empty", True)
        rows.append({"level": "ok" if has_tessa else "err", "check": "source_dataset", "target": "tessa_data", "detail": "доступен" if has_tessa else "не загружен"})
        rows.append({"level": "ok" if has_task else "warn", "check": "source_dataset", "target": "tessa_tasks_data", "detail": "доступен" if has_task else "не загружен"})
    if selected_dashboard == "Дебиторская и кредиторская задолженность подрядчиков":
        has_dk = state.get("debit_credit_data") is not None and not getattr(state.get("debit_credit_data"), "empty", True)
        rows.append({"level": "ok" if has_dk else "err", "check": "source_dataset", "target": "debit_credit_data", "detail": "доступен" if has_dk else "не загружен"})

    return {"dashboard": selected_dashboard, "generated_at": datetime.now().isoformat(), "rows": rows}


def render_dashboard_diagnostics_tab(selected_dashboard: str, df: pd.DataFrame, state: Any) -> None:
    report = build_dashboard_diagnostics(selected_dashboard, df, state)
    rows = report.get("rows", [])
    st.caption("Проверка обновляется при каждом изменении фильтров/вкладок (перезапуск Streamlit-цикла).")
    if not rows:
        st.info("Нет данных для диагностики.")
        return
    _df = pd.DataFrame(rows)
    _prio = {"err": 0, "warn": 1, "ok": 2}
    _df["_p"] = _df["level"].map(lambda x: _prio.get(str(x).lower(), 9))
    _df = _df.sort_values(["_p", "check", "target"], kind="stable").drop(columns=["_p"])
    st.dataframe(_df, use_container_width=True, hide_index=True, height=min(680, 40 + len(_df) * 34))

    md_lines = [
        f"# Диагностика: {selected_dashboard}",
        f"- generated_at: {report.get('generated_at')}",
        "",
    ]
    for r in rows:
        md_lines.append(f"- [{str(r.get('level')).upper()}] {r.get('check')} | {r.get('target')} | {r.get('detail')}")
    md_text = "\n".join(md_lines)
    j_text = json.dumps(report, ensure_ascii=False, indent=2)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Скачать diagnostics.md",
            data=md_text,
            file_name=f"diagnostics_{selected_dashboard}.md".replace("/", "_"),
            mime="text/markdown",
            key=f"diag_md_{selected_dashboard}",
        )
    with c2:
        st.download_button(
            "Скачать diagnostics.json",
            data=j_text,
            file_name=f"diagnostics_{selected_dashboard}.json".replace("/", "_"),
            mime="application/json",
            key=f"diag_json_{selected_dashboard}",
        )
