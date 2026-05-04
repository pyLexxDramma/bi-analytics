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

import html
import os
from typing import Any, Dict, List, Optional

import streamlit as st

from data_health import collect_contract_file_checks


def _is_informational_contract_warning(msg: str) -> bool:
    """
    Сообщения режима загрузки (не ошибка формата и не отсутствие данных для построения).
    Остаются в полном списке warnings у результата, но не поднимают баннер контракта.
    """
    s = str(msg).strip().lower()
    if not s:
        return True
    needles = (
        "режим последних снимков",
        "bi_analytics_web_latest_only",
        "bi_analytics_ignore_demo",
        "демо не подмешивается",
        "пропуск дубликата",
    )
    return any(n in s for n in needles)


def _render_contract_alert_lines(lines: List[str]) -> None:
    body = "\n\n".join(str(x).strip() for x in lines if str(x).strip())
    if not body:
        return
    safe = html.escape(body).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
    st.markdown(
        (
            '<div style="color:#ff2b2b;font-weight:600;line-height:1.45;padding:0.65rem 0.85rem;'
            "border:1px solid rgba(255,70,70,0.55);border-radius:0.45rem;"
            'background:rgba(255,60,60,0.08);">'
            f"{safe}</div>"
        ),
        unsafe_allow_html=True,
    )


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
    Возвращает ``{"ok": bool, "blocking": [...], "warnings": [...], "banner_warnings": [...]}``.
    В ``banner_warnings`` только сообщения, из‑за которых нужно показать баннер (без информационных про режим снимков и т.п.).

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

    banner_warnings = [w for w in uniq_w if not _is_informational_contract_warning(w)]

    ok = len(uniq_b) == 0
    return {
        "ok": ok,
        "blocking": uniq_b,
        "warnings": uniq_w,
        "banner_warnings": banner_warnings,
    }


def render_contract_banner(contract: Dict[str, Any]) -> None:
    """Баннер только при блокирующих ошибках или предупреждениях о данных/формате; единый красный акцент."""
    if not contract:
        return
    blocking = list(contract.get("blocking") or [])
    warns = list(contract.get("banner_warnings") or [])
    if not blocking and not warns:
        return

    lines: List[str] = []
    if blocking:
        lines.extend(blocking[:40])
    if warns:
        lines.extend(warns[:30])

    with st.container(border=True):
        st.markdown(
            '<p style="margin:0 0 0.35rem 0;font-size:1.15rem;font-weight:700;color:#ff2b2b;">'
            "Контракт данных для дашборда"
            "</p>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Перечислено только то, из‑за чего не загружены данные или распознан некорректный формат для отчётов. "
            "Исправьте выгрузки на стороне 1С / MSP / TESSA и повторите загрузку."
        )
        _render_contract_alert_lines(lines)
