from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from collections import Counter

import pandas as pd
import streamlit as st


REPORT_JSON = Path(__file__).resolve().parent / "data_health_report.json"
REPORT_MD = Path(__file__).resolve().parent / "data_health_report.md"


def _df(x: Any) -> pd.DataFrame | None:
    return x if isinstance(x, pd.DataFrame) and not x.empty else None


def _cols(df: pd.DataFrame | None) -> set[str]:
    if df is None:
        return set()
    return {str(c).strip().casefold() for c in df.columns}


def _has_any(cols: set[str], needles: tuple[str, ...]) -> bool:
    for c in cols:
        for n in needles:
            if n.casefold() in c:
                return True
    return False


def _row(report: list[dict[str, str]], dashboard: str, level: str, required: str, issue: str) -> None:
    report.append(
        {
            "dashboard": dashboard,
            "level": level,  # ok/warn/err
            "required": required,
            "issue": issue,
        }
    )


def _collect_file_checks(load_result: dict[str, Any] | None) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    diags = (load_result or {}).get("diagnostics") or []
    if not isinstance(diags, list):
        diags = []

    def _hint_for(target: str, level: str) -> str:
        if str(level).lower() != "err":
            return ""
        t = str(target).lower()
        if "1c dannye" in t:
            return "Положите `*_dannye.json` (UTF-8, массив объектов) с полями Сценарий/Сумма/Период."
        if "tessa task" in t:
            return "Положите `tessa_*_task.csv` (разделитель `;` или `,`) с CardID и полями статуса задачи."
        if "tessa id/rd" in t:
            return "Положите `tessa_*_id.csv` и/или `tessa_*_rd.csv` с DocID."
        if "resources" in t:
            return "Положите `other_*_resursi.csv` с корректной шапкой дат."
        if "msp" in t:
            return "Положите `msp_*.csv` (MSP экспорт) с задачами и датами."
        if "1c dk" in t:
            return "Положите `*_DK.json` (UTF-8, массив) с блоками Организация/Контрагент/Договор."
        return "Нужно добавить файл требуемого типа в `web/` и повторить загрузку."

    def _add(level: str, target: str, issue: str) -> None:
        checks.append({"level": level, "target": target, "issue": issue, "hint": _hint_for(target, level)})

    if not diags:
        # Fallback: берем данные из session_state.loaded_files_info, чтобы не терять
        # проверку после rerun/переключения версии.
        lfi = st.session_state.get("loaded_files_info") or {}
        if isinstance(lfi, dict) and lfi:
            for file_id, info in lfi.items():
                diags.append(
                    {
                        "file": str(file_id),
                        "type": str((info or {}).get("type", "unknown")),
                        "rows": int((info or {}).get("rows", 0) or 0),
                        "columns": [str(c) for c in ((info or {}).get("columns") or [])],
                    }
                )
        if not diags:
            # Второй fallback: проверка по текущим объектам в session_state.
            session_map = {
                "project": st.session_state.get("project_data"),
                "resources": st.session_state.get("resources_data"),
                "tessa": st.session_state.get("tessa_data"),
                "tessa_tasks": st.session_state.get("tessa_tasks_data"),
                "debit_credit": st.session_state.get("debit_credit_data"),
                "reference_dannye": st.session_state.get("reference_1c_dannye"),
            }
            for tp, obj in session_map.items():
                if isinstance(obj, pd.DataFrame) and not obj.empty:
                    diags.append(
                        {
                            "file": f"session:{tp}",
                            "type": tp,
                            "rows": int(len(obj)),
                            "columns": [str(c) for c in obj.columns],
                        }
                    )
            if not diags:
                _add("warn", "Загрузка", "Нет diagnostics, loaded_files_info и активных DataFrame в session_state.")
                return checks

    type_to_items: dict[str, list[dict[str, Any]]] = {}
    for d in diags:
        t = str((d or {}).get("type", "unknown"))
        type_to_items.setdefault(t, []).append(d or {})

    def _has_type(*types: str) -> bool:
        return any(t in type_to_items for t in types)

    def _type_cols(t: str) -> set[str]:
        cols: set[str] = set()
        for it in type_to_items.get(t, []):
            for c in (it.get("columns") or []):
                cols.add(str(c).casefold())
        return cols

    # Files existence checks
    _add("ok" if _has_type("project") else "err", "MSP", "Найден msp/project csv." if _has_type("project") else "Не найден MSP (project csv).")
    _add("ok" if _has_type("resources") else "err", "Resources", "Найден resources csv." if _has_type("resources") else "Не найден resources csv.")
    _add("ok" if _has_type("tessa") else "err", "TESSA id/rd", "Найдены tessa csv." if _has_type("tessa") else "Не найдены tessa id/rd csv.")
    _add("ok" if _has_type("tessa_tasks") else "err", "TESSA task", "Найдены tessa task csv." if _has_type("tessa_tasks") else "Не найден tessa_*_task.csv.")
    _add("ok" if _has_type("debit_credit") else "err", "1C DK", "Найден DK json." if _has_type("debit_credit") else "Не найден *_DK.json.")
    _add("ok" if _has_type("reference_dannye") else "err", "1C dannye", "Найден dannye json." if _has_type("reference_dannye") else "Не найден *_dannye.json.")

    # Column checks by parsed diagnostics
    pcols = _type_cols("project")
    if pcols:
        need = {
            "task name": ("task name", "название"),
            "plan end": ("plan end", "окончание"),
            "base end": ("base end", "базовое"),
            "reason of deviation": ("reason of deviation", "причины"),
        }
        for label, alts in need.items():
            ok = any(any(a in c for a in alts) for c in pcols)
            _add("ok" if ok else "warn", f"MSP column: {label}", "Колонка найдена." if ok else "Колонка не найдена/не распознана.")

    tcols = _type_cols("tessa")
    if tcols:
        has_doc = any(("docid" in c) or ("doc id" in c) for c in tcols)
        _add("ok" if has_doc else "warn", "TESSA column: DocID", "DocID найден." if has_doc else "DocID не найден.")
    ttcols = _type_cols("tessa_tasks")
    if ttcols:
        has_card = any(("cardid" in c) or ("card id" in c) for c in ttcols)
        _add("ok" if has_card else "warn", "TESSA task column: CardID", "CardID найден." if has_card else "CardID не найден.")
    dcols = _type_cols("reference_dannye")
    if dcols:
        has_scen = any(("сценар" in c) or ("scenario" in c) for c in dcols)
        has_sum = any(("сумм" in c) or ("amount" in c) for c in dcols)
        _add("ok" if has_scen else "warn", "1C dannye column: Сценарий", "Сценарий найден." if has_scen else "Сценарий не найден.")
        _add("ok" if has_sum else "warn", "1C dannye column: Сумма", "Сумма найдена." if has_sum else "Сумма не найдена.")

    return checks


def build_schema_health_report(load_result: dict[str, Any] | None = None) -> dict[str, Any]:
    project = _df(st.session_state.get("project_data"))
    resources = _df(st.session_state.get("resources_data"))
    tessa = _df(st.session_state.get("tessa_data"))
    tessa_task = _df(st.session_state.get("tessa_tasks_data"))
    dk = _df(st.session_state.get("debit_credit_data"))
    d1c = _df(st.session_state.get("reference_1c_dannye"))
    kr = _df(st.session_state.get("reference_krstates"))

    pcols, dcols, c1cols = (
        _cols(project),
        _cols(dk),
        _cols(d1c),
    )
    rows: list[dict[str, str]] = []

    # MSP timelines
    if project is None:
        for n in ("Причины отклонений", "Отклонение от базового плана", "Контрольные точки", "График проекта"):
            _row(rows, n, "err", "msp_*.csv", "Нет project_data (MSP не загружен).")
    else:
        _row(rows, "Причины отклонений", "ok" if _has_any(pcols, ("reason of deviation", "причины")) else "warn",
             "Колонка причины", "Проверьте наличие колонки причин отклонений.")
        _row(rows, "Отклонение от базового плана", "ok" if _has_any(pcols, ("base end", "базовое окончание")) and _has_any(pcols, ("plan end", "окончание")) else "warn",
             "base/plan end", "Нужны плановые и базовые даты.")
        _row(rows, "Контрольные точки", "ok", "MSP задачи КТ", "Если пусто — чаще логика отбора задач.")
        _row(rows, "График проекта", "ok", "MSP даты", "Если пусто — проверить фильтры/иерархию.")

    # Finance
    has_msp_budget = project is not None and _has_any(pcols, ("budget plan",)) and _has_any(pcols, ("budget fact",))
    has_1c_budget = d1c is not None and _has_any(c1cols, ("сценар", "scenario")) and _has_any(c1cols, ("сумм", "amount"))
    lvl = "ok" if (has_msp_budget or has_1c_budget) else "err"
    msg = "Нет budget plan/fact в MSP и нет Сценарий+Сумма в *_dannye.json." if lvl == "err" else "Источник сумм найден."
    for n in ("БДДС", "Бюджет по лотам", "БДР", "Бюджет план/факт", "Утвержденный бюджет", "Прогнозный бюджет"):
        _row(rows, n, lvl, "MSP budget_* или 1C dannye", msg)

    # DK
    _row(
        rows,
        "Дебиторская и кредиторская задолженность подрядчиков",
        "ok" if dk is not None and _has_any(dcols, ("контрагент", "договор", "остаток")) else ("warn" if dk is not None else "err"),
        "*_DK.json",
        "Если warn/err — проверьте структуру JSON: Организация/Контрагент/Договор + суммы.",
    )

    # Docs / TESSA
    _row(rows, "Исполнительная документация", "ok" if tessa is not None else "err", "tessa_*_id/rd + KrStates",
         "Нет tessa_data." if tessa is None else ("KrStates пуст, статусы могут быть сырыми." if kr is None else "Источник есть."))
    _row(rows, "Неустраненные предписания", "ok" if (tessa is not None and tessa_task is not None) else "err", "tessa_*_id + tessa_*_task",
         "Нужна пара документов и задач TESSA.")
    _row(rows, "Просрочка выдачи РД", "ok" if (project is not None and tessa is not None) else "warn", "MSP + TESSA rd + rd_plan",
         "Проверьте связку ключей проект/шифр/раздел.")
    _row(rows, "Просрочка выдачи ПД", "ok" if project is not None else "err", "MSP ПД", "Нужен MSP с задачами ПД.")

    # GDRS
    _row(
        rows,
        "ГДРС",
        "ok" if resources is not None else "err",
        "other_*_resursi.csv",
        "Источник resources_data загружен." if resources is not None else "Нет resources_data.",
    )
    _row(
        rows,
        "ГДРС Техника",
        "ok" if resources is not None else "err",
        "other_*_resursi.csv",
        "Источник resources_data загружен." if resources is not None else "Нет resources_data.",
    )
    # BRD gaps
    _row(rows, "Интеграция по ТЗ", "warn", "Dogovors/Partners/Projekts JSON", "В текущей поставке обычно отсутствуют; без них часть BRD-сценариев неполная.")

    data = {
        "summary": {
            "project_rows": 0 if project is None else int(len(project)),
            "resources_rows": 0 if resources is None else int(len(resources)),
            "tessa_rows": 0 if tessa is None else int(len(tessa)),
            "tessa_task_rows": 0 if tessa_task is None else int(len(tessa_task)),
            "dk_rows": 0 if dk is None else int(len(dk)),
            "dannye_rows": 0 if d1c is None else int(len(d1c)),
        },
        "rows": rows,
        "file_checks": _collect_file_checks(load_result),
    }
    return data


def save_schema_health_report(data: dict[str, Any] | None = None, load_result: dict[str, Any] | None = None) -> dict[str, Any]:
    report = data or build_schema_health_report(load_result=load_result)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Data Health Report", "", "## Summary", ""]
    for k, v in report.get("summary", {}).items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Dashboards", "", "| dashboard | level | required | issue |", "|---|---|---|---|"]
    for r in report.get("rows", []):
        lines.append(f"| {r['dashboard']} | {r['level']} | {r['required']} | {r['issue']} |")
    checks = report.get("file_checks") or []
    if checks:
        lines += ["", "## File / Column Checks", "", "| level | target | issue | what to add/fix |", "|---|---|---|---|"]
        for c in checks:
            lines.append(f"| {c['level']} | {c['target']} | {c['issue']} | {c.get('hint', '')} |")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def build_environment_fingerprint(load_result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Снимок окружения/источников, чтобы сравнивать local vs deploy."""
    from config import ignore_demo_data_files
    from web_loader import _iter_web_scan_roots

    roots = []
    try:
        for p, prefix in _iter_web_scan_roots():
            roots.append({"path": str(p), "prefix": str(prefix)})
    except Exception:
        pass

    active_version = st.session_state.get("web_version_id")
    diags = (load_result or {}).get("diagnostics") or []
    if not diags:
        lfi = st.session_state.get("loaded_files_info") or {}
        if isinstance(lfi, dict):
            diags = [
                {"type": (v or {}).get("type", "unknown"), "rows": int((v or {}).get("rows", 0) or 0)}
                for _, v in lfi.items()
            ]
    c_types = Counter(str((d or {}).get("type", "unknown")) for d in diags)
    total_rows = 0
    for d in diags:
        try:
            total_rows += int((d or {}).get("rows", 0) or 0)
        except Exception:
            pass
    return {
        "active_web_version_id": active_version,
        "ignore_demo_mode": bool(ignore_demo_data_files()),
        "scan_roots": roots,
        "diagnostics_files_count": len(diags),
        "diagnostics_total_rows": total_rows,
        "diagnostics_types": dict(c_types),
    }
