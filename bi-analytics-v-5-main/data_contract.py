# -*- coding: utf-8 -*-
"""
Жёсткая проверка «контракта» данных после загрузки из web/ или FTP→web.

Цель: если формат выгрузки не тот, клиент видит явные ошибки/подсказки; при включённом
режиме принуждения вызывающий код делает ``st.stop()`` после баннера.

Переменные окружения:
- ``BI_ANALYTICS_DATA_CONTRACT_STRICT=1|0`` — явно вкл/выкл остановку дашбордов при нарушении.
  Если не задано: используется флаг ``release_client_mode``, передаваемый из приложения.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import streamlit as st

from data_health import collect_contract_file_checks


def should_enforce_data_contract_stop(release_client_mode: bool = False) -> bool:
    """
    True — при ``not contract["ok"]`` после баннера выполняется ``st.stop()``.
    """
    raw = os.environ.get("BI_ANALYTICS_DATA_CONTRACT_STRICT", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return bool(release_client_mode)


def evaluate_data_contract(load_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Возвращает ``{"ok": bool, "blocking": [...], "warnings": [...]}``.

    Ошибки парсинга из ``load_result["errors"]`` учитываются только если
    ``version_id`` результата совпадает с активной версией в сессии.
    """
    blocking: List[str] = []
    warnings: List[str] = []

    lr = dict(load_result) if isinstance(load_result, dict) else {}
    cur_vid = st.session_state.get("web_version_id")
    lr_vid = lr.get("version_id")

    same_ver = True
    if cur_vid is not None and lr_vid is not None:
        try:
            same_ver = int(lr_vid) == int(cur_vid)
        except (TypeError, ValueError):
            same_ver = True

    lr_errors = [str(x) for x in (lr.get("errors") or []) if str(x).strip()]
    if lr_errors and same_ver:
        blocking.extend(lr_errors)

    try:
        loaded_n = int(lr.get("loaded") or 0)
    except (TypeError, ValueError):
        loaded_n = 0

    if (
        same_ver
        and lr
        and loaded_n == 0
        and not lr_errors
        and st.session_state.get("project_data") is None
    ):
        blocking.append(
            "Не загружен ни один распознанный файл в последней попытке чтения web/. "
            "Нужны выгрузки в оговорённом формате (msp_*.csv, *_dannye.json, tessa_*.csv, *_DK.json, resources)."
        )

    for w in (lr.get("warnings") or [])[:24]:
        ws = str(w).strip()
        if ws:
            warnings.append(ws)

    try:
        checks = collect_contract_file_checks(lr)
    except Exception as exc:
        warnings.append(f"Внутренняя ошибка проверки файлов: {exc}")
        checks = []

    for chk in checks:
        lvl = str(chk.get("level", "")).lower()
        tgt = str(chk.get("target", "") or "").strip()
        issue = str(chk.get("issue", "") or "").strip()
        hint = str(chk.get("hint", "") or "").strip()
        msg = f"[{tgt}] {issue}" if tgt else issue
        if hint:
            msg = f"{msg} — {hint}"
        if lvl == "err":
            blocking.append(msg)
        elif lvl == "warn":
            warnings.append(msg)

    seen_b = set()
    uniq_b = []
    for x in blocking:
        if x not in seen_b:
            seen_b.add(x)
            uniq_b.append(x)

    seen_w = set()
    uniq_w = []
    for x in warnings:
        if x not in seen_w:
            seen_w.add(x)
            uniq_w.append(x)

    ok = len(uniq_b) == 0
    return {"ok": ok, "blocking": uniq_b, "warnings": uniq_w}


def render_contract_banner(contract: Dict[str, Any]) -> None:
    """Крупный блок на главной панели: блокирующие ошибки и предупреждения."""
    if not contract:
        return
    blocking = contract.get("blocking") or []
    warns = contract.get("warnings") or []
    if contract.get("ok") and not warns:
        return

    with st.container(border=True):
        st.markdown("### Контракт данных для дашборда")
        st.caption(
            "Ниже перечислено, чего не хватает или что распознано с ошибкой. "
            "Исправьте выгрузки на стороне 1С / MSP / TESSA и повторите загрузку."
        )
        for msg in blocking[:40]:
            st.error(msg)
        for msg in warns[:30]:
            st.warning(msg)
        if contract.get("ok") and warns:
            st.success("Критичных нарушений контракта нет; есть предупреждения выше.")
