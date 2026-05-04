# -*- coding: utf-8 -*-
"""
Матрица «Девелоперские проекты» по ТЗ (правки): строки-показатели, колонки План / Факт / Откл.
Источники: MSP (canonical колонки после web_loader), project_data (БДДС), tessa_tasks_data.
"""
from __future__ import annotations

import copy
import html as html_module
import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from utils import outline_level_numeric

from settings import SETTING_KEYS

DEV_MATRIX_JSON_KEY = "developer_projects_matrix_json"

# Стабильные ключи строк матрицы (порядок = порядок колонок отчёта), для titles/matches в JSON.
_DEV_MATRIX_ROW_KEYS: List[str] = [
    "inv_arenda_zu",
    "inv_gotovy_produkt",
    "inv_gpzu",
    "life_ekspertiza_st_p",
    "life_komanda_rp",
    "life_rs",
    "life_rd_1var",
    "life_fin_ds",
    "life_tessa_preds",
    "life_ird_elvo",
    "life_ird_udc",
    "life_pos_1var",
    "life_fin_smr_start",
    "life_smr_start",
    "life_tech_pri",
    "life_zos",
    "life_rv",
    "life_pravo1",
    "life_vykup_zu",
    "life_pravo2",
    "life_boxes_res",
]


def load_developer_projects_matrix_prefs() -> Dict[str, Any]:
    """Подписи План/Факт/Откл., умолчание вертикальных дат, заголовки вех и patch match-критериев к MSP."""
    try:
        from settings import get_setting

        raw = (get_setting(DEV_MATRIX_JSON_KEY) or "").strip()
        base: Dict[str, Any] = {
            "subcolumns": {"plan": "План", "fact": "Факт", "otkl": "Откл."},
            "default_vertical_dates": False,
            "titles": {},
            "matches": {},
        }
        if not raw:
            return base
        data = json.loads(raw)
        if not isinstance(data, dict):
            return base
        sc = data.get("subcolumns")
        if isinstance(sc, dict):
            for k in ("plan", "fact", "otkl"):
                v = sc.get(k)
                if isinstance(v, str) and v.strip():
                    base["subcolumns"][k] = v.strip()
        dv = data.get("default_vertical_dates")
        if isinstance(dv, bool):
            base["default_vertical_dates"] = dv
        tt = data.get("titles")
        if isinstance(tt, dict):
            base["titles"] = {
                str(a).strip(): str(b).strip() for a, b in tt.items() if str(a).strip()
            }
        mt = data.get("matches")
        if isinstance(mt, dict):
            base["matches"] = mt
        return base
    except Exception:
        return {
            "subcolumns": {"plan": "План", "fact": "Факт", "otkl": "Откл."},
            "default_vertical_dates": False,
            "titles": {},
            "matches": {},
        }


def developer_projects_matrix_default_prefs_json() -> str:
    return json.dumps(
        {
            "subcolumns": {"plan": "План", "fact": "Факт", "otkl": "Откл."},
            "default_vertical_dates": False,
            "titles": {},
            "matches": {},
        },
        ensure_ascii=False,
        indent=2,
    )


def save_developer_projects_matrix_prefs_json(json_str: str, updated_by: str) -> Tuple[bool, str]:
    """Сохранение JSON; пустая строка — сброс подписей/маппинга."""
    try:
        from settings import set_setting

        s = (json_str or "").strip()
        desc = ""
        try:
            desc = str(SETTING_KEYS.get(DEV_MATRIX_JSON_KEY, ""))
        except Exception:
            desc = ""
        if not s:
            set_setting(
                DEV_MATRIX_JSON_KEY,
                "",
                description=desc,
                updated_by=updated_by,
            )
            return True, "Сброшено на правила из кода / пустые переопределения."
        data = json.loads(s)
        if not isinstance(data, dict):
            return False, "Ожидается JSON-объект (subcolumns, default_vertical_dates, titles, matches)."
        out: Dict[str, Any] = {
            "subcolumns": {"plan": "План", "fact": "Факт", "otkl": "Откл."},
            "default_vertical_dates": bool(data.get("default_vertical_dates", False)),
            "titles": {},
            "matches": {},
        }
        sc = data.get("subcolumns")
        if isinstance(sc, dict):
            for k in ("plan", "fact", "otkl"):
                vv = sc.get(k)
                if isinstance(vv, str) and vv.strip():
                    out["subcolumns"][k] = vv.strip()
        tt = data.get("titles")
        if isinstance(tt, dict):
            for a, b in tt.items():
                ak = str(a).strip()
                if ak:
                    out["titles"][ak] = str(b).strip()
        mt = data.get("matches")
        if isinstance(mt, dict):
            for a, patch in mt.items():
                ak = str(a).strip()
                if ak and isinstance(patch, dict):
                    out["matches"][ak] = patch
        set_setting(
            DEV_MATRIX_JSON_KEY,
            json.dumps(out, ensure_ascii=False, separators=(",", ":")),
            description=desc,
            updated_by=updated_by,
        )
        return True, "Сохранено."
    except json.JSONDecodeError as e:
        return False, f"Ошибка JSON: {e}"
    except Exception as e:
        return False, str(e)[:500]


def _guess_msp_project_slug_for_loader(df: pd.DataFrame) -> str:
    """
    Ключ для web_loader._apply_msp_column_mapping (MSP_PROJECT_NAME_MAP / имя файла):
    по имени файла msp_<slug>_… при наличии в attrs, иначе из первой ячейки колонки проекта.
    """
    try:
        fn = str(df.attrs.get("file_name") or "").strip()
    except Exception:
        fn = ""
    if fn:
        base = fn.replace("\\", "/").split("/")[-1]
        low = base.lower()
        if low.startswith("msp_") and low.endswith(".csv"):
            stem = base[:-4]
            parts = stem.split("_")
            if len(parts) >= 2 and parts[1].strip():
                return parts[1].strip().lower()
    try:
        from config import MSP_PROJECT_NAME_MAP as M
    except Exception:
        M = {}
    pc = _find_col(df, ["project name", "Проект", "Project", "проект"])
    if not pc or pc not in df.columns:
        return ""
    s = df[pc].dropna().astype(str).str.strip()
    if s.empty:
        return ""
    raw = str(s.iloc[0]).strip()
    lk = raw.lower().replace(" ", "").replace("\xa0", "")
    if lk in M:
        return str(lk)
    for k, v in M.items():
        if str(v).strip().lower() == raw.lower():
            return str(k).strip().lower()
    return lk


def _needs_msp_web_loader_normalize(df: pd.DataFrame) -> bool:
    """Русская выгрузка без прохода через web_loader: нет canonical-колонок дат/задачи/уровня."""
    if df is None or getattr(df, "empty", True):
        return False
    cl = {str(c).strip().lower() for c in df.columns}
    if "plan end" not in cl and _find_col(df, ["Окончание", "План окончание", "План_окончание"]) is not None:
        return True
    if "task name" not in cl and _find_col(df, ["Название", "Название задачи", "Task Name"]) is not None:
        return True
    if "level" not in cl and _find_col(df, ["Уровень"]) is not None:
        return True
    if "base end" not in cl and _find_col(df, ["Базовое_окончание", "Базовое окончание"]) is not None:
        return True
    return False


def ensure_msp_df_for_dev_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """
    Единая схема MSP для матрицы: canonical-колонки, даты, section из дерева (как при load_all_from_web).
    """
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()
    if _needs_msp_web_loader_normalize(out):
        try:
            from web_loader import _apply_msp_column_mapping

            slug = _guess_msp_project_slug_for_loader(out)
            out = _apply_msp_column_mapping(out, slug)
        except Exception:
            out = _control_points_prepare_msp_dates(out)
    else:
        out = _control_points_prepare_msp_dates(out)
    try:
        from web_loader import _coerce_msp_project_name_from_file_if_needed
        from config import MSP_PROJECT_NAME_MAP

        slug = (_guess_msp_project_slug_for_loader(out) or "").strip().lower()
        if slug:
            ru_from_file = str(MSP_PROJECT_NAME_MAP.get(slug, slug)).strip()
            if ru_from_file:
                out = _coerce_msp_project_name_from_file_if_needed(out, ru_from_file)
    except Exception:
        pass
    return out


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    if df is None or not hasattr(df, "columns"):
        return None
    cols = list(df.columns)
    for cand in candidates:
        c0 = cand.strip().lower()
        for c in cols:
            if str(c).strip().lower() == c0:
                return c
    for cand in candidates:
        c0 = cand.strip().lower()
        for c in cols:
            if c0 in str(c).strip().lower():
                return c
    return None


def _find_building_column(df: pd.DataFrame) -> Optional[str]:
    if df is None or not hasattr(df, "columns"):
        return None
    for col in df.columns:
        cn = str(col).lower()
        for kw in ("building", "строение", "лот", "lot", "bldg"):
            if str(kw).lower() in cn:
                return str(col)
    return None


def _krstate_bucket(raw: Any) -> str:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "other"
    s = str(raw).strip()
    sl = s.lower()
    if "declined" in sl or "отказ" in sl:
        return "declined"
    if "active" in sl or "doc_active" in sl:
        return "active"
    # Подписано: Tessa KrState / справочники (в т.ч. KrStates_Doc_Signed)
    if "signed" in sl or "doc_signed" in sl:
        return "signed"
    if re.search(r"не\s*подпис", sl) or "на подпис" in sl:
        return "other"
    if "подписан" in sl or "подписано" in sl:
        return "signed"
    return "other"


def _norm_join_key(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    try:
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            fv = float(val)
            if fv == int(fv):
                return str(int(fv))
    except (TypeError, ValueError, OverflowError):
        pass
    s = str(val).strip()
    if len(s) > 2 and s.endswith(".0") and s[:-2].replace("-", "").isdigit():
        return s[:-2]
    return s


def _fmt_date_ru(v: Any) -> str:
    if v is None:
        return "Н/Д"
    try:
        if pd.isna(v):
            return "Н/Д"
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and pd.isna(v):
        return "Н/Д"
    if isinstance(v, pd.Timestamp):
        return v.strftime("%d.%m.%Y")
    from datetime import date, datetime

    if isinstance(v, datetime):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    # Чистое число без календарного контекста — не показываем как дату (частая ошибка маппинга)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if pd.isna(v):
            return "Н/Д"
        fv = float(v)
        if 1900 <= fv <= 2100 and fv == int(fv):
            return "Н/Д"
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() in ("nan", "nat", "none", ""):
            return "Н/Д"
        if re.fullmatch(r"[-+]?\d+([.,]\d+)?", s.replace(" ", "").replace("\u00a0", "")):
            return "Н/Д"
        s2 = s.replace("/", ".").replace("\\", ".")
        ts = pd.to_datetime(s2, errors="coerce", dayfirst=True)
        if pd.isna(ts):
            return "Н/Д"
        return ts.strftime("%d.%m.%Y")
    ts = pd.to_datetime(v, errors="coerce", dayfirst=True)
    if pd.isna(ts):
        return "Н/Д"
    return ts.strftime("%d.%m.%Y")


def _level_series(df: pd.DataFrame) -> pd.Series:
    """
    Фильтр «уровень N» по ТЗ — колонка MSP «Уровень» (не outline).
    В выгрузке «Уровень» и «Уровень_структуры» различаются (напр. ГПЗУ: Уровень=5, структура=3).
    Родителя «Ковенанты» считаем в web_loader по outline — см. _fill_section_from_task_tree.
    """
    if "level" in df.columns:
        return pd.to_numeric(df["level"], errors="coerce")
    if "level structure" in df.columns:
        return pd.to_numeric(df["level structure"], errors="coerce")
    return pd.Series(np.nan, index=df.index)


def _task_name_col(df: pd.DataFrame) -> Optional[str]:
    if "task name" in df.columns:
        return "task name"
    return _find_col(df, ["Название задачи", "Название", "Task Name"])


def _series_first_value(row: pd.Series, col: str) -> Any:
    """
    Скаляр из ячейки: при дублирующихся именах колонок (напр. два «plan end» после
    ремапа «Окончание» и «План окончание») берётся первое непустое значение.
    """
    if col not in row.index:
        return pd.NaT
    v = row[col]
    if isinstance(v, pd.Series):
        v2 = v.dropna()
        if v2.empty:
            return pd.NaT
        return v2.iloc[0]
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return pd.NaT
    return v


def _is_pct_complete_not_100(pct: Any) -> bool:
    """ТЗ: подсветка, если «% выполнения» задан и не равен 100%."""
    if pct is None:
        return False
    try:
        if isinstance(pct, float) and pd.isna(pct):
            return False
    except (TypeError, ValueError):
        return False
    s = str(pct).strip().replace("%", "").replace(" ", "").replace(",", ".")
    if not s or s.lower() in ("nan", "none", "nat"):
        return False
    try:
        v = float(s)
    except (TypeError, ValueError):
        return False
    # Некоторые выгрузки дают долю 0..1 вместо процентов 0..100.
    if 0.0 <= v <= 1.0:
        v = v * 100.0
    return abs(v - 100.0) > 1e-3


def _msp_plan_fact_pct(row: pd.Series) -> Tuple[Any, Any, Any]:
    """
    ТЗ: План = «Базовое окончание» (base end); Факт = «Окончание» (после web_loader — plan end).
    Без подмены на «Фактическое окончание»: только колонка окончания срока из MSP.
    Если базовое окончание пусто — для «Плана» берём то же «Окончание».
    """
    be = _series_first_value(row, "base end")
    if pd.isna(be):
        be = _series_first_value(row, "plan end")
    fe = _series_first_value(row, "plan end")
    pc = _series_first_value(row, "pct complete") if "pct complete" in row.index else pd.NaT
    return be, fe, pc


def _delta_days_plan_minus_fact(plan_d: Any, fact_d: Any) -> Optional[int]:
    if pd.isna(plan_d) or pd.isna(fact_d):
        return None
    try:
        return int((pd.Timestamp(plan_d).normalize() - pd.Timestamp(fact_d).normalize()).days)
    except Exception:
        return None


def _fmt_delta_days(d: Optional[int]) -> str:
    if d is None:
        return "Н/Д"
    try:
        di = int(d)
    except (TypeError, ValueError):
        return "Н/Д"
    if di == 0:
        return "0 дн."
    sign = "+" if di > 0 else ""
    return f"{sign}{di} дн."


_OTKL_DAYS_DISPLAY_RE = re.compile(r"([+-]?\d+)\s*дн", re.IGNORECASE)


def _parse_otkl_days_display(s: Any) -> Optional[int]:
    """Число дней из строки вида «+3 дн.» / «0 дн.» для раскраски «Откл.» (План−Факт)."""
    if s is None:
        return None
    t = str(s).strip()
    if not t or t.upper() in ("Н/Д", "N/D", "—", "-"):
        return None
    m = _OTKL_DAYS_DISPLAY_RE.search(t)
    if not m:
        return None
    try:
        v = int(m.group(1))
        return v
    except ValueError:
        return None


def _norm_cell_for_date_check(s: Any) -> str:
    """Нормализация текста ячейки: NBSP/ZWSP, чтобы облако/Excel не ломали матч даты."""
    if s is None:
        return ""
    t = (
        str(s)
        .replace("\xa0", " ")
        .replace("\u2009", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .strip()
    )
    while "  " in t:
        t = t.replace("  ", " ")
    return t


def _looks_like_ru_date_cell(s: Any) -> bool:
    if s is None:
        return False
    t = _norm_cell_for_date_check(s)
    if not t or t.upper() in ("Н/Д", "N/D", "—", "-"):
        return False
    # Строго DD.MM.YYYY или дата в начале («01.03.2026 г.», хвост от экспорта)
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", t):
        return True
    if re.match(r"^\d{2}\.\d{2}\.\d{4}\b", t):
        return True
    # Иногда в CSV/Excel приходит ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}\b", t):
        return True
    return False


def _dev_tz_apply_vert_date(vertical_dates: bool, col: str, cell_val: Any) -> bool:
    """Нужны и класс, и inline-style (на Streamlit Cloud стили из <style> иногда не цепляются к ячейкам)."""
    return bool(
        vertical_dates
        and col in ("plan", "fact")
        and _looks_like_ru_date_cell(cell_val)
    )


def _find_phase_column(df: pd.DataFrame) -> Optional[str]:
    """Колонка вехи по макету правок: «Инвестиционная. Аренда ЗУ» и т.п. (не имена задач MSP)."""
    if df is None or not hasattr(df, "columns"):
        return None
    for c in df.columns:
        cl = str(c).strip().lower()
        if cl in ("фаза", "phase"):
            return str(c)
    return _find_col(df, ["Фаза", "Phase", "фаза"])


def _match_by_phase_needles(
    mdf: pd.DataFrame,
    needles: List[str],
    exclude_needles: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Внутренние CSV: веха в «Фаза». Чистый MSP без «Фаза»: те же подстроки ищем в «Задача» / notes / «Заметки».
    exclude_needles — применяются к колонке «Фаза», если она есть (разделение двух столбцов ИРД).
    """
    if mdf is None or mdf.empty or not needles:
        return mdf.iloc[0:0].copy()
    _lit = dict(case=False, na=False, regex=False)
    pc = _find_phase_column(mdf)
    nm = _task_name_col(mdf)
    text_cols: List[str] = []
    if pc and pc in mdf.columns:
        text_cols.append(pc)
    for c in (nm, "notes", "Заметки"):
        if c and c in mdf.columns and c not in text_cols:
            text_cols.append(str(c))
    if not text_cols:
        return mdf.iloc[0:0].copy()
    masks: List[pd.Series] = []
    for needle in needles:
        n = str(needle).strip()
        if not n:
            continue
        for c in text_cols:
            masks.append(mdf[c].astype(str).str.contains(n, **_lit))
    if not masks:
        return mdf.iloc[0:0].copy()
    mm = masks[0]
    for x in masks[1:]:
        mm = mm | x
    out = mdf[mm].copy()
    if exclude_needles and pc and pc in out.columns:
        s2 = out[pc].astype(str)
        for ex in exclude_needles:
            exs = str(ex).strip()
            if exs:
                out = out[~s2.str.contains(exs, **_lit)]
    return out


def _match_msp(
    mdf: pd.DataFrame,
    *,
    level: Optional[float],
    name_contains: Optional[str] = None,
    names_any: Optional[List[str]] = None,
    names_exact_any: Optional[List[str]] = None,
    parent_l2_contains: Optional[str] = None,
    block_contains: Optional[str] = None,
) -> pd.DataFrame:
    if mdf is None or mdf.empty:
        return mdf.iloc[0:0].copy()
    out = mdf
    nm = _task_name_col(out)
    if nm is None:
        return out.iloc[0:0].copy()
    lvl = _level_series(out)
    if level is not None and lvl.notna().any():
        out = out[lvl == float(level)]
    _lit = dict(case=False, na=False, regex=False)  # иначе «(РД)» и др. ломают regex
    if block_contains and "block" in out.columns:
        out = out[out["block"].astype(str).str.contains(block_contains, **_lit)]
    if parent_l2_contains:
        # Родитель ур.2: section из дерева задач; для «Ковенанты» — по подстроке «ковенант» (склонения/опечатки)
        l2c = _find_col(out, ["l2 parent", "l2_parent", "parent l2", "Раздел"])
        col = l2c if l2c and l2c in out.columns else ("section" if "section" in out.columns else None)
        if col is None:
            return out.iloc[0:0].copy()
        sc = out[col].astype(str)
        if "ковенант" in str(parent_l2_contains).lower():
            out = out[sc.str.contains("ковенант", **_lit)]
        else:
            out = out[sc.str.contains(str(parent_l2_contains), **_lit)]
    name_masks: List[pd.Series] = []
    if names_any:
        for needle in names_any:
            if needle:
                name_masks.append(out[nm].astype(str).str.contains(str(needle), **_lit))
    if names_exact_any:
        nv = out[nm].astype(str).str.strip().str.casefold()
        for xs in names_exact_any:
            if xs is None or str(xs).strip() == "":
                continue
            xf = str(xs).strip().casefold()
            name_masks.append(nv.eq(xf))
    if name_contains:
        name_masks.append(out[nm].astype(str).str.contains(str(name_contains), **_lit))
    if name_masks:
        mm_nm = name_masks[0]
        for xm in name_masks[1:]:
            mm_nm = mm_nm | xm
        out = out[mm_nm]
    return out


def _match_tasks_like_msp_row(mdf: pd.DataFrame, kw: dict) -> pd.DataFrame:
    """
    Те же шаги отбора задач MSP, что и для строки матрицы «Девелоперские проекты»
    (ослабление родителя ур.2, уровня, блока → «Фаза»).
    """
    if mdf is None or getattr(mdf, "empty", True):
        return mdf.iloc[0:0].copy()
    kw_m = {
        k: v
        for k, v in kw.items()
        if k not in ("phase_needles", "phase_exclude_needles", "names_exact_any")
    }
    _nex = kw.get("names_exact_any")
    phase_needles = kw.get("phase_needles")
    phase_exclude = kw.get("phase_exclude_needles")
    sub = _match_msp(
        mdf,
        level=kw_m.get("level"),
        name_contains=kw_m.get("name_contains"),
        names_any=kw_m.get("names_any"),
        names_exact_any=_nex,
        parent_l2_contains=kw_m.get("parent_l2_contains"),
        block_contains=kw_m.get("block_contains"),
    )
    if sub.empty and kw_m.get("parent_l2_contains"):
        sub = _match_msp(
            mdf,
            level=kw_m.get("level"),
            name_contains=kw_m.get("name_contains"),
            names_any=kw_m.get("names_any"),
            names_exact_any=_nex,
            parent_l2_contains=None,
            block_contains=kw_m.get("block_contains"),
        )
    if sub.empty and kw_m.get("level") is not None:
        sub = _match_msp(
            mdf,
            level=None,
            name_contains=kw_m.get("name_contains"),
            names_any=kw_m.get("names_any"),
            names_exact_any=_nex,
            parent_l2_contains=None,
            block_contains=kw_m.get("block_contains"),
        )
    if sub.empty:
        sub = _match_msp(
            mdf,
            level=None,
            name_contains=kw_m.get("name_contains"),
            names_any=kw_m.get("names_any"),
            names_exact_any=_nex,
            parent_l2_contains=None,
            block_contains=kw_m.get("block_contains"),
        )
    if sub.empty and kw_m.get("block_contains"):
        sub = _match_msp(
            mdf,
            level=None,
            name_contains=kw_m.get("name_contains"),
            names_any=kw_m.get("names_any"),
            names_exact_any=_nex,
            parent_l2_contains=None,
            block_contains=None,
        )
    if sub.empty and phase_needles:
        sub = _match_by_phase_needles(mdf, phase_needles, phase_exclude)
    return sub


def _unicode_dash_fold(s: str) -> str:
    """Единый дефис: длинное/короткое тире из MSP/Excel → '-', чтобы ключи группировки совпадали."""
    t = str(s)
    for ch in ("\u2013", "\u2014", "\u2212", "\u00ad"):
        t = t.replace(ch, "-")
    return t


def _norm_dev_project_key(val: Any) -> str:
    """
    Сопоставление подписи проекта MSP / 1С / TESSA: регистр, пробелы, «-», хвостовые
    римские цифры I..X → арабские 1..10 (чтобы «Есипово V» и «Есипово-5»,
    «Дмитровский I» и «Дмитровский-1» имели один ключ группировки).
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip().lower().replace("ё", "е")
    s = re.sub(r"[\s\-_]+", "", s)
    _roman_tail = {
        "iii": 3, "ii": 2, "iv": 4, "ix": 9, "viii": 8, "vii": 7, "vi": 6,
        "v": 5, "i": 1, "x": 10,
    }
    for _rom in ("viii", "iii", "vii", "iv", "ix", "vi", "ii", "v", "x", "i"):
        if s.endswith(_rom) and len(s) > len(_rom) and s[-len(_rom) - 1].isalpha():
            s = s[: -len(_rom)] + str(_roman_tail[_rom])
            break
    return s


def _control_points_project_group_key(raw: Any) -> str:
    """
    Группировка строк в «Контрольные точки»: один логический проект (дубли «Дмитровский» / «Дмитровский-1»).
    """
    try:
        from config import MSP_PROJECT_NAME_MAP as M
    except Exception:
        M = {}
    s = (
        _unicode_dash_fold(str(raw))
        .replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .strip()
    )
    # «Имя-1» / «Имя – 1» после фолда тире — тот же логический проект, что «Имя» (типовой дубль выгрузок)
    if re.search(r"-\s*1\s*$", s):
        s_alt = re.sub(r"-\s*1\s*$", "", s).strip()
        if len(s_alt) >= 3:
            s = s_alt
    lk = s.lower().replace(" ", "")
    if lk in M:
        nk = _norm_dev_project_key(M[lk])
    else:
        nk = _norm_dev_project_key(s)
    # После маппинга: «Дмитровский», «Дмитровский 1», «Дмитровский I» — один проект.
    nk_base = re.sub(r"(?:1|i)$", "", nk)
    if nk in ("дмитровский", "дмитровский1", "дмитровскийi") or nk_base == "дмитровский":
        return "unified_dmitrovsky1"
    return nk


def _control_points_project_label(group_key: str, raw_names: List[str]) -> str:
    """Подпись столбца «Проект» после группировки."""
    try:
        from config import MSP_PROJECT_NAME_MAP as M
    except Exception:
        M = {}
    # Сначала точный ключ из карты (без нормализации римских), чтобы не потерять имена вида
    # «Дмитровский-1». Далее — по нормализованному ключу (римские хвосты тоже сводятся).
    for r in raw_names:
        lk = str(r).strip().lower().replace(" ", "")
        if lk in M:
            return str(M[lk]).strip()
    for r in raw_names:
        nk = _norm_dev_project_key(r)
        if nk and nk in M:
            return str(M[nk]).strip()
    if group_key == "unified_dmitrovsky1":
        return "Дмитровский 1"
    return str(raw_names[0]).strip() if raw_names else ""


def _bddds_df_for_dev_matrix(
    mdf: pd.DataFrame,
    project_data: Optional[pd.DataFrame],
    ss: Any,
) -> Optional[pd.DataFrame]:
    """
    Обороты 1С для строки «Выборка ДС»: из session_state.reference_1c_dannye по колонке «Проект»,
    с тем же ключом, что и MSP «project name». Иначе — project_data, если там есть «Сценарий».
    """
    pname = ""
    if mdf is not None and not getattr(mdf, "empty", True) and "project name" in mdf.columns:
        s0 = mdf["project name"].dropna().astype(str).str.strip()
        if not s0.empty:
            pname = str(s0.iloc[0]).strip()
    ref = ss.get("reference_1c_dannye") if hasattr(ss, "get") else None
    if ref is not None and not getattr(ref, "empty", True) and pname:
        pc = _find_col(ref, ["Проект", "Project", "проект"])
        if pc and pc in ref.columns:
            pk = _norm_dev_project_key(pname)
            m = ref[pc].map(lambda x: _norm_dev_project_key(x) == pk)
            sub = ref.loc[m.fillna(False)].copy()
            if not sub.empty:
                return sub
            try:
                from config import MSP_PROJECT_NAME_MAP

                for _k, v in MSP_PROJECT_NAME_MAP.items():
                    if _norm_dev_project_key(v) == pk or _norm_dev_project_key(str(_k)) == pk:
                        m2 = ref[pc].map(lambda x: _norm_dev_project_key(x) == _norm_dev_project_key(v))
                        sub2 = ref.loc[m2.fillna(False)].copy()
                        if not sub2.empty:
                            return sub2
            except Exception:
                pass
            if pk:
                def _soft_dev_proj_cell(x: Any) -> bool:
                    nk = _norm_dev_project_key(x)
                    if not nk:
                        return False
                    if nk == pk:
                        return True
                    a, b = (nk, pk) if len(nk) <= len(pk) else (pk, nk)
                    return len(a) >= 4 and (a in b)

                m_soft = ref[pc].map(_soft_dev_proj_cell)
                sub_s = ref.loc[m_soft.fillna(False)].copy()
                if not sub_s.empty:
                    return sub_s
    if project_data is None or getattr(project_data, "empty", True):
        return None
    scen = _find_col(project_data, ["Сценарий", "Scenario"])
    if not scen or scen not in project_data.columns:
        return None
    if pname:
        pc2 = _find_col(project_data, ["Проект", "Project", "проект"])
        if pc2 and pc2 in project_data.columns:
            pk = _norm_dev_project_key(pname)
            m3 = project_data[pc2].map(lambda x: _norm_dev_project_key(x) == pk)
            if m3.fillna(False).any():
                return project_data.loc[m3.fillna(False)].copy()
            if pk:
                def _soft_proj_pd(x: Any) -> bool:
                    nk = _norm_dev_project_key(x)
                    if not nk:
                        return False
                    if nk == pk:
                        return True
                    a, b = (nk, pk) if len(nk) <= len(pk) else (pk, nk)
                    return len(a) >= 4 and (a in b)

                ms = project_data[pc2].map(_soft_proj_pd)
                if ms.fillna(False).any():
                    return project_data.loc[ms.fillna(False)].copy()
    return project_data


def _ds_plan_fact_otkl_mln(project_data: Optional[pd.DataFrame]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if project_data is None or project_data.empty:
        return None, None, None
    bd = project_data.copy()
    bd.columns = [str(c).strip() for c in bd.columns]
    scen_col = _find_col(bd, ["Сценарий", "Scenario"])
    sum_col = _find_col(bd, ["Сумма", "Sum", "Amount", "СуммаОборота"])
    art_col = _find_col(bd, ["Статья оборотов", "СтатьяОборотов", "Статья"])
    if not scen_col or not sum_col:
        return None, None, None
    b = bd[bd[scen_col].notna()].copy()
    b = b[b[scen_col].astype(str).str.strip() != ""]
    if b.empty:
        return None, None, None
    scen_s = b[scen_col].astype(str)
    art_s = b[art_col].astype(str) if art_col and art_col in b.columns else pd.Series("", index=b.index)
    # ТЗ (file-003): статьи оборотов — все, кроме содержащих «(БДР)» в названии
    bdr_in_article = art_s.str.contains(r"\(\s*бдр\s*\)", case=False, na=False, regex=True)
    plan_mask = (
        scen_s.str.contains("бюджет", case=False, na=False)
        & art_s.astype(str).str.strip().ne("")
        & ~bdr_in_article
    )
    fact_mask = scen_s.str.contains("факт", case=False, na=False)
    if art_col and art_col in b.columns:
        fact_mask = (
            fact_mask
            & art_s.astype(str).str.strip().ne("")
            & ~bdr_in_article
        )
    plan_sum = pd.to_numeric(b.loc[plan_mask, sum_col], errors="coerce").fillna(0).sum()
    fact_sum = pd.to_numeric(b.loc[fact_mask, sum_col], errors="coerce").fillna(0).sum()
    return float(plan_sum) / 1e6, float(fact_sum) / 1e6, float(plan_sum - fact_sum) / 1e6


def _tessa_to_dt(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)


def _tessa_counts(ss: Any) -> Tuple[str, str, str, str]:
    tdf = ss.get("tessa_tasks_data") if hasattr(ss, "get") else None
    if tdf is None or getattr(tdf, "empty", True):
        return "Н/Д", "Н/Д", "Н/Д", ""
    tk = tdf.copy()
    tk.columns = [str(c).strip() for c in tk.columns]
    kk = _find_col(tk, ["KindName", "kindname", "Вид"])
    if not kk:
        return "Н/Д", "Н/Д", "Н/Д", ""
    # ТЗ: KindName = «Предписание» / «Предписания» (Tessa.Tasks)
    pred = tk[tk[kk].astype(str).str.contains(r"предписани", case=False, na=False, regex=True)].copy()
    if pred.empty:
        return "0", "0", "0", ""
    card_c = _find_col(pred, ["CardId", "CardID", "cardId"])
    state_c = _find_col(pred, ["KrStateName", "KrState", "State", "Состояние", "Статус"])
    due_c = _find_col(pred, ["PlanDate", "DueDate", "Срок", "Крайний срок"])
    if not card_c:
        return str(len(pred)), "—", "Н/Д", ""
    pred = pred.assign(_card=pred[card_c].map(_norm_join_key))
    pred = pred[pred["_card"].astype(str).str.len() > 0]
    n_cards = int(pred["_card"].nunique())
    if state_c and state_c in pred.columns:
        signed_any = pred.groupby("_card", group_keys=False)[state_c].agg(
            lambda s: any(_krstate_bucket(x) == "signed" for x in s.astype(str))
        )
        n_signed = int(signed_any.sum())
    else:
        n_signed = 0
    n_open = int(max(0, n_cards - n_signed))
    hint = ""
    overdue_n = 0
    if due_c and due_c in pred.columns and state_c and state_c in pred.columns:
        now = pd.Timestamp.now().normalize()

        def _open_row(r: pd.Series) -> bool:
            return _krstate_bucket(r.get(state_c)) != "signed"

        om = pred.apply(_open_row, axis=1)
        dts = _tessa_to_dt(pred.loc[om, due_c])
        overdue_n = int(((dts.dt.normalize() < now) & dts.notna()).sum())
        if overdue_n:
            hint = f"Просрочено (не устранено, срок прошёл): {overdue_n}"
    # ТЗ: План = «Количество» (уник. cardId); Факт = «Не устранено»; Откл. = «Просрочено»
    otkl_s = str(overdue_n) if (due_c and due_c in pred.columns and state_c and state_c in pred.columns) else "Н/Д"
    return str(n_cards), str(n_open), otkl_s, hint


def _predpisaniya_combined(mdf: pd.DataFrame, ss: Any) -> Tuple[str, str, str, bool, str]:
    """
    TESSA (предписания) — приоритет; если файла нет / колонок нет (всё Н/Д) — строки с «Предписан» в «Фаза» или в названии задачи.
    """
    tp, tf, to, hint = _tessa_counts(ss)
    if not (tp == "Н/Д" and tf == "Н/Д" and to == "Н/Д"):
        try:
            nfu = int(str(tf).strip())
        except (TypeError, ValueError):
            nfu = 0
        try:
            nov = int(str(to).strip())
        except (TypeError, ValueError):
            nov = 0
        warn_t = nfu > 0 or nov > 0
        return tp, tf, to, warn_t, hint
    sub = _match_by_phase_needles(mdf, ["Предписан", "предписание", "предписания"])
    if sub.empty:
        nm = _task_name_col(mdf)
        if nm and nm in mdf.columns:
            _lit = dict(case=False, na=False, regex=False)
            sub = mdf[mdf[nm].astype(str).str.contains("предписан", **_lit)]
    if sub.empty:
        return tp, tf, to, False, hint
    # ТЗ: одна дата на ячейку — представительная задача вехи (как в _one_milestone_cell), без склейки « / ».
    ps, fs, os, _ok, w = _one_milestone_cell(sub)
    return ps, fs, os, bool(w), hint


def build_predpisaniya_detail_df(ss: Any, project_name_hint: str = "") -> pd.DataFrame:
    """Все строки предписаний из Tessa (tasks), опционально — фильтр по названию проекта/объекта."""
    tdf = ss.get("tessa_tasks_data") if hasattr(ss, "get") else None
    if tdf is None or getattr(tdf, "empty", True):
        return pd.DataFrame()
    tk = tdf.copy()
    tk.columns = [str(c).strip() for c in tk.columns]
    kk = _find_col(tk, ["KindName", "kindname", "Вид"])
    if not kk:
        return pd.DataFrame()
    pred = tk[tk[kk].astype(str).str.contains(r"предписани", case=False, na=False, regex=True)].copy()
    if pred.empty:
        return pd.DataFrame()
    hint = (project_name_hint or "").strip()
    if hint:
        pk = _norm_dev_project_key(hint)
        proj_cols = [
            _find_col(pred, ["ObjectName", "Object Name", "Объект"]),
            _find_col(pred, ["Проект", "Project", "project", "ProjectName"]),
        ]
        matched = False
        for proj_c in proj_cols:
            if not proj_c or proj_c not in pred.columns:
                continue

            def _row_match_cell(x: Any) -> bool:
                nk = _norm_dev_project_key(x)
                if not nk:
                    return False
                if nk == pk:
                    return True
                if len(pk) >= 4 and (pk in nk or nk in pk):
                    return True
                return False

            m = pred[proj_c].map(_row_match_cell)
            if m.fillna(False).any():
                pred = pred.loc[m.fillna(False)].copy()
                matched = True
                break
        if not matched and pk:
            pass
    return pred.reset_index(drop=True)


def render_developer_predpisaniya_expander(
    ss: Any,
    project_names: Optional[List[str]] = None,
    *,
    expanded: bool = False,
) -> None:
    """Полная таблица предписаний Tessa под матрицей + выгрузка."""
    import streamlit as st

    from utils import render_dataframe_excel_csv_downloads

    raw_names = [str(n).strip() for n in (project_names or []) if str(n).strip()]
    if len(raw_names) == 1:
        exp_title = f"Предписания (Tessa), полная выгрузка — «{raw_names[0]}»"
    elif len(raw_names) > 1:
        exp_title = f"Предписания (Tessa), полная выгрузка — проектов: {len(raw_names)}"
    else:
        exp_title = "Предписания (Tessa), полная выгрузка"

    with st.expander(exp_title, expanded=expanded):
        if not raw_names:
            df_all = build_predpisaniya_detail_df(ss, "")
            if df_all.empty:
                st.caption("Нет данных Tessa по предписаниям (KindName) или файл не загружен.")
                return
            st.dataframe(df_all, use_container_width=True, hide_index=True)
            render_dataframe_excel_csv_downloads(
                df_all,
                file_stem="predpisaniya_tessa",
                key_prefix="dev_pred_all",
                csv_label="Скачать предписания (CSV)",
            )
            return

        chunks: List[pd.DataFrame] = []
        for pname in raw_names:
            chunk = build_predpisaniya_detail_df(ss, pname)
            if not chunk.empty:
                c2 = chunk.copy()
                c2.insert(0, "проект_фильтр", pname)
                chunks.append(c2)

        if not chunks:
            st.caption(
                "Для выбранных проектов не найдено строк предписаний по объекту/проекту в Tessa. "
                "Показываются все предписания без фильтра."
            )
            df_fallback = build_predpisaniya_detail_df(ss, "")
            if df_fallback.empty:
                return
            st.dataframe(df_fallback, use_container_width=True, hide_index=True)
            render_dataframe_excel_csv_downloads(
                df_fallback,
                file_stem="predpisaniya_tessa",
                key_prefix="dev_pred_fb",
                csv_label="Скачать предписания (CSV)",
            )
            return

        merged = pd.concat(chunks, ignore_index=True)
        st.dataframe(merged, use_container_width=True, hide_index=True)
        render_dataframe_excel_csv_downloads(
            merged,
            file_stem="predpisaniya_tessa_by_project",
            key_prefix="dev_pred_detail",
            csv_label="Скачать предписания (CSV)",
        )


def dedupe_msp_for_developer_projects(df: pd.DataFrame) -> pd.DataFrame:
    """
    ТЗ: нет дублирования проектов и задач в «Девелоперские проекты».
    Сначала по идентификатору задачи MSP (если колонка есть и не пустая), иначе по (проект, задача) / по задаче.

    Если в колонке id часть строк без значения, нельзя делать ``drop_duplicates`` по всему кадру:
    строки без id считаются дубликатами друг друга и схлопываются в одну (матрица уходит в Н/Д).
    """
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()

    def _series_id_valid(ser: pd.Series) -> pd.Series:
        s2 = ser.astype(str).str.strip()
        low = s2.str.lower()
        return ser.notna() & ~low.isin(("", "nan", "none", "<na>", "nat"))

    def _dedupe_by_id_nonempty(frame: pd.DataFrame, id_col: str) -> pd.DataFrame:
        ok = _series_id_valid(frame[id_col])
        if int(ok.sum()) == 0:
            return frame
        part_ok = frame.loc[ok].drop_duplicates(subset=[id_col], keep="first")
        part_miss = frame.loc[~ok]
        return pd.concat([part_miss, part_ok]).sort_index()

    for id_c in (
        "unique id",
        "Уникальный_идентификатор",
        "task id seq",
        "Ид",
    ):
        if id_c not in out.columns:
            continue
        if int(_series_id_valid(out[id_c]).sum()) == 0:
            continue
        out = _dedupe_by_id_nonempty(out, id_c).reset_index(drop=True)
        return out
    pc = _find_col(out, ["project name", "Проект", "Project", "проект"])
    tc = _task_name_col(out)
    if pc and tc and pc in out.columns and tc in out.columns:
        return out.drop_duplicates(subset=[pc, tc], keep="first").reset_index(drop=True)
    if tc and tc in out.columns:
        return out.drop_duplicates(subset=[tc], keep="first").reset_index(drop=True)
    return out


def build_dev_tz_matrix_rows(
    mdf: pd.DataFrame,
    project_data: Optional[pd.DataFrame],
    ss: Any,
) -> Tuple[List[Dict[str, Any]], str]:
    rows: List[Dict[str, Any]] = []

    if mdf is None or getattr(mdf, "empty", True):
        return [], ""
    mdf = ensure_msp_df_for_dev_matrix(mdf)
    if mdf is None or getattr(mdf, "empty", True):
        return [], ""

    # На всякий случай пересчитываем section из дерева (старые сессии/БД могли иметь ЛОТ вместо родителя ур.2)
    if mdf is not None and not getattr(mdf, "empty", True) and "task name" in mdf.columns:
        try:
            from web_loader import _fill_section_from_task_tree

            mdf = _fill_section_from_task_tree(mdf.copy())
        except Exception:
            pass
    if mdf is not None and not getattr(mdf, "empty", True):
        mdf = dedupe_msp_for_developer_projects(mdf)

    _prefs = load_developer_projects_matrix_prefs()

    def effective_title(row_key: str, default_title: str) -> str:
        tt = (_prefs.get("titles") or {}).get(row_key)
        if isinstance(tt, str) and tt.strip():
            return tt.strip()
        return default_title

    def effective_match(row_key: str, kw: dict) -> dict:
        patch = (_prefs.get("matches") or {}).get(row_key)
        out = copy.deepcopy(kw)
        if isinstance(patch, dict) and patch:
            out.update(patch)
        return out

    def add_row(
        group: str,
        label: str,
        plan_s: str,
        fact_s: str,
        otkl_s: str,
        *,
        warn_pct: bool = False,
        warn_directives: bool = False,
        phase: str = "",
        row_key: str = "",
    ) -> None:
        rows.append(
            {
                "group": group,
                "label": label,
                "plan": plan_s,
                "fact": fact_s,
                "otkl": otkl_s,
                "warn": bool(warn_pct or warn_directives),
                "warn_pct": bool(warn_pct),
                "warn_directives": bool(warn_directives),
                "phase": phase,
                "row_key": str(row_key or "").strip(),
            }
        )

    cap = ""
    if "project name" in mdf.columns and mdf["project name"].notna().any():
        cap = str(mdf["project name"].dropna().astype(str).iloc[0]).strip()

    def _msp_row(
        phase: str,
        group: str,
        label: str,
        kw: dict,
        *,
        row_key: str,
    ) -> None:
        lab = effective_title(row_key, label)
        kw2 = effective_match(row_key, kw)
        sub = _match_tasks_like_msp_row(mdf, kw2)
        if sub is None or sub.empty:
            add_row(group, lab, "Н/Д", "Н/Д", "Н/Д", phase=phase, row_key=row_key)
            return
        # ТЗ: в каждой ячейке План/Факт/Откл. — одно значение (одна дата / один текст отклонения), без «дата1 / дата2».
        ps, fs, os, _ok, w = _one_milestone_cell(sub)
        add_row(group, lab, ps, fs, os, warn_pct=bool(w), phase=phase, row_key=row_key)

    # Порядок столбцов — по референсу (file-002: вехи Ковенантов; file-003: ДС/ТЕССА до ИРД/ПОС)
    _rk = iter(_DEV_MATRIX_ROW_KEYS)
    specs_invest_msp: List[Tuple[str, str, str, dict]] = [
        # По ТЗ: в реальной MSP — имя задачи + ур.5; во внутренних CSV вехи часто в колонке «Фаза» (см. phase_needles).
        (
            "invest",
            "ЗУ / Ковенанты",
            "Аренда ЗУ",
            {
                "level": 5.0,
                # ТЗ (редакции): «Регистрация договора субаренды» и «Подготовка договора аренды».
                "names_any": [
                    "Регистрация договора субаренды",
                    "Подготовка договора аренды",
                    "договор субаренды",
                    "субаренд",
                ],
                "phase_needles": [
                    "Аренда ЗУ",
                    "субаренд",
                    "Инвестиционная. Аренда",
                    "аренда зу",
                    "договор субаренды",
                ],
            },
        ),
        (
            "invest",
            "Ковенанты",
            "Готовый Продукт",
            {
                "level": 5.0,
                "names_any": [
                    "Рассмотрение и утверждение на инвестиционном комитете",
                    "инвестиционном комитете",
                    "Готовый продукт",
                    "готовый продукт",
                    "ГОТОВЫЙ ПРОДУКТ",
                    "Этап ГОТОВЫЙ ПРОДУКТ",
                    "Этап ГОТОВЫЙ",
                    "Инвестиционная. Готовый",
                ],
                "phase_needles": [
                    "Готовый продукт",
                    "готовый продукт",
                    "ГОТОВЫЙ ПРОДУКТ",
                    "Этап ГОТОВЫЙ ПРОДУКТ",
                    "Этап ГОТОВЫЙ",
                    "Инвестиционная. Готовый",
                    "инвестиционная. готовый",
                ],
            },
        ),
        (
            "invest",
            "Ковенанты",
            "ГПЗУ",
            {
                "level": 5.0,
                "parent_l2_contains": "Ковенанты",
                "names_any": [
                    "ГПЗУ",
                    "гпзу",
                    "Градплан",
                    "градостроительн",
                    "план территории",
                    "градостроительного плана",
                    "городской план",
                    "зонирования территории",
                    "Согласование ГП",
                    "( ГП,",
                    "ГП, АР",
                    "планировочных решений",
                    "Предварительные планировочные",
                    "Предварительные планировочные решения",
                    "Эскизный проект (",
                ],
                "phase_needles": [
                    "ГПЗУ",
                    "гпзу",
                    "градостроительн",
                    "план территории",
                    "Градплан",
                    "Инвестиционная. ГПЗУ",
                    "градостроительного плана",
                    "зонирования",
                    "Согласование ГП",
                    "( ГП,",
                    "ГП, АР",
                    "планировочных решений",
                    "Предварительные планировочные",
                    "Предварительные планировочные решения",
                ],
            },
        ),
        (
            "life",
            "Ковенанты",
            "Экспертиза стадия ст П",
            {
                "level": 5.0,
                "names_any": ["Экспертиза ПД", "Экспертиза", "экспертиза пд"],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": ["Экспертиза стадия", "Экспертиза ПД", "Экспертиза стП"],
            },
        ),
        (
            "life",
            "Ковенанты",
            "КОМАНДА РП",
            {
                "level": 5.0,
                "names_any": [
                    "Подбор команды",
                    "Команда РП",
                    "КОМАНДА РП",
                    "Распоряжение Руководителя Холдинга",
                    "Руководителя Холдинга об утверждении",
                    "назначен руководител",
                    "проектную группу",
                ],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": [
                    "Команда РП",
                    "КОМАНДА РП",
                    "Подбор команды",
                    "руководител проекта",
                    "назначени руководител",
                ],
            },
        ),
        (
            "life",
            "Ковенанты",
            "РС",
            {
                "level": 5.0,
                "names_any": [
                    "Разрешение РС",
                    "Разрешение на строительство (РС)",
                    "Разрешение на строительство",
                    "разрешение на строительство",
                ],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": [
                    ". РС",
                    "Разрешение на строительство",
                    "Инвестиционная. РС",
                    "инвестиционная. рс",
                    "Жизнь проекта. РС",
                ],
            },
        ),
        (
            "life",
            "Ковенанты",
            "РД (1вар)",
            {
                "level": 5.0,
                "names_any": [
                    "Стадия Рабочая Документация (РД)",
                    "Рабочая Документация (РД)",
                    "стадия РД",
                    "стадия рабочая документация",
                ],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": ["РД (1", "1вар)", "1 вар)", "Рабочая Документация", "стадия РД"],
            },
        ),
    ]
    for phase, group, label, kw in specs_invest_msp:
        _msp_row(phase, group, label, kw, row_key=str(next(_rk)))

    def _fmtml(v: float) -> str:
        # ТЗ: млн руб., два знака после запятой
        return f"{v:.2f}".replace(".", ",")

    rk_ds = str(next(_rk))
    pm, fm, om = _ds_plan_fact_otkl_mln(_bddds_df_for_dev_matrix(mdf, project_data, ss))
    if pm is None:
        add_row(
            "Финансы",
            effective_title(rk_ds, "Выборка ДС, млн руб."),
            "Н/Д",
            "Н/Д",
            "Н/Д",
            phase="life",
            row_key=rk_ds,
        )
    else:
        add_row(
            "Финансы",
            effective_title(rk_ds, "Выборка ДС, млн руб."),
            _fmtml(pm),
            _fmtml(fm),
            _fmtml(om),
            phase="life",
            row_key=rk_ds,
        )

    rk_tp = str(next(_rk))
    tp, tf, to, warn_t, _tessa_hint = _predpisaniya_combined(mdf, ss)
    add_row(
        "ТЕССА",
        effective_title(rk_tp, "ПРЕДПИСАНИЯ"),
        tp,
        tf,
        to,
        warn_directives=warn_t,
        phase="life",
        row_key=rk_tp,
    )

    specs_invest_tail: List[Tuple[str, str, str, dict]] = [
        (
            "life",
            "ИРД",
            "Подготовительный этап (ТУ, ПРОЕКТ временные сети ЭЛ-ВО)",
            {
                "level": 4.0,
                "names_any": ["Электроснабжение:", "Электроснабжение"],
                "block_contains": "ИРД",
                "phase_needles": [
                    "Электроснабжение",
                    "временные сети ЭЛ",
                    "ЭЛ-ВО",
                    "Эл-во",
                    "сети ЭЛ",
                    "ИСЭ",
                    "инженерные сети: электро",
                    "ВНУТРИПЛОЩАДОЧНЫЕ ИНЖЕНЕРНЫЕ СЕТИ: ЭЛЕКТРО",
                ],
                # Не смешивать со столбцом «примыкания» (часто та же длинная строка «Подготовительный этап…»)
                "phase_exclude_needles": ["Примыкания", "УДС", "примыкания к удс"],
            },
        ),
        (
            "life",
            "ИРД",
            "Подготовительный этап (ТУ, ПРОЕКТ временные примыкания)",
            {
                "level": 4.0,
                "names_any": ["Примыкания к УДС:", "Примыкания к УДС"],
                "block_contains": "ИРД",
                "phase_needles": ["Примыкания к УДС", "временные примыкания"],
                "phase_exclude_needles": ["ЭЛ-ВО", "Электроснабжение", "сети ЭЛ", "ИСЭ"],
            },
        ),
        (
            "life",
            "Проектные работы",
            "ПОС (1 вар)",
            {
                "level": None,
                "names_any": [
                    "Согласование ПЗУ, ПОС, ПОДД с КРМО, МОЭСК, Мособлгаз, Мосавтодор",
                    "Согласование ПЗУ",
                    "ПОС, ПОДД",
                ],
                "block_contains": "ПРОЕКТ",
                "phase_needles": [
                    "ПОС (1 вар)",
                    "ПОС (1вар)",
                    "ПОС (1 этап)",
                    "ПОС (1этап)",
                    "ПОС (1 очер",
                    "Согласование ПЗУ",
                ],
            },
        ),
        (
            "life",
            "Ковенанты",
            "Начало финансирования СМР",
            {
                "level": 5.0,
                "name_contains": "Начало финансирования",
                "parent_l2_contains": "Ковенанты",
                "phase_needles": ["Начало финансирования"],
            },
        ),
        (
            "life",
            "Ковенанты",
            "Начало СМР",
            {
                "level": 5.0,
                "names_any": [
                    "Начало СМР",
                    "начало смр",
                    "СМР (начало)",
                    "смр (начало)",
                ],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": ["Начало СМР", "СМР (начало)", "смр (начало)"],
            },
        ),
    ]
    for phase, group, label, kw in specs_invest_tail:
        _msp_row(phase, group, label, kw, row_key=str(next(_rk)))

    specs_life: List[Tuple[str, str, str, dict]] = [
        (
            "life",
            "Ковенанты",
            "ТЕХ.ПРИСОЕДИНЕНИЯ (ГАЗ, ЭЛ-ВО, ВОДА)",
            {
                "level": 5.0,
                "names_any": [
                    "Пуск электричества",
                    "Пуск газа",
                    "Пуск воды",
                    "Пуск водоснабжения",
                    "водоснабжения",
                    "ТЕХПРИСОЕДИНЕНИЯ",
                    "техприсоединения",
                    "ГАЗ, ЭП",
                    "ЭП, ВО",
                    "ВИС",
                    "вода",
                ],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": [
                    "ТЕХ.ПРИСОЕДИНЕНИЯ",
                    "ТЕХПРИСОЕДИНЕНИЯ",
                    "ПРИСОЕДИНЕНИЯ (ГАЗ",
                    "ГАЗ, ЭЛ-ВО",
                    "ГАЗ, ЭП",
                    "ЭП, ВО",
                    "ЭП ВО",
                    "ГАЗ, ВОД",
                    "ВОДА",
                    "водоснабж",
                    "Пуск электричества",
                    "Пуск газа",
                    "Пуск вод",
                    "Жизнь проекта. ТЕХ",
                    "Жизнь проекта. ТЕХПРИСОЕДИНЕНИЯ",
                    "Инвестиционная. ТЕХ",
                ],
            },
        ),
        (
            "life",
            "Ковенанты",
            "ЗОС",
            {
                "level": 5.0,
                "names_any": [
                    "Заключение о соответствии",
                    "заключение о соответствии",
                    "ЗОС)",
                    "зос)",
                ],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": [
                    "Заключение о соответствии",
                    ". ЗОС",
                    "Жизнь проекта. ЗОС",
                    "Инвестиционная. ЗОС",
                    "инвестиционная. зос",
                ],
            },
        ),
        (
            "life",
            "Ковенанты",
            "РВ",
            {
                "level": 5.0,
                "names_any": [
                    "Разрешение на ввод в эксплуатацию (РВ)",
                    "Разрешение на ввод",
                    "ввод в эксплуатацию",
                    "Разрешение на ввод объекта",
                    "Разрешение на ввод в эксплуатацию",
                ],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": [
                    ". РВ",
                    " РВ",
                    "Разрешение на ввод",
                    "ввод в эксплуатацию",
                    "Разрешение на ввод объекта",
                    "Жизнь проекта. РВ",
                    "Инвестиционная. РВ",
                ],
            },
        ),
        (
            "life",
            "Ковенанты",
            "Право 1",
            {
                "level": 5.0,
                "names_any": ["Право 1", "Право1", "право 1", "Право 1 на"],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": [
                    "Право 1",
                    "Право1",
                    "право 1",
                    "Право 1 на",
                    "Жизнь проекта. Право 1",
                    "Инвестиционная. Право 1",
                ],
            },
        ),
        (
            "life",
            "Ковенанты",
            "Выкуп ЗУ",
            {
                "level": 5.0,
                "names_any": [
                    "Выкуп земельного участка",
                    "Выкуп ЗУ",
                    "Выкуп участка",
                    "выкуп земли",
                    "выкуп земельного",
                ],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": [
                    "Выкуп ЗУ",
                    "Выкуп земельного",
                    "Выкуп участка",
                    "выкуп земли",
                    "Жизнь проекта. Выкуп",
                    "Инвестиционная. Выкуп",
                ],
            },
        ),
        (
            "life",
            "Ковенанты",
            "Право 2 на Застройщика",
            {
                "level": 5.0,
                "names_any": [
                    "Право 2 на Застройщика",
                    "Право 2",
                    "Право2",
                ],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": [
                    "Право 2 на Застройщика",
                    "Право 2",
                    "Жизнь проекта. Право 2",
                    "Инвестиционная. Право 2",
                ],
            },
        ),
        (
            "life",
            "Ковенанты",
            "Передача БОКСОВ резидентам",
            {
                "level": 5.0,
                "names_any": [
                    "Передача боксов резидентам",
                    "Передача боксов",
                    "Передача бокс",
                    "боксов резидент",
                    "передачи резидент",
                    "передаче резидент",
                    "для передачи резидент",
                    "сформированная документация для передачи",
                    "по боксам)",
                    "БОНУСОВ",
                    "бонусов резидент",
                    "передача бонус",
                ],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": [
                    "Передача боксов",
                    "передачи резидент",
                    "БОКСОВ",
                    "БОНУСОВ",
                    "бонусов резидент",
                    "Передача бонус",
                    "Жизнь проекта. Передача",
                    "Инвестиционная. Передача",
                ],
            },
        ),
    ]
    for phase, group, label, kw in specs_life:
        _msp_row(phase, group, label, kw, row_key=str(next(_rk)))

    try:
        next(_rk)
    except StopIteration:
        pass
    else:
        raise RuntimeError("_DEV_MATRIX_ROW_KEYS не совпадает с генерацией строк матрицы")

    return rows, cap


_DEV_TZ_MATRIX_CSS = """
<style>
/*
 * Одна таблица: строки шапки и данных всегда совпадают.
 * Первый столбец — position:sticky;left:0 внутри .dev-tz-matrix-wrap (overflow-x:auto),
 * остальные th без вертикального sticky из глобального _TABLE_CSS (иначе ломается шапка).
 */
.dev-tz-matrix-wrap {
  width: 100%;
  max-width: 100%;
  margin-bottom: 0.75rem;
  box-sizing: border-box;
  overflow-x: auto;
  overflow-y: visible;
  overscroll-behavior-x: contain;
  -webkit-overflow-scrolling: touch;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide {
  border: 2px solid rgba(220, 228, 240, 0.45);
  border-collapse: separate;
  border-spacing: 0;
  width: max-content !important;
  min-width: max(720px, 100%) !important;
  max-width: none !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide thead th:not(.dev-tz-th-project) {
  border: 1px solid rgba(200, 210, 225, 0.5) !important;
  border-bottom: 2px solid rgba(200, 210, 225, 0.6) !important;
  box-sizing: border-box;
  position: relative !important;
  top: auto !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide thead th.dev-tz-th-project {
  border: 1px solid rgba(200, 210, 225, 0.5) !important;
  border-bottom: 2px solid rgba(200, 210, 225, 0.6) !important;
  box-sizing: border-box;
  position: sticky !important;
  left: 0 !important;
  top: auto !important;
  z-index: 14 !important;
  text-align: center !important;
  vertical-align: middle !important;
  font-weight: 700;
  font-size: 12px;
  padding: 6px 10px;
  color: #e8f5e9;
  background: #1a3328 !important;
  min-width: 10em;
  width: 11em;
  max-width: 14em;
  border-right: 2px solid rgba(190, 214, 242, 0.65) !important;
  box-shadow: 8px 0 20px -10px rgba(0, 0, 0, 0.55);
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide tbody td {
  border: 1px solid rgba(200, 210, 225, 0.38) !important;
  border-top: 1px solid rgba(200, 210, 225, 0.45) !important;
  vertical-align: middle !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide tbody tr:hover td {
  background: inherit;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide tbody tr:nth-child(even) td {
  background: inherit;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide th.dev-tz-ghead {
  text-align: center !important;
  vertical-align: middle !important;
  font-weight: 700;
  font-size: 13px;
  padding: 6px 8px;
  background: linear-gradient(180deg, rgba(34, 139, 34, 0.35) 0%, rgba(25, 90, 25, 0.25) 100%) !important;
  color: #e8f5e9;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide th.dev-tz-ghead-life {
  text-align: center !important;
  vertical-align: middle !important;
  background: linear-gradient(180deg, rgba(92, 100, 115, 0.58) 0%, rgba(55, 61, 72, 0.48) 100%) !important;
  color: #e8eaed !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide th.dev-tz-milestone {
  text-align: center !important;
  vertical-align: middle !important;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.25;
  max-width: 9em;
  padding: 5px 6px;
  color: #c9d1d9;
  background: rgba(26, 28, 35, 0.92) !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide th.dev-tz-sub {
  text-align: center !important;
  vertical-align: middle !important;
  font-size: 11px;
  font-weight: 500;
  color: #9aa4b2;
  padding: 5px 6px;
  background: rgba(22, 24, 32, 0.95) !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide th.dev-tz-milestone.dev-tz-inv-block,
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide th.dev-tz-sub.dev-tz-inv-block {
  background: linear-gradient(180deg, rgba(34, 139, 34, 0.35) 0%, rgba(25, 90, 25, 0.25) 100%) !important;
  color: #e8f5e9 !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide th.dev-tz-sub.dev-tz-inv-block {
  text-align: center !important;
  vertical-align: middle !important;
  font-weight: 600;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide th.dev-tz-milestone.dev-tz-life-block,
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide th.dev-tz-sub.dev-tz-life-block {
  background: linear-gradient(180deg, rgba(92, 100, 115, 0.58) 0%, rgba(55, 61, 72, 0.48) 100%) !important;
  color: #e8eaed !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide th.dev-tz-sub.dev-tz-life-block {
  text-align: center !important;
  vertical-align: middle !important;
  font-weight: 600;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide td.dev-tz-td-project {
  position: sticky !important;
  left: 0 !important;
  z-index: 8 !important;
  text-align: center !important;
  font-weight: 600;
  font-size: 12px;
  padding: 6px 10px;
  background: #161f2b !important;
  color: #e6edf3;
  word-wrap: break-word;
  overflow-wrap: anywhere;
  border-right: 2px solid rgba(190, 214, 242, 0.45) !important;
  box-shadow: 8px 0 18px -10px rgba(0, 0, 0, 0.45);
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide td.dev-tz-text-pct-warn {
  color: #fb923c !important;
  font-weight: 600 !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide td.dev-tz-otkl-ok {
  color: #22c55e !important;
  font-weight: 600 !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide td.dev-tz-otkl-bad {
  color: #ef4444 !important;
  font-weight: 600 !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide td.dev-tz-date-vert {
  writing-mode: vertical-rl;
  text-orientation: mixed;
  max-height: 7.5em;
  white-space: nowrap;
  vertical-align: middle;
  text-align: center;
  padding: 8px 4px !important;
}
.dev-tz-matrix-wrap table.rendered-table.dev-tz-wide td.dev-tz-directives-warn {
  background: rgba(234, 88, 12, 0.15) !important;
}
</style>
"""


def _dev_tz_matrix_row_key(r: Dict[str, Any]) -> Tuple[str, str]:
    """Стабильный ключ строки матрицы для сопоставления блоков разных проектов."""
    rid = str(r.get("row_key") or "").strip()
    if rid:
        return ("__devmx_key__", rid)
    return (str(r.get("group") or ""), str(r.get("label") or ""))


def _dev_tz_matrix_cell_classes(
    r: Dict[str, Any],
    col: str,
    *,
    vertical_dates: bool,
) -> str:
    """CSS-классы для ячейки План / Факт / Откл."""
    parts: List[str] = []
    v = r.get(col) or ""
    warn_pct = bool(r.get("warn_pct"))
    warn_dir = bool(r.get("warn_directives"))
    if col in ("plan", "fact") and warn_pct and _looks_like_ru_date_cell(v):
        parts.append("dev-tz-text-pct-warn")
    if _dev_tz_apply_vert_date(vertical_dates, col, v):
        parts.append("dev-tz-date-vert")
    if col == "otkl":
        if warn_dir:
            parts.append("dev-tz-directives-warn")
        dd = _parse_otkl_days_display(v)
        if dd is not None:
            parts.append("dev-tz-otkl-ok" if dd >= 0 else "dev-tz-otkl-bad")
    return " ".join(parts).strip()


def render_dev_tz_matrix(
    rows: Union[List[Dict[str, Any]], List[List[Dict[str, Any]]]],
    table_css: str,
    *,
    project_labels: Optional[List[str]] = None,
    vertical_dates: bool = False,
) -> None:
    """
    Первая колонка «Проект» — только название; далее «Инвестиционная фаза» / «Жизнь проекта»
    и под каждой вехой План / Факт / Откл.

    ``project_labels``: подпись в колонке «Проект» для каждой строки (порядок = порядок блоков).
    ``vertical_dates``: писать даты в План/Факт вертикально (ТЗ).
    """
    import streamlit as st

    blocks: List[List[Dict[str, Any]]]
    if rows and isinstance(rows[0], dict):
        blocks = [rows]  # type: ignore[list-item]
    else:
        blocks = [b for b in (rows or []) if isinstance(b, list)]  # type: ignore[assignment]

    if not blocks or not blocks[0]:
        st.info("Нет строк матрицы.")
        return

    n_blocks = len(blocks)
    if project_labels is None:
        row_labels = [""] * n_blocks
    else:
        row_labels = [str(x or "").strip() for x in project_labels]
        if len(row_labels) < n_blocks:
            row_labels.extend([""] * (n_blocks - len(row_labels)))
        else:
            row_labels = row_labels[:n_blocks]

    template = blocks[0]
    esc = html_module.escape
    prefs = load_developer_projects_matrix_prefs()
    sc_map = prefs.get("subcolumns") or {}
    l_plan = str(sc_map.get("plan") or "План").strip() or "План"
    l_fact = str(sc_map.get("fact") or "Факт").strip() or "Факт"
    l_otkl = str(sc_map.get("otkl") or "Откл.").strip() or "Откл."
    invest_labels = [r["label"] for r in template if r.get("phase") == "invest"]
    life_labels = [r["label"] for r in template if r.get("phase") == "life"]
    n_inv = max(1, len(invest_labels))
    n_life = max(0, len(life_labels))
    col_span_inv = n_inv * 3
    col_span_life = n_life * 3

    mline: List[str] = []
    subline: List[str] = []
    for r in template:
        lab = r.get("label") or ""
        ph = str(r.get("phase") or "life").strip().lower()
        band = "dev-tz-inv-block" if ph == "invest" else "dev-tz-life-block"
        mline.append(
            f'<th colspan="3" class="dev-tz-milestone {band}" title="{esc(str(lab))}">{esc(str(lab))}</th>'
        )
        subline.extend(
            [
                f'<th class="dev-tz-sub {band}">{esc(l_plan)}</th>',
                f'<th class="dev-tz-sub {band}">{esc(l_fact)}</th>',
                f'<th class="dev-tz-sub {band}">{esc(l_otkl)}</th>',
            ]
        )

    head_rows: List[str] = [
        "<tr>"
        '<th rowspan="3" class="dev-tz-th-project">Проект</th>'
        f'<th colspan="{col_span_inv}" class="dev-tz-ghead" style="text-align:center;vertical-align:middle;">Инвестиционная фаза</th>'
        f'<th colspan="{col_span_life}" class="dev-tz-ghead dev-tz-ghead-life" style="text-align:center;vertical-align:middle;">Жизнь проекта</th>'
        "</tr>"
    ]
    head_rows.append("<tr>" + "".join(mline) + "</tr>")
    head_rows.append("<tr>" + "".join(subline) + "</tr>")
    thead = "<thead>" + "".join(head_rows) + "</thead>"

    body_trs: List[str] = []
    tmpl_keys: List[Tuple[str, str]] = [_dev_tz_matrix_row_key(r) for r in template]
    for bi, block in enumerate(blocks):
        row_by_key = {_dev_tz_matrix_row_key(r): r for r in block}
        body_cells: List[str] = []
        for k in tmpl_keys:
            r = row_by_key.get(k)
            if r is None:
                for _ in ("plan", "fact", "otkl"):
                    body_cells.append("<td>Н/Д</td>")
                continue
            for key in ("plan", "fact", "otkl"):
                v = r.get(key) or ""
                cls = _dev_tz_matrix_cell_classes(r, key, vertical_dates=vertical_dates)
                oc = f' class="{esc(cls)}"' if cls else ""
                iv = ""
                if _dev_tz_apply_vert_date(vertical_dates, key, v):
                    iv = (
                        ' style="writing-mode:vertical-rl;text-orientation:mixed;'
                        "max-height:7.5em;white-space:nowrap;vertical-align:middle;"
                        'text-align:center;padding:8px 4px;"'
                    )
                body_cells.append(f"<td{oc}{iv}>{esc(str(v))}</td>")
        plab = row_labels[bi] if bi < len(row_labels) else ""
        body_trs.append(
            '<tr><td class="dev-tz-td-project">' + esc(plab) + "</td>" + "".join(body_cells) + "</tr>"
        )

    html_tbl = (
        '<table class="rendered-table dev-tz-wide" border="0">'
        + thead
        + "<tbody>"
        + "".join(body_trs)
        + "</tbody></table>"
    )
    frag = (
        table_css
        + _DEV_TZ_MATRIX_CSS
        + '<div class="dev-tz-matrix-wrap">'
        + html_tbl
        + "</div>"
    )
    # st.markdown(unsafe_allow_html) на Streamlit Cloud срезает style/class у <td>.
    # st.html отдаёт фрагмент через отдельный путь разметки — вертикальные даты остаются.
    if hasattr(st, "html"):
        st.html(frag)
    else:
        st.markdown(frag, unsafe_allow_html=True)


# ── Контрольные точки (Сроки / макет file-009): проекты × вехи ───────────────

# Вехи «Контрольные точки»: доп. оранжевая подсветка ячеек при % ≠ 100% только для ГПЗУ / Экспертизы стадии П.
CONTROL_POINTS_ORANGE_PCT_SLUGS: frozenset = frozenset({"gpzu", "exp_pd"})


def _is_orange_pct_milestone(slug: str, title: str) -> bool:
    """Определить, что веха относится к ГПЗУ/Экспертизе стадии П (в т.ч. при кастомном slug)."""
    s_slug = str(slug or "").strip().lower()
    if s_slug in CONTROL_POINTS_ORANGE_PCT_SLUGS:
        return True
    s_title = str(title or "").strip().lower().replace("ё", "е")
    return ("гпзу" in s_title) or ("экспертиз" in s_title)

# Контрольные точки: список и правила сопоставления по согласованному ТЗ.
# Контрольные точки (ТЗ скрин): задачи блока «Ковенанты», План = Базовое окончание, Факт = Окончание,
# столбцы MSP → см. маппинг web_loader (_MSP_COLUMN_REMAP).
CONTROL_POINT_MILESTONES: List[Tuple[str, str, dict]] = [
    ("ГПЗУ", "gpzu", {"level": 5.0, "names_any": ["ГПЗУ"], "parent_l2_contains": "Ковенанты"}),
    (
        "Экспертиза стадии П",
        "exp_pd",
        {
            "level": 5.0,
            "names_any": [
                "Экспертиза стадии П",
                "Экспертиза стадии",
                "Экспертиза ПД",
                "экспертиза пд",
                "Экспертиза проектной документации",
                "экспертиза проектной документации",
                "Экспертиза",
            ],
            "parent_l2_contains": "Ковенанты",
        },
    ),
    (
        "Начало финансирования",
        "fin_start",
        {
            "level": 5.0,
            "names_any": [
                "КОД_ОТКР_ФИНАНС",
                "КОД ОТКР ФИНАНС",
                "КОД, ОТКР. ФИНАНС.",
                "КОД ОТКР. ФИНАНС.",
                "ОТКР. ФИНАНС.",
                "ОТКР ФИНАНС",
                "(начало финансирования)",
                "Начало финансирования",
                "начало финансирования",
                "КОД, ОТКР. ФИНАНС. (начало финансирования)",
            ],
            "parent_l2_contains": "Ковенанты",
        },
    ),
    (
        "Стадия РД",
        "rd_stage",
        {
            "level": 5.0,
            "names_any": ["Стадия РД", "Стадия Рабочая Документация (РД)", "Рабочая Документация (РД)"],
            "parent_l2_contains": "Ковенанты",
        },
    ),
    (
        "РС",
        "rs",
        {
            "level": 5.0,
            "names_any": ["Разрешение РС", "Разрешение на строительство (РС)", "Разрешение на строительство"],
            "parent_l2_contains": "Ковенанты",
        },
    ),
    ("Завершение СМР", "smr_finish", {"level": 5.0, "names_any": ["Завершение СМР"], "parent_l2_contains": "Ковенанты"}),
    ("Пуск электричества", "power_on", {"level": 5.0, "names_any": ["Пуск электричества"], "parent_l2_contains": "Ковенанты"}),
    ("Пуск газа", "gas_on", {"level": 5.0, "names_any": ["Пуск газа"], "parent_l2_contains": "Ковенанты"}),
    (
        "РВ",
        "rv",
        {
            "level": 5.0,
            "names_any": [
                "Разрешение на ввод в эксплуатацию (РВ)",
                "Разрешение на ввод в эксплуатацию",
                "Разрешение на ввод объекта",
                "Разрешение на ввод",
                "ввод в эксплуатацию",
            ],
            "names_exact_any": ["РВ"],
            "parent_l2_contains": "Ковенанты",
        },
    ),
    ("Право 1", "pravo1", {"level": 5.0, "names_any": ["Право 1"], "parent_l2_contains": "Ковенанты"}),
    ("Выкуп ЗУ", "vykup_zu", {"level": 5.0, "names_any": ["Выкуп ЗУ", "Выкуп земельного участка"], "parent_l2_contains": "Ковенанты"}),
    ("Право 2", "pravo2", {"level": 5.0, "names_any": ["Право 2", "Право 2 на Застройщика"], "parent_l2_contains": "Ковенанты"}),
]

_CP_MILESTONES_JSON_KEY = "control_points_milestones_json"


def get_control_point_milestones_effective() -> List[Tuple[str, str, dict]]:
    """
    Вехи для отчёта «Контрольные точки»: из настроек БД (JSON) или встроенный список CONTROL_POINT_MILESTONES.
    Админ задаёт title (заголовок столбца), slug (ключ колонок), match (правила сопоставления с MSP).
    """
    try:
        from settings import get_setting

        raw = (get_setting(_CP_MILESTONES_JSON_KEY) or "").strip()
        if not raw:
            return CONTROL_POINT_MILESTONES
        import json

        data = json.loads(raw)
        if not isinstance(data, list):
            return CONTROL_POINT_MILESTONES
        out: List[Tuple[str, str, dict]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            slug = str(item.get("slug", "")).strip()
            match = item.get("match")
            if not title or not slug or not isinstance(match, dict):
                continue
            out.append((title, slug, match))
        return out if out else CONTROL_POINT_MILESTONES
    except Exception:
        return CONTROL_POINT_MILESTONES


def control_point_milestones_default_json() -> str:
    """JSON по умолчанию (как в коде) — для админки и сброса."""
    import json

    data = [{"title": t, "slug": s, "match": m} for t, s, m in CONTROL_POINT_MILESTONES]
    return json.dumps(data, ensure_ascii=False, indent=2)


def save_control_point_milestones_json(json_str: str, updated_by: str) -> Tuple[bool, str]:
    """Сохранение JSON величин вех; пустая строка = сброс на встроенные правила."""
    try:
        import json

        from settings import set_setting

        s = (json_str or "").strip()
        if not s:
            set_setting(
                _CP_MILESTONES_JSON_KEY,
                "",
                description="Вехи «Контрольные точки» (JSON); пусто = код по умолчанию",
                updated_by=updated_by,
            )
            return True, "Сброшено на встроенные правила из кода."
        parsed = json.loads(s)
        if not isinstance(parsed, list):
            return False, "Ожидается JSON-массив объектов с полями title, slug, match."
        out: List[Tuple[str, str, dict]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            slug = str(item.get("slug", "")).strip()
            match = item.get("match")
            if not title or not slug or not isinstance(match, dict):
                return False, "Каждый элемент: { \"title\", \"slug\", \"match\": { ... } }."
            out.append((title, slug, match))
        if not out:
            return False, "Нет ни одной валидной вехи."
        set_setting(
            _CP_MILESTONES_JSON_KEY,
            s,
            description="Вехи «Контрольные точки» (JSON): заголовки и match к MSP",
            updated_by=updated_by,
        )
        return True, f"Сохранено вех: {len(out)}."
    except Exception as e:
        return False, str(e)[:500]


def _control_points_project_filter_options(
    df: pd.DataFrame,
) -> Tuple[List[str], Dict[str, List[str]]]:
    """Подписи для фильтра «Проект» и карта подпись → список сырых project name (без дублей логического проекта)."""
    if df is None or df.empty or "project name" not in df.columns:
        return [], {}
    raws = df["project name"].dropna().astype(str).str.strip().unique().tolist()
    groups: Dict[str, List[str]] = defaultdict(list)
    for p in raws:
        groups[_control_points_project_group_key(p)].append(str(p).strip())
    labels_map: Dict[str, List[str]] = {}
    for gk, rlist in groups.items():
        rlist = sorted(set(rlist))
        lab = _control_points_project_label(gk, rlist)
        if lab in labels_map:
            labels_map[lab] = sorted(set(labels_map[lab] + rlist))
        else:
            labels_map[lab] = rlist
    ordered = sorted(labels_map.keys(), key=lambda x: x.lower())
    return ordered, labels_map


def _control_points_prepare_msp_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Для «Контрольные точки»: гарантировать canonical-колонки base end / plan end (и при наличии actual finish),
    если в файле русские/альтернативные заголовки без прохода через web_loader.
    """
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()
    if "base end" not in out.columns:
        be = _find_col(
            out,
            ["base end", "Baseline Finish", "Базовое окончание", "Базовое_окончание"],
        )
        if be:
            out["base end"] = out[be]
    if "plan end" not in out.columns:
        pe = _find_col(
            out,
            ["plan end", "План окончание", "План_окончание", "Окончание"],
        )
        if pe:
            out["plan end"] = out[pe]
    if "actual finish" not in out.columns:
        af = _find_col(
            out,
            ["actual finish", "Фактическое окончание", "Фактическое_окончание"],
        )
        if af:
            out["actual finish"] = out[af]
    if "pct complete" not in out.columns:
        pc = _find_col(
            out,
            [
                "pct complete",
                "percent complete",
                "% complete",
                "Процент_завершения",
                "Процент завершения",
                "процент выполнения",
            ],
        )
        if not pc:
            # Fallback для выгрузок с нестандартными заголовками колонки процента.
            for c in out.columns:
                cl = str(c).strip().lower().replace("_", " ")
                if (
                    "%" in cl
                    or "percent" in cl
                    or "процент" in cl
                    or "выполн" in cl
                    or "готов" in cl
                ):
                    pc = c
                    break
        if pc:
            out["pct complete"] = out[pc]
    return out


def _project_name_column(df: pd.DataFrame) -> Optional[str]:
    if "project name" in df.columns:
        return "project name"
    return _find_col(df, ["Проект", "Project", "project"])


def _match_milestone_tasks(mdf: pd.DataFrame, kw: dict) -> pd.DataFrame:
    """Те же правила, что и строка матрицы девелоперских проектов."""
    return _match_tasks_like_msp_row(mdf, kw)


def _one_milestone_cell(rows: pd.DataFrame) -> Tuple[str, str, str, bool, bool]:
    """
    План = базовое окончание (base end), Факт = «Окончание» (plan end после загрузки MSP).
    Откл. = План − Факт (календарные дни), как в матрице девелоперских проектов.
    Пятый элемент — подсветка по % выполнения у строки-представителя вехи (не 100% при известном %).
    """
    if rows is None or rows.empty:
        return "Н/Д", "Н/Д", "Н/Д", False, False
    tc = _task_name_col(rows)
    if tc and tc in rows.columns:
        r = rows.sort_values(by=tc).iloc[0]
    else:
        r = rows.iloc[0]
    pdt, fdt, pct = _msp_plan_fact_pct(r)
    # Предупреждение по % — только по строке-представителе вехи (та же, что даёт План/Факт),
    # иначе при нескольких совпадениях под одну веху «оранжевый» статус липнет ко всем столбцам.
    def _row_has_pct_lt_100(rr: pd.Series) -> bool:
        if "pct complete" not in rr.index:
            return False
        v = rr["pct complete"]
        if isinstance(v, pd.Series):
            for _x in v.tolist():
                if _is_pct_complete_not_100(_x):
                    return True
            return False
        return _is_pct_complete_not_100(v)

    try:
        warn_pct = bool(_row_has_pct_lt_100(r))
    except Exception:
        warn_pct = bool(_is_pct_complete_not_100(pct))
    pl = _fmt_date_ru(pdt)
    fl = _fmt_date_ru(fdt)
    if pd.isna(pdt) or pd.isna(fdt):
        return pl, fl, "Н/Д", False, warn_pct
    dev_days = _delta_days_plan_minus_fact(pdt, fdt)
    otk = _fmt_delta_days(dev_days)
    # План − Факт: ≥0 — факт не позже плана (в срок или раньше); <0 — просрочка.
    ok = bool(dev_days is not None and dev_days >= 0)
    return pl, fl, otk, ok, warn_pct


def _cp_hide_completed_candidates(sub: pd.DataFrame) -> pd.DataFrame:
    """Строки с % выполнения ≠ 100 или без процента; если пусто — исходный кадр (без потери вехи)."""
    if sub is None or getattr(sub, "empty", True) or "pct complete" not in sub.columns:
        return sub
    pc = pd.to_numeric(sub["pct complete"], errors="coerce")
    keep = (~pc.fillna(np.nan).eq(100.0)) | pc.isna()
    out = sub.loc[keep.fillna(False)]
    return out if not getattr(out, "empty", True) else sub


def _control_point_matching_row_indices(mdf: pd.DataFrame) -> set:
    """Индексы строк, попавших под любую встроенную/админскую веху «Контрольные точки»."""
    idx: set = set()
    if mdf is None or getattr(mdf, "empty", True):
        return idx
    for _t, _s, kw in get_control_point_milestones_effective():
        hit = _match_milestone_tasks(mdf, kw)
        if hit is not None and not hit.empty:
            idx.update(hit.index.tolist())
    return idx


def build_control_points_df(mdf: pd.DataFrame, *, hide_completed: bool = False) -> pd.DataFrame:
    """Одна строка на проект; столбцы project, row_ok, {slug}_plan|_fact|_otkl|_warn_pct."""
    pcol = _project_name_column(mdf)
    if pcol is None or mdf is None or mdf.empty:
        return pd.DataFrame()
    work = mdf.copy()
    raw_vals = work[pcol].dropna().astype(str).str.strip().unique().tolist()
    key_to_raws: Dict[str, List[str]] = defaultdict(list)
    for p in raw_vals:
        key_to_raws[_control_points_project_group_key(p)].append(str(p).strip())
    for gk in key_to_raws:
        key_to_raws[gk] = sorted(set(key_to_raws[gk]))

    rows_out: List[Dict[str, Any]] = []
    for gk, raws in sorted(
        key_to_raws.items(),
        key=lambda it: _control_points_project_label(it[0], it[1]).lower(),
    ):
        sub = work[work[pcol].astype(str).str.strip().isin(raws)]
        display = _control_points_project_label(gk, raws)
        rec: Dict[str, Any] = {"project": display, "row_ok": True}
        for title, slug, kw in get_control_point_milestones_effective():
            sub_m = _cp_hide_completed_candidates(sub) if hide_completed else sub
            m = _match_milestone_tasks(sub_m, kw)
            if hide_completed and (m is None or getattr(m, "empty", True)):
                m = _match_milestone_tasks(sub, kw)
            pl, fl, otk, ok, warn_pct = _one_milestone_cell(m)
            rec[f"{slug}_plan"] = pl
            rec[f"{slug}_fact"] = fl
            rec[f"{slug}_otkl"] = otk
            rec[f"{slug}_ok"] = ok
            rec[f"{slug}_warn_pct"] = bool(warn_pct)
            if not ok:
                rec["row_ok"] = False
        rows_out.append(rec)
    return pd.DataFrame(rows_out)


_CONTROL_POINTS_CSS = """
<style>
.cp-table-wrap { overflow-x: auto; min-width: 0; max-width: 100%; }
.cp-table-wrap .rendered-table th,
.cp-table-wrap .rendered-table td {
  border: 1px solid rgba(121, 154, 192, 0.55) !important;
}
.cp-table-wrap .rendered-table th {
  font-size: 12px !important;
  color: #eaf2fb !important;
  background: #17314b !important;
}
.cp-table-wrap .rendered-table td {
  font-size: 12px !important;
  color: #f3f7fc !important;
  line-height: 1.25;
}
.rendered-table th.cp-tophead {
  text-align: center;
  background: #17314b !important;
  color: #f5f9ff !important;
  font-size: 14px;
  font-weight: 800;
}
.rendered-table th.cp-ghead { text-align:center; background:#1f232d; font-size:13px; padding:7px 9px; color:#f5f9ff !important; }
.rendered-table th.cp-sub { font-size:12px; color:#dde8f5; font-weight:600; }
.cp-col-project {
  border-right: 2px solid rgba(190, 214, 242, 0.8) !important;
}
.cp-group-start {
  border-left: 2px solid rgba(190, 214, 242, 0.8) !important;
}
/* ТЗ «СРОКИ»: при % выполнения ≠ 100% — полужирный текст во всех вехах */
.cp-td-pct-bold {
  font-weight: 700 !important;
}
/* ГПЗУ / Экспертиза стадии П: дополнительно «рыжая» подсветка (согласованные правки) */
.cp-td-warn {
  background: rgba(234, 88, 12, 0.38) !important;
  color: #fff7ed !important;
  font-weight: 600;
}
.cp-td-warn.cp-td-pct-bold {
  font-weight: 700 !important;
}
/* Просрочка по План−Факт (отрицательные дни в «Откл.») — красный текст по макету ТЗ */
.cp-otkl-late {
  color: #f87171 !important;
  font-weight: 700 !important;
}
.cp-status-cell { text-align: center; vertical-align: middle; }
.cp-status-dot { display: inline-block; width: 14px; height: 14px; border-radius: 50%; vertical-align: middle; }
.cp-status-ok { background: #22c55e; box-shadow: 0 0 6px rgba(34,197,94,0.45); }
.cp-status-bad { background: #ef4444; box-shadow: 0 0 6px rgba(239,68,68,0.45); }
.cp-status-warn { background: #f59e0b; box-shadow: 0 0 7px rgba(245,158,11,0.7); }
</style>
"""


def _apply_control_points_msp_filters(
    st, mdf: pd.DataFrame
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Фильтр по проекту (ур.1): единственный фильтр на дашборде «Контрольные точки».
    Возвращает датафрейм для расчёта вех и метаданные (число строк после фильтра).
    """
    meta: Dict[str, Any] = {}
    if mdf is None or getattr(mdf, "empty", True):
        return pd.DataFrame(), meta
    df = mdf.copy()
    labels_map: Dict[str, List[str]] = {}
    if "project name" in df.columns:
        ordered, labels_map = _control_points_project_filter_options(df)
        preferred_projects = ["Дмитровский", "Есипово V", "Завод", "Ленинский"]
        if any(p in ordered for p in preferred_projects):
            ordered = [p for p in preferred_projects if p in ordered]
        opts = ["Все"] + ordered
        sel_proj = st.selectbox("Проект", opts, key="cp_msp_filter_project")
    else:
        sel_proj = "Все"

    out = df
    if sel_proj != "Все" and "project name" in out.columns:
        raws = labels_map.get(str(sel_proj).strip(), [str(sel_proj).strip()])
        out = out[out["project name"].astype(str).str.strip().isin(raws)]

    meta["subtree_rows"] = int(len(out))
    return out, meta


def render_control_points_dashboard(st, mdf: pd.DataFrame, table_css: str) -> None:
    """Таблица «Контрольные точки проектов»: фильтр по проекту, выгрузка CSV."""
    esc = html_module.escape
    if mdf is None or getattr(mdf, "empty", True):
        st.warning("Нет строк в данных MSP.")
        return

    filtered_mdf, _cp_filter_info = _apply_control_points_msp_filters(st, mdf)
    if filtered_mdf is None or getattr(filtered_mdf, "empty", True):
        st.info("Нет строк по выбранным фильтрам.")
        return

    df = build_control_points_df(filtered_mdf, hide_completed=False)
    if df.empty:
        st.warning("Нет строк проектов в данных MSP.")
        return
    view = df.copy()

    ms_specs = [(t, s) for t, s, _k in get_control_point_milestones_effective()]
    project_w = "min-width:180px"
    thead1 = [f'<th rowspan="2" class="cp-col-project" style="{project_w}">Проекты</th>']
    for i, (title, slug) in enumerate(ms_specs):
        hdr = title
        gcls = "cp-ghead cp-group-start" if i == 0 else "cp-ghead"
        thead1.append(f'<th colspan="4" class="{gcls}">{esc(hdr)}</th>')
    sub_headers: List[str] = []
    for i, (_title, slug) in enumerate(ms_specs):
        plan_title = "План"
        p_cls = "cp-sub cp-group-start" if i == 0 else "cp-sub"
        sub_headers.extend(
            [
                f'<th class="{p_cls}">{esc(plan_title)}</th>',
                f'<th class="cp-sub">{esc("Факт")}</th>',
                f'<th class="cp-sub">{esc("Откл.")}</th>',
                f'<th class="cp-sub">{esc("Статус")}</th>',
            ]
        )
    thead_html = (
        "<thead><tr>"
        + "".join(thead1)
        + "</tr><tr>"
        + "".join(sub_headers)
        + "</tr></thead>"
    )
    body: List[str] = ["<tbody>"]
    for _, r in view.iterrows():
        cells = [f'<td class="cp-col-project">{esc(str(r.get("project", "")))}</td>']
        for _t, slug in ms_specs:
            _is_orange_milestone = _is_orange_pct_milestone(slug, _t)
            pct_inc = bool(r.get(f"{slug}_warn_pct"))
            owarn = _is_orange_milestone and pct_inc
            m_ok = bool(r.get(f"{slug}_ok", False))
            # Оранжевая подсветка — только для ГПЗУ/Экспертизы и только если по датам норма.
            pct_warn_cells = owarn and m_ok
            otkl_txt = str(r.get(f"{slug}_otkl", "") or "")
            _od = _parse_otkl_days_display(otkl_txt)
            otk_late = _od is not None and _od < 0
            plan_parts = ["cp-group-start"]
            fact_parts: List[str] = []
            otkl_parts: List[str] = []
            if pct_inc:
                plan_parts.append("cp-td-pct-bold")
                fact_parts.append("cp-td-pct-bold")
                otkl_parts.append("cp-td-pct-bold")
            if pct_warn_cells:
                plan_parts.append("cp-td-warn")
                fact_parts.append("cp-td-warn")
                otkl_parts.append("cp-td-warn")
            if otk_late:
                otkl_parts.append("cp-otkl-late")
            wc_plan = ' class="' + " ".join(plan_parts) + '"'
            wc_fact = (' class="' + " ".join(fact_parts) + '"') if fact_parts else ""
            wc_otkl = (' class="' + " ".join(otkl_parts) + '"') if otkl_parts else ""
            cells.append(f"<td{wc_plan}>{esc(str(r.get(f'{slug}_plan', '')))}</td>")
            cells.append(
                f"<td{wc_fact}>{esc(str(r.get(f'{slug}_fact', '')))}</td>"
                if wc_fact
                else f"<td>{esc(str(r.get(f'{slug}_fact', '')))}</td>"
            )
            cells.append(
                f"<td{wc_otkl}>{esc(otkl_txt)}</td>"
                if wc_otkl
                else f"<td>{esc(otkl_txt)}</td>"
            )
            # Индикатор «Статус» — только соблюдение сроков (зелёный/красный). Незавершённые по %
            # подсвечиваются в ячейках План/Факт/Откл. (полужирный; для ГПЗУ/Экспертизы — фон).
            if not m_ok:
                st_cls = "cp-status-bad"
                tip = "Отклонение по срокам (факт позже плана) или неполные даты."
                al = "Отклонение по срокам"
            else:
                st_cls = "cp-status-ok"
                tip = (
                    "По срокам норма: факт не позже плана. Если в MSP «% выполнения» не 100%, "
                    "смотрите полужирный текст и оранжевую подсветку в ячейках (для ГПЗУ и Экспертизы стадии П)."
                )
                al = "Норма по срокам"
            st_extra = " cp-td-pct-bold" if pct_inc else ""
            cells.append(
                f'<td class="cp-status-cell{st_extra}" title="{esc(tip)}">'
                f'<span class="cp-status-dot {st_cls}" role="img" aria-label="{esc(al)}"></span></td>'
            )
        body.append("<tr>" + "".join(cells) + "</tr>")
    body.append("</tbody>")
    html_tbl = (
        '<table class="rendered-table" border="0">'
        + thead_html
        + "".join(body)
        + "</table>"
    )
    st.markdown(
        table_css + _CONTROL_POINTS_CSS + '<div class="rendered-table-wrap cp-table-wrap">' + html_tbl + "</div>",
        unsafe_allow_html=True,
    )
    drop_ok = [
        c
        for c in view.columns
        if str(c).endswith("_ok") or str(c).endswith("_warn_pct")
    ]
    export = view.drop(columns=drop_ok, errors="ignore")
    from utils import render_dataframe_excel_csv_downloads

    render_dataframe_excel_csv_downloads(
        export,
        file_stem="control_points",
        key_prefix="cp_msp_table",
        csv_label="Скачать таблицу (CSV, для Excel)",
    )
