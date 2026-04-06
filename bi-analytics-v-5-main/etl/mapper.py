"""
etl/mapper.py — чтение файлов и нормализация данных в унифицированный формат.

Каждая функция map_*() принимает Path и meta-dict, возвращает list[dict].
Все даты приводятся к ISO-строке YYYY-MM-DD (или None если не распознана).
"""

import csv
import json
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import chardet
import pandas as pd

log = logging.getLogger(__name__)


# ── Утилиты ──────────────────────────────────────────────────────────────────

def _read_csv_auto(path: Path, sep: str = ";", header: int = 0) -> pd.DataFrame:
    """Читает CSV с автоопределением кодировки."""
    with open(path, "rb") as f:
        raw = f.read(20000)
    enc = chardet.detect(raw).get("encoding") or "utf-8"
    # Fallback-цепочка кодировок
    for encoding in [enc, "windows-1251", "utf-8-sig", "utf-8"]:
        try:
            df = pd.read_csv(
                path, sep=sep, encoding=encoding, header=header,
                quoting=csv.QUOTE_MINIMAL, quotechar='"', doublequote=True,
                on_bad_lines="skip",
            )
            # Нормализуем колонки
            df.columns = [
                str(c).replace("\ufeff", "").replace("\n", " ").replace("\r", "").strip()
                for c in df.columns
            ]
            return df
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise ValueError(f"Не удалось прочитать файл: {path}")


def _parse_date(value) -> Optional[str]:
    """Приводит дату к ISO YYYY-MM-DD. Возвращает None если не распознана."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nat", "none", "nan", ""):
        return None
    # Форматы: DD.MM.YYYY  DD.MM.YY  YYYY-MM-DD  M/D/YYYY H:M:S AM/PM
    for fmt in (
        "%d.%m.%Y", "%d.%m.%y",
        "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S",
        "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y", "%d/%m/%Y",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Попытка через pandas
    try:
        return pd.to_datetime(s, dayfirst=True, errors="raise").strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_pct(value) -> Optional[float]:
    """'5%' → 5.0, '100' → 100.0"""
    if value is None:
        return None
    s = str(value).replace("%", "").replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _parse_duration_days(value) -> Optional[float]:
    """'244 д' → 244.0, '1218 д?' → 1218.0"""
    if value is None:
        return None
    s = str(value).strip()
    m = re.search(r"[\d]+(?:[.,]\d+)?", s.replace("\xa0", ""))
    if m:
        try:
            return float(m.group().replace(",", "."))
        except ValueError:
            return None
    return None


def _clean_amount(value) -> Optional[float]:
    """'25,861,200' → 25861200.0  '760.00' → 760.0"""
    if value is None:
        return None
    s = str(value).strip().replace(" ", "").replace("\xa0", "")
    # Удаляем тысячные запятые (американский формат): "25,861,200"
    # Если точка одна и она разделитель дробной части
    comma_count = s.count(",")
    dot_count = s.count(".")
    if comma_count > 1:
        s = s.replace(",", "")
    elif comma_count == 1 and dot_count == 0:
        # Может быть и "25,5" (дробный) и "25,861" (тысячный)
        parts = s.split(",")
        if len(parts[-1]) == 3 and len(parts) == 2 and len(parts[0]) <= 3:
            # Тысячный разделитель: "861,200"
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ── MSP ──────────────────────────────────────────────────────────────────────

# Маппинг колонок MSP → canonical name
_MSP_COL_MAP = {
    "Процент_завершения":    "pct_complete",
    "Базовая_длительность":  "base_duration",
    "Базовое_начало":        "base_start",
    "Базовое_окончание":     "base_finish",
    "Начало":                "start",
    "Окончание":             "finish",
    "Длительность":          "duration",
    "Причины_отклонений":    "deviation_reason",
    "Заметки":               "notes",
    "Уровень_структуры":     "level_structure",
    "БЛОК":                  "block",
    "Ид":                    "task_id",
    "Уникальный_идентификатор": "unique_id",
    "Предшественники":       "predecessors",
    "Последователи":         "successors",
    "Дата_ограничения":      "constraint_date",
    "Название":              "name",
    "ЛОТ":                   "lot",
    "ID_проекта":            "project_id",
    "Уровень":               "level",
    "Шифр_ПД_и_РД":          "cipher",
    "Режим_задачи":          "task_mode",
    "Тип":                   "task_type",
    "Календарь_задачи":      "calendar",
    "Отклонение_начала":     "deviation_start_days",
    "Отклонение_окончания":  "deviation_finish_days",
}


def map_msp(path: Path, meta: dict) -> list[dict]:
    """Читает MSP CSV и нормализует в список записей."""
    df = _read_csv_auto(path, sep=";")
    if df.empty:
        return []

    df = df.rename(columns={k: v for k, v in _MSP_COL_MAP.items() if k in df.columns})

    project_name = meta.get("project_name", "")
    snapshot_date = meta.get("snapshot_date", "")
    source_file = meta["name"]

    records = []
    for _, row in df.iterrows():
        r = {
            "snapshot_date":        snapshot_date,
            "project_name":         project_name,
            "source_file":          source_file,
            "project_id":           str(row.get("project_id", "") or "").strip(),
            "task_id":              str(row.get("task_id", "") or "").strip(),
            "unique_id":            str(row.get("unique_id", "") or "").strip(),
            "name":                 str(row.get("name", "") or "").strip(),
            "level_structure":      _safe_int(row.get("level_structure")),
            "level":                str(row.get("level", "") or "").strip(),
            "block":                str(row.get("block", "") or "").strip(),
            "lot":                  str(row.get("lot", "") or "").strip(),
            "task_type":            str(row.get("task_type", "") or "").strip(),
            "task_mode":            str(row.get("task_mode", "") or "").strip(),
            "calendar":             str(row.get("calendar", "") or "").strip(),
            "pct_complete":         _parse_pct(row.get("pct_complete")),
            "base_duration":        str(row.get("base_duration", "") or "").strip(),
            "duration":             str(row.get("duration", "") or "").strip(),
            "base_start":           _parse_date(row.get("base_start")),
            "base_finish":          _parse_date(row.get("base_finish")),
            "start":                _parse_date(row.get("start")),
            "finish":               _parse_date(row.get("finish")),
            "constraint_date":      _parse_date(row.get("constraint_date")),
            "predecessors":         str(row.get("predecessors", "") or "").strip(),
            "successors":           str(row.get("successors", "") or "").strip(),
            "deviation_reason":     str(row.get("deviation_reason", "") or "").strip(),
            "notes":                str(row.get("notes", "") or "").strip(),
            "cipher":               str(row.get("cipher", "") or "").strip(),
            "deviation_start_days": _safe_float(row.get("deviation_start_days")),
            "deviation_finish_days":_safe_float(row.get("deviation_finish_days")),
        }
        # Вычисляем отклонения если нет готовых колонок
        if r["deviation_finish_days"] is None and r["base_finish"] and r["finish"]:
            try:
                bd = datetime.strptime(r["base_finish"], "%Y-%m-%d")
                fd = datetime.strptime(r["finish"], "%Y-%m-%d")
                r["deviation_finish_days"] = (fd - bd).days
            except Exception:
                pass
        if r["deviation_start_days"] is None and r["base_start"] and r["start"]:
            try:
                bs = datetime.strptime(r["base_start"], "%Y-%m-%d")
                st = datetime.strptime(r["start"], "%Y-%m-%d")
                r["deviation_start_days"] = (st - bs).days
            except Exception:
                pass
        records.append(r)
    return records


# ── 1С БДДС / БДР ────────────────────────────────────────────────────────────

def map_1c_budget(path: Path, meta: dict) -> list[dict]:
    """Читает 1С dannye.json → список записей budget_1c."""
    records_raw = _load_json_tolerant(path)
    snapshot_date = meta.get("snapshot_date", "")
    source_file = meta["name"]

    records = []
    for item in records_raw:
        if not isinstance(item, dict):
            continue
        amount_raw = item.get("Сумма", "") or ""
        records.append({
            "snapshot_date":       snapshot_date,
            "period":              _parse_date(item.get("Период")),
            "registrar":           str(item.get("Регистратор", "") or "").strip(),
            "scenario":            str(item.get("Сценарий", "") or "").strip(),
            "cfo":                 str(item.get("ЦФО", "") or "").strip(),
            "article":             str(item.get("СтатьяОборотов", "") or "").strip(),
            "currency":            str(item.get("Валюта", "") or "").strip(),
            "contractor":          str(item.get("Контрагент", "") or "").strip(),
            "contractor_contract": str(item.get("ДоговорКонтрагента", "") or "").strip(),
            "project":             str(item.get("Проект", "") or "").strip(),
            "nomenclature_group":  str(item.get("НоменклатурнаяГруппа", "") or "").strip(),
            "bank_account":        str(item.get("БанковскийСчет", "") or "").strip(),
            "analytics_1":         str(item.get("Аналитика_1", "") or "").strip(),
            "organization":        str(item.get("Организация", "") or "").strip(),
            "amount":              _clean_amount(amount_raw),
            "flow_type":           str(item.get("РасходДоход", "") or "").strip(),
            "article_type":        str(item.get("ТипСтатьи", "") or "").strip(),
            "source_file":         source_file,
        })
    return records


# ── 1С ДЗ / КЗ ───────────────────────────────────────────────────────────────

def map_1c_dk(path: Path, meta: dict) -> list[dict]:
    """Читает 1С DK.json → список записей debit_credit_1c."""
    records_raw = _load_json_tolerant(path)
    snapshot_date = meta.get("snapshot_date", "")
    source_file = meta["name"]

    records = []
    for item in records_raw:
        if not isinstance(item, dict):
            continue
        org = item.get("Организация", {}) or {}
        contr = item.get("Контрагент", {}) or {}
        dog = item.get("Договор", {}) or {}
        amount_str = str(dog.get("СуммаДоговора", "") or "")
        records.append({
            "snapshot_date":             snapshot_date,
            "org_id":                    str(org.get("ID_Организации", "") or "").strip(),
            "org_name":                  str(org.get("НаименованиеОрганизации", "") or "").strip(),
            "contractor_id":             str(contr.get("ID_Контрагента", "") or "").strip(),
            "contractor_name":           str(contr.get("НаименованиеКонтрагента", "") or "").strip(),
            "contract_id":               str(dog.get("ID_Договора", "") or "").strip(),
            "contract_number":           str(dog.get("НомерДоговора", "") or "").strip(),
            "contract_date":             _parse_date(dog.get("ДатаДоговора")),
            "contract_amount":           amount_str.strip(),
            "contract_amount_clean":     _clean_amount(amount_str),
            "balance_start":             _safe_float(item.get("ОстатокНаНачало")),
            "balance_start_period":      _safe_float(item.get("ОстатокНаНачалоПериода")),
            "balance_start_period_adv":  _safe_float(item.get("ОстатокНаНачалоПериодаПоАвансам")),
            "total_payments":            _safe_float(item.get("ВсегоОплат")),
            "total_payments_adv":        _safe_float(item.get("ВсегоОплат_Аванс")),
            "balance_end":               _safe_float(item.get("ОстатокНаКонец")),
            "balance_end_period":        _safe_float(item.get("ОстатокНаКонецПериода")),
            "balance_end_period_adv":    _safe_float(item.get("ОстатокНаКонецПериодаПоАвансам")),
            "source_file":               source_file,
        })
    return records


# ── 1С Справочник контрагентов ────────────────────────────────────────────────

def map_1c_sprav(path: Path, meta: dict) -> list[dict]:
    """Читает 1С spravochniki.json → список записей contractors_1c."""
    records_raw = _load_json_tolerant(path)
    source_file = meta["name"]

    records = []
    for item in records_raw:
        if not isinstance(item, dict):
            continue
        records.append({
            "contractor_id":   str(item.get("ID_Контрагента", "") or "").strip(),
            "contractor_name": str(item.get("Наименование_Контрагента", "") or "").strip(),
            "inn":             str(item.get("ИНН_Контрагента", "") or "").strip(),
            "kpp":             str(item.get("КПП_Контрагента", "") or "").strip(),
            "source_file":     source_file,
        })
    return records


# ── TESSA РД ─────────────────────────────────────────────────────────────────

def map_tessa_rd(path: Path, meta: dict) -> list[dict]:
    df = _read_csv_auto(path, sep=";")
    if df.empty:
        return []

    snapshot_date = meta.get("snapshot_date", "")
    source_file = meta["name"]
    records = []
    for _, row in df.iterrows():
        records.append({
            "snapshot_date":          snapshot_date,
            "import_date":            _parse_date(row.get("import_data") or row.get("Import_date")),
            "doc_id":                 _str(row.get("DocID")),
            "doc_description":        _str(row.get("DocDescription")),
            "internal_id":            _str(row.get("InternalID")),
            "creation_date":          _parse_date(row.get("CreationDate")),
            "doc_number":             _str(row.get("DocNumber")),
            "kr_state":               _str(row.get("KrState")),
            "kr_state_ru":            "",   # заполняется при вставке
            "object_id":              _str(row.get("ObjectID")),
            "object_name":            _str(row.get("ObjectName")),
            "project_id":             _str(row.get("ObjectProjectID")),
            "project_name":           _str(row.get("ObjectProjectName")),
            "division_id":            _str(row.get("DivisionID")),
            "division_cipher":        _str(row.get("DivisionCipher")),
            "subdivision_version_id": _str(row.get("SubDivisionVersionID")),
            "subdivision_version":    _str(row.get("SubDivisionVersionName")),
            "contractor":             _str(row.get("CONTR")),
            "lot":                    _str(row.get("Lot")),
            "contractor_1c_id":       _str(row.get("1C_ID_CONTR")),
            "object_1c_id":           _str(row.get("1C_ID_OBJECT")),
            "source_file":            source_file,
        })
    return records


# ── TESSA ИД ─────────────────────────────────────────────────────────────────

def map_tessa_id(path: Path, meta: dict) -> list[dict]:
    df = _read_csv_auto(path, sep=";")
    if df.empty:
        return []

    snapshot_date = meta.get("snapshot_date", "")
    source_file = meta["name"]
    records = []
    for _, row in df.iterrows():
        records.append({
            "snapshot_date":  snapshot_date,
            "import_date":    _parse_date(row.get("Import_date") or row.get("import_date")),
            "doc_id":         _str(row.get("DocID")),
            "doc_description":_str(row.get("DocDescription")),
            "internal_id":    _str(row.get("InternalID")),
            "creation_date":  _parse_date(row.get("CreationDate")),
            "doc_number":     _str(row.get("DocNumber")),
            "kr_state":       _str(row.get("KrState")),
            "kr_state_id":    _safe_int(row.get("KrStateID")),
            "kr_state_ru":    "",
            "contractor_id":  _str(row.get("CONTRID")),
            "contractor_name":_str(row.get("CONTR")),
            "kind_id":        _str(row.get("KindID")),
            "kind_name":      _str(row.get("KindName")),
            "name":           _str(row.get("Name")),
            "object_id":      _str(row.get("ObjectID")),
            "object_name":    _str(row.get("ObjectName")),
            "lot":            _str(row.get("Lot")),
            "podr_1c_id":     _str(row.get("1C_ID_PODR")),
            "contr_1c_id":    _str(row.get("1C_ID_CONTR")),
            "source_file":    source_file,
        })
    return records


# ── TESSA Tasks ───────────────────────────────────────────────────────────────

def map_tessa_task(path: Path, meta: dict) -> list[dict]:
    df = _read_csv_auto(path, sep=";")
    if df.empty:
        return []

    snapshot_date = meta.get("snapshot_date", "")
    source_file = meta["name"]
    records = []
    for _, row in df.iterrows():
        records.append({
            "snapshot_date":    snapshot_date,
            "import_date":      _parse_date(row.get("imort_data") or row.get("import_data")),
            "card_id":          _str(row.get("CardID")),
            "card_name":        _str(row.get("CardName")),
            "card_type_caption":_str(row.get("CardTypeCaption")),
            "type_id":          _str(row.get("TypeID")),
            "type_caption":     _str(row.get("TypeCaption")),
            "option_id":        _str(row.get("OptionID")),
            "option_caption":   _str(row.get("OptionCaption")),
            "result":           _str(row.get("Result")),
            "role_id":          _str(row.get("RoleID")),
            "role_name":        _str(row.get("RoleName")),
            "author_id":        _str(row.get("AuthorID")),
            "author_name":      _str(row.get("AuthorName")),
            "completed":        _parse_date(row.get("Completed")),
            "rn":               _safe_int(row.get("rn")),
            "source_file":      source_file,
        })
    return records


# ── Ресурсы (ГДРС) ────────────────────────────────────────────────────────────

def map_resources(path: Path, meta: dict) -> list[dict]:
    """
    Читает other_*_resursi.csv — файл с двухуровневой шапкой.
    Строка 0: номера недель ("1 неделя", "", "", "2 неделя", ...)
    Строка 1: конкретные даты и "среднее значение за день"
    Строка 2+: данные (Проект, Подрядчик, тип ресурсов, значения...)
    """
    df_raw = _read_csv_auto(path, sep=";", header=None)
    if df_raw.empty or len(df_raw) < 3:
        return []

    snapshot_date = meta.get("snapshot_date", "")
    source_file = meta["name"]

    # Строим маппинг колонок
    week_row = df_raw.iloc[0].tolist()
    date_row = df_raw.iloc[1].tolist()

    current_week = ""
    col_meta = []   # list of (col_idx, period_label, date_str, col_type)
    for i, (w, d) in enumerate(zip(week_row, date_row)):
        ws = str(w).strip() if pd.notna(w) else ""
        ds = str(d).strip() if pd.notna(d) else ""
        if ws:
            current_week = ws
        if i < 3:
            # Первые 3 — Проект, Подрядчик, тип ресурсов
            col_meta.append((i, "", ds, "key"))
            continue
        if "среднее" in ds.lower() or "план" in ds.lower():
            col_meta.append((i, current_week, ds, "avg"))
        elif ds:
            col_meta.append((i, current_week, ds, "daily"))
        else:
            col_meta.append((i, current_week, ds, "skip"))

    records = []
    for row_idx in range(2, len(df_raw)):
        row = df_raw.iloc[row_idx].tolist()
        project = str(row[0]).strip() if pd.notna(row[0]) else ""
        contractor = str(row[1]).strip() if pd.notna(row[1]) else ""
        res_type = str(row[2]).strip() if pd.notna(row[2]) else ""

        if not project or project.lower() in ("nan", "", "none"):
            continue

        for (col_idx, period_label, date_str, col_type) in col_meta:
            if col_type in ("key", "skip"):
                continue
            if col_idx >= len(row):
                continue
            val = row[col_idx]
            val_clean = _safe_float(val)
            if val_clean is None:
                continue
            records.append({
                "snapshot_date":  snapshot_date,
                "period_label":   period_label,
                "date_col":       _parse_date(date_str) if col_type == "daily" else None,
                "project":        project,
                "contractor":     contractor,
                "resource_type":  res_type,
                "value":          val_clean,
                "col_type":       col_type,   # 'daily' / 'avg'
                "source_file":    source_file,
            })
    return records


# ── Плановая выдача РД ────────────────────────────────────────────────────────

def map_rd_plan(path: Path, meta: dict) -> list[dict]:
    """Читает other_*_rd.csv — плановые даты выдачи РД по разделам."""
    df = _read_csv_auto(path, sep=";")
    if df.empty:
        return []

    snapshot_date = meta.get("snapshot_date", "")
    project_name = meta.get("project_name", "")
    source_file = meta["name"]

    # Нормализуем имена колонок (могут быть с переносами)
    col_map = {}
    for col in df.columns:
        cn = col.replace("\n", " ").replace("  ", " ").strip().lower()
        col_map[col] = cn
    df = df.rename(columns=col_map)

    records = []
    for _, row in df.iterrows():
        # Попытка найти нужные колонки по подстрокам
        num_col = _find_col(df.columns, ["номер", "number", "№"])
        cipher_col = _find_col(df.columns, ["шифр", "cipher", "code"])
        name_col = _find_col(df.columns, ["наименование", "name", "раздел"])
        count_col = _find_col(df.columns, ["количество", "count", "кол"])
        date_col = _find_col(df.columns, ["дата", "date"])

        records.append({
            "snapshot_date": snapshot_date,
            "project_name":  project_name,
            "number":        _safe_int(row.get(num_col)) if num_col else None,
            "cipher":        _str(row.get(cipher_col)) if cipher_col else None,
            "section_name":  _str(row.get(name_col)) if name_col else None,
            "count_plan":    _safe_int(row.get(count_col)) if count_col else None,
            "date_plan":     _parse_date(row.get(date_col)) if date_col else None,
            "source_file":   source_file,
        })
    return records


# ── KrStates справочник ───────────────────────────────────────────────────────

def map_kr_states(path: Path, meta: dict) -> list[dict]:
    try:
        df = _read_csv_auto(path, sep=",")
    except Exception:
        df = _read_csv_auto(path, sep=";")
    if df.empty:
        return []

    records = []
    for _, row in df.iterrows():
        records.append({
            "name":    _str(row.get("Название")),
            "comment": _str(row.get("Комментарий")),
            "en":      _str(row.get("en")),
            "ru":      _str(row.get("ru")),
        })
    return records


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _str(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _safe_int(val) -> Optional[int]:
    try:
        return int(float(str(val).replace(",", ".")))
    except (ValueError, TypeError):
        return None


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    s = str(val).replace(",", ".").replace(" ", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _find_col(columns, keywords: list) -> Optional[str]:
    """Находит первую колонку, содержащую одно из ключевых слов."""
    for col in columns:
        cl = col.lower()
        if any(kw in cl for kw in keywords):
            return col
    return None


def _load_json_tolerant(path: Path) -> list:
    """Загружает JSON с автоопределением кодировки. Tolerant к BOM."""
    with open(path, "rb") as f:
        raw = f.read()
    enc = chardet.detect(raw[:5000]).get("encoding") or "utf-8"
    text = raw.decode(enc, errors="replace")
    # Убираем BOM
    text = text.lstrip("\ufeff").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Попытка починить обрезанный JSON (добавляем закрывающую скобку)
        log.warning("JSON decode error in %s, trying to fix...", path.name)
        for suffix in ("]", "]}"):
            try:
                return json.loads(text + suffix)
            except json.JSONDecodeError:
                continue
        log.error("Cannot parse JSON: %s", path.name)
        return []
