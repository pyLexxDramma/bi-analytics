"""Генерация и выбор PNG по смыслу запроса пользователя (не все пути из ответа ИИ)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from workspace_paths import extract_image_path_tokens, normalize_path_token, resolve_workspace_media_path

_ANALYTICS_DIR = Path(__file__).resolve().parent
_FINANCE_OUTPUT = "/workspace/analytics/output/db_finance_plan_fact"
_DEVIATIONS_OUTPUT = "/workspace/analytics/output/db_deviations_chat"

CHART_SCRIPT_BY_BASENAME: dict[str, str] = {
    "plan_fact_by_project.png": "analyze_db_finance_plan_fact.py",
    "plan_fact_bddds_monthly.png": "analyze_db_finance_plan_fact.py",
    "deviations_reasons_for_chat_pie.png": "analyze_db_deviations_for_chat.py",
}

OUTPUT_DIR_ALIASES: dict[str, str] = {
    "db_deviations_for_chat": "db_deviations_chat",
}


def query_requests_analytics_charts(user_message: str) -> bool:
    """PNG только для явного запроса данных/графика, не для «привет» и small talk."""
    lowered = str(user_message or "").lower().strip()
    if not lowered:
        return False
    short_greeting = len(lowered) <= 48 and any(
        token in lowered
        for token in ("привет", "здравств", "hello", "добрый", "доброе", "hi ", "hey")
    )
    if short_greeting:
        return False
    chart_markers = (
        "диаграм",
        "график",
        "chart",
        "png",
        "план/факт",
        "план-факт",
        "бддс",
        "bdds",
        "утвержден",
        "утверждён",
    )
    data_markers = (
        "бюджет",
        "освоен",
        "факт",
        "план",
        "руб",
        "₽",
        "отклонен",
        "отставан",
        "задерж",
        "средств",
        "выгруз",
        "анализ",
        "сравни",
        "топ ",
        "подрядчик",
        "предписан",
        "просроч",
        "msp",
        "бддс",
        "bdds",
        "динамик",
        "недоосвоен",
        "перерасход",
    )
    if any(marker in lowered for marker in chart_markers):
        return True
    return sum(1 for marker in data_markers if marker in lowered) >= 2


def infer_chart_basenames_for_query(user_message: str) -> list[str]:
    """
    Какой PNG соответствует вопросу (см. KNOWLEDGE_BASE / AI_DATA_RULES).
    Без явного data/chart-запроса — пустой список (не подставлять plan_fact на «привет»).
    """
    if not query_requests_analytics_charts(user_message):
        return []
    lowered = str(user_message or "").lower()
    if any(marker in lowered for marker in ("причин", "отклонен", "msp", "просроч", "срок")) and not any(
        marker in lowered for marker in ("бюджет", "план", "факт", "руб", "₽", "бддс", "освоен")
    ):
        return ["deviations_reasons_for_chat_pie.png"]

    monthly_markers = ("бддс", "bdds", "по месяц", "ежемесяч", "динамик по месяц", "monthly", "месяцам")
    project_markers = (
        "по проект",
        "проект",
        "утвержден",
        "утверждён",
        "план/факт",
        "план-факт",
        "диаграмм",
        "график",
        "бюджет",
    )
    wants_monthly = any(marker in lowered for marker in monthly_markers)
    wants_project = any(marker in lowered for marker in project_markers)

    if wants_monthly and not wants_project:
        return ["plan_fact_bddds_monthly.png"]
    if wants_project or wants_monthly:
        return ["plan_fact_by_project.png"]
    return []


def _output_dir_for_basename(basename: str) -> str:
    if basename.startswith("deviations"):
        return _DEVIATIONS_OUTPUT
    return _FINANCE_OUTPUT


def _run_chart_script(script_name: str) -> bool:
    script_path = _ANALYTICS_DIR / script_name
    if not script_path.is_file():
        return False
    try:
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(_ANALYTICS_DIR),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _token_variants(token: str) -> list[str]:
    normalized = normalize_path_token(token)
    if not normalized:
        return []
    variants = [normalized]
    for wrong, right in OUTPUT_DIR_ALIASES.items():
        if f"/{wrong}/" in normalized:
            variants.append(normalized.replace(f"/{wrong}/", f"/{right}/"))
    return variants


def materialize_chart_token(token: str, *, allow_run_script: bool = True) -> Path | None:
    for variant in _token_variants(token):
        found = resolve_workspace_media_path(variant)
        if found is not None:
            return found

    if not allow_run_script:
        return None

    basename = Path(normalize_path_token(token)).name
    script_name = CHART_SCRIPT_BY_BASENAME.get(basename)
    if not script_name:
        return None

    if not _run_chart_script(script_name):
        return None

    for variant in _token_variants(token):
        found = resolve_workspace_media_path(variant)
        if found is not None:
            return found
    return None


def materialize_charts_from_hints(
    hinted_tokens: list[str] | None,
    *,
    allow_run_script: bool = False,
) -> list[Path]:
    """
    Только PNG, которые модель явно указала в ответе (path_hints / строка с .png).
    Без автоподстановки plan_fact_by_project.png для каждого запроса.
    """
    resolved: list[Path] = []
    seen: set[str] = set()
    for raw in hinted_tokens or []:
        normalized = normalize_path_token(raw)
        if not normalized or not normalized.lower().endswith(".png"):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        path = materialize_chart_token(normalized, allow_run_script=allow_run_script)
        if path is not None and path not in resolved:
            resolved.append(path)
    return resolved


def materialize_charts_for_query(
    user_message: str,
    hinted_tokens: list[str] | None = None,
    *,
    allow_run_script: bool = False,
) -> list[Path]:
    """
    Сначала пути из ответа ИИ; иначе — только если запрос явно про график и файл уже есть.
    Не запускает finance-скрипт «на всякий случай».
    """
    hinted = [str(token) for token in (hinted_tokens or []) if token]
    from_hints = materialize_charts_from_hints(hinted, allow_run_script=allow_run_script)
    if from_hints:
        return from_hints

    if allow_run_script:
        preferred = infer_chart_basenames_for_query(user_message)
        resolved: list[Path] = []
        seen: set[str] = set()
        for basename in preferred:
            token = f"{_output_dir_for_basename(basename)}/{basename}"
            key = normalize_path_token(token)
            if not key or key in seen:
                continue
            seen.add(key)
            path = materialize_chart_token(token, allow_run_script=True)
            if path is not None:
                resolved.append(path)
        return resolved

    preferred = infer_chart_basenames_for_query(user_message)
    resolved = []
    for basename in preferred:
        token = f"{_output_dir_for_basename(basename)}/{basename}"
        path = materialize_chart_token(token, allow_run_script=False)
        if path is not None:
            resolved.append(path)
    return resolved


def materialize_charts_from_text(text: str, *, allow_run_script: bool = True) -> list[Path]:
    """Устаревший путь: без user_message берёт все PNG из текста. Предпочтите materialize_charts_for_query."""
    seen: set[str] = set()
    resolved: list[Path] = []
    for token in extract_image_path_tokens(text):
        key = normalize_path_token(token)
        if not key or key in seen:
            continue
        seen.add(key)
        path = materialize_chart_token(token, allow_run_script=allow_run_script)
        if path is not None:
            resolved.append(path)
    return resolved
