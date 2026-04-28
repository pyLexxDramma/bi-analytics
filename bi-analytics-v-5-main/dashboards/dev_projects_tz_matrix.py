# -*- coding: utf-8 -*-
"""
Матрица «Девелоперские проекты» по ТЗ (правки): строки-показатели, колонки План / Факт / Откл.
Источники: MSP (canonical колонки после web_loader), project_data (БДДС), tessa_tasks_data.
"""
from __future__ import annotations

import html as html_module
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


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
    if d == 0:
        return "0 дн."
    sign = "+" if d > 0 else ""
    return f"{sign}{d} дн."


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
    if names_any:
        masks = []
        for needle in names_any:
            if needle:
                masks.append(out[nm].astype(str).str.contains(str(needle), **_lit))
        if masks:
            mm = masks[0]
            for x in masks[1:]:
                mm = mm | x
            out = out[mm]
    elif name_contains:
        out = out[out[nm].astype(str).str.contains(str(name_contains), **_lit)]
    return out


def _match_tasks_like_msp_row(mdf: pd.DataFrame, kw: dict) -> pd.DataFrame:
    """
    Те же шаги отбора задач MSP, что и для строки матрицы «Девелоперские проекты»
    (ослабление родителя ур.2, уровня, блока → «Фаза»).
    """
    if mdf is None or getattr(mdf, "empty", True):
        return mdf.iloc[0:0].copy()
    kw_m = {k: v for k, v in kw.items() if k not in ("phase_needles", "phase_exclude_needles")}
    phase_needles = kw.get("phase_needles")
    phase_exclude = kw.get("phase_exclude_needles")
    sub = _match_msp(
        mdf,
        level=kw_m.get("level"),
        name_contains=kw_m.get("name_contains"),
        names_any=kw_m.get("names_any"),
        parent_l2_contains=kw_m.get("parent_l2_contains"),
        block_contains=kw_m.get("block_contains"),
    )
    if sub.empty and kw_m.get("parent_l2_contains"):
        sub = _match_msp(
            mdf,
            level=kw_m.get("level"),
            name_contains=kw_m.get("name_contains"),
            names_any=kw_m.get("names_any"),
            parent_l2_contains=None,
            block_contains=kw_m.get("block_contains"),
        )
    if sub.empty and kw_m.get("level") is not None:
        sub = _match_msp(
            mdf,
            level=None,
            name_contains=kw_m.get("name_contains"),
            names_any=kw_m.get("names_any"),
            parent_l2_contains=None,
            block_contains=kw_m.get("block_contains"),
        )
    if sub.empty:
        sub = _match_msp(
            mdf,
            level=None,
            name_contains=kw_m.get("name_contains"),
            names_any=kw_m.get("names_any"),
            parent_l2_contains=None,
            block_contains=kw_m.get("block_contains"),
        )
    if sub.empty and kw_m.get("block_contains"):
        sub = _match_msp(
            mdf,
            level=None,
            name_contains=kw_m.get("name_contains"),
            names_any=kw_m.get("names_any"),
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


def dedupe_msp_for_developer_projects(df: pd.DataFrame) -> pd.DataFrame:
    """
    ТЗ: нет дублирования проектов и задач в «Девелоперские проекты».
    Сначала по идентификатору задачи MSP (если колонка есть и не пустая), иначе по (проект, задача) / по задаче.
    """
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()
    for id_c in (
        "unique id",
        "Уникальный_идентификатор",
        "task id seq",
        "Ид",
    ):
        if id_c not in out.columns:
            continue
        if int(out[id_c].notna().sum()) == 0:
            continue
        return out.drop_duplicates(subset=[id_c], keep="first").reset_index(drop=True)
    pc = _find_col(out, ["project name", "Проект", "Project", "проект", "ID_проекта"])
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

    # На всякий случай пересчитываем section из дерева (старые сессии/БД могли иметь ЛОТ вместо родителя ур.2)
    if mdf is not None and not getattr(mdf, "empty", True) and "task name" in mdf.columns:
        try:
            from web_loader import _fill_section_from_task_tree

            mdf = _fill_section_from_task_tree(mdf.copy())
        except Exception:
            pass
    if mdf is not None and not getattr(mdf, "empty", True):
        mdf = dedupe_msp_for_developer_projects(mdf)

    def add_row(
        group: str,
        label: str,
        plan_s: str,
        fact_s: str,
        otkl_s: str,
        warn: bool = False,
        *,
        phase: str = "",
    ) -> None:
        rows.append(
            {
                "group": group,
                "label": label,
                "plan": plan_s,
                "fact": fact_s,
                "otkl": otkl_s,
                "warn": warn,
                "phase": phase,
            }
        )

    pid = "Н/Д"
    pname = "Н/Д"
    if "project id" in mdf.columns and mdf["project id"].notna().any():
        pid = str(mdf["project id"].dropna().astype(str).iloc[0]).strip() or "Н/Д"
    if "project name" in mdf.columns and mdf["project name"].notna().any():
        pname = str(mdf["project name"].dropna().astype(str).iloc[0]).strip() or "Н/Д"
    # Если в выгрузке нет ID, но есть имя — в «План» показываем имя (чтобы не везде Н/Д)
    if pid == "Н/Д" and pname != "Н/Д":
        pid = pname
    add_row("Проект", "Проект", pid, pname, "—", False, phase="invest")

    def _msp_row(phase: str, group: str, label: str, kw: dict) -> None:
        sub = _match_tasks_like_msp_row(mdf, kw)
        if sub is None or sub.empty:
            add_row(group, label, "Н/Д", "Н/Д", "Н/Д", False, phase=phase)
            return
        # ТЗ: в каждой ячейке План/Факт/Откл. — одно значение (одна дата / один текст отклонения), без «дата1 / дата2».
        ps, fs, os, _ok, w = _one_milestone_cell(sub)
        add_row(group, label, ps, fs, os, bool(w), phase=phase)

    # Порядок столбцов — по референсу (file-002: вехи Ковенантов; file-003: ДС/ТЕССА до ИРД/ПОС)
    specs_invest_msp: List[Tuple[str, str, str, dict]] = [
        # По ТЗ: в реальной MSP — имя задачи + ур.5; во внутренних CSV вехи часто в колонке «Фаза» (см. phase_needles).
        (
            "invest",
            "ЗУ / Ковенанты",
            "Аренда ЗУ",
            {
                "level": 5.0,
                "name_contains": "Регистрация договора субаренды",
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
            "invest",
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
            "invest",
            "Ковенанты",
            "КОМАНДА РП",
            {
                "level": 5.0,
                "name_contains": "Подбор команды",
                "parent_l2_contains": "Ковенанты",
                "phase_needles": ["Команда РП", "КОМАНДА РП", "Подбор команды"],
            },
        ),
        (
            "invest",
            "Ковенанты",
            "РС",
            {
                "level": 5.0,
                "names_any": [
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
            "invest",
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
        _msp_row(phase, group, label, kw)

    pm, fm, om = _ds_plan_fact_otkl_mln(_bddds_df_for_dev_matrix(mdf, project_data, ss))
    if pm is None:
        add_row("Финансы", "Выборка ДС, млн руб.", "Н/Д", "Н/Д", "Н/Д", False, phase="invest")
    else:

        def _fmtml(v: float) -> str:
            # ТЗ: млн руб., два знака после запятой
            return f"{v:.2f}".replace(".", ",")

        add_row("Финансы", "Выборка ДС, млн руб.", _fmtml(pm), _fmtml(fm), _fmtml(om), False, phase="invest")

    tp, tf, to, warn_t, _tessa_hint = _predpisaniya_combined(mdf, ss)
    add_row("ТЕССА", "ПРЕДПИСАНИЯ", tp, tf, to, warn_t, phase="invest")

    specs_invest_tail: List[Tuple[str, str, str, dict]] = [
        (
            "invest",
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
            "invest",
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
            "invest",
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
            "invest",
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
            "invest",
            "Ковенанты",
            "Начало СМР",
            {
                "level": 5.0,
                "name_contains": "Начало СМР",
                "parent_l2_contains": "Ковенанты",
                "phase_needles": ["Начало СМР"],
            },
        ),
    ]
    for phase, group, label, kw in specs_invest_tail:
        _msp_row(phase, group, label, kw)

    specs_life: List[Tuple[str, str, str, dict]] = [
        (
            "life",
            "Ковенанты",
            "ТЕХ.ПРИСОЕДИНЕНИЯ (ГАЗ, ЭЛ-ВО)",
            {
                "level": 5.0,
                "names_any": [
                    "Пуск электричества",
                    "Пуск газа",
                    "ТЕХПРИСОЕДИНЕНИЯ",
                    "техприсоединения",
                    "ГАЗ, ЭП",
                    "ЭП, ВО",
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
                    "Пуск электричества",
                    "Пуск газа",
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
                    "БОНУСОВ",
                    "бонусов резидент",
                    "передача бонус",
                ],
                "parent_l2_contains": "Ковенанты",
                "phase_needles": [
                    "Передача боксов",
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
        _msp_row(phase, group, label, kw)

    cap = ""
    return rows, cap


_DEV_TZ_MATRIX_CSS = """
<style>
.dev-tz-matrix-wrap { overflow-x: auto; min-width: 0; max-width: 100%; margin-bottom: 0.75rem; }
.rendered-table.dev-tz-wide { border-collapse: collapse; min-width: 720px; }
.rendered-table.dev-tz-wide th.dev-tz-ghead {
  text-align: center; font-weight: 700; font-size: 13px; padding: 6px 8px;
  background: linear-gradient(180deg, rgba(34, 139, 34, 0.35) 0%, rgba(25, 90, 25, 0.25) 100%);
  color: #e8f5e9; border: 1px solid rgba(255,255,255,0.12);
}
.rendered-table.dev-tz-wide th.dev-tz-ghead-life {
  background: linear-gradient(180deg, rgba(34, 139, 34, 0.28) 0%, rgba(25, 90, 25, 0.18) 100%);
}
.rendered-table.dev-tz-wide th.dev-tz-milestone {
  text-align: center; vertical-align: bottom; font-size: 11px; font-weight: 600; line-height: 1.25;
  max-width: 9em; padding: 5px 6px; color: #c9d1d9; border: 1px solid rgba(255,255,255,0.08);
}
.rendered-table.dev-tz-wide th.dev-tz-sub {
  font-size: 11px; font-weight: 500; color: #9aa4b2; padding: 5px 6px;
  border: 1px solid rgba(255,255,255,0.06);
}
.rendered-table.dev-tz-wide td {
  font-size: 12px; padding: 5px 8px; text-align: center; vertical-align: middle;
  border: 1px solid rgba(255,255,255,0.06);
}
/* ТЗ: при «% выполнения» ≠ 100% — подсветка ячеек оранжевым */
.rendered-table.dev-tz-wide td.dev-tz-warn {
  background: rgba(255, 140, 0, 0.38) !important;
  color: #1a1a1a;
}
</style>
"""


def _dev_tz_matrix_row_key(r: Dict[str, Any]) -> Tuple[str, str]:
    """Стабильный ключ строки матрицы для сопоставления блоков разных проектов."""
    return (str(r.get("group") or ""), str(r.get("label") or ""))


def render_dev_tz_matrix(
    rows: Union[List[Dict[str, Any]], List[List[Dict[str, Any]]]],
    table_css: str,
) -> None:
    """
    Макет по референсу клиента: две группы столбцов «Инвестиционная фаза» / «Жизнь проекта»,
    под каждой вехой — План / Факт / Откл.

    - Один проект: ``rows`` — плоский список словарей (как раньше) — одна строка данных в таблице.
    - Несколько проектов: ``rows`` — список списков словарей (по одному списку на проект, тот же порядок
      вех, что у первого проекта) — в tbody по одной строке на проект.
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

    template = blocks[0]
    esc = html_module.escape
    invest_labels = [r["label"] for r in template if r.get("phase") == "invest"]
    life_labels = [r["label"] for r in template if r.get("phase") == "life"]
    n_inv = max(1, len(invest_labels))
    n_life = max(0, len(life_labels))
    col_span_inv = n_inv * 3
    col_span_life = n_life * 3

    head_rows: List[str] = [
        "<tr>"
        f'<th colspan="{col_span_inv}" class="dev-tz-ghead">Инвестиционная фаза</th>'
        f'<th colspan="{col_span_life}" class="dev-tz-ghead dev-tz-ghead-life">Жизнь проекта</th>'
        "</tr>"
    ]
    mline: List[str] = []
    subline: List[str] = []
    for r in template:
        lab = r.get("label") or ""
        mline.append(f'<th colspan="3" class="dev-tz-milestone" title="{esc(str(lab))}">{esc(str(lab))}</th>')
        subline.extend(
            [
                '<th class="dev-tz-sub">План</th>',
                '<th class="dev-tz-sub">Факт</th>',
                '<th class="dev-tz-sub">Откл.</th>',
            ]
        )
    head_rows.append("<tr>" + "".join(mline) + "</tr>")
    head_rows.append("<tr>" + "".join(subline) + "</tr>")
    thead = "<thead>" + "".join(head_rows) + "</thead>"

    body_trs: List[str] = []
    tmpl_keys: List[Tuple[str, str]] = [_dev_tz_matrix_row_key(r) for r in template]
    for block in blocks:
        row_by_key = {_dev_tz_matrix_row_key(r): r for r in block}
        body_cells: List[str] = []
        for k in tmpl_keys:
            r = row_by_key.get(k)
            if r is None:
                for _ in ("plan", "fact", "otkl"):
                    body_cells.append("<td>Н/Д</td>")
                continue
            warn_row = bool(r.get("warn"))
            for key in ("plan", "fact", "otkl"):
                v = r.get(key) or ""
                oc = ' class="dev-tz-warn"' if warn_row else ""
                body_cells.append(f"<td{oc}>{esc(str(v))}</td>")
        body_trs.append("<tr>" + "".join(body_cells) + "</tr>")

    html_tbl = (
        '<table class="rendered-table dev-tz-wide" border="0">'
        + thead
        + "<tbody>"
        + "".join(body_trs)
        + "</tbody></table>"
    )
    st.markdown(
        table_css + _DEV_TZ_MATRIX_CSS + '<div class="dev-tz-matrix-wrap">' + html_tbl + "</div>",
        unsafe_allow_html=True,
    )


# ── Контрольные точки (Сроки / макет file-009): проекты × вехи ───────────────

# Вехи «Контрольные точки»: оранжевая подсветка План/Факт/Откл. при % выполнения ≠ 100% (ТЗ, правки 1).
CONTROL_POINTS_ORANGE_PCT_SLUGS: frozenset = frozenset({"gpzu", "exp_pd"})


def _is_orange_pct_milestone(slug: str, title: str) -> bool:
    """Определить, что веха относится к ГПЗУ/Экспертизе стадии П (в т.ч. при кастомном slug)."""
    s_slug = str(slug or "").strip().lower()
    if s_slug in CONTROL_POINTS_ORANGE_PCT_SLUGS:
        return True
    s_title = str(title or "").strip().lower().replace("ё", "е")
    return ("гпзу" in s_title) or ("экспертиз" in s_title)

# Контрольные точки: список и правила сопоставления по согласованному ТЗ.
CONTROL_POINT_MILESTONES: List[Tuple[str, str, dict]] = [
    ("ГПЗУ", "gpzu", {"level": 5.0, "names_any": ["ГПЗУ"], "parent_l2_contains": "Ковенанты"}),
    ("Экспертиза стадии П", "exp_pd", {"level": 5.0, "names_any": ["Экспертиза ПД", "Экспертиза"], "parent_l2_contains": "Ковенанты"}),
    ("Начало финансирования", "fin_start", {"level": 5.0, "names_any": ["КОД, ОТКР. ФИНАНС. (начало финансирования)", "Начало финансирования"], "parent_l2_contains": "Ковенанты"}),
    ("Стадия РД", "rd_stage", {"level": 5.0, "names_any": ["Стадия РД", "Стадия Рабочая Документация (РД)", "Рабочая Документация (РД)"], "parent_l2_contains": "Ковенанты"}),
    ("РС", "rs", {"level": 5.0, "names_any": ["Разрешение РС", "Разрешение на строительство (РС)", "Разрешение на строительство"], "parent_l2_contains": "Ковенанты"}),
    ("Завершение СМР", "smr_finish", {"level": 5.0, "names_any": ["Завершение СМР"], "parent_l2_contains": "Ковенанты"}),
    ("Пуск электричества", "power_on", {"level": 5.0, "names_any": ["Пуск электричества"], "parent_l2_contains": "Ковенанты"}),
    ("Пуск газа", "gas_on", {"level": 5.0, "names_any": ["Пуск газа"], "parent_l2_contains": "Ковенанты"}),
    ("РВ", "rv", {"level": 5.0, "names_any": ["РВ", "Разрешение на ввод в эксплуатацию (РВ)", "Разрешение на ввод"], "parent_l2_contains": "Ковенанты"}),
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
    Пятый элемент — подсветка по % выполнения (не 100% при известном %).
    """
    if rows is None or rows.empty:
        return "Н/Д", "Н/Д", "Н/Д", False, False
    tc = _task_name_col(rows)
    if tc and tc in rows.columns:
        r = rows.sort_values(by=tc).iloc[0]
    else:
        r = rows.iloc[0]
    pdt, fdt, pct = _msp_plan_fact_pct(r)
    # Для оранжевого статуса достаточно, чтобы в любой строке вехи % был задан и < 100.
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

    warn_pct = False
    try:
        for _, _rr in rows.iterrows():
            if _row_has_pct_lt_100(_rr):
                warn_pct = True
                break
    except Exception:
        warn_pct = _is_pct_complete_not_100(pct)
    pl = _fmt_date_ru(pdt)
    fl = _fmt_date_ru(fdt)
    if pd.isna(pdt) or pd.isna(fdt):
        return pl, fl, "Н/Д", False, warn_pct
    dev_days = _delta_days_plan_minus_fact(pdt, fdt)
    otk = _fmt_delta_days(dev_days)
    ok = bool(dev_days == 0) if dev_days is not None else False
    return pl, fl, otk, ok, warn_pct


def build_control_points_df(mdf: pd.DataFrame) -> pd.DataFrame:
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
  border-color: rgba(121, 154, 192, 0.55) !important;
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
.rendered-table th.cp-ghead { text-align:center; background:#1f232d; font-size:13px; padding:7px 9px; color:#f5f9ff !important; }
.rendered-table th.cp-sub { font-size:12px; color:#dde8f5; font-weight:600; }
/* ГПЗУ / Экспертиза стадии П: % выполнения в MSP ≠ 100% — «рыжая» подсветка значения */
.cp-td-warn {
  background: rgba(234, 88, 12, 0.38) !important;
  color: #fff7ed !important;
  font-weight: 600;
}
.cp-status-cell { text-align: center; vertical-align: middle; }
.cp-status-dot { display: inline-block; width: 14px; height: 14px; border-radius: 50%; vertical-align: middle; }
.cp-status-ok { background: #22c55e; box-shadow: 0 0 6px rgba(34,197,94,0.45); }
.cp-status-bad { background: #ef4444; box-shadow: 0 0 6px rgba(239,68,68,0.45); }
.cp-status-warn { background: #f59e0b; box-shadow: 0 0 7px rgba(245,158,11,0.7); }
</style>
"""


def _apply_control_points_msp_filters(st, mdf: pd.DataFrame) -> pd.DataFrame:
    """
    Фильтры по ТЗ:
    - Проект (ур.1)
    - Функциональный блок (ур.2)
    - Строения (ур.3)
    - Верхний уровень задач (ур.4)
    - Детальный уровень задач (ур.5)
    """
    if mdf is None or getattr(mdf, "empty", True):
        return mdf
    df = mdf.copy()

    def _clean_filter_label(v: Any) -> str:
        s = str(v or "").replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "").strip()
        while "  " in s:
            s = s.replace("  ", " ")
        # Убираем кавычки в отображаемом label (в т.ч. внутренние), чтобы списки фильтров были читаемыми.
        s = (
            s.replace('"', "")
            .replace("'", "")
            .replace("«", "")
            .replace("»", "")
        )
        # Чистим типовые артефакты выгрузки MSP в названиях.
        s = s.replace(" ,", ",").replace(" .", ".")
        s = s.lstrip("*- ").strip()
        while "  " in s:
            s = s.replace("  ", " ")
        s = s.strip()
        return s

    def _build_options_map(series: pd.Series) -> Dict[str, List[str]]:
        mp: Dict[str, List[str]] = {}
        if series is None or getattr(series, "empty", True):
            return mp
        for raw in series.dropna().astype(str).tolist():
            rs = str(raw).strip()
            if not rs:
                continue
            lab = _clean_filter_label(rs)
            if not lab:
                continue
            mp.setdefault(lab, []).append(rs)
        for k in list(mp.keys()):
            # Дедуп исходников для выбранной подписи.
            mp[k] = sorted(set(mp[k]))
        return mp
    lvl_col = "level structure" if "level structure" in df.columns else ("level" if "level" in df.columns else None)
    task_col = _task_name_col(df)
    if lvl_col and task_col and lvl_col in df.columns and task_col in df.columns:
        # Восстанавливаем предков по порядку строк MSP.
        anc2: List[str] = []
        anc3: List[str] = []
        anc4: List[str] = []
        anc5: List[str] = []
        stack: Dict[int, str] = {}
        pcol = "project name" if "project name" in df.columns else None
        if pcol:
            grouped = df.groupby(df[pcol].astype(str), sort=False)
            parts = []
            for _, g in grouped:
                g = g.copy()
                stack = {}
                _a2: List[str] = []
                _a3: List[str] = []
                _a4: List[str] = []
                _a5: List[str] = []
                for _, r in g.iterrows():
                    lv = pd.to_numeric(r.get(lvl_col), errors="coerce")
                    try:
                        lvi = int(lv)
                    except Exception:
                        lvi = -1
                    if lvi > 0:
                        for k in list(stack.keys()):
                            if k >= lvi:
                                del stack[k]
                    name = str(r.get(task_col) or "").strip()
                    if lvi == 2:
                        v2, v3, v4, v5 = name, "", "", ""
                    elif lvi == 3:
                        v2, v3, v4, v5 = stack.get(2, ""), name, "", ""
                    elif lvi == 4:
                        v2, v3, v4, v5 = stack.get(2, ""), stack.get(3, ""), name, ""
                    elif lvi == 5:
                        v2, v3, v4, v5 = stack.get(2, ""), stack.get(3, ""), stack.get(4, ""), name
                    else:
                        v2, v3, v4, v5 = stack.get(2, ""), stack.get(3, ""), stack.get(4, ""), stack.get(5, "")
                    _a2.append(v2)
                    _a3.append(v3)
                    _a4.append(v4)
                    _a5.append(v5)
                    if lvi > 0 and name:
                        stack[lvi] = name
                g["__l2"] = _a2
                g["__l3"] = _a3
                g["__l4"] = _a4
                g["__l5"] = _a5
                parts.append(g)
            if parts:
                df = pd.concat(parts, axis=0)
        else:
            for _, r in df.iterrows():
                lv = pd.to_numeric(r.get(lvl_col), errors="coerce")
                try:
                    lvi = int(lv)
                except Exception:
                    lvi = -1
                if lvi > 0:
                    for k in list(stack.keys()):
                        if k >= lvi:
                            del stack[k]
                name = str(r.get(task_col) or "").strip()
                if lvi == 2:
                    v2, v3, v4, v5 = name, "", "", ""
                elif lvi == 3:
                    v2, v3, v4, v5 = stack.get(2, ""), name, "", ""
                elif lvi == 4:
                    v2, v3, v4, v5 = stack.get(2, ""), stack.get(3, ""), name, ""
                elif lvi == 5:
                    v2, v3, v4, v5 = stack.get(2, ""), stack.get(3, ""), stack.get(4, ""), name
                else:
                    v2, v3, v4, v5 = stack.get(2, ""), stack.get(3, ""), stack.get(4, ""), stack.get(5, "")
                anc2.append(v2)
                anc3.append(v3)
                anc4.append(v4)
                anc5.append(v5)
                if lvi > 0 and name:
                    stack[lvi] = name
            df["__l2"] = anc2
            df["__l3"] = anc3
            df["__l4"] = anc4
            df["__l5"] = anc5

    r1a, r1b, r1c = st.columns(3)
    r2a, r2b = st.columns(2)
    labels_map: Dict[str, List[str]] = {}
    with r1a:
        if "project name" in df.columns:
            ordered, labels_map = _control_points_project_filter_options(df)
            opts = ["Все"] + ordered
            sel_proj = st.selectbox("Проект", opts, key="cp_msp_filter_project")
        else:
            sel_proj = "Все"

    # Каскад: каждый следующий список строим из уже отфильтрованного набора.
    out = df
    if sel_proj != "Все" and "project name" in out.columns:
        raws = labels_map.get(str(sel_proj).strip(), [str(sel_proj).strip()])
        out = out[out["project name"].astype(str).str.strip().isin(raws)]

    with r1b:
        l2_map = _build_options_map(out.get("__l2", pd.Series(dtype=str)))
        l2_opts = ["Все"] + sorted(l2_map.keys(), key=lambda x: x.lower())
        sel_l2 = st.selectbox("Функциональный блок", l2_opts, key="cp_msp_filter_l2")
    if sel_l2 != "Все" and "__l2" in out.columns:
        raws = l2_map.get(str(sel_l2).strip(), [str(sel_l2).strip()])
        out = out[out["__l2"].astype(str).str.strip().isin(raws)]

    with r1c:
        l3_map = _build_options_map(out.get("__l3", pd.Series(dtype=str)))
        l3_opts = ["Все"] + sorted(l3_map.keys(), key=lambda x: x.lower())
        sel_l3 = st.selectbox("Строения", l3_opts, key="cp_msp_filter_l3")
    if sel_l3 != "Все" and "__l3" in out.columns:
        raws = l3_map.get(str(sel_l3).strip(), [str(sel_l3).strip()])
        out = out[out["__l3"].astype(str).str.strip().isin(raws)]

    # Для уровней 4/5 показываем только релевантные варианты:
    # строки, которые потенциально попадают в вехи «Контрольных точек» по текущему ТЗ.
    rel = out
    try:
        rel_idx = set()
        for _title, _slug, _kw in get_control_point_milestones_effective():
            _m = _match_milestone_tasks(out, _kw)
            if _m is not None and not getattr(_m, "empty", True):
                rel_idx.update(_m.index.tolist())
        if rel_idx:
            rel = out.loc[sorted(rel_idx)]
    except Exception:
        rel = out

    with r2a:
        l4_map = _build_options_map(out.get("__l4", pd.Series(dtype=str)))
        if "__l4" in rel.columns:
            _rel_l4 = set(_build_options_map(rel["__l4"]).keys())
            if _rel_l4:
                l4_map = {k: v for k, v in l4_map.items() if k in _rel_l4}
        l4_opts = ["Все"] + sorted(l4_map.keys(), key=lambda x: x.lower())
        sel_l4 = st.selectbox("Верхний уровень задач", l4_opts, key="cp_msp_filter_l4")
    if sel_l4 != "Все" and "__l4" in out.columns:
        raws = l4_map.get(str(sel_l4).strip(), [str(sel_l4).strip()])
        out = out[out["__l4"].astype(str).str.strip().isin(raws)]

    with r2b:
        l5_map = _build_options_map(out.get("__l5", pd.Series(dtype=str)))
        if "__l5" in rel.columns:
            _rel_l5 = set(_build_options_map(rel["__l5"]).keys())
            if _rel_l5:
                l5_map = {k: v for k, v in l5_map.items() if k in _rel_l5}
        l5_opts = ["Все"] + sorted(l5_map.keys(), key=lambda x: x.lower())
        sel_l5 = st.selectbox("Детальный уровень задач", l5_opts, key="cp_msp_filter_l5")
    if sel_l5 != "Все" and "__l5" in out.columns:
        raws = l5_map.get(str(sel_l5).strip(), [str(sel_l5).strip()])
        out = out[out["__l5"].astype(str).str.strip().isin(raws)]
    out = out.drop(columns=["__l2", "__l3", "__l4", "__l5"], errors="ignore")
    return out


def render_control_points_dashboard(st, mdf: pd.DataFrame, table_css: str) -> None:
    """Таблица «Контрольные точки проектов» + фильтры MSP + выгрузка CSV."""
    esc = html_module.escape
    if mdf is None or getattr(mdf, "empty", True):
        st.warning("Нет строк в данных MSP.")
        return
    filtered_mdf = _apply_control_points_msp_filters(st, mdf)
    if filtered_mdf is None or getattr(filtered_mdf, "empty", True):
        st.info("Нет строк по выбранным фильтрам.")
        return
    df = build_control_points_df(filtered_mdf)
    if df.empty:
        st.warning("Нет строк проектов в данных MSP.")
        return
    view = df.copy()

    ms_specs = [(t, s) for t, s, _k in get_control_point_milestones_effective()]
    thead1 = ['<th rowspan="2" style="min-width:180px">Проект</th>']
    for title, slug in ms_specs:
        thead1.append(f'<th colspan="4" class="cp-ghead">{esc(title)}</th>')
    sub_headers: List[str] = []
    for _title, slug in ms_specs:
        sub_headers.extend(
            [
                f'<th class="cp-sub">{esc("План")}</th>',
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
        cells = [f'<td>{esc(str(r.get("project", "")))}</td>']
        for _t, slug in ms_specs:
            _is_orange_milestone = _is_orange_pct_milestone(slug, _t)
            owarn = _is_orange_milestone and bool(r.get(f"{slug}_warn_pct"))
            wc = ' class="cp-td-warn"' if owarn else ""
            cells.append(f"<td{wc}>{esc(str(r.get(f'{slug}_plan', '')))}</td>")
            cells.append(f"<td{wc}>{esc(str(r.get(f'{slug}_fact', '')))}</td>")
            cells.append(f"<td{wc}>{esc(str(r.get(f'{slug}_otkl', '')))}</td>")
            m_ok = bool(r.get(f"{slug}_ok", False))
            # A1: для ГПЗУ/Экспертизы стадии П при % < 100 статус должен быть оранжевым.
            if owarn:
                st_cls = "cp-status-warn"
                tip = "В MSP для задачи «% выполнения» указано не 100% (вехи ГПЗУ / Экспертиза стадии П)"
                al = "Незавершено по %"
            elif not m_ok:
                st_cls = "cp-status-bad"
                tip = "Отклонение по датам (План/Факт) или неполные даты"
                al = "Отклонение по датам"
            else:
                st_cls = "cp-status-ok"
                tip = "План и факт по датам совпадают (0 дн.), % выполнения — 100% или н/д"
                al = "Норма"
            cells.append(
                f'<td class="cp-status-cell" title="{esc(tip)}">'
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
