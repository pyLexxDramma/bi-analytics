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
            "Бюджет план/факт построен из оборотов 1С (`*_dannye.json`), потому что в MSP нет "
            "заполненных полей «budget plan» / «budget fact». Для корректного разделения план/факт "
            "нужны колонки «Сценарий» и «Сумма»; по ТЗ для факта — бюджетный сценарий и статья оборотов «ФАКТ»."
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


def render_quality_hints(hints: list[str]) -> None:
    import streamlit as st

    h = _dedupe_preserve(hints)
    if not h:
        return
    if len(h) == 1:
        st.warning(h[0])
    else:
        st.warning("\n\n".join(h))
