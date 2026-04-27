# -*- coding: utf-8 -*-
"""
Сводка готовности данных для дашбордов после load_all_from_web().

Используется на главной панели: session_state['last_data_readiness'].
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st


def _df_ok(d: Any) -> bool:
    return d is not None and isinstance(d, pd.DataFrame) and not d.empty


def _msp_cols_present(df: pd.DataFrame) -> set[str]:
    if not _df_ok(df):
        return set()
    return {str(c).strip().casefold() for c in df.columns}


def _has_budget_msp_or_1c(project_df, ref1c: Optional[pd.DataFrame]) -> str:
    if _df_ok(project_df):
        c = {str(x).casefold() for x in project_df.columns}
        if "budget plan" in c and "budget fact" in c:
            bp = pd.to_numeric(project_df.get("budget plan", 0), errors="coerce")
            bf = pd.to_numeric(project_df.get("budget fact", 0), errors="coerce")
            if (bp.fillna(0).abs().sum() + bf.fillna(0).abs().sum()) > 0:
                return "ok"
    if _df_ok(ref1c):
        sjoin = " ".join(str(c).casefold() for c in ref1c.columns)
        if "сценар" in sjoin and ("сумм" in sjoin or "amount" in sjoin):
            return "ok"
    return "warn"


def _dk_ok(dfdk: Any) -> str:
    if not _df_ok(dfdk):
        return "err"
    need = ("остаток", "контрагент", "договор")
    s = " ".join(str(c).casefold() for c in dfdk.columns)
    for k in need:
        if k not in s and k not in s.replace(" ", ""):
            return "warn"
    return "ok"


def build_data_readiness_report(
    load_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Возвращает dict: summary, file_rows, duplicates_note, reports: List[{name, level, source, message}]
    level: ok | warn | err
    """
    pd_ = st.session_state.get("project_data")
    res_ = st.session_state.get("resources_data")
    tech_ = st.session_state.get("technique_data")
    tessa_ = st.session_state.get("tessa_data")
    tasks_ = st.session_state.get("tessa_tasks_data")
    dk_ = st.session_state.get("debit_credit_data")
    ref1c = st.session_state.get("reference_1c_dannye")
    kr_ = st.session_state.get("reference_krstates")

    summary = {
        "project_data_rows": int(len(pd_)) if _df_ok(pd_) else 0,
        "resources_rows": int(len(res_)) if _df_ok(res_) else 0,
        "tessa_rows": int(len(tessa_)) if _df_ok(tessa_) else 0,
        "tessa_tasks_rows": int(len(tasks_)) if _df_ok(tasks_) else 0,
        "debit_credit_rows": int(len(dk_)) if _df_ok(dk_) else 0,
        "reference_1c_rows": int(len(ref1c)) if _df_ok(ref1c) else 0,
        "krstates_rows": int(len(kr_)) if _df_ok(kr_) else 0,
    }
    out_load = {}
    if load_result and isinstance(load_result, dict):
        out_load = {
            "loaded": load_result.get("loaded"),
            "skipped": load_result.get("skipped"),
            "version_id": load_result.get("version_id"),
            "n_warnings": len(load_result.get("warnings") or []),
            "n_errors": len(load_result.get("errors") or []),
        }
    reports: List[Dict[str, str]] = []

    def add(name: str, level: str, source: str, message: str) -> None:
        reports.append({"name": name, "level": level, "source": source, "message": message})

    # --- сроки / MSP
    mnames = (
        "Причины отклонений",
        "Отклонение от базового плана",
        "Контрольные точки",
        "График проекта",
    )
    for n in mnames:
        if not _df_ok(pd_):
            add(n, "err", "MSP", "Нет project_data (msp csv).")
            continue
        cols = _msp_cols_present(pd_)
        if n == "Причины отклонений" and "reason of deviation" not in cols:
            add(n, "warn", "MSP", "Нет колонки reason of deviation.")
        elif n == "Отклонение от базового плана" and ("base end" not in cols or "plan end" not in cols):
            add(n, "warn", "MSP", "Нужны колонки base end / plan end.")
        elif n == "Контрольные точки":
            add(n, "warn", "MSP", "Нужны задачи и даты в MSP; сверка с настройками КТ.")
        else:
            add(n, "ok", "MSP", "Строки MSP загружены (график/сроки).")

    # БДДС / лот
    for n in ("БДДС", "Бюджет по лотам"):
        h = _has_budget_msp_or_1c(pd_, ref1c if _df_ok(ref1c) else None)
        if h == "ok":
            add(n, "ok", "MSP или 1С", "Есть бюджет в MSP и/или обороты 1С (Сценарий+Сумма).")
        else:
            add(n, "err", "MSP+1С", "Нет непустого budget plan/fact в MSP и нет пригодных оборотов в reference_1c_dannye.")

    for n in ("БДР", "Бюджет план/факт", "Утвержденный бюджет", "Прогнозный бюджет"):
        h = _has_budget_msp_or_1c(pd_, ref1c if _df_ok(ref1c) else None)
        if h == "ok":
            add(n, "ok", "MSP/1С", "Источник сумм доступен; при расхождении — согласовать джойн с заказчиком.")
        else:
            add(n, "warn" if n == "Прогнозный бюджет" else "err", "MSP/1С", "Возможен пустой отчёт: нет бюджетных колонок / нет 1С.")

    # ДЗ/КЗ
    dkl = _dk_ok(dk_)
    if dkl == "ok":
        add("Дебиторская и кредиторская задолженность подрядчиков", "ok", "1С DK.json", "Данные ДЗ/КЗ загружены.")
    elif dkl == "warn" and _df_ok(dk_):
        add("Дебиторская и кредиторская задолженность подрядчиков", "warn", "1С DK.json", "Файл есть, проверьте полноту колонок.")
    else:
        add("Дебиторская и кредиторская задолженность подрядчиков", "err", "1С DK.json", "Нет debit_credit_data.")

    # РД/ПД
    if not _df_ok(pd_):
        add("Рабочая документация", "err", "MSP+TESSA", "Нет MSP; план/факт РД — частично из сессии.")
    else:
        add("Рабочая документация", "warn" if not _df_ok(tessa_) else "ok", "MSP+TESSA", "TESSA rd для факта" + ("" if _df_ok(tessa_) else " — пусто."))
    if not _df_ok(pd_):
        add("Проектная документация", "err", "MSP", "Нет MSP.")
    else:
        add("Проектная документация", "ok", "MSP", "Задачи ПД из MSP.")

    # ГДРС
    if not _df_ok(res_):
        add("ГДРС", "err", "resources csv", "Нет resources_data (other_*_resursi).")
    else:
        add("ГДРС", "ok", "resources csv", "Факт загружен; план по договору в ТЗ может отсутствовать.")
    if not _df_ok(res_):
        add("ГДРС Техника", "err", "resources csv", "Нет resources_data.")
    else:
        add("ГДРС Техника", "ok", "resources csv", "Проверьте колонку типа ресурса при пустом отчёте.")

    # TESSA
    for n in ("Исполнительная документация", "Неустраненные предписания"):
        if not _df_ok(tessa_):
            add(n, "err", "TESSA", "Нет tessa_data (id/rd).")
        elif not _df_ok(kr_):
            add(n, "warn", "TESSA+KrStates", "TESSA есть, KrStates пуст — статусы могут быть сырые.")
        else:
            add(n, "ok", "TESSA", "TESSA + справочник статусов.")
    if not _df_ok(pd_) and (not _df_ok(tessa_)):
        add("Просрочка выдачи РД", "err", "MSP+план+TESSA", "Нет MSP и TESSA — отчёт неполный.")
    else:
        add("Просрочка выдачи РД", "warn", "rd_plan+TESSA", "Нужен план РД (csv) + факт TESSA rd.")
    if not _df_ok(pd_):
        add("Просрочка выдачи ПД", "err", "MSP", "Нет MSP.")
    else:
        add("Просрочка выдачи ПД", "ok", "MSP", "Задачи ПД в MSP.")
    if not _df_ok(pd_):
        add("Девелоперские проекты", "warn" if _df_ok(ref1c) or _df_ok(tessa_) else "err", "MSP+1С+TESSA", "Нет MSP; доступны 1С/TESSA.")
    else:
        add("Девелоперские проекты", "ok", "MSP+1С+TESSA", "База для сводки есть.")

    return {
        "summary": summary,
        "load": out_load,
        "reports": reports,
    }


def render_data_readiness_expander() -> None:
    """Показать в Streamlit expander, если last_data_readiness в session_state."""
    rep = st.session_state.get("last_data_readiness")
    if not rep:
        return
    with st.expander("Проверка загрузки: готовность данных по дашбордам", expanded=True):
        s = rep.get("summary") or {}
        st.markdown(
            f"**Строки в сессии:** project_data={s.get('project_data_rows', 0)}, "
            f"resources={s.get('resources_rows', 0)}, **1С dannye**={s.get('reference_1c_rows', 0)}, "
            f"TESSA={s.get('tessa_rows', 0)}, TESSA task={s.get('tessa_tasks_rows', 0)}, "
            f"DK={s.get('debit_credit_rows', 0)}."
        )
        lo = rep.get("load") or {}
        if lo:
            st.caption(
                f"Последняя загрузка: файлов={lo.get('loaded')}, пропущено={lo.get('skipped')}, "
                f"version_id={lo.get('version_id')}, предупреждений={lo.get('n_warnings', 0)}."
            )
        rows = rep.get("reports") or []
        if rows:
            # Показываем таблицу полностью (без внутреннего скролла), чтобы
            # пользователь прокручивал только страницу целиком.
            _row_h = 34
            _header_h = 38
            _table_h = _header_h + max(1, len(rows)) * _row_h
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                height=_table_h,
            )
        st.caption(
            "ok — данные для отчёта в целом есть; warn — есть риск пустых/частичных графиков; "
            "err — для отчёта не хватает выгрузки. Детализация колонок: см. expander «Справка: колонки загрузки»."
        )
