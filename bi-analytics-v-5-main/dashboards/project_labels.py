"""
Единые подписи проектов для фильтров, таблиц и выгрузок (MSP / 1С / СКУД).

Использует MSP_PROJECT_NAME_MAP и правила из dev_projects_tz_matrix
(«Дмитровский-1», «Есипово-5» из 1с_*_Projekts.json вместо лат. slug / римских V).
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import List, Optional, Set

import pandas as pd

from config import MSP_PROJECT_FILTER_EXCLUDE_NAMES

_ROMAN_PROJECT_TAIL = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
}

_PROJECT_CHILD_SUFFIX_RE = re.compile(r"^(\d{1,4}|[IVX]{1,4})$", re.I)


def _project_name_fusion_base(s: str) -> str:
    if not s:
        return ""
    t = (
        str(s)
        .replace("\xa0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .replace("-", " ")
    )
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""
    m_num = re.fullmatch(r"(.+?)\s+(\d{1,4})\s*", t, flags=re.I)
    if m_num:
        return f"{m_num.group(1).strip()} {int(m_num.group(2))}"
    m_rom = re.fullmatch(r"(.+?)\s+([IVX]{1,4})\s*", t, flags=re.I)
    if m_rom:
        rom = m_rom.group(2).upper()
        n = _ROMAN_PROJECT_TAIL.get(rom)
        if n is not None:
            return f"{m_rom.group(1).strip()} {n}"
    return t


def project_filter_norm_key(val) -> str:
    """Ключ сравнения названий проекта (пробел/дефис, римские → арабские)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = (
        str(val)
        .replace("\xa0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .strip()
    )
    while "  " in s:
        s = s.replace("  ", " ")
    s = _project_name_fusion_base(s)
    if s:
        try:
            s2 = re.sub(r"([А-Яа-яЁёA-Za-z])(\d{1,4})$", r"\1 \2", s)
        except re.error:
            s2 = s
        if s2 != s:
            s = re.sub(r"\s+", " ", str(s2)).strip()
    sl = s.casefold()
    if sl in ("", "nan", "none", "nat"):
        return ""
    return sl


def _project_norm_key_matches_msp_keys(row_key: str, msp_keys: Set[str]) -> bool:
    if not msp_keys:
        return True
    if not row_key:
        return False
    rk = str(row_key).strip()
    try:
        rk2 = re.sub(r"([а-яёa-z])(\d{1,4})$", r"\1 \2", rk)
        if rk2 != rk:
            rk = re.sub(r"\s+", " ", rk2).strip()
    except re.error:
        pass
    if rk in msp_keys:
        return True
    for k in msp_keys:
        if not k:
            continue
        pref = k + " "
        if rk.startswith(pref):
            rest = rk[len(pref) :]
            if rest and _PROJECT_CHILD_SUFFIX_RE.fullmatch(rest):
                return True
    for k in msp_keys:
        if not k:
            continue
        pref = rk + " "
        if rk and k.startswith(pref):
            rest = k[len(pref) :]
            if rest and _PROJECT_CHILD_SUFFIX_RE.fullmatch(rest):
                return True
    return False


def _clean_raw_name(raw: object) -> str:
    s = (
        str(raw)
        .replace("\xa0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .strip()
    )
    while "  " in s:
        s = s.replace("  ", " ")
    return s


def unified_project_display_label(raw: object) -> str:
    """Каноническая подпись проекта для UI и таблиц."""
    s = _clean_raw_name(raw)
    if not s or s.lower() in ("nan", "none", "nat"):
        return ""
    try:
        from dashboards.dev_projects_tz_matrix import (
            _control_points_project_group_key,
            _control_points_project_label,
        )

        gk = _control_points_project_group_key(s)
        return str(_control_points_project_label(gk, [s])).strip() or s
    except Exception:
        lk = s.lower().replace(" ", "")
        try:
            from config import MSP_PROJECT_NAME_MAP as M

            if lk in M:
                return str(M[lk]).strip()
        except Exception:
            pass
        return s


def project_labels_for_filter(
    series: pd.Series, *, apply_exclude_names: bool = True
) -> List[str]:
    """Уникальные подписи для select/multiselect: один пункт на логический проект."""
    if series is None or getattr(series, "empty", True):
        return []
    try:
        from dashboards.dev_projects_tz_matrix import _control_points_project_group_key
    except Exception:
        _control_points_project_group_key = None  # type: ignore[assignment]

    by_gk: dict[str, list[str]] = defaultdict(list)
    for raw in series.dropna().unique():
        s = _clean_raw_name(raw)
        if not s or s.lower() in ("nan", "none", "nat"):
            continue
        if _control_points_project_group_key is not None:
            by_gk[str(_control_points_project_group_key(s))].append(s)
        else:
            by_gk[project_filter_norm_key(s) or s].append(s)

    def _raws_for_group_label(raws: list[str]) -> list[str]:
        """Исключать дубли написания только если в группе есть другой вариант имени."""
        raws_u = sorted(set(raws))
        if not apply_exclude_names or len(raws_u) <= 1:
            return raws_u
        kept = [r for r in raws_u if r not in MSP_PROJECT_FILTER_EXCLUDE_NAMES]
        return kept if kept else raws_u

    labels: list[str] = []
    if _control_points_project_group_key is not None:
        try:
            from dashboards.dev_projects_tz_matrix import _control_points_project_label

            for gk, raws in by_gk.items():
                use_raws = _raws_for_group_label(raws)
                lab = str(_control_points_project_label(gk, use_raws)).strip()
                if lab:
                    labels.append(lab)
        except Exception:
            for raws in by_gk.values():
                use_raws = _raws_for_group_label(raws)
                labels.append(unified_project_display_label(use_raws[0]))
    else:
        for raws in by_gk.values():
            use_raws = _raws_for_group_label(raws)
            labels.append(unified_project_display_label(use_raws[0]))
    return sorted(set(labels), key=lambda x: x.casefold())


def apply_unified_project_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Подменяет значения колонки проекта на единые подписи."""
    if df is None or getattr(df, "empty", True) or col not in df.columns:
        return df
    out = df.copy()
    # Считаем подпись один раз на уникальное значение: unified_project_display_label
    # дорогая (нормализация + справочник), а строк в таблицах десятки/сотни тысяч
    # при ~сотне уникальных проектов. Прямой .map по всем строкам давал десятки
    # секунд на тяжёлых дашбордах («Причины отклонений» и т.п.).
    _uniq = out[col].dropna().unique()
    _label_map = {v: unified_project_display_label(v) for v in _uniq}
    out[col] = out[col].map(
        lambda z: _label_map.get(z, z)
        if z is not None and not (isinstance(z, float) and pd.isna(z))
        else z
    )
    return out


def filter_dataframe_by_project_labels(
    df: pd.DataFrame,
    selected_labels: list[str],
    *,
    col: str = "project_name",
) -> pd.DataFrame:
    """Оставить строки выбранных проектов (сопоставление по norm-key)."""
    if df is None or getattr(df, "empty", True) or col not in df.columns:
        return df
    labels = [str(x).strip() for x in (selected_labels or []) if str(x).strip()]
    if not labels:
        return df.copy()
    keys = {project_filter_norm_key(x) for x in labels}
    keys.discard("")
    if not keys:
        return df.copy()
    rk = df[col].map(project_filter_norm_key)
    return df[rk.map(lambda k: _project_norm_key_matches_msp_keys(k, keys))].copy()
