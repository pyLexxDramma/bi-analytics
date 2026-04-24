"""
etl/parser.py — определение типа файла и даты среза по имени.

Соглашение об именах:
  msp_{project}_{DD-MM-YYYY}.csv           → тип 'msp',       дата среза из имени
  1с_{DD-MM-YYYY}_{HH-MM}_{suffix}.json   → тип '1c_budget' / '1c_dk' / '1c_sprav'
  tessa_{DD-MM-YYYY}_{HH-MM}_{suffix}.csv → тип 'tessa_rd' / 'tessa_id' / 'tessa_task'
  other_{project}_{DD-MM-YYYY|DD.MM.YYYY}_rd.csv → 'rd_plan', проект (без даты)
  other_{DD-MM-YYYY}_resursi.csv          → тип 'resources'
  KrStates.csv / DocStates.csv / UI_Tasks.csv → тип 'reference'
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Регулярки для разбора имён файлов ────────────────────────────────────────

_DATE_DDMMYYYY = re.compile(r"(\d{2})[-_](\d{2})[-_](\d{4})")      # 02-03-2026 или 02_03_2026
_DATE_DDMMYYYY_DOT = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")       # 02.03.2026
_DATE_YYYYMMDD = re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})")       # 2026-03-02

# Маппинг суффиксов → тип 1С
_1C_SUFFIX_MAP = {
    "dannye":       "1c_budget",
    "данные":       "1c_budget",
    "dk":           "1c_dk",
    "дк":           "1c_dk",
    "spravochniki": "1c_sprav",
    "справочники":  "1c_sprav",
}

# Маппинг суффиксов TESSA → тип
_TESSA_SUFFIX_MAP = {
    "rd":    "tessa_rd",
    "id":    "tessa_id",
    "task":  "tessa_task",
    "tasks": "tessa_task",
}

# Статические справочники
_REFERENCE_FILES = {"krstates", "docstates", "ui_tasks"}


def _is_1c_json_name(name_lower: str) -> bool:
    """1c_ / 1C_ / 1с_ / 1С_ (вторая буква — лат. c или кирил. с, как в фактических выгрузках)."""
    if not name_lower.startswith("1") or len(name_lower) < 2:
        return False
    return name_lower[1] in ("c", "C", "с", "С")


def _parse_date(name_lower: str) -> Optional[str]:
    """Извлекает дату среза из имени файла, возвращает ISO YYYY-MM-DD или None."""
    # Пробуем DD-MM-YYYY / DD_MM_YYYY
    m = _DATE_DDMMYYYY.search(name_lower)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # Пробуем YYYY-MM-DD
    m = _DATE_YYYYMMDD.search(name_lower)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # Пробуем DD.MM.YYYY
    m = _DATE_DDMMYYYY_DOT.search(name_lower)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _extract_project_from_msp(name_lower: str) -> str:
    """
    msp_dmitrovsky1_02-03-2026 → 'dmitrovsky1'
    msp_esipovo5_16-03-2026    → 'esipovo5'
    msp_leninsky_30-03-2026    → 'leninsky'
    """
    # Убираем 'msp_' в начале
    tail = re.sub(r"^msp_", "", name_lower)
    # Убираем дату и расширение с конца
    tail = _DATE_DDMMYYYY.sub("", tail)
    tail = _DATE_YYYYMMDD.sub("", tail)
    tail = re.sub(r"\.csv$", "", tail)
    tail = tail.strip("_- ")
    return tail or "unknown"


def _extract_project_from_rd(name_lower: str) -> str:
    """
    other_dmitrovsky1_01_04_2025_rd  → 'dmitrovsky1'
    other_dmitrovsky1_01.04.2025_rd  → 'dmitrovsky1'  (дата с точками, как в web/AI)
    other_leninsky_01_04_2025_rd     → 'leninsky'
    """
    tail = re.sub(r"^other_", "", name_lower, flags=re.IGNORECASE)
    tail = re.sub(r"_rd(\.csv)?$", "", tail, flags=re.IGNORECASE)
    tail = re.sub(r"\.csv$", "", tail, flags=re.IGNORECASE)
    # Все варианты даты в середине/конце: DD-MM-YYYY, DD.MM.YYYY, YYYY-MM-DD, DD_MM_YYYY
    tail = _DATE_DDMMYYYY.sub("", tail)
    tail = _DATE_DDMMYYYY_DOT.sub("", tail)
    tail = _DATE_YYYYMMDD.sub("", tail)
    tail = re.sub(r"_+", "_", tail)
    tail = tail.strip("_- .")
    return tail or "unknown"


def detect_file(path: Path) -> dict:
    """
    Определяет тип файла и метаданные.

    Возвращает:
    {
        "file_type": str,          # msp | 1c_budget | 1c_dk | 1c_sprav |
                                   # tessa_rd | tessa_id | tessa_task |
                                   # resources | rd_plan | reference | unknown
        "snapshot_date": str|None, # YYYY-MM-DD
        "project_name": str|None,  # для msp / rd_plan
        "path": Path,
        "name": str,
    }
    """
    name = path.name
    name_lower = name.lower()
    stem_lower = path.stem.lower()

    result = {
        "file_type": "unknown",
        "snapshot_date": _parse_date(stem_lower),
        "project_name": None,
        "path": path,
        "name": name,
    }

    # ── MSP ──────────────────────────────────────────────────────────────────
    if stem_lower.startswith("msp_") and name_lower.endswith(".csv"):
        result["file_type"] = "msp"
        result["project_name"] = _extract_project_from_msp(stem_lower)
        return result

    # ── 1С JSON ──────────────────────────────────────────────────────────────
    if name_lower.endswith(".json") and _is_1c_json_name(name_lower):
        # Суффикс — последняя часть имени после всех дат и цифр
        parts = re.split(r"[_\-]", stem_lower)
        for part in reversed(parts):
            clean = re.sub(r"[\d\.\:]", "", part).strip()
            if clean in _1C_SUFFIX_MAP:
                result["file_type"] = _1C_SUFFIX_MAP[clean]
                return result
        result["file_type"] = "1c_budget"  # дефолт
        return result

    # ── TESSA CSV ────────────────────────────────────────────────────────────
    if stem_lower.startswith("tessa_") and name_lower.endswith(".csv"):
        parts = re.split(r"[_\-]", stem_lower)
        for part in reversed(parts):
            if part in _TESSA_SUFFIX_MAP:
                result["file_type"] = _TESSA_SUFFIX_MAP[part]
                return result
        result["file_type"] = "tessa_rd"
        return result

    # ── Ресурсы (ГДРС) ───────────────────────────────────────────────────────
    if "resursi" in stem_lower or "ресурс" in stem_lower:
        result["file_type"] = "resources"
        return result

    # ── Плановая выдача РД ───────────────────────────────────────────────────
    if stem_lower.startswith("other_") and stem_lower.endswith("_rd"):
        result["file_type"] = "rd_plan"
        result["project_name"] = _extract_project_from_rd(stem_lower)
        return result

    # ── Статические справочники ───────────────────────────────────────────────
    if stem_lower in _REFERENCE_FILES:
        result["file_type"] = "reference"
        result["snapshot_date"] = None
        return result

    return result


def scan_web_dir(web_dir: Path) -> list[dict]:
    """
    Рекурсивно сканирует папку web/ и возвращает метаданные всех файлов.
    Игнорирует скрытые файлы и __pycache__.
    """
    if not web_dir.exists():
        return []

    results = []
    for path in sorted(web_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith(".") or "__pycache__" in str(path):
            continue
        if path.suffix.lower() not in {".csv", ".json"}:
            continue
        meta = detect_file(path)
        meta["rel_path"] = str(path.relative_to(web_dir))
        results.append(meta)

    return results


def group_by_snapshot(file_metas: list[dict]) -> dict[str, list[dict]]:
    """
    Группирует файлы по дате среза.
    Файлы без даты (справочники) попадают в ключ '__reference__'.
    Файлы с неизвестной датой — в '__unknown__'.
    """
    groups: dict[str, list[dict]] = {}
    for meta in file_metas:
        key = meta["snapshot_date"] or (
            "__reference__" if meta["file_type"] == "reference" else "__unknown__"
        )
        groups.setdefault(key, []).append(meta)
    return groups
