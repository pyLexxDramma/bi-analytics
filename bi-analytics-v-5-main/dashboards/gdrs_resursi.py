# -*- coding: utf-8 -*-
"""
B-16/17 ГДРС (2026-05-07) — загрузка ресурсов и агрегация план/факт по СКУДу.

Источники:
  • web/AI/other_<DD-MM-YYYY>_resursi.csv
        - один файл = один календарный месяц.
        - формат: 1-я строка — «надстрока» (1 неделя | 2 неделя | …),
          2-я строка — заголовки колонок: ID Проекта | Наименование проекта |
          Подрядчик (ИЛИ ID Подрядчика + Подрядчик_new + Подрядчик_old) |
          Тип ресурсов (рабочие/техника) | <дата1> | <дата2> | … | <Тип ресурсов>.
        - данные начинаются с 3-й строки.
        - встречается 3 формата шапки (январь — c колонкой «среднее значение за день»
          внутри каждой недели; март — без неё; апрель — расширенный набор колонок
          подрядчика).

  • web/1с_<...>_Dogovor.json
        - список договоров; ключевые поля: ID_Контрагента, ID_Проекта,
          Наименование_Контрагента, Наименование_Проекта, Наименование_Договора,
          Количество_Людей, Количество_Техники, Дата_Начала_Договора,
          Дата_Окончания_Договора, Сумма_Договора.
        - используется как ПЛАН по ключу (ID_Проекта, ID_Контрагента).

  • web/1с_<...>_spravochniki.json
        - fallback для ПЛАНа (КоличествоРаботников / КоличествоСпецТехники)
          по ключу (ID_Проекта, ID_Контрагента).

Архитектура (long-формат):
    long DataFrame: project_id, project_name, contractor_id, contractor_name,
    vid_resursa ∈ {"Рабочие","Техника"}, date (datetime), fact (float).

    Дополнительно к long-факту строится PLAN-таблица per (project_id × contractor_id × vid).

API:
    load_resursi_files(paths) -> long_fact_df
    load_plan_from_dogovor(json_path) -> plan_df
    load_plan_from_spravochniki(json_path) -> plan_df
    merge_plan(dogovor_plan, sprav_plan) -> plan_df  (Dogovor приоритет, fallback Sprav)
    build_main_table(long, plan, period_from, period_to, vid)  (Таб 1, Скрин 11)
    build_summary_table(long, plan, …)                          (Таб 3, Скрин 5)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

# =====================================================================
# Парсер resursi.csv
# =====================================================================

_DATE_RE = re.compile(r"^(\d{1,2})\.{1,2}(\d{1,2})\.(\d{2}|\d{4})$")


def _is_date_label(val: object) -> bool:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return False
    s = str(val).strip()
    return bool(_DATE_RE.match(s))


def _is_avg_label(val: object) -> bool:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return False
    return "сред" in str(val).strip().lower()


def _parse_date_label(val: object) -> Optional[pd.Timestamp]:
    if not _is_date_label(val):
        return None
    s = str(val).strip().replace("..", ".")
    try:
        return pd.to_datetime(s, dayfirst=True, errors="coerce")
    except Exception:
        return None


def _read_csv_best_effort(path: Path) -> pd.DataFrame:
    """Читает CSV не интерпретируя 1-ю строку как заголовок (header=None)."""
    last_err: Optional[Exception] = None
    for enc in ("utf-8-sig", "utf-8", "cp1251", "cp866"):
        for sep in (";", ",", "\t", "|"):
            try:
                df = pd.read_csv(
                    path,
                    encoding=enc,
                    sep=sep,
                    header=None,
                    engine="python",
                    dtype=str,
                    keep_default_na=False,
                )
                if df.shape[1] >= 4:
                    return df
            except Exception as e:
                last_err = e
                continue
    if last_err is not None:
        raise last_err
    return pd.DataFrame()


@dataclass
class _ResursiSchema:
    """Схема одного `resursi.csv`: позиции колонок и список (col_idx, date)."""
    col_id_project: Optional[int]  # None если в файле нет колонки «ID Проекта»
    col_name_project: int
    col_contractor: int  # позиция «человекочитаемого» названия подрядчика
    col_id_contractor: Optional[int]  # отдельная колонка ID подрядчика, если есть
    col_vid: int  # позиция колонки «Тип ресурсов»
    date_columns: list[tuple[int, pd.Timestamp]]
    header_row: int  # индекс строки с заголовками (0-based)


def _detect_schema(df_raw: pd.DataFrame) -> Optional[_ResursiSchema]:
    """Найти строку-заголовок (где есть «ID Проекта» или «Наименование проекта»)."""
    if df_raw.empty:
        return None
    n_scan = min(6, len(df_raw))
    date_row = None
    best_count = 0
    for r in range(n_scan):
        row = df_raw.iloc[r].tolist()
        cnt = sum(1 for v in row if _is_date_label(v))
        if cnt > best_count:
            best_count = cnt
            date_row = r
    if date_row is None or best_count == 0:
        return None

    text_row = None
    for r in range(date_row, -1, -1):
        row = df_raw.iloc[r].astype(str).str.strip().str.lower()
        if any(
            ("id проекта" in v) or ("наименование проекта" in v) or (v == "проект")
            for v in row
        ):
            text_row = r
            break
    if text_row is None:
        return None

    header_row = max(text_row, date_row)
    above_rows = df_raw.iloc[: header_row + 1].astype(str).fillna("")
    combined_headers: list[str] = []
    for col in range(df_raw.shape[1]):
        parts = []
        for r in range(header_row + 1):
            v = above_rows.iloc[r, col].strip() if col < above_rows.shape[1] else ""
            if v and v.lower() not in {"nan", "none"} and v not in parts:
                parts.append(v)
        combined_headers.append(" | ".join(parts))
    headers = combined_headers
    headers_norm = [h.strip().lower() for h in headers]

    def _find_first(*kws: str, exclude_idx: Optional[int] = None) -> Optional[int]:
        for i, h in enumerate(headers_norm):
            if i == exclude_idx:
                continue
            if all(k in h for k in kws):
                return i
        return None

    col_id_project = _find_first("id", "проект")
    if col_id_project is None:
        col_id_project = _find_first("идентификатор", "проект")
    col_name_project = _find_first("наименование", "проект")
    if col_name_project is None:
        col_name_project = _find_first("проект", exclude_idx=col_id_project)

    col_id_contractor = _find_first("id", "подряд")
    col_contractor_new = _find_first("подрядчик_new")
    col_contractor_old = _find_first("подрядчик_old")
    col_contractor = col_contractor_new or _find_first("подряд", exclude_idx=col_id_contractor)
    if col_contractor is None and col_contractor_old is not None:
        col_contractor = col_contractor_old
    col_vid = _find_first("тип", "ресурс")

    if col_name_project is None or col_contractor is None or col_vid is None:
        return None

    date_row_values = df_raw.iloc[date_row].tolist()
    date_columns: list[tuple[int, pd.Timestamp]] = []
    for i, raw in enumerate(date_row_values):
        ts = _parse_date_label(raw)
        if ts is not None:
            date_columns.append((i, ts))
    if not date_columns:
        return None

    return _ResursiSchema(
        col_id_project=col_id_project,
        col_name_project=col_name_project,
        col_contractor=col_contractor,
        col_id_contractor=col_id_contractor,
        col_vid=col_vid,
        date_columns=date_columns,
        header_row=header_row,
    )


_NAME_NOISE_RE = re.compile(r"[\s\.,\-_/\\\"'«»()\[\]]+")
_NAME_LEGAL_RE = re.compile(
    r"\b(ооо|ао|зао|пао|оао|ип|оу|ук|нко|спк|кфх|апсх|нпф|чоп|снт|тсж)\b",
    re.IGNORECASE,
)


def normalize_name(s: object) -> str:
    """Нормализация названия (контрагента, проекта) для fuzzy-match.

    Убирает легальный префикс/суффикс ООО/АО/ЗАО/…, регистр, пробелы,
    скобочные пояснения, кавычки.
    Примеры:
      «ООО Альфа С (БЛОК U3 U4)»  → «альфас»
      «АЛЬФА С ООО»                → «альфас»
      «ООО "СК Сети"»              → «сксети»
      «АО Марафон»                 → «марафон»
    """
    if s is None:
        return ""
    txt = str(s).strip()
    if not txt:
        return ""
    txt = re.sub(r"\(.*?\)", " ", txt)
    txt = txt.replace("«", " ").replace("»", " ").replace('"', " ").replace("'", " ")
    txt = _NAME_LEGAL_RE.sub(" ", txt)
    txt = _NAME_NOISE_RE.sub("", txt).casefold()
    return txt


def _normalize_vid(raw: object) -> str:
    """Нормализация значения «Тип ресурсов» → 'Рабочие' | 'Техника' | ''."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    s = str(raw).strip().lower()
    if not s:
        return ""
    if "рабоч" in s or "люд" in s or "people" in s or "worker" in s:
        return "Рабочие"
    if "техн" in s or "машин" in s or "механ" in s or "оборуд" in s or "equip" in s:
        return "Техника"
    return ""


def _coerce_int(val: object) -> Optional[float]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def load_resursi_file(path: Path) -> pd.DataFrame:
    """Загрузить один resursi.csv → long DataFrame.

    Возвращаемые столбцы:
        project_id, project_name, contractor_id (опц., может быть пустой строкой),
        contractor_name, vid_resursa ∈ {Рабочие, Техника}, date (datetime), fact (float).
    """
    raw = _read_csv_best_effort(Path(path))
    schema = _detect_schema(raw)
    if schema is None:
        return pd.DataFrame(
            columns=[
                "project_id", "project_name", "contractor_id",
                "contractor_name", "vid_resursa", "date", "fact",
            ]
        )

    body = raw.iloc[schema.header_row + 1 :].reset_index(drop=True).copy()
    out_rows: list[dict] = []
    for _, row in body.iterrows():
        proj_id = (
            str(row.iloc[schema.col_id_project]).strip()
            if schema.col_id_project is not None
            else ""
        )
        proj_name = str(row.iloc[schema.col_name_project]).strip()
        if not proj_name or proj_name.lower() in {"nan", "none"}:
            continue
        contractor_id = (
            str(row.iloc[schema.col_id_contractor]).strip()
            if schema.col_id_contractor is not None
            else ""
        )
        contractor_name = str(row.iloc[schema.col_contractor]).strip()
        if not contractor_name or contractor_name.lower() in {"nan", "none"}:
            continue
        vid = _normalize_vid(row.iloc[schema.col_vid])
        if not vid:
            continue
        for col_idx, ts in schema.date_columns:
            if col_idx >= len(row):
                continue
            v = _coerce_int(row.iloc[col_idx])
            if v is None:
                continue
            out_rows.append(
                {
                    "project_id": proj_id,
                    "project_name": proj_name,
                    "contractor_id": contractor_id,
                    "contractor_name": contractor_name,
                    "vid_resursa": vid,
                    "date": ts,
                    "fact": float(v),
                }
            )
    if not out_rows:
        return pd.DataFrame(
            columns=[
                "project_id", "project_name", "contractor_id",
                "contractor_name", "vid_resursa", "date", "fact",
            ]
        )
    out = pd.DataFrame(out_rows)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out[out["date"].notna()].copy()
    return out


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_uuid_like(s: object) -> bool:
    if s is None:
        return False
    return bool(_UUID_RE.match(str(s).strip()))


def _pick_canonical_name(names: pd.Series) -> Optional[str]:
    """Самое популярное (mode) НЕ-UUID имя в серии. Используется для канонизации."""
    cnt = names.value_counts()
    cnt = cnt[~cnt.index.to_series().apply(_is_uuid_like)]
    if cnt.empty:
        return None
    return str(cnt.idxmax())


def _canonicalize_project_names(df: pd.DataFrame) -> pd.DataFrame:
    """Подменяет UUID-подобные `project_name` на каноническое человекочитаемое имя.
    Канонический выбор — самое популярное не-UUID имя для того же `project_id`,
    или (если ID нет/пуст) — самое популярное по нормализованному имени.
    Также схлопывает варианты типа «Дмитровский1» / «Дмитровский-1».
    """
    if df is None or df.empty:
        return df
    work = df.copy()
    work["__name_norm__"] = work["project_name"].astype(str).map(normalize_name)

    by_id: dict[str, str] = {}
    for pid, grp in work[work["project_id"].astype(str).str.strip() != ""].groupby("project_id"):
        canon = _pick_canonical_name(grp["project_name"].astype(str))
        if canon:
            by_id[str(pid).strip()] = canon
    by_norm: dict[str, str] = {}
    for nn, grp in work.groupby("__name_norm__"):
        canon = _pick_canonical_name(grp["project_name"].astype(str))
        if canon:
            by_norm[str(nn)] = canon

    def _resolve(row) -> str:
        name = str(row["project_name"]).strip()
        pid = str(row["project_id"]).strip()
        if _is_uuid_like(name):
            return by_id.get(pid, name)
        return by_norm.get(str(row["__name_norm__"]), name)

    work["project_name"] = work.apply(_resolve, axis=1)
    work = work.drop(columns="__name_norm__")
    return work


def _fuzzy_cluster(norms: list[str], cutoff: float = 0.86) -> dict[str, str]:
    """Строит DSU-кластеры по фуззи-похожести нормализованных имён.
    Возвращает маппинг norm → root_norm (по самому раннему совпадению в списке).

    Помогает схлопнуть typo подрядчиков 1С:
      «констракшн» ↔ «контракшн» ↔ «констракшен»
    """
    import difflib as _dl

    parent: dict[str, str] = {n: n for n in norms}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra == rb:
            return
        if len(ra) <= len(rb):
            parent[rb] = ra
        else:
            parent[ra] = rb

    for n in norms:
        if not n:
            continue
        for m in _dl.get_close_matches(n, norms, n=5, cutoff=cutoff):
            if m != n:
                _union(n, m)
    return {n: _find(n) for n in norms}


def _canonicalize_contractor_names(df: pd.DataFrame) -> pd.DataFrame:
    """Схлопывает разные написания имени контрагента в одно каноническое.
    Этапы:
      (1) точное совпадение `normalize_name` — «ООО СК Сети» / «СК СЕТИ ООО».
      (2) фуззи (difflib, cutoff 0.86) — typo «Констракшн/Контракшн/Констракшен».
    Канонический выбор — самое популярное по числу строк (value_counts.idxmax).

    Дополнительно: если у каноники имеется не-пустой `contractor_id` хотя бы в одной
    строке — заполняем им пустые `contractor_id` тех же строк (нужно для матчинга плана).
    """
    if df is None or df.empty:
        return df
    work = df.copy()
    work["__cn_norm__"] = work["contractor_name"].astype(str).map(normalize_name)
    norms_unique = sorted({n for n in work["__cn_norm__"].unique() if n})
    fuzzy_root = _fuzzy_cluster(norms_unique, cutoff=0.93)
    work["__cn_root__"] = work["__cn_norm__"].map(lambda x: fuzzy_root.get(x, x))

    by_root_name: dict[str, str] = {}
    by_root_id: dict[str, str] = {}
    for root, grp in work.groupby("__cn_root__"):
        if not root:
            continue
        canon = _pick_canonical_name(grp["contractor_name"].astype(str))
        if canon:
            by_root_name[str(root)] = canon
        ids = [i for i in grp["contractor_id"].astype(str).str.strip().unique() if i]
        if ids:
            by_root_id[str(root)] = ids[0]

    def _name(row) -> str:
        root = str(row["__cn_root__"])
        return by_root_name.get(root, str(row["contractor_name"]).strip())

    def _id(row) -> str:
        cur = str(row["contractor_id"]).strip()
        if cur:
            return cur
        return by_root_id.get(str(row["__cn_root__"]), "")

    work["contractor_name"] = work.apply(_name, axis=1)
    work["contractor_id"] = work.apply(_id, axis=1)
    work = work.drop(columns=["__cn_norm__", "__cn_root__"])
    return work


def load_resursi_files(paths: Iterable[Path | str]) -> pd.DataFrame:
    frames = []
    for p in paths:
        try:
            df = load_resursi_file(Path(p))
        except Exception:
            df = pd.DataFrame()
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(
            columns=[
                "project_id", "project_name", "contractor_id",
                "contractor_name", "vid_resursa", "date", "fact",
            ]
        )
    out = pd.concat(frames, ignore_index=True)
    out = _canonicalize_project_names(out)
    out = _canonicalize_contractor_names(out)
    out = out.drop_duplicates(
        subset=["project_name", "contractor_name", "vid_resursa", "date"], keep="last"
    )
    return out


# =====================================================================
# Парсер плана (Dogovor.json + spravochniki.json fallback)
# =====================================================================

def _safe_json(path: Path) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except Exception:
            return None


def _snapshot_history(history: object, target_date: Optional[pd.Timestamp]) -> Optional[float]:
    """Из истории `[{'Дата': 'YYYY-MM-DD', 'Количество': 'N'}, ...]` взять последнее значение
    с `Дата <= target_date`. Если history скаляр — вернуть его. Если target_date is None —
    вернуть последнее значение в истории.
    """
    if history is None:
        return None
    if isinstance(history, (int, float)):
        return float(history)
    if isinstance(history, str):
        return _coerce_int(history)
    if not isinstance(history, list) or not history:
        return None
    items = []
    for item in history:
        if not isinstance(item, dict):
            continue
        d_raw = item.get("Дата") or item.get("дата")
        n_raw = item.get("Количество") or item.get("количество")
        d = pd.to_datetime(d_raw, errors="coerce", format="ISO8601")
        if pd.isna(d):
            d = pd.to_datetime(d_raw, errors="coerce", dayfirst=True)
        n = _coerce_int(n_raw)
        if pd.isna(d) or n is None:
            continue
        items.append((d, n))
    if not items:
        return None
    items.sort(key=lambda x: x[0])
    if target_date is None:
        return float(items[-1][1])
    candidates = [n for d, n in items if d <= target_date]
    if candidates:
        return float(candidates[-1])
    return None


def load_plan_from_dogovor(
    path: Path,
    *,
    snapshot_date: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Из 1с_*_Dogovor.json (по состоянию на `snapshot_date`) → DataFrame.

    Поля «Количество_Людей» и «Количество_Техники» — массивы вида
    `[{Дата: ..., Количество: ...}, ...]`. snapshot берётся «не позднее snapshot_date».
    Если snapshot_date is None — берётся последнее значение.
    """
    data = _safe_json(Path(path))
    if not isinstance(data, list):
        return pd.DataFrame(
            columns=[
                "project_id", "contractor_id", "project_name", "contractor_name",
                "contract_name", "plan_workers", "plan_equipment", "date_start", "date_end",
            ]
        )
    rows = []
    for r in data:
        if not isinstance(r, dict):
            continue
        rows.append(
            {
                "project_id": str(r.get("ID_Проекта") or "").strip(),
                "contractor_id": str(r.get("ID_Контрагента") or "").strip(),
                "project_name": str(r.get("Наименование_Проекта") or "").strip(),
                "contractor_name": str(r.get("Наименование_Контрагента") or "").strip(),
                "contract_name": str(r.get("Наименование_Договора") or "").strip(),
                "plan_workers": _snapshot_history(r.get("Количество_Людей"), snapshot_date),
                "plan_equipment": _snapshot_history(r.get("Количество_Техники"), snapshot_date),
                "date_start": pd.to_datetime(r.get("Дата_Начала_Договора"), errors="coerce", utc=True),
                "date_end": pd.to_datetime(r.get("Дата_Окончания_Договора"), errors="coerce", utc=True),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date_start"] = pd.to_datetime(df["date_start"], errors="coerce").dt.tz_localize(None)
    df["date_end"] = pd.to_datetime(df["date_end"], errors="coerce").dt.tz_localize(None)
    return df


def load_plan_from_spravochniki(
    path: Path,
    *,
    snapshot_date: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Из 1с_*_spravochniki.json (snapshot на дату) → DataFrame с агрегированным планом.

    «КоличествоРаботников» и «КоличествоСпецТехники» — массивы вида
    `[{Дата, Количество}, ...]`.
    """
    data = _safe_json(Path(path))
    if not isinstance(data, list):
        return pd.DataFrame(columns=["project_id", "contractor_id", "plan_workers", "plan_equipment"])
    rows = []
    for r in data:
        if not isinstance(r, dict):
            continue
        rows.append(
            {
                "project_id": str(r.get("ID_Проекта") or "").strip(),
                "contractor_id": str(r.get("ID_Контрагента") or "").strip(),
                "plan_workers": _snapshot_history(r.get("КоличествоРаботников"), snapshot_date),
                "plan_equipment": _snapshot_history(r.get("КоличествоСпецТехники"), snapshot_date),
            }
        )
    return pd.DataFrame(rows)


def load_plan_aggregate(
    dogovor_paths: Iterable[Path | str],
    sprav_paths: Iterable[Path | str],
    *,
    snapshot_date: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Загрузить план из ВСЕХ файлов Dogovor.json + spravochniki.json
    и агрегировать в единую таблицу.

    Преимущество перед `merge_plan(load_dogovor(last), load_sprav(last))`: 
    некоторые контрагенты/договоры могут отсутствовать в одном snapshot,
    но присутствовать в другом — берём максимум знания.

    Алгоритм:
        - Для каждого Dogovor.json берём snapshot на дату snapshot_date.
        - Объединяем по (project_id, contractor_id), беря MAX `plan_workers/equipment`
          (если в одном snapshot план был, а в другом None — оставляем имеющееся).
        - Аналогично для spravochniki.json (как fallback, если Dogovor=None).
    """
    def _per_file_dog(p: Path) -> pd.DataFrame:
        df = load_plan_from_dogovor(Path(p), snapshot_date=snapshot_date)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df[(df["project_id"].astype(str).str.strip() != "") | (df["contractor_id"].astype(str).str.strip() != "")]
        if df.empty:
            return pd.DataFrame()
        return (
            df.groupby(["project_id", "contractor_id"], dropna=False, as_index=False)
            .agg(
                project_name=("project_name", "first"),
                contractor_name=("contractor_name", "first"),
                contract_name=("contract_name", lambda s: " · ".join(sorted({x for x in s if x}))),
                plan_workers=("plan_workers", lambda s: float(np.nansum(s)) if any(pd.notna(s)) else np.nan),
                plan_equipment=("plan_equipment", lambda s: float(np.nansum(s)) if any(pd.notna(s)) else np.nan),
            )
        )

    def _per_file_sprav(p: Path) -> pd.DataFrame:
        df = load_plan_from_spravochniki(Path(p), snapshot_date=snapshot_date)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df[(df["project_id"].astype(str).str.strip() != "") & (df["contractor_id"].astype(str).str.strip() != "")]
        if df.empty:
            return pd.DataFrame()
        return (
            df.groupby(["project_id", "contractor_id"], dropna=False, as_index=False)
            .agg(
                plan_workers=("plan_workers", lambda s: float(np.nansum(s)) if any(pd.notna(s)) else np.nan),
                plan_equipment=("plan_equipment", lambda s: float(np.nansum(s)) if any(pd.notna(s)) else np.nan),
            )
        )

    dogovor_frames = [_per_file_dog(p) for p in dogovor_paths]
    dogovor_frames = [d for d in dogovor_frames if not d.empty]
    sprav_frames = [_per_file_sprav(p) for p in sprav_paths]
    sprav_frames = [d for d in sprav_frames if not d.empty]

    dog_all = pd.concat(dogovor_frames, ignore_index=True) if dogovor_frames else pd.DataFrame()
    sprav_all = pd.concat(sprav_frames, ignore_index=True) if sprav_frames else pd.DataFrame()

    if not dog_all.empty:
        dog_all = (
            dog_all.groupby(["project_id", "contractor_id"], dropna=False, as_index=False)
            .agg(
                project_name=("project_name", "first"),
                contractor_name=("contractor_name", "first"),
                contract_name=("contract_name", lambda s: " · ".join(sorted({x for x in s if x}))),
                plan_workers=("plan_workers", "max"),
                plan_equipment=("plan_equipment", "max"),
            )
        )
    if not sprav_all.empty:
        sprav_all = (
            sprav_all.groupby(["project_id", "contractor_id"], dropna=False, as_index=False)
            .agg(plan_workers=("plan_workers", "max"), plan_equipment=("plan_equipment", "max"))
        )
    return merge_plan(dog_all, sprav_all)


def merge_plan(dogovor: pd.DataFrame, sprav: pd.DataFrame) -> pd.DataFrame:
    """Слить план из Dogovor (приоритет) и spravochniki (fallback) per (project_id, contractor_id).

    Если у нескольких договоров на один (project_id, contractor_id) есть план — суммируем.
    """
    if dogovor is None or dogovor.empty:
        d = pd.DataFrame(
            columns=[
                "project_id", "contractor_id", "project_name", "contractor_name",
                "contract_name", "plan_workers", "plan_equipment",
            ]
        )
    else:
        d = (
            dogovor.groupby(["project_id", "contractor_id"], dropna=False, as_index=False)
            .agg(
                project_name=("project_name", "first"),
                contractor_name=("contractor_name", "first"),
                contract_name=("contract_name", lambda s: " · ".join(sorted({x for x in s if x}))),
                plan_workers=("plan_workers", lambda s: float(np.nansum(s)) if any(pd.notna(s)) else None),
                plan_equipment=("plan_equipment", lambda s: float(np.nansum(s)) if any(pd.notna(s)) else None),
            )
        )
    if sprav is not None and not sprav.empty:
        s = (
            sprav.groupby(["project_id", "contractor_id"], dropna=False, as_index=False)
            .agg(
                plan_workers_s=("plan_workers", lambda s: float(np.nansum(s)) if any(pd.notna(s)) else None),
                plan_equipment_s=("plan_equipment", lambda s: float(np.nansum(s)) if any(pd.notna(s)) else None),
            )
        )
        merged = d.merge(s, on=["project_id", "contractor_id"], how="outer")
        merged["plan_workers"] = merged["plan_workers"].combine_first(merged["plan_workers_s"])
        merged["plan_equipment"] = merged["plan_equipment"].combine_first(merged["plan_equipment_s"])
        merged = merged.drop(columns=["plan_workers_s", "plan_equipment_s"], errors="ignore")
        return merged
    return d


# =====================================================================
# Сборка таблицы (Скрин 11)
# =====================================================================

def _build_plan_lookup(plan: Optional[pd.DataFrame], plan_col: str) -> tuple[dict, dict, dict]:
    """Возвращает три словаря для матчинга плана:
    by_id        — (project_id, contractor_id)         → plan_value
    by_id_name   — (project_id, contractor_name_norm)  → plan_value
    by_norm_name — (project_name_norm, contractor_name_norm) → plan_value
    Также contract_lookup_by_norm — для подписи «Вид работы» (Наименование_Договора).
    """
    by_id: dict = {}
    by_id_name: dict = {}
    by_norm_name: dict = {}
    contract_by_norm: dict = {}
    if plan is None or plan.empty:
        return by_id, by_id_name, by_norm_name
    for _, p in plan.iterrows():
        v = p.get(plan_col)
        if v is None or pd.isna(v):
            continue
        try:
            v = float(v)
        except Exception:
            continue
        proj_id = str(p.get("project_id", "")).strip()
        contr_id = str(p.get("contractor_id", "")).strip()
        proj_norm = normalize_name(p.get("project_name", ""))
        contr_norm = normalize_name(p.get("contractor_name", ""))
        contract_name = str(p.get("contract_name", "")).strip() if "contract_name" in p else ""
        if proj_id and contr_id:
            by_id[(proj_id, contr_id)] = by_id.get((proj_id, contr_id), 0.0) + v
        if proj_id and contr_norm:
            by_id_name[(proj_id, contr_norm)] = by_id_name.get((proj_id, contr_norm), 0.0) + v
        if proj_norm and contr_norm:
            by_norm_name[(proj_norm, contr_norm)] = by_norm_name.get((proj_norm, contr_norm), 0.0) + v
        if contract_name and proj_norm and contr_norm:
            existing = contract_by_norm.get((proj_norm, contr_norm), "")
            if contract_name not in existing:
                contract_by_norm[(proj_norm, contr_norm)] = (
                    f"{existing} · {contract_name}".strip(" ·") if existing else contract_name
                )
    by_id_name["__contract_by_norm__"] = contract_by_norm  # piggyback
    return by_id, by_id_name, by_norm_name


def _lookup_plan(
    project_id: str,
    contractor_id: str,
    project_name: str,
    contractor_name: str,
    by_id: dict,
    by_id_name: dict,
    by_norm: dict,
    *,
    fuzzy_threshold: float = 0.86,
) -> float:
    """Многоуровневый матчинг плана:
    1) точно по (project_id, contractor_id);
    2) точно по (project_id, contractor_name_norm);
    3) точно по (project_name_norm, contractor_name_norm);
    4) фуззи по (project_name_norm, contractor_name_norm) — difflib SequenceMatcher
       (typo: «Констракшн»↔«Контракшн», «Констракшн»↔«Констракшен» и т.п.).
    """
    import difflib as _dl

    pid, cid = str(project_id or "").strip(), str(contractor_id or "").strip()
    if pid and cid and (pid, cid) in by_id:
        return float(by_id[(pid, cid)])
    cn = normalize_name(contractor_name)
    if pid and cn and (pid, cn) in by_id_name:
        return float(by_id_name[(pid, cn)])
    pn = normalize_name(project_name)
    if pn and cn and (pn, cn) in by_norm:
        return float(by_norm[(pn, cn)])
    if pn and cn and by_norm:
        candidates = [k_cn for (k_pn, k_cn) in by_norm.keys() if k_pn == pn and k_cn != "__contract_by_norm__"]
        if candidates:
            best = _dl.get_close_matches(cn, candidates, n=1, cutoff=fuzzy_threshold)
            if best:
                return float(by_norm[(pn, best[0])])
    return 0.0


def _lookup_contract_name(
    project_name: str,
    contractor_name: str,
    by_id_name: dict,
) -> str:
    contract_by_norm: dict = by_id_name.get("__contract_by_norm__", {}) or {}
    pn = normalize_name(project_name)
    cn = normalize_name(contractor_name)
    return str(contract_by_norm.get((pn, cn), "") or "")


# ТЗ заказчика 2026-05-08 (скрин ГДРС): расширен список паттернов
# для «Вид работы» — добавлены ЛЭП, АЦБ, ЗОМ и ГРЩ (через «и»),
# Вертикальная планировка, ВК (наружные сети), ИИВ, Газопровод
# (ГСВ/ГСН/ГСЗ), ИНК; добавлен fallback «БЛОК X» (без префикса «СМР»),
# т.к. в реальных contract_name из 1С чаще встречается «АЛЬФА-С БЛОК А»,
# «БЛОК U3U4», а не «СМР Блок A». Без fallback покрытие было ~2%.
_VID_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("СМР Блок", re.compile(r"\b(?:смр|cmp)[\s\-_]*блок[\s\-_]*[a-zа-яёA-ZА-ЯЁ0-9]+", re.IGNORECASE)),
    ("АУПТ", re.compile(r"\bаупт\b", re.IGNORECASE)),
    ("АЦБ", re.compile(r"\bацб\b", re.IGNORECASE)),
    ("ВОС", re.compile(r"\bв\.?\s?о\.?\s?с\b", re.IGNORECASE)),
    ("ЛЭП", re.compile(r"\bлэп\b", re.IGNORECASE)),
    ("ЗОМ и ГРЩ", re.compile(r"\bзом[\s\+иand]+грщ\b", re.IGNORECASE)),
    ("Вынос сетей", re.compile(r"вынос\s+сетей", re.IGNORECASE)),
    ("Газоразрядка котельной", re.compile(r"газоразрядк", re.IGNORECASE)),
    ("Газопровод (ГСВ/ГСН)", re.compile(r"газопровод|\bгсв\b|\bгсн\b|\bгсз\b", re.IGNORECASE)),
    ("Вертикальная планировка", re.compile(r"вертикальн\w*\s+планир", re.IGNORECASE)),
    ("ВК (наружные сети)", re.compile(r"\bвк\b[\s\-_]*\(?\s*наруж", re.IGNORECASE)),
    ("ИНК", re.compile(r"\bинк\b", re.IGNORECASE)),
    ("ИИВ", re.compile(r"\bиив\b", re.IGNORECASE)),
    ("Огнезащита", re.compile(r"огнезащит", re.IGNORECASE)),
    ("Благоустройство", re.compile(r"благоустр", re.IGNORECASE)),
    ("Подпорные стены", re.compile(r"подпорн", re.IGNORECASE)),
    ("ЛК ввод/вывод", re.compile(r"ливневая\s+канал", re.IGNORECASE)),
    ("НВК", re.compile(r"\bнвк\b", re.IGNORECASE)),
    ("НПС/ПС/Эксплуатация", re.compile(r"\b(нпс|пс|эксплуатац)\b", re.IGNORECASE)),
    ("Электрооборудование", re.compile(r"электрообор|эл\.\s?обор|электросн", re.IGNORECASE)),
    ("Монтаж резервуара", re.compile(r"монтаж\s+резервуар", re.IGNORECASE)),
    ("Мобилизация", re.compile(r"мобилизац", re.IGNORECASE)),
    # Fallback: «БЛОК X» (X = A/B/C/D/E/F/G/U/U1/U2/U3U4/0/1/2/3/4/5).
    # Должен идти ПОСЛЕДНИМ — иначе перехватит более точные «СМР Блок».
    ("Блок", re.compile(r"\bблок[\s\-_]*[a-zа-яёA-ZА-ЯЁ0-9]+", re.IGNORECASE)),
]


def extract_vid_raboty(contract_name: str) -> str:
    """Из `Наименование_Договора` извлечь «Вид работы» по эвристикам ТЗ заказчика.

    Примеры:
      «Дог. № 28-СА/25 от 22.07.25 (Есипово-5) СМР Блок А, АУПТ» → «СМР Блок А · АУПТ».
      «… Вынос сетей …» → «Вынос сетей».
      «… ШТРАФ» → «—».
    Если ничего не извлечь — возвращает пустую строку (UI отображает «—»).
    """
    if not contract_name:
        return ""
    s = str(contract_name).strip()
    if not s:
        return ""
    matches = []
    for label, pat in _VID_PATTERNS:
        for m in pat.finditer(s):
            txt = m.group(0).strip()
            # Для паттернов, содержащих «блок», возвращаем буквальный
            # текст совпадения (например, «БЛОК A», «Блок U3U4») —
            # чтобы различать разные блоки в рамках одного контрагента.
            # Для остальных — фиксированный label.
            matches.append(txt if "блок" in label.lower() else label)
    if matches:
        seen = []
        for m in matches:
            if m not in seen:
                seen.append(m)
        return " · ".join(seen)
    return ""


def _iso_week_groups(dates: pd.Series) -> tuple[pd.Series, dict[int, int]]:
    """Для серии дат (выборка одного отчётного периода) возвращает:
       (1) Series — порядковый номер ISO-недели в выборке (1..N), 1 = самая ранняя.
       (2) dict   — {номер_недели : число_дней_в_неделе_в_выборке}.
    """
    iso = dates.dt.isocalendar()
    key = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    sorted_keys = sorted(set(key.dropna().tolist()))
    key_to_idx = {k: i + 1 for i, k in enumerate(sorted_keys)}
    week_idx = key.map(key_to_idx).fillna(0).astype(int)
    days_per_week: dict[int, int] = {}
    for k, idx in key_to_idx.items():
        mask = key == k
        days_per_week[idx] = int(dates[mask].dt.normalize().nunique())
    return week_idx, days_per_week


def build_main_table(
    long_fact: pd.DataFrame,
    plan: pd.DataFrame,
    *,
    vid: str,
    date_from: Optional[pd.Timestamp] = None,
    date_to: Optional[pd.Timestamp] = None,
    projects: Optional[list[str]] = None,
    contractors: Optional[list[str]] = None,
    only_with_plan: bool = False,
) -> pd.DataFrame:
    """Сборка главной таблицы (Скрин 11): Контрагент × недели × отклонение × дельта.

    Возвращает DataFrame с колонками:
        project_name, contractor_name, contract_name,
        plan, skud, deviation, w1..w6, delta_pct, row_kind ∈ {"row","subtotal","grand_total"}.

    Логика расчёта:
    - Неделя = ISO-неделя; нумерация в порядке возрастания внутри выборки (1..6 для месяца).
    - weekly_avg(подрядчик, неделя) = ∑ daily / N_дней_в_неделе_в_выборке.
    - skud(подрядчик)              = ∑ daily / N_всех_дней_в_выборке (= «Факт / СКУД» среднее за день).
    - deviation                       = План − skud; delta_pct = (deviation / План) × 100 (при План≠0).
    - subtotal(проект, неделя)     = ∑ weekly_avg по подрядчикам.
    - subtotal(проект, СКУД)       = ∑ skud по подрядчикам.
    """
    if long_fact is None or long_fact.empty:
        return pd.DataFrame()
    fact = long_fact[long_fact["vid_resursa"].astype(str).str.casefold() == vid.casefold()].copy()
    if fact.empty:
        return pd.DataFrame()
    if date_from is not None:
        fact = fact[fact["date"] >= pd.to_datetime(date_from)]
    if date_to is not None:
        fact = fact[fact["date"] <= pd.to_datetime(date_to)]
    if projects:
        proj_keys = {p.strip().casefold() for p in projects}
        fact = fact[fact["project_name"].astype(str).str.strip().str.casefold().isin(proj_keys)]
    if contractors:
        c_keys = {c.strip().casefold() for c in contractors}
        fact = fact[fact["contractor_name"].astype(str).str.strip().str.casefold().isin(c_keys)]
    if fact.empty:
        return pd.DataFrame()

    plan_col = "plan_workers" if vid.casefold() == "рабочие" else "plan_equipment"
    by_id, by_id_name, by_norm = _build_plan_lookup(plan, plan_col)

    fact["date"] = pd.to_datetime(fact["date"])
    week_idx, days_per_week = _iso_week_groups(fact["date"])
    fact["week"] = week_idx
    total_days = int(fact["date"].dt.normalize().nunique())

    id_pick = (
        fact.groupby(["project_name", "contractor_name"], dropna=False)
        .agg(
            project_id=("project_id", lambda s: next((x for x in s.astype(str) if x.strip()), "")),
            contractor_id=("contractor_id", lambda s: next((x for x in s.astype(str) if x.strip()), "")),
        )
        .reset_index()
    )

    week_sum = (
        fact.groupby(["project_name", "contractor_name", "week"], dropna=False)["fact"]
        .sum()
        .reset_index(name="daily_sum")
    )
    week_sum["weekly_avg"] = week_sum.apply(
        lambda r: r["daily_sum"] / max(1, days_per_week.get(int(r["week"]), 1)), axis=1
    )

    pivot = week_sum.pivot_table(
        index=["project_name", "contractor_name"],
        columns="week",
        values="weekly_avg",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    for w in (1, 2, 3, 4, 5, 6):
        if w not in pivot.columns:
            pivot[w] = 0.0
    pivot.rename(columns={1: "w1", 2: "w2", 3: "w3", 4: "w4", 5: "w5", 6: "w6"}, inplace=True)

    skud_per = (
        fact.groupby(["project_name", "contractor_name"], dropna=False)["fact"]
        .sum()
        .reset_index(name="skud_sum")
    )
    skud_per["skud_avg"] = skud_per["skud_sum"] / max(1, total_days)

    rows = pivot.merge(skud_per, on=["project_name", "contractor_name"], how="left")
    rows = rows.merge(id_pick, on=["project_name", "contractor_name"], how="left")

    rows["plan"] = rows.apply(
        lambda r: _lookup_plan(
            str(r.get("project_id", "")), str(r.get("contractor_id", "")),
            str(r.get("project_name", "")), str(r.get("contractor_name", "")),
            by_id, by_id_name, by_norm,
        ),
        axis=1,
    ).astype(float)
    rows["contract_name"] = rows.apply(
        lambda r: _lookup_contract_name(str(r.get("project_name", "")), str(r.get("contractor_name", "")), by_id_name),
        axis=1,
    )
    rows["vid_raboty"] = rows["contract_name"].astype(str).apply(extract_vid_raboty)
    rows["skud"] = rows["skud_avg"].fillna(0.0).round(0)
    # ТЗ ГДРС (2026-05 + уточнение по скринам): Отклонение = План − Факт (СКУД);
    # Отклонение % = (Отклонение / План) × 100. Положительное — недовыполнение.
    rows["deviation"] = (rows["plan"] - rows["skud"]).round(0)
    rows["delta_pct"] = rows.apply(
        lambda r: ((r["plan"] - r["skud"]) / r["plan"] * 100.0)
        if r["plan"] not in (0.0, None) and float(r["plan"]) != 0.0
        else np.nan,
        axis=1,
    )
    for w in ("w1", "w2", "w3", "w4", "w5", "w6"):
        rows[w] = rows[w].fillna(0.0).round(0)
    rows["row_kind"] = "row"

    if only_with_plan:
        rows = rows[rows["plan"] > 0].copy()
        if rows.empty:
            return pd.DataFrame()

    out_blocks: list[pd.DataFrame] = []
    for proj, chunk in rows.groupby("project_name", sort=True):
        block = chunk.sort_values("contractor_name").copy()
        plan_sum = float(block["plan"].sum())
        skud_sum = float(block["skud"].sum())
        dev_sum = plan_sum - skud_sum
        sub = pd.DataFrame(
            [{
                "project_name": proj,
                "contractor_name": "",
                "contractor_id": "",
                "project_id": "",
                "contract_name": "",
                "plan": plan_sum,
                "skud": skud_sum,
                "deviation": dev_sum,
                "delta_pct": ((plan_sum - skud_sum) / plan_sum * 100.0) if plan_sum > 0 else np.nan,
                "w1": float(block["w1"].sum()),
                "w2": float(block["w2"].sum()),
                "w3": float(block["w3"].sum()),
                "w4": float(block["w4"].sum()),
                "w5": float(block["w5"].sum()),
                "w6": float(block["w6"].sum()),
                "row_kind": "subtotal",
            }]
        )
        out_blocks.append(sub)
        out_blocks.append(block)

    if not out_blocks:
        return pd.DataFrame()

    body = pd.concat(out_blocks, ignore_index=True)
    sub_only = body[body["row_kind"] == "subtotal"]
    plan_total = float(sub_only["plan"].sum())
    skud_total_v = float(sub_only["skud"].sum())
    dev_total = plan_total - skud_total_v
    grand = pd.DataFrame(
        [{
            "project_name": "Итого",
            "contractor_name": "",
            "contractor_id": "",
            "project_id": "",
            "contract_name": "",
            "plan": plan_total,
            "skud": skud_total_v,
            "deviation": dev_total,
            "delta_pct": ((plan_total - skud_total_v) / plan_total * 100.0)
            if plan_total > 0
            else np.nan,
            "w1": float(sub_only["w1"].sum()),
            "w2": float(sub_only["w2"].sum()),
            "w3": float(sub_only["w3"].sum()),
            "w4": float(sub_only["w4"].sum()),
            "w5": float(sub_only["w5"].sum()),
            "w6": float(sub_only["w6"].sum()),
            "row_kind": "grand_total",
        }]
    )
    final = pd.concat([body, grand], ignore_index=True)
    return final


def build_summary_table(
    long_fact: pd.DataFrame,
    plan: pd.DataFrame,
    *,
    vid: str,
    date_from: Optional[pd.Timestamp] = None,
    date_to: Optional[pd.Timestamp] = None,
    projects: Optional[list[str]] = None,
    contractors: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Сводка по контрагентам (Скрин 5): Контрагент / План / Среднее за месяц / Отклонение."""
    if long_fact is None or long_fact.empty:
        return pd.DataFrame()
    fact = long_fact[long_fact["vid_resursa"].astype(str).str.casefold() == vid.casefold()].copy()
    if fact.empty:
        return pd.DataFrame()
    if date_from is not None:
        fact = fact[fact["date"] >= pd.to_datetime(date_from)]
    if date_to is not None:
        fact = fact[fact["date"] <= pd.to_datetime(date_to)]
    if projects:
        proj_keys = {p.strip().casefold() for p in projects}
        fact = fact[fact["project_name"].astype(str).str.strip().str.casefold().isin(proj_keys)]
    if contractors:
        c_keys = {c.strip().casefold() for c in contractors}
        fact = fact[fact["contractor_name"].astype(str).str.strip().str.casefold().isin(c_keys)]
    if fact.empty:
        return pd.DataFrame()

    plan_col = "plan_workers" if vid.casefold() == "рабочие" else "plan_equipment"
    by_id, by_id_name, by_norm = _build_plan_lookup(plan, plan_col)

    total_days = int(fact["date"].dt.normalize().nunique())
    id_pick = (
        fact.groupby(["project_name", "contractor_name"], dropna=False)
        .agg(
            project_id=("project_id", lambda s: next((x for x in s.astype(str) if x.strip()), "")),
            contractor_id=("contractor_id", lambda s: next((x for x in s.astype(str) if x.strip()), "")),
        )
        .reset_index()
    )
    summary = (
        fact.groupby(["project_name", "contractor_name"], dropna=False)["fact"]
        .sum()
        .reset_index(name="skud_sum")
    )
    summary = summary.merge(id_pick, on=["project_name", "contractor_name"], how="left")
    summary["mean_per_day"] = (summary["skud_sum"] / max(1, total_days)).round(0)
    summary["plan"] = summary.apply(
        lambda r: _lookup_plan(
            str(r.get("project_id", "")), str(r.get("contractor_id", "")),
            str(r.get("project_name", "")), str(r.get("contractor_name", "")),
            by_id, by_id_name, by_norm,
        ),
        axis=1,
    ).astype(float)
    out = (
        summary.groupby("contractor_name", as_index=False)
        .agg(plan=("plan", "sum"), mean_per_day=("mean_per_day", "sum"))
    )
    # ТЗ: Отклонение = План − Факт (среднее за день для периода).
    out["deviation"] = (out["plan"] - out["mean_per_day"]).round(0)
    return out[["contractor_name", "plan", "mean_per_day", "deviation"]]
