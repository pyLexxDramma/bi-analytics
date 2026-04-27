"""
web_loader.py — парсинг файлов из папки web/ и сохранение в SQLite (data/web_data.db).

Основная функция: load_all_from_web()
- Сканирует локальный web/, при наличии — каталог «Analitics/web» (см. config.get_analytics_sibling_web_dir),
  и дополнительные пути из BI_ANALYTICS_WEB_EXTRA_PATHS
- Сканирует web/ рекурсивно
- Определяет тип файла через ETL-парсер (etl/parser.py)
- Для MSP-файлов применяет маппинг колонок → формат дашбордов
- Для файлов ресурсов использует специальный загрузчик с 3-строчным заголовком
- Сохраняет строки в web_data с привязкой к версии
- Раскладывает данные в session_state для дашбордов

Чтение из БД: read_version_to_session(version_id)
- Загружает данные нужной версии из SQLite в session_state
"""
import csv
import io
import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import ignore_demo_data_files

import pandas as pd
import streamlit as st

from utils import norm_partner_join_key, ensure_msp_hierarchy_columns

from web_schema import (
    WEB_DB_PATH,
    get_active_version_id,
    activate_version,
)


# ── Маппинг MSP-колонок → формат дашбордов ──────────────────────────────────

# MSP экспортирует файлы с русскими названиями колонок (Windows-1251).
# Дашборды ожидают английские canonical-имена из data_loader.column_mapping.
_MSP_COLUMN_REMAP: Dict[str, str] = {
    "Название задачи":       "task name",
    "Название":              "task name",
    "Начало":                "plan start",
    "Окончание":             "plan end",
    "Базовое_начало":        "base start",
    "Базовое_окончание":     "base end",
    "Причины_отклонений":    "reason of deviation",
    "БЛОК":                  "block",
    # Лот — отдельная колонка; «section» заполняется из иерархии (родитель ур. 2) в _postprocess_msp_df
    "ЛОТ":                   "lot",
    "Уровень_структуры":     "level structure",
    "Процент_завершения":    "pct complete",
    "Отклонение_окончания":  "deviation in days",
    "Отклонение_начала":     "deviation start days",
    "Шифр_ПД_и_РД":          "abbreviation",
    "ID_проекта":            "project id",
    "Уровень":               "level",
    "Тип":                   "task type",
    "Заметки":               "notes",
    "Базовая_длительность":  "base duration",
    "Длительность":          "duration",
    "Режим_задачи":          "task mode",
    "Календарь_задачи":      "calendar",
    "Предшественники":       "predecessors",
    "Последователи":         "successors",
    "Дата_ограничения":      "constraint date",
    "Уникальный_идентификатор": "unique id",
    "Ид":                    "task id seq",
    # Варианты с пробелами (экспорт MSP / Excel)
    "Базовое начало":       "base start",
    "Базовое окончание":    "base end",
    "План начало":          "plan start",
    "План окончание":       "plan end",
    # Фактическое окончание (если есть в экспорте MSP) — приоритетное «Факт» для дат окончания задачи
    "Фактическое_окончание": "actual finish",
    "Фактическое окончание": "actual finish",
}


def _parse_snapshot_date(date_str: str):
    """
    Парсит дату снимка из имени файла.
    '30-03-2026' или '30.03.2026' → datetime.date(2026, 3, 30)
    Возвращает None при ошибке.
    """
    if not date_str:
        return None
    from datetime import datetime as _dt
    for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return _dt.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _deduplicate_project_snapshots(df: pd.DataFrame) -> pd.DataFrame:
    """
    Для проектных данных из MSP: оставляет только последний снимок каждого
    проекта (строки с максимальным snapshot_date по каждому project name).
    Строки без snapshot_date оставляет нетронутыми.
    """
    if df is None or df.empty:
        return df
    if "snapshot_date" not in df.columns:
        return df

    df = df.copy()
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"], errors="coerce")

    # Строки без snapshot_date или без project name — оставляем как есть
    has_snap = df["snapshot_date"].notna()
    if "project name" in df.columns:
        has_snap = has_snap & df["project name"].notna()

    if not has_snap.any():
        return df

    snap_part = df[has_snap].copy()
    no_snap_part = df[~has_snap].copy()

    # Максимальная дата снимка на группу project name
    latest = snap_part.groupby("project name")["snapshot_date"].transform("max")
    snap_part = snap_part[snap_part["snapshot_date"] == latest]

    result = pd.concat([no_snap_part, snap_part], ignore_index=True)
    return result


def _fill_section_from_task_tree(df: pd.DataFrame) -> pd.DataFrame:
    """
    Заполняет колонку section именем родительской задачи уровня 2 (для маппинга «Ковенанты»).
    Раньше колонка «ЛОТ» попадала в section — иерархия не считалась; при чтении из БД пересчитываем.
    Для каждого проекта обход в порядке строк в выгрузке (как в MSP).

    В MSP CSV «Уровень» и «Уровень_структуры» часто различаются; иерархия дерева — по outline
    (после ремапа: level structure), иначе родитель ур.2 и ветки «Ковенанты» считаются неверно.
    """
    if df is None or df.empty or "task name" not in df.columns:
        return df
    if "level" not in df.columns and "level structure" not in df.columns:
        return df
    df = df.copy()
    if "level" in df.columns:
        df["level"] = pd.to_numeric(df["level"], errors="coerce")
    if "level structure" in df.columns:
        df["level structure"] = pd.to_numeric(df["level structure"], errors="coerce")
    if "section" not in df.columns:
        df["section"] = ""

    def _outline_col(g: pd.DataFrame) -> Optional[str]:
        if "level structure" in g.columns and pd.to_numeric(g["level structure"], errors="coerce").notna().any():
            return "level structure"
        if "level" in g.columns:
            return "level"
        return None

    def _walk_one(g: pd.DataFrame) -> pd.DataFrame:
        g = g.sort_index()
        ocol = _outline_col(g)
        if ocol is None:
            return g
        current_sections: Dict[int, str] = {}
        proj_name = ""
        if "project name" in g.columns and len(g) > 0:
            v0 = g["project name"].iloc[0]
            proj_name = str(v0).strip() if pd.notna(v0) else ""
        for idx in g.index:
            lvl = pd.to_numeric(g.at[idx, ocol], errors="coerce")
            task = str(g.at[idx, "task name"]).strip() if pd.notna(g.at[idx, "task name"]) else ""
            if pd.notna(lvl):
                lvl_int = int(lvl)
                if lvl_int == 1:
                    current_sections[lvl_int] = str(proj_name) if proj_name else task
                else:
                    current_sections[lvl_int] = task
                for k in list(current_sections.keys()):
                    if k > lvl_int:
                        del current_sections[k]
                if lvl_int >= 3 and 2 in current_sections:
                    g.at[idx, "section"] = current_sections[2]
                elif lvl_int >= 2 and 1 in current_sections:
                    g.at[idx, "section"] = current_sections[1]
        return g

    if "project name" in df.columns:
        parts = []
        for _, g in df.groupby("project name", sort=False, dropna=False):
            parts.append(_walk_one(g))
        if not parts:
            return _walk_one(df)
        out = pd.concat(parts)
        return out.sort_index()
    return _walk_one(df)


def _apply_msp_column_mapping(df: pd.DataFrame, project_name: str) -> pd.DataFrame:
    """
    Переименовывает MSP-колонки в canonical-имена дашбордов.
    Парсит числовые поля (deviation in days, pct complete).
    Вычисляет deviation in days из дат если колонка пустая.
    Устанавливает boolean-флаг deviation (True = задача запаздывает).
    Добавляет Period-колонки для группировки по месяцу/кварталу/году.
    """
    # ── Переименование колонок ───────────────────────────────────────────────
    # data_loader.load_data() уже мог частично переименовать MSP-колонки в canonical-имена
    # (plan start, plan end, task name, lot, level structure, level). Пропускаем те
    # переименования, которые создадут дубликат с уже существующей canonical-колонкой,
    # иначе далее df[col] возвращает DataFrame и df[col] = df[col].apply(...) падает KeyError.
    _existing = set(df.columns)
    remap = {
        k: v for k, v in _MSP_COLUMN_REMAP.items()
        if k in _existing and v not in _existing
    }
    df = df.rename(columns=remap)
    # Страховка: если дубликаты всё-таки появились (разные исходные имена → один canonical),
    # оставляем копию с бо́льшим числом непустых значений.
    if df.columns.duplicated().any():
        _cols = list(df.columns)
        _keep = [True] * len(_cols)
        _seen: Dict[str, int] = {}
        for _i, _c in enumerate(_cols):
            if _cols.count(_c) <= 1:
                continue
            _idxs = [j for j, cc in enumerate(_cols) if cc == _c]
            if _c in _seen:
                continue
            _best = max(_idxs, key=lambda j: int(df.iloc[:, j].notna().sum()))
            for j in _idxs:
                if j != _best:
                    _keep[j] = False
            _seen[_c] = _best
        df = df.iloc[:, _keep].copy()

    from config import MSP_PROJECT_NAME_MAP

    # Нормализованное имя проекта из имени файла (msp_<project_name>_<date>.csv).
    # Используется и как заполнитель пустых ячеек, и как fallback для непокрытых ключей.
    _file_key = (project_name or "").strip().lower()
    ru_from_file = MSP_PROJECT_NAME_MAP.get(_file_key, project_name or "")

    def _normalize_project_cell(x):
        if pd.isna(x):
            return ru_from_file
        s = str(x).strip()
        if not s or s.lower() in ("nan", "none", "<na>"):
            return ru_from_file
        # Пробуем маппинг (с учётом регистра и варианта lower).
        return MSP_PROJECT_NAME_MAP.get(s, MSP_PROJECT_NAME_MAP.get(s.lower(), ru_from_file or s))

    if "project name" not in df.columns:
        df["project name"] = ru_from_file
    else:
        df["project name"] = df["project name"].apply(_normalize_project_cell)

    # ── Вспомогательные функции ──────────────────────────────────────────────
    def _parse_msp_date(val):
        """Парсит DD.MM.YY, DD.MM.YYYY, YYYY-MM-DD → pd.Timestamp.
        Явные форматы надёжнее format='mixed' для 2-значного года."""
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return pd.NaT
        s = str(val).strip()
        if not s or s.lower() in ("nan", "none", "нд", "nd", ""):
            return pd.NaT
        for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
            try:
                from datetime import datetime as _dt
                return pd.Timestamp(_dt.strptime(s, fmt))
            except ValueError:
                continue
        return pd.to_datetime(s, dayfirst=True, errors="coerce")

    def _parse_days_str(val):
        """'5 дн' → 5.0, '-30 дн' → -30.0, '0 дн?' → 0.0, пустое → None."""
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        s = str(val).strip().replace("\xa0", "")
        if not s or s.lower() in ("nan", "none", ""):
            return None
        m = re.search(r"(-?\s*\d+(?:[.,]\d+)?)", s)
        if m:
            try:
                return float(m.group(1).replace(",", ".").replace(" ", ""))
            except (ValueError, TypeError):
                return None
        return None

    # ── Даты: явные форматы вместо format='mixed' ────────────────────────────
    for col in ("plan start", "plan end", "base start", "base end", "actual finish"):
        if col in df.columns:
            df[col] = df[col].apply(_parse_msp_date)

    # ── pct complete: "5%" → 5.0 ────────────────────────────────────────────
    if "pct complete" in df.columns:
        def _parse_pct(val):
            if val is None:
                return None
            s = str(val).replace("%", "").replace(",", ".").strip()
            try:
                return float(s)
            except (ValueError, TypeError):
                return None
        df["pct complete"] = df["pct complete"].apply(_parse_pct)

    # ── deviation in days: "5 дн" → 5.0, "-30 дн" → -30.0 ─────────────────
    if "deviation in days" in df.columns:
        df["deviation in days"] = df["deviation in days"].apply(_parse_days_str)
    else:
        df["deviation in days"] = None

    # Fallback: если колонка пустая — вычисляем из дат (plan end - base end)
    if "plan end" in df.columns and "base end" in df.columns:
        mask_empty = df["deviation in days"].isna()
        calc_mask = mask_empty & df["plan end"].notna() & df["base end"].notna()
        if calc_mask.any():
            df.loc[calc_mask, "deviation in days"] = (
                df.loc[calc_mask, "plan end"] - df.loc[calc_mask, "base end"]
            ).dt.days

    # ── Флаг deviation: True если задача запаздывает ─────────────────────────
    # Дашборды фильтруют по: deviation == True или deviation == 1
    df["deviation"] = df["deviation in days"].apply(
        lambda x: True if (pd.notna(x) and float(x) > 0) else False
    )

    # ── Period-колонки для группировки (аналогично data_loader.py) ──────────
    for date_col, prefix in [
        ("plan start", "plan_start"),
        ("plan end", "plan"),
        ("base start", "base_start"),
        ("base end", "base"),
    ]:
        if date_col in df.columns:
            mask = df[date_col].notna()
            if mask.any():
                df.loc[mask, f"{prefix}_day"] = df.loc[mask, date_col].dt.date
                df.loc[mask, f"{prefix}_month"] = df.loc[mask, date_col].dt.to_period("M")
                df.loc[mask, f"{prefix}_quarter"] = df.loc[mask, date_col].dt.to_period("Q")
                df.loc[mask, f"{prefix}_year"] = df.loc[mask, date_col].dt.to_period("Y")

    if "plan end" in df.columns:
        mask = df["plan end"].notna()
        if mask.any():
            df.loc[mask, "plan_month"] = df.loc[mask, "plan end"].dt.to_period("M")
            df.loc[mask, "plan_quarter"] = df.loc[mask, "plan end"].dt.to_period("Q")
            df.loc[mask, "plan_year"] = df.loc[mask, "plan end"].dt.to_period("Y")

    if "base end" in df.columns:
        mask = df["base end"].notna()
        if mask.any():
            df.loc[mask, "actual_month"] = df.loc[mask, "base end"].dt.to_period("M")
            df.loc[mask, "actual_quarter"] = df.loc[mask, "base end"].dt.to_period("Q")
            df.loc[mask, "actual_year"] = df.loc[mask, "base end"].dt.to_period("Y")

    ensure_msp_hierarchy_columns(df)
    if "level" in df.columns and "task name" in df.columns:
        df = _fill_section_from_task_tree(df)

    df.attrs["data_type"] = "project"
    return df


def _load_resources_file(filepath: Path) -> Optional[pd.DataFrame]:
    """
    Загружает файл ресурсов (other_*_resursi.csv) с 3-строчным заголовком.

    Структура файла:
      Строка 0: пустая или с лишними разделителями (пропускаем)
      Строка 1: метки недель (пропускаем)
      Строка 2: реальный заголовок: Проект;Подрядчик;тип ресурсов;01.01.2026;...
      Строка 3+: данные
    """
    encodings = ["utf-8", "utf-8-sig", "windows-1251", "cp1251"]
    seps = [";", ","]
    # На FTP иногда 2 или 1 строка «служебных» строк — пробуем несколько header
    for header_row in (2, 1, 0):
        for encoding in encodings:
            for sep in seps:
                try:
                    df = pd.read_csv(
                        filepath,
                        sep=sep,
                        encoding=encoding,
                        header=header_row,
                        quoting=csv.QUOTE_MINIMAL,
                        quotechar='"',
                        doublequote=True,
                        on_bad_lines="skip",
                    )
                    df.columns = [
                        str(c).replace("\ufeff", "").replace("\n", " ").replace("\r", " ").strip()
                        for c in df.columns
                    ]
                    df = df.dropna(how="all")
                    if df.empty or len(df.columns) < 3:
                        continue
                    cols_low = [str(c).lower() for c in df.columns]
                    has_contractor = any(
                        x in cols_low
                        for x in ("контрагент", "подрядчик", "contractor")
                    )
                    if not has_contractor:
                        continue
                    if "Подрядчик" in df.columns and "Контрагент" not in df.columns:
                        df = df.rename(columns={"Подрядчик": "Контрагент"})
                    _ru_res_aliases = {
                        "тип ресурса": "тип ресурсов",
                        "Тип ресурса": "тип ресурсов",
                    }
                    for a, b in _ru_res_aliases.items():
                        if a in df.columns and b not in df.columns:
                            df = df.rename(columns={a: b})

                    from config import MSP_PROJECT_NAME_MAP
                    if "Проект" in df.columns:
                        df["Проект"] = df["Проект"].apply(
                            lambda x: MSP_PROJECT_NAME_MAP.get(
                                str(x).strip().lower().replace(" ", ""), str(x).strip()
                            ) if pd.notna(x) else x
                        )

                    df.attrs["data_type"] = "resources"
                    return df
                except (UnicodeDecodeError, pd.errors.ParserError):
                    continue
                except Exception:
                    continue
    return None


def _load_1c_json_dk(filepath: Path) -> Optional[pd.DataFrame]:
    try:
        with open(filepath, encoding="utf-8") as f:
            raw = json.load(f)
        if not raw or not isinstance(raw, list):
            return None
        rows = []
        for item in raw:
            try:
                flat = {}
                org = item.get("Организация") or {}
                flat["Название организации"] = org.get("НаименованиеОрганизации", "")
                flat["ID_Организации"] = org.get("ID_Организации", "")
                contr = item.get("Контрагент") or {}
                flat["Название контрагента"] = contr.get("НаименованиеКонтрагента", "")
                flat["ID_Контрагента"] = contr.get("ID_Контрагента", "")
                dog = item.get("Договор") or {}
                flat["Номер договора"] = str(dog.get("НомерДоговора", "") or "").strip()
                flat["ID_Договора"] = dog.get("ID_Договора", "")
                flat["Дата договора"] = dog.get("ДатаДоговора", "")
                sum_str = str(dog.get("СуммаДоговора", "0") or "0").replace(",", "").replace(" ", "")
                try:
                    flat["Сумма в договоре"] = float(sum_str) if sum_str else 0.0
                except (ValueError, TypeError):
                    flat["Сумма в договоре"] = 0.0
                def _safe_float(val):
                    try:
                        return float(val) if val is not None else 0.0
                    except (ValueError, TypeError):
                        return 0.0
                flat["ОстатокНаНачало"] = _safe_float(item.get("ОстатокНаНачало", 0))
                flat["ОстатокНаНачалоПериода"] = _safe_float(item.get("ОстатокНаНачалоПериода", 0))
                flat["ОстатокНаНачалоПериодаПоАвансам"] = _safe_float(item.get("ОстатокНаНачалоПериодаПоАвансам", 0))
                flat["Выплачено"] = _safe_float(item.get("ВсегоОплат", 0))
                flat["Аванс"] = _safe_float(item.get("ВсегоОплат_Аванс", 0))
                flat["ОстатокНаКонец"] = _safe_float(item.get("ОстатокНаКонец", 0))
                flat["Остаток на конец периода"] = _safe_float(item.get("ОстатокНаКонецПериода", 0))
                flat["ОстатокНаКонецПериодаПоАвансам"] = _safe_float(item.get("ОстатокНаКонецПериодаПоАвансам", 0))
                rows.append(flat)
            except Exception:
                continue
        if not rows:
            return None
        df = pd.DataFrame(rows)
        df.attrs["data_type"] = "debit_credit"
        return df
    except Exception:
        return None


def _load_1c_json_spravochniki(filepath: Path) -> Optional[pd.DataFrame]:
    try:
        with open(filepath, encoding="utf-8") as f:
            raw = json.load(f)
        if not raw or not isinstance(raw, list):
            return None
        return pd.DataFrame(raw)
    except Exception:
        return None


def _find_dannye_contractor_column(df: pd.DataFrame) -> Optional[str]:
    """Колонка контрагента в JSON «данные» 1С (обороты): Контрагент, Наименование…"""
    if df is None or df.empty:
        return None
    scored: List[Tuple[int, str]] = []
    for c in df.columns:
        s = str(c).strip().lower().replace("_", " ")
        sc = 0
        if "инн" in s or "кпп" in s:
            continue
        if s in ("контрагент", "контрагенты"):
            sc += 80
        if "контрагент" in s and "договор" not in s:
            sc += 40
        if "наименование" in s and "контрагент" in s:
            sc += 60
        if "организация" in s and "контрагент" not in s:
            sc += 5
        if sc > 0:
            scored.append((sc, str(c)))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def _find_dannye_project_column(df: pd.DataFrame) -> Optional[str]:
    """Колонка проекта в JSON «данные» 1С."""
    if df is None or df.empty:
        return None
    for c in df.columns:
        sl = str(c).strip().lower().replace("_", " ")
        if sl == "проект" or sl.endswith(" проект"):
            return str(c)
    for c in df.columns:
        sl = str(c).strip().lower().replace("_", " ")
        if "проект" in sl and "проектн" not in sl and "подпроект" not in sl:
            if "id" not in sl or sl == "id проекта":
                return str(c)
    return None


def _build_partner_project_map_from_dannye(df: pd.DataFrame) -> Dict[str, str]:
    """
    Контрагент → наиболее частый Проект по строкам dannye.json (обороты 1С).
    Ключи — norm_partner_join_key.
    """
    from collections import Counter

    if df is None or df.empty:
        return {}
    cc = _find_dannye_contractor_column(df)
    pc = _find_dannye_project_column(df)
    if not cc or not pc or cc not in df.columns or pc not in df.columns:
        return {}
    tmp = df[[cc, pc]].copy()
    tmp = tmp.dropna(how="any")
    tmp = tmp[tmp[cc].astype(str).str.strip() != ""]
    tmp = tmp[tmp[pc].astype(str).str.strip() != ""]
    if tmp.empty:
        return {}
    out: Dict[str, str] = {}
    for raw_k, g in tmp.groupby(tmp[cc].map(lambda x: norm_partner_join_key(x))):
        if not raw_k:
            continue
        cnt = Counter(g[pc].astype(str).str.strip())
        out[raw_k] = cnt.most_common(1)[0][0]
    return out


def _merge_partner_project_maps(
    old: Optional[Dict[str, str]], new: Optional[Dict[str, str]]
) -> Dict[str, str]:
    """Объединяет карты; при конфликте оставляет значение из new (свежий файл)."""
    a = dict(old or {})
    for k, v in (new or {}).items():
        if k and v:
            a[k] = v
    return a


def _load_tessa_file(filepath: Path) -> Optional[pd.DataFrame]:
    encodings = ["utf-8", "utf-8-sig", "windows-1251", "cp1251"]
    seps = [";", ","]
    for encoding in encodings:
        for sep in seps:
            try:
                df = pd.read_csv(
                    filepath,
                    sep=sep,
                    encoding=encoding,
                    quoting=csv.QUOTE_MINIMAL,
                    quotechar='"',
                    doublequote=True,
                    on_bad_lines="skip",
                )
                df.columns = [
                    str(c).replace("\ufeff", "").replace("\n", " ").replace("\r", " ").strip()
                    for c in df.columns
                ]
                df = df.dropna(how="all")
                if df.empty or len(df.columns) < 3:
                    continue
                df.attrs["data_type"] = "tessa"
                return df
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
    return None


def _load_reference_csv(filepath: Path) -> Optional[pd.DataFrame]:
    encodings = ["utf-8", "utf-8-sig", "windows-1251", "cp1251"]
    for encoding in encodings:
        try:
            df = pd.read_csv(filepath, sep=",", encoding=encoding, on_bad_lines="skip")
            df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
            if df.empty:
                continue
            return df
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    return None


def _format_skip_reason(rel_path: str, reason: str, detail: str = "") -> str:
    msg = f"{rel_path}: {reason}"
    if detail:
        msg += f" — {detail}"
    return msg


# ── Утилиты ─────────────────────────────────────────────────────────────────

def get_web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def _iter_web_scan_roots() -> List[Tuple[Path, str]]:
    """
    Корни для CSV/JSON: локальный web/, при наличии .../Analitics/web, пути из BI_ANALYTICS_WEB_EXTRA_PATHS.
    Второй элемент кортежа — префикс для rel_path (уникальность при одинаковых именах в разных корнях).
    """
    from config import get_analytics_sibling_web_dir, get_extra_web_dirs_from_env

    roots: List[Tuple[Path, str]] = []
    seen: set = set()

    def _add(root: Path, prefix: str) -> None:
        try:
            key = str(root.resolve())
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        roots.append((root, prefix))

    _add(get_web_dir(), "")

    sib = get_analytics_sibling_web_dir()
    if sib is not None:
        try:
            if sib.resolve() != get_web_dir().resolve():
                _add(sib, "Analitics_web")
        except OSError:
            _add(sib, "Analitics_web")

    for ex in get_extra_web_dirs_from_env():
        label = ex.name.replace(" ", "_") or "extra_web"
        _add(ex, label)

    return roots


def web_dir_exists() -> bool:
    """True, если есть хотя бы один из каталогов данных (локальный web/, Analitics/web, extra из env)."""
    for root, _ in _iter_web_scan_roots():
        if root.is_dir():
            return True
    return False


def _is_demo_file(rel_path: str, name: str) -> bool:
    """
    Демо: имена sample_*, любой файл внутри каталога new_csv/ в пути.
    (Режим отключения — ``BI_ANALYTICS_IGNORE_DEMO`` через :func:`ignore_demo_data_files`.)
    """
    n = str(name).lower()
    if n.startswith("sample_"):
        return True
    for part in Path(str(rel_path).replace("\\", "/")).parts:
        if part.lower() == "new_csv":
            return True
    return False


def scan_web_files(extensions: tuple = (".csv", ".json")) -> List[Dict]:
    """Рекурсивно сканирует все настроенные корни данных и возвращает список файлов."""
    files: List[Dict] = []
    for root, prefix in _iter_web_scan_roots():
        if not root.exists():
            continue
        for ext in extensions:
            for filepath in sorted(root.rglob(f"*{ext}")):
                if filepath.is_file():
                    rel = filepath.relative_to(root)
                    rel_path = str(rel).replace("\\", "/")
                    if prefix:
                        rel_path = f"{prefix}/{rel_path}"
                    if ignore_demo_data_files() and _is_demo_file(rel_path, filepath.name):
                        continue
                    files.append({
                        "path": filepath,
                        "name": filepath.name,
                        "rel_path": rel_path,
                    })
    return files


def _dedupe_scan_files_by_identity(files: List[Dict]) -> Tuple[List[Dict], List[str]]:
    """
    Убирает повторную загрузку одного и того же файла, если он попал в список
    из нескольких корней (локальный web/, Analitics/web/, BI_ANALYTICS_WEB_EXTRA_PATHS):
    одинаковое имя и размер на диске считаем дубликатом, оставляем первый путь.

    Без этого concat в session_state даёт удвоение строк MSP и «лишние» записи в БД.
    """
    seen: Dict[Tuple[str, int], str] = {}
    out: List[Dict] = []
    warns: List[str] = []
    for f in files:
        try:
            sz = int(f["path"].stat().st_size)
        except OSError:
            out.append(f)
            continue
        key = (str(f["name"]).lower(), sz)
        if key in seen:
            warns.append(
                f"Пропуск дубликата (уже как «{seen[key]}»): {f['rel_path']}"
            )
            continue
        seen[key] = f["rel_path"]
        out.append(f)
    return out, warns


def scan_new_csv_demo_files(extensions: tuple = (".csv",)) -> List[Dict]:
    """
    Демо-файлы из new_csv/ — подмешиваются к загрузке из web/, чтобы локально
    открывались финансовые отчёты и ДЗ/КЗ (колонки budget plan, дебиторка и т.д.).
    """
    base = Path(__file__).resolve().parent
    demo_dir = base / "new_csv"
    if not demo_dir.is_dir():
        return []
    names = (
        "sample_project_data_fixed.csv",
        "sample_budget_data.csv",
        "sample_debit_credit_data.csv",
        "sample_technique_data.csv",
    )
    out: List[Dict] = []
    for name in names:
        p = demo_dir / name
        if p.is_file() and p.suffix.lower() in extensions:
            out.append({
                "path": p,
                "name": name,
                "rel_path": f"new_csv/{name}",
            })
    return out


def get_web_file_list() -> List[str]:
    """Список относительных путей всех CSV в web/ (для отображения в UI)."""
    return [f["rel_path"] for f in scan_web_files()]


class _FileWrapper(io.BytesIO):
    """
    Обёртка над BytesIO — притворяется Streamlit UploadedFile.
    load_data() ожидает объект с атрибутом .name и методом .seek().
    """
    def __init__(self, content: bytes, name: str):
        super().__init__(content)
        self.name = name


def _infer_file_type(df: pd.DataFrame, file_name: str) -> str:
    """
    Определяет тип файла по содержимому DataFrame и имени файла.
    Вызывается только для файлов, чей тип не определён по имени (_infer_file_type_by_name).

    Возвращает: 'project' | 'resources' | 'technique' | 'budget' | 'debit_credit' | 'unknown'
    """
    name_lower = file_name.lower()
    cols = [str(c).lower() for c in df.columns]

    # MSP-файл: подчёркивания или пробелы в типичных заголовках
    has_msp_cols = any(c in cols for c in [
        "базовое_начало", "базовое_окончание", "причины_отклонений",
        "уровень_структуры",
        "базовое начало", "базовое окончание", "причины отклонений",
        "уровень структуры", "шифр_пд_и_рд", "шифр пд и рд",
    ])
    has_task_name = any(c in cols for c in ["название", "task name", "задача"])
    has_dates = any(c in cols for c in ["начало", "plan start", "старт план"])
    if has_msp_cols or (has_task_name and has_dates and "начало" in cols):
        return "msp"

    # Ресурсы: контрагент/подрядчик + недели или даты в заголовках (01.01.2026)
    has_contractor = any(c in cols for c in ["контрагент", "подрядчик", "contractor"])
    has_weeks = any("неделя" in c or "недели" in c for c in cols)
    has_date_headers = any(re.match(r"^\d{2}\.\d{2}\.\d{4}", c.strip()) for c in cols)
    if has_contractor and (has_weeks or has_date_headers):
        if "среднее за неделю" in " ".join(cols) or "техник" in name_lower:
            return "technique"
        return "resources"

    # Бюджет
    if "budget" in name_lower or "бюджет" in name_lower or "бддс" in name_lower:
        return "budget"
    has_scenario = any(c in cols for c in ["сценарий", "scenario"])
    if has_scenario:
        return "budget"

    # Дебиторка/Кредиторка
    if "debit" in name_lower or "credit" in name_lower or "задолженност" in name_lower:
        return "debit_credit"
    has_contract = any(c in cols for c in ["договор", "contract", "номер договора"])
    has_sum = any(c in cols for c in ["сумма", "sum", "выплачено"])
    if has_contract and has_sum:
        return "debit_credit"

    # Техника по содержимому
    if any("среднее за неделю" in c for c in cols):
        return "technique"
    if "technique" in name_lower or "техник" in name_lower or "tehnik" in name_lower:
        return "technique"

    return "unknown"


# ── Запись в SQLite ──────────────────────────────────────────────────────────

def _create_version(cur, files_count: int) -> int:
    """Создаёт новую запись версии и возвращает её id."""
    cur.execute(
        "INSERT INTO web_versions (status, files_count) VALUES ('pending', ?)",
        (files_count,)
    )
    return cur.lastrowid


def _register_file(cur, version_id: int, file_info: Dict, file_type: str, rows_count: int) -> int:
    """Регистрирует файл в web_files и возвращает его id."""
    cur.execute(
        """
        INSERT INTO web_files (version_id, file_name, rel_path, file_type, rows_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        (version_id, file_info["name"], file_info["rel_path"], file_type, rows_count)
    )
    return cur.lastrowid


def _save_rows(cur, version_id: int, file_id: int, file_type: str, source_file: str, df: pd.DataFrame):
    """Сохраняет строки DataFrame в web_data как JSON."""
    df_copy = df.copy()
    # Даты → строки
    for col in df_copy.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns:
        df_copy[col] = df_copy[col].astype(str)
    # Period-колонки → строки (pandas Period не сериализуется в JSON напрямую)
    for col in df_copy.columns:
        if df_copy[col].dtype == object:
            continue
        try:
            # Period dtype
            if hasattr(df_copy[col], "dt") and hasattr(df_copy[col].dt, "to_timestamp"):
                df_copy[col] = df_copy[col].astype(str)
        except Exception:
            pass

    rows = df_copy.where(pd.notnull(df_copy), None).to_dict(orient="records")
    cur.executemany(
        """
        INSERT INTO web_data (version_id, file_id, file_type, source_file, row_data)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (version_id, file_id, file_type, source_file, json.dumps(r, ensure_ascii=False, default=str))
            for r in rows
        ]
    )


# ── Основная функция загрузки ────────────────────────────────────────────────

def load_all_from_web() -> Dict:
    """
    Сканирует web/, парсит CSV, сохраняет в SQLite.
    Возвращает {"loaded": N, "skipped": N, "errors": [], "version_id": int|None}
    """
    from data_loader import load_data, ensure_data_session_state, update_session_with_loaded_file

    result = {
        "loaded": 0,
        "skipped": 0,
        "errors": [],
        "warnings": [],
        "diagnostics": [],
        "version_id": None,
    }

    if ignore_demo_data_files():
        result["warnings"].insert(
            0,
            "BI_ANALYTICS_IGNORE_DEMO: демо не подмешивается (каталог new_csv/ рядом с приложением, "
            "а также sample_*.csv и пути с …/new_csv/ в web/).",
        )
        files = scan_web_files(extensions=(".csv", ".json"))
    else:
        files = scan_web_files(extensions=(".csv", ".json")) + scan_new_csv_demo_files()
    files, dedupe_warns = _dedupe_scan_files_by_identity(files)
    result["warnings"].extend(dedupe_warns)
    if not files:
        if ignore_demo_data_files():
            result["errors"].append(
                "Нет CSV/JSON для загрузки после исключения демо, либо каталоги пусты. "
                "Положите в web/ актуальные выгрузки MSP/1С/TESSA (без опоры на sample_ и new_csv)."
            )
        else:
            result["errors"].append("Папка web/ пуста или не найдена, и new_csv/ без демо-файлов.")
        return result

    ensure_data_session_state()
    # Сбрасываем session_state перед новой загрузкой
    st.session_state.project_data = None
    st.session_state["project_data_all_snapshots"] = None
    st.session_state.resources_data = None
    st.session_state.technique_data = None
    st.session_state.debit_credit_data = None
    st.session_state.loaded_files_info = {}
    st.session_state.tessa_data = None
    st.session_state["tessa_tasks_data"] = None
    st.session_state["reference_contractors"] = None
    st.session_state["reference_krstates"] = None
    st.session_state["reference_docstates"] = None
    st.session_state["reference_1c_dannye"] = None
    st.session_state["reference_partner_to_project"] = None

    import sqlite3
    conn = sqlite3.connect(WEB_DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        version_id = _create_version(cur, len(files))
        result["version_id"] = version_id
        total_rows = 0

        for file_info in files:
            filepath: Path = file_info["path"]
            name: str = file_info["name"]
            rel_path: str = file_info["rel_path"]

            try:
                # ── Определяем тип файла через ETL-парсер ──────────────────
                # Сначала определяем тип по имени файла (не нужен DataFrame)
                file_type_by_name = _infer_file_type_by_name(name)

                # ── Особый случай: файлы ресурсов (multi-level header) ──────
                if file_type_by_name == "resources":
                    df = _load_resources_file(filepath)
                    if df is None or df.empty:
                        result["skipped"] += 1
                        result["errors"].append(
                            _format_skip_reason(
                                rel_path,
                                "ресурсы не распознаны",
                                "ожидался многострочный заголовок (Проект;Подрядчик;…); "
                                "проверьте разделитель ; или , и кодировку",
                            )
                        )
                        continue
                    file_type = "resources"
                    file_id = _register_file(cur, version_id, file_info, file_type, len(df))
                    _save_rows(cur, version_id, file_id, file_type, name, df)
                    total_rows += len(df)
                    result["loaded"] += 1
                    df.attrs["data_type"] = "resources"
                    update_session_with_loaded_file(df, rel_path)
                    result["diagnostics"].append({
                        "file": rel_path,
                        "type": "resources",
                        "rows": int(len(df)),
                        "columns": [str(c) for c in df.columns[:25]],
                    })
                    continue

                # ── Пропускаем ненужные файлы ──────────────────────────────
                if file_type_by_name == "skip":
                    result["skipped"] += 1
                    continue

                # ── JSON файлы из 1С ─────────────────────────────────────────
                if file_type_by_name == "debit_credit_json":
                    df = _load_1c_json_dk(filepath)
                    if df is not None and not df.empty:
                        file_type = "debit_credit"
                        file_id = _register_file(cur, version_id, file_info, file_type, len(df))
                        _save_rows(cur, version_id, file_id, file_type, name, df)
                        total_rows += len(df)
                        result["loaded"] += 1
                        df.attrs["data_type"] = "debit_credit"
                        update_session_with_loaded_file(df, rel_path)
                        result["diagnostics"].append({
                            "file": rel_path, "type": "debit_credit", "rows": int(len(df)),
                            "columns": [str(c) for c in df.columns[:25]],
                        })
                    else:
                        result["skipped"] += 1
                        result["errors"].append(_format_skip_reason(rel_path, "JSON DK не распознан"))
                    continue

                if file_type_by_name == "reference_json":
                    ref_df = _load_1c_json_spravochniki(filepath)
                    if ref_df is not None and not ref_df.empty:
                        st.session_state["reference_contractors"] = ref_df
                        result["loaded"] += 1
                        result["diagnostics"].append({
                            "file": rel_path, "type": "reference", "rows": int(len(ref_df)),
                            "columns": [str(c) for c in ref_df.columns[:25]],
                        })
                    else:
                        result["skipped"] += 1
                    continue

                if file_type_by_name == "budget_json":
                    ddf = _load_1c_json_spravochniki(filepath)
                    if ddf is not None and not ddf.empty:
                        ddf.attrs["data_type"] = "reference_dannye"
                        if st.session_state.get("reference_1c_dannye") is None:
                            st.session_state["reference_1c_dannye"] = ddf
                        else:
                            st.session_state["reference_1c_dannye"] = pd.concat(
                                [st.session_state["reference_1c_dannye"], ddf],
                                ignore_index=True,
                            )
                        pmap = _build_partner_project_map_from_dannye(ddf)
                        st.session_state["reference_partner_to_project"] = (
                            _merge_partner_project_maps(
                                st.session_state.get("reference_partner_to_project"),
                                pmap,
                            )
                        )
                        result["loaded"] += 1
                        result["diagnostics"].append({
                            "file": rel_path,
                            "type": "reference_dannye",
                            "rows": int(len(ddf)),
                            "columns": [str(c) for c in ddf.columns[:30]],
                            "partner_project_keys": int(len(pmap)),
                        })
                    else:
                        result["skipped"] += 1
                    continue

                # ── TESSA файлы ──────────────────────────────────────────────
                if file_type_by_name == "tessa_tasks":
                    df = _load_tessa_file(filepath)
                    if df is not None and not df.empty:
                        file_type = "tessa_tasks"
                        file_id = _register_file(cur, version_id, file_info, file_type, len(df))
                        _save_rows(cur, version_id, file_id, file_type, name, df)
                        total_rows += len(df)
                        result["loaded"] += 1
                        df.attrs["data_type"] = "tessa_tasks"
                        if st.session_state.get("tessa_tasks_data") is None:
                            st.session_state["tessa_tasks_data"] = df
                        else:
                            st.session_state["tessa_tasks_data"] = pd.concat(
                                [st.session_state["tessa_tasks_data"], df], ignore_index=True
                            )
                        result["diagnostics"].append({
                            "file": rel_path, "type": "tessa_tasks", "rows": int(len(df)),
                            "columns": [str(c) for c in df.columns[:25]],
                        })
                    else:
                        result["skipped"] += 1
                    continue

                if file_type_by_name == "tessa":
                    df = _load_tessa_file(filepath)
                    if df is not None and not df.empty:
                        file_type = "tessa"
                        file_id = _register_file(cur, version_id, file_info, file_type, len(df))
                        _save_rows(cur, version_id, file_id, file_type, name, df)
                        total_rows += len(df)
                        result["loaded"] += 1
                        if st.session_state.get("tessa_data") is None:
                            st.session_state["tessa_data"] = df
                        else:
                            st.session_state["tessa_data"] = pd.concat(
                                [st.session_state["tessa_data"], df], ignore_index=True
                            )
                        result["diagnostics"].append({
                            "file": rel_path, "type": "tessa", "rows": int(len(df)),
                            "columns": [str(c) for c in df.columns[:25]],
                        })
                    else:
                        result["skipped"] += 1
                    continue

                # ── Справочники CSV (KrStates, DocStates) ────────────────────
                if file_type_by_name == "reference_csv":
                    ref_df = _load_reference_csv(filepath)
                    if ref_df is not None and not ref_df.empty:
                        ref_key = "krstates" if "krstate" in name.lower() else "docstates"
                        st.session_state[f"reference_{ref_key}"] = ref_df
                        result["loaded"] += 1
                    else:
                        result["skipped"] += 1
                    continue

                # ── RD plan файлы ────────────────────────────────────────────
                if file_type_by_name == "rd_plan":
                    content = filepath.read_bytes()
                    wrapped = _FileWrapper(content, name)
                    df = load_data(wrapped, file_name=name)
                    if df is not None and not df.empty:
                        file_type = "project"
                        df.attrs["data_type"] = "project"
                        file_id = _register_file(cur, version_id, file_info, file_type, len(df))
                        _save_rows(cur, version_id, file_id, file_type, name, df)
                        total_rows += len(df)
                        result["loaded"] += 1
                        update_session_with_loaded_file(df, rel_path)
                        result["diagnostics"].append({
                            "file": rel_path, "type": "rd_plan", "rows": int(len(df)),
                            "columns": [str(c) for c in df.columns[:25]],
                        })
                    else:
                        result["skipped"] += 1
                    continue

                # ── Загружаем через data_loader ─────────────────────────────
                content = filepath.read_bytes()
                wrapped = _FileWrapper(content, name)
                df = load_data(wrapped, file_name=name)

                if df is None or df.empty:
                    result["skipped"] += 1
                    result["errors"].append(
                        _format_skip_reason(
                            rel_path,
                            "не удалось прочитать CSV",
                            "пустой файл, неверный разделитель (; ,), кодировка (UTF-8 / Windows-1251) или нет заголовков",
                        )
                    )
                    continue

                # ── Уточняем тип (с учётом содержимого) ────────────────────
                if file_type_by_name in ("unknown",):
                    file_type = _infer_file_type(df, name)
                else:
                    file_type = file_type_by_name

                # Если всё ещё unknown — берём тип от data_loader
                if file_type == "unknown":
                    file_type = df.attrs.get("data_type", "project")

                # Пропускаем skip-файлы (могли определиться только по колонкам)
                if file_type == "skip":
                    result["skipped"] += 1
                    continue

                if file_type == "unknown":
                    preview = ", ".join(str(c) for c in list(df.columns)[:15])
                    result["warnings"].append(
                        f"{rel_path}: тип файла не распознан; первые колонки: {preview}"
                    )
                    result["skipped"] += 1
                    continue

                # ── MSP-файлы: применяем ремаппинг колонок ─────────────────
                if file_type == "msp":
                    # Извлекаем имя проекта из имени файла: msp_dmitrovsky1_... → dmitrovsky1
                    # Формат: msp_<project_name>_<date>.csv
                    parts = name.replace(".csv", "").split("_")
                    project_name = parts[1] if len(parts) > 1 else name.replace(".csv", "")
                    # Дата снимка: последний сегмент до расширения (02-03-2026)
                    snapshot_date = _parse_snapshot_date(parts[-1]) if len(parts) > 2 else None
                    df = _apply_msp_column_mapping(df, project_name)
                    if snapshot_date is not None:
                        df["snapshot_date"] = pd.Timestamp(snapshot_date)
                    file_type = "project"
                elif file_type in ("resources", "technique"):
                    # Для ГДРС/техники: дата снимка из имени файла (other_01-02-2026_resursi.csv и т.п.)
                    _parts = name.replace(".csv", "").replace(".CSV", "").split("_")
                    _snap = None
                    for _p in reversed(_parts):
                        _snap = _parse_snapshot_date(_p)
                        if _snap is not None:
                            break
                    if _snap is not None and "snapshot_date" not in df.columns:
                        df["snapshot_date"] = pd.Timestamp(_snap)

                file_id = _register_file(cur, version_id, file_info, file_type, len(df))
                _save_rows(cur, version_id, file_id, file_type, name, df)

                total_rows += len(df)
                result["loaded"] += 1

                # Сразу кладём в session_state для немедленного отображения
                if file_type in ("resources", "technique"):
                    session_type = file_type
                elif file_type == "debit_credit":
                    session_type = "debit_credit"
                else:
                    session_type = "project"
                df.attrs["data_type"] = session_type
                update_session_with_loaded_file(df, rel_path)
                result["diagnostics"].append({
                    "file": rel_path,
                    "type": file_type,
                    "rows": int(len(df)),
                    "columns": [str(c) for c in df.columns[:25]],
                })

            except Exception as e:
                result["errors"].append(
                    _format_skip_reason(rel_path, "исключение при обработке", str(e))
                )
                result["skipped"] += 1

        # Обновляем статус версии (warnings не делают partial, только errors)
        status = "partial" if result["errors"] else "success"
        cur.execute(
            "UPDATE web_versions SET status=?, rows_count=? WHERE id=?",
            (status, total_rows, version_id)
        )
        # Политика активации:
        # - `success`: становится активной, старые деактивируются.
        # - `partial`: активируется только если нет ни одной прежней `success`-версии
        #   (иначе оставляем активной последнюю корректную, чтобы неполная загрузка
        #   не ломала рабочий дашборд).
        if status == "success":
            cur.execute("UPDATE web_versions SET is_active=0")
            cur.execute(
                "UPDATE web_versions SET is_active=1 WHERE id=?", (version_id,)
            )
        else:
            prev_success = cur.execute(
                "SELECT id FROM web_versions "
                "WHERE status='success' AND id<>? ORDER BY id DESC LIMIT 1",
                (version_id,),
            ).fetchone()
            if prev_success:
                cur.execute("UPDATE web_versions SET is_active=0")
                cur.execute(
                    "UPDATE web_versions SET is_active=1 WHERE id=?",
                    (prev_success[0],),
                )
                result.setdefault("warnings", []).append(
                    f"Версия {version_id} сохранена как partial — активной оставлена "
                    f"последняя success-версия (id={prev_success[0]})."
                )
            else:
                cur.execute("UPDATE web_versions SET is_active=0")
                cur.execute(
                    "UPDATE web_versions SET is_active=1 WHERE id=?", (version_id,)
                )

        conn.commit()

    except Exception as e:
        conn.rollback()
        result["errors"].append(f"Критическая ошибка: {e}")
    finally:
        cur.close()
        conn.close()

    # ── Все снимки до дедупликации — для «Причины отклонений» → вкладка «Динамика по периодам» (ось по дате файла) ──
    if st.session_state.get("project_data") is not None:
        st.session_state["project_data_all_snapshots"] = st.session_state.project_data.copy()
        st.session_state.project_data = _deduplicate_project_snapshots(
            st.session_state.project_data
        )
    else:
        st.session_state["project_data_all_snapshots"] = None

    return result


def _infer_file_type_by_name(file_name: str) -> str:
    """
    Быстрое определение типа файла ТОЛЬКО по имени (без чтения содержимого).
    Использует шаблоны имён из ETL-соглашения, без зависимости от etl-модуля.

    Возвращает: 'msp' | 'resources' | 'budget' | 'debit_credit' |
                'skip' | 'unknown'

    'msp'  — MSP-файл задач (msp_*.csv)
    'resources' — файл ресурсов (*resursi*.csv)
    'skip' — tessa_*, rd_plan, справочники — не нужны для дашбордов
    'unknown' — нужна проверка содержимого
    """
    name_lower = file_name.lower()
    # Убираем расширение для упрощённого сравнения
    stem = name_lower.rsplit(".", 1)[0]

    # ── MSP файлы проектов ───────────────────────────────────────────────────
    if stem.startswith("msp_") or stem.startswith("msp-") or "msp_" in name_lower:
        return "msp"

    # ── Файлы ресурсов (ГДРС) ────────────────────────────────────────────────
    if (
        "resursi" in stem
        or "resursy" in stem
        or "ресурс" in stem
        or "gdrs" in stem
        or "_gdrc" in stem
    ):
        return "resources"

    # ── Техника по имени ─────────────────────────────────────────────────────
    if any(
        x in stem
        for x in (
            "tehnik",
            "tehnika",
            "technique",
            "техник",
            "texnik",
            "other_techn",
        )
    ):
        return "technique"

    # ── Плановая выдача РД (other_*_rd.csv) ─────────────────────────────────
    if stem.startswith("other_") and stem.endswith("_rd"):
        return "rd_plan"

    # ── TESSA: задачи (CardId, KindName, …) — отдельный тип, чтобы join с Id по правкам ──
    if "tessa_tasks" in stem or (stem.startswith("tessa_") and "tasks" in stem):
        return "tessa_tasks"

    # ── TESSA файлы (карточки / Id) ──────────────────────────────────────────
    if stem.startswith("tessa_"):
        return "tessa"

    # ── Справочники KrStates / DocStates ─────────────────────────────────────
    if stem in ("docstates", "krstates"):
        return "reference_csv"

    # ── Статические файлы — пропускаем ───────────────────────────────────────
    if stem in ("ui_tasks",):
        return "skip"

    # ── Демо new_csv: дебиторка / бюджет обороты ─────────────────────────────
    if "debit" in stem and "credit" in stem:
        return "debit_credit"
    if (
        "debitor" in stem
        or "debtor" in stem
        or "zadol" in stem
        or "дз" in stem
        or "кз" in stem
    ):
        return "debit_credit"
    if (
        "sample_budget" in stem
        or stem.startswith("sample_budget")
        or "bdds" in stem
        or "бддс" in stem
        or "budget" in stem
        or "бюджет" in stem
        or "oborot" in stem
        or "оборот" in stem
        or "oborotypopodryad" in stem
        or "oboroty_po_podryad" in stem
        or "оборотыпоподряд" in stem
        or "oborot_po_podryad" in stem
    ):
        return "budget"

    # ── 1C JSON файлы ──────────────────────────────────────────────────────────
    if name_lower.endswith(".json"):
        if "dk" in stem.lower():
            return "debit_credit_json"
        if "dtkttpopodryad" in stem.lower() or "dtkt" in stem.lower() or "дткт" in stem.lower():
            return "debit_credit_json"
        if "spravochniki" in stem.lower() or "справочник" in stem.lower():
            return "reference_json"
        if "dannye" in stem.lower() or "данные" in stem.lower():
            return "budget_json"
        return "skip"

    return "unknown"


# ── Чтение версии из БД в session_state ─────────────────────────────────────

@st.cache_data(ttl=120)
def _load_version_data(version_id: int, file_type: str) -> Optional[pd.DataFrame]:
    """Загружает строки нужного типа из web_data для указанной версии."""
    import sqlite3
    try:
        conn = sqlite3.connect(WEB_DB_PATH)
        # Порядок строк = порядок вставки при загрузке (= порядок строк в CSV). Без ORDER BY
        # порядок не определён — ломается обход дерева и колонка section (родитель ур.2, «Ковенанты»).
        rows = conn.execute(
            "SELECT row_data, source_file FROM web_data WHERE version_id=? AND file_type=? ORDER BY id ASC",
            (version_id, file_type),
        ).fetchall()
        conn.close()
        if not rows:
            return None
        records = []
        for row_json, src_file in rows:
            rec = json.loads(row_json)
            if src_file:
                rec["__source_file"] = str(src_file)
            # Для старых версий БД: если snapshot_date не сохранён в row_data,
            # восстанавливаем его из имени source_file (other_01-02-2026_resursi.csv и т.п.).
            if "snapshot_date" not in rec and src_file:
                try:
                    parts = str(src_file).replace("\\", "/").split("/")[-1].replace(".csv", "").replace(".CSV", "").split("_")
                    snap = None
                    for p in reversed(parts):
                        snap = _parse_snapshot_date(p)
                        if snap is not None:
                            break
                    if snap is not None:
                        rec["snapshot_date"] = pd.Timestamp(snap)
                except Exception:
                    pass
            records.append(rec)
        return pd.DataFrame(records)
    except Exception:
        return None


def _restore_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Восстанавливает типы данных после чтения из SQLite (где всё хранится как строки).
    - datetime-колонки → pd.Timestamp
    - Period-колонки (_month, _quarter, _year) → pd.Period
    - _day-колонки → datetime.date
    """
    # Основные datetime-колонки
    for col in ("plan start", "plan end", "base start", "base end", "actual finish", "snapshot_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Period-колонки
    month_cols = [c for c in df.columns if c.endswith("_month") or c.endswith("_quarter") or c.endswith("_year")]
    for col in month_cols:
        if df[col].dtype == object:
            try:
                if col.endswith("_month"):
                    df[col] = df[col].apply(
                        lambda x: pd.Period(x, "M") if pd.notna(x) and x not in ("NaT", "None", "nan", "") else pd.NaT
                    )
                elif col.endswith("_quarter"):
                    df[col] = df[col].apply(
                        lambda x: pd.Period(x, "Q") if pd.notna(x) and x not in ("NaT", "None", "nan", "") else pd.NaT
                    )
                elif col.endswith("_year"):
                    df[col] = df[col].apply(
                        lambda x: pd.Period(x, "Y") if pd.notna(x) and x not in ("NaT", "None", "nan", "") else pd.NaT
                    )
            except Exception:
                pass

    # _day-колонки
    day_cols = [c for c in df.columns if c.endswith("_day")]
    for col in day_cols:
        if col in df.columns and df[col].dtype == object:
            try:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
            except Exception:
                pass

    return df


def read_version_to_session(version_id: int):
    """
    Загружает данные выбранной версии из SQLite в session_state.
    project_data  — объединение project + budget + debit_credit типов
    resources_data — данные ресурсов (для ГДРС)
    technique_data — данные техники (для ГДРС)
    """
    from data_loader import ensure_data_session_state

    ensure_data_session_state()

    # ── Данные проектов (без дебиторки — она в отдельном session_state) ─────
    dfs = []
    for ftype in ("project", "budget"):
        df = _load_version_data(version_id, ftype)
        if df is not None and not df.empty:
            df = df.copy()
            df = _restore_date_columns(df)
            # Старые версии в БД могли иметь «ЛОТ» в section — пересчитываем родителя ур.2 при каждом чтении
            if ftype == "project":
                ensure_msp_hierarchy_columns(df)
                df = _fill_section_from_task_tree(df)
            dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True) if dfs else None
    if combined is not None:
        st.session_state["project_data_all_snapshots"] = combined.copy()
    else:
        st.session_state["project_data_all_snapshots"] = None
    st.session_state.project_data = _deduplicate_project_snapshots(combined) if combined is not None else None

    deb = _load_version_data(version_id, "debit_credit")
    if deb is not None and not deb.empty:
        st.session_state.debit_credit_data = deb
    else:
        st.session_state.debit_credit_data = None

    # ── Данные ресурсов ──────────────────────────────────────────────────────
    res = _load_version_data(version_id, "resources")
    st.session_state.resources_data = res if (res is not None and not res.empty) else None

    # ── Данные техники ───────────────────────────────────────────────────────
    tech = _load_version_data(version_id, "technique")
    st.session_state.technique_data = tech if (tech is not None and not tech.empty) else None

    # ── Данные TESSA (исполнительная документация) ────────────────────────
    tessa = _load_version_data(version_id, "tessa")
    if tessa is not None and not tessa.empty:
        st.session_state["tessa_data"] = tessa
    elif st.session_state.get("tessa_data") is None:
        st.session_state["tessa_data"] = None

    # ── TESSA Tasks (отдельный файл для join CardId ↔ DocID) ───────────────
    tt = _load_version_data(version_id, "tessa_tasks")
    if tt is not None and not tt.empty:
        st.session_state["tessa_tasks_data"] = tt
    elif st.session_state.get("tessa_tasks_data") is None:
        st.session_state["tessa_tasks_data"] = None

    # ── Справочники (KrStates / DocStates) ────────────────────────────────
    # Загружаются из CSV при load_all_from_web(), не из БД;
    # если уже в session_state — не трогаем
    if st.session_state.get("reference_krstates") is None:
        kr_path = Path(__file__).resolve().parent / "web" / "KrStates.csv"
        if kr_path.exists():
            st.session_state["reference_krstates"] = _load_reference_csv(kr_path)
