# -*- coding: utf-8 -*-
"""Предупреждения о качестве / источнике данных под графиками и таблицами."""

from __future__ import annotations

from typing import Any, Iterable


def _dedupe_preserve(seq: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        s = str(x).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def collect_budget_1c_hints(
    attrs: dict[str, Any] | None,
    *,
    used_fallback_1c: bool = False,
) -> list[str]:
    """БДДС / план-факт из MSP или синтетики 1С."""
    a = attrs or {}
    hints: list[str] = []
    syn = bool(a.get("data_source_1c_synthetic"))
    if used_fallback_1c or syn:
        hints.append(
            "Бюджет план/факт на этом экране берётся из оборотов 1С (`*_dannye.json`). "
            "Нужны колонки «Период», «Сумма» и «Сценарий»; разделение по ТЗ: "
            "бюджетный сценарий и статья оборотов **не** «ФАКТ» → план, "
            "тот же бюджетный сценарий и статья ровно **«ФАКТ»** → факт. "
            "Если в MSP есть «budget plan» / «budget fact», для БДДС они могут не использоваться, пока задана выгрузка 1С. "
            "Месяцы с нулевым планом при ненулевом факте означают, что в JSON за этот период нет строк плана по этим правилам."
        )
    if bool(a.get("bddds_plan_imputed_ratio")):
        hints.append(
            "Для части месяцев в выгрузке есть только сценарий «ФАКТ» без строк «ПЛАН». "
            "Столбец «План» для таких месяцев оценён как «Факт» × (Σплан/Σфакт) по месяцам с заполненными планом и фактом "
            "(коэффициент по проекту, при недостатке данных — общий по выборке)."
        )
    return _dedupe_preserve(hints)


def collect_bdr_hints(attrs: dict[str, Any] | None) -> list[str]:
    """Флаги из attrs синтетического БДР (`finance_from_1c.try_synthetic_bdr_from_1c_dannye`)."""
    a = attrs or {}
    hints: list[str] = []
    if not bool(a.get("data_source_1c_synthetic_bdr")):
        return hints
    hints.append(
        "БДР построен из оборотов 1С: проверьте наличие периода, сценария, суммы и явной маркировки статей БДР в выгрузке."
    )
    if bool(a.get("bdr_approx_no_bdr_marker")):
        hints.append(
            "В выгрузке не найдена явная маркировка статей БДР (например «(БДР)» в статье оборотов или типе статьи БДР). "
            "Для достоверного отчёта в 1С нужно явно размечать статьи БДР."
        )
    if bool(a.get("bdr_synthetic_rd_column")):
        hints.append(
            "Колонка «РасходДоход» отсутствует в выгрузке: расход определён по эвристике. Задайте колонку направления движения в 1С."
        )
    if bool(a.get("bdr_scenario_unsplit_all_to_fact")):
        hints.append(
            "Не удалось разделить строки на план и факт по сценарию по правилам ТЗ — суммы отнесены к фактическим расходам."
        )
    if bool(a.get("bdr_synthetic_split_by_msp_dims")):
        hints.append(
            "Суммы БДР из 1С без разреза по лоту/этапу распределены по комбинациям из MSP поровну — при фильтрах по лоту/этапу это оценка."
        )
    return _dedupe_preserve(hints)


def collect_forecast_bddcs_hints(attrs: dict[str, Any] | None) -> list[str]:
    """Подстановка план/факт из 1С на экране прогнозного БДДС (`_forecast_merge_bddcs_from_1c`)."""
    a = attrs or {}
    hints: list[str] = []
    if bool(a.get("forecast_bddcs_injected_from_1c")):
        hints.append(
            "Утверждённые суммы БДДС план/факт по проекту подставлены из оборотов 1С (без БДР) и распределены по строкам лотов "
            "пропорционально полю «budget plan» в MSP для этого проекта."
        )
    if bool(a.get("forecast_bddcs_uniform_lot_weights")):
        hints.append(
            "Сумма «budget plan» по строкам MSP для проекта была нулевой — суммы из 1С распределены по лотам **поровну**; это приближение."
        )
    return _dedupe_preserve(hints)


def collect_project_schedule_hints(
    *,
    only_finish_delay_active: bool,
    is_covenants: bool,
    base_end_column_present: bool,
    base_end_filled_ratio: float | None,
) -> list[str]:
    """Дашборд «График проекта» / MSP: фильтр просрочки по базовому окончанию."""
    hints: list[str] = []
    if is_covenants or not only_finish_delay_active:
        return _dedupe_preserve(hints)
    if not base_end_column_present:
        hints.append(
            "Фильтр «только просрочка по окончанию» по ТЗ опирается на колонку «base end» (базовое окончание). "
            "В текущей MSP-выгрузке её нет — отбор по просрочке не применён; добавьте базовый план в файл или снимите фильтр."
        )
        return _dedupe_preserve(hints)
    if base_end_filled_ratio is not None and base_end_filled_ratio < 0.15:
        pct = int(max(0, min(100, round(base_end_filled_ratio * 100))))
        hints.append(
            f"Базовое окончание заполнено лишь у ~{pct}% строк — при включённом фильтре просрочки график может быть почти пустым."
        )
    return _dedupe_preserve(hints)


def collect_developer_projects_hints(
    ss: Any,
    mdf: Any | None,
) -> list[str]:
    """
    Дашборд «Девелоперские проекты»: обороты 1С для «Выборка ДС», TESSA для предписаний.
    """
    hints: list[str] = []
    if mdf is None or getattr(mdf, "empty", True):
        return _dedupe_preserve(hints)
    try:
        from dashboards.dev_projects_tz_matrix import _bddds_df_for_dev_matrix

        pd_obj = ss.get("project_data") if hasattr(ss, "get") else None
        bd = _bddds_df_for_dev_matrix(mdf, pd_obj, ss)
        if bd is None:
            hints.append(
                "Строка «Выборка ДС, млн руб.»: не найдены обороты 1С для выбранного проекта "
                "(`reference_1c_dannye` или `project_data` со столбцом «Сценарий»). По ТЗ источник — отчёт оборотов по бюджетам; без выгрузки отображается Н/Д."
            )
    except Exception:
        pass
    tdf = ss.get("tessa_tasks_data") if hasattr(ss, "get") else None
    if tdf is None or getattr(tdf, "empty", True):
        hints.append(
            "Блок «ПРЕДПИСАНИЯ»: не загружен набор TESSA (`tessa_tasks_data`). При отсутствии файла счётчики и сроки могут быть Н/Д или опираться на строки MSP с «Предписан» в фазе/названии."
        )
    return _dedupe_preserve(hints)


def render_quality_hints(hints: list[str]) -> None:
    import streamlit as st

    h = _dedupe_preserve(hints)
    if not h:
        return
    if len(h) == 1:
        st.warning(h[0])
    else:
        st.warning("\n\n".join(h))
