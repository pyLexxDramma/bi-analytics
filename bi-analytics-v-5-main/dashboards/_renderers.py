"""
Отрисовка дашбордов. Код перенесён из project_visualization_app.py для уменьшения главного файла.
"""
import streamlit as st
import pandas as pd
from typing import Optional
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
import numpy as np
import re
import textwrap
import html as html_module
from urllib.parse import urlencode

from config import MSP_PROJECT_FILTER_EXCLUDE_NAMES, RUSSIAN_MONTHS

from dashboards.dev_projects_tz_matrix import (
    build_dev_tz_matrix_rows,
    render_dev_tz_matrix,
    render_control_points_dashboard,
    _control_points_prepare_msp_dates,
)


def _project_name_select_options(series: pd.Series) -> list:
    """Уникальные значения project name для фильтров; без меток из MSP_PROJECT_FILTER_EXCLUDE_NAMES."""
    return _unique_project_labels_for_select(series)


# Суффикс этапа «V» / «V» как римская цифра и «-5» как арабская — один проект
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


def _project_name_fusion_base(s: str) -> str:
    """
    Приводит хвост названия к виду «… 5»: «Есипово V» и «Есипово-5» → «Есипово 5».
    """
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
        head = m_num.group(1).strip()
        n = int(m_num.group(2))
        return f"{head} {n}"
    m_rom = re.fullmatch(r"(.+?)\s+([IVX]{1,4})\s*", t, flags=re.I)
    if m_rom:
        head = m_rom.group(1).strip()
        rom = m_rom.group(2).upper()
        n = _ROMAN_PROJECT_TAIL.get(rom)
        if n is not None:
            return f"{head} {n}"
    return t


def _project_filter_norm_key(val) -> str:
    """Ключ для сравнения названий проекта (скрытые дубли в фильтре, совпадение с выбором)."""
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
    sl = s.casefold()
    if sl in ("", "nan", "none", "nat"):
        return ""
    return sl


def _project_canonical_display_map(series: pd.Series) -> dict[str, str]:
    """
    Для каждого «сырого» варианта названия проекта — одна подпись для таблиц/группировок
    (короче имя — приоритет внутри ключа нормализации).
    """
    if series is None or getattr(series, "empty", True):
        return {}
    buckets: dict[str, list[str]] = {}
    for raw in series.dropna().unique():
        s = str(raw).strip()
        if not s or s.lower() in ("nan", "none"):
            continue
        fk = _project_filter_norm_key(s)
        if not fk:
            continue
        buckets.setdefault(fk, []).append(s)
    out: dict[str, str] = {}
    for _fk, variants in buckets.items():
        best = min(variants, key=lambda x: (len(x), x.casefold()))
        for v in variants:
            out[v] = best
    return out


def _project_column_apply_canonical(df: pd.DataFrame, col: str | None) -> pd.DataFrame:
    """Подменяет значения колонки проекта на канонические подписи в копии датафрейма."""
    if not col or col not in df.columns:
        return df
    mp = _project_canonical_display_map(df[col])
    if not mp:
        return df
    out = df.copy()

    def _cell(z):
        if z is None or (isinstance(z, float) and pd.isna(z)):
            return z
        s = str(z).strip()
        return mp.get(s, z)

    out[col] = out[col].map(_cell)
    return out


def _unique_project_labels_for_select(series: pd.Series) -> list[str]:
    """Уникальные подписи для selectbox: один пункт на один нормализованный ключ (короче имя — приоритет)."""
    if series is None or getattr(series, "empty", True):
        return []
    excluded_keys = {
        _project_filter_norm_key(p)
        for p in MSP_PROJECT_FILTER_EXCLUDE_NAMES
        if _project_filter_norm_key(p)
    }
    by_key: dict[str, str] = {}
    for raw in series.dropna().unique():
        s = (
            str(raw)
            .replace("\xa0", " ")
            .replace("\u200b", "")
            .replace("\ufeff", "")
            .strip()
        )
        while "  " in s:
            s = s.replace("  ", " ")
        k = _project_filter_norm_key(s)
        if not k or k in excluded_keys:
            continue
        if k not in by_key or len(s) < len(by_key[k]):
            by_key[k] = s
    return sorted(by_key.values(), key=lambda x: x.casefold())


def _session_reset_project_if_excluded(state_key: str) -> None:
    """Если в session_state сохранён исключённый проект — сброс на «Все»."""
    try:
        if state_key in st.session_state and st.session_state[state_key] in MSP_PROJECT_FILTER_EXCLUDE_NAMES:
            st.session_state[state_key] = "Все"
    except Exception:
        pass


_TABLE_CSS = """
<style>
.rendered-table-wrap {overflow-x:auto; margin:0.5rem 0 1rem 0}
.rendered-table {
  width:100%; border-collapse:collapse; font-size:13px;
  font-family:Inter,system-ui,sans-serif;
}
.rendered-table th {
  position:sticky; top:0; background:#1a1c23; color:#fafafa;
  padding:8px 12px; text-align:left; border-bottom:2px solid #444;
  font-weight:600; white-space:nowrap;
}
.rendered-table td {
  padding:6px 12px; border-bottom:1px solid #333; color:#e0e0e0;
  white-space:nowrap; max-width:400px; overflow:hidden; text-overflow:ellipsis;
}
.rendered-table tr:hover td {background:#262833}
.rendered-table tr:nth-child(even) td {background:rgba(255,255,255,0.02)}
.rendered-table th.col-baseline, .rendered-table td.col-baseline { background:rgba(46,134,171,0.12); }
.rendered-table th.col-fact, .rendered-table td.col-fact { background:rgba(255,99,71,0.10); }
.rendered-table th.col-dev, .rendered-table td.col-dev { background:rgba(241,196,15,0.08); }
</style>
"""

def _render_html_table(
    df,
    max_rows=500,
    column_tooltips=None,
    *,
    cell_titles: bool = False,
    column_role: dict = None,
):
    """Render a DataFrame as a styled HTML table (bypasses broken st.dataframe canvas).

    column_tooltips: optional dict column_name -> tooltip for <th title="..."> (full header text on hover).
    cell_titles: если True — у ячеек td задаётся title «Колонка: значение» для подсказки.
    column_role: опционально имя колонки -> 'baseline' | 'fact' | 'dev' | None (класс col-* для раскраски).
    """
    show = df.head(max_rows).copy()
    for col in show.columns:
        show[col] = [str(v) if pd.notna(v) else "" for v in show[col]]
    _role = column_role or {}

    def _th_class(c):
        r = _role.get(c) or _role.get(str(c))
        if r == "baseline":
            return " col-baseline"
        if r == "fact":
            return " col-fact"
        if r == "dev":
            return " col-dev"
        return ""

    if column_tooltips is not None or column_role is not None or cell_titles:
        parts = [
            '<div class="rendered-table-wrap">',
            '<table class="rendered-table" style="border-collapse:collapse;width:100%">',
            "<thead><tr>",
        ]
        for c in show.columns:
            esc_c = html_module.escape(str(c))
            tip = (column_tooltips or {}).get(c) or (column_tooltips or {}).get(str(c))
            cls = _th_class(c)
            if tip:
                esc_tip = html_module.escape(str(tip), quote=True)
                parts.append(f'<th class="{cls.strip()}" title="{esc_tip}">{esc_c}</th>')
            else:
                parts.append(f'<th class="{cls.strip()}">{esc_c}</th>')
        parts.append("</tr></thead><tbody>")
        for i in range(len(show)):
            row = show.iloc[i]
            parts.append("<tr>")
            for c in show.columns:
                cell = row[c]
                esc = html_module.escape(str(cell)) if str(cell).strip() != "" else ""
                cls = _th_class(c)
                if cell_titles and esc:
                    ct = html_module.escape(f"{c}: {cell}", quote=True)
                    parts.append(f'<td class="{cls.strip()}" title="{ct}">{esc}</td>')
                else:
                    parts.append(f'<td class="{cls.strip()}">{esc}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table></div>")
        st.markdown(_TABLE_CSS + "".join(parts), unsafe_allow_html=True)
    else:
        html = show.to_html(index=False, classes="rendered-table", escape=True, border=0)
        st.markdown(_TABLE_CSS + '<div class="rendered-table-wrap">' + html + "</div>",
                    unsafe_allow_html=True)
    if len(df) > max_rows:
        with st.expander("Ограничение отображения таблицы", expanded=False):
            st.caption(
                f"Показано {max_rows} из {len(df)} записей. Скачайте CSV или Excel для полных данных."
            )


def _parse_gantt_dev_days_display(v):
    """Число дней из строки вида «+5 дн.» / «0 дн.» для подсветки таблицы графика проекта."""
    if v is None:
        return None
    try:
        if isinstance(v, float) and pd.isna(v):
            return None
    except Exception:
        pass
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    s = re.sub(r"дн\.?", "", s, flags=re.I).strip()
    m = re.search(r"([+-]?)\s*(\d+)", s)
    if not m:
        return None
    val = int(m.group(2))
    sg = m.group(1) or ""
    if sg == "-":
        return -val
    if sg == "+":
        return val
    return val


def _gantt_deviation_cell_style(v) -> str:
    n = _parse_gantt_dev_days_display(v)
    base = f"background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR}"
    if n is None or n == 0:
        return base
    if n > 0:
        return "background-color: #c0392b; color: #ffffff"
    return "background-color: #27ae60; color: #ffffff"


def _render_gantt_schedule_html_table(df: pd.DataFrame, max_rows: int = 80):
    """Таблица под графиком проекта: тёмная тема и подсветка «Отклонение Начала/Окончания» по дням (как в блоке отклонений)."""
    show = df.head(max_rows).copy()
    for col in show.columns:
        show[col] = [str(v) if pd.notna(v) else "" for v in show[col]]
    dev_names = [c for c in ("Отклонение Начала", "Отклонение Окончания") if c in show.columns]
    sty = show.style.set_properties(
        **{"background-color": TABLE_BG_COLOR, "color": TABLE_TEXT_COLOR, "font-size": "13px"}
    ).set_table_styles(
        [
            {
                "selector": "th",
                "props": [
                    ("background-color", TABLE_BG_COLOR),
                    ("color", TABLE_TEXT_COLOR),
                    ("font-weight", "600"),
                    ("border-bottom", "2px solid #444"),
                    ("padding", "8px 12px"),
                    ("text-align", "left"),
                ],
            },
            {"selector": "td", "props": [("border-bottom", "1px solid #333"), ("padding", "6px 12px")]},
        ]
    )
    if dev_names:
        sty = sty.apply(
            lambda s: s.map(_gantt_deviation_cell_style),
            subset=dev_names,
            axis=0,
        )
    html = sty.to_html(index=False, classes="rendered-table", escape=True, border=0)
    st.markdown(_TABLE_CSS + '<div class="rendered-table-wrap">' + html + "</div>", unsafe_allow_html=True)
    if len(df) > max_rows:
        with st.expander("Ограничение отображения таблицы", expanded=False):
            st.caption(
                f"Показано {max_rows} из {len(df)} записей. Скачайте CSV или Excel для полных данных."
            )


from utils import (
    TABLE_BG_COLOR,
    TABLE_TEXT_COLOR,
    get_russian_month_name,
    format_period_ru,
    apply_chart_background,
    get_report_param_value,
    apply_default_filters,
    ensure_budget_columns,
    ensure_date_columns,
    ensure_msp_hierarchy_columns,
    outline_level_numeric,
    style_dataframe_for_dark_theme,
    plan_fact_dates_table_to_html,
    render_styled_table_to_html,
    budget_table_to_html,
    format_million_rub,
    to_million_rub,
    format_dataframe_as_html,
    norm_partner_join_key,
    render_dataframe_excel_csv_downloads,
    dataframe_to_csv_bytes_for_excel,
    dataframe_to_xlsx_bytes,
)

# Максимальное число строк, передаваемых в Plotly для scatter/line-графиков.
# Для агрегированных (bar, pie) ограничение не нужно — там строк обычно немного.
_MAX_CHART_ROWS = 5_000

_dev_outline_level_numeric = outline_level_numeric


def _dev_tasks_find_column(df, possible_names):
    """Поиск колонки по списку имён (без учёта регистра, с частичным совпадением)."""
    if df is None or not hasattr(df, "columns"):
        return None
    for col in df.columns:
        col_normalized = str(col).replace("\n", " ").replace("\r", " ").strip()
        col_lower = col_normalized.lower()
        for name in possible_names:
            name_lower = name.lower().strip()
            if name_lower == col_lower:
                return col
            if name_lower in col_lower or col_lower in name_lower:
                return col
            name_words = [w for w in name_lower.split() if len(w) > 2]
            if name_words and all(word in col_lower for word in name_words):
                return col
    return None


def _dev_tasks_resolve_level_column(d: pd.DataFrame):
    """Колонка числового уровня иерархии MSP (Outline / level structure / Уровень)."""
    if d is None or getattr(d, "empty", True):
        return None
    candidates: list = []
    seen = set()

    def _add(col) -> None:
        if col is None or col not in d.columns:
            return
        key = str(col).strip().lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(col)

    for c in d.columns:
        if str(c).strip().lower() == "level structure":
            _add(c)
    for name in (
        "level",
        "outline level",
        "outline_level",
        "wbs level",
        "wbs_level",
        "исходный уровень",
        "исходный_уровень",
    ):
        cols_lower = {str(x).strip().lower(): x for x in d.columns}
        if name in cols_lower:
            _add(cols_lower[name])
    for c in d.columns:
        sl = str(c).strip().lower()
        if "outline" in sl and "level" in sl.replace(" ", "") and "number" not in sl:
            _add(c)
        if "wbs" in sl and "level" in sl.replace(" ", "") and "number" not in sl:
            _add(c)
        if "уровень" in sl and "приоритет" not in sl and "риск" not in sl:
            _add(c)

    for c in candidates:
        coerced = _dev_outline_level_numeric(d[c])
        if coerced.notna().any():
            return c
    return None


def _deviations_msp_tier_levels(ln: pd.Series) -> tuple[int, int]:
    """
    Уровни MSP для фильтров «функциональный блок» и «строение».
    Если в данных есть классические 2 и 3 — используем их; иначе — вторая и третья
    уникальные величины уровня (экспорты, где нумерация начинается не с 2).
    """
    s = _dev_outline_level_numeric(ln).dropna()
    us: list[int] = []
    for x in s:
        try:
            v = int(round(float(x)))
        except (TypeError, ValueError):
            continue
        if v not in us:
            us.append(v)
    us.sort()
    if not us:
        return 2, 3
    if 2 in us and 3 in us:
        return 2, 3
    if len(us) >= 3:
        return us[1], us[2]
    if len(us) == 2:
        return us[0], us[1]
    return us[0], us[0]


def _dev_tasks_build_ancestor_keys(
    df: pd.DataFrame,
    level_col,
    task_col,
    *,
    block_outline_level=None,
    building_outline_level=None,
) -> pd.DataFrame:
    """
    По порядку строк MSP и колонке уровня строит ключи для фильтров:
    задача ур. block_outline_level (функциональный блок) и ур. building_outline_level (строение)
    как предки текущей строки.
    """
    work = df.copy().reset_index(drop=True)
    if (
        not level_col
        or level_col not in work.columns
        or not task_col
        or task_col not in work.columns
    ):
        work["_dt_lvl2_key"] = ""
        work["_dt_lvl3_key"] = ""
        work["_dt_lvl_num"] = np.nan
        return work
    lvl = _dev_outline_level_numeric(work[level_col])
    _tier_blk, _tier_bld = _deviations_msp_tier_levels(lvl)
    if block_outline_level is None:
        block_outline_level = _tier_blk
    if building_outline_level is None:
        building_outline_level = _tier_bld
    names = work[task_col].map(lambda x: str(x).strip() if pd.notna(x) else "")
    stack = []
    r2, r3, lvn = [], [], []
    for i in range(len(work)):
        L_raw = lvl.iloc[i] if i < len(lvl) else np.nan
        if pd.isna(L_raw):
            L = None
        else:
            try:
                L = int(round(float(L_raw)))
            except (TypeError, ValueError):
                L = None
        nm = names.iloc[i] if i < len(names) else ""
        lvn.append(float(L) if L is not None else np.nan)
        if L is None:
            r2.append("")
            r3.append("")
            continue
        while stack and stack[-1][0] >= L:
            stack.pop()
        a2 = ""
        a3 = ""
        for le, nn in stack:
            if le == block_outline_level:
                a2 = nn
            if le == building_outline_level:
                a3 = nn
        k2 = nm if L == block_outline_level else a2
        k3 = nm if L == building_outline_level else a3
        r2.append(k2)
        r3.append(k3)
        stack.append((L, nm))
    work["_dt_lvl2_key"] = r2
    work["_dt_lvl3_key"] = r3
    work["_dt_lvl_num"] = lvn
    return work


def _gdrs_header_is_dd_mm_yyyy(name) -> bool:
    """
    Колонка — календарный день: строка ДД.ММ.ГГГГ либо datetime/Timestamp в имени колонки после read_excel.
    """
    if name is None:
        return False
    try:
        if pd.isna(name):
            return False
    except Exception:
        pass
    if isinstance(name, (pd.Timestamp, datetime, date)):
        return True
    t = str(name).strip()
    # 01.02.2026 / 1.2.26
    if re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$", t):
        return True
    # "грязные" заголовки вида 02..01.2026 / 02...01.26
    if re.match(r"^\d{1,2}\.{2,3}\d{1,2}\.\d{2,4}$", t):
        return True
    return False


def _gdrs_match_data_source(series: pd.Series, wanted) -> pd.Series:
    """Фильтр по data_source без учёта регистра."""
    s = series.astype(str).str.strip().str.lower()
    w = str(wanted).strip().lower()
    if w in ("техника", "tech", "technique"):
        return s.isin({"техника", "tech", "technique"})
    if w in ("ресурсы", "ресурс"):
        return s.isin({"ресурсы", "ресурс"})
    return s == w


def _gdrs_is_metric_like_period_false_positive(col) -> bool:
    """Колонка не может быть «периодом»: метрики, дельта, суточные даты, служебные."""
    s = str(col).strip().lower()
    if not s:
        return True
    if s.startswith("unnamed"):
        return True
    if _gdrs_header_is_dd_mm_yyyy(col):
        return True
    bad = (
            "среднее" in s
            or "количество ресурс" in s
            or "за день" in s
            or "неделя" in s
            or "недел" in s
            or "дельт" in s
            or "отклон" in s
            or "план" == s
            or "факт" == s
            or "data_source" in s
            or "тип ресурсов" in s
    )
    if bad:
        return True
    # «…за месяц» в длинном названии метрики, не колонка «Месяц»
    if "за месяц" in s and s not in ("месяц", "за месяц") and "период" not in s:
        if not (s.startswith("месяц") or s.startswith("период")):
            return True
    return False


def _gdrs_resolve_period_column(df: pd.DataFrame):
    """
    Колонка календарного периода (Период / Месяц). Не используем find_column_by_partial
    с подстрокой «месяц» — иначе матчится «среднее … за месяц» и ломается ось X.
    """
    if df is None or getattr(df, "empty", True):
        return None
    for c in df.columns:
        if _gdrs_is_metric_like_period_false_positive(c):
            continue
        t = str(c).strip()
        tl = t.lower()
        if tl in ("период", "месяц", "period", "month"):
            return c
    for c in df.columns:
        if _gdrs_is_metric_like_period_false_positive(c):
            continue
        tl = str(c).strip().lower()
        if tl.startswith("период") or tl.startswith("месяц"):
            return c
    return None


def _gdrs_is_plan_column_false_positive(col) -> bool:
    s = str(col).strip().lower()
    if not s:
        return True
    if s.startswith("unnamed"):
        return True
    if _gdrs_header_is_dd_mm_yyyy(col):
        return True
    if "дельт" in s or "отклон" in s:
        return True
    if "бюджет" in s:
        return True
    # Метрики факта/средних и недельные поля не должны попадать в «План»
    if "среднее" in s or "average" in s:
        return True
    if "недел" in s or "week" in s:
        return True
    if "старт" in s or "конец" in s or "start" in s or "finish" in s:
        return True
    if s.startswith("планов") or s.startswith("планир"):
        return True
    return False


def _gdrs_resolve_plan_column(df: pd.DataFrame):
    """
    Колонка числового плана (чел.-дни и т.п.). Без жёсткого «подстрока план везде» —
    иначе цепляются «Планета», «плановый», «Старт План» из других отчётов.
    """
    if df is None or getattr(df, "empty", True):
        return None
    for c in df.columns:
        if _gdrs_is_plan_column_false_positive(c):
            continue
        tl = str(c).strip().lower()
        if tl in ("план", "plan"):
            return c
    for c in df.columns:
        if _gdrs_is_plan_column_false_positive(c):
            continue
        tl = str(c).strip().lower()
        if tl.startswith("план") and (len(tl) == 4 or tl[4] in " ,.(["):
            return c
        if tl.startswith("plan") and (len(tl) == 4 or tl[4] in " ,.(["):
            return c
    for c in df.columns:
        if _gdrs_is_plan_column_false_positive(c):
            continue
        tl = str(c).strip().lower()
        if re.search(r"(?<!\w)план(?!\w)", tl, flags=re.UNICODE):
            return c
        if re.search(r"(?<!\w)plan(?!\w)", tl, flags=re.UNICODE):
            return c
    return None


def _gdrs_point_pct_of_period_plan(
    by_frame: pd.DataFrame,
    df_src: pd.DataFrame,
    period_col: str,
    fact_col: str = "Факт",
) -> pd.DataFrame:
    """
    Доля для подписей точек «факт по неделям» / «факт по периоду»:
    **факт / сумма(План_numeric) по тому же периоду** × 100.
    Если колонки плана нет или сумма плана по периоду = 0 — fallback: доля факта в сумме факта по всем точкам (как раньше).
    Добавляет/перезаписывает колонки: «%», «План_период» (сумма плана по периоду или NaN).
    """
    out = by_frame.copy()
    if period_col not in out.columns or fact_col not in out.columns or out.empty:
        out["%"] = 0.0
        if "План_период" not in out.columns:
            out["План_период"] = np.nan
        return out
    fac = pd.to_numeric(out[fact_col], errors="coerce").fillna(0.0)
    total_fact = float(fac.sum())
    out["План_период"] = np.nan
    if df_src is not None and "План_numeric" in getattr(df_src, "columns", []):
        plan_sum = (
            df_src.groupby(period_col, dropna=False)["План_numeric"]
            .apply(lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0.0).sum()))
            .reset_index(name="_psum")
        )
        out = out.merge(plan_sum, on=period_col, how="left")
        psum = pd.to_numeric(out["_psum"], errors="coerce").fillna(0.0)
        out["План_период"] = psum
        out.drop(columns=["_psum"], inplace=True, errors="ignore")
        out["%"] = 0.0
        mask = psum > 0
        out.loc[mask, "%"] = (fac.loc[mask] / psum.loc[mask] * 100.0).clip(lower=0.0)
        rem = ~mask
        if rem.any() and total_fact > 0:
            out.loc[rem, "%"] = (fac.loc[rem] / total_fact * 100.0).round(1)
    else:
        out["%"] = ((fac / total_fact * 100.0).round(1) if total_fact else 0.0)
    return out


def _sample_for_chart(df: pd.DataFrame, max_rows: int = _MAX_CHART_ROWS) -> pd.DataFrame:
    """
    Если датафрейм превышает max_rows, равномерно сэмплирует его и показывает уведомление.
    Используется перед передачей больших таблиц в Plotly.
    """
    if df is None or df.empty or len(df) <= max_rows:
        return df
    sampled = df.sample(n=max_rows, random_state=42).sort_index()
    st.info(
        f"Показаны {max_rows:,} из {len(df):,} строк (равномерная выборка для ускорения графика)."
    )
    return sampled


def _limit_bar_categories(
    df: pd.DataFrame,
    value_col: str,
    max_bars: int = 40,
    label: str = "позиций",
) -> pd.DataFrame:
    """
    Оставляет топ-max_bars строк по убыванию value_col.
    Если отрезаны строки — показывает предупреждение.
    Используется для горизонтальных bar-графиков с большим числом категорий.
    """
    if df is None or df.empty or len(df) <= max_bars:
        return df
    top_df = df.nlargest(max_bars, value_col)
    st.info(
        f"График показывает топ-{max_bars} из {len(df)} {label} по убыванию значения."
    )
    return top_df


def wrap_label(text, width=15):
    return "<br>".join(textwrap.wrap(text, width=width))


def _xaxis_range_positive(values, pad: float = 1.15, min_span: float = 1.0):
    """
    Диапазон оси X для неотрицательных величин (гориз. bar): без лишнего «пустого» поля справа.
    Учитывает только конечные неотрицательные числа; иначе — компактный дефолт.
    """
    s = pd.to_numeric(pd.Series(values), errors="coerce")
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    s = s[s >= 0]
    if s.empty:
        return [0.0, float(min_span)]
    xmax = float(s.max())
    if not np.isfinite(xmax) or xmax <= 0:
        xmax = float(min_span)
    upper = max(xmax * pad, float(min_span))
    return [0.0, upper]


def _clean_display_str(val, empty: str = "") -> str:
    """Строка для ячеек: без nan/None; без «Н/Д» в табличных данных."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return empty
    s = str(val).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return empty
    return s


_DEV_REASONS_FULL_TABLE_CSS = """
<style>
.dev-reasons-wrap { overflow-x:auto; margin:0.5rem 0 1rem 0; }
.dev-reasons-table {
  width:100%; border-collapse:collapse; font-size:13px;
  font-family:Inter,system-ui,sans-serif;
}
.dev-reasons-table th {
  position:sticky; top:0; background:#1a1c23; color:#fafafa;
  padding:8px 10px; text-align:left; border-bottom:2px solid #444;
  font-weight:600; white-space:nowrap;
}
.dev-reasons-table td {
  padding:6px 10px; border-bottom:1px solid #333; color:#e0e0e0;
  white-space:nowrap; max-width:360px; overflow:hidden; text-overflow:ellipsis;
}
.dev-reasons-table tr:hover td { background:#262833; }
.dev-bg-turq { background:rgba(72,202,228,0.18) !important; }
.dev-bg-blue { background:rgba(52,152,219,0.22) !important; }
.dev-bg-dblue { background:rgba(26,82,118,0.38) !important; }
.dev-bg-lblue { background:rgba(214,234,248,0.14) !important; }
.dev-txt-ok { color:#27ae60 !important; font-weight:600; }
.dev-txt-bad { color:#c0392b !important; font-weight:600; }
</style>
"""


def _dev_days_diff(a, b):
    """Разница (a − b) в днях; NaN если нет дат."""
    if a is None or b is None:
        return np.nan
    try:
        if isinstance(a, float) and pd.isna(a):
            return np.nan
        if isinstance(b, float) and pd.isna(b):
            return np.nan
    except Exception:
        pass
    try:
        ta = pd.Timestamp(a)
        tb = pd.Timestamp(b)
        if pd.isna(ta) or pd.isna(tb):
            return np.nan
        return (ta - tb).total_seconds() / 86400.0
    except Exception:
        return np.nan


def _fmt_date_cell(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    try:
        t = pd.Timestamp(v)
        if pd.isna(t):
            return ""
        return t.strftime("%d.%m.%Y")
    except Exception:
        return str(v).strip() if v is not None else ""


def _fmt_int_days(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    try:
        return str(int(round(float(v), 0)))
    except (TypeError, ValueError):
        return ""


def _render_deviations_reasons_full_table(table_reason_df, building_col, notes_col):
    """
    Полная таблица отчёта «Причины отклонений» по правкам ТЗ: порядок колонок, подписи,
    отклонения начала/окончания и длительности, цветовые группы.
    """
    if table_reason_df is None or getattr(table_reason_df, "empty", True):
        st.info("Нет строк для полной таблицы.")
        return
    d = table_reason_df.copy()
    for c in ("plan start", "plan end", "base start", "base end"):
        if c in d.columns:
            d[c] = pd.to_datetime(d[c], errors="coerce", dayfirst=True)
    # MSP-совместимость: причина/заметки могут приходить в русских колонках без ремапа.
    reason_col = (
        "reason of deviation"
        if "reason of deviation" in d.columns
        else _find_column_by_keywords(d, ("причина отклон", "reason of deviation", "reason"))
    )
    notes_col_eff = (
        notes_col
        if notes_col and notes_col in d.columns
        else _find_column_by_keywords(d, ("заметк", "note", "comment", "remark", "notes"))
    )

    headers = ["Проект", "Задача"]
    if "block" in d.columns:
        headers.append("Функциональный блок")
    headers.extend(
        [
            "Начало",
            "Базовое начало",
            "Отклонение начала",
            "Окончание",
            "Базовое окончание",
            "Отклонение окончания",
            "Базовая длительность",
            "Длительность",
            "Причина отклонений",
            "Заметки",
        ]
    )
    if "snapshot_date" in d.columns:
        headers.append("Дата снимка")

    rows_out = []
    parts = [
        '<div class="dev-reasons-wrap">',
        '<table class="dev-reasons-table">',
        "<thead><tr>",
    ]
    for h in headers:
        parts.append(f"<th>{html_module.escape(h)}</th>")
    parts.append("</tr></thead><tbody>")

    for _, row in d.iterrows():
        ps = row.get("plan start")
        pe = row.get("plan end")
        bs = row.get("base start")
        be = row.get("base end")
        # ТЗ: отклонение начала = Базовое начало − Начало (дни)
        start_dev = _dev_days_diff(ps, bs)
        # ТЗ: отклонение окончания = Окончание − Базовое окончание (дни); красный шрифт если > 0
        end_dev = _dev_days_diff(be, pe)
        dur_b = _dev_days_diff(pe, ps)
        dur_f = _dev_days_diff(be, bs)

        pr = _clean_display_str(row.get("project name"))
        tn = _clean_display_str(row.get("task name"))
        cells = [
            ("", pr),
            ("", tn),
        ]
        if "block" in d.columns:
            cells.append(("", _clean_display_str(row.get("block"))))
        cells.extend(
            [
                ("dev-bg-turq", _fmt_date_cell(bs)),
                ("dev-bg-turq", _fmt_date_cell(ps)),
                (
                    "dev-bg-lblue",
                    _fmt_int_days(start_dev),
                    "start_dev",
                    start_dev,
                ),
                ("dev-bg-blue", _fmt_date_cell(be)),
                ("dev-bg-blue", _fmt_date_cell(pe)),
                (
                    "dev-bg-lblue",
                    _fmt_int_days(end_dev),
                    "end_dev",
                    end_dev,
                ),
                ("dev-bg-dblue", _fmt_int_days(dur_b)),
                ("dev-bg-dblue", _fmt_int_days(dur_f)),
                (
                    "",
                    _clean_display_str(row.get(reason_col))
                    if reason_col and reason_col in d.columns
                    else "",
                ),
                (
                    "",
                    _clean_display_str(row.get(notes_col_eff))
                    if notes_col_eff and notes_col_eff in d.columns
                    else "",
                ),
            ]
        )
        if "snapshot_date" in d.columns:
            sd = row.get("snapshot_date")
            try:
                sds = (
                    pd.Timestamp(sd).strftime("%d.%m.%Y")
                    if pd.notna(pd.to_datetime(sd, errors="coerce"))
                    else str(sd) if sd is not None else ""
                )
            except Exception:
                sds = str(sd) if sd is not None else ""
            cells.append(("", sds))

        row_csv = {}
        for i, h in enumerate(headers):
            if i < len(cells):
                ent = cells[i]
                if len(ent) == 4:
                    row_csv[h] = ent[1]
                elif len(ent) == 2:
                    row_csv[h] = ent[1]
                else:
                    row_csv[h] = ent[1] if len(ent) > 1 else ""
        rows_out.append(row_csv)

        parts.append("<tr>")
        for ent in cells:
            if len(ent) == 4:
                cls, txt, _kind, raw = ent
                fg = ""
                if _kind == "start_dev" and not (raw is None or (isinstance(raw, float) and pd.isna(raw))):
                    fg = " dev-txt-bad" if float(raw) < 0 else " dev-txt-ok"
                elif _kind == "end_dev" and not (raw is None or (isinstance(raw, float) and pd.isna(raw))):
                    fg = " dev-txt-bad" if float(raw) > 0 else " dev-txt-ok"
                esc = html_module.escape(txt) if str(txt).strip() != "" else ""
                parts.append(
                    f'<td class="{cls.strip()}{fg}">{esc}</td>'
                )
            else:
                cls, txt = ent[0], ent[1]
                esc = html_module.escape(txt) if str(txt).strip() != "" else ""
                parts.append(f'<td class="{cls.strip()}">{esc}</td>')
        parts.append("</tr>")

    parts.append("</tbody></table></div>")
    st.markdown(f"**Записей:** {len(d)}")
    st.markdown(_DEV_REASONS_FULL_TABLE_CSS + "".join(parts), unsafe_allow_html=True)

    out_df = pd.DataFrame(rows_out, columns=headers)
    render_dataframe_excel_csv_downloads(
        out_df,
        file_stem="deviations_detail",
        key_prefix="devtable_detail",
    )


def _find_column_by_keywords(df, keywords: tuple):
    """Первое имя колонки, в котором встречается любое из ключевых слов (без учёта регистра)."""
    if df is None or not hasattr(df, "columns"):
        return None
    for col in df.columns:
        cn = str(col).lower()
        for kw in keywords:
            if str(kw).lower() in cn:
                return col
    return None


def _find_first_column_matching_keywords(df, keywords: tuple):
    """
    Ищет колонку по ключевым словам в порядке приоритета: сначала более специфичные
    kw (например, «percent complete»), затем общие. Иначе «complete» в названии может
    сопоставиться с неверной колонкой раньше, чем доля выполнения задачи.
    """
    if df is None or not hasattr(df, "columns"):
        return None
    for kw in keywords:
        k = str(kw).lower()
        for col in df.columns:
            if k in str(col).lower():
                return col
    return None


def _safe_df_column_series(df, col_name):
    """Одна колонка: при дублирующихся именах в DataFrame берём первую серию."""
    if col_name is None or col_name not in df.columns:
        return None
    obj = df[col_name]
    if isinstance(obj, pd.DataFrame):
        return obj.iloc[:, 0]
    return obj


def _parse_msp_percent_complete_series(raw) -> pd.Series:
    """Приводит процент выполнения к шкале 0..100+ для фильтра «скрыть завершённые (100%)»."""
    if raw is None:
        return pd.Series(dtype=float)
    s = raw if isinstance(raw, pd.Series) else pd.Series(raw)
    t = s.astype(str).str.strip()
    t = t.str.replace("\xa0", "", regex=False).str.replace("\u200b", "", regex=False)
    t = t.str.replace("%", "", regex=False).str.replace(",", ".", regex=False)
    num = pd.to_numeric(t, errors="coerce")
    v = num.dropna()
    if not v.empty and float(v.max()) <= 1.000001:
        num = num * 100.0
    return num


def _chart_caption_below(title: str) -> None:
    """Заголовок под графиком (после подписей значений на столбцах/точках)."""
    if not title:
        return
    esc = html_module.escape(str(title))
    st.markdown(
        "<p style='text-align:center;color:#e8eef5;margin:0.6rem 0 1rem;font-size:1.08rem;font-weight:700;'>"
        f"{esc}</p>",
        unsafe_allow_html=True,
    )


# Единая конфигурация Plotly для всех графиков:
# responsive=True — перерисовка при изменении размера окна браузера
# displayModeBar — панель инструментов только при hover
_PLOTLY_CONFIG = {
    "responsive": True,
    "displayModeBar": True,
    "displaylogo": False,
    "scrollZoom": True,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
}


def _series_is_non_numeric_non_date(x) -> bool:
    """True, если ось по значениям похожа на категории/строки (не числа и не даты)."""
    if x is None:
        return False
    s = pd.Series(x)
    if s.empty:
        return False
    if pd.api.types.is_datetime64_any_dtype(s):
        return False
    if pd.api.types.is_numeric_dtype(s):
        return False
    return True


def _clamp_plotly_scroll_zoom_padding(fig: go.Figure) -> None:
    """
    Уменьшает «пустые поля» при зуме колёсиком (scrollZoom):
    - горизонтальные бары по датам (Gantt): ось X нельзя уводить далеко за пределы данных;
    - категориальные оси у столбиков: без интерактивного «растягивания» категорий (пустые промежутки).

    Вызывается из render_chart для всех фигур — для остальных типов графиков обычно no-op.
    """
    try:
        traces = list(fig.data or [])
    except Exception:
        return
    if not traces:
        return

    date_points = []
    has_h_bar = False
    has_v_categorical_bar = False

    for tr in traces:
        if type(tr).__name__ != "Bar":
            continue
        orient = getattr(tr, "orientation", None) or "v"
        if orient == "h":
            has_h_bar = True
            for arr in (getattr(tr, "x", None), getattr(tr, "base", None)):
                if arr is None:
                    continue
                s = pd.to_datetime(pd.Series(list(arr)), errors="coerce").dropna()
                if not s.empty:
                    date_points.extend(s.tolist())
        elif orient == "v" and _series_is_non_numeric_non_date(getattr(tr, "x", None)):
            has_v_categorical_bar = True

    if has_h_bar:
        try:
            fig.update_yaxes(fixedrange=True)
        except Exception:
            pass
    if has_v_categorical_bar:
        try:
            fig.update_xaxes(fixedrange=True)
        except Exception:
            pass

    if len(date_points) < 1:
        return
    d0 = pd.Timestamp(min(date_points))
    d1 = pd.Timestamp(max(date_points))
    if pd.isna(d0) or pd.isna(d1):
        return
    span_sec = max((d1 - d0).total_seconds(), 86400.0)
    pad_sec = max(span_sec * 0.06, 4 * 86400.0)
    lo = (d0 - pd.Timedelta(seconds=pad_sec)).to_pydatetime()
    hi = (d1 + pd.Timedelta(seconds=pad_sec)).to_pydatetime()
    try:
        fig.update_xaxes(minallowed=lo, maxallowed=hi)
    except Exception:
        pass


def _apply_finance_bar_label_layout(fig: go.Figure) -> go.Figure:
    try:
        fig.update_layout(
            uniformtext=dict(minsize=8, mode="hide"),
            # Верхний отступ — чтобы подписи «outside» над столбцами не обрезались и реже наезжали
            margin=dict(l=56, r=36, t=72, b=120),
        )
        fig.update_xaxes(automargin=True)
        fig.update_yaxes(automargin=True, rangemode="tozero")
    except Exception:
        pass
    return fig


def _apply_vertical_category_bar_width(fig: go.Figure) -> go.Figure:
    """
    Вертикальные bar по категориальной оси X: одинаковая визуальная ширина столбцов,
    минимальный зазор между ними (исполнительная документация и др.).
    """
    try:
        fig.update_layout(bargap=0.28, bargroupgap=0.12)
        fig.update_traces(width=0.68, selector=dict(type="bar"))
    except Exception:
        pass
    return fig


def _plotly_legend_horizontal_below_plot(
    fig: go.Figure,
    *,
    bottom_px: int = 300,
    top_px: int = 88,
    legend_y: float = -0.34,
) -> go.Figure:
    """
    Легенда под осью X (в нижнем поле, не над столбцами): отрицательный y + yanchor=top + margin b.
    У вызова render_chart задавайте height (БДДС: 560), иначе область графика может сжаться.
    """
    try:
        fig.update_layout(
            legend=dict(
                orientation="h",
                x=0.5,
                xanchor="center",
                y=legend_y,
                yanchor="top",
                font=dict(size=11, color="#e8eef5"),
            ),
            margin=dict(l=56, r=36, t=top_px, b=bottom_px),
        )
    except Exception:
        pass
    return fig


def _finance_bar_text_mln_rub(values_rub: pd.Series) -> list:
    """Подписи над столбцами по ТЗ: число и строка «млн руб.» (две строки)."""
    out = []
    for v in values_rub:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            out.append("")
            continue
        try:
            x = float(v) / 1e6
            out.append(f"{x:.2f}<br>млн руб.")
        except (TypeError, ValueError):
            out.append("")
    return out


def _apply_bar_uniformtext(fig: go.Figure) -> go.Figure:
    """
    Подписи bar: uniformtext + automargin по осям без перезаписи margin
    (для графиков с кастомными l/r/t/b).
    """
    try:
        fig.update_layout(uniformtext=dict(minsize=7, mode="hide"))
        fig.update_xaxes(automargin=True)
        fig.update_yaxes(automargin=True)
    except Exception:
        pass
    return fig


def render_chart(
    fig,
    key: str = None,
    height: int = None,
    max_height: int = 900,
    caption_below: str = None,
    plotly_config_extra=None,
    *,
    skip_clamp_zoom: bool = False,
) -> None:
    """
    Единая точка вывода Plotly-графика с адаптивной конфигурацией.
    Заменяет прямые вызовы st.plotly_chart() по всему файлу.
    Если задан только height — ограничиваем сверху max_height для читаемости на больших bar-графиках.
    caption_below — подпись под графиком (заголовок снизу); при этом у fig убирается верхний title.
    plotly_config_extra — дополнительные ключи config (мержатся поверх _PLOTLY_CONFIG).
    skip_clamp_zoom: не вызывать _clamp_plotly_scroll_zoom_padding (Gantt по датам: minallowed/maxallowed
    на оси X в Streamlit иногда даёт пустую область графика).
    """
    cfg = dict(_PLOTLY_CONFIG)
    if plotly_config_extra:
        cfg.update(plotly_config_extra)
    kwargs = {
        "width": "stretch",
        "config": cfg,
    }
    if key:
        kwargs["key"] = key
    if height is not None:
        h = min(int(height), int(max_height)) if max_height else int(height)
        fig.update_layout(height=h)
    if caption_below:
        try:
            fig.update_layout(title_text="")
        except Exception:
            pass
    if not skip_clamp_zoom:
        _clamp_plotly_scroll_zoom_padding(fig)
    st.plotly_chart(fig, **kwargs)
    if caption_below:
        _chart_caption_below(caption_below)


def render_export_buttons(
    df: pd.DataFrame = None,
    fig=None,
    csv_filename: str = "export.csv",
    png_filename: str = "chart.png",
    key_prefix: str = "export",
) -> None:
    """
    Автоэкспорт после отчёта: только PNG графика (поповер «Скачать таблицу» отключён).

    Args:
        df:           не даёт отдельной кнопки таблицы в этом блоке
        fig:          Plotly-фигура для PNG (опционально)
        csv_filename: резерв
        png_filename: Имя PNG-файла
        key_prefix:   префикс ключей виджетов
    """
    has_df = df is not None and not df.empty
    png_bytes = None
    if fig is not None:
        try:
            png_bytes = fig.to_image(format="png", width=1400, height=700, scale=2)
        except Exception:
            png_bytes = None

    if not has_df and png_bytes is None:
        return

    def _log_export(fmt_name: str, file_name: str):
        try:
            from auth import get_current_user
            from logger import log_action

            u = get_current_user()
            if u:
                log_action(
                    u["username"],
                    "data_exported",
                    f"{fmt_name}:{file_name} ({key_prefix})",
                )
        except Exception:
            pass

    if has_df and png_bytes is not None:
        # Таблицу из автоматического экспорта не дублируем (поповер «Скачать таблицу» убран по макету) —
        # остаётся только PNG графика.
        try:
            st.download_button(
                label="Скачать PNG",
                data=png_bytes,
                file_name=png_filename,
                mime="image/png",
                key=f"{key_prefix}_png",
                on_click=lambda: _log_export("png", png_filename),
            )
        except TypeError:
            st.download_button(
                label="Скачать PNG",
                data=png_bytes,
                file_name=png_filename,
                mime="image/png",
                key=f"{key_prefix}_png",
            )
        return

    if png_bytes is not None:
        try:
            st.download_button(
                label="Скачать PNG",
                data=png_bytes,
                file_name=png_filename,
                mime="image/png",
                key=f"{key_prefix}_png",
                on_click=lambda: _log_export("png", png_filename),
            )
        except TypeError:
            st.download_button(
                label="Скачать PNG",
                data=png_bytes,
                file_name=png_filename,
                mime="image/png",
                key=f"{key_prefix}_png",
            )


def _deviations_filter_month_string_to_period(month_str):
    try:
        parts = str(month_str).split()
        if len(parts) == 2:
            month_name, year = parts
            month_num = None
            for num, russian_name in RUSSIAN_MONTHS.items():
                if russian_name == month_name:
                    month_num = num
                    break
            if month_num:
                return pd.Period(f"{year}-{month_num:02d}", freq="M")
    except Exception:
        pass
    return None


def _drop_deviation_hierarchy_artifacts(d: pd.DataFrame) -> pd.DataFrame:
    """Удаляет служебные колонки _dt_* после фильтрации по иерархии MSP."""
    if d is None or getattr(d, "empty", True):
        return d
    drop = [c for c in d.columns if str(c).startswith("_dt_")]
    if not drop:
        return d
    return d.drop(columns=drop, errors="ignore")


# Разделитель для плоской модели «Блок · Раздел» (нет колонок уровня MSP в CSV/Excel)
_DEVIATIONS_FLAT_FB_SEP = " · "


def _deviations_resolve_task_col(df: pd.DataFrame):
    if df is None or not hasattr(df, "columns"):
        return None
    if "task name" in df.columns:
        return "task name"
    return _dev_tasks_find_column(df, ["Задача", "task", "Task Name", "Название"])


def _deviations_effective_level_col(df: pd.DataFrame):
    """
    Колонка уровня иерархии MSP для фильтров отклонений.

    ``_dev_tasks_resolve_level_column`` иногда не видит уровень, хотя после
    ``ensure_msp_hierarchy_columns`` уже есть непустой ``level structure``/``level``
    — тогда не падаем в сырой ``block`` («Блок U1…») в селекте «Функциональный блок».
    """
    if df is None or getattr(df, "empty", True):
        return None
    c = _dev_tasks_resolve_level_column(df)
    if c and c in df.columns:
        s = _dev_outline_level_numeric(df[c])
        if s.notna().any():
            return c
    if "level structure" in df.columns:
        s = _dev_outline_level_numeric(df["level structure"])
        if s.notna().any():
            return "level structure"
    if "level" in df.columns:
        s = _dev_outline_level_numeric(df["level"])
        if s.notna().any():
            return "level"
    return None


def _deviations_flat_fb_label(block_val, section_val) -> str:
    b = (
        str(block_val).strip()
        if block_val is not None and not (isinstance(block_val, float) and pd.isna(block_val))
        else ""
    )
    s = (
        str(section_val).strip()
        if section_val is not None and not (isinstance(section_val, float) and pd.isna(section_val))
        else ""
    )
    if b and s:
        return f"{b}{_DEVIATIONS_FLAT_FB_SEP}{s}"
    return b or s or ""


def _deviations_use_flat_block_section_task(df: pd.DataFrame) -> bool:
    """Excel/фиксированный макет: Блок + Раздел + Задача без колонок outline MSP."""
    if df is None or getattr(df, "empty", True):
        return False
    if _deviations_effective_level_col(df) is not None:
        return False
    tc = _deviations_resolve_task_col(df)
    if not tc or tc not in df.columns:
        return False
    if "block" not in df.columns or "section" not in df.columns:
        return False
    return True


def _deviations_flat_functional_block_options(df_slice: pd.DataFrame) -> list:
    if df_slice is None or getattr(df_slice, "empty", True):
        return ["Все"]
    if "block" not in df_slice.columns or "section" not in df_slice.columns:
        return ["Все"]
    w = df_slice[["block", "section"]].copy()
    w["_lbl"] = w.apply(lambda r: _deviations_flat_fb_label(r["block"], r["section"]), axis=1)
    u = sorted({x for x in w["_lbl"].dropna().astype(str).str.strip().tolist() if x})
    return ["Все"] + u


def _deviations_flat_building_options(
    df_slice: pd.DataFrame, selected_fb: str, task_col: str
) -> list:
    if df_slice is None or getattr(df_slice, "empty", True):
        return ["Все"]
    if not task_col or task_col not in df_slice.columns:
        return ["Все"]
    sub = df_slice
    if selected_fb != "Все" and _DEVIATIONS_FLAT_FB_SEP in str(selected_fb):
        parts = str(selected_fb).split(_DEVIATIONS_FLAT_FB_SEP, 1)
        if len(parts) == 2:
            blk, sec = parts[0].strip(), parts[1].strip()
            sub = sub[sub["block"].astype(str).str.strip() == blk]
            sub = sub[sub["section"].astype(str).str.strip() == sec]
    u = sorted(sub[task_col].dropna().astype(str).str.strip().unique().tolist())
    return ["Все"] + u


def _deviations_apply_block_building_filters(
    filtered_df: pd.DataFrame,
    selected_block: str,
    selected_building: str,
    building_col,
):
    """
    Функциональный блок и строение — по уровням MSP (2 и 3, если есть в данных; иначе вторая и третья ступени).
    Если колонки уровня нет — fallback на колонки block и строения в файле.
    """
    if filtered_df is None or getattr(filtered_df, "empty", True):
        return filtered_df
    level_col = _deviations_effective_level_col(filtered_df)
    task_col = (
        "task name"
        if "task name" in filtered_df.columns
        else _dev_tasks_find_column(
            filtered_df, ["Задача", "task", "Task Name", "Название"]
        )
    )
    use_hierarchy = bool(level_col and task_col and task_col in filtered_df.columns)
    if use_hierarchy:
        _ln_fb = _dev_outline_level_numeric(filtered_df[level_col])
        _blv, _bdv = _deviations_msp_tier_levels(_ln_fb)
        wh = _dev_tasks_build_ancestor_keys(
            filtered_df,
            level_col,
            task_col,
            block_outline_level=_blv,
            building_outline_level=_bdv,
        )
        if selected_block != "Все":
            wh = wh[
                wh["_dt_lvl2_key"].astype(str).str.strip()
                == str(selected_block).strip()
            ]
        if selected_building != "Все":
            wh = wh[
                wh["_dt_lvl3_key"].astype(str).str.strip()
                == str(selected_building).strip()
            ]
        return _drop_deviation_hierarchy_artifacts(wh)
    out = filtered_df
    use_flat = (
        task_col
        and task_col in out.columns
        and "block" in out.columns
        and "section" in out.columns
        and not use_hierarchy
    )
    if use_flat:
        if selected_block != "Все":
            sb = str(selected_block).strip()
            if _DEVIATIONS_FLAT_FB_SEP in sb:
                parts = sb.split(_DEVIATIONS_FLAT_FB_SEP, 1)
                if len(parts) == 2:
                    blk, sec = parts[0].strip(), parts[1].strip()
                    out = out[out["block"].astype(str).str.strip() == blk]
                    out = out[out["section"].astype(str).str.strip() == sec]
            elif "block" in out.columns:
                out = out[out["block"].astype(str).str.strip() == sb]
        if selected_building != "Все":
            out = out[out[task_col].astype(str).str.strip() == str(selected_building).strip()]
        return out
    if selected_block != "Все" and "block" in out.columns:
        out = out[
            out["block"].astype(str).str.strip() == str(selected_block).strip()
        ]
    if (
        selected_building != "Все"
        and building_col
        and building_col in out.columns
    ):
        out = out[
            out[building_col].astype(str).str.strip()
            == str(selected_building).strip()
        ]
    return out


def _deviations_project_slice_by_key(df: pd.DataFrame, state_key: str) -> pd.DataFrame:
    """Срез по выбранному проекту (ключ session_state) — для списков блока/строения."""
    pr = st.session_state.get(state_key, "Все")
    if pr != "Все" and df is not None and "project name" in df.columns:
        return df[
            df["project name"].astype(str).str.strip() == str(pr).strip()
        ].copy()
    return df.copy() if df is not None else df


def _render_deviations_combined_shared_filters(df):
    ensure_msp_hierarchy_columns(df)
    st.markdown(
        """
        <style>
        div[data-testid="column"] {
            flex: 1 1 0%;
            min-width: 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    building_col = _find_column_by_keywords(
        df, ("building", "строение", "лот", "lot", "bldg")
    )
    level_col = _deviations_effective_level_col(df)
    task_col = (
        "task name"
        if "task name" in df.columns
        else _dev_tasks_find_column(df, ["Задача", "task", "Task Name", "Название"])
    )
    use_hierarchy = bool(level_col and task_col and task_col in df.columns)
    use_flat_bs = _deviations_use_flat_block_section_task(df)

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        if "project name" in df.columns:
            _session_reset_project_if_excluded("devcombo_project")
            projects = ["Все"] + _project_name_select_options(df["project name"])
            st.selectbox("Проект", projects, key="devcombo_project")
    with col2:
        df_opts = _deviations_project_slice_by_key(df, "devcombo_project")
        if use_hierarchy:
            _ln_opts = _dev_outline_level_numeric(df_opts[level_col])
            _blv, _bdv = _deviations_msp_tier_levels(_ln_opts)
            wh = _dev_tasks_build_ancestor_keys(
                df_opts.copy(),
                level_col,
                task_col,
                block_outline_level=_blv,
                building_outline_level=_bdv,
            )
            ln = _dev_outline_level_numeric(wh[level_col])
            block_opts = ["Все"] + sorted(
                wh.loc[ln == _blv, task_col]
                .dropna()
                .astype(str)
                .str.strip()
                .unique()
                .tolist()
            )
            if len(block_opts) <= 1 and "_dt_lvl2_key" in wh.columns:
                _k2c = wh["_dt_lvl2_key"].astype(str).str.strip()
                _k2c = _k2c[_k2c.ne("") & _k2c.str.lower().ne("nan")]
                if len(_k2c):
                    block_opts = ["Все"] + sorted(pd.unique(_k2c).tolist())
            st.selectbox(
                "Функциональный блок",
                block_opts,
                key="devcombo_block",
                help=f"Задачи уровня {_blv} (иерархия MSP по колонке уровня).",
            )
        elif use_flat_bs:
            fb_opts = _deviations_flat_functional_block_options(df_opts)
            st.selectbox(
                "Функциональный блок",
                fb_opts,
                key="devcombo_block",
                help="Нет колонки уровня MSP в файле: «Блок · Раздел» (аналог функционального блока). "
                "Для списка задач уровня 2 по MSP загрузите выгрузку с «Уровень_структуры» / Outline Level.",
            )
        elif "block" in df.columns:
            blocks = ["Все"] + sorted(
                df["block"].dropna().astype(str).str.strip().unique().tolist()
            )
            st.selectbox("Функциональный блок", blocks, key="devcombo_block")
        else:
            st.caption("Нет колонки блока")
    with col3:
        df_opts = _deviations_project_slice_by_key(df, "devcombo_project")
        if use_hierarchy:
            _ln_opts_b = _dev_outline_level_numeric(df_opts[level_col])
            _blv_b, _bdv_b = _deviations_msp_tier_levels(_ln_opts_b)
            wh = _dev_tasks_build_ancestor_keys(
                df_opts.copy(),
                level_col,
                task_col,
                block_outline_level=_blv_b,
                building_outline_level=_bdv_b,
            )
            ln = _dev_outline_level_numeric(wh[level_col])
            sb = st.session_state.get("devcombo_block", "Все")
            w3 = wh[ln == _bdv_b]
            if sb != "Все":
                w3 = w3[
                    w3["_dt_lvl2_key"].astype(str).str.strip()
                    == str(sb).strip()
                ]
            build_opts = ["Все"] + sorted(
                w3[task_col].dropna().astype(str).str.strip().unique().tolist()
            )
            if len(build_opts) <= 1 and sb != "Все" and "_dt_lvl3_key" in w3.columns:
                _k3b = w3["_dt_lvl3_key"].astype(str).str.strip()
                _k3b = _k3b[_k3b.ne("") & _k3b.str.lower().ne("nan")]
                if len(_k3b):
                    build_opts = ["Все"] + sorted(pd.unique(_k3b).tolist())
            st.selectbox(
                "Строение",
                build_opts,
                key="devcombo_building",
                help=f"Задачи уровня {_bdv_b} в выбранном функциональном блоке (ур. {_blv_b}).",
            )
        elif use_flat_bs:
            _tc_fb = _deviations_resolve_task_col(df_opts)
            _sb_fb = st.session_state.get("devcombo_block", "Все")
            _bld_opts = _deviations_flat_building_options(df_opts, _sb_fb, _tc_fb)
            st.selectbox(
                "Строение",
                _bld_opts,
                key="devcombo_building",
                help="Задачи в выбранном «Блок · Раздел» (аналог строения / уровень 3 без MSP).",
            )
        elif building_col and building_col in df.columns:
            bvals = ["Все"] + sorted(
                df[building_col].dropna().astype(str).str.strip().unique().tolist()
            )
            st.selectbox("Строение", bvals, key="devcombo_building")
        else:
            st.caption("Нет строения")

    available_months = []
    if "plan_month" in df.columns:
        unique_months = df["plan_month"].dropna().unique()
        if len(unique_months) > 0:
            month_dict = {format_period_ru(m): m for m in unique_months}
            available_months = sorted(month_dict.keys(), key=lambda x: month_dict[x])
    elif "plan end" in df.columns:
        mask = df["plan end"].notna()
        if mask.any():
            temp_months = df.loc[mask, "plan end"].dt.to_period("M").unique()
            if len(temp_months) > 0:
                month_dict = {format_period_ru(m): m for m in temp_months}
                available_months = sorted(month_dict.keys(), key=lambda x: month_dict[x])

    with col4:
        if len(available_months) > 0:
            months_opts = ["Все"] + available_months
            st.selectbox("Период с", months_opts, key="devcombo_period_from")
        else:
            st.selectbox("Период с", ["Все"], key="devcombo_period_from", disabled=True)
    with col5:
        if len(available_months) > 0:
            months_opts = ["Все"] + available_months
            st.selectbox("Период по", months_opts, key="devcombo_period_to")
        else:
            st.selectbox("Период по", ["Все"], key="devcombo_period_to", disabled=True)

    with col6:
        st.checkbox(
            "ТОП‑5",
            value=False,
            key="reason_top5",
            help="Оставить только пять наиболее частых причин на диаграммах первой вкладки.",
        )

    filtered_df = df.copy()
    selected_project = (
        st.session_state.get("devcombo_project", "Все")
        if "project name" in filtered_df.columns
        else "Все"
    )
    selected_block = st.session_state.get("devcombo_block", "Все")
    selected_building = st.session_state.get("devcombo_building", "Все")
    period_from = (
        st.session_state.get("devcombo_period_from", "Все")
        if len(available_months) > 0
        else "Все"
    )
    period_to = (
        st.session_state.get("devcombo_period_to", "Все")
        if len(available_months) > 0
        else "Все"
    )

    if selected_project != "Все" and "project name" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["project name"].astype(str).str.strip()
            == str(selected_project).strip()
        ]
    filtered_df = _deviations_apply_block_building_filters(
        filtered_df, selected_block, selected_building, building_col
    )

    has_plan_month_col = "plan_month" in filtered_df.columns
    if has_plan_month_col and (period_from != "Все" or period_to != "Все"):
        pf = (
            _deviations_filter_month_string_to_period(period_from)
            if period_from != "Все"
            else None
        )
        pt = (
            _deviations_filter_month_string_to_period(period_to)
            if period_to != "Все"
            else None
        )
        if pf is not None and pt is not None and pf > pt:
            pf, pt = pt, pf
        if pf is not None:
            filtered_df = filtered_df[filtered_df["plan_month"] >= pf]
        if pt is not None:
            filtered_df = filtered_df[filtered_df["plan_month"] <= pt]
    elif not has_plan_month_col and "plan end" in filtered_df.columns:
        pf = (
            _deviations_filter_month_string_to_period(period_from)
            if period_from != "Все"
            else None
        )
        pt = (
            _deviations_filter_month_string_to_period(period_to)
            if period_to != "Все"
            else None
        )
        if pf is not None or pt is not None:
            if pf is not None and pt is not None and pf > pt:
                pf, pt = pt, pf
            _pe = pd.to_datetime(
                filtered_df["plan end"], errors="coerce", dayfirst=True
            )
            pm = _pe.dt.to_period("M")
            ok = pd.Series(True, index=filtered_df.index)
            if pf is not None:
                ok &= pm >= pf
            if pt is not None:
                ok &= pm <= pt
            filtered_df = filtered_df[ok]

    return filtered_df, building_col


def dashboard_deviations_combined(df):

    """Единый отчёт по отклонениям с табами (макет правок: общий заголовок «Причины отклонений»)."""
    if df is None or not hasattr(df, "columns") or df.empty:
        st.warning(
            "Нет данных для отображения. Пожалуйста, загрузите данные проекта."
        )
        return

    st.header("Причины отклонений")
    st.caption(
        "Категории в диаграммах и таблицах приведены к перечню из последних правок по отчёту "
        "(стек долей, легенда и детальная таблица)."
    )
    filtered_shared, building_col = _render_deviations_combined_shared_filters(df)
    tab_by_month, tab_dynamics, tab_reasons = st.tabs(
        [
            "Доли причин по проекту",
            "Динамика отклонений по месяцам",
            "Динамика причин",
        ]
    )
    with tab_by_month:
        dashboard_reasons_of_deviation(
            filtered_shared, hide_shared_filters=True, building_col=building_col
        )
    with tab_dynamics:
        dashboard_dynamics_of_deviations(filtered_shared, hide_shared_filters=True)
    with tab_reasons:
        dashboard_dynamics_of_reasons(filtered_shared, hide_shared_filters=True)


def dashboard_reasons_of_deviation(df, hide_shared_filters=False, building_col=None):
    # Проверка на None или пустой DataFrame
    if df is None:
        st.warning(
            "Нет данных для отображения. Пожалуйста, загрузите данные проекта."
        )
        return

    # Проверка, что df является DataFrame и имеет атрибут columns
    if not hasattr(df, "columns") or df.empty:
        st.warning(
            "Нет данных для отображения. Пожалуйста, загрузите данные проекта."
        )
        return

    ensure_msp_hierarchy_columns(df)

    # При hide_shared_filters фильтры задаются в общем блоке; локальные selectbox не рисуются — задаём значения по умолчанию.
    selected_project = "Все"

    if building_col is None:
        building_col = _find_column_by_keywords(
            df, ("building", "строение", "лот", "lot", "bldg")
        )

    if not hide_shared_filters:
        st.header("Доли причин отклонений по проекту")

        st.markdown(
            """
            <style>
            div[data-testid="column"] {
                flex: 1 1 0%;
                min-width: 0;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        _lvl_rs = _deviations_effective_level_col(df)
        _task_rs = (
            "task name"
            if "task name" in df.columns
            else _dev_tasks_find_column(
                df, ["Задача", "task", "Task Name", "Название"]
            )
        )
        _use_hi_rs = bool(_lvl_rs and _task_rs and _task_rs in df.columns)
        _use_flat_rs = _deviations_use_flat_block_section_task(df)

        col1, col2, col3 = st.columns(3)

        with col1:
            try:
                has_project_column = "project name" in df.columns
            except (AttributeError, TypeError):
                has_project_column = False

            if has_project_column:
                _session_reset_project_if_excluded("reason_project")
                projects = ["Все"] + _project_name_select_options(df["project name"])
                selected_project = st.selectbox("Проект", projects, key="reason_project")
            else:
                selected_project = "Все"

        with col2:
            df_opts = _deviations_project_slice_by_key(df, "reason_project")
            if _use_hi_rs:
                _ln_rs = _dev_outline_level_numeric(df_opts[_lvl_rs])
                _blv_rs, _bdv_rs = _deviations_msp_tier_levels(_ln_rs)
                wh = _dev_tasks_build_ancestor_keys(
                    df_opts.copy(),
                    _lvl_rs,
                    _task_rs,
                    block_outline_level=_blv_rs,
                    building_outline_level=_bdv_rs,
                )
                ln = _dev_outline_level_numeric(wh[_lvl_rs])
                block_opts = ["Все"] + sorted(
                    wh.loc[ln == _blv_rs, _task_rs]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .unique()
                    .tolist()
                )
                if len(block_opts) <= 1 and "_dt_lvl2_key" in wh.columns:
                    _k2r = wh["_dt_lvl2_key"].astype(str).str.strip()
                    _k2r = _k2r[_k2r.ne("") & _k2r.str.lower().ne("nan")]
                    if len(_k2r):
                        block_opts = ["Все"] + sorted(pd.unique(_k2r).tolist())
                st.selectbox(
                    "Функциональный блок",
                    block_opts,
                    key="reason_block",
                    help=f"Задачи уровня {_blv_rs} (иерархия MSP по колонке уровня).",
                )
            elif _use_flat_rs:
                fb_opts_rs = _deviations_flat_functional_block_options(df_opts)
                st.selectbox(
                    "Функциональный блок",
                    fb_opts_rs,
                    key="reason_block",
                    help="Нет колонки уровня MSP в файле: «Блок · Раздел» (аналог функционального блока). "
                    "Для списка задач уровня 2 по MSP загрузите выгрузку с «Уровень_структуры» / Outline Level.",
                )
            elif "block" in df.columns:
                blocks = ["Все"] + sorted(
                    df["block"].dropna().astype(str).str.strip().unique().tolist()
                )
                st.selectbox("Функциональный блок", blocks, key="reason_block")
            else:
                st.caption("Нет колонки блока")

        with col3:
            df_opts = _deviations_project_slice_by_key(df, "reason_project")
            if _use_hi_rs:
                _ln_rs_b = _dev_outline_level_numeric(df_opts[_lvl_rs])
                _blv_rsb, _bdv_rsb = _deviations_msp_tier_levels(_ln_rs_b)
                wh = _dev_tasks_build_ancestor_keys(
                    df_opts.copy(),
                    _lvl_rs,
                    _task_rs,
                    block_outline_level=_blv_rsb,
                    building_outline_level=_bdv_rsb,
                )
                ln = _dev_outline_level_numeric(wh[_lvl_rs])
                sb = st.session_state.get("reason_block", "Все")
                w3 = wh[ln == _bdv_rsb]
                if sb != "Все":
                    w3 = w3[
                        w3["_dt_lvl2_key"].astype(str).str.strip()
                        == str(sb).strip()
                    ]
                build_opts = ["Все"] + sorted(
                    w3[_task_rs].dropna().astype(str).str.strip().unique().tolist()
                )
                if len(build_opts) <= 1 and sb != "Все" and "_dt_lvl3_key" in w3.columns:
                    _k3r = w3["_dt_lvl3_key"].astype(str).str.strip()
                    _k3r = _k3r[_k3r.ne("") & _k3r.str.lower().ne("nan")]
                    if len(_k3r):
                        build_opts = ["Все"] + sorted(pd.unique(_k3r).tolist())
                st.selectbox(
                    "Строение",
                    build_opts,
                    key="reason_building",
                    help=f"Задачи уровня {_bdv_rsb} в выбранном функциональном блоке (ур. {_blv_rsb}).",
                )
            elif _use_flat_rs:
                _tc_rs = _deviations_resolve_task_col(df_opts)
                _sb_rs = st.session_state.get("reason_block", "Все")
                _bld_rs = _deviations_flat_building_options(df_opts, _sb_rs, _tc_rs)
                st.selectbox(
                    "Строение",
                    _bld_rs,
                    key="reason_building",
                    help="Задачи в выбранном «Блок · Раздел» (аналог строения / уровень 3 без MSP).",
                )
            elif building_col and building_col in df.columns:
                bvals = ["Все"] + sorted(
                    df[building_col].dropna().astype(str).str.strip().unique().tolist()
                )
                st.selectbox("Строение", bvals, key="reason_building")
            else:
                st.caption("Нет строения")

        available_months = []
        try:
            has_plan_month_column = "plan_month" in df.columns
        except (AttributeError, TypeError):
            has_plan_month_column = False

        if has_plan_month_column:
            unique_months = df["plan_month"].dropna().unique()
            if len(unique_months) > 0:
                month_dict = {format_period_ru(m): m for m in unique_months}
                available_months = sorted(
                    month_dict.keys(), key=lambda x: month_dict[x]
                )
        else:
            try:
                has_plan_end_column = "plan end" in df.columns
            except (AttributeError, TypeError):
                has_plan_end_column = False

            if has_plan_end_column:
                mask = df["plan end"].notna()
                if mask.any():
                    temp_months = df.loc[mask, "plan end"].dt.to_period("M").unique()
                    if len(temp_months) > 0:
                        month_dict = {format_period_ru(m): m for m in temp_months}
                        available_months = sorted(
                            month_dict.keys(), key=lambda x: month_dict[x]
                        )

        r2b, r2c = st.columns(2)
        with r2b:
            if len(available_months) > 0:
                months_opts = ["Все"] + available_months
                period_from = st.selectbox(
                    "Период с", months_opts, key="reason_period_from"
                )
            else:
                period_from = "Все"
                st.selectbox("Период с", ["Все"], key="reason_period_from", disabled=True)
        with r2c:
            if len(available_months) > 0:
                months_opts = ["Все"] + available_months
                period_to = st.selectbox(
                    "Период по", months_opts, key="reason_period_to"
                )
            else:
                period_to = "Все"
                st.selectbox("Период по", ["Все"], key="reason_period_to", disabled=True)
    else:
        period_from = "Все"
        period_to = "Все"
        available_months = []

    filtered_df = df.copy()

    try:
        has_project_col = "project name" in filtered_df.columns
    except (AttributeError, TypeError):
        has_project_col = False

    if not hide_shared_filters:
        if selected_project != "Все" and has_project_col:
            filtered_df = filtered_df[
                filtered_df["project name"].astype(str).str.strip()
                == str(selected_project).strip()
            ]
        filtered_df = _deviations_apply_block_building_filters(
            filtered_df,
            st.session_state.get("reason_block", "Все"),
            st.session_state.get("reason_building", "Все"),
            building_col,
        )

    try:
        has_reason_col = "reason of deviation" in filtered_df.columns
    except (AttributeError, TypeError):
        has_reason_col = False

    try:
        has_plan_month_col = "plan_month" in filtered_df.columns
    except (AttributeError, TypeError):
        has_plan_month_col = False

    if has_plan_month_col and (period_from != "Все" or period_to != "Все"):
        pf = (
            _deviations_filter_month_string_to_period(period_from)
            if period_from != "Все"
            else None
        )
        pt = (
            _deviations_filter_month_string_to_period(period_to)
            if period_to != "Все"
            else None
        )
        if pf is not None and pt is not None and pf > pt:
            pf, pt = pt, pf
        if pf is not None:
            filtered_df = filtered_df[filtered_df["plan_month"] >= pf]
        if pt is not None:
            filtered_df = filtered_df[filtered_df["plan_month"] <= pt]
    elif not has_plan_month_col and "plan end" in filtered_df.columns:
        pf = (
            _deviations_filter_month_string_to_period(period_from)
            if period_from != "Все"
            else None
        )
        pt = (
            _deviations_filter_month_string_to_period(period_to)
            if period_to != "Все"
            else None
        )
        if pf is not None or pt is not None:
            if pf is not None and pt is not None and pf > pt:
                pf, pt = pt, pf
            _pe = pd.to_datetime(
                filtered_df["plan end"], errors="coerce", dayfirst=True
            )
            pm = _pe.dt.to_period("M")
            ok = pd.Series(True, index=filtered_df.index)
            if pf is not None:
                ok &= pm >= pf
            if pt is not None:
                ok &= pm <= pt
            filtered_df = filtered_df[ok]

    # Filter tasks relevant for "dynamics of deviations": deviation=1/True OR reason of deviation filled
    try:
        has_deviation_col = "deviation" in filtered_df.columns
        has_reason_col = "reason of deviation" in filtered_df.columns
    except (AttributeError, TypeError):
        has_deviation_col = False
        has_reason_col = False

    if has_deviation_col or has_reason_col:
        # Rows with deviation flag = 1/True
        if has_deviation_col:
            deviation_flag = (
                (filtered_df["deviation"] == True)
                | (filtered_df["deviation"] == 1)
                | (filtered_df["deviation"].astype(str).str.lower() == "true")
                | (filtered_df["deviation"].astype(str).str.strip() == "1")
            )
        else:
            deviation_flag = pd.Series(False, index=filtered_df.index)
        # Rows with non-empty reason of deviation (для project_fixed: показываем и при причине)
        if has_reason_col:
            reason_filled = (
                filtered_df["reason of deviation"].notna()
                & (filtered_df["reason of deviation"].astype(str).str.strip() != "")
            )
        else:
            reason_filled = pd.Series(False, index=filtered_df.index)
        filtered_df = filtered_df[deviation_flag | reason_filled]

    if filtered_df.empty:
        st.info("Нет данных для выбранных фильтров.")
        return

    if hide_shared_filters:
        top5_only = bool(st.session_state.get("reason_top5", False))
    else:
        top5_only = st.checkbox(
            "ТОП 5 причин отклонений",
            value=False,
            key="reason_top5",
            help="Оставить только пять наиболее частых причин на диаграммах.",
        )

    # Summary metrics: основная причина и доля (метрика «Всего задач» убрана по правкам макета)
    has_reason_col_metric = "reason of deviation" in filtered_df.columns
    main_reason_name = "—"
    main_reason_pct = 0.0
    main_reason_count = 0
    if has_reason_col_metric and not filtered_df.empty:
        reason_counts = filtered_df["reason of deviation"].value_counts()
        if not reason_counts.empty:
            main_reason_name = str(reason_counts.index[0]).strip() or "—"
            main_reason_count = int(reason_counts.iloc[0])
            total_tasks = len(filtered_df)
            main_reason_pct = (main_reason_count / total_tasks * 100) if total_tasks else 0.0

    m1, m2 = st.columns(2)
    with m1:
        st.metric("Основная причина отклонения", main_reason_name[:50] + ("…" if len(main_reason_name) > 50 else ""))
    with m2:
        col3_value = f"{main_reason_pct:.1f}% ({main_reason_count})" if (has_reason_col_metric and main_reason_count > 0) else "—"
        st.metric("Доля основной причины", col3_value)

    # Reasons breakdown
    try:
        has_reason_col_breakdown = "reason of deviation" in filtered_df.columns
    except (AttributeError, TypeError):
        has_reason_col_breakdown = False

    if has_reason_col_breakdown:
        reason_counts = filtered_df["reason of deviation"].value_counts().reset_index()
        reason_counts.columns = ["Причина", "Количество"]
        total_rc = float(reason_counts["Количество"].sum()) or 1.0
        reason_counts["pct"] = (reason_counts["Количество"] / total_rc * 100).round(1)
        if top5_only:
            reason_counts = reason_counts.nlargest(5, "Количество").reset_index(drop=True)
        reason_counts["label_bar"] = reason_counts.apply(
            lambda r: f"{int(r['Количество'])}\n({r['pct']}%)", axis=1
        )

        fig = px.bar(
            reason_counts,
            x="Причина",
            y="Количество",
            title=None,
            labels={
                "Причина": "Причина отклонения",
                "Количество": "Количество",
            },
            text="label_bar",
        )
        fig.update_traces(
            textposition="outside", textfont=dict(size=14, color="white")
        )
        fig = _apply_finance_bar_label_layout(fig)
        fig = apply_chart_background(fig)
        _ymax = float(reason_counts["Количество"].max() or 0)
        n = len(reason_counts)
        _bar_h = max(480, int(140 + n * 56))
        _y_top = max(1.0, _ymax * 1.42 + 8.0)
        fig.update_layout(
            height=_bar_h,
            margin=dict(l=24, r=24, t=96, b=140 if n > 6 else 100),
            yaxis=dict(
                range=[0, _y_top],
                title="Количество",
                automargin=True,
            ),
        )
        if n > 6:
            fig.update_xaxes(tickangle=-45)
        else:
            fig.update_xaxes(
                tickangle=0,
                tickmode="array",
                tickvals=reason_counts["Причина"].tolist(),
                ticktext=[wrap_label(r, width=15) for r in reason_counts["Причина"].tolist()],
                tickfont=dict(size=14),
                ticklabelstandoff=12,
                overwrite=True,
            )
        render_chart(fig, caption_below="")

        total = reason_counts["Количество"].sum()
        if "pct" not in reason_counts.columns:
            reason_counts["pct"] = (reason_counts["Количество"] / (float(total) or 1.0) * 100).round(1)

        n_reasons = len(reason_counts)
        fig = px.pie(
            reason_counts,
            values="Количество",
            names="Причина",
            title=None,
        )
        _pie_textpos = "outside" if n_reasons <= 6 else "inside"
        _pie_font = 11 if n_reasons <= 6 else 10
        fig.update_traces(
            textinfo="none",
            texttemplate="%{label}<br>%{value}<br>(%{percent})",
            textposition=_pie_textpos,
            textfont_size=_pie_font,
            insidetextorientation="radial",
            hovertemplate="<b>%{label}</b><br>Количество: %{value}<br>Доля: %{percent}<extra></extra>",
        )
        fig.update_layout(
            height=600,
            margin=dict(l=20, r=20, t=30, b=30),
            legend=dict(
                orientation="h",
                x=0.5, y=-0.15,
                xanchor="center", yanchor="top",
                font=dict(size=9),
            ),
            font=dict(family="Inter, system-ui, sans-serif"),
            uniformtext=dict(minsize=7, mode="hide"),
            showlegend=True,
        )
        fig = apply_chart_background(fig)
        render_chart(fig, caption_below="")

    # Подпись текущего проекта (макет правок); в комбинированном отчёте — из общих фильтров
    if hide_shared_filters:
        _pl = st.session_state.get("devcombo_project", "Все")
        proj_lbl = str(_pl).strip() if _pl != "Все" else "Все проекты"
    else:
        proj_lbl = (
            str(selected_project).strip()
            if selected_project != "Все"
            else "Все проекты"
        )
    st.markdown(
        f"<div style='text-align:right;font-size:1.35rem;font-weight:600;color:#b8c0cc;margin:0.75rem 0 0 0'>{html_module.escape(proj_lbl)}</div>",
        unsafe_allow_html=True,
    )

    # Детальная таблица по макету (п. 11): уровень 5, причина заполнена, отклонение окончания < 0
    st.subheader("Детальные данные")
    table_reason_df = filtered_df
    selected_reason_table = "Все"
    if has_reason_col:
        _reason_opts_tbl = ["Все"] + sorted(
            filtered_df["reason of deviation"].dropna().astype(str).str.strip().unique().tolist()
        )
        selected_reason_table = st.selectbox(
            "Причина",
            _reason_opts_tbl,
            key="reason_filter_table_only",
            help="Влияет только на таблицы ниже (не на диаграммы и метрики выше).",
        )
        if selected_reason_table != "Все":
            table_reason_df = filtered_df[
                filtered_df["reason of deviation"].astype(str).str.strip()
                == str(selected_reason_table).strip()
            ]
    notes_col_m = _find_column_by_keywords(
        filtered_df, ("note", "заметк", "comment", "remark", "notes")
    )
    work_m = table_reason_df.copy()
    try:
        ensure_date_columns(work_m)
    except Exception:
        pass
    if "plan end" in work_m.columns:
        work_m["plan end"] = pd.to_datetime(
            work_m["plan end"], errors="coerce", dayfirst=True
        )
    if "base end" in work_m.columns:
        work_m["base end"] = pd.to_datetime(
            work_m["base end"], errors="coerce", dayfirst=True
        )

    work_m["_end_diff"] = np.nan
    if "plan end" in work_m.columns and "base end" in work_m.columns:
        _m = work_m["plan end"].notna() & work_m["base end"].notna()
        work_m.loc[_m, "_end_diff"] = (
            work_m.loc[_m, "base end"] - work_m.loc[_m, "plan end"]
        ).dt.total_seconds() / 86400.0

    mask_r = pd.Series(True, index=work_m.index)
    if "reason of deviation" in work_m.columns:
        mask_r = (
            work_m["reason of deviation"].notna()
            & (work_m["reason of deviation"].astype(str).str.strip() != "")
        )
    mask_l = pd.Series(True, index=work_m.index)
    if "level" in work_m.columns:
        _ln = pd.to_numeric(work_m["level"], errors="coerce")
        mask_l = _ln == 5
    mask_neg = work_m["_end_diff"].notna() & (work_m["_end_diff"] < 0)
    maket_df = work_m[mask_r & mask_l & mask_neg].copy()
    maket_df = maket_df.sort_values("_end_diff", ascending=True)

    if maket_df.empty:
        st.info(
            "По макету нет строк: уровень 5, непустая причина, отклонение окончания < 0. "
            "Ниже — полная выгрузка по текущим фильтрам."
        )
    else:
        with st.expander("Условия отбора по макету", expanded=False):
            st.caption(
                "По макету: уровень 5 MSP, причина отклонения заполнена, отклонение окончания < 0. "
                "Сортировка: по возрастанию отклонения (худшее сверху)."
            )
        _date_bg_m = "rgba(46, 134, 171, 0.22)"
        _tbl_m = [
            '<div class="rendered-table-wrap" style="margin-top:0.5rem">',
            '<table class="rendered-table" style="border-collapse:collapse;width:100%">',
            "<thead><tr>",
        ]
        _hdrs = ["№", "Проект"]
        if "block" in maket_df.columns:
            _hdrs.append("Функциональный блок")
        if building_col and building_col in maket_df.columns:
            _hdrs.append("Строение")
        _hdrs.extend(
            [
                "Базовое окончание",
                "Окончание",
                "Отклонение",
                "Причина отклонения",
                "Заметки",
            ]
        )
        for h in _hdrs:
            _tbl_m.append(f"<th>{html_module.escape(h)}</th>")
        _tbl_m.append("</tr></thead><tbody>")

        for i, (_, rr) in enumerate(maket_df.iterrows(), start=1):
            pr = _clean_display_str(rr.get("project name"))
            fb = (
                _clean_display_str(rr.get("block"))
                if "block" in maket_df.columns
                else ""
            )
            stv = (
                _clean_display_str(rr.get(building_col))
                if building_col and building_col in maket_df.columns
                else ""
            )
            pe = rr.get("plan end")
            fe = rr.get("base end")
            ed = rr.get("_end_diff")
            pe_s = pe.strftime("%d.%m.%Y") if pd.notna(pe) else ""
            fe_s = fe.strftime("%d.%m.%Y") if pd.notna(fe) else ""
            ed_s = ""
            if pd.notna(ed):
                ed_s = str(int(round(float(ed), 0)))
            rs = _clean_display_str(rr.get("reason of deviation"))
            nt = ""
            if notes_col_m and notes_col_m in maket_df.columns:
                nt = _clean_display_str(rr.get(notes_col_m))

            _tbl_m.append("<tr>")
            _tbl_m.append(f"<td>{html_module.escape(str(i))}</td>")
            _tbl_m.append(f"<td>{html_module.escape(pr)}</td>")
            if "block" in maket_df.columns:
                _tbl_m.append(f"<td>{html_module.escape(fb)}</td>")
            if building_col and building_col in maket_df.columns:
                _tbl_m.append(f"<td>{html_module.escape(stv)}</td>")
            _tbl_m.append(
                f'<td style="background:{_date_bg_m}">{html_module.escape(pe_s)}</td>'
            )
            _tbl_m.append(
                f'<td style="background:{_date_bg_m}">{html_module.escape(fe_s)}</td>'
            )
            if pd.isna(ed):
                _tbl_m.append(
                    f'<td style="background:{_date_bg_m}">{html_module.escape("—")}</td>'
                )
            else:
                try:
                    ev = float(ed)
                except (TypeError, ValueError):
                    _tbl_m.append(
                        f'<td style="background:{_date_bg_m}">{html_module.escape(ed_s)}</td>'
                    )
                else:
                    clr = "#c0392b" if ev < 0 else "#27ae60"
                    _tbl_m.append(
                        f'<td style="background:{_date_bg_m};color:{clr};font-weight:600">{html_module.escape(ed_s)}</td>'
                    )
            _tbl_m.append(f"<td>{html_module.escape(rs)}</td>")
            _tbl_m.append(f"<td>{html_module.escape(nt)}</td>")
            _tbl_m.append("</tr>")

        _tbl_m.append("</tbody></table></div>")
        st.markdown(_TABLE_CSS + "".join(_tbl_m), unsafe_allow_html=True)
        st.markdown(f"**Записей (по макету):** {len(maket_df)}")
        _maket_out = []
        for i, (_, rr) in enumerate(maket_df.iterrows(), start=1):
            row = {"№": i, "Проект": _clean_display_str(rr.get("project name"))}
            if "block" in maket_df.columns:
                row["Функциональный блок"] = _clean_display_str(rr.get("block"))
            if building_col and building_col in maket_df.columns:
                row["Строение"] = _clean_display_str(rr.get(building_col))
            pe = rr.get("plan end")
            fe = rr.get("base end")
            ed = rr.get("_end_diff")
            row["Базовое окончание"] = (
                pe.strftime("%d.%m.%Y") if pd.notna(pe) else ""
            )
            row["Окончание"] = fe.strftime("%d.%m.%Y") if pd.notna(fe) else ""
            row["Отклонение"] = (
                int(round(float(ed), 0)) if pd.notna(ed) else ""
            )
            row["Причина отклонения"] = _clean_display_str(
                rr.get("reason of deviation")
            )
            row["Заметки"] = (
                _clean_display_str(rr.get(notes_col_m))
                if notes_col_m and notes_col_m in maket_df.columns
                else ""
            )
            _maket_out.append(row)
        render_dataframe_excel_csv_downloads(
            pd.DataFrame(_maket_out),
            file_stem="deviations_detail_maket",
            key_prefix="devtable_maket",
            csv_label="Скачать CSV (по макету, для Excel)",
        )

    with st.expander("Полная выгрузка по фильтрам", expanded=False):
        st.caption(
            "Ниже — полная таблица по текущим фильтрам и выбранной причине в блоке «Детальные данные» "
            "(не только строки «по макету»). Колонки и цвета — по макету правок (базовые/фактические даты, "
            "отклонения начала и окончания в днях, длительности)."
        )
    _render_deviations_reasons_full_table(table_reason_df, building_col, notes_col_m)


def _deviations_contrast_text_on_fill(fill_hex: str | None) -> str:
    """Цвет подписи внутри сегмента столбца: тёмный на светлой заливке, белый на тёмной."""
    if not fill_hex or not isinstance(fill_hex, str):
        return "#f5f5f5"
    h = fill_hex.strip()
    if not h.startswith("#"):
        return "#f5f5f5"
    h = h[1:]
    try:
        if len(h) == 3:
            r = int(h[0] + h[0], 16)
            g = int(h[1] + h[1], 16)
            b = int(h[2] + h[2], 16)
        elif len(h) == 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        else:
            return "#f5f5f5"
    except ValueError:
        return "#f5f5f5"
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return "#141414" if lum > 0.62 else "#f5f5f5"


# Порядок снизу вверх в стеке (первая категория — нижний сегмент), как в референсе отчёта.
DEVIATIONS_REASON_BUCKET_ORDER: tuple[str, ...] = (
    "Изменение объемов",
    "Изменение расценки",
    "Не передан фронт работ",
    "Переделка за предыдущим подрядчиком",
    "Увеличение сроков по вине подрядчика",
    "Прочее",
)


def _deviations_reason_bucket_colors() -> dict[str, str]:
    """Фиксированные цвета категорий причин (как в референсе отчёта)."""
    return {
        "Изменение объемов": "#cddc39",
        "Изменение расценки": "#fbc02d",
        "Не передан фронт работ": "#26c6da",
        "Переделка за предыдущим подрядчиком": "#8bc34a",
        "Увеличение сроков по вине подрядчика": "#9e9e9e",
        "Прочее": "#e91e63",
    }


def _deviations_reason_bucket_label(raw_reason) -> str:
    """Нормализация свободного текста причины в фиксированные категории легенды."""
    if raw_reason is None or (isinstance(raw_reason, float) and pd.isna(raw_reason)):
        return "Прочее"
    s = str(raw_reason).strip().lower()
    if not s:
        return "Прочее"
    if "измен" in s and "объем" in s:
        return "Изменение объемов"
    if "измен" in s and ("расцен" in s or "стоим" in s or "цен" in s):
        return "Изменение расценки"
    if "не передан фронт" in s or ("фронт" in s and "не передан" in s):
        return "Не передан фронт работ"
    if "переделк" in s:
        return "Переделка за предыдущим подрядчиком"
    if "увеличение срок" in s and "подрядчик" in s:
        return "Увеличение сроков по вине подрядчика"
    return "Прочее"


# ==================== DASHBOARD 2: Dynamics of Deviations ====================
def dashboard_dynamics_of_deviations(df, hide_shared_filters=False):

    if df is None or not hasattr(df, "columns"):
        st.warning(
            "Нет данных для отображения. Пожалуйста, загрузите данные проекта."
        )
        return

    if hide_shared_filters:
        st.subheader("Динамика отклонений по месяцам")
    else:
        st.header("Динамика отклонений по месяцам")

    _time_axis = st.radio(
        "Ось времени",
        [
            "По дате окончания плана (plan end)",
            "По дате снимка выгрузки (snapshot_date)",
        ],
        horizontal=True,
        key="dynamics_time_axis_pravki",
    )
    source_df = df
    if _time_axis.startswith("По дате снимка"):
        snap = st.session_state.get("project_data_all_snapshots")
        if snap is not None and not getattr(snap, "empty", True):
            source_df = snap
        if "snapshot_date" not in getattr(source_df, "columns", []):
            st.warning(
                "Нет колонки snapshot_date. Она задаётся для MSP-файлов вида msp_<проект>_…_<дд-мм-гггг>.csv. "
                "Показана динамика по plan end из текущего набора."
            )
            source_df = df
            _time_axis = "По дате окончания плана (plan end)"

    if hide_shared_filters:
        col1, = st.columns(1)
        with col1:
            period_type = st.selectbox(
                "Группировать по",
                ["День", "Месяц", "Квартал", "Год"],
                key="dynamics_period",
            )
            period_map = {
                "День": "Day",
                "Месяц": "Month",
                "Квартал": "Quarter",
                "Год": "Year",
            }
            period_type_en = period_map.get(period_type, "Month")
    else:
        col1, col2, col3 = st.columns(3)

        with col1:
            period_type = st.selectbox(
                "Группировать по",
                ["День", "Месяц", "Квартал", "Год"],
                key="dynamics_period",
            )
            period_map = {
                "День": "Day",
                "Месяц": "Month",
                "Квартал": "Quarter",
                "Год": "Year",
            }
            period_type_en = period_map.get(period_type, "Month")

        with col2:
            if "project name" in source_df.columns:
                projects = ["Все"] + _project_name_select_options(source_df["project name"])
                selected_project = st.selectbox(
                    "Проект", projects, key="dynamics_project"
                )
            else:
                selected_project = "Все"

        with col3:
            if "reason of deviation" in source_df.columns:
                reasons = ["Все"] + sorted(
                    source_df["reason of deviation"].dropna().unique().tolist()
                )
                selected_reason = st.selectbox(
                    "Причина", reasons, key="dynamics_reason"
                )
            else:
                selected_reason = "Все"

    filtered_df = source_df.copy()
    if not hide_shared_filters:
        if selected_project != "Все" and "project name" in filtered_df.columns:
            filtered_df = filtered_df[
                filtered_df["project name"].map(_project_filter_norm_key)
                == _project_filter_norm_key(selected_project)
            ]
        if selected_reason != "Все" and "reason of deviation" in filtered_df.columns:
            filtered_df = filtered_df[
                filtered_df["reason of deviation"].astype(str).str.strip()
                == str(selected_reason).strip()
            ]

    # Filter tasks: deviation=1/True OR reason of deviation filled
    if "deviation" in filtered_df.columns:
        deviation_flag = (
            (filtered_df["deviation"] == True)
            | (filtered_df["deviation"] == 1)
            | (filtered_df["deviation"].astype(str).str.lower() == "true")
            | (filtered_df["deviation"].astype(str).str.strip() == "1")
        )
    else:
        deviation_flag = pd.Series(False, index=filtered_df.index)
    if "reason of deviation" in filtered_df.columns:
        reason_filled = (
            filtered_df["reason of deviation"].notna()
            & (filtered_df["reason of deviation"].astype(str).str.strip() != "")
        )
    else:
        reason_filled = pd.Series(False, index=filtered_df.index)
    filtered_df = filtered_df[deviation_flag | reason_filled]

    if filtered_df.empty:
        st.info("Нет данных для выбранных фильтров.")
        return

    use_snapshot_period = (
        _time_axis.startswith("По дате снимка")
        and "snapshot_date" in filtered_df.columns
    )
    if use_snapshot_period:
        filtered_df = filtered_df.copy()
        filtered_df["snapshot_date"] = pd.to_datetime(
            filtered_df["snapshot_date"], errors="coerce"
        )
        sd = filtered_df["snapshot_date"]
        if period_type_en == "Day":
            mask = sd.notna()
            filtered_df.loc[mask, "period"] = sd.loc[mask].dt.date
            period_label = "День (дата снимка файла)"
        elif period_type_en == "Month":
            mask = sd.notna()
            filtered_df.loc[mask, "period"] = sd.loc[mask].dt.to_period("M")
            period_label = "Месяц (дата снимка файла)"
        elif period_type_en == "Quarter":
            mask = sd.notna()
            filtered_df.loc[mask, "period"] = sd.loc[mask].dt.to_period("Q")
            period_label = "Квартал (дата снимка файла)"
        else:
            mask = sd.notna()
            filtered_df.loc[mask, "period"] = sd.loc[mask].dt.to_period("Y")
            period_label = "Год (дата снимка файла)"
        if not mask.any():
            st.warning("Нет заполненной snapshot_date после фильтров.")
            return
    # Extract period from plan end dates
    elif period_type_en == "Day":
        # Use date (day level)
        if "plan end" in filtered_df.columns:
            mask = filtered_df["plan end"].notna()
            filtered_df.loc[mask, "period"] = filtered_df.loc[mask, "plan end"].dt.date
            period_label = "День"
        else:
            st.warning("Поле 'plan end' не найдено для группировки по дням.")
            return
    elif period_type_en == "Month":
        if "plan end" in filtered_df.columns:
            mask = filtered_df["plan end"].notna()
            filtered_df.loc[mask, "period"] = filtered_df.loc[
                mask, "plan end"
            ].dt.to_period("M")
            period_label = "Месяц"
        else:
            st.warning("Поле 'plan end' не найдено для группировки по месяцам.")
            return
    elif period_type_en == "Quarter":
        if "plan end" in filtered_df.columns:
            mask = filtered_df["plan end"].notna()
            filtered_df.loc[mask, "period"] = filtered_df.loc[
                mask, "plan end"
            ].dt.to_period("Q")
            period_label = "Квартал"
        else:
            st.warning("Поле 'plan end' не найдено для группировки по кварталам.")
            return
    else:  # Year
        if "plan end" in filtered_df.columns:
            mask = filtered_df["plan end"].notna()
            filtered_df.loc[mask, "period"] = filtered_df.loc[
                mask, "plan end"
            ].dt.to_period("Y")
            period_label = "Год"
        else:
            st.warning("Поле 'plan end' не найдено для группировки по годам.")
            return

    # Filter out rows without period data
    filtered_df = filtered_df[filtered_df["period"].notna()]

    if filtered_df.empty:
        st.info("Нет данных с указанными периодами.")
        return

    # Convert deviation in days to numeric
    if "deviation in days" in filtered_df.columns:
        filtered_df["deviation in days"] = pd.to_numeric(
            filtered_df["deviation in days"], errors="coerce"
        )

    # Group by project, period, and reason - count deviation days
    group_cols = ["period"]
    if "project name" in filtered_df.columns:
        group_cols.append("project name")
    if "reason of deviation" in filtered_df.columns:
        group_cols.append("reason of deviation")

    # Aggregate: count tasks and sum deviation days
    # For average: sum deviation days / number of tasks (grouped by project if project is in group)
    agg_dict = {"deviation": "count"}  # Count tasks
    if "deviation in days" in filtered_df.columns:
        agg_dict["deviation in days"] = "sum"  # Sum deviation days

    grouped_data = filtered_df.groupby(group_cols).agg(agg_dict).reset_index()

    # Ensure period column is preserved as Period type if possible
    # After groupby, Period objects might be converted, so we need to handle this
    if "period" in grouped_data.columns:
        # Try to preserve Period type or convert back if needed
        try:
            # Check if period values are still Period objects
            if isinstance(grouped_data["period"].iloc[0], pd.Period):
                # Period objects are preserved, good
                pass
            else:
                # Try to convert back to Period if they're strings
                try:
                    # Try to convert string representations back to Period
                    def try_convert_to_period(val):
                        if isinstance(val, pd.Period):
                            return val
                        if isinstance(val, str) and "-" in val:
                            try:
                                parts = val.split("-")
                                if len(parts) >= 2:
                                    year = int(parts[0])
                                    month = int(parts[1])
                                    return pd.Period(f"{year}-{month:02d}", freq="M")
                            except:
                                pass
                        return val

                    grouped_data["period"] = grouped_data["period"].apply(
                        try_convert_to_period
                    )
                except:
                    pass
        except:
            pass

    # Calculate average: sum of deviation days / number of tasks
    if "deviation in days" in filtered_df.columns:
        # Rename columns
        if "deviation in days" in grouped_data.columns:
            grouped_data = grouped_data.rename(
                columns={
                    "deviation": "Количество задач",
                    "deviation in days": "Всего дней отклонений",
                }
            )
        else:
            grouped_data = grouped_data.rename(
                columns={"deviation": "Количество задач"}
            )
            grouped_data["Всего дней отклонений"] = 0

        # Calculate average: sum / count of tasks (деление на 0 — в 0 дней задач)
        _cnt = grouped_data["Количество задач"].replace(0, np.nan)
        grouped_data["Среднее дней отклонений"] = (
            grouped_data["Всего дней отклонений"] / _cnt
        ).round(0)
        grouped_data["Среднее дней отклонений"] = grouped_data[
            "Среднее дней отклонений"
        ].fillna(0)
    else:
        grouped_data = grouped_data.rename(columns={"deviation": "Количество задач"})
        grouped_data["Всего дней отклонений"] = 0
        grouped_data["Среднее дней отклонений"] = 0

    def _dynamics_period_sort_key(p):
        """Ключ для хронологической сортировки периода (до format_period_ru)."""
        if p is None:
            return (2, 0)
        try:
            if isinstance(p, float) and pd.isna(p):
                return (2, 0)
        except Exception:
            pass
        if isinstance(p, pd.Period):
            return (0, p.ordinal)
        if isinstance(p, pd.Timestamp):
            try:
                return (0, p.to_period("D").ordinal)
            except Exception:
                return (1, str(p))
        if isinstance(p, date):
            try:
                return (0, pd.Timestamp(p).to_period("D").ordinal)
            except Exception:
                return (1, str(p))
        try:
            ts = pd.Timestamp(p)
            if pd.notna(ts):
                return (0, ts.to_period("D").ordinal)
        except Exception:
            pass
        return (1, str(p))

    grouped_data = grouped_data.sort_values(
        "period", key=lambda s: s.map(_dynamics_period_sort_key)
    ).reset_index(drop=True)
    _period_uniq_sorted = sorted(
        grouped_data["period"].dropna().unique(),
        key=_dynamics_period_sort_key,
    )
    _period_cat_labels = [format_period_ru(x) for x in _period_uniq_sorted]
    grouped_data["period"] = grouped_data["period"].map(format_period_ru)
    try:
        grouped_data["period"] = pd.Categorical(
            grouped_data["period"],
            categories=_period_cat_labels,
            ordered=True,
        )
    except (ValueError, TypeError):
        pass

    # Visualizations
    if len(group_cols) == 1:  # Only period
        col1, col2 = st.columns(2)

        with col1:
            fig = px.bar(
                grouped_data,
                x="period",
                y="Количество задач",
                title=None,
                labels={"period": period_label, "Количество задач": "Количество задач"},
                text="Количество задач",
            )
            fig.update_xaxes(tickangle=-45)
            fig.update_traces(
                textposition="outside", textfont=dict(size=14, color="white")
            )
            fig = _apply_finance_bar_label_layout(fig)
            fig = apply_chart_background(fig)
            render_chart(
                fig,
                caption_below=f"Количество задач с отклонениями по {period_label.lower()}",
            )

        with col2:
            if grouped_data["Всего дней отклонений"].sum() > 0:
                grouped_data = grouped_data.copy()
                grouped_data["_дни_текст"] = grouped_data["Всего дней отклонений"].apply(
                    lambda x: f"{int(round(x, 0))}" if pd.notna(x) else ""
                )
                fig = px.line(
                    grouped_data,
                    x="period",
                    y="Всего дней отклонений",
                    title=None,
                    markers=True,
                    text="_дни_текст",
                )
                fig.update_xaxes(tickangle=-45)
                fig.update_traces(textposition="top center", textfont=dict(color="white"))
                fig = apply_chart_background(fig)
                render_chart(
                    fig,
                    caption_below=f"Всего дней отклонений по {period_label.lower()}",
                )
            else:
                st.info("Нет данных по дням отклонений.")
    else:  # Grouped by project and/or reason
        # Show by project if project is in group
        if "project name" in group_cols:
            st.subheader("По проектам")
            # If reason is also in group_cols, aggregate by period and project only (sum across reasons)
            if "reason of deviation" in group_cols:
                project_data = (
                    grouped_data.groupby(["period", "project name"])
                    .agg({"Всего дней отклонений": "sum", "Количество задач": "sum"})
                    .reset_index()
                )
            else:
                project_data = grouped_data

            project_data = project_data.copy()
            project_data["_дни_текст"] = project_data["Всего дней отклонений"].apply(
                lambda x: f"{int(round(x, 0))}" if pd.notna(x) else ""
            )
            fig = px.bar(
                project_data,
                x="period",
                y="Всего дней отклонений",
                color="project name",
                title=None,
                labels={
                    "period": "Период",
                    "Всего дней отклонений": "Дни отклонений",
                    "project name": "Проект",
                },
                text="_дни_текст",
            )
            # Группировка столбцов: легенда справа, как у «По причинам», чтобы не наезжать на ось X
            fig.update_layout(
                barmode="group",
                legend=dict(
                    title=dict(text="Проект"),
                    orientation="v",
                    yanchor="top",
                    y=1,
                    x=1.02,
                    xanchor="left",
                    font=dict(size=10),
                    traceorder="normal",
                    itemsizing="constant",
                ),
                margin=dict(l=56, r=280, t=28, b=140),
                xaxis=dict(
                    title="",
                    tickangle=-45,
                    tickfont=dict(size=10),
                    automargin=True,
                ),
                yaxis=dict(title="Дни отклонений", automargin=True),
                height=560,
            )
            fig.update_traces(
                textposition="outside",
                textfont=dict(size=12, color="white"),
            )
            fig = _apply_bar_uniformtext(fig)
            fig = apply_chart_background(fig)
            render_chart(fig, caption_below="Дни отклонений по периоду")

        # Show by reason if reason is in group
        if "reason of deviation" in group_cols:
            st.subheader("По причинам")
            # Агрегируем по периоду и причинам; при нескольких проектах — сохраняем «project name» для стека/фасетов
            reason_data = grouped_data.copy()
            reason_data["_reason_bucket"] = reason_data["reason of deviation"].map(
                _deviations_reason_bucket_label
            )
            if "project name" in group_cols:
                reason_data = (
                    reason_data.groupby(
                        ["period", "project name", "_reason_bucket"], observed=False
                    )
                    .agg({"Всего дней отклонений": "sum", "Количество задач": "sum"})
                    .reset_index()
                )
            else:
                reason_data = (
                    reason_data.groupby(["period", "_reason_bucket"], observed=False)
                    .agg({"Всего дней отклонений": "sum", "Количество задач": "sum"})
                    .reset_index()
                )

            _reason_order = list(DEVIATIONS_REASON_BUCKET_ORDER)
            _clr_map = _deviations_reason_bucket_colors()
            _periods_grid = (
                list(_period_cat_labels)
                if _period_cat_labels
                else reason_data["period"].drop_duplicates().tolist()
            )
            _period_x_title = f"Период ({str(period_label).lower()})"
            _n_proj = (
                int(reason_data["project name"].nunique(dropna=True))
                if "project name" in reason_data.columns
                else 0
            )
            _multi_proj = _n_proj > 1

            def _seg_cnt_lbl(v) -> str:
                if pd.isna(v):
                    return ""
                n = int(round(float(v), 0))
                return str(n) if n != 0 else ""

            if not _multi_proj and "project name" in reason_data.columns:
                reason_data = reason_data.drop(columns=["project name"], errors="ignore")

            if not _multi_proj:
                _grid_idx = pd.MultiIndex.from_product(
                    [_periods_grid, _reason_order],
                    names=["period", "_reason_bucket"],
                )
                reason_data = (
                    reason_data.set_index(["period", "_reason_bucket"])
                    .reindex(_grid_idx)
                    .reset_index()
                )
                reason_data["Всего дней отклонений"] = reason_data[
                    "Всего дней отклонений"
                ].fillna(0.0)
                reason_data["Количество задач"] = reason_data["Количество задач"].fillna(
                    0.0
                )

            reason_data["_seg_lbl"] = reason_data["Количество задач"].map(_seg_cnt_lbl)
            try:
                reason_data["period"] = pd.Categorical(
                    reason_data["period"],
                    categories=_periods_grid,
                    ordered=True,
                )
            except (ValueError, TypeError):
                pass

            if _multi_proj:
                _wrap = min(4, max(2, _n_proj))
                fig = px.bar(
                    reason_data,
                    x="period",
                    y="Количество задач",
                    color="_reason_bucket",
                    facet_col="project name",
                    facet_col_wrap=_wrap,
                    title=None,
                    color_discrete_map=_clr_map or None,
                    category_orders={"_reason_bucket": _reason_order},
                    labels={
                        "period": _period_x_title,
                        "Количество задач": "Количество отклонений",
                        "_reason_bucket": "Причина отклонения",
                        "project name": "Проект",
                    },
                    text="_seg_lbl",
                )
                fig.update_layout(
                    barmode="stack",
                    legend=dict(
                        title=dict(text="Причина отклонения"),
                        orientation="v",
                        yanchor="top",
                        y=1,
                        x=1.02,
                        xanchor="left",
                        font=dict(size=10),
                        traceorder="normal",
                        itemsizing="constant",
                    ),
                    margin=dict(l=56, r=280, t=72, b=160),
                    height=min(960, 120 + 320 * max(1, int(np.ceil(_n_proj / float(_wrap))))),
                )
                fig.update_xaxes(tickangle=-45, title=_period_x_title, automargin=True)
                fig.update_yaxes(title="Количество отклонений", automargin=True)
            else:
                fig = px.bar(
                    reason_data,
                    x="period",
                    y="Количество задач",
                    color="_reason_bucket",
                    title=None,
                    color_discrete_map=_clr_map or None,
                    category_orders={"_reason_bucket": _reason_order},
                    labels={
                        "period": _period_x_title,
                        "Количество задач": "Количество отклонений",
                        "_reason_bucket": "Причина отклонения",
                    },
                    text="_seg_lbl",
                )
                fig.update_layout(
                    barmode="stack",
                    legend=dict(
                        title=dict(text="Причина отклонения"),
                        orientation="v",
                        yanchor="top",
                        y=1,
                        x=1.02,
                        xanchor="left",
                        font=dict(size=10),
                        traceorder="normal",
                        itemsizing="constant",
                    ),
                    margin=dict(l=56, r=280, t=40, b=140),
                    xaxis=dict(
                        title=_period_x_title,
                        tickangle=-45,
                        tickfont=dict(size=10),
                        automargin=True,
                    ),
                    yaxis=dict(
                        title="Количество отклонений", automargin=True
                    ),
                    height=580,
                )
            fig.update_traces(
                textposition="inside",
                insidetextanchor="middle",
                textangle=0,
                cliponaxis=False,
            )
            for tr in fig.data:
                if getattr(tr, "type", None) != "bar":
                    continue
                mc = getattr(tr.marker, "color", None)
                if isinstance(mc, str):
                    tc = _deviations_contrast_text_on_fill(mc)
                    tr.update(
                        textfont=dict(color=tc, size=11),
                        insidetextfont=dict(color=tc, size=11),
                    )
                tr.update(
                    hovertemplate=(
                        "<b>%{fullData.name}</b><br>"
                        "%{x}<br>"
                        "Количество: %{y}<extra></extra>"
                    )
                )

            if not _multi_proj:
                tot_period = (
                    reason_data.groupby("period", observed=False)["Количество задач"]
                    .sum()
                    .reset_index()
                )
                for _, row in tot_period.iterrows():
                    v = row["Количество задач"]
                    if pd.isna(v):
                        continue
                    txt = str(int(round(float(v), 0)))
                    x_pos = row["period"]
                    fv = float(v)
                    if fv >= 0:
                        fig.add_annotation(
                            x=x_pos,
                            y=fv,
                            text=f"<b>{txt}</b>",
                            showarrow=False,
                            xref="x",
                            yref="y",
                            xanchor="center",
                            yanchor="bottom",
                            yshift=8,
                            font=dict(color="#f5f5f5", size=12),
                        )
                    else:
                        fig.add_annotation(
                            x=x_pos,
                            y=fv,
                            text=f"<b>{txt}</b>",
                            showarrow=False,
                            xref="x",
                            yref="y",
                            xanchor="center",
                            yanchor="top",
                            yshift=-8,
                            font=dict(color="#f5f5f5", size=12),
                        )

            fig = _apply_bar_uniformtext(fig)
            try:
                fig.update_layout(uniformtext=dict(minsize=4, mode="show"))
            except Exception:
                pass
            fig = apply_chart_background(fig)
            _cap_dyn = (
                "Каждый столбец — период; стек по причинам; при нескольких проектах — отдельная панель на проект. "
                "В сегменте — число отклонений по причине; над столбцом — итог за период (один проект в данных)."
            )
            render_chart(fig, caption_below=_cap_dyn)

    # Summary table
    # If project is in group, show summary grouped by project overall (aggregate across all periods)
    if "project name" in group_cols:
        # Create project-level summary (aggregate across all periods, not by day/period)
        project_summary_cols = ["project name"]
        if "reason of deviation" in group_cols:
            project_summary_cols.append("reason of deviation")

        # Периоды для фильтра — в календарном порядке (как на графике), не по алфавиту строки
        available_periods = []
        if "period" in grouped_data.columns:
            _per_ser = grouped_data["period"]
            if pd.api.types.is_categorical_dtype(_per_ser) and len(_per_ser.dtype.categories):
                available_periods = [str(x) for x in _per_ser.dtype.categories]
            else:
                _present = set(_per_ser.astype(str).dropna().unique().tolist())
                available_periods = [
                    lb for lb in _period_cat_labels if lb in _present
                ]

        st.subheader(
            f"Сводная таблица (группировка: {', '.join(project_summary_cols)})"
        )

        # Добавляем селекторы для фильтрации таблицы
        filter_cols = st.columns(3)
        filtered_df_for_summary = filtered_df.copy()

        with filter_cols[0]:
            if "project name" in filtered_df_for_summary.columns:
                available_projects = ["Все"] + sorted(
                    filtered_df_for_summary["project name"].dropna().unique().tolist()
                )
                selected_project_filter = st.selectbox(
                    "Фильтр по проекту",
                    available_projects,
                    key="summary_project_filter",
                )
                if selected_project_filter != "Все":
                    filtered_df_for_summary = filtered_df_for_summary[
                        filtered_df_for_summary["project name"]
                        == selected_project_filter
                    ]

        with filter_cols[1]:
            if "reason of deviation" in filtered_df_for_summary.columns:
                available_reasons = ["Все"] + sorted(
                    filtered_df_for_summary["reason of deviation"]
                    .dropna()
                    .unique()
                    .tolist()
                )
                selected_reason_filter = st.selectbox(
                    "Фильтр по причине отклонения",
                    available_reasons,
                    key="summary_reason_filter",
                )
                if selected_reason_filter != "Все":
                    filtered_df_for_summary = filtered_df_for_summary[
                        filtered_df_for_summary["reason of deviation"]
                        == selected_reason_filter
                    ]

        with filter_cols[2]:
            # Фильтр по периоду
            period_options = ["Весь период"] + available_periods
            selected_period_filter = st.selectbox(
                "Фильтр по периоду", period_options, key="summary_period_filter"
            )

            # Применяем фильтр по периоду
            if (
                selected_period_filter != "Весь период"
                and "period" in filtered_df_for_summary.columns
            ):
                # Фильтруем по отформатированному периоду
                if "plan end" in filtered_df_for_summary.columns:
                    # Создаем временную колонку с отформатированными периодами для фильтрации
                    filtered_df_for_summary = filtered_df_for_summary.copy()
                    mask = filtered_df_for_summary["plan end"].notna()
                    if period_type_en == "Month":
                        filtered_df_for_summary.loc[mask, "temp_period"] = (
                            filtered_df_for_summary.loc[mask, "plan end"].dt.to_period(
                                "M"
                            )
                        )
                    elif period_type_en == "Quarter":
                        filtered_df_for_summary.loc[mask, "temp_period"] = (
                            filtered_df_for_summary.loc[mask, "plan end"].dt.to_period(
                                "Q"
                            )
                        )
                    elif period_type_en == "Year":
                        filtered_df_for_summary.loc[mask, "temp_period"] = (
                            filtered_df_for_summary.loc[mask, "plan end"].dt.to_period(
                                "Y"
                            )
                        )
                    else:
                        filtered_df_for_summary.loc[mask, "temp_period"] = (
                            filtered_df_for_summary.loc[mask, "plan end"].dt.date
                        )

                    # Форматируем периоды для сравнения
                    filtered_df_for_summary.loc[mask, "temp_period_formatted"] = (
                        filtered_df_for_summary.loc[mask, "temp_period"].apply(
                            format_period_ru
                        )
                    )
                    # Фильтруем по выбранному периоду
                    period_mask = (
                        filtered_df_for_summary["temp_period_formatted"]
                        == selected_period_filter
                    )
                    filtered_df_for_summary = filtered_df_for_summary[period_mask]
                    # Удаляем временные колонки
                    filtered_df_for_summary = filtered_df_for_summary.drop(
                        columns=["temp_period", "temp_period_formatted"],
                        errors="ignore",
                    )

        # Aggregate by project (and reason if present) - sum across selected periods
        project_summary = (
            filtered_df_for_summary.groupby(project_summary_cols)
            .agg(
                {
                    "deviation": "count",  # Count tasks
                    "deviation in days": (
                        "sum"
                        if "deviation in days" in filtered_df_for_summary.columns
                        else "count"
                    ),
                }
            )
            .reset_index()
        )

        # Rename columns
        period_col_name = (
            f"Дни отклонений ({selected_period_filter})"
            if selected_period_filter != "Весь период"
            else "Всего дней отклонений"
        )
        col_ru_summary = {
            "deviation": "Количество отклонений",
            "deviation in days": period_col_name,
            "project name": "Проект",
            "reason of deviation": "Причина отклонений",
        }
        project_summary = project_summary.rename(
            columns={c: col_ru_summary[c] for c in project_summary.columns if c in col_ru_summary}
        )

        # Если нет данных по дням отклонений, добавляем нулевую колонку
        if period_col_name not in project_summary.columns:
            project_summary[period_col_name] = 0

        # Sort by total deviation days (descending)
        if period_col_name in project_summary.columns:
            project_summary = project_summary.sort_values(
                period_col_name, ascending=False
            )

        # Строка "Итого": для колонок группировки (после переименования — Проект, Причина отклонений)
        total_row = {}
        for col in project_summary.columns:
            if col in ("Проект", "Причина отклонений"):
                total_row[col] = "Итого"
            elif col == "Количество отклонений":
                total_row[col] = round(project_summary[col].sum(), 0)
            elif col == period_col_name:
                total_row[col] = round(project_summary[col].sum(), 0)
            else:
                total_row[col] = ""

        # Создаем DataFrame для строки "Итого"
        total_df = pd.DataFrame([total_row])
        # Объединяем с основным DataFrame
        project_summary = pd.concat([project_summary, total_df], ignore_index=True)

        # Отображение дней целыми числами (без дробной части, без значения после точки)
        if period_col_name in project_summary.columns:
            def _fmt_days(x):
                if pd.isna(x): return x
                if str(x).strip() == "Итого": return x
                try: return int(round(float(x), 0))
                except (TypeError, ValueError): return x
            project_summary[period_col_name] = project_summary[period_col_name].apply(_fmt_days)

        st.caption(f"Записей: {len(project_summary)}")
        _render_html_table(project_summary)
        render_dataframe_excel_csv_downloads(
            project_summary,
            file_stem="project_summary",
            key_prefix="proj_summary",
        )
    else:
        # No project in group, show regular summary by period (только количество, без дней)
        group_desc = [period_label] + [c for c in group_cols if c != "period"]
        st.subheader(f"Сводная таблица (группировка: {', '.join(group_desc)})")
        table_cols = ["period", "Количество задач"]
        table_cols.extend([c for c in grouped_data.columns if c not in ("period", "Количество задач", "Всего дней отклонений", "Среднее дней отклонений")])
        display_grouped = grouped_data[[c for c in table_cols if c in grouped_data.columns]].copy()
        display_grouped = display_grouped.rename(columns={
            "period": "Период",
            "project name": "Проект",
            "reason of deviation": "Причина отклонений",
        })
        st.caption(f"Записей: {len(display_grouped)}")
        _render_html_table(display_grouped)
        render_dataframe_excel_csv_downloads(
            display_grouped,
            file_stem="grouped_summary",
            key_prefix="grouped_summary",
        )


# ==================== DASHBOARD 3: Plan/Fact Dates for Tasks ====================
def dashboard_plan_fact_dates(df):
    st.header("Отклонение от базового плана")
    if df is None or not hasattr(df, "columns") or df.empty:
        st.warning("Нет данных для отображения. Загрузите файл с задачами MSP.")
        return

    # Ручная загрузка (data_loader) раньше не создавала level structure — без этого L2/L3 не работают.
    ensure_msp_hierarchy_columns(df)

    with st.expander("Откуда берутся сроки и почему таблицы могут отличаться", expanded=False):
        st.markdown(
            """
**Таблица «Отклонение от базового плана (таблица)»** строится **по строкам задач** из выгрузки MSP после ваших фильтров
(проект, функциональный блок, строение, уровень и т.д.). В ячейках — **базовые (плановые) и фактические даты** из колонок вроде
`plan start` / `plan end` / `base start` / `base end` (или русских аналогов); отклонения в днях считаются из этих дат.

**Задача для расчёта окончания проекта** (для связанных отчётов) задаётся в **админке** — ключ `baseline_plan_task_for_metrics`.

**ЗОС** — отдельная узкая таблица: только задачи, в названии которых есть ЗОС / «заключение о соответствии».

**Режим «Ковенанты»**: узкая таблица ковенантов сортируется по отклонению окончания; **полная таблица по всем задачам** спрятана
в развёртку ниже, чтобы не дублировать строки ковенантов.
            """
        )

    # Helper function to find columns by partial match
    def find_column(df, possible_names):
        """Find column by possible names"""
        for col in df.columns:
            # Normalize column name: remove newlines, extra spaces, normalize case
            col_normalized = str(col).replace("\n", " ").replace("\r", " ").strip()
            col_lower = col_normalized.lower()

            for name in possible_names:
                name_lower = name.lower().strip()
                # Exact match (case insensitive)
                if name_lower == col_lower:
                    return col
                # Substring match
                if name_lower in col_lower or col_lower in name_lower:
                    return col
                # Check if all key words from name are in column
                name_words = [w for w in name_lower.split() if len(w) > 2]
                if name_words and all(word in col_lower for word in name_words):
                    return col
        return None

    dates_building_col = _find_column_by_keywords(
        df, ("building", "строение", "лот", "lot", "bldg")
    )
    dates_pct_col = _find_first_column_matching_keywords(
        df,
        (
            "percent complete",
            "pct complete",
            "% complete",
            "процент выполн",
            "процент_заверш",
            "% выполн",
            "% заверш",
            "физический %",
            "выполн",
            "complete",
            "percent",
        ),
    )
    if dates_pct_col is None:
        dates_pct_col = find_column(
            df,
            [
                "pct complete",
                "% complete",
                "percent complete",
                "% выполнения",
                "Процент выполнения",
                "Процент_завершения",
                "процент заверш",
            ],
        )
    dates_pct_col_resolved = dates_pct_col or find_column(
        df,
        [
            "pct complete",
            "percent complete",
            "Процент_завершения",
            "Процент завершения",
            "% выполнения",
        ],
    )
    dates_notes_col = _find_column_by_keywords(
        df, ("note", "заметк", "comment", "remark", "notes")
    )
    dates_lot_col = _find_column_by_keywords(df, ("lot", "лот", "LOT"))
    # Иерархия MSP: предпочтительно outline (level structure), см. web_loader._fill_section_from_task_tree
    plan_fact_dates_outline_col = _dev_tasks_resolve_level_column(df)
    if plan_fact_dates_outline_col is None and "level structure" in df.columns:
        plan_fact_dates_outline_col = "level structure"
    if plan_fact_dates_outline_col is None and "level" in df.columns:
        plan_fact_dates_outline_col = "level"

    st.markdown("**Фильтры**")
    _flt_css = """
        <style>
        div[data-testid="column"] {
            flex: 1 1 0% !important;
            min-width: 0 !important;
        }
        </style>
    """
    st.markdown(_flt_css, unsafe_allow_html=True)

    fl_main1, fl_main2, fl_main3, fl_main4 = st.columns(4)
    with fl_main1:
        if "project name" in df.columns:
            _session_reset_project_if_excluded("dates_project")
            projects = ["Все"] + _project_name_select_options(df["project name"])
            selected_project = st.selectbox(
                "Проект",
                projects,
                key="dates_project",
                help="Фильтр по проекту из выгрузки MSP.",
            )
        else:
            selected_project = "Все"

    pf_dates_proj_df = df.copy()
    if selected_project != "Все" and "project name" in pf_dates_proj_df.columns:
        pf_dates_proj_df = pf_dates_proj_df[
            pf_dates_proj_df["project name"].map(_project_filter_norm_key)
            == _project_filter_norm_key(selected_project)
        ]
    pf_dates_proj_df = pf_dates_proj_df.reset_index(drop=True)
    pf_dates_level_col = _dev_tasks_resolve_level_column(pf_dates_proj_df)
    pf_dates_task_col = (
        "task name"
        if "task name" in pf_dates_proj_df.columns
        else find_column(
            pf_dates_proj_df,
            ["Задача", "task", "Task Name", "Название"],
        )
    )
    pf_dates_work_proj = _dev_tasks_build_ancestor_keys(
        pf_dates_proj_df, pf_dates_level_col, pf_dates_task_col
    )
    # Второй и третий ярусы в выгрузке (часто 2 и 3; иначе — по фактическим уровням в файле).
    pf_dates_blk_tier, pf_dates_bld_tier = 2, 3
    if pf_dates_level_col and pf_dates_level_col in pf_dates_work_proj.columns:
        _pf_lv_s = _dev_outline_level_numeric(
            pf_dates_work_proj[pf_dates_level_col]
        )
        pf_dates_blk_tier, pf_dates_bld_tier = _deviations_msp_tier_levels(_pf_lv_s)

    selected_block_dates = "Все"
    selected_building_dates = "Все"
    pf_dates_block_filter_mode = "none"  # l2 | section | block
    with fl_main2:
        hierarchy_ok = (
            bool(pf_dates_level_col)
            and bool(pf_dates_task_col)
            and pf_dates_level_col in pf_dates_work_proj.columns
        )
        l2_names: list = []
        if hierarchy_ok:
            _ln_b = _dev_outline_level_numeric(
                pf_dates_work_proj[pf_dates_level_col]
            )
            l2_names = sorted(
                pf_dates_work_proj.loc[
                    _ln_b == float(pf_dates_blk_tier), pf_dates_task_col
                ]
                .dropna()
                .astype(str)
                .str.strip()
                .unique()
                .tolist()
            )
            l2_names = [x for x in l2_names if x]
            # Если в строках с номинальным ур. «блока» нет имён (часто у суммарных),
            # берём ключи предка ур.2 из обхода дерева — по ним же фильтруется таблица.
            if not l2_names and "_dt_lvl2_key" in pf_dates_work_proj.columns:
                _k2 = (
                    pf_dates_work_proj["_dt_lvl2_key"]
                    .astype(str)
                    .str.strip()
                )
                _k2 = _k2[_k2.ne("") & _k2.str.lower().ne("nan")]
                if len(_k2):
                    l2_names = sorted(pd.unique(_k2).tolist())

        if l2_names:
            pf_dates_block_filter_mode = "l2"
            blks = ["Все"] + l2_names
            selected_block_dates = st.selectbox(
                "Функциональный блок",
                blks,
                key="dates_block_l2",
                help=(
                    "Список — названия задач яруса «функциональный блок» (в типичной выгрузке MSP это уровень 2). "
                    f"В текущем файле этот ярус по колонке уровня: {pf_dates_blk_tier}. "
                    "Порядок строк в выгрузке задаёт иерархию."
                ),
            )
        elif "section" in pf_dates_proj_df.columns:
            _sec = pf_dates_proj_df["section"].dropna().astype(str).map(str.strip)
            _sec = _sec[_sec.ne("") & _sec.str.lower().ne("nan")]
            _uniq = sorted(pd.unique(_sec)) if len(_sec) else []
            if _uniq:
                pf_dates_block_filter_mode = "section"
                blks = ["Все"] + list(_uniq)
                selected_block_dates = st.selectbox(
                    "Функциональный блок",
                    blks,
                    key="dates_block_section",
                    help=(
                        "В выгрузке нет непустого списка задач ур.2 по иерархии — фильтр по колонке «Раздел» (section). "
                        "Для MSP из web/ после обхода дерева section обычно совпадает с родителем ур.2."
                    ),
                )
            elif "block" in pf_dates_proj_df.columns:
                pf_dates_block_filter_mode = "block"
                blks = ["Все"] + sorted(
                    pf_dates_proj_df["block"]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .unique()
                    .tolist()
                )
                selected_block_dates = st.selectbox(
                    "Функциональный блок",
                    blks,
                    key="dates_block",
                    help="Колонка block в выгрузке (иерархия MSP и раздел не дали списка).",
                )
            else:
                selected_block_dates = "Все"
        elif "block" in pf_dates_proj_df.columns:
            pf_dates_block_filter_mode = "block"
            blks = ["Все"] + sorted(
                pf_dates_proj_df["block"]
                .dropna()
                .astype(str)
                .str.strip()
                .unique()
                .tolist()
            )
            selected_block_dates = st.selectbox(
                "Функциональный блок",
                blks,
                key="dates_block",
                help="Колонка block в выгрузке (колонка уровня MSP не найдена или нет задач ур.2).",
            )
        else:
            selected_block_dates = "Все"
    with fl_main3:
        if (
            pf_dates_level_col
            and pf_dates_task_col
            and pf_dates_level_col in pf_dates_work_proj.columns
        ):
            _ln_g = _dev_outline_level_numeric(
                pf_dates_work_proj[pf_dates_level_col]
            )
            w3_pf = pf_dates_work_proj[
                _ln_g == float(pf_dates_bld_tier)
            ].copy()
            if selected_block_dates != "Все":
                w3_pf = w3_pf[
                    w3_pf["_dt_lvl2_key"].astype(str).str.strip()
                    == str(selected_block_dates).strip()
                ]
            _go = sorted(
                w3_pf[pf_dates_task_col]
                .dropna()
                .astype(str)
                .str.strip()
                .unique()
                .tolist()
            )
            _go = [x for x in _go if x]
            if not _go and selected_block_dates != "Все" and "_dt_lvl3_key" in w3_pf.columns:
                _k3pf = w3_pf["_dt_lvl3_key"].astype(str).str.strip()
                _k3pf = _k3pf[_k3pf.ne("") & _k3pf.str.lower().ne("nan")]
                if len(_k3pf):
                    _go = sorted(pd.unique(_k3pf).tolist())
            bopts = ["Все"] + _go
            selected_building_dates = st.selectbox(
                "Строение",
                bopts,
                key="dates_building_l3",
                help="Задачи уровня 3 в выбранном функциональном блоке.",
            )
        elif dates_building_col and dates_building_col in pf_dates_proj_df.columns:
            bopts = ["Все"] + sorted(
                pf_dates_proj_df[dates_building_col]
                .dropna()
                .astype(str)
                .str.strip()
                .unique()
                .tolist()
            )
            selected_building_dates = st.selectbox(
                "Строение",
                bopts,
                key="dates_building",
                help="Колонка строения в выгрузке (иерархия ур. 3 недоступна).",
            )
        else:
            selected_building_dates = "Все"
    with fl_main4:
        _lvl_opts_tz = [
            "Уровень 4 (укрупнённо)",
            "Уровень 5 (детально)",
        ]
        if plan_fact_dates_outline_col and plan_fact_dates_outline_col in df.columns:
            _legacy_lvl = st.session_state.get("dates_level")
            if _legacy_lvl in (
                "Сводные (1–3 ур.)",
                "Все уровни",
                "Укрупнённо (уровень 4)",
            ):
                st.session_state["dates_level"] = _lvl_opts_tz[0]
            elif _legacy_lvl in ("Детально (уровень 5)", "Уровень 5 (детально)"):
                st.session_state["dates_level"] = _lvl_opts_tz[1]
            elif _legacy_lvl not in _lvl_opts_tz:
                st.session_state["dates_level"] = _lvl_opts_tz[0]
            selected_level = st.selectbox(
                "Детализация",
                _lvl_opts_tz,
                index=0,
                key="dates_level",
                help=(
                    "Укрупнённо — задачи уровня 4 MSP; детально — уровень 5. "
                    f"Колонка уровня: {plan_fact_dates_outline_col}."
                ),
            )
        else:
            selected_level = st.selectbox(
                "Детализация",
                _lvl_opts_tz,
                index=0,
                key="dates_level",
                disabled=True,
                help="Нет колонки уровня MSP в выгрузке — фильтр по уровню 4/5 недоступен.",
            )

    st.markdown("**Параметры отображения**")
    _pct_ok = bool(
        dates_pct_col_resolved and str(dates_pct_col_resolved).strip() in df.columns
    )
    if not _pct_ok and dates_pct_col:
        _pct_ok = bool(str(dates_pct_col).strip() in df.columns)
    cb_c1, cb_c2, cb_c3, cb_c4 = st.columns(4)
    with cb_c1:
        dates_show_reason_notes = st.checkbox(
            "Показать причины отклонений",
            value=True,
            key="dates_show_reason_notes",
            help="Добавить в таблицу колонки «Причина отклонения» и «Заметки», если они есть в выгрузке.",
        )
    with cb_c2:
        _hide_done_help = (
            "Скрыть задачи со 100% выполнения по числовой колонке процента из MSP "
            f"({dates_pct_col_resolved or 'не найдена'})."
        )
        if not _pct_ok:
            _hide_done_help += " Колонка процента не найдена — при включении фильтр не применится."
        hide_completed_dates = st.checkbox(
            "Скрыть завершённые (100%)",
            value=False,
            key="dates_hide_done",
            disabled=False,
            help=_hide_done_help,
        )
    with cb_c3:
        only_negative_dev_dates = st.checkbox(
            "Показывать только диаграммы, где отклонение окончания < 0",
            value=False,
            key="dates_only_neg_end",
            help=(
                "Для графиков ниже: оставить только строки, где отклонение окончания "
                "(base end − plan end) < 0. На основную таблицу не распространяется."
            ),
        )
    with cb_c4:
        if dates_lot_col:
            task_label_mode = st.radio(
                "Подписи на графике и в таблице",
                ("По наименованию MSP", "По лоту"),
                horizontal=True,
                key="dates_task_label_mode",
                help="«По лоту» — в графике и в колонке «Задача» таблицы показывается лот (если заполнен в выгрузке).",
            )
        else:
            task_label_mode = "По наименованию MSP"
            st.caption("Колонка лота не найдена — подписи только по наименованию MSP.")

    if pf_dates_block_filter_mode == "section":
        st.caption(
            "Иерархия MSP не дала списка задач ур.2 — «Функциональный блок» фильтрует по колонке «Раздел» (section)."
        )
    elif pf_dates_block_filter_mode == "block":
        st.caption(
            "В данных нет пригодной иерархии MSP для ур.2 — список из колонки «Блок». "
            "Для настоящих задач ур.2 добавьте в файл «Уровень_структуры»/«Уровень» и «Название задачи»."
        )
    elif not (pf_dates_level_col and pf_dates_task_col):
        st.caption(
            "Колонка уровня MSP или имя задачи не найдены — «Строение» заполняется из колонок выгрузки (если есть)."
        )

    st.markdown("**Таблица**")
    d3a = st.columns(1)[0]
    with d3a:
        dates_value_type = st.selectbox(
            "Тип значения",
            ["Даты (план/факт)", "Отклонение (дней)"],
            index=0,
            key="dates_value_type",
            help="Макет: даты или акцент на отклонениях в днях в итоговой таблице.",
        )

    tbl_opt1, tbl_opt2, tbl_opt3 = st.columns(3)
    with tbl_opt1:
        tbl_show_end = st.checkbox(
            "Таблица: отклонение окончания",
            value=True,
            key="dates_tbl_end",
            help="Столбец «Отклонение окончания» (дней): фактическое окончание минус плановое.",
        )
    with tbl_opt2:
        tbl_show_start = st.checkbox(
            "Таблица: отклонение начала",
            value=True,
            key="dates_tbl_start",
        )
    with tbl_opt3:
        tbl_show_dur = st.checkbox(
            "Таблица: отклонение длительности",
            value=False,
            key="dates_tbl_dur",
        )

    # По ТЗ в таблице показываем только строки, где есть отклонение (|дней| > 0) по началу или окончанию.

    # Apply filters
    filtered_df = df.copy()
    if selected_project != "Все" and "project name" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["project name"].astype(str).str.strip()
            == str(selected_project).strip()
        ]
    filtered_df = filtered_df.reset_index(drop=True)
    _pf_lvl_col = _dev_tasks_resolve_level_column(filtered_df)
    _pf_task_col = (
        "task name"
        if "task name" in filtered_df.columns
        else find_column(
            filtered_df,
            ["Задача", "task", "Task Name", "Название"],
        )
    )
    _pf_work = _dev_tasks_build_ancestor_keys(filtered_df, _pf_lvl_col, _pf_task_col)
    for _c in ("_dt_lvl2_key", "_dt_lvl3_key", "_dt_lvl_num"):
        filtered_df[_c] = _pf_work[_c].to_numpy()

    if selected_block_dates != "Все":
        if (
            pf_dates_block_filter_mode == "l2"
            and _pf_lvl_col
            and _pf_task_col
            and "_dt_lvl2_key" in filtered_df.columns
        ):
            filtered_df = filtered_df[
                filtered_df["_dt_lvl2_key"].astype(str).str.strip()
                == str(selected_block_dates).strip()
            ]
        elif pf_dates_block_filter_mode == "section" and "section" in filtered_df.columns:
            filtered_df = filtered_df[
                filtered_df["section"].astype(str).str.strip()
                == str(selected_block_dates).strip()
            ]
        elif pf_dates_block_filter_mode == "block" and "block" in filtered_df.columns:
            filtered_df = filtered_df[
                filtered_df["block"].astype(str).str.strip()
                == str(selected_block_dates).strip()
            ]
    if selected_building_dates != "Все":
        if (
            _pf_lvl_col
            and _pf_task_col
            and "_dt_lvl3_key" in filtered_df.columns
        ):
            filtered_df = filtered_df[
                filtered_df["_dt_lvl3_key"].astype(str).str.strip()
                == str(selected_building_dates).strip()
            ]
        elif (
            dates_building_col
            and dates_building_col in filtered_df.columns
        ):
            filtered_df = filtered_df[
                filtered_df[dates_building_col].astype(str).str.strip()
                == str(selected_building_dates).strip()
            ]
    # Фильтр по уровню иерархии (макет: сводные 1–3, верхний 4, детальный 5)
    _mask_lvl_col = plan_fact_dates_outline_col
    if _mask_lvl_col is None or _mask_lvl_col not in filtered_df.columns:
        if "level structure" in filtered_df.columns:
            _mask_lvl_col = "level structure"
        elif "level" in filtered_df.columns:
            _mask_lvl_col = "level"
    if _mask_lvl_col and _mask_lvl_col in filtered_df.columns:
        level_num = pd.to_numeric(filtered_df[_mask_lvl_col], errors="coerce")
        if selected_level == "Сводные (1–3 ур.)":
            mask_level = level_num.notna() & (level_num <= 3)
            if mask_level.any():
                filtered_df = filtered_df[mask_level]
        elif selected_level in (
            "Уровень 4 (верхний)",
            "Укрупнённо (уровень 4)",
            "Уровень 4 (укрупнённо)",
        ):
            filtered_df = filtered_df[level_num == 4]
        elif selected_level in (
            "Уровень 5 (детальный)",
            "Детально (уровень 5)",
            "Уровень 5 (детально)",
        ):
            filtered_df = filtered_df[level_num == 5]

    if filtered_df.empty:
        st.info("Нет данных для выбранных фильтров.")
        return

    ensure_date_columns(filtered_df)
    # Prepare data for visualization - compare plan and fact dates
    # First, ensure all dates are datetime objects
    date_cols = ["plan start", "plan end", "base start", "base end"]
    for col in date_cols:
        if col in filtered_df.columns:
            filtered_df[col] = pd.to_datetime(
                filtered_df[col], errors="coerce", dayfirst=True
            )

    missing_date_cols = [col for col in date_cols if col not in filtered_df.columns]
    if missing_date_cols:
        st.warning(f"Отсутствуют необходимые колонки с датами: {', '.join(missing_date_cols)}")
        return

    # Filter to rows that have at least plan OR fact dates (not necessarily both)
    has_plan_dates = filtered_df["plan start"].notna() & filtered_df["plan end"].notna()
    has_fact_dates = filtered_df["base start"].notna() & filtered_df["base end"].notna()
    has_any_dates = has_plan_dates | has_fact_dates
    # .copy() обязателен для pandas 2.x (CoW): избегаем присвоений в slice/view
    filtered_df = filtered_df[has_any_dates].copy()

    if filtered_df.empty:
        st.info("Нет задач с плановыми или фактическими датами для выбранных фильтров.")
        return

    # Перевычисляем маски: начало и конец считаются отдельно, если есть обе даты пары
    both_starts = (
        filtered_df["plan start"].notna() & filtered_df["base start"].notna()
    )
    both_ends = filtered_df["plan end"].notna() & filtered_df["base end"].notna()

    filtered_df["plan_start_diff"] = np.nan
    filtered_df["plan_end_diff"] = np.nan
    filtered_df["total_diff_days"] = 0.0

    if both_starts.any():
        filtered_df.loc[both_starts, "plan_start_diff"] = (
            filtered_df.loc[both_starts, "base start"]
            - filtered_df.loc[both_starts, "plan start"]
        ).dt.total_seconds() / 86400
    if both_ends.any():
        filtered_df.loc[both_ends, "plan_end_diff"] = (
            filtered_df.loc[both_ends, "base end"]
            - filtered_df.loc[both_ends, "plan end"]
        ).dt.total_seconds() / 86400

    has_end = filtered_df["plan_end_diff"].notna()
    filtered_df.loc[has_end, "total_diff_days"] = filtered_df.loc[
        has_end, "plan_end_diff"
    ].abs()
    only_start = (~has_end) & filtered_df["plan_start_diff"].notna()
    filtered_df.loc[only_start, "total_diff_days"] = filtered_df.loc[
        only_start, "plan_start_diff"
    ].abs()

    pct_col_live = dates_pct_col_resolved
    if pct_col_live is None or pct_col_live not in filtered_df.columns:
        pct_col_live = find_column(
            filtered_df,
            [
                "pct complete",
                "percent complete",
                "Процент_завершения",
                "Процент завершения",
                "% выполнения",
                "% complete",
                "percent",
            ],
        )
    if pct_col_live is None or pct_col_live not in filtered_df.columns:
        pct_col_live = _find_first_column_matching_keywords(
            filtered_df,
            (
                "percent complete",
                "pct complete",
                "% complete",
                "процент выполн",
                "процент_заверш",
                "% выполн",
                "% заверш",
                "физический %",
                "выполн",
                "complete",
                "percent",
            ),
        )
    if hide_completed_dates and pct_col_live and pct_col_live in filtered_df.columns:
        _pct_raw = _safe_df_column_series(filtered_df, pct_col_live)
        if _pct_raw is not None:
            _pct = _parse_msp_percent_complete_series(_pct_raw).reindex(
                filtered_df.index
            )
            # Явные 100% (и «1» как доля) скрываем; пустые/нечисловые оставляем.
            filtered_df = filtered_df.loc[
                _pct.isna() | (_pct < 99.9995)
            ].copy()

    df_after_hide = filtered_df.copy()
    if df_after_hide.empty:
        st.info("Нет данных после фильтра «Скрыть завершённые».")
        return

    if task_label_mode == "По лоту" and dates_lot_col and dates_lot_col in df_after_hide.columns:
        _lc = df_after_hide[dates_lot_col].astype(str).str.strip()
        _lot_mask = df_after_hide[dates_lot_col].notna() & _lc.ne("") & _lc.str.lower().ne("nan")
        df_after_hide = df_after_hide[_lot_mask].copy()
        if df_after_hide.empty:
            st.info("Нет строк с заполненным лотом для выбранных фильтров.")
            return

    chart_df = df_after_hide.copy()
    if only_negative_dev_dates:
        chart_df = chart_df[
            chart_df["plan_end_diff"].notna()
            & (chart_df["plan_end_diff"] < 0)
        ]

    table_df = df_after_hide.copy()
    _end = pd.to_numeric(table_df.get("plan_end_diff"), errors="coerce")
    _start = pd.to_numeric(table_df.get("plan_start_diff"), errors="coerce")
    _has_dev = (_end.notna() & (_end.abs() > 1e-9)) | (_start.notna() & (_start.abs() > 1e-9))
    table_df = table_df[_has_dev].copy()

    if chart_df.empty and table_df.empty:
        st.info(
            "Нет строк с отклонением (|Δ| > 0 по началу или окончанию) для таблицы "
            "или нет данных для графика при включённом фильтре «только отрицательное отклонение»."
        )
        return

    # filtered_df — выборка для графиков (учитывает «< 0»); основная таблица — из table_df.
    filtered_df = chart_df.sort_values("task name", ascending=True)

    def _sanitize_eng_networks(s):
        if s is None or (isinstance(s, float) and pd.isna(s)):
            return ""
        t = str(s).strip()
        return re.sub(
            r"(?i)(инженерн[а-яё]*\s+сет[а-яё]*)\s*№\s*[12]\b",
            r"\1",
            t,
        ).strip()

    def _bar_task_label_from_row(row, task_name):
        if task_label_mode == "По лоту" and dates_lot_col and dates_lot_col in row.index:
            lv = row.get(dates_lot_col)
            if pd.notna(lv) and str(lv).strip() not in ("", "nan", "None"):
                return _sanitize_eng_networks(f"Лот {str(lv).strip()}")
        return _sanitize_eng_networks(str(task_name).strip() if task_name is not None else "")

    plan_start_col = "plan start" if "plan start" in filtered_df.columns else find_column(filtered_df, ["Старт План", "План Старт"])
    plan_end_col = "plan end" if "plan end" in filtered_df.columns else find_column(filtered_df, ["Конец План", "План Конец"])
    base_start_col = "base start" if "base start" in filtered_df.columns else find_column(filtered_df, ["Старт Факт", "Факт Старт"])
    base_end_col = "base end" if "base end" in filtered_df.columns else find_column(filtered_df, ["Конец Факт", "Факт Конец"])
    if not all([plan_start_col, plan_end_col, base_start_col, base_end_col]):
        st.warning("Не найдены колонки с датами (план/факт).")
        return

    # Prepare data for Gantt chart - compare plan vs fact
    viz_data = []
    for idx, row in filtered_df.iterrows():
        task_name = row.get("task name", "Неизвестно")
        project_name = row.get("project name", "Неизвестно")
        _disp = _bar_task_label_from_row(row, task_name)

        plan_start = row.get(plan_start_col)
        plan_end = row.get(plan_end_col)
        base_start = row.get(base_start_col)
        base_end = row.get(base_end_col)
        diff_days = row.get("total_diff_days", 0)

        # Add plan dates
        if pd.notna(plan_start) and pd.notna(plan_end):
            viz_data.append(
                {
                    "Task": f"{_disp} ({project_name})",
                    "Task_Original": task_name,
                    "Project": project_name,
                    "Start": plan_start,
                    "End": plan_end,
                    "Type": "План",
                    "Duration": (plan_end - plan_start).total_seconds() / 86400,
                    "Diff_Days": diff_days,
                }
            )

        # Add fact dates
        if pd.notna(base_start) and pd.notna(base_end):
            viz_data.append(
                {
                    "Task": f"{_disp} ({project_name})",
                    "Task_Original": task_name,
                    "Project": project_name,
                    "Start": base_start,
                    "End": base_end,
                    "Type": "Факт",
                    "Duration": (base_end - base_start).total_seconds() / 86400,
                    "Diff_Days": diff_days,
                }
            )

    if not viz_data:
        st.info("Нет валидных данных по датам.")
        return

    viz_df = pd.DataFrame(viz_data)

    # Sort tasks by difference (largest first) - maintain order from filtered_df
    task_order = filtered_df.sort_values("total_diff_days", ascending=False)[
        "task name"
    ].tolist()
    # Create a mapping for sorting
    task_order_map = {task: idx for idx, task in enumerate(task_order)}
    viz_df["sort_order"] = viz_df["Task_Original"].map(task_order_map).fillna(999)
    viz_df = viz_df.sort_values("sort_order")

    # Gantt chart - use proper timeline visualization with plotly express
    # Prepare data for bar chart - plan and fact side by side for each task
    # Порядок строк: по убыванию |отклонение окончания| (ТЗ: крупные отклонения сверху на графике)
    bar_data = []
    _ord = filtered_df.copy()
    _ord["_abs_end_dev"] = pd.to_numeric(_ord["plan_end_diff"], errors="coerce").abs()
    unique_tasks = (
        _ord.sort_values(["_abs_end_dev", "total_diff_days"], ascending=[False, False], na_position="last")
        .drop_duplicates(subset=["task name"], keep="first")["task name"]
        .tolist()
    )
    for task_name in unique_tasks:
        task_rows = filtered_df[filtered_df["task name"] == task_name]
        if task_rows.empty:
            continue

        # If "Все" projects, show each task for each project separately
        if selected_project == "Все":
            for _, row in task_rows.iterrows():
                project_name = row.get("project name", "Неизвестно")
                _tl = _bar_task_label_from_row(row, task_name)
                display_name = f"{_tl} ({project_name})"
                diff_days = row.get("total_diff_days", 0)

                plan_start = row.get("plan start")
                plan_end = row.get("plan end")
                base_start = row.get("base start")
                base_end = row.get("base end")

                # Этап (section) для оси X
                section_name = row.get("section", "—")
                if pd.isna(section_name) or str(section_name).strip() == "":
                    section_name = "—"

                # Add plan entry
                if pd.notna(plan_start) and pd.notna(plan_end):
                    bar_data.append(
                        {
                            "Задача": display_name,
                            "Этап": section_name,
                            "Тип": "План",
                            "Дата начала": plan_start,
                            "Дата окончания": plan_end,
                            "Длительность": (plan_end - plan_start).total_seconds() / 86400,
                            "Отклонение": diff_days,
                        }
                    )

                # Add fact entry
                if pd.notna(base_start) and pd.notna(base_end):
                    bar_data.append(
                        {
                            "Задача": display_name,
                            "Этап": section_name,
                            "Тип": "Факт",
                            "Дата начала": base_start,
                            "Дата окончания": base_end,
                            "Длительность": (base_end - base_start).total_seconds() / 86400,
                            "Отклонение": diff_days,
                        }
                    )
        else:
            # If specific project selected, show only that project's tasks
            row = task_rows.iloc[0]
            project_name = row.get("project name", "Неизвестно")
            _tl = _bar_task_label_from_row(row, task_name)
            display_name = f"{_tl} ({project_name})"
            diff_days = row.get("total_diff_days", 0)
            section_name = row.get("section", "—")
            if pd.isna(section_name) or str(section_name).strip() == "":
                section_name = "—"

            plan_start = row.get("plan start")
            plan_end = row.get("plan end")
            base_start = row.get("base start")
            base_end = row.get("base end")

            # Add plan entry
            if pd.notna(plan_start) and pd.notna(plan_end):
                bar_data.append(
                    {
                        "Задача": display_name,
                        "Этап": section_name,
                        "Тип": "План",
                        "Дата начала": plan_start,
                        "Дата окончания": plan_end,
                        "Длительность": (plan_end - plan_start).total_seconds() / 86400,
                        "Отклонение": diff_days,
                    }
                )

            # Add fact entry
            if pd.notna(base_start) and pd.notna(base_end):
                bar_data.append(
                    {
                        "Задача": display_name,
                        "Этап": section_name,
                        "Тип": "Факт",
                        "Дата начала": base_start,
                        "Дата окончания": base_end,
                        "Длительность": (base_end - base_start).total_seconds() / 86400,
                        "Отклонение": diff_days,
                    }
                )

    bar_df = pd.DataFrame(bar_data)

    def _text_indicates_covenant(val):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return False
        t = str(val).lower()
        return "ковенант" in t or "coven" in t

    def _covenant_row_mask(frame):
        m = pd.Series(False, index=frame.index)
        for col in ("section", "block", "task name"):
            if col in frame.columns:
                m = m | frame[col].astype(str).map(_text_indicates_covenant)
        return m

    covenant_filter_selected = (
        selected_block_dates != "Все"
        and _text_indicates_covenant(selected_block_dates)
    )
    covenant_auto_from_data = False
    for col in ("section", "block"):
        if col in df_after_hide.columns and df_after_hide[col].astype(str).map(
            _text_indicates_covenant
        ).any():
            covenant_auto_from_data = True
            break
    show_covenant_ui = covenant_filter_selected or covenant_auto_from_data
    covenant_rows_df = table_df
    if covenant_auto_from_data and not covenant_filter_selected:
        covenant_rows_df = table_df.loc[_covenant_row_mask(table_df)].copy()
        if covenant_rows_df.empty:
            show_covenant_ui = False

    def _render_stage_deviation_bar_chart(bar_df_local):
        if bar_df_local.empty or "Этап" not in bar_df_local.columns:
            return
        section_dev = (
            bar_df_local.drop_duplicates(subset=["Задача"])[["Этап", "Отклонение"]]
            .groupby("Этап", as_index=False)["Отклонение"]
            .max()
        )
        if section_dev.empty:
            return
        section_dev = section_dev.sort_values("Отклонение", ascending=True)
        fig_section = go.Figure()
        fig_section.add_trace(
            go.Bar(
                x=section_dev["Отклонение"],
                y=section_dev["Этап"],
                orientation="h",
                text=section_dev["Отклонение"].apply(
                    lambda v: f"{int(round(v, 0))}" if pd.notna(v) else ""
                ),
                textposition="outside",
                textfont=dict(size=12, color="white"),
                marker_color="#2E86AB",
                name="Отклонение (дней)",
            )
        )
        fig_section.update_layout(
            xaxis_title="Отклонение (дней)",
            yaxis_title="Этап",
            height=max(440, len(section_dev) * 52),
            showlegend=False,
        )
        # Сверху вниз — по убыванию отклонения: в Plotly первая категория в array — низ графика, последняя — верх.
        fig_section.update_yaxes(
            categoryorder="array",
            categoryarray=section_dev.sort_values("Отклонение", ascending=True)[
                "Этап"
            ].tolist(),
        )
        fig_section = _apply_finance_bar_label_layout(fig_section)
        fig_section = apply_chart_background(fig_section)
        fig_section.update_layout(margin=dict(t=30, l=160))
        render_chart(
            fig_section,
            caption_below=(
                "Отклонение от базового плана по этапам (горизонтально; по убыванию величины отклонения)"
            ),
        )

    _render_stage_deviation_bar_chart(bar_df)

    if show_covenant_ui:
        pe_col, fe_col = "plan end", "base end"
        if pe_col not in covenant_rows_df.columns or fe_col not in covenant_rows_df.columns:
            st.warning("Нет колонок с датами окончания для ковенантов.")
        else:
            tdf = covenant_rows_df.copy()
            tdf[pe_col] = pd.to_datetime(tdf[pe_col], errors="coerce", dayfirst=True)
            tdf[fe_col] = pd.to_datetime(tdf[fe_col], errors="coerce", dayfirst=True)
            tdf_vis = tdf[tdf[pe_col].notna() | tdf[fe_col].notna()]

            def _cov_y(row):
                tn = row.get("task name", "—")
                pr = row.get("project name", "")
                if selected_project == "Все" and pr is not None and str(pr).strip():
                    return f"{tn} ({pr})"
                return str(tn)

            if not tdf_vis.empty:
                tdf_vis = tdf_vis.copy()
                tdf_vis["_y"] = tdf_vis.apply(_cov_y, axis=1)
                tdf_vis = tdf_vis.sort_values("_y")
                fig_cov = go.Figure()
                fig_cov.add_trace(
                    go.Scatter(
                        x=tdf_vis[pe_col],
                        y=tdf_vis["_y"],
                        mode="markers+text",
                        name="Базовое окончание",
                        marker=dict(
                            symbol="circle",
                            size=10,
                            color="#3B82F6",
                            line=dict(width=1, color="#ffffff"),
                        ),
                        text=tdf_vis[pe_col].apply(
                            lambda d: d.strftime("%d.%m.%Y") if pd.notna(d) else ""
                        ),
                        textposition="middle right",
                        textfont=dict(size=11, color="white"),
                        hovertemplate="%{y}<br>Базовое окончание: %{x|%d.%m.%Y}<extra></extra>",
                    )
                )
                fig_cov.add_trace(
                    go.Scatter(
                        x=tdf_vis[fe_col],
                        y=tdf_vis["_y"],
                        mode="markers+text",
                        name="Окончание",
                        marker=dict(
                            symbol="circle",
                            size=10,
                            color="#EF4444",
                            line=dict(width=1, color="#ffffff"),
                        ),
                        text=tdf_vis[fe_col].apply(
                            lambda d: d.strftime("%d.%m.%Y") if pd.notna(d) else ""
                        ),
                        textposition="middle right",
                        textfont=dict(size=11, color="white"),
                        hovertemplate="%{y}<br>Окончание: %{x|%d.%m.%Y}<extra></extra>",
                    )
                )
                nuniq = tdf_vis["_y"].nunique()
                fig_cov.update_layout(
                    xaxis_title="Дата",
                    yaxis_title="Ковенант",
                    height=max(420, int(nuniq) * 36),
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                    ),
                    xaxis=dict(type="date", tickformat="%d.%m.%Y"),
                    margin=dict(l=10, r=20, t=50, b=60),
                )
                fig_cov = apply_chart_background(fig_cov, skip_uniformtext=True)
                render_chart(fig_cov, caption_below="Ковенанты: базовое окончание и окончание (точки)")
            else:
                st.info("Нет дат для отображения ковенантов.")

            # Таблица: перечень ковенант — базовое окончание, окончание, отклонение окончания (макет правок)
            def _cov_fmt_date_cell(val):
                if pd.isna(val):
                    return ""
                if hasattr(val, "strftime"):
                    return val.strftime("%d.%m.%Y")
                try:
                    dt = pd.to_datetime(val, errors="coerce", dayfirst=True)
                    return dt.strftime("%d.%m.%Y") if pd.notna(dt) else ""
                except Exception:
                    return str(val).strip()

            cov_rows = []
            for _, crow in covenant_rows_df.iterrows():
                ped = crow.get("plan_end_diff")
                ped_num = pd.to_numeric(ped, errors="coerce")
                pev = crow.get(pe_col)
                fev = crow.get(fe_col)
                cov_rows.append(
                    {
                        "Проект": _clean_display_str(crow.get("project name"))
                        if selected_project == "Все" and "project name" in covenant_rows_df.columns
                        else "",
                        "Задача": _clean_display_str(crow.get("task name")),
                        "Базовое окончание": _cov_fmt_date_cell(pev),
                        "Окончание": _cov_fmt_date_cell(fev),
                        "Отклонение окончания (дней)": ped_num,
                    }
                )
            cov_df = pd.DataFrame(cov_rows)
            if selected_project != "Все" or "project name" not in covenant_rows_df.columns:
                cov_df = cov_df.drop(columns=["Проект"], errors="ignore")
            cov_df = cov_df.sort_values(
                "Отклонение окончания (дней)", ascending=False, na_position="last"
            ).reset_index(drop=True)
            if cov_df.empty:
                st.info("Нет строк для таблицы ковенантов.")
            else:
                cov_display = cov_df.copy()
                dev_num = cov_display["Отклонение окончания (дней)"]
                cov_display["Отклонение окончания (дней)"] = dev_num.apply(
                    lambda x: ""
                    if pd.isna(x)
                    else str(int(round(float(x), 0)))
                )

                st.subheader("Ковенанты (таблица)")
                with st.expander("Примечание к таблице ковенантов", expanded=False):
                    st.caption(
                        "Сортировка: по убыванию отклонения окончания. "
                        "Красный — отклонение > 0, зелёный — ≤ 0."
                    )
                _date_bg = "rgba(46, 134, 171, 0.22)"
                _tbl_parts = [
                    '<div class="rendered-table-wrap" style="margin-top:0.5rem">',
                    '<table class="rendered-table" style="border-collapse:collapse;width:100%">',
                    "<thead><tr>",
                ]
                for c in cov_display.columns:
                    _tbl_parts.append(
                        f"<th>{html_module.escape(str(c))}</th>"
                    )
                _tbl_parts.append("</tr></thead><tbody>")
                for i in range(len(cov_display)):
                    row = cov_display.iloc[i]
                    ped_raw = dev_num.iloc[i]
                    _tbl_parts.append("<tr>")
                    for col in cov_display.columns:
                        cell = row[col]
                        esc = html_module.escape(str(cell)) if str(cell).strip() != "" else ""
                        if col in ("Базовое окончание", "Окончание"):
                            _tbl_parts.append(
                                f'<td style="background:{_date_bg}">{esc}</td>'
                            )
                        elif col == "Отклонение окончания (дней)":
                            if pd.isna(ped_raw):
                                _tbl_parts.append(
                                    f"<td>{html_module.escape('—')}</td>"
                                )
                            else:
                                try:
                                    pv = float(ped_raw)
                                except (TypeError, ValueError):
                                    _tbl_parts.append(
                                        f"<td>{esc}</td>"
                                    )
                                else:
                                    clr = "#c0392b" if pv > 0 else "#27ae60"
                                    _tbl_parts.append(
                                        f'<td style="color:{clr};font-weight:600">{esc}</td>'
                                    )
                        else:
                            _tbl_parts.append(f"<td>{esc}</td>")
                    _tbl_parts.append("</tr>")
                _tbl_parts.append("</tbody></table></div>")
                st.markdown(_TABLE_CSS + "".join(_tbl_parts), unsafe_allow_html=True)
                st.caption(f"Записей: {len(cov_display)}")
                render_dataframe_excel_csv_downloads(
                    cov_display,
                    file_stem="covenant_plan_fact",
                    key_prefix="covenant_table",
                    csv_label="Скачать CSV (ковенанты, для Excel)",
                )
    elif bar_df.empty:
        st.info("Нет данных для отображения графика.")
    else:
        # Блок «План/факт по этапам» скрыт по ТЗ (макет: верхние метрики/поля убрать).
        pass

    # Форматирование даты для отображения (без «Н/Д» — пустая ячейка, если даты нет)
    def format_date_display(date_val):
        if pd.isna(date_val):
            return ""
        if isinstance(date_val, pd.Timestamp):
            return date_val.strftime("%d.%m.%Y")
        try:
            dt = pd.to_datetime(date_val, errors="coerce", dayfirst=True)
            if pd.notna(dt):
                return dt.strftime("%d.%m.%Y")
        except Exception:
            pass
        s = str(date_val).strip() if date_val else ""
        return s if s and s.lower() not in ("nan", "nat", "none") else ""

    # Верхние KPI и блок «РС» скрыты по правкам; задача для метрик в других отчётах — в админке (baseline_plan_task_for_metrics).

    # Summary table — макет: даты / отклонения, видимые столбцы, сортировка
    summary_data = []

    def _resolve_msp_id_columns(frame: pd.DataFrame) -> dict:
        """
        Возвращает маппинг {display_name: source_column} для ID задач MSP.
        Встречаются разные выгрузки: Unique ID / UID / Task ID и т.п.
        """
        if frame is None or getattr(frame, "empty", True):
            return {}
        cols = list(frame.columns)
        lower_map = {}
        for c in cols:
            try:
                lower_map[str(c).strip().lower()] = c
            except Exception:
                continue

        out = {}
        # Приоритет: unique id / uid
        for key in ("unique id", "uid"):
            if key in lower_map:
                out["UID задачи (MSP)"] = lower_map[key]
                break
        # Приоритет: task id / task id seq
        for key in ("task id", "task id seq"):
            if key in lower_map:
                out["ID задачи (MSP)"] = lower_map[key]
                break
        # Фоллбек: identifier (не берём просто "id", чтобы не поймать чужие ID)
        if "ID задачи (MSP)" not in out and "identifier" in lower_map:
            out["ID задачи (MSP)"] = lower_map["identifier"]
        return out

    _msp_id_cols = _resolve_msp_id_columns(table_df)

    def _format_date_cell(date_val):
        if pd.isna(date_val):
            return ""
        if isinstance(date_val, pd.Timestamp):
            return date_val.strftime("%d.%m.%Y")
        try:
            dt = pd.to_datetime(date_val, errors="coerce", dayfirst=True)
            if pd.notna(dt):
                return dt.strftime("%d.%m.%Y")
        except Exception:
            pass
        s = str(date_val).strip() if date_val else ""
        return s if s and s.lower() not in ("nan", "nat", "none") else ""

    for idx, row in table_df.iterrows():
        plan_start = row.get("plan start", pd.NaT)
        plan_end = row.get("plan end", pd.NaT)
        base_start = row.get("base start", pd.NaT)
        base_end = row.get("base end", pd.NaT)
        start_diff = row.get("plan_start_diff", np.nan)
        end_diff = row.get("plan_end_diff", np.nan)
        dur_diff = np.nan
        if (
            pd.notna(plan_start)
            and pd.notna(plan_end)
            and pd.notna(base_start)
            and pd.notna(base_end)
        ):
            try:
                pdur = (plan_end - plan_start).total_seconds() / 86400.0
                fdur = (base_end - base_start).total_seconds() / 86400.0
                dur_diff = fdur - pdur
            except Exception:
                dur_diff = np.nan

        if task_label_mode == "По лоту" and dates_lot_col and dates_lot_col in row.index:
            lv = row.get(dates_lot_col)
            if pd.notna(lv) and str(lv).strip() not in ("", "nan", "None"):
                task_show = _sanitize_eng_networks(f"Лот {str(lv).strip()}")
            else:
                task_show = _sanitize_eng_networks(_clean_display_str(row.get("task name")))
        else:
            task_show = _sanitize_eng_networks(_clean_display_str(row.get("task name")))

        rec = {
            "Проект": _clean_display_str(row.get("project name")),
            "Задача": task_show,
            "Базовое начало": _format_date_cell(plan_start),
            "Базовое окончание": _format_date_cell(plan_end),
            "Начало (факт)": _format_date_cell(base_start),
            "Окончание": _format_date_cell(base_end),
            "Отклонение начала": start_diff,
            "Отклонение окончания": end_diff,
            "Отклонение длительности": dur_diff,
        }
        for disp, src in _msp_id_cols.items():
            _tid = row.get(src)
            rec[disp] = (
                str(_tid).strip()
                if pd.notna(_tid) and str(_tid).strip() not in ("", "nan", "none")
                else ""
            )
        if "reason of deviation" in table_df.columns:
            rec["Причина отклонения"] = _clean_display_str(
                row.get("reason of deviation")
            )
        if dates_notes_col and dates_notes_col in table_df.columns:
            rec["Заметки"] = _clean_display_str(row.get(dates_notes_col))
        summary_data.append(rec)

    summary_df = pd.DataFrame(summary_data)
    for col in (
        "Отклонение начала",
        "Отклонение окончания",
        "Отклонение длительности",
    ):
        if col in summary_df.columns:
            summary_df[col] = pd.to_numeric(summary_df[col], errors="coerce")

    def _format_int_days(x):
        if pd.isna(x) or str(x).strip() == "":
            return ""
        try:
            return str(int(round(float(x), 0)))
        except (TypeError, ValueError):
            return ""

    # Дефолтный порядок (без отдельного фильтра сортировки): крупные отклонения выше.
    try:
        _end_dev = pd.to_numeric(summary_df.get("Отклонение окончания"), errors="coerce")
        _start_dev = pd.to_numeric(summary_df.get("Отклонение начала"), errors="coerce")
        summary_df = summary_df.assign(
            _abs_end=_end_dev.abs() if _end_dev is not None else np.nan,
            _abs_start=_start_dev.abs() if _start_dev is not None else np.nan,
        ).sort_values(
            ["_abs_end", "_abs_start", "Проект", "Задача"],
            ascending=[False, False, True, True],
            na_position="last",
        ).drop(columns=["_abs_end", "_abs_start"])
    except Exception:
        pass

    out_cols = ["Проект", "Задача"]
    if "UID задачи (MSP)" in summary_df.columns:
        out_cols.append("UID задачи (MSP)")
    if "ID задачи (MSP)" in summary_df.columns:
        out_cols.append("ID задачи (MSP)")
    if dates_value_type == "Даты (план/факт)":
        out_cols += [
            "Базовое начало",
            "Базовое окончание",
            "Начало (факт)",
            "Окончание",
        ]
    if tbl_show_start:
        out_cols.append("Отклонение начала")
    if tbl_show_end:
        out_cols.append("Отклонение окончания")
    if tbl_show_dur:
        out_cols.append("Отклонение длительности")
    if dates_show_reason_notes:
        if "Причина отклонения" in summary_df.columns:
            out_cols.append("Причина отклонения")
        if "Заметки" in summary_df.columns:
            out_cols.append("Заметки")
    out_cols = [c for c in out_cols if c in summary_df.columns]
    summary_df = summary_df[out_cols]

    summary_numeric = summary_df.copy()
    summary_display = summary_df.copy()
    for col in ("Отклонение начала", "Отклонение окончания", "Отклонение длительности"):
        if col in summary_display.columns:
            summary_display[col] = summary_display[col].apply(_format_int_days)
    for col in ("Отклонение начала", "Отклонение окончания", "Отклонение длительности"):
        if col in summary_numeric.columns:
            summary_numeric[col] = summary_numeric[col].apply(
                lambda x: pd.NA if pd.isna(x) else int(round(float(x)))
            ).astype("Int64")

    _dates_table_tooltips = {
        "Проект": "Название проекта из выгрузки MSP.",
        "Задача": "Наименование задачи MSP или лот (режим «По лоту» — см. блок «Подписи на графике и в таблице»).",
        "UID задачи (MSP)": "Уникальный идентификатор задачи в MSP (если есть в выгрузке).",
        "ID задачи (MSP)": "Идентификатор задачи в MSP (если есть в файле).",
        "Базовое начало": "Плановая дата начала из MSP (колонка plan start / аналог).",
        "Базовое окончание": "Плановая дата окончания из MSP (колонка plan end / аналог).",
        "Начало (факт)": "Фактическая дата начала (base start / аналог).",
        "Окончание": "Фактическая дата окончания (base end / аналог).",
        "Отклонение начала": "В днях: base start − plan start (при наличии обеих дат).",
        "Отклонение окончания": "В днях: base end − plan end (при наличии обеих дат).",
        "Отклонение длительности": "Разница длительностей факт vs план (в днях).",
        "Причина отклонения": "Поле причины отклонения из выгрузки (если есть).",
        "Заметки": "Заметки / комментарии из выгрузки (если есть).",
    }
    _dates_column_role = {
        "Базовое начало": "baseline",
        "Базовое окончание": "baseline",
        "Начало (факт)": "fact",
        "Окончание": "fact",
        "Отклонение окончания": "dev",
        "Отклонение начала": "dev",
        "Отклонение длительности": "dev",
    }
    if dates_value_type == "Отклонение (дней)" and not any(
        c in summary_df.columns
        for c in (
            "Отклонение начала",
            "Отклонение окончания",
            "Отклонение длительности",
        )
    ):
        st.warning(
            "В режиме «Отклонение (дней)» нет столбцов отклонения: включите один из чекбоксов ниже "
            "или переключите тип значения на «Даты (план/факт)»."
        )

    def _is_zos_task_name(name):
        if name is None or (isinstance(name, float) and pd.isna(name)):
            return False
        s = str(name).lower()
        if "зос" in s:
            return True
        return "заключение о соответствии" in s

    if "task name" in table_df.columns:
        zos_subset = table_df[
            table_df["task name"].astype(str).map(_is_zos_task_name)
        ].copy()
    else:
        zos_subset = table_df.iloc[0:0].copy()

    if not zos_subset.empty:
        st.subheader("ЗОС")
        zos_proj_count = (
            zos_subset["project name"].dropna().astype(str).str.strip().nunique()
            if "project name" in zos_subset.columns
            else 0
        )
        with st.expander("Контекст ЗОС", expanded=False):
            if selected_project != "Все":
                st.caption(f"Проект: {selected_project}")
            elif "project name" in zos_subset.columns and zos_proj_count == 1:
                _pn = zos_subset["project name"].dropna().astype(str).str.strip().unique().tolist()
                if _pn:
                    st.caption(f"Проект: {_pn[0]}")
            st.caption(
                "Сроки окончания и отклонение (дней); знак отклонения: факт − план по дате окончания."
            )
        zos_show_project_col = (
            "project name" in zos_subset.columns
            and selected_project == "Все"
            and zos_proj_count > 1
        )
        if "plan_end_diff" in zos_subset.columns:
            zos_subset = zos_subset.sort_values(
                "plan_end_diff", ascending=False, na_position="last"
            )
        zos_tbl_rows = []
        for _, zr in zos_subset.iterrows():
            row_out = {
                "Задача": _sanitize_eng_networks(_clean_display_str(zr.get("task name"))),
                "Базовое окончание": format_date_display(zr.get("plan end")),
                "Окончание": format_date_display(zr.get("base end")),
                "Отклонения": _format_int_days(zr.get("plan_end_diff")),
            }
            if zos_show_project_col:
                row_out = {
                    "Проект": _clean_display_str(zr.get("project name")),
                    **row_out,
                }
            zos_tbl_rows.append(row_out)
        zos_tbl = pd.DataFrame(zos_tbl_rows)
        _render_html_table(zos_tbl)
        st.markdown("---")

    # В режиме ковенантов узкая таблица «Ковенанты (таблица)» уже даёт сроки/отклонения по ковенантам;
    # полная таблица по filtered_df дублировала бы те же строки — показываем её только свёрнуто.
    def _render_dates_main_table():
        _extra_dev = tuple(
            c
            for c in ("Отклонение начала",)
            if c in summary_numeric.columns
        )
        _styled = style_dataframe_for_dark_theme(
            summary_numeric,
            days_column=(
                "Отклонение окончания"
                if "Отклонение окончания" in summary_numeric.columns
                else None
            ),
            extra_days_columns=_extra_dev if _extra_dev else None,
            plan_date_column=(
                "Базовое окончание" if "Базовое окончание" in summary_numeric.columns else None
            ),
            fact_date_column="Окончание" if "Окончание" in summary_numeric.columns else None,
        )
        # Цветовые группы по ТЗ: базовые даты / факт даты (мягкий фон колонок, без перезаписи красно‑зелёной подсветки отклонений).
        _baseline_cols = [c for c in ("Базовое начало", "Базовое окончание") if c in summary_numeric.columns]
        _fact_cols = [c for c in ("Начало (факт)", "Окончание") if c in summary_numeric.columns]
        try:
            if _baseline_cols:
                _styled = _styled.set_properties(subset=_baseline_cols, **{"background-color": "rgba(59, 130, 246, 0.14)"})
            if _fact_cols:
                _styled = _styled.set_properties(subset=_fact_cols, **{"background-color": "rgba(239, 68, 68, 0.10)"})
        except Exception:
            pass
        st.dataframe(
            _styled,
            hide_index=True,
            use_container_width=True,
            height=min(700, 50 + max(1, len(summary_numeric)) * 35),
        )

    if not show_covenant_ui:
        st.subheader("Отклонение от базового плана (таблица)")
        with st.expander("Сводка по таблице", expanded=False):
            st.caption(
                f"Записей: {len(summary_df)} · тип: {dates_value_type}. "
                "Сортировка по столбцам — кликом по заголовку в таблице."
            )
        _render_dates_main_table()
        render_dataframe_excel_csv_downloads(
            summary_display,
            file_stem="detail_dates",
            key_prefix="detail_dates",
        )
    else:
        with st.expander("Полная таблица отклонений по всем задачам фильтра", expanded=False):
            st.markdown(
                "Полная таблица по всем задачам фильтра не выводится отдельным блоком, чтобы не дублировать "
                "таблицу **Ковенанты** выше. Ниже — развёртка со всеми колонками (план/факт, отклонения), если нужен экспорт."
            )
            st.caption(
                f"Записей: {len(summary_df)} · тип: {dates_value_type}"
            )
            _render_dates_main_table()
            render_dataframe_excel_csv_downloads(
                summary_display,
                file_stem="detail_dates",
                key_prefix="detail_dates_cov_all",
                csv_label="Скачать CSV (все задачи фильтра, для Excel)",
            )


# ==================== DASHBOARD 4: Deviation Amount by Tasks ====================
def dashboard_deviation_by_tasks_current_month(df):
    # Проверка на None или пустой DataFrame
    if df is None:
        st.warning(
            "Нет данных для отображения. Пожалуйста, загрузите данные проекта."
        )
        return

    # Проверка, что df является DataFrame и имеет атрибут columns
    if not hasattr(df, "columns") or df.empty:
        st.warning(
            "Нет данных для отображения. Пожалуйста, загрузите данные проекта."
        )
        return

    ensure_msp_hierarchy_columns(df)

    st.header("Значения отклонений от базового плана")

    find_column = _dev_tasks_find_column

    project_col = (
        "project name"
        if "project name" in df.columns
        else find_column(df, ["Проект", "project"])
    )
    if not project_col:
        st.warning("Поле 'project name' / 'Проект' не найдено в данных.")
        return

    all_projects = _unique_project_labels_for_select(df[project_col])
    if not all_projects:
        st.warning("Проекты не найдены в данных.")
        return

    f_proj, f_block, f_build, f_det = st.columns(4)
    with f_proj:
        projects = ["Все"] + all_projects
        selected_project = st.selectbox(
            "Фильтр по проекту", projects, key="deviation_tasks_project"
        )

    base = df.copy()
    if selected_project != "Все" and project_col in base.columns:
        base = base[
            base[project_col].map(_project_filter_norm_key)
            == _project_filter_norm_key(selected_project)
        ]

    level_col = _dev_tasks_resolve_level_column(base)
    task_col = (
        "task name"
        if "task name" in base.columns
        else find_column(base, ["Задача", "task", "Task Name", "Название"])
    )
    if not task_col:
        st.warning("Поле 'task name' / «Задача» не найдено в данных.")
        return

    work_h = _dev_tasks_build_ancestor_keys(base, level_col, task_col)

    selected_block = "Все"
    selected_building = "Все"
    target_lvl = None

    if level_col and level_col in work_h.columns:
        ln = pd.to_numeric(work_h[level_col], errors="coerce")
        _blk_tier_d, _bld_tier_d = _deviations_msp_tier_levels(ln)
        block_opts = ["Все"] + sorted(
            work_h.loc[ln == float(_blk_tier_d), task_col]
            .dropna()
            .astype(str)
            .str.strip()
            .unique()
            .tolist()
        )
        if len(block_opts) <= 1 and "_dt_lvl2_key" in work_h.columns:
            _k2d = work_h["_dt_lvl2_key"].astype(str).str.strip()
            _k2d = _k2d[_k2d.ne("") & _k2d.str.lower().ne("nan")]
            if len(_k2d):
                block_opts = ["Все"] + sorted(pd.unique(_k2d).tolist())
        with f_block:
            selected_block = st.selectbox(
                "Функциональный блок",
                block_opts,
                key="deviation_tasks_block_l2",
                help=(
                    f"Задачи яруса «функциональный блок» (ур. {_blk_tier_d} по колонке уровня MSP). "
                    "Если в строках этого уровня нет имён — список из ключа предка ур.2 по дереву выгрузки."
                ),
            )
        w3 = work_h[ln == float(_bld_tier_d)]
        if selected_block != "Все":
            w3 = w3[
                w3["_dt_lvl2_key"].astype(str).str.strip()
                == str(selected_block).strip()
            ]
        build_opts = ["Все"] + sorted(
            w3[task_col].dropna().astype(str).str.strip().unique().tolist()
        )
        if len(build_opts) <= 1 and selected_block != "Все" and "_dt_lvl3_key" in w3.columns:
            _k3d = w3["_dt_lvl3_key"].astype(str).str.strip()
            _k3d = _k3d[_k3d.ne("") & _k3d.str.lower().ne("nan")]
            if len(_k3d):
                build_opts = ["Все"] + sorted(pd.unique(_k3d).tolist())
        with f_build:
            selected_building = st.selectbox(
                "Строение",
                build_opts,
                key="deviation_tasks_building_l3",
                help=(
                    f"Задачи яруса «строение» (ур. {_bld_tier_d}) в выбранном функциональном блоке."
                ),
            )
        detail_opts = ("Укрупнённо (уровень 4)", "Детально (уровень 5)")
        with f_det:
            detail_label = st.selectbox(
                "Детализация",
                detail_opts,
                index=0,
                key="deviation_tasks_detail_lvl",
                help="Показать строки MSP с уровнем структуры 4 или 5.",
            )
        target_lvl = 5 if "5" in str(detail_label) else 4
    else:
        with f_block:
            st.caption("Нет колонки уровня MSP")
        block_col_fb = find_column(
            base,
            ["block", "Блок", "Функциональный блок", "Functional block"],
        )
        with f_block:
            if block_col_fb and block_col_fb in base.columns:
                bopts = ["Все"] + sorted(
                    base[block_col_fb].dropna().astype(str).str.strip().unique().tolist()
                )
                selected_block = st.selectbox(
                    "Функциональный блок",
                    bopts,
                    key="deviation_tasks_block_col",
                )
            else:
                selected_block = "Все"
        building_col_fb = find_column(
            base,
            ["building", "Строение", "строение", "Сооружение"],
        )
        with f_build:
            if building_col_fb and building_col_fb in base.columns:
                gopts = ["Все"] + sorted(
                    base[building_col_fb].dropna().astype(str).str.strip().unique().tolist()
                )
                selected_building = st.selectbox(
                    "Строение",
                    gopts,
                    key="deviation_tasks_building_col",
                )
            else:
                selected_building = "Все"
        with f_det:
            st.caption("—")
        st.caption(
            "Колонка уровня MSP не найдена — блок/строение из отдельных колонок (если есть); "
            "режим «уровень 4 / 5» недоступен."
        )

    filtered_df = work_h.copy()
    if level_col and level_col in filtered_df.columns and target_lvl is not None:
        if selected_block != "Все":
            filtered_df = filtered_df[
                filtered_df["_dt_lvl2_key"].astype(str).str.strip()
                == str(selected_block).strip()
            ]
        if selected_building != "Все":
            filtered_df = filtered_df[
                filtered_df["_dt_lvl3_key"].astype(str).str.strip()
                == str(selected_building).strip()
            ]
        ln_f = pd.to_numeric(filtered_df["_dt_lvl_num"], errors="coerce")
        filtered_df = filtered_df[ln_f == float(target_lvl)]
    else:
        block_col_fb = find_column(
            filtered_df,
            ["block", "Блок", "Функциональный блок", "Functional block"],
        )
        building_col_fb = find_column(
            filtered_df,
            ["building", "Строение", "строение", "Сооружение"],
        )
        if selected_block != "Все" and block_col_fb and block_col_fb in filtered_df.columns:
            filtered_df = filtered_df[
                filtered_df[block_col_fb].astype(str).str.strip()
                == str(selected_block).strip()
            ]
        if selected_building != "Все" and building_col_fb and building_col_fb in filtered_df.columns:
            filtered_df = filtered_df[
                filtered_df[building_col_fb].astype(str).str.strip()
                == str(selected_building).strip()
            ]

    # Filter tasks: deviation=1/True OR reason of deviation filled
    try:
        has_deviation_col = "deviation" in filtered_df.columns
        has_reason_col = "reason of deviation" in filtered_df.columns
    except (AttributeError, TypeError):
        has_deviation_col = False
        has_reason_col = False

    if has_deviation_col or has_reason_col:
        if has_deviation_col:
            deviation_flag = (
                (filtered_df["deviation"] == True)
                | (filtered_df["deviation"] == 1)
                | (filtered_df["deviation"].astype(str).str.lower() == "true")
                | (filtered_df["deviation"].astype(str).str.strip() == "1")
            )
        else:
            deviation_flag = pd.Series(False, index=filtered_df.index)
        if has_reason_col:
            reason_filled = (
                filtered_df["reason of deviation"].notna()
                & (filtered_df["reason of deviation"].astype(str).str.strip() != "")
            )
        else:
            reason_filled = pd.Series(False, index=filtered_df.index)
        filtered_df = filtered_df[deviation_flag | reason_filled]
    else:
        st.warning("Поле 'deviation' или 'reason of deviation' не найдено в данных.")
        return

    if filtered_df.empty:
        st.info("Отклонения не найдены для выбранных фильтров.")
        return

    # Колонка задачи уже определена выше (по выборке проекта)
    has_task_col = task_col is not None and task_col in filtered_df.columns

    if project_col and has_task_col:
        # Convert deviation in days to numeric
        try:
            has_deviation_days_col = "deviation in days" in filtered_df.columns
        except (AttributeError, TypeError):
            has_deviation_days_col = False

        if has_deviation_days_col:
            filtered_df["deviation in days"] = pd.to_numeric(
                filtered_df["deviation in days"], errors="coerce"
            )

        # Подставляем колонки дат из русских названий, если их ещё нет
        ensure_date_columns(filtered_df)
        # Calculate completion percentage if dates are available
        try:
            has_plan_start = "plan start" in filtered_df.columns
            has_plan_end = "plan end" in filtered_df.columns
            has_base_start = "base start" in filtered_df.columns
            has_base_end = "base end" in filtered_df.columns
        except (AttributeError, TypeError):
            has_plan_start = False
            has_plan_end = False
            has_base_start = False
            has_base_end = False

        if has_plan_start and has_plan_end and has_base_start and has_base_end:
            # Convert dates to datetime
            for col in ["plan start", "plan end", "base start", "base end"]:
                filtered_df[col] = pd.to_datetime(
                    filtered_df[col], errors="coerce", dayfirst=True
                )

            # Calculate completion percentage:
            # (Планируемая дата окончания - планируемая дата начала) / (Фактическая дата окончания - фактическая дата начала) * 100
            filtered_df["plan_duration"] = (
                filtered_df["plan end"] - filtered_df["plan start"]
            ).dt.days
            filtered_df["fact_duration"] = (
                filtered_df["base end"] - filtered_df["base start"]
            ).dt.days

            # Calculate percentage: plan_duration / fact_duration * 100
            # Avoid division by zero
            filtered_df["completion_percent"] = (
                filtered_df["plan_duration"]
                / filtered_df["fact_duration"].replace(0, np.nan)
                * 100
            ).fillna(0)
            # Cap at reasonable values (0-200%)
            filtered_df["completion_percent"] = filtered_df["completion_percent"].clip(
                0, 200
            )
        else:
            filtered_df["completion_percent"] = None

        # Группировка по проекту (фильтр по этапу/section убран по ТЗ)
        group_by_cols = [project_col]
        y_column = "Проект"

        # Group data based on determined grouping level
        deviations = (
            filtered_df.groupby(group_by_cols)
            .agg(
                {
                    "deviation in days": (
                        "sum" if "deviation in days" in filtered_df.columns else "count"
                    ),
                    "completion_percent": (
                        "mean"
                        if "completion_percent" in filtered_df.columns
                        and filtered_df["completion_percent"].notna().any()
                        else lambda x: None
                    ),
                }
            )
            .reset_index()
        )

        # Set column names based on grouping level (только проект)
        if len(group_by_cols) == 2:
            deviations.columns = [
                "Проект",
                "Задача",
                "Суммарно дней отклонений",
                "Процент выполнения",
            ]
            deviations["Отображение"] = (
                deviations["Задача"] + " (" + deviations["Проект"] + ")"
            )
        else:
            deviations.columns = [
                "Проект",
                "Суммарно дней отклонений",
                "Процент выполнения",
            ]
            deviations["Отображение"] = deviations["Проект"]

        def _wrap_label_dev(text, max_len=30, max_total=60):
            s = str(text)
            if len(s) > max_total:
                s = s[:max_total - 1] + "…"
            words = s.split(" ")
            lines, current = [], ""
            for word in words:
                if len(current) + len(word) + 1 > max_len:
                    lines.append(current)
                    current = word
                else:
                    current = (current + " " + word).strip()
            if current:
                lines.append(current)
            return "<br>".join(lines[:3])

        deviations["Отображение"] = deviations["Отображение"].apply(_wrap_label_dev)

        # If completion percent calculation failed, set to None
        if "Процент выполнения" in deviations.columns:
            deviations["Процент выполнения"] = pd.to_numeric(
                deviations["Процент выполнения"], errors="coerce"
            )

        # Числовая ось: убирает ошибочный масштаб и «пустое» поле справа на гориз. bar
        deviations["Суммарно дней отклонений"] = pd.to_numeric(
            deviations["Суммарно дней отклонений"], errors="coerce"
        ).fillna(0)

        # Sort by deviation amount (descending - largest first)
        deviations = deviations.sort_values("Суммарно дней отклонений", ascending=False)

        if deviations.empty:
            st.info("Нет данных для отображения.")
            return

        # Checkboxes row 2: Top 5 and Completion percentage
        col5, col6 = st.columns(2)

        with col5:
            # Checkbox for Top 5 filter
            show_top5 = st.checkbox(
                "Топ 5 отклонений", value=False, key="show_top5_deviations"
            )

        with col6:
            # Checkbox to show/hide completion percentage
            show_completion = st.checkbox(
                "Показывать процент выполнения",
                value=False,
                key="show_completion_percent",
            )

        # Apply Top 5 filter if enabled
        if show_top5:
            deviations = deviations.head(5)

        # Visualization - horizontal bar chart
        deviations = _limit_bar_categories(
            deviations, "Суммарно дней отклонений", max_bars=50, label="проектов"
        )
        # Format text for display on bars
        text_values = []
        for _, row in deviations.iterrows():
            if show_completion and pd.notna(row.get("Процент выполнения")):
                text_values.append(
                    f"{int(round(row['Суммарно дней отклонений'], 0))} ({row['Процент выполнения']:.1f}%)"
                )
            else:
                text_values.append(f"{int(round(row['Суммарно дней отклонений'], 0))}")

        fig = px.bar(
            deviations,
            x="Суммарно дней отклонений",
            y="Отображение",
            orientation="h",
            title=None,
            labels={
                "Суммарно дней отклонений": "Суммарно дней отклонений",
                "Отображение": y_column,
            },
            text=text_values,
            color_discrete_sequence=["#1f77b4"],  # Blue color for all bars
        )

        # Set category order to show largest values at top (descending order)
        # For horizontal bars, reverse the list so largest is at top
        category_list = deviations["Отображение"].tolist()
        fig.update_layout(
            showlegend=False,
            yaxis=dict(
                categoryorder="array",
                categoryarray=list(
                    reversed(category_list)
                ),  # Reverse to show largest at top
            ),
        )
        fig.update_traces(
            textposition="outside", textfont=dict(size=14, color="white"),
            cliponaxis=False,
        )

        fig = apply_chart_background(fig)
        max_line_len = max(
            max(len(line) for line in s.split("<br>"))
            for s in deviations["Отображение"].tolist()
        ) if not deviations.empty else 20
        left_margin = min(max_line_len * 8, 400)
        fig.update_layout(
            height=max(350, len(deviations) * 80),
            margin=dict(l=left_margin, r=10, t=40, b=80),
            xaxis=dict(range=_xaxis_range_positive(deviations["Суммарно дней отклонений"])),
        )
        fig = _apply_bar_uniformtext(fig)
        render_chart(fig, caption_below="Отклонения от базового плана")

        # Детализация: те же фильтры, что у основного графика (проект / блок / строение / уровень 4–5)
        st.subheader("Детализация отклонений по задачам")

        detail_df = filtered_df.copy()

        if detail_df.empty:
            st.info("Нет данных для отображения детализации.")
        else:
            # Convert deviation in days to numeric
            if "deviation in days" in detail_df.columns:
                detail_df["deviation in days"] = pd.to_numeric(
                    detail_df["deviation in days"], errors="coerce"
                )

            if "task name" in detail_df.columns:
                detail_deviations = (
                    detail_df.groupby(["task name"])
                    .agg(
                        {
                            "deviation in days": (
                                "sum"
                                if "deviation in days" in detail_df.columns
                                else "count"
                            )
                        }
                    )
                    .reset_index()
                )

                detail_deviations.columns = [
                    "Задача",
                    "Суммарно дней отклонений",
                ]
                detail_deviations["Отображение"] = detail_deviations["Задача"]

                def _wrap_label(text, max_len=30, max_total=60):
                    s = str(text)
                    if len(s) > max_total:
                        s = s[:max_total - 1] + "…"
                    words = s.split(" ")
                    lines, current = [], ""
                    for word in words:
                        if len(current) + len(word) + 1 > max_len:
                            lines.append(current)
                            current = word
                        else:
                            current = (current + " " + word).strip()
                    if current:
                        lines.append(current)
                    return "<br>".join(lines[:3])

                detail_deviations["Отображение"] = detail_deviations["Отображение"].apply(_wrap_label)

                # Не выводить отрицательные значения на графике
                detail_deviations = detail_deviations[
                    detail_deviations["Суммарно дней отклонений"] >= 0
                ]

                # Sort by deviation amount (descending)
                detail_deviations = detail_deviations.sort_values(
                    "Суммарно дней отклонений", ascending=False
                )

                # Create horizontal bar chart (только неотрицательные)
                if detail_deviations.empty:
                    st.info("Нет неотрицательных отклонений для детализации.")
                else:
                    detail_deviations["Суммарно дней отклонений"] = pd.to_numeric(
                        detail_deviations["Суммарно дней отклонений"], errors="coerce"
                    ).fillna(0)
                    table_display = detail_deviations[["Задача", "Суммарно дней отклонений"]].copy()
                    table_display["Суммарно дней отклонений"] = table_display["Суммарно дней отклонений"].apply(
                        lambda x: int(round(x, 0)) if pd.notna(x) else 0
                    )
                    table_display = table_display.sort_values("Суммарно дней отклонений", ascending=False)
                    st.caption(f"Записей: {len(table_display)}")
                    _render_html_table(table_display)
                    render_dataframe_excel_csv_downloads(
                        table_display,
                        file_stem="deviation_details",
                        key_prefix="deviation_detail_export",
                    )
                    fig_detail = px.bar(
                        detail_deviations,
                        x="Суммарно дней отклонений",
                        y="Отображение",
                        orientation="h",
                        title=None,
                        labels={
                            "Суммарно дней отклонений": "Суммарно дней отклонений",
                            "Отображение": "Задача",
                        },
                        text=detail_deviations["Суммарно дней отклонений"].apply(
                            lambda x: f"{int(round(x, 0))}" if pd.notna(x) else ""
                        ),
                        color_discrete_sequence=["#1f77b4"],
                    )

                    category_list_detail = detail_deviations["Отображение"].tolist()
                    fig_detail.update_layout(
                        showlegend=False,
                        yaxis=dict(
                            categoryorder="array",
                            categoryarray=list(reversed(category_list_detail)),
                        ),
                        height=max(400, len(detail_deviations) * 80),
                    )
                    fig_detail.update_traces(
                        textposition="outside", textfont=dict(size=12, color="white"),
                        cliponaxis=False,
                    )

                    fig_detail = _apply_bar_uniformtext(fig_detail)
                    fig_detail = apply_chart_background(fig_detail)
                    max_line_len = max(
                        max(len(line) for line in s.split("<br>"))
                        for s in detail_deviations["Отображение"].tolist()
                    ) if not detail_deviations.empty else 20
                    left_margin = min(max_line_len * 8, 400)
                    fig_detail.update_layout(
                        margin=dict(l=left_margin, r=10, t=40, b=80),
                        xaxis=dict(
                            range=_xaxis_range_positive(
                                detail_deviations["Суммарно дней отклонений"]
                            )
                        ),
                    )
                    render_chart(
                        fig_detail,
                        caption_below="Детализация отклонений по задачам",
                    )
            else:
                st.warning("Поле 'task name' не найдено для детализации.")
    else:
        st.warning(
            "Необходимые поля 'project name' или 'task name' не найдены в данных."
        )


# ==================== DASHBOARD 5: Dynamics of Reasons by Month ====================
def dashboard_dynamics_of_reasons(df, hide_shared_filters=False):
    # Проверка на None или пустой DataFrame
    if df is None:
        st.warning(
            "Нет данных для отображения. Пожалуйста, загрузите данные проекта."
        )
        return

    # Проверка, что df является DataFrame и имеет атрибут columns
    if not hasattr(df, "columns") or df.empty:
        st.warning(
            "Нет данных для отображения. Пожалуйста, загрузите данные проекта."
        )
        return

    # При hide_shared_filters проект/этап/причина задаются общими фильтрами выше; без значений по умолчанию — NameError в ветках «По месяцам».
    selected_project = "Все"
    selected_reason = "Все"
    selected_section = "Все"

    if hide_shared_filters:
        st.subheader("Динамика причин отклонений")
        col1, = st.columns(1)
        with col1:
            period_type = st.selectbox(
                "Группировать по", ["Месяц", "Квартал", "Год"], key="reasons_period"
            )
            period_map = {"Месяц": "Month", "Квартал": "Quarter", "Год": "Year"}
            period_type_en = period_map.get(period_type, "Month")
    else:
        st.header("Динамика причин отклонений")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            period_type = st.selectbox(
                "Группировать по", ["Месяц", "Квартал", "Год"], key="reasons_period"
            )
            period_map = {"Месяц": "Month", "Квартал": "Quarter", "Год": "Year"}
            period_type_en = period_map.get(period_type, "Month")

        with col2:
            try:
                has_reason_column = "reason of deviation" in df.columns
            except (AttributeError, TypeError):
                has_reason_column = False

            if has_reason_column:
                reasons = ["Все"] + sorted(
                    df["reason of deviation"].dropna().unique().tolist()
                )
                selected_reason = st.selectbox(
                    "Причина", reasons, key="reasons_reason"
                )
            else:
                selected_reason = "Все"

        with col3:
            try:
                has_project_column = "project name" in df.columns
            except (AttributeError, TypeError):
                has_project_column = False

            if has_project_column:
                _session_reset_project_if_excluded("reasons_project")
                projects = ["Все"] + _project_name_select_options(df["project name"])
                selected_project = st.selectbox(
                    "Проект", projects, key="reasons_project"
                )
            else:
                selected_project = "Все"

        with col4:
            try:
                has_section_column = "section" in df.columns
            except (AttributeError, TypeError):
                has_section_column = False

            if has_section_column:
                sections = ["Все"] + sorted(df["section"].dropna().unique().tolist())
                selected_section = st.selectbox(
                    "Этап", sections, key="reasons_section"
                )
            else:
                selected_section = "Все"

    view_type = st.selectbox(
        "Вид отображения", ["По причинам", "По месяцам"], key="reasons_view_type"
    )
    show_trend_line = st.checkbox(
        "Показывать линию тренда",
        value=False,
        key="reasons_dynamics_show_trend_line",
        help="Применяется к графику «По месяцам»",
    )

    filtered_df = df.copy()

    if not hide_shared_filters:
        try:
            has_reason_col = "reason of deviation" in df.columns
        except (AttributeError, TypeError):
            has_reason_col = False

        if selected_reason != "Все" and has_reason_col:
            filtered_df = filtered_df[
                filtered_df["reason of deviation"].astype(str).str.strip()
                == str(selected_reason).strip()
            ]

        try:
            has_project_col = "project name" in filtered_df.columns
        except (AttributeError, TypeError):
            has_project_col = False

        if selected_project != "Все" and has_project_col:
            filtered_df = filtered_df[
                filtered_df["project name"].astype(str).str.strip()
                == str(selected_project).strip()
            ]

        try:
            has_section_col = "section" in filtered_df.columns
        except (AttributeError, TypeError):
            has_section_col = False

        if selected_section != "Все" and has_section_col:
            filtered_df = filtered_df[
                filtered_df["section"].astype(str).str.strip()
                == str(selected_section).strip()
            ]

    # Filter tasks: deviation=1/True OR reason of deviation filled
    try:
        has_deviation_col = "deviation" in filtered_df.columns
        has_reason_col = "reason of deviation" in filtered_df.columns
    except (AttributeError, TypeError):
        has_deviation_col = False
        has_reason_col = False

    if has_deviation_col or has_reason_col:
        if has_deviation_col:
            deviation_flag = (
                (filtered_df["deviation"] == True)
                | (filtered_df["deviation"] == 1)
                | (filtered_df["deviation"].astype(str).str.lower() == "true")
                | (filtered_df["deviation"].astype(str).str.strip() == "1")
            )
        else:
            deviation_flag = pd.Series(False, index=filtered_df.index)
        if has_reason_col:
            reason_filled = (
                filtered_df["reason of deviation"].notna()
                & (filtered_df["reason of deviation"].astype(str).str.strip() != "")
            )
        else:
            reason_filled = pd.Series(False, index=filtered_df.index)
        filtered_df = filtered_df[deviation_flag | reason_filled]

    if filtered_df.empty:
        st.info("Нет данных для выбранных фильтров.")
        return

    # Determine period column - use plan_month for month grouping
    try:
        has_plan_end_col = "plan end" in filtered_df.columns
    except (AttributeError, TypeError):
        has_plan_end_col = False

    if period_type_en == "Month":
        period_col = "plan_month"
        period_label = "Месяц"
        # If plan_month doesn't exist, try to create it from plan end
        try:
            has_period_col = period_col in filtered_df.columns
        except (AttributeError, TypeError):
            has_period_col = False

        if not has_period_col and has_plan_end_col:
            mask = filtered_df["plan end"].notna()
            filtered_df.loc[mask, period_col] = filtered_df.loc[
                mask, "plan end"
            ].dt.to_period("M")
    elif period_type_en == "Quarter":
        period_col = "plan_quarter"
        period_label = "Квартал"
        try:
            has_period_col = period_col in filtered_df.columns
        except (AttributeError, TypeError):
            has_period_col = False

        if not has_period_col and has_plan_end_col:
            mask = filtered_df["plan end"].notna()
            filtered_df.loc[mask, period_col] = filtered_df.loc[
                mask, "plan end"
            ].dt.to_period("Q")
    else:
        period_col = "plan_year"
        period_label = "Год"
        try:
            has_period_col = period_col in filtered_df.columns
        except (AttributeError, TypeError):
            has_period_col = False

        if not has_period_col and has_plan_end_col:
            mask = filtered_df["plan end"].notna()
            filtered_df.loc[mask, period_col] = filtered_df.loc[
                mask, "plan end"
            ].dt.to_period("Y")

    if period_col not in filtered_df.columns:
        st.warning(f"Столбец периода '{period_col}' не найден.")
        return

    # Group by period and reason - ensure we have both project name and reason
    if "reason of deviation" in filtered_df.columns:
        # Filter out rows without period data
        reason_dynamics = (
            filtered_df[filtered_df[period_col].notna()]
            .groupby([period_col, "reason of deviation"])
            .size()
            .reset_index(name="Количество")
        )

        reason_dynamics[period_col] = reason_dynamics[period_col].apply(format_period_ru)

        # Aggregate again after formatting to handle potential duplicates from formatting
        reason_dynamics = (
            reason_dynamics.groupby([period_col, "reason of deviation"])["Количество"]
            .sum()
            .reset_index()
        )

        # В комбинированном отчёте selected_project не заполняется — для веток графика «По месяцам» берём devcombo_project
        chart_project_scope = (
            st.session_state.get("devcombo_project", "Все")
            if hide_shared_filters
            else selected_project
        )

        # Build visualization based on view type
        if view_type == "По причинам":
            # View 1: By reasons - reason on X-axis, count on Y-axis
            # Group by reason and sum across all periods
            reason_summary = (
                reason_dynamics.groupby("reason of deviation")["Количество"]
                .sum()
                .reset_index()
            )
            reason_summary = reason_summary.sort_values("Количество", ascending=False)

            # Visualization - vertical bar chart with reasons on X-axis
            fig = px.bar(
                reason_summary,
                x="reason of deviation",
                y="Количество",
                title=None,
                labels={
                    "reason of deviation": "Причина отклонения",
                    "Количество": "Количество отклонений",
                },
                text="Количество",
                color_discrete_sequence=["#1f77b4"],
            )
            # fig.update_xaxes(tickangle=-45)
            # fig.update_traces(
            #     textposition="outside", textfont=dict(size=12, color="white")
            # )
            fig.update_xaxes(tickangle=-45)
            fig.update_traces(
                textposition="outside", textfont=dict(size=12, color="white")
            )
            fig = _apply_finance_bar_label_layout(fig)
            n_rs = int(len(reason_summary))
            _ymax_rs = float(
                pd.to_numeric(reason_summary["Количество"], errors="coerce").max() or 0.0
            )
            _y_top_rs = max(1.0, _ymax_rs * 1.45 + 12.0)
            fig.update_layout(
                height=max(520, int(180 + n_rs * 52)),
                margin=dict(l=28, r=28, t=110, b=200),
                yaxis=dict(
                    range=[0, _y_top_rs],
                    title="Количество отклонений",
                    automargin=True,
                ),
                xaxis=dict(automargin=True),
            )
        else:
            # View 2: By months - month on X-axis, count on Y-axis, reasons as colors (stacked)
            # If "Все" projects selected, show aggregated view (one column per period)
            if chart_project_scope == "Все":
                # For chart: group only by period (sum all reasons)
                chart_data = (
                    reason_dynamics.groupby(period_col)["Количество"]
                    .sum()
                    .reset_index()
                )
                chart_data["reason of deviation"] = (
                    "Все проекты"  # Dummy column for consistency
                )

                # Visualization - vertical bar chart with single column per period
                fig = px.bar(
                    chart_data,
                    x=period_col,
                    y="Количество",
                    title=None,
                    labels={
                        period_col: period_label,
                        "Количество": "Количество отклонений",
                    },
                    text="Количество",
                    color_discrete_sequence=["#1f77b4"],  # Single color for all bars
                )
            else:
                # Visualization - vertical bar chart with stacked reasons
                # Use period_col for x-axis and reason for color (legend)
                # Use stacked mode to show all reasons in one column per period
                fig = px.bar(
                    reason_dynamics,
                    x=period_col,
                    y="Количество",
                    color="reason of deviation",
                    title=None,
                    labels={
                        period_col: period_label,
                        "reason of deviation": "Причина отклонения",
                        "Количество": "Количество отклонений",
                    },
                    text="Количество",
                    barmode="stack",  # Stacked bars: all reasons in one column per period
                )
        # Update layout based on view type
        if view_type == "По причинам":
            # For "По причинам" view, no additional annotations needed
            pass
        else:
            # For "По месяцам" view, add annotations and trend line
            fig.update_xaxes(tickangle=-45)
            # Show values inside bars for each reason - horizontal text (same as other charts)
            fig.update_traces(
                textposition="inside", textfont=dict(size=12, color="white")
            )
            # Set text angle to horizontal (0 degrees) for inside bar labels - same as other charts
            for i, trace in enumerate(fig.data):
                fig.data[i].update(textangle=0)

            # Add total values above bars and trend line
            if chart_project_scope == "Все":
                # For "Все проекты": use chart_data for annotations and trend
                total_by_period = (
                    chart_data.groupby(period_col)["Количество"].sum().reset_index()
                )
                periods = sorted(chart_data[period_col].unique())
                max_y_value = chart_data["Количество"].max()
            else:
                # Calculate total deviations per period for annotations
                total_by_period = (
                    reason_dynamics.groupby(period_col)["Количество"]
                    .sum()
                    .reset_index()
                )
                total_by_period_dict = dict(
                    zip(total_by_period[period_col], total_by_period["Количество"])
                )
                periods = sorted(reason_dynamics[period_col].unique())
                max_y_value = reason_dynamics["Количество"].max()

                # Add annotations for individual project view
                for period in periods:
                    total = total_by_period_dict.get(period, 0)
                    if total > 0:
                        # Get all bars for this period to find max height
                        period_bars = reason_dynamics[
                            reason_dynamics[period_col] == period
                        ]
                        if not period_bars.empty:
                            # Find the maximum height among all bars in this period group
                            max_bar_height = period_bars["Количество"].max()

                            # Calculate offset
                            if max_y_value > 0:
                                y_offset = max_y_value * 0.10
                            else:
                                y_offset = max_bar_height * 0.10

                            # Position annotation
                            x_position = period
                            y_position = max_bar_height + y_offset

                            fig.add_annotation(
                                x=x_position,
                                y=y_position,
                                text=f"<b>{int(round(total, 0))}</b>",
                                showarrow=False,
                                font=dict(size=14, color="white"),
                                xanchor="center",
                                yanchor="bottom",
                                bgcolor="rgba(0,0,0,0.5)",
                                xshift=10,
                            )

            # Add trend line if checkbox is checked (use chart's x order so line aligns with bars)
            if show_trend_line and len(fig.data) > 0:
                x_order = list(fig.data[0].x)
                if len(x_order) > 1:
                    total_by_period_idx = total_by_period.set_index(period_col)
                    y_values = total_by_period_idx.reindex(x_order)["Количество"].values
                    y_values = np.nan_to_num(y_values, nan=0.0)

                    x_numeric = np.arange(len(y_values))
                    z = np.polyfit(x_numeric, y_values, 1)
                    p = np.poly1d(z)
                    trend_y = p(x_numeric)

                    fig.add_trace(
                        go.Scatter(
                            x=x_order,
                            y=trend_y,
                            mode="lines",
                            name="Линия тренда",
                            line=dict(dash="dash", width=3, color="white"),
                            showlegend=True,
                            hoverinfo="skip",
                        )
                    )

        fig = _apply_bar_uniformtext(fig)
        fig = apply_chart_background(fig)
        _reasons_chart_caption = (
            "Динамика причин отклонений по причинам"
            if view_type == "По причинам"
            else "Динамика причин отклонений по периодам"
        )
        render_chart(fig, caption_below=_reasons_chart_caption)

        # Summary table - always show by reason (summarized values)
        # Group by reason and sum across all periods
        summary_by_reason = (
            reason_dynamics.groupby("reason of deviation")["Количество"]
            .sum()
            .reset_index()
        )
        summary_by_reason.columns = ["Причина отклонения", "Суммарное количество"]
        summary_by_reason = summary_by_reason.sort_values(
            "Суммарное количество", ascending=False
        )

        st.subheader(f"Сводная таблица по {period_label.lower()}")
        st.markdown(f"**Записей:** {len(summary_by_reason)}")
        _render_html_table(summary_by_reason)
        render_dataframe_excel_csv_downloads(
            summary_by_reason,
            file_stem="reasons_summary",
            key_prefix="reasons_summary",
        )
    else:
        st.warning("Столбец 'reason of deviation' не найден в данных.")


# ==================== DASHBOARD 6: Budget Plan/Fact/Reserve by Project by Period ====================
def dashboard_budget_by_period(df):
    st.header("БДДС")

    # Сетка фильтров; чекбоксы — после фильтров (П.9)
    col1, col2, col3 = st.columns(3)

    with col1:
        period_type = st.selectbox(
            "Группировать по", ["Месяц", "Квартал", "Год"], key="budget_period"
        )
        period_map = {"Месяц": "Month", "Квартал": "Quarter", "Год": "Year"}
        period_type_en = period_map.get(period_type, "Month")

    with col2:
        if "project name" in df.columns:
            projects = ["Все"] + _unique_project_labels_for_select(df["project name"])
            selected_project = st.selectbox(
                "Фильтр по проекту", projects, key="budget_project"
            )
        else:
            selected_project = "Все"

    with col3:
        if "section" in df.columns:
            sections = ["Все"] + sorted(df["section"].dropna().unique().tolist())
            selected_section = st.selectbox(
                "Фильтр по этапу", sections, key="budget_section"
            )
        else:
            selected_section = "Все"

    hide_adjusted = st.checkbox(
        "Скрыть скорректированный бюджет",
        value=True,
        key="budget_period_hide_adjusted",
    )
    hide_reserve = st.checkbox(
        "Скрыть отклонение (столбец на графике)",
        value=False,
        key="budget_period_hide_reserve",
    )

    # Apply filters - fix filtering
    filtered_df = df.copy()
    if selected_project != "Все" and "project name" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["project name"].map(_project_filter_norm_key)
            == _project_filter_norm_key(selected_project)
        ]
    if selected_section != "Все" and "section" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["section"].astype(str).str.strip()
            == str(selected_section).strip()
        ]

    ensure_date_columns(filtered_df)
    if "plan end" in filtered_df.columns:
        pe_y = pd.to_datetime(filtered_df["plan end"], errors="coerce")
        if pe_y.notna().any():
            filtered_df["_filter_year_bdd"] = pe_y.dt.year
            _years = sorted(
                {int(y) for y in filtered_df["_filter_year_bdd"].dropna().unique().tolist()}
            )
            selected_year = st.selectbox(
                "Год",
                ["Все"] + [str(y) for y in _years],
                key="budget_period_year",
            )
            if selected_year != "Все":
                try:
                    filtered_df = filtered_df[
                        filtered_df["_filter_year_bdd"] == int(selected_year)
                    ].copy()
                except (TypeError, ValueError):
                    pass

    # Check for budget columns (нормализуем русские названия)
    ensure_budget_columns(filtered_df)
    has_budget = (
        "budget plan" in filtered_df.columns and "budget fact" in filtered_df.columns
    )

    if not has_budget:
        st.warning("Столбцы бюджета (budget plan, budget fact) не найдены в данных.")
        return

    # Determine adjusted budget column name
    adjusted_budget_col = None
    if "budget adjusted" in filtered_df.columns:
        adjusted_budget_col = "budget adjusted"
    elif "adjusted budget" in filtered_df.columns:
        adjusted_budget_col = "adjusted budget"

    # Determine period column and ensure it exists (create from plan end if missing)
    if "plan end" in filtered_df.columns:
        plan_end = pd.to_datetime(filtered_df["plan end"], errors="coerce")
        mask = plan_end.notna()
        if mask.any():
            if "plan_month" not in filtered_df.columns:
                filtered_df.loc[mask, "plan_month"] = plan_end.loc[mask].dt.to_period("M")
            if "plan_quarter" not in filtered_df.columns:
                filtered_df.loc[mask, "plan_quarter"] = plan_end.loc[mask].dt.to_period("Q")
            if "plan_year" not in filtered_df.columns:
                filtered_df.loc[mask, "plan_year"] = plan_end.loc[mask].dt.to_period("Y")

    if period_type_en == "Month":
        period_col = "plan_month"
        period_label = "Месяц"
    elif period_type_en == "Quarter":
        period_col = "plan_quarter"
        period_label = "Квартал"
    else:
        period_col = "plan_year"
        period_label = "Год"

    if period_col not in filtered_df.columns:
        st.warning(f"Столбец периода '{period_col}' не найден. Убедитесь, что в данных есть колонка дат (например, «Конец План» / plan end).")
        return

    # Отклонение = факт - план (положительное — перерасход, красный; отрицательное — экономия, зелёный)
    filtered_df["budget plan"] = pd.to_numeric(
        filtered_df["budget plan"], errors="coerce"
    )
    filtered_df["budget fact"] = pd.to_numeric(
        filtered_df["budget fact"], errors="coerce"
    )
    filtered_df["reserve budget"] = (
        filtered_df["budget fact"] - filtered_df["budget plan"]
    )

    # Convert adjusted budget to numeric if it exists
    if adjusted_budget_col:
        filtered_df[adjusted_budget_col] = pd.to_numeric(
            filtered_df[adjusted_budget_col], errors="coerce"
        )

    # Колонка для группировки по лотам (лот = section или колонка "лот"/"lot")
    lot_col = "лот" if "лот" in filtered_df.columns else ("lot" if "lot" in filtered_df.columns else "section")
    if lot_col not in filtered_df.columns:
        lot_col = "section"  # fallback для группировки по лотам

    tab_period, tab_lot = st.tabs(["По периодам", "По лотам"])

    with tab_period:
        # Group by period and project
        agg_dict = {"budget plan": "sum", "budget fact": "sum", "reserve budget": "sum"}
        if adjusted_budget_col:
            agg_dict[adjusted_budget_col] = "sum"

        budget_summary = (
            filtered_df.groupby([period_col, "project name"]).agg(agg_dict).reset_index()
        )

        # Store original period values for sorting before formatting
        budget_summary["period_original"] = budget_summary[period_col]
        budget_summary[period_col] = budget_summary[period_col].apply(format_period_ru)

        @st.fragment
        def _budget_period_chart():
            view_type = st.selectbox(
                "Вид отображения", ["По месяцам", "Накопительно"], key="budget_period_view"
            )
            if selected_project != "Все":
                project_data = budget_summary[
                    budget_summary["project name"] == selected_project
                ].copy()
            else:
                agg_dict_all = {
                    "budget plan": "sum",
                    "budget fact": "sum",
                    "reserve budget": "sum",
                    "period_original": "first",
                }
                if adjusted_budget_col:
                    agg_dict_all[adjusted_budget_col] = "sum"
                project_data = (
                    budget_summary.groupby(period_col).agg(agg_dict_all).reset_index()
                )
            if project_data["period_original"].dtype == "object":
                try:
                    project_data["period_sort"] = project_data["period_original"].apply(
                        lambda x: (
                            x if isinstance(x, pd.Period)
                            else (pd.Period(str(x), freq=period_type_en[0]) if pd.notna(x) else None)
                        )
                    )
                    project_data = project_data.sort_values("period_sort").copy()
                    project_data = project_data.drop("period_sort", axis=1)
                except Exception:
                    project_data = project_data.sort_values("period_original").copy()
            else:
                project_data = project_data.sort_values("period_original").copy()
            if view_type == "Накопительно":
                project_data["budget plan"] = project_data["budget plan"].cumsum()
                project_data["budget fact"] = project_data["budget fact"].cumsum()
                project_data["reserve budget"] = project_data["reserve budget"].cumsum()
                if adjusted_budget_col and adjusted_budget_col in project_data.columns:
                    project_data[adjusted_budget_col] = project_data[adjusted_budget_col].cumsum()
                title_suffix = " (накопительно)"
            else:
                title_suffix = ""
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=project_data[period_col],
                    y=project_data["budget plan"].div(1e6),
                    name="БДДС план",
                    marker_color="#2E86AB",
                    text=_finance_bar_text_mln_rub(project_data["budget plan"]),
                    textposition="outside",
                    textfont=dict(size=11, color="#f0f4f8"),
                    customdata=project_data["budget plan"].apply(format_million_rub),
                    hovertemplate="<b>%{x}</b><br>БДДС план: %{customdata}<br><extra></extra>",
                )
            )
            fig.add_trace(
                go.Bar(
                    x=project_data[period_col],
                    y=project_data["budget fact"].div(1e6),
                    name="БДДС факт",
                    marker_color="#A23B72",
                    text=_finance_bar_text_mln_rub(project_data["budget fact"]),
                    textposition="outside",
                    textfont=dict(size=11, color="#f0f4f8"),
                    customdata=project_data["budget fact"].apply(format_million_rub),
                    hovertemplate="<b>%{x}</b><br>БДДС факт: %{customdata}<br><extra></extra>",
                )
            )
            if not hide_reserve:
                dev_vals = project_data["reserve budget"].div(1e6)
                dev_colors = ["#e74c3c" if v >= 0 else "#27ae60" for v in project_data["reserve budget"]]
                fig.add_trace(
                    go.Bar(
                        x=project_data[period_col],
                        y=project_data["reserve budget"].div(1e6),
                        name="Отклонение",
                        marker_color="#e74c3c",
                        text=project_data["reserve budget"].apply(format_million_rub),
                        textposition="outside",
                        textfont=dict(size=11, color="#f0f4f8"),
                        customdata=project_data["reserve budget"].apply(format_million_rub),
                        hovertemplate="<b>%{x}</b><br>Отклонение: %{customdata}<br><extra></extra>",
                        visible="legendonly",
                    )
                )
            if (
                adjusted_budget_col
                and adjusted_budget_col in project_data.columns
                and not hide_adjusted
            ):
                fig.add_trace(
                    go.Bar(
                        x=project_data[period_col],
                        y=project_data[adjusted_budget_col].div(1e6),
                        name="Скорректированный бюджет",
                        marker_color="#F18F01",
                        text=project_data[adjusted_budget_col].apply(format_million_rub),
                        textposition="outside",
                        textfont=dict(size=11, color="#f0f4f8"),
                        customdata=project_data[adjusted_budget_col].apply(format_million_rub),
                        hovertemplate="<b>%{x}</b><br>Скорректированный бюджет: %{customdata}<br><extra></extra>",
                    )
                )
            fig.update_layout(
                title_text="",
                yaxis_title="млн руб.",
                barmode="group",
                bargap=0.18,
                bargroupgap=0.08,
                xaxis=dict(
                    title=dict(text=period_label, standoff=26),
                    tickangle=-45,
                    tickfont=dict(size=10),
                    nticks=18,
                ),
            )
            fig = _apply_finance_bar_label_layout(fig)
            fig = _plotly_legend_horizontal_below_plot(fig)
            if not project_data.empty:
                _ymax = float(
                    np.nanmax(
                        np.concatenate(
                            [
                                project_data["budget plan"].div(1e6).to_numpy(),
                                project_data["budget fact"].div(1e6).to_numpy(),
                                project_data["reserve budget"].div(1e6).to_numpy(),
                            ]
                        )
                    )
                )
                if np.isfinite(_ymax) and _ymax > 0:
                    fig.update_layout(yaxis=dict(range=[0, _ymax * 1.22]))
            fig = apply_chart_background(fig)
            render_chart(fig, caption_below=f"БДДС{title_suffix}", height=600)

        _budget_period_chart()

        # Summary table — суммы в млн руб., строка «Итого» (ТЗ)
        st.subheader(f"Сводка бюджета (по {period_label.lower()})")
        table_display = budget_summary.drop(columns=["period_original"], errors="ignore").copy()
        _tot_vals = {
            period_col: "Итого",
            "project name": "",
            "budget plan": table_display["budget plan"].sum(),
            "budget fact": table_display["budget fact"].sum(),
            "reserve budget": table_display["reserve budget"].sum(),
        }
        if adjusted_budget_col and adjusted_budget_col in table_display.columns:
            _tot_vals[adjusted_budget_col] = table_display[adjusted_budget_col].sum()
        table_display = pd.concat([table_display, pd.DataFrame([_tot_vals])], ignore_index=True)
        budget_cols_table = ["budget plan", "budget fact", "reserve budget"]
        if adjusted_budget_col and adjusted_budget_col in table_display.columns:
            budget_cols_table = budget_cols_table + [adjusted_budget_col]
        for col in budget_cols_table:
            if col in table_display.columns:
                table_display[col] = (table_display[col] / 1e6).round(2).apply(
                    lambda x: f"{float(x):.2f} млн руб." if pd.notna(x) else ""
                )
        table_display = table_display.rename(columns={
            "budget plan": "БДДС план, млн руб.",
            "budget fact": "БДДС факт, млн руб.",
            "reserve budget": "Отклонение (факт − план), млн руб.",
            "project name": "Проект",
            **({adjusted_budget_col: "Скорр. бюджет, млн руб."} if adjusted_budget_col and adjusted_budget_col in table_display.columns else {}),
        })
        if period_col in table_display.columns:
            table_display = table_display.rename(columns={period_col: period_label})
        st.markdown(
            budget_table_to_html(
                table_display,
                finance_deviation_column="Отклонение (факт − план), млн руб.",
            ),
            unsafe_allow_html=True,
        )

    with tab_lot:
        # По лотам: группировка по периоду и лоту (section / лот / lot)
        if lot_col not in filtered_df.columns:
            st.info("Нет колонки для группировки по лотам (section / лот).")
        else:
            agg_dict_lot = {"budget plan": "sum", "budget fact": "sum", "reserve budget": "sum"}
            budget_summary_lot = (
                filtered_df.groupby([period_col, lot_col]).agg(agg_dict_lot).reset_index()
            )
            budget_summary_lot["period_original"] = budget_summary_lot[period_col]
            budget_summary_lot[period_col] = budget_summary_lot[period_col].apply(format_period_ru)

            # hide_reserve_lot = st.checkbox(
            #     "Скрыть отклонение", value=True, key="budget_lot_hide_reserve"
            # )
            hide_reserve_lot = False
            # По лотам: ось Y = этапы (лоты), ось X = млн руб.
            lot_chart_data = (
                budget_summary_lot.groupby(lot_col)
                .agg({"budget plan": "sum", "budget fact": "sum", "reserve budget": "sum"})
                .reset_index()
            )
            # Только лоты с ненулевой суммой — иначе на оси Y сотни «пустых» строк и огромный зазор.
            _lot_abs = (
                lot_chart_data["budget plan"].abs()
                + lot_chart_data["budget fact"].abs()
                + lot_chart_data["reserve budget"].abs()
            )
            lot_chart_data = lot_chart_data[_lot_abs > 1.0].copy()
            if not lot_chart_data.empty:
                lot_chart_data["_sort_key"] = lot_chart_data[
                    ["budget plan", "budget fact"]
                ].abs().max(axis=1)
                lot_chart_data = _limit_bar_categories(
                    lot_chart_data, "_sort_key", max_bars=40, label="лотов"
                )
                lot_chart_data = lot_chart_data.drop(columns=["_sort_key"], errors="ignore")
                lot_chart_data = lot_chart_data.sort_values("budget plan", ascending=True)

            def _wrap_lot_label(text, max_len=25):
                words = str(text).split(" ")
                lines, current = [], ""
                for word in words:
                    if len(current) + len(word) + 1 > max_len:
                        lines.append(current)
                        current = word
                    else:
                        current = (current + " " + word).strip()
                if current:
                    lines.append(current)
                return "<br>".join(lines)

            if lot_chart_data.empty:
                st.info("Нет ненулевых сумм по лотам для выбранных фильтров.")
            else:
                lot_chart_data[lot_col] = lot_chart_data[lot_col].apply(_wrap_lot_label)

                fig_lot = go.Figure()
                fig_lot.add_trace(
                    go.Bar(
                        y=lot_chart_data[lot_col],
                        x=lot_chart_data["budget plan"].div(1e6),
                        name="Бюджет План",
                        marker_color="#2E86AB",
                        text=lot_chart_data["budget plan"].apply(format_million_rub),
                        textposition="outside",
                        textfont=dict(size=12, color="#f0f4f8"),
                        cliponaxis=False,
                        orientation="h",
                    )
                )
                fig_lot.add_trace(
                    go.Bar(
                        y=lot_chart_data[lot_col],
                        x=lot_chart_data["budget fact"].div(1e6),
                        name="Бюджет Факт",
                        marker_color="#A23B72",
                        text=lot_chart_data["budget fact"].apply(format_million_rub),
                        textposition="outside",
                        textfont=dict(size=12, color="#f0f4f8"),
                        cliponaxis=False,
                        orientation="h",
                    )
                )
                fig_lot.add_trace(
                    go.Bar(
                        y=lot_chart_data[lot_col],
                        x=lot_chart_data["reserve budget"].div(1e6),
                        name="Отклонение",
                        marker_color="#e74c3c",
                        text=lot_chart_data["reserve budget"].apply(format_million_rub),
                        textposition="outside",
                        textfont=dict(size=12, color="#f0f4f8"),
                        cliponaxis=False,
                        orientation="h",
                        visible="legendonly",
                    )
                )
                fig_lot.update_layout(
                    title_text="",
                    xaxis_title="млн руб.",
                    yaxis_title="Этапы",
                    barmode="group",
                    bargap=0.22,
                    bargroupgap=0.05,
                    xaxis=dict(tickangle=0, tickfont=dict(size=12), rangemode="tozero"),
                    yaxis=dict(tickfont=dict(size=12), categoryorder="trace"),
                    legend=dict(font=dict(size=12)),
                )
                fig_lot = _apply_finance_bar_label_layout(fig_lot)
                fig_lot = apply_chart_background(fig_lot)
                max_line_len = max(
                    max(len(line) for line in s.split("<br>"))
                    for s in lot_chart_data[lot_col].tolist()
                ) if not lot_chart_data.empty else 20
                left_margin = min(max_line_len * 8.2, 400)
                max_val = float(
                    lot_chart_data[["budget plan", "budget fact"]].max().max() / 1e6
                )
                if not np.isfinite(max_val) or max_val <= 0:
                    max_val = 0.0
                # Умеренный запас справа для подписей «outside», без лишнего «воздуха» на оси
                _x_hi = max_val * (1.18 if max_val > 0 else 1.0)
                fig_lot.update_layout(
                    margin=dict(l=left_margin, r=130, t=80, b=50),
                    xaxis=dict(range=[0, _x_hi], rangemode="tozero"),
                )
                _lot_rows = len(lot_chart_data)
                _plot_height = max(320, min(_lot_rows * 56, 1200))
                render_chart(
                    fig_lot,
                    caption_below="План/факт/отклонение по лотам",
                    height=_plot_height,
                    max_height=1200,
                )

            st.subheader("Сводка бюджета по лотам")
            table_lot = budget_summary_lot.drop(columns=["period_original"], errors="ignore").copy()
            for col in ["budget plan", "budget fact", "reserve budget"]:
                if col in table_lot.columns:
                    table_lot[col] = (table_lot[col] / 1e6).round(2).apply(
                        lambda x: f"{float(x):.2f} млн руб." if pd.notna(x) else ""
                    )
            rename_cols = {
                "budget plan": "Бюджет План, млн руб.",
                "budget fact": "Бюджет Факт, млн руб.",
                "reserve budget": "Отклонение, млн руб.",
            }
            if lot_col in table_lot.columns:
                rename_cols[lot_col] = "Лот"
            table_lot = table_lot.rename(columns=rename_cols)
            st.markdown(
                budget_table_to_html(table_lot, finance_deviation_column="Отклонение, млн руб."),
                unsafe_allow_html=True,
            )


# ==================== DASHBOARD 6.5: Budget Cumulative ====================
def dashboard_budget_cumulative(df):

    st.header("БДДС накопительно")

    col1, col2, col3 = st.columns(3)

    with col1:
        period_type = st.selectbox(
            "Группировать по", ["Месяц", "Квартал", "Год"], key="budget_cum_period"
        )
        period_map = {"Месяц": "Month", "Квартал": "Quarter", "Год": "Year"}
        period_type_en = period_map.get(period_type, "Month")

    with col2:
        if "project name" in df.columns:
            projects = ["Все"] + _unique_project_labels_for_select(df["project name"])
            selected_project = st.selectbox(
                "Фильтр по проекту", projects, key="budget_cum_project"
            )
        else:
            selected_project = "Все"

    col3 = st.columns(1)[0]
    with col3:
        if "section" in df.columns:
            sections = ["Все"] + sorted(df["section"].dropna().unique().tolist())
            selected_section = st.selectbox(
                "Фильтр по этапу", sections, key="budget_cum_section"
            )
        else:
            selected_section = "Все"

    hide_reserve = st.checkbox(
        "Скрыть отклонение (столбец на графике)",
        value=False,
        key="budget_cum_hide_reserve",
    )

    filtered_df = df.copy()
    if selected_project != "Все" and "project name" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["project name"].map(_project_filter_norm_key)
            == _project_filter_norm_key(selected_project)
        ]
    if selected_section != "Все" and "section" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["section"].astype(str).str.strip()
            == str(selected_section).strip()
        ]

    ensure_date_columns(filtered_df)
    if "plan end" in filtered_df.columns:
        pe_y = pd.to_datetime(filtered_df["plan end"], errors="coerce")
        if pe_y.notna().any():
            filtered_df["_filter_year_bdd"] = pe_y.dt.year
            _years = sorted(
                {int(y) for y in filtered_df["_filter_year_bdd"].dropna().unique().tolist()}
            )
            selected_year = st.selectbox(
                "Год",
                ["Все"] + [str(y) for y in _years],
                key="budget_cum_year",
            )
            if selected_year != "Все":
                try:
                    filtered_df = filtered_df[
                        filtered_df["_filter_year_bdd"] == int(selected_year)
                    ].copy()
                except (TypeError, ValueError):
                    pass

    ensure_budget_columns(filtered_df)
    has_budget = (
        "budget plan" in filtered_df.columns and "budget fact" in filtered_df.columns
    )
    if not has_budget:
        st.warning("Столбцы бюджета (budget plan, budget fact) не найдены в данных.")
        return

    adjusted_budget_col = None
    if "budget adjusted" in filtered_df.columns:
        adjusted_budget_col = "budget adjusted"
    elif "adjusted budget" in filtered_df.columns:
        adjusted_budget_col = "adjusted budget"

    if "plan end" in filtered_df.columns:
        plan_end = pd.to_datetime(filtered_df["plan end"], errors="coerce")
        mask = plan_end.notna()
        if mask.any():
            if "plan_month" not in filtered_df.columns:
                filtered_df.loc[mask, "plan_month"] = plan_end.loc[mask].dt.to_period("M")
            if "plan_quarter" not in filtered_df.columns:
                filtered_df.loc[mask, "plan_quarter"] = plan_end.loc[mask].dt.to_period("Q")
            if "plan_year" not in filtered_df.columns:
                filtered_df.loc[mask, "plan_year"] = plan_end.loc[mask].dt.to_period("Y")

    if period_type_en == "Month":
        period_col = "plan_month"
        period_label = "Месяц"
    elif period_type_en == "Quarter":
        period_col = "plan_quarter"
        period_label = "Квартал"
    else:
        period_col = "plan_year"
        period_label = "Год"

    if period_col not in filtered_df.columns:
        st.warning(
            f"Столбец периода '{period_col}' не найден. Нужна дата в данных (например «Конец План» / plan end)."
        )
        return

    filtered_df["budget plan"] = pd.to_numeric(filtered_df["budget plan"], errors="coerce")
    filtered_df["budget fact"] = pd.to_numeric(filtered_df["budget fact"], errors="coerce")
    if adjusted_budget_col:
        filtered_df[adjusted_budget_col] = pd.to_numeric(
            filtered_df[adjusted_budget_col], errors="coerce"
        )
    filtered_df["reserve budget"] = filtered_df["budget fact"] - filtered_df["budget plan"]

    agg_dict = {"budget plan": "sum", "budget fact": "sum", "reserve budget": "sum"}
    if adjusted_budget_col:
        agg_dict[adjusted_budget_col] = "sum"

    budget_summary = (
        filtered_df.groupby([period_col, "project name"], dropna=False).agg(agg_dict).reset_index()
    )
    budget_summary["period_original"] = budget_summary[period_col]

    def _sort_period_df(b: pd.DataFrame) -> pd.DataFrame:
        if b.empty:
            return b
        po = b["period_original"]
        if po.dtype == "object":
            try:
                b = b.copy()
                b["_ps"] = po.apply(
                    lambda x: (
                        x
                        if isinstance(x, pd.Period)
                        else (pd.Period(str(x), freq=period_type_en[0]) if pd.notna(x) else pd.NaT)
                    )
                )
                b = b.sort_values("_ps").drop(columns=["_ps"])
            except Exception:
                b = b.sort_values("period_original")
        else:
            b = b.sort_values("period_original")
        return b

    # --- Таблица «по периоду» (не накопительно)
    st.subheader(f"Сводка бюджета (по {period_label.lower()})")
    tbl_period = _sort_period_df(budget_summary.copy())
    tbl_period_disp = tbl_period.drop(columns=["period_original"], errors="ignore").copy()
    tbl_period_disp[period_col] = tbl_period_disp[period_col].apply(format_period_ru)
    _tot_p = {
        period_col: "Итого",
        "project name": "",
        "budget plan": tbl_period_disp["budget plan"].sum(),
        "budget fact": tbl_period_disp["budget fact"].sum(),
        "reserve budget": tbl_period_disp["reserve budget"].sum(),
    }
    if adjusted_budget_col and adjusted_budget_col in tbl_period_disp.columns:
        _tot_p[adjusted_budget_col] = tbl_period_disp[adjusted_budget_col].sum()
    tbl_period_disp = pd.concat([tbl_period_disp, pd.DataFrame([_tot_p])], ignore_index=True)
    for c in ["budget plan", "budget fact", "reserve budget"] + (
        [adjusted_budget_col] if adjusted_budget_col and adjusted_budget_col in tbl_period_disp.columns else []
    ):
        if c in tbl_period_disp.columns:
            tbl_period_disp[c] = (tbl_period_disp[c] / 1e6).round(2).apply(
                lambda x: f"{float(x):.2f} млн руб." if pd.notna(x) else ""
            )
    ren_p = {
        "budget plan": "БДДС план, млн руб.",
        "budget fact": "БДДС факт, млн руб.",
        "reserve budget": "Отклонение (факт − план), млн руб.",
        "project name": "Проект",
    }
    if adjusted_budget_col and adjusted_budget_col in tbl_period_disp.columns:
        ren_p[adjusted_budget_col] = "Скорр. бюджет, млн руб."
    tbl_period_disp = tbl_period_disp.rename(columns=ren_p)
    if period_col in tbl_period_disp.columns:
        tbl_period_disp = tbl_period_disp.rename(columns={period_col: period_label})
    st.markdown(
        budget_table_to_html(
            tbl_period_disp,
            finance_deviation_column="Отклонение (факт − план), млн руб.",
        ),
        unsafe_allow_html=True,
    )

    # --- Накопительные ряды для графика (по выбранному проекту или сумма по всем)
    bs = _sort_period_df(budget_summary.copy())
    if selected_project != "Все":
        chart_src = bs[
            bs["project name"].map(_project_filter_norm_key)
            == _project_filter_norm_key(selected_project)
        ].copy()
    else:
        agg_c = {"budget plan": "sum", "budget fact": "sum", "reserve budget": "sum"}
        if adjusted_budget_col:
            agg_c[adjusted_budget_col] = "sum"
        chart_src = bs.groupby(period_col, as_index=False).agg(agg_c)
        chart_src["period_original"] = chart_src[period_col]

    chart_src = _sort_period_df(chart_src)
    if chart_src.empty:
        st.info("Нет данных для графика накопительно по выбранным фильтрам.")
    else:
        chart_src["budget plan_cum"] = chart_src["budget plan"].cumsum()
        chart_src["budget fact_cum"] = chart_src["budget fact"].cumsum()
        chart_src["reserve_cum"] = chart_src["budget fact_cum"] - chart_src["budget plan_cum"]
        if adjusted_budget_col and adjusted_budget_col in chart_src.columns:
            chart_src[f"{adjusted_budget_col}_cum"] = chart_src[adjusted_budget_col].cumsum()

        x_labels = chart_src[period_col].apply(format_period_ru)

        fig_cum = go.Figure()
        fig_cum.add_trace(
            go.Bar(
                x=x_labels,
                y=chart_src["budget plan_cum"].div(1e6),
                name="БДДС план (накопительно)",
                marker_color="#2E86AB",
                text=_finance_bar_text_mln_rub(chart_src["budget plan_cum"]),
                textposition="outside",
                textfont=dict(size=11, color="#f0f4f8"),
                customdata=chart_src["budget plan_cum"].apply(format_million_rub),
                hovertemplate="<b>%{x}</b><br>БДДС план (накоп.): %{customdata}<extra></extra>",
            )
        )
        fig_cum.add_trace(
            go.Bar(
                x=x_labels,
                y=chart_src["budget fact_cum"].div(1e6),
                name="БДДС факт (накопительно)",
                marker_color="#A23B72",
                text=_finance_bar_text_mln_rub(chart_src["budget fact_cum"]),
                textposition="outside",
                textfont=dict(size=11, color="#f0f4f8"),
                customdata=chart_src["budget fact_cum"].apply(format_million_rub),
                hovertemplate="<b>%{x}</b><br>БДДС факт (накоп.): %{customdata}<extra></extra>",
            )
        )
        if not hide_reserve:
            fig_cum.add_trace(
                go.Bar(
                    x=x_labels,
                    y=chart_src["reserve_cum"].div(1e6),
                    name="Отклонение (накопительно)",
                    marker_color="#e74c3c",
                    text=_finance_bar_text_mln_rub(chart_src["reserve_cum"]),
                    textposition="outside",
                    textfont=dict(size=11, color="#f0f4f8"),
                    visible="legendonly",
                )
            )
        if adjusted_budget_col and adjusted_budget_col in chart_src.columns:
            fig_cum.add_trace(
                go.Bar(
                    x=x_labels,
                    y=chart_src[f"{adjusted_budget_col}_cum"].div(1e6),
                    name="Скорректированный бюджет (накопительно)",
                    marker_color="#F18F01",
                    text=_finance_bar_text_mln_rub(chart_src[f"{adjusted_budget_col}_cum"]),
                    textposition="outside",
                    textfont=dict(size=11, color="#f0f4f8"),
                )
            )

        fig_cum.update_layout(
            title_text="",
            yaxis_title="млн руб.",
            barmode="group",
            bargap=0.18,
            bargroupgap=0.08,
            xaxis=dict(
                title=dict(text=period_label, standoff=26),
                tickangle=-45,
                tickfont=dict(size=10),
                nticks=18,
            ),
        )
        fig_cum = _apply_finance_bar_label_layout(fig_cum)
        fig_cum = _plotly_legend_horizontal_below_plot(fig_cum)
        _yc = [
            chart_src["budget plan_cum"].div(1e6).max(),
            chart_src["budget fact_cum"].div(1e6).max(),
            chart_src["reserve_cum"].div(1e6).max(),
        ]
        if adjusted_budget_col and f"{adjusted_budget_col}_cum" in chart_src.columns:
            _yc.append(chart_src[f"{adjusted_budget_col}_cum"].div(1e6).max())
        _ymax = float(np.nanmax(_yc)) if _yc else 0.0
        if np.isfinite(_ymax) and _ymax > 0:
            fig_cum.update_layout(yaxis=dict(range=[0, _ymax * 1.22]))
        fig_cum = apply_chart_background(fig_cum)
        render_chart(fig_cum, caption_below="БДДС накопительно (подписи — млн руб.)", height=600)

    # --- Таблица «накопительно»: по каждому проекту — нарастающий итог по периодам
    st.subheader(f"Сводка бюджета (накопительно) по {period_label.lower()}")
    bs2 = _sort_period_df(budget_summary.copy())
    if selected_project != "Все":
        bs2 = bs2[
            bs2["project name"].map(_project_filter_norm_key)
            == _project_filter_norm_key(selected_project)
        ].copy()
        bs2 = _sort_period_df(bs2)
    bs2["budget plan_cum"] = bs2.groupby("project name", dropna=False)["budget plan"].cumsum()
    bs2["budget fact_cum"] = bs2.groupby("project name", dropna=False)["budget fact"].cumsum()
    bs2["reserve_cum"] = bs2["budget fact_cum"] - bs2["budget plan_cum"]
    tbl_c = bs2[
        [
            period_col,
            "project name",
            "budget plan_cum",
            "budget fact_cum",
            "reserve_cum",
        ]
    ].copy()
    if not tbl_c.empty:
        if selected_project != "Все":
            lr = bs2.iloc[-1]
            _tot_c = {
                period_col: "Итого",
                "project name": "",
                "budget plan_cum": lr["budget plan_cum"],
                "budget fact_cum": lr["budget fact_cum"],
                "reserve_cum": lr["reserve_cum"],
            }
        else:
            last_pp = (
                bs2.sort_values("period_original")
                .groupby("project name", dropna=False)
                .last()
                .reset_index()
            )
            _tot_c = {
                period_col: "Итого",
                "project name": "",
                "budget plan_cum": last_pp["budget plan_cum"].sum(),
                "budget fact_cum": last_pp["budget fact_cum"].sum(),
                "reserve_cum": last_pp["budget fact_cum"].sum() - last_pp["budget plan_cum"].sum(),
            }
        tbl_c[period_col] = tbl_c[period_col].apply(format_period_ru)
        tbl_c = pd.concat([tbl_c, pd.DataFrame([_tot_c])], ignore_index=True)
    else:
        tbl_c[period_col] = tbl_c[period_col].apply(format_period_ru)
    for c in ["budget plan_cum", "budget fact_cum", "reserve_cum"]:
        tbl_c[c] = (tbl_c[c] / 1e6).round(2).apply(
            lambda x: f"{float(x):.2f} млн руб." if pd.notna(x) else ""
        )
    tbl_c = tbl_c.rename(
        columns={
            period_col: period_label,
            "project name": "Проект",
            "budget plan_cum": "БДДС план (накоп.), млн руб.",
            "budget fact_cum": "БДДС факт (накоп.), млн руб.",
            "reserve_cum": "Отклонение (факт − план, накоп.), млн руб.",
        }
    )
    st.markdown(
        budget_table_to_html(
            tbl_c,
            finance_deviation_column="Отклонение (факт − план, накоп.), млн руб.",
        ),
        unsafe_allow_html=True,
    )


# ==================== DASHBOARD 7: Budget Plan/Fact/Reserve by Section by Period ====================
def dashboard_budget_by_section(df):
    st.header("💰 БДДС по лотам")
    with st.expander("Вид отображения", expanded=False):
        st.caption("По месяцам или накопительно — переключатель в блоке графика ниже.")

    col1, col2, col3 = st.columns(3)

    with col1:
        period_type = st.selectbox(
            "Группировать по", ["Месяц", "Квартал", "Год"], key="budget_section_period"
        )
        period_map = {"Месяц": "Month", "Квартал": "Quarter", "Год": "Year"}
        period_type_en = period_map.get(period_type, "Month")

    with col2:
        if "section" in df.columns:
            sections = ["Все"] + sorted(df["section"].dropna().unique().tolist())
            selected_section = st.selectbox(
                "Фильтр по этапу", sections, key="budget_section"
            )
        else:
            selected_section = "Все"

    with col3:
        pass

    hide_reserve = st.checkbox(
        "Скрыть отклонение", value=True, key="budget_section_hide_reserve"
    )

    # Apply filters
    filtered_df = df.copy()
    if selected_section != "Все" and "section" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["section"].astype(str).str.strip()
            == str(selected_section).strip()
        ]

    # Check for budget columns (нормализуем русские названия)
    ensure_budget_columns(filtered_df)
    has_budget = (
        "budget plan" in filtered_df.columns and "budget fact" in filtered_df.columns
    )

    if not has_budget:
        st.warning("Столбцы бюджета (budget plan, budget fact) не найдены в данных.")
        return

    # Determine period column
    if period_type_en == "Month":
        period_col = "plan_month"
        period_label = "Месяц"
    elif period_type_en == "Quarter":
        period_col = "plan_quarter"
        period_label = "Квартал"
    else:
        period_col = "plan_year"
        period_label = "Год"

    if period_col not in filtered_df.columns:
        st.warning(f"Столбец периода '{period_col}' не найден.")
        return

    # Отклонение = факт - план (положительное — перерасход, красный; отрицательное — экономия, зелёный)
    filtered_df["budget plan"] = pd.to_numeric(
        filtered_df["budget plan"], errors="coerce"
    )
    filtered_df["budget fact"] = pd.to_numeric(
        filtered_df["budget fact"], errors="coerce"
    )
    filtered_df["reserve budget"] = (
        filtered_df["budget fact"] - filtered_df["budget plan"]
    )

    # Group by period and section
    budget_summary = (
        filtered_df.groupby([period_col, "section"])
        .agg({"budget plan": "sum", "budget fact": "sum", "reserve budget": "sum"})
        .reset_index()
    )

    # Store original period values for sorting before formatting
    budget_summary["period_original"] = budget_summary[period_col]
    budget_summary[period_col] = budget_summary[period_col].apply(format_period_ru)

    @st.fragment
    def _budget_section_chart():
        if selected_section != "Все":
            section_data = budget_summary[
                budget_summary["section"] == selected_section
            ].copy()
            if section_data["period_original"].dtype == "object":
                try:
                    section_data["period_sort"] = section_data["period_original"].apply(
                        lambda x: (
                            x if isinstance(x, pd.Period)
                            else (pd.Period(str(x), freq=period_type_en[0]) if pd.notna(x) else None)
                        )
                    )
                    section_data = section_data.sort_values("period_sort").copy()
                    section_data = section_data.drop("period_sort", axis=1)
                except Exception:
                    section_data = section_data.sort_values("period_original").copy()
            else:
                section_data = section_data.sort_values("period_original").copy()
            view_type = st.selectbox(
                "Вид отображения", ["По месяцам", "Накопительно"], key="budget_section_view"
            )
            if view_type == "Накопительно":
                section_data = section_data.copy()
                section_data["budget plan"] = section_data["budget plan"].cumsum()
                section_data["budget fact"] = section_data["budget fact"].cumsum()
                section_data["reserve budget"] = section_data["reserve budget"].cumsum()
                title_suffix = " (накопительно)"
            else:
                title_suffix = ""
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=section_data[period_col],
                    y=section_data["budget plan"].div(1e6),
                    name="Бюджет План",
                    marker_color="#2E86AB",
                    text=section_data["budget plan"].apply(format_million_rub),
                    textposition="outside",
                    textfont=dict(size=18, color="white"),
                )
            )
            fig.add_trace(
                go.Bar(
                    x=section_data[period_col],
                    y=section_data["budget fact"].div(1e6),
                    name="Бюджет Факт",
                    marker_color="#A23B72",
                    text=section_data["budget fact"].apply(format_million_rub),
                    textposition="outside",
                    textfont=dict(size=18, color="white"),
                )
            )
            if not hide_reserve:
                dev_colors_sec = ["#e74c3c" if v >= 0 else "#27ae60" for v in section_data["reserve budget"]]
                fig.add_trace(
                    go.Bar(
                        x=section_data[period_col],
                        y=section_data["reserve budget"].div(1e6),
                        name="Отклонение",
                        marker_color=dev_colors_sec,
                        text=section_data["reserve budget"].apply(format_million_rub),
                        textposition="outside",
                        textfont=dict(size=18, color="white"),
                    )
                )
            fig.update_layout(
                title_text="",
                xaxis_title=dict(text=period_label, font=dict(size=20)),
                yaxis_title=dict(text="млн руб.", font=dict(size=20)),
                barmode="group",
                xaxis=dict(tickangle=0, tickfont=dict(size=16)),
                yaxis=dict(tickfont=dict(size=16)),
                legend=dict(font=dict(size=18)),
                height=600,
            )
            _lot_budget_caption = f"План/факт/отклонение по лотам{title_suffix}"
        else:
            # Все этапы: ось Y = этапы, ось X = млн руб.
            section_chart_data = (
                budget_summary.groupby("section")
                .agg({"budget plan": "sum", "budget fact": "sum", "reserve budget": "sum"})
                .reset_index()
            )
            section_chart_data = section_chart_data.sort_values("budget plan", ascending=True)
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    y=section_chart_data["section"],
                    x=section_chart_data["budget plan"].div(1e6),
                    name="Бюджет План",
                    marker_color="#2E86AB",
                    text=section_chart_data["budget plan"].apply(format_million_rub),
                    textposition="outside",
                    textfont=dict(size=18, color="white"),
                    orientation="h",
                )
            )
            fig.add_trace(
                go.Bar(
                    y=section_chart_data["section"],
                    x=section_chart_data["budget fact"].div(1e6),
                    name="Бюджет Факт",
                    marker_color="#A23B72",
                    text=section_chart_data["budget fact"].apply(format_million_rub),
                    textposition="outside",
                    textfont=dict(size=18, color="white"),
                    orientation="h",
                )
            )
            if not hide_reserve:
                dev_colors_sec = ["#e74c3c" if v >= 0 else "#27ae60" for v in section_chart_data["reserve budget"]]
                fig.add_trace(
                    go.Bar(
                        y=section_chart_data["section"],
                        x=section_chart_data["reserve budget"].div(1e6),
                        name="Отклонение",
                        marker_color=dev_colors_sec,
                        text=section_chart_data["reserve budget"].apply(format_million_rub),
                        textposition="outside",
                        textfont=dict(size=18, color="white"),
                        orientation="h",
                    )
                )
            fig.update_layout(
                title_text="",
                xaxis_title=dict(text="млн руб.", font=dict(size=20)),
                yaxis_title=dict(text="Этапы", font=dict(size=20)),
                barmode="group",
                xaxis=dict(tickangle=0, tickfont=dict(size=16)),
                yaxis=dict(tickfont=dict(size=16), categoryorder="trace order"),
                legend=dict(font=dict(size=18)),
                height=max(400, len(section_chart_data) * 44),
            )
            _lot_budget_caption = "План/факт/отклонение по лотам"
        fig = _apply_finance_bar_label_layout(fig)
        fig = apply_chart_background(fig)
        render_chart(fig, caption_below=_lot_budget_caption)

    _budget_section_chart()

    # Summary table — в млн руб., два знака после запятой
    st.subheader("Сводка бюджета по периоду")
    table_section = budget_summary.drop(columns=["period_original"], errors="ignore").copy()
    for col in ["budget plan", "budget fact", "reserve budget"]:
        if col in table_section.columns:
            table_section[col] = (table_section[col] / 1e6).round(2).apply(
                lambda x: f"{float(x):.2f} млн руб." if pd.notna(x) else ""
            )
    table_section = table_section.rename(columns={
        "budget plan": "Бюджет План, млн руб.",
        "budget fact": "Бюджет Факт, млн руб.",
        "reserve budget": "Отклонение, млн руб.",
    })
    st.markdown(
        budget_table_to_html(table_section, finance_deviation_column="Отклонение, млн руб."),
        unsafe_allow_html=True,
    )


# ==================== DASHBOARD: БДР (бюджет доходов и расходов) ====================
def dashboard_bdr(df):
    """
    БДР — план/факт расходов: колонки ищутся по шаблонам (расходы / budget plan / budget fact).
    В таблице и на графике: План расходов, Факт расходов, Отклонение (факт − план).
    """
    st.header("БДР. План/факт расходов")

    if df is None or not hasattr(df, "columns") or df.empty:
        st.warning("⚠️ Нет данных для отображения. Загрузите данные проекта.")
        return

    # Определяем колонки для доходов и расходов
    def find_col(df, variants):
        for v in variants:
            for c in df.columns:
                if str(c).strip().lower() == v.lower() or v.lower() in str(c).lower():
                    return c
        return None

    revenue_col = find_col(
        df,
        ["доходы", "доход", "revenue", "income", "Бюджет План", "budget plan"],
    )
    expense_col = find_col(
        df,
        ["расходы", "расход", "expense", "Бюджет Факт", "budget fact"],
    )
    ensure_budget_columns(df)
    if revenue_col is None and "budget plan" in df.columns:
        revenue_col = "budget plan"
    if expense_col is None and "budget fact" in df.columns:
        expense_col = "budget fact"

    if revenue_col is None or expense_col is None:
        st.warning(
            "Для отчёта БДР нужны столбцы плана и факта расходов "
            "(например «Бюджет План» / «Бюджет Факт» или пары колонок по шаблону из ТЗ)."
        )
        return

    # Фильтры — в одном стиле с БДДС: строка 1 — Группировать по, Фильтр по проекту; строка 2 — Фильтр по этапу
    col1, col2, col3 = st.columns(3)
    with col1:
        period_type = st.selectbox(
            "Группировать по", ["Месяц", "Квартал", "Год"], key="bdr_period"
        )
        period_map = {"Месяц": "Month", "Квартал": "Quarter", "Год": "Year"}
        period_type_en = period_map.get(period_type, "Month")
    with col2:
        if "project name" in df.columns:
            projects = ["Все"] + _unique_project_labels_for_select(df["project name"])
            selected_project = st.selectbox(
                "Фильтр по проекту", projects, key="bdr_project"
            )
        else:
            selected_project = "Все"

    col3 = st.columns(1)[0]
    with col3:
        if "section" in df.columns:
            sections = ["Все"] + sorted(df["section"].dropna().unique().tolist())
            selected_section = st.selectbox(
                "Фильтр по этапу", sections, key="bdr_section"
            )
        else:
            selected_section = "Все"

    # Период
    if period_type_en == "Month":
        period_col = "plan_month"
        period_label = "Месяц"
    elif period_type_en == "Quarter":
        period_col = "plan_quarter"
        period_label = "Квартал"
    else:
        period_col = "plan_year"
        period_label = "Год"

    if period_col not in df.columns:
        st.warning(f"Столбец периода «{period_col}» не найден. Добавьте даты в данные.")
        return

    filtered_df = df.copy()
    if selected_project != "Все" and "project name" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["project name"].map(_project_filter_norm_key)
            == _project_filter_norm_key(selected_project)
        ]
    if selected_section != "Все" and "section" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["section"].astype(str).str.strip()
            == str(selected_section).strip()
        ]

    filtered_df["_plan_exp"] = pd.to_numeric(filtered_df[revenue_col], errors="coerce")
    filtered_df["_fact_exp"] = pd.to_numeric(filtered_df[expense_col], errors="coerce")
    filtered_df["_deviation"] = filtered_df["_fact_exp"] - filtered_df["_plan_exp"]

    agg_dict = {"_plan_exp": "sum", "_fact_exp": "sum", "_deviation": "sum"}
    bdr_summary = (
        filtered_df.groupby(period_col).agg(agg_dict).reset_index()
    )
    bdr_summary = bdr_summary.rename(
        columns={
            "_plan_exp": "План расходов",
            "_fact_exp": "Факт расходов",
            "_deviation": "Отклонение",
        }
    )

    bdr_summary["Период"] = bdr_summary[period_col].apply(format_period_ru)

    @st.fragment
    def _bdr_chart():
        view_type = st.selectbox(
            "Вид отображения", ["По месяцам", "Накопительно"], key="bdr_view"
        )
        chart_df = bdr_summary.copy()
        if view_type == "Накопительно":
            chart_df["План расходов"] = chart_df["План расходов"].cumsum()
            chart_df["Факт расходов"] = chart_df["Факт расходов"].cumsum()
            chart_df["Отклонение"] = chart_df["Факт расходов"] - chart_df["План расходов"]
            title_suffix = " (накопительно)"
        else:
            title_suffix = ""
        fig = go.Figure()
        x_vals = chart_df["Период"]
        fig.add_trace(
            go.Bar(
                x=x_vals,
                y=chart_df["План расходов"].div(1e6),
                name="План расходов",
                marker_color="#2E86AB",
                text=_finance_bar_text_mln_rub(chart_df["План расходов"]),
                textposition="outside",
                textfont=dict(size=11, color="#f0f4f8"),
            )
        )
        fig.add_trace(
            go.Bar(
                x=x_vals,
                y=chart_df["Факт расходов"].div(1e6),
                name="Факт расходов",
                marker_color="#A23B72",
                text=_finance_bar_text_mln_rub(chart_df["Факт расходов"]),
                textposition="outside",
                textfont=dict(size=11, color="#f0f4f8"),
            )
        )
        dev_colors = [
            "#e74c3c" if v >= 0 else "#27ae60" for v in chart_df["Отклонение"]
        ]
        fig.add_trace(
            go.Bar(
                x=x_vals,
                y=chart_df["Отклонение"].div(1e6),
                name="Отклонение",
                marker_color=dev_colors,
                text=_finance_bar_text_mln_rub(chart_df["Отклонение"]),
                textposition="outside",
                textfont=dict(size=11, color="#f0f4f8"),
            )
        )
        fig.update_layout(
            title_text="",
            xaxis_title=period_label,
            yaxis_title="млн руб.",
            barmode="group",
            xaxis=dict(tickangle=-45, tickfont=dict(size=10), nticks=18),
            margin=dict(b=100),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        )
        if not chart_df.empty:
            _ymax = float(
                np.nanmax(
                    np.concatenate(
                        [
                            chart_df["План расходов"].div(1e6).to_numpy(),
                            chart_df["Факт расходов"].div(1e6).to_numpy(),
                            chart_df["Отклонение"].div(1e6).to_numpy(),
                        ]
                    )
                )
            )
            _ymin = float(
                np.nanmin(
                    np.concatenate(
                        [
                            chart_df["План расходов"].div(1e6).to_numpy(),
                            chart_df["Факт расходов"].div(1e6).to_numpy(),
                            chart_df["Отклонение"].div(1e6).to_numpy(),
                        ]
                    )
                )
            )
            if np.isfinite(_ymax) and np.isfinite(_ymin):
                pad = max(abs(_ymax), abs(_ymin), 1e-6) * 0.2
                fig.update_layout(yaxis=dict(range=[_ymin - pad, _ymax + pad]))
        fig = _apply_finance_bar_label_layout(fig)
        fig = apply_chart_background(fig)
        render_chart(fig, caption_below=f"БДР — план/факт расходов{title_suffix}")

    _bdr_chart()

    st.subheader("Сводка бюджета по периоду")
    display_df = bdr_summary[
        [c for c in ["Период", "План расходов", "Факт расходов", "Отклонение"] if c in bdr_summary.columns]
    ].copy()
    display_df = display_df.rename(columns={"Период": period_label})
    for col in ["План расходов", "Факт расходов", "Отклонение"]:
        if col in display_df.columns:
            display_df[col] = (display_df[col] / 1e6).round(2).apply(
                lambda x: f"{float(x):.2f} млн руб." if pd.notna(x) else ""
            )
    display_df = display_df.rename(columns={
        "План расходов": "План расходов, млн руб.",
        "Факт расходов": "Факт расходов, млн руб.",
        "Отклонение": "Отклонение, млн руб.",
    })
    st.markdown(
        budget_table_to_html(display_df, finance_deviation_column="Отклонение, млн руб."),
        unsafe_allow_html=True,
    )

    if "project name" in filtered_df.columns:
        st.subheader("Сводка бюджета по проекту")
        by_p = (
            filtered_df.groupby("project name", dropna=False)
            .agg({"_plan_exp": "sum", "_fact_exp": "sum"})
            .reset_index()
        )
        by_p["Итого"] = by_p["_fact_exp"] - by_p["_plan_exp"]
        proj_tbl = pd.DataFrame(
            {
                "Проект": by_p["project name"].astype(str),
                "План, млн руб.": (by_p["_plan_exp"] / 1e6).round(2).apply(
                    lambda x: f"{float(x):.2f}" if pd.notna(x) else ""
                ),
                "Факт, млн руб.": (by_p["_fact_exp"] / 1e6).round(2).apply(
                    lambda x: f"{float(x):.2f}" if pd.notna(x) else ""
                ),
                "Итого (отклонение), млн руб.": (by_p["Итого"] / 1e6).round(2).apply(
                    lambda x: f"{float(x):.2f}" if pd.notna(x) else ""
                ),
            }
        )
        st.caption(
            "Колонка «Итого» — отклонение (факт − план) по проекту за выбранные фильтры."
        )
        st.markdown(
            budget_table_to_html(
                proj_tbl,
                finance_deviation_column="Итого (отклонение), млн руб.",
            ),
            unsafe_allow_html=True,
        )


# ==================== DASHBOARD 8.6: RD Delay Chart ====================
def dashboard_rd_delay(df):
    # st.subheader("⏱️ Просрочка выдачи РД")
    st.subheader("Просрочка выдачи РД")

    # Find column names (they might have different formats)
    # Try to find columns by partial name matching
    def find_column(df, possible_names):
        """Find column by possible names"""
        for col in df.columns:
            # Normalize column name: remove newlines, extra spaces, normalize case
            col_normalized = str(col).replace("\n", " ").replace("\r", " ").strip()
            col_lower = col_normalized.lower()

            for name in possible_names:
                name_lower = name.lower().strip()
                # Exact match (case insensitive)
                if name_lower == col_lower:
                    return col
                # Substring match
                if name_lower in col_lower or col_lower in name_lower:
                    return col
                # Check if all key words from name are in column
                name_words = [w for w in name_lower.split() if len(w) > 2]
                if name_words and all(word in col_lower for word in name_words):
                    return col

        # Special handling for RD count column with key words
        if any(
            "разделов" in n.lower() and "рд" in n.lower() and "договор" in n.lower()
            for n in possible_names
        ):
            for col in df.columns:
                col_lower = str(col).lower().replace("\n", " ").replace("\r", " ")
                key_words = ["разделов", "рд", "договор", "количество"]
                if all(word in col_lower for word in key_words if len(word) > 3):
                    return col

        return None

    # Find required columns
    # Column for Y-axis: "Отклонение разделов РД" (exact match from CSV file)
    # This is column 17 in the CSV file (after header row)
    rd_deviation_col = None

    # First try exact match
    if "Отклонение разделов РД" in df.columns:
        rd_deviation_col = "Отклонение разделов РД"
    else:
        # Try with find_column function for variations
        rd_deviation_col = find_column(
            df,
            [
                "Отклонение разделов РД",
                "Отклонение разделов рд",
                "отклонение разделов рд",
                "Отклон. Количества разделов РД",
                "Отклонение количества разделов РД",
                "Отклон. разделов РД",
                "Отклонение разделов РД по Договору",
            ],
        )

        # Special handling: if not found, try to find by key words
        if not rd_deviation_col:
            for col in df.columns:
                col_lower = str(col).lower().replace("\n", " ").replace("\r", " ")
                key_words = ["отклон", "раздел", "рд"]
                if all(word in col_lower for word in key_words if len(word) > 3):
                    rd_deviation_col = col
                    break

    if not rd_deviation_col:
        st.warning("⚠️ Колонка 'Отклонение разделов РД' не найдена.")
        return

    # Find required columns
    plan_start_col = (
        "plan start"
        if "plan start" in df.columns
        else find_column(df, ["Старт План", "План Старт"])
    )
    project_col = (
        "project name"
        if "project name" in df.columns
        else find_column(df, ["Проект", "project"])
    )
    section_col = (
        "section" if "section" in df.columns else find_column(df, ["Раздел", "section"])
    )
    task_col = (
        "task name"
        if "task name" in df.columns
        else find_column(df, ["Задача", "task"])
    )
    rd_plan_col = find_column(df, ["РД по Договору", "РД по договору", "Количество разделов РД по Договору"])
    rd_fact_col = find_column(
        df,
        [
            "Выдано в производство работ",
            "Разработано",
            "В работе",
            "Выдана подрядчику",
            "Всего загружено",
            "выдано в производство",
        ],
    )
    plan_end_col = "plan end" if "plan end" in df.columns else find_column(df, ["Конец План", "План Конец", "План окончания ПД/РД"])
    actual_finish_col = (
        "actual finish"
        if "actual finish" in df.columns
        else find_column(
            df,
            ["actual finish", "Фактическое окончание", "Окончание факт", "Факт окончание"],
        )
    )
    fact_end_col = (
        actual_finish_col
        if actual_finish_col and actual_finish_col in df.columns
        else (
            "base end"
            if "base end" in df.columns
            else find_column(df, ["Конец Факт", "Факт Конец", "Факт окончания ПД/РД"])
        )
    )

    on_approval_col_rd = find_column(df, ["На согласовании", "согласовании"])
    in_production_col_rd = find_column(
        df,
        [
            "Выдано в производство работ",
            "Разработано",
            "В работе",
            "производство работ",
            "в производство",
        ],
    )
    contractor_transfer_col_rd = find_column(
        df,
        [
            "Выдана подрядчику",
            "Передано подрядчику",
            "подрядчику",
            "TransferToCustomer",
        ],
    )
    rework_col_rd = find_column(df, ["На доработке", "доработке"])

    # Check if required columns exist (section optional — заменён фильтром по виду документации)
    missing_cols = []
    if not project_col or project_col not in df.columns:
        missing_cols.append("Проект (project name)")
    if not task_col or task_col not in df.columns:
        missing_cols.append("Задача (task name)")

    if missing_cols:
        st.warning(f"⚠️ Отсутствуют необходимые колонки: {', '.join(missing_cols)}")
        st.info("Пожалуйста, убедитесь, что файл содержит все необходимые колонки.")
        return

    def _to_numeric_series(series):
        return pd.to_numeric(
            series.astype(str)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False),
            errors="coerce",
        ).fillna(0.0)

    def _to_datetime_series(series):
        return pd.to_datetime(series.astype(str), errors="coerce", dayfirst=True, format="mixed")

    # Add filters
    st.subheader("Фильтры")
    st.markdown(
        """
        <style>
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="column"]) div[data-testid="column"] {
            flex: 1 1 0% !important;
            min-width: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    filter_col1, filter_col2 = st.columns(2, gap="small")

    # Project filter (несколько проектов)
    selected_projects: list[str] = []
    with filter_col1:
        try:
            projects = _unique_project_labels_for_select(df[project_col])
            selected_projects = st.multiselect(
                "Фильтр по проектам",
                options=projects,
                default=projects,
                key="rd_delay_projects",
                help="Ничего не выбрано — показываются все проекты.",
                placeholder="Выберите проекты",
            )
        except Exception as e:
            st.error(f"Ошибка при загрузке списка проектов: {str(e)}")
            return

    # Filter by RD section kind
    selected_section = "Все"
    with filter_col2:
        if section_col and section_col in df.columns:
            section_options = sorted(
                {
                    str(v).strip()
                    for v in df[section_col].dropna().tolist()
                    if str(v).strip() and str(v).strip().lower() not in ("nan", "none")
                },
                key=lambda x: x.casefold(),
            )
            selected_section = st.selectbox(
                ("Фильтр по виду раздела ПД" if is_pd else "Фильтр по виду раздела РД"),
                ["Все"] + section_options,
                key="rd_delay_section",
            )
        else:
            st.caption("Колонка раздела РД не найдена.")

    selected_statuses_rd: list[str] = []
    rd_status_options_rd: list[str] = []
    if on_approval_col_rd and on_approval_col_rd in df.columns:
        rd_status_options_rd.append("На согласовании")
    if in_production_col_rd and in_production_col_rd in df.columns:
        rd_status_options_rd.append("Выдано в производство работ")
    if contractor_transfer_col_rd and contractor_transfer_col_rd in df.columns:
        rd_status_options_rd.append("Передано подрядчику")
    if rework_col_rd and rework_col_rd in df.columns:
        rd_status_options_rd.append("На доработке")
    if rd_status_options_rd:
        selected_statuses_rd = st.pills(
            "Фильтр по статусу РД",
            rd_status_options_rd,
            selection_mode="multi",
            default=rd_status_options_rd,
            key="rd_delay_status_filter",
            help="Пустой выбор — все статусы.",
        )
        if selected_statuses_rd is None:
            selected_statuses_rd = []
    else:
        st.caption("Нет колонок статусов РД для фильтра.")

    # Apply filters
    filtered_df = df.copy()

    if selected_projects:
        _pk_set = {_project_filter_norm_key(p) for p in selected_projects}
        filtered_df = filtered_df[
            filtered_df[project_col].map(_project_filter_norm_key).isin(_pk_set)
        ]

    if selected_section != "Все" and section_col and section_col in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df[section_col].astype(str).str.strip() == selected_section
        ]

    if (
        selected_statuses_rd
        and rd_status_options_rd
        and set(selected_statuses_rd) != set(rd_status_options_rd)
    ):
        status_mask = pd.Series([False] * len(filtered_df), index=filtered_df.index)
        if (
            "На согласовании" in selected_statuses_rd
            and on_approval_col_rd
            and on_approval_col_rd in filtered_df.columns
        ):
            on_approval_series = (
                filtered_df[on_approval_col_rd]
                .astype(str)
                .str.replace(",", ".", regex=False)
            )
            on_approval_numeric = pd.to_numeric(
                on_approval_series, errors="coerce"
            ).fillna(0)
            status_mask = status_mask | (on_approval_numeric > 0)
        if (
            "Выдано в производство работ" in selected_statuses_rd
            and in_production_col_rd
            and in_production_col_rd in filtered_df.columns
        ):
            in_production_series = (
                filtered_df[in_production_col_rd]
                .astype(str)
                .str.replace(",", ".", regex=False)
            )
            in_production_numeric = pd.to_numeric(
                in_production_series, errors="coerce"
            ).fillna(0)
            status_mask = status_mask | (in_production_numeric > 0)
        if (
            "Передано подрядчику" in selected_statuses_rd
            and contractor_transfer_col_rd
            and contractor_transfer_col_rd in filtered_df.columns
        ):
            contractor_series = (
                filtered_df[contractor_transfer_col_rd]
                .astype(str)
                .str.replace(",", ".", regex=False)
            )
            contractor_numeric = pd.to_numeric(
                contractor_series, errors="coerce"
            ).fillna(0)
            status_mask = status_mask | (contractor_numeric > 0)
        if (
            "На доработке" in selected_statuses_rd
            and rework_col_rd
            and rework_col_rd in filtered_df.columns
        ):
            rework_series = (
                filtered_df[rework_col_rd].astype(str).str.replace(",", ".", regex=False)
            )
            rework_numeric = pd.to_numeric(rework_series, errors="coerce").fillna(0)
            status_mask = status_mask | (rework_numeric > 0)
        filtered_df = filtered_df[status_mask].copy()

    if project_col and project_col in filtered_df.columns:
        filtered_df = _project_column_apply_canonical(filtered_df, project_col)

    if filtered_df.empty:
        st.info("Нет данных для выбранных фильтров.")
        return

    # TESSA: наименование задачи для колонки «Задача» (если загружен tessa_tasks_data)
    if task_col and task_col in filtered_df.columns:
        try:
            _td = _rd_tessa_task_display_series(filtered_df, task_col)
            if _td is not None:
                filtered_df = filtered_df.copy()
                filtered_df["_task_display_tessa"] = _td
        except Exception:
            pass

    # Prepare data for "Просрочка выдачи РД"
    # X-axis: "Задача" (each task is a separate bar)
    # Y-axis: "Отклонение разделов РД" (deviation values)
    try:
        rd_deviation_raw = filtered_df[rd_deviation_col].copy()
        rd_deviation_str = rd_deviation_raw.astype(str)
        rd_deviation_str = rd_deviation_str.replace(
            ["nan", "None", "NaN", "NaT", "<NA>", "None"], ""
        )
        rd_deviation_str = rd_deviation_str.str.strip()
        rd_deviation_str = rd_deviation_str.str.replace(",", ".", regex=False)
        rd_deviation_str = rd_deviation_str.replace("", "0")
        filtered_df["rd_deviation_numeric"] = pd.to_numeric(
            rd_deviation_str, errors="coerce"
        ).fillna(0)

        # Числовые колонки для % выполнения РД/ПД
        if rd_plan_col and rd_plan_col in filtered_df.columns:
            filtered_df["_rd_plan_n"] = _to_numeric_series(filtered_df[rd_plan_col])
        else:
            filtered_df["_rd_plan_n"] = 0
        if rd_fact_col and rd_fact_col in filtered_df.columns:
            filtered_df["_rd_fact_n"] = _to_numeric_series(filtered_df[rd_fact_col])
        else:
            filtered_df["_rd_fact_n"] = 0
        filtered_df["_plan_end_dt"] = (
            _to_datetime_series(filtered_df[plan_end_col])
            if plan_end_col and plan_end_col in filtered_df.columns
            else pd.NaT
        )
        filtered_df["_fact_end_dt"] = (
            _to_datetime_series(filtered_df[fact_end_col])
            if fact_end_col and fact_end_col in filtered_df.columns
            else pd.NaT
        )

        # Группировка: по проекту (фильтр по разделу заменён на вид документации)
        show_by_tasks = False

        if show_by_tasks:
            # Prepare data for chart - each task is a separate bar
            if section_col and section_col in filtered_df.columns:
                filtered_df["Задача_полная"] = (
                    filtered_df[section_col].astype(str)
                    + " | "
                    + filtered_df[task_col].astype(str)
                )
            else:
                filtered_df["Задача_полная"] = filtered_df[task_col].astype(str)

            agg_map = {"rd_deviation_numeric": "sum", "_rd_plan_n": "sum", "_rd_fact_n": "sum"}
            chart_data = (
                filtered_df.groupby("Задача_полная", as_index=False).agg(agg_map)
            )
            chart_data = chart_data.rename(columns={"rd_deviation_numeric": "Отклонение разделов РД"})
            chart_data["Задача"] = chart_data["Задача_полная"]

            # % выполнения РД/ПД = факт / план * 100
            chart_data["% выполнения РД/ПД"] = ""
            mask_plan = chart_data["_rd_plan_n"] > 0
            chart_data.loc[mask_plan, "% выполнения РД/ПД"] = (
                (chart_data.loc[mask_plan, "_rd_fact_n"] / chart_data.loc[mask_plan, "_rd_plan_n"] * 100)
                .round(1)
                .astype(str)
                .str.replace(r"\.0$", "", regex=True)
            ) + "%"
            chart_data.loc[~mask_plan, "% выполнения РД/ПД"] = "—"
            chart_data["_overdue_share_pct"] = 0.0
            chart_data.loc[mask_plan, "_overdue_share_pct"] = (
                chart_data.loc[mask_plan, "Отклонение разделов РД"]
                / chart_data.loc[mask_plan, "_rd_plan_n"]
                * 100.0
            ).round(1)

            chart_data = chart_data.sort_values("Отклонение разделов РД", ascending=False)
            y_column = "Задача_полная"
            y_title = "Задача"
        else:
            # Group by project and sum deviations
            if project_col and project_col in filtered_df.columns:
                agg_map = {"rd_deviation_numeric": "sum", "_rd_plan_n": "sum", "_rd_fact_n": "sum"}
                chart_data = (
                    filtered_df.groupby(project_col, as_index=False).agg(agg_map)
                )
                chart_data = chart_data.rename(
                    columns={"rd_deviation_numeric": "Отклонение разделов РД", project_col: "Проект"}
                )
                chart_data["% выполнения РД/ПД"] = ""
                mask_plan = chart_data["_rd_plan_n"] > 0
                chart_data.loc[mask_plan, "% выполнения РД/ПД"] = (
                    (chart_data.loc[mask_plan, "_rd_fact_n"] / chart_data.loc[mask_plan, "_rd_plan_n"] * 100)
                    .round(1)
                    .astype(str)
                    .str.replace(r"\.0$", "", regex=True)
                ) + "%"
                chart_data.loc[~mask_plan, "% выполнения РД/ПД"] = "—"
                chart_data["_overdue_share_pct"] = 0.0
                chart_data.loc[mask_plan, "_overdue_share_pct"] = (
                    chart_data.loc[mask_plan, "Отклонение разделов РД"]
                    / chart_data.loc[mask_plan, "_rd_plan_n"]
                    * 100.0
                ).round(1)
                chart_data = chart_data.sort_values("Отклонение разделов РД", ascending=False)
                y_column = "Проект"
                y_title = "Проект"
            else:
                st.info("Нет данных для построения графика.")
                return

        if chart_data.empty:
            st.info("Нет данных для построения графика.")
            return

        # Текст на столбцах: отклонение и % выполнения РД/ПД
        text_values = []
        for _, row in chart_data.iterrows():
            val = row["Отклонение разделов РД"]
            pct = row.get("% выполнения РД/ПД", "") or ""
            overdue_pct = row.get("_overdue_share_pct", 0)
            plan_total = row.get("_rd_plan_n", 0)
            if pd.notna(val):
                dev_str = f"{int(round(val, 0))}"
                if pd.notna(plan_total) and float(plan_total) > 0:
                    plan_str = f"{int(round(float(plan_total), 0))}"
                    pct_str = f"{float(overdue_pct):.0f}%"
                    text_values.append(f"{dev_str} из {plan_str} ({pct_str})")
                else:
                    text_values.append(f"{dev_str} ({pct})" if pct and str(pct).strip() != "—" else dev_str)
            else:
                text_values.append(pct if pct else "")

        # Create horizontal bar chart
        chart_data["_severity"] = chart_data["Отклонение разделов РД"].clip(lower=0)
        severity_max = float(chart_data["_severity"].max()) if not chart_data.empty else 0.0
        severity_max = max(severity_max, 1.0)
        fig = px.bar(
            chart_data,
            x="Отклонение разделов РД",
            y=y_column,
            orientation="h",
            title=None,
            labels={
                y_column: y_title,
                "Отклонение разделов РД": "Отклонение разделов РД",
            },
            text=text_values,
            color="_severity",
            color_continuous_scale=[
                (0.0, "#27AE60"),
                (0.5, "#F1C40F"),
                (1.0, "#C0392B"),
            ],
            range_color=(0.0, severity_max),
        )

        # Format text labels (same as "Отклонение от базового плана")
        fig.update_traces(
            textposition="outside",
            textfont=dict(size=14, color="white"),
            marker=dict(line=dict(width=1, color="white")),
            showlegend=False,  # Hide legend
        )

        # Add vertical line at 0 to separate positive and negative deviations (without annotation)
        fig.add_vline(x=0, line_dash="dash", line_color="gray")

        # Set category order to show largest values at top (descending order)
        # For horizontal bars, reverse the list so largest is at top
        category_list = chart_data[y_column].tolist()
        fig.update_layout(
            xaxis_title="Отклонение разделов РД",
            yaxis_title=y_title,
            height=max(
                600, len(chart_data) * 40
            ),  # Adjust height based on number of items
            showlegend=False,
            coloraxis_showscale=False,
            yaxis=dict(
                tickangle=0,  # Horizontal labels
                categoryorder="array",
                categoryarray=list(
                    reversed(category_list)
                ),  # Reverse to show largest at top
            ),
            bargap=0.1,  # Reduce gap between bars to make them appear larger
        )

        fig = _apply_bar_uniformtext(fig)
        fig = apply_chart_background(fig)
        render_chart(fig, caption_below="Просрочка выдачи РД")

        if plan_end_col and plan_end_col in filtered_df.columns:
            month_df = filtered_df[filtered_df["_plan_end_dt"].notna()].copy()
            if not month_df.empty:
                today_ts = pd.Timestamp(date.today())
                month_df["_month"] = month_df["_plan_end_dt"].dt.to_period("M")
                month_df["_done_n"] = np.where(
                    month_df["_rd_fact_n"] > 0,
                    np.minimum(month_df["_rd_plan_n"], month_df["_rd_fact_n"]),
                    0.0,
                )
                month_df["_remaining_n"] = (
                    month_df["_rd_plan_n"] - month_df["_done_n"]
                ).clip(lower=0.0)
                month_df["_overdue_n"] = np.where(
                    (month_df["_remaining_n"] > 0)
                    & (month_df["_plan_end_dt"] < today_ts),
                    month_df["_remaining_n"],
                    0.0,
                )
                month_df["_delta_n"] = (
                    month_df["_remaining_n"] - month_df["_overdue_n"]
                ).clip(lower=0.0)

                monthly = (
                    month_df.groupby("_month", as_index=False)
                    .agg(
                        plan=("_rd_plan_n", "sum"),
                        done=("_done_n", "sum"),
                        delta=("_delta_n", "sum"),
                        overdue=("_overdue_n", "sum"),
                    )
                    .sort_values("_month")
                )
                monthly = monthly[monthly["plan"] > 0].copy()
                if not monthly.empty:
                    monthly["Месяц"] = monthly["_month"].apply(
                        lambda p: f"{RUSSIAN_MONTHS.get(p.month, str(p.month))} {p.year}"
                    )
                    monthly["Выполнено"] = (monthly["done"] / monthly["plan"] * 100).round(1)
                    monthly["Разница план/факт"] = (
                        monthly["delta"] / monthly["plan"] * 100
                    ).round(1)
                    monthly["Просрочено"] = (
                        monthly["overdue"] / monthly["plan"] * 100
                    ).round(1)

                    monthly_plot_df = monthly.melt(
                        id_vars=["Месяц"],
                        value_vars=["Выполнено", "Разница план/факт", "Просрочено"],
                        var_name="Статус",
                        value_name="Процент",
                    )
                    monthly_plot_df["Подпись"] = monthly_plot_df["Процент"].apply(
                        lambda v: f"{v:.0f}%" if pd.notna(v) and float(v) > 0 else ""
                    )

                    st.subheader("Динамика по месяцам")
                    fig_months = px.bar(
                        monthly_plot_df,
                        x="Месяц",
                        y="Процент",
                        color="Статус",
                        barmode="stack",
                        text="Подпись",
                        color_discrete_map={
                            "Выполнено": "#27AE60",
                            "Разница план/факт": "#F39C12",
                            "Просрочено": "#C0392B",
                        },
                    )
                    fig_months.update_layout(
                        xaxis_title="Месяц",
                        yaxis_title="% РД",
                        yaxis=dict(range=[0, 100], ticksuffix="%"),
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=1.02,
                            xanchor="left",
                            x=0,
                            title_text="",
                        ),
                        height=520,
                    )
                    fig_months.update_traces(textposition="inside", textfont=dict(size=10))
                    fig_months = apply_chart_background(fig_months)
                    render_chart(fig_months, caption_below="Динамика по месяцам")

        st.subheader("Детальная таблица")
        detail_cipher_col = find_column(
            filtered_df,
            ["Шифр полный", "Полный шифр", "DivisionCipher", "Cipher", "Аббревиатура"],
        )
        forecast_date_col = find_column(
            filtered_df,
            [
                "Прогнозная дата выдачи разделов",
                "Прогнозная дата выдачи РД",
                "Прогнозная дата",
                "ForecastDate",
                "Forecast date",
            ],
        )
        upload_date_col = find_column(
            filtered_df,
            [
                "Дата загрузки раздела РД",
                "Дата загрузки",
                "Completed",
                "CompletedDate",
                "UploadDate",
                "Upload date",
            ],
        )
        production_issue_date_col = find_column(
            filtered_df,
            [
                "Дата выдачи РД в производство работ",
                "Дата выдачи в производство работ",
                "Дата выдачи в производство",
                "Дата выдачи РД",
                "Дата выдачи",
            ],
        )

        detail_df = filtered_df.copy()
        detail_df["_detail_section_name"] = (
            detail_df[section_col].astype(str).str.strip()
            if section_col and section_col in detail_df.columns
            else (
                detail_df[task_col].astype(str).str.strip()
                if task_col and task_col in detail_df.columns
                else ""
            )
        )
        detail_df["_detail_cipher"] = (
            detail_df[detail_cipher_col].astype(str).str.strip()
            if detail_cipher_col and detail_cipher_col in detail_df.columns
            else ""
        )
        detail_df["_detail_plan_date"] = (
            _to_datetime_series(detail_df[plan_end_col])
            if plan_end_col and plan_end_col in detail_df.columns
            else pd.Series(pd.NaT, index=detail_df.index)
        )
        detail_df["_detail_forecast_date"] = (
            _to_datetime_series(detail_df[forecast_date_col])
            if forecast_date_col and forecast_date_col in detail_df.columns
            else detail_df["_detail_plan_date"].copy()
        )
        detail_df["_detail_upload_date"] = (
            _to_datetime_series(detail_df[upload_date_col])
            if upload_date_col and upload_date_col in detail_df.columns
            else pd.Series(pd.NaT, index=detail_df.index)
        )
        detail_df["_detail_production_issue_date"] = (
            _to_datetime_series(detail_df[production_issue_date_col])
            if production_issue_date_col and production_issue_date_col in detail_df.columns
            else detail_df["_fact_end_dt"].copy()
        )

        def _resolve_rd_status_label(row) -> str:
            if contractor_transfer_col_rd and contractor_transfer_col_rd in row.index:
                if float(_to_numeric_series(pd.Series([row[contractor_transfer_col_rd]])).iloc[0]) > 0:
                    return "Передано подрядчику"
            if in_production_col_rd and in_production_col_rd in row.index:
                if float(_to_numeric_series(pd.Series([row[in_production_col_rd]])).iloc[0]) > 0:
                    return "Выдано в производство работ"
            if on_approval_col_rd and on_approval_col_rd in row.index:
                if float(_to_numeric_series(pd.Series([row[on_approval_col_rd]])).iloc[0]) > 0:
                    return "На согласовании"
            if rework_col_rd and rework_col_rd in row.index:
                if float(_to_numeric_series(pd.Series([row[rework_col_rd]])).iloc[0]) > 0:
                    return "На доработке"
            return "Не выдано"

        detail_df["_detail_status"] = detail_df.apply(_resolve_rd_status_label, axis=1)
        detail_df["_detail_actual_issue_date"] = detail_df["_detail_production_issue_date"].where(
            detail_df["_detail_production_issue_date"].notna(),
            detail_df["_detail_upload_date"],
        )
        detail_df["_detail_actual_issue_date"] = detail_df["_detail_actual_issue_date"].where(
            detail_df["_detail_actual_issue_date"].notna(),
            detail_df["_detail_plan_date"],
        )
        detail_df["_detail_delta_vs_contract"] = (
            detail_df["_detail_actual_issue_date"] - detail_df["_detail_plan_date"]
        ).dt.days
        detail_df["_detail_delta_vs_contract"] = detail_df["_detail_delta_vs_contract"].fillna(0)
        detail_df["_detail_delta_vs_forecast"] = (
            detail_df["_detail_actual_issue_date"] - detail_df["_detail_forecast_date"]
        ).dt.days

        def _fmt_date_or_blank(series: pd.Series) -> pd.Series:
            parsed = pd.to_datetime(series, errors="coerce")
            return parsed.dt.strftime("%d.%m.%Y").fillna("")

        detail_table = pd.DataFrame(
            {
                "Наименование разделов работ": detail_df["_detail_section_name"],
                "Шифр полный": detail_df["_detail_cipher"],
                "Дата выдачи разделов по договору": _fmt_date_or_blank(
                    detail_df["_detail_plan_date"]
                ),
                "Прогнозная дата выдачи разделов": _fmt_date_or_blank(
                    detail_df["_detail_forecast_date"]
                ),
                "Статус": detail_df["_detail_status"],
                "Дата загрузки раздела РД": _fmt_date_or_blank(detail_df["_detail_upload_date"]),
                "Дата выдачи РД в производство работ": _fmt_date_or_blank(
                    detail_df["_detail_production_issue_date"]
                ),
                "Отклонение от даты по договору, дн.": detail_df[
                    "_detail_delta_vs_contract"
                ].apply(lambda x: int(round(float(x), 0)) if pd.notna(x) else ""),
                "Отклонение от прогнозной даты, дн.": detail_df[
                    "_detail_delta_vs_forecast"
                ].apply(lambda x: int(round(float(x), 0)) if pd.notna(x) else ""),
            }
        )

        if project_col and project_col in detail_df.columns:
            detail_table.insert(0, "Проект", detail_df[project_col].astype(str).str.strip())

        sort_col1, sort_col2 = st.columns([3, 1])
        with sort_col1:
            detail_sort_column = st.selectbox(
                "Сортировка по колонке",
                options=list(detail_table.columns),
                index=0,
                key="rd_delay_detail_sort_col",
            )
        with sort_col2:
            detail_sort_desc = st.checkbox(
                "Отображать в порядке убывания",
                value=False,
                key="rd_delay_detail_sort_desc",
            )

        def _detail_sort_series(table: pd.DataFrame, column: str) -> pd.Series:
            if "дата" in column.lower():
                return pd.to_datetime(table[column], format="%d.%m.%Y", errors="coerce")
            if "дн." in column.lower():
                return pd.to_numeric(table[column], errors="coerce")
            return table[column].astype(str).str.casefold()

        detail_table = detail_table.assign(
            _sort_key=_detail_sort_series(detail_table, detail_sort_column)
        ).sort_values(
            by=["_sort_key", "Наименование разделов работ"],
            ascending=[not detail_sort_desc, True],
            na_position="last",
        )
        detail_table = detail_table.drop(columns=["_sort_key"], errors="ignore").reset_index(
            drop=True
        )

        if detail_table.empty and not filtered_df.empty:
            st.info("Детальная таблица не собрана, хотя строки в источнике есть.")
        elif detail_table.empty:
            st.info("Нет данных для детальной таблицы.")
        else:
            st.markdown(format_dataframe_as_html(detail_table), unsafe_allow_html=True)
            render_dataframe_excel_csv_downloads(
                detail_table,
                file_stem="rd_delay_detail",
                key_prefix="rd_delay_detail",
            )

        # Summary table (с % выполнения РД/ПД и раскраской отклонения: >0 красный, <=0 зелёный)
        st.subheader("Сводка по просрочке")
        if show_by_tasks:
            summary_table = chart_data[
                ["Задача_полная", "Отклонение разделов РД", "% выполнения РД/ПД"]
            ].copy()
            summary_table = summary_table.rename(columns={"Задача_полная": "Задача"})
        else:
            summary_table = chart_data[["Проект", "Отклонение разделов РД", "% выполнения РД/ПД"]].copy()
        if "Отклонение разделов РД" in summary_table.columns:
            summary_table["Отклонение разделов РД"] = summary_table["Отклонение разделов РД"].apply(
                lambda x: int(round(float(x), 0)) if pd.notna(x) else ""
            )
        # Раскраска: отклонение > 0 — красный, <= 0 — зелёный
        # st.table(style_dataframe_for_dark_theme(
        #     summary_table,
        #     days_column="Отклонение разделов РД",
        # ))
        st.markdown(format_dataframe_as_html(summary_table), unsafe_allow_html=True)
        render_dataframe_excel_csv_downloads(
            summary_table,
            file_stem="rd_delay_summary",
            key_prefix="rd_delay_summary",
        )

        # Таблица: План окончания ПД/РД и Факт окончания ПД/РД
        if (plan_end_col and plan_end_col in filtered_df.columns) or (fact_end_col and fact_end_col in filtered_df.columns):
            st.subheader("План и факт окончания ПД/РД")
            date_df = filtered_df.copy()
            if plan_end_col and plan_end_col in date_df.columns:
                date_df["План окончания ПД/РД"] = _to_datetime_series(date_df[plan_end_col])
                date_df["План окончания ПД/РД"] = date_df["План окончания ПД/РД"].dt.strftime("%d.%m.%Y")
            else:
                date_df["План окончания ПД/РД"] = ""
            if fact_end_col and fact_end_col in date_df.columns:
                date_df["Факт окончания ПД/РД"] = _to_datetime_series(date_df[fact_end_col])
                date_df["Факт окончания ПД/РД"] = date_df["Факт окончания ПД/РД"].dt.strftime("%d.%m.%Y")
            else:
                date_df["Факт окончания ПД/РД"] = ""
            tab_cols = []
            if project_col and project_col in date_df.columns:
                tab_cols.append(project_col)
            if section_col and section_col in date_df.columns:
                tab_cols.append(section_col)
            tab_cols.extend(["План окончания ПД/РД", "Факт окончания ПД/РД"])
            date_table = date_df[[c for c in tab_cols if c in date_df.columns]].drop_duplicates()
            rename_map = {}
            if project_col and project_col in date_table.columns:
                rename_map[project_col] = "Проект"
            if section_col and section_col in date_table.columns:
                rename_map[section_col] = "Направление раздела РД"
            date_table = date_table.rename(columns=rename_map)
            st.markdown(
                plan_fact_dates_table_to_html(
                    date_table,
                    plan_date_column="План окончания ПД/РД",
                    fact_date_column="Факт окончания ПД/РД",
                ),
                unsafe_allow_html=True,
            )

        # Summary metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            total_deviation = chart_data["Отклонение разделов РД"].sum()
            st.metric(
                "Сумма отклонений",
                f"{total_deviation:,.0f}" if pd.notna(total_deviation) else "Н/Д",
            )
        with col2:
            positive_deviation = chart_data[chart_data["Отклонение разделов РД"] > 0][
                "Отклонение разделов РД"
            ].sum()
            st.metric(
                "Положительные отклонения",
                f"{positive_deviation:,.0f}" if pd.notna(positive_deviation) else "0",
            )
        with col3:
            negative_deviation = chart_data[chart_data["Отклонение разделов РД"] < 0][
                "Отклонение разделов РД"
            ].sum()
            st.metric(
                "Отрицательные отклонения",
                f"{negative_deviation:,.0f}" if pd.notna(negative_deviation) else "0",
            )

    except Exception as e:
        st.error(f"Ошибка при построении графика 'Просрочка выдачи РД': {str(e)}")


# ==================== DASHBOARD 8.6.5: Technique Visualization ====================
def dashboard_technique(df):
    st.header("График движения рабочей силы")

    technique_df = st.session_state.get("technique_data", None)
    resources_df = st.session_state.get("resources_data", None)

    def _cols_lc_gdrs(pdf):
        if pdf is None or getattr(pdf, "empty", True):
            return []
        return [str(c).lower().strip() for c in pdf.columns]

    def _technique_shape_from_resources(pdf_res):
        """Общая выгрузка web часто попадает только в resources_data."""
        if pdf_res is None or getattr(pdf_res, "empty", True):
            return None
        cl = _cols_lc_gdrs(pdf_res)
        if any("среднее значение за день" in c for c in cl):
            return pdf_res
        if any("среднее за недел" in c for c in cl):
            return pdf_res
        n_d = sum(1 for c in pdf_res.columns if _gdrs_header_is_dd_mm_yyyy(c))
        if n_d >= 2 and any("тип ресурсов" in c for c in cl):
            return pdf_res
        return None

    if technique_df is None or technique_df.empty:
        technique_df = _technique_shape_from_resources(resources_df)

    if technique_df is None or technique_df.empty:
        st.warning(
            "Для отображения аналитики по технике необходимо загрузить файл с данными о технике."
        )
        st.info(
            "Ожидаемые колонки: Проект, Контрагент, Период, План, Среднее за месяц или Среднее за неделю, 1–5 неделя; «Дельта» / «Дельта (%)» в отчёте: отклонение и отклонение %."
        )
        return

    key_prefix = "gdrs_technique"
    work_df = technique_df.copy()
    work_df.columns = [
        str(c).replace("\ufeff", "").replace("\n", " ").replace("\r", " ").strip()
        for c in work_df.columns
    ]
    _plan_src_t = _gdrs_resolve_plan_column(work_df)
    if _plan_src_t and _plan_src_t != "План":
        work_df["План"] = work_df[_plan_src_t]

    date_cols_found = [c for c in work_df.columns if _gdrs_header_is_dd_mm_yyyy(c)]
    _daily_dates: list[pd.Timestamp] = []
    if date_cols_found:
        _hdr_norm = (
            pd.Series(date_cols_found)
            .astype(str)
            .str.replace(r"\.{2,3}", ".", regex=True)
            .str.strip()
        )
        _parsed = pd.to_datetime(_hdr_norm, errors="coerce", dayfirst=True).dropna()
        if not _parsed.empty:
            _daily_dates = sorted(
                list({pd.Timestamp(d).normalize() for d in _parsed.tolist()})
            )
    # Даты из заголовков (ДД.ММ.ГГГГ / DD.MM.YY) — для фильтра периода по дням.
    _daily_dates: list[pd.Timestamp] = []
    if date_cols_found:
        _hdr_norm = (
            pd.Series(date_cols_found)
            .astype(str)
            .str.replace(r"\.{2,3}", ".", regex=True)
            .str.strip()
        )
        _daily_dates = [
            pd.Timestamp(x).normalize()
            for x in pd.to_datetime(_hdr_norm, errors="coerce", dayfirst=True).dropna().tolist()
        ]
        _daily_dates = sorted(list({d for d in _daily_dates}))
    _period_missing_or_empty = (
        "Период" not in work_df.columns
        or work_df["Период"].astype(str).str.strip().replace({"nan": "", "None": ""}).eq("").all()
    )
    if date_cols_found and _period_missing_or_empty:
        # Формируем период по датам заголовков (для файлов, где период не задан отдельной колонкой).
        _hdr_ser = pd.Series(date_cols_found).astype(str).str.replace(r"\.{2,3}", ".", regex=True)
        _parsed_header_dates = pd.to_datetime(
            _hdr_ser, errors="coerce", dayfirst=True
        ).dropna()
        _period_from_headers = None
        if not _parsed_header_dates.empty:
            _period_from_headers = _parsed_header_dates.iloc[0].to_period("M")

        id_cols = [c for c in ["Проект", "Контрагент", "тип ресурсов", "data_source"]
                   if c in work_df.columns]
        avg_month_col = None
        for c in work_df.columns:
            cl = str(c).lower()
            if "среднее" in cl and ("за месяц" in cl or "количество ресурсов" in cl):
                vals = pd.to_numeric(work_df[c], errors="coerce")
                if vals.notna().any() and (vals != 0).any():
                    avg_month_col = c
                    break
        if not avg_month_col:
            for c in reversed(list(work_df.columns)):
                cl = str(c).lower()
                if "среднее" in cl and not cl.startswith("тип"):
                    vals = pd.to_numeric(work_df[c], errors="coerce")
                    if vals.notna().any() and (vals != 0).any():
                        avg_month_col = c
                        break

        for dc in date_cols_found:
            work_df[dc] = pd.to_numeric(work_df[dc], errors="coerce")

        if id_cols:
            agg_spec = {dc: (dc, "mean") for dc in date_cols_found}
            if "План" in work_df.columns and "План" not in id_cols:
                agg_spec["План"] = ("План", "first")
            for _wk in range(1, 6):
                wn = f"{_wk} неделя"
                if wn in work_df.columns and wn not in id_cols:
                    agg_spec[wn] = (wn, "first")
            agg = work_df.groupby(id_cols, dropna=False).agg(**agg_spec).reset_index()
            agg["Среднее за месяц"] = agg[date_cols_found].mean(axis=1).round(1)
            if _period_from_headers is not None:
                agg["Период"] = _period_from_headers
            if avg_month_col and avg_month_col in work_df.columns:
                month_avg = work_df.groupby(id_cols, dropna=False)[avg_month_col].first().reset_index()
                month_avg["_avg_num"] = pd.to_numeric(month_avg[avg_month_col], errors="coerce")
                if month_avg["_avg_num"].notna().any() and (month_avg["_avg_num"] != 0).any():
                    agg["Среднее за месяц"] = month_avg["_avg_num"].values
            agg = agg.drop(columns=date_cols_found, errors="ignore")
            work_df = agg
        else:
            work_df["Среднее за месяц"] = work_df[date_cols_found].mean(axis=1).round(1)
            if _period_from_headers is not None:
                work_df["Период"] = _period_from_headers
            work_df = work_df.drop(columns=date_cols_found, errors="ignore")

    def find_column_by_partial(df, possible_names):
        """Find column by possible names (exact or partial match)"""
        for col in df.columns:
            col_lower = str(col).lower().strip()
            for name in possible_names:
                name_lower = str(name).lower().strip()
                if (
                    name_lower == col_lower
                    or name_lower in col_lower
                    or col_lower in name_lower
                ):
                    return col
        return None

    # sample_resources_data.csv: Проект, Контрагент, Период, План, Среднее за месяц, 1–5 неделя, Дельта, Дельта (%)
    # Use Russian column names directly

    # Check required columns - Контрагент is essential
    if "Контрагент" not in work_df.columns:
        # Try to find contractor column by partial match
        contractor_col = find_column_by_partial(
            work_df,
            [
                "Контрагент",
                "контрагент",
                "Подразделение",
                "подразделение",
                "contractor",
            ],
        )
        if contractor_col:
            work_df["Контрагент"] = work_df[contractor_col]
        else:
            st.error(f"Отсутствует необходимая колонка 'Контрагент'")
            st.info(f"Доступные колонки: {', '.join(work_df.columns)}")
            return

    # Find week columns dynamically - also try partial match
    week_columns = []
    for week_num in range(1, 7):
        week_col = f"{week_num} неделя"
        if week_col in work_df.columns:
            week_columns.append(week_col)
        else:
            # Try to find by partial match
            found_col = find_column_by_partial(
                work_df,
                [
                    week_col,
                    f"{week_num} недел",
                    f"недел {week_num}",
                    f"week {week_num}",
                ],
            )
            if found_col:
                week_columns.append(found_col)

    # Check if we have any data
    if work_df.empty:
        st.warning("⚠️ Данные пусты после обработки.")
        return

    # Process numeric columns
    # Process План
    if "План" in work_df.columns:
        work_df["План_numeric"] = pd.to_numeric(
            work_df["План"].astype(str).str.replace(",", ".").str.replace(" ", ""),
            errors="coerce",
        ).fillna(0)
    else:
        work_df["План_numeric"] = 0

    # Process week columns - convert to numeric, handle empty strings
    for week_col in week_columns:
        work_df[f"{week_col}_numeric"] = pd.to_numeric(
            work_df[week_col]
            .astype(str)
            .str.replace(",", ".")
            .str.replace(" ", "")
            .replace("", "0"),
            errors="coerce",
        ).fillna(0)

    # Факт: при наличии недельных колонок берём сумму 1..5 недели (приоритетнее средних).
    if week_columns:
        week_numeric_cols = [f"{col}_numeric" for col in week_columns]
        work_df["week_sum"] = work_df[week_numeric_cols].sum(axis=1)
    elif "Среднее за месяц" in work_df.columns:
        work_df["Среднее_за_месяц_numeric"] = pd.to_numeric(
            work_df["Среднее за месяц"]
            .astype(str)
            .str.replace(",", ".")
            .str.replace(" ", ""),
            errors="coerce",
        ).fillna(0)
        work_df["week_sum"] = work_df["Среднее_за_месяц_numeric"]
    elif "Среднее за неделю" in work_df.columns:
        work_df["Среднее_за_неделю_numeric"] = pd.to_numeric(
            work_df["Среднее за неделю"]
            .astype(str)
            .str.replace(",", ".")
            .str.replace(" ", ""),
            errors="coerce",
        ).fillna(0)
        _nw = len(week_columns) if week_columns else 4
        work_df["week_sum"] = work_df["Среднее_за_неделю_numeric"] * _nw
    else:
        work_df["week_sum"] = 0

    # Process Дельта (Delta) if available - try to find column by partial match
    delta_col = None
    if "Дельта" in work_df.columns:
        delta_col = "Дельта"
    else:
        delta_col = find_column_by_partial(
            work_df, ["Дельта", "дельта", "delta", "Delta", "Дельта (без %)"]
        )

    if delta_col and delta_col in work_df.columns:
        work_df["Дельта_numeric"] = pd.to_numeric(
            work_df[delta_col].astype(str).str.replace(",", ".").str.replace(" ", ""),
            errors="coerce",
        ).fillna(0)
    else:
        # Calculate delta as plan - fact (week_sum)
        work_df["Дельта_numeric"] = work_df["План_numeric"] - work_df["week_sum"]

    # Process Дельта (%) (Delta %) if available - extract numeric value from percentage string
    # Try to find column by partial match
    delta_pct_col = None
    if "Дельта (%)" in work_df.columns:
        delta_pct_col = "Дельта (%)"
    else:
        delta_pct_col = find_column_by_partial(
            work_df,
            [
                "Дельта (%)",
                "Дельта %",
                "дельта (%)",
                "дельта %",
                "Delta %",
                "delta %",
                "Дельта(%)",
                "Дельта%",
            ],
        )

    if delta_pct_col and delta_pct_col in work_df.columns:

        def extract_percentage(value):
            """Extract numeric value from percentage string like '-90%' or '90%', or numeric value"""
            if pd.isna(value):
                return 0
            # If already numeric, return as is
            if isinstance(value, (int, float)):
                return float(value)
            # Otherwise, try to extract from string
            value_str = str(value).strip()
            # Remove % sign and convert to float
            value_str = value_str.replace("%", "").replace(",", ".").replace(" ", "")
            try:
                return float(value_str)
            except:
                return 0

        work_df["Дельта_процент_numeric"] = work_df[delta_pct_col].apply(
            extract_percentage
        )
    else:
        # Calculate delta percentage if we have delta and plan
        work_df["Дельта_процент_numeric"] = 0.0
        if "Дельта_numeric" in work_df.columns and "План_numeric" in work_df.columns:
            mask = work_df["План_numeric"] != 0
            work_df.loc[mask, "Дельта_процент_numeric"] = (
                work_df.loc[mask, "Дельта_numeric"] / work_df.loc[mask, "План_numeric"]
            ) * 100
        work_df["Дельта_процент_numeric"] = work_df["Дельта_процент_numeric"].fillna(0)

    # Find Проект column
    # Период: нельзя искать через «месяц» в подстроке — матчится «среднее … за месяц» и ломает графики.
    src_period = _gdrs_resolve_period_column(work_df)
    if src_period:
        if src_period != "Период":
            def parse_period(period_val):
                if pd.isna(period_val):
                    return None
                period_str = str(period_val).strip()
                if "." in period_str:
                    parts = period_str.split(".")
                    if len(parts) >= 2:
                        month_part = parts[0].strip()
                        year_part = parts[1].strip()
                        try:
                            year = int(year_part)
                            if year < 100:
                                year = 2000 + year
                            return f"{month_part}.{year}"
                        except Exception:
                            pass
                return period_str

            work_df["Период"] = work_df[src_period].apply(parse_period)

    has_plan_data = (
        "План_numeric" in work_df.columns
        and work_df["План_numeric"].sum() > 0
    )

    project_col = None
    if "Проект" in work_df.columns:
        project_col = "Проект"
    else:
        project_col = find_column_by_partial(
            work_df, ["Проект", "проект", "project", "Project"]
        )

    period_col = _gdrs_resolve_period_column(work_df)
    # Жёсткий fallback: если «Период» не найден, восстанавливаем его из датовых заголовков.
    if period_col is None:
        _date_cols_fb = [c for c in work_df.columns if _gdrs_header_is_dd_mm_yyyy(c)]
        if _date_cols_fb:
            _hdr_fb = pd.Series(_date_cols_fb).astype(str).str.replace(r"\.{2,3}", ".", regex=True)
            _dt_fb = pd.to_datetime(_hdr_fb, errors="coerce", dayfirst=True).dropna()
            if not _dt_fb.empty:
                work_df = work_df.copy()
                work_df["Период"] = _dt_fb.iloc[0].to_period("M")
                period_col = "Период"

    col1, col2, col3 = st.columns(3)

    with col1:
        if project_col and project_col in work_df.columns:
            all_projects = _unique_project_labels_for_select(work_df[project_col])
            selected_projects = st.multiselect(
                "Фильтр по проектам (можно выбрать несколько)",
                all_projects,
                default=all_projects if len(all_projects) <= 3 else all_projects[:3],
                key="technique_projects",
                placeholder="Выберите проекты",
            )
        else:
            selected_projects = []
            st.info("Колонка 'Проект' не найдена")

    with col2:
        if "Контрагент" in work_df.columns:
            contractors = ["Все"] + sorted(
                work_df["Контрагент"].dropna().unique().tolist()
            )
            selected_contractor = st.selectbox(
                "Фильтр по контрагенту", contractors, key="technique_contractor"
            )
        else:
            selected_contractor = "Все"
            st.info("Колонка 'Контрагент' не найдена")

    selected_periods = []
    selected_period_from = "Все"
    selected_period_to = "Все"
    period_value_by_label = {}
    period_labels_sorted = []

    def _gdrs_period_value_to_ts(v):
        if v is None:
            return pd.NaT
        try:
            ts = pd.to_datetime(v, errors="coerce", dayfirst=True)
            if pd.notna(ts):
                return ts.normalize()
        except Exception:
            pass
        s = str(v).strip().lower()
        if not s:
            return pd.NaT
        # "ноя.25" / "ноя 25" / "ноябрь 2025" -> 01.MM.YYYY
        m = re.match(r"^([а-яa-z\.]+)[\s\.\-_/]*(\d{2,4})$", s, flags=re.IGNORECASE)
        if m:
            mon_raw, yy_raw = m.group(1), m.group(2)
            mon_raw = mon_raw.replace(".", "")
            mon_map = {
                "янв": 1, "январь": 1,
                "фев": 2, "февраль": 2,
                "мар": 3, "март": 3,
                "апр": 4, "апрель": 4,
                "май": 5, "мая": 5,
                "июн": 6, "июнь": 6,
                "июл": 7, "июль": 7,
                "авг": 8, "август": 8,
                "сен": 9, "сент": 9, "сентябрь": 9,
                "окт": 10, "октябрь": 10,
                "ноя": 11, "ноябрь": 11,
                "дек": 12, "декабрь": 12,
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
            }
            mm = mon_map.get(mon_raw)
            if mm:
                y = int(yy_raw)
                if y < 100:
                    y = 2000 + y
                try:
                    return pd.Timestamp(year=y, month=mm, day=1)
                except Exception:
                    return pd.NaT
        return pd.NaT

    with col3:
        if period_col and period_col in work_df.columns:
            raw_vals = (
                work_df[period_col].dropna().astype(str).str.strip().tolist()
            )
            raw_vals = [v for v in raw_vals if v]
            uniq_vals = sorted(set(raw_vals))
            if uniq_vals:
                parsed = [(v, _gdrs_period_value_to_ts(v)) for v in uniq_vals]
                has_any_ts = any(pd.notna(ts) for _, ts in parsed)
                if has_any_ts:
                    parsed.sort(key=lambda it: (0, it[1]) if pd.notna(it[1]) else (1, str(it[0])))
                    for v, ts in parsed:
                        label = ts.strftime("%d.%m.%Y") if pd.notna(ts) else str(v)
                        if label not in period_value_by_label:
                            period_value_by_label[label] = v
                            period_labels_sorted.append(label)
                else:
                    period_labels_sorted = sorted(uniq_vals)
                    period_value_by_label = {v: v for v in period_labels_sorted}

                selected_period_from = st.selectbox(
                    "Период с (дата)",
                    ["Все"] + period_labels_sorted,
                    key=f"{key_prefix}_period_from",
                )
                selected_period_to = st.selectbox(
                    "Период по (дата)",
                    ["Все"] + period_labels_sorted,
                    key=f"{key_prefix}_period_to",
                )
                if period_labels_sorted:
                    i_from = period_labels_sorted.index(selected_period_from) if selected_period_from in period_labels_sorted else 0
                    i_to = period_labels_sorted.index(selected_period_to) if selected_period_to in period_labels_sorted else (len(period_labels_sorted) - 1)
                    if i_from > i_to:
                        i_from, i_to = i_to, i_from
                    selected_periods = [
                        period_value_by_label[lbl]
                        for lbl in period_labels_sorted[i_from : i_to + 1]
                    ]
            else:
                st.info("Нет значений периода")
        else:
            st.info("Колонка 'Период' не найдена")
    # Apply filters
    filtered_df = work_df.copy()
    if selected_projects and project_col and project_col in filtered_df.columns:
        selected_project_keys = {
            _project_filter_norm_key(p)
            for p in selected_projects
            if _project_filter_norm_key(p)
        }
        project_mask = filtered_df[project_col].map(_project_filter_norm_key).isin(selected_project_keys)
        filtered_df = filtered_df[project_mask]
    if selected_contractor != "Все" and "Контрагент" in filtered_df.columns:
        # Use string comparison with strip to handle whitespace
        filtered_df = filtered_df[
            filtered_df["Контрагент"].astype(str).str.strip()
            == str(selected_contractor).strip()
        ]

    if filtered_df.empty:
        st.info("Нет данных для отображения с выбранными фильтрами.")
        return

    # Ensure Контрагент column exists and has values
    if (
        "Контрагент" not in filtered_df.columns
        or filtered_df["Контрагент"].isna().all()
    ):
        st.error("Колонка 'Контрагент' отсутствует или пуста после фильтрации.")
        return

    # Remove rows where Контрагент is NaN before grouping
    filtered_df = filtered_df[filtered_df["Контрагент"].notna()].copy()

    if filtered_df.empty:
        st.info("Нет данных с указанными контрагентами после фильтрации.")
        return

    # Определяем список проектов для обработки
    if selected_projects and project_col and project_col in filtered_df.columns:
        projects_to_process = selected_projects
    else:
        # Если проекты не выбраны или колонка не найдена, обрабатываем все проекты
        if project_col and project_col in filtered_df.columns:
            projects_to_process = sorted(
                filtered_df[project_col].dropna().unique().tolist()
            )
        else:
            projects_to_process = ["Все проекты"]

    # Гистограммы: факт по периодам (люди и техника отдельно), количество и %
    period_col_hist = _gdrs_resolve_period_column(filtered_df)
    if period_col_hist and "week_sum" in filtered_df.columns:
        # Линейный график (по ТЗ): план — 100% (синий), факт — % от плана (оранжевый), округление до целых %.
        try:
            _p = pd.to_numeric(filtered_df.get("План_numeric"), errors="coerce").fillna(0.0)
            _f = pd.to_numeric(filtered_df.get("week_sum"), errors="coerce").fillna(0.0)
            _pp = pd.to_datetime(filtered_df[period_col_hist], errors="coerce", dayfirst=True)
            if _pp.notna().any():
                _tmp = pd.DataFrame({"period": _pp.dt.to_period("M"), "plan": _p, "fact": _f})
                _by = _tmp.groupby("period", as_index=False).agg({"plan": "sum", "fact": "sum"})
                _by = _by[_by["plan"] > 0].copy()
                if not _by.empty:
                    _by["period_str"] = _by["period"].map(format_period_ru)
                    _by["fact_pct"] = (_by["fact"] / _by["plan"] * 100.0).clip(lower=0.0)
                    _by["fact_pct_int"] = _by["fact_pct"].map(lambda x: int(np.ceil(float(x))) if pd.notna(x) else 0)
                    fig_pct = go.Figure()
                    fig_pct.add_trace(
                        go.Scatter(
                            x=_by["period_str"],
                            y=[100] * len(_by.index),
                            name="План",
                            mode="lines+markers+text",
                            line=dict(color="#3498db", width=3),
                            marker=dict(size=8, color="#3498db"),
                            text=["100"] * len(_by.index),
                            textposition="top center",
                            textfont=dict(color="white", size=10),
                            hovertemplate="Период: %{x}<br>План: 100%<extra></extra>",
                            cliponaxis=False,
                        )
                    )
                    fig_pct.add_trace(
                        go.Scatter(
                            x=_by["period_str"],
                            y=_by["fact_pct_int"],
                            name="Факт",
                            mode="lines+markers+text",
                            line=dict(color="#e67e22", width=3),
                            marker=dict(size=8, color="#e67e22"),
                            text=[str(v) for v in _by["fact_pct_int"].tolist()],
                            textposition="top center",
                            textfont=dict(color="white", size=10),
                            customdata=np.stack(
                                [
                                    _by["plan"].map(lambda v: int(np.ceil(float(v))) if pd.notna(v) else 0).values,
                                    _by["fact"].map(lambda v: int(np.ceil(float(v))) if pd.notna(v) else 0).values,
                                ],
                                axis=-1,
                            ),
                            hovertemplate="Период: %{x}<br>План: %{customdata[0]}<br>Факт: %{customdata[1]}<br>Факт/план: %{y}%<extra></extra>",
                            cliponaxis=False,
                        )
                    )
                    fig_pct.update_layout(
                        height=460,
                        showlegend=True,
                        legend=dict(
                            orientation="v",
                            yanchor="top",
                            y=1,
                            xanchor="left",
                            x=1.02,
                            font=dict(size=11, color="#e8eef5"),
                        ),
                        xaxis_title="Период",
                        yaxis_title="Факт к плану, %",
                        margin=dict(l=56, r=140, t=72, b=120),
                        xaxis=dict(automargin=True),
                        yaxis=dict(automargin=True),
                        uniformtext=dict(minsize=7, mode="show"),
                    )
                    fig_pct = apply_chart_background(fig_pct, skip_uniformtext=True)
                    try:
                        fig_pct.update_layout(
                            margin=dict(l=56, r=150, t=88, b=140),
                            uniformtext=dict(minsize=6, mode="show"),
                        )
                    except Exception:
                        pass
                    render_chart(fig_pct, key=f"{key_prefix}_planfact_pct_line", caption_below="Динамика: план = 100%, факт = % от плана (округление вверх).")
        except Exception:
            pass

        sources_hist = []
        if "data_source" in filtered_df.columns:
            sources_hist = filtered_df["data_source"].dropna().unique().tolist()
        else:
            sources_hist = [None]
        source_labels_hist = []
        for s in sources_hist:
            if s is None:
                source_labels_hist.append("Данные")
            elif str(s).strip() == "Ресурсы":
                source_labels_hist.append("Люди (ресурсы)")
            elif str(s).strip() == "Техника":
                source_labels_hist.append("Техника")
            else:
                source_labels_hist.append(str(s))
        hist_cols = st.columns(max(1, len(sources_hist)))
        for idx, (src, label) in enumerate(zip(sources_hist, source_labels_hist)):
            if src is None:
                df_hist = filtered_df.copy()
            else:
                df_hist = filtered_df[_gdrs_match_data_source(filtered_df["data_source"], src)].copy()
            if df_hist.empty:
                with hist_cols[idx]:
                    st.info(f"**{label}** — нет данных для графика «Факт по периодам».")
                continue
            # Колонки по неделям (1 неделя_numeric, 2 неделя_numeric, ...)
            week_numeric_cols_hist = [
                c for c in df_hist.columns
                if isinstance(c, str) and "_numeric" in c and "недел" in c.lower()
            ]
            if not week_numeric_cols_hist:
                for i in range(1, 6):
                    cn = f"{i} неделя_numeric"
                    if cn in df_hist.columns:
                        week_numeric_cols_hist.append(cn)
            week_numeric_cols_hist = sorted(week_numeric_cols_hist, key=lambda c: (
                int(c.split()[0]) if c.split() and c.split()[0].isdigit() else 99
            ))
            if week_numeric_cols_hist:
                # Группировка по периоду, точки — по неделям: melt по неделям, затем groupby(период, неделя)
                id_vars = [period_col_hist]
                value_vars = [c for c in week_numeric_cols_hist if c in df_hist.columns]
                if value_vars:
                    long_df = df_hist[id_vars + value_vars].melt(
                        id_vars=id_vars,
                        value_vars=value_vars,
                        var_name="Неделя",
                        value_name="Факт",
                    )
                    long_df["Неделя"] = long_df["Неделя"].str.replace("_numeric", "").str.strip()
                    long_df["Факт"] = pd.to_numeric(long_df["Факт"], errors="coerce").fillna(0)
                    by_period_week = (
                        long_df.groupby([period_col_hist, "Неделя"], as_index=False)["Факт"]
                        .sum()
                    )
                    by_period_week["Период_стр"] = by_period_week[period_col_hist].astype(str).str.strip()
                    by_period_week = _gdrs_point_pct_of_period_plan(
                        by_period_week, df_hist, period_col_hist, "Факт"
                    )
                else:
                    by_period_week = None
            else:
                by_period_week = None
            if by_period_week is not None and not by_period_week.empty:
                fig_hist = go.Figure()
                is_resources = "Ресурсы" in label or "Люди" in label
                base_color = "#3498db" if is_resources else "#e67e22"
                weeks = by_period_week["Неделя"].unique().tolist()
                # Люди и техника: точечная диаграмма — одна линия через все точки по порядку (период → неделя)
                by_period_week = by_period_week.copy()
                by_period_week["x_label"] = (
                    by_period_week["Период_стр"].astype(str)
                    + " — "
                    + by_period_week["Неделя"].astype(str).str.replace(" неделя", "н", regex=False)
                )
                by_period_week = by_period_week.sort_values([period_col_hist, "Неделя"])
                x_order = by_period_week["x_label"].tolist()
                _mk_week_lbl = lambda r: (
                    f"{int(r['Факт'])} ({int(np.ceil(float(r['%'])))}%)"
                )
                _mk_week_hover = lambda r: (
                    f"Факт: {int(r['Факт'])}<br>"
                    f"План (период): {int(np.ceil(float(r['План_период']))) if pd.notna(r.get('План_период')) and float(r.get('План_период') or 0) > 0 else '—'}<br>"
                    f"К плану: {int(np.ceil(float(r['%'])))}%"
                )
                fig_hist.add_trace(
                    go.Scatter(
                        x=by_period_week["x_label"],
                        y=by_period_week["Факт"],
                        name="Факт",
                        mode="lines+markers+text",
                        line=dict(color=base_color, width=2),
                        marker=dict(size=10, color=base_color, line=dict(width=1, color="white")),
                        text=[_mk_week_lbl(r) for _, r in by_period_week.iterrows()],
                        textposition="top center",
                        textfont=dict(size=9, color="white"),
                        hovertext=[_mk_week_hover(r) for _, r in by_period_week.iterrows()],
                        hovertemplate="%{x}<br>%{hovertext}<extra></extra>",
                        connectgaps=False,
                        cliponaxis=False,
                    )
                )
                fig_hist.update_layout(
                    title_text="",
                    xaxis_title="Период — неделя",
                    yaxis_title="Количество",
                    height=440,
                    showlegend=False,
                    margin=dict(l=56, r=28, t=56, b=168),
                    uniformtext=dict(minsize=7, mode="show"),
                    xaxis=dict(
                        tickangle=-45,
                        categoryorder="array",
                        categoryarray=x_order,
                        automargin=True,
                    ),
                    yaxis=dict(automargin=True),
                )
                fig_hist = apply_chart_background(fig_hist)
                with hist_cols[idx]:
                    render_chart(
                        fig_hist,
                        key=f"{key_prefix}_hist_period_{idx}",
                        caption_below=(
                            f"Факт по периодам (недели), % к сумме плана периода (округление вверх): {label}"
                        ),
                    )
            else:
                # Нет колонок по неделям — один столбец/точка на период (сумма)
                by_period = (
                    df_hist.groupby(period_col_hist, as_index=False)["week_sum"]
                    .sum()
                    .rename(columns={"week_sum": "Факт"})
                )
                by_period["Период_стр"] = by_period[period_col_hist].astype(str).str.strip()
                by_period = _gdrs_point_pct_of_period_plan(
                    by_period, df_hist, period_col_hist, "Факт"
                )
                by_period = by_period.sort_values(period_col_hist)
                with hist_cols[idx]:
                    fig_hist = go.Figure()
                    is_resources_fb = "Ресурсы" in label or "Люди" in label
                    if is_resources_fb:
                        fig_hist.add_trace(
                            go.Scatter(
                                x=by_period["Период_стр"],
                                y=by_period["Факт"],
                                mode="markers+text",
                                name="Факт",
                                marker=dict(size=14, color="#3498db", line=dict(width=1, color="white")),
                                text=[
                                    f"{int(row['Факт'])} ({int(np.ceil(float(row['%'])))}%)"
                                    for _, row in by_period.iterrows()
                                ],
                                textposition="top center",
                                textfont=dict(size=11, color="white"),
                                cliponaxis=False,
                            )
                        )
                    else:
                        fig_hist.add_trace(
                            go.Bar(
                                x=by_period["Период_стр"],
                                y=by_period["Факт"],
                                text=[
                                    f"{int(row['Факт'])} ({int(np.ceil(float(row['%'])))}%)"
                                    for _, row in by_period.iterrows()
                                ],
                                textposition="outside",
                                textfont=dict(size=11, color="white"),
                                marker_color="#e67e22",
                                name="Факт",
                                cliponaxis=False,
                            )
                        )
                    fig_hist.update_layout(
                        title_text="",
                        xaxis_title="Период",
                        yaxis_title="Количество",
                        height=440,
                        showlegend=False,
                        margin=dict(l=56, r=28, t=56, b=168),
                        uniformtext=dict(minsize=7, mode="show"),
                        xaxis=dict(tickangle=-45, automargin=True),
                        yaxis=dict(automargin=True),
                    )
                    fig_hist = _apply_finance_bar_label_layout(fig_hist)
                    try:
                        fig_hist.update_layout(
                            uniformtext=dict(minsize=6, mode="show"),
                            margin=dict(l=56, r=36, t=88, b=180),
                        )
                    except Exception:
                        pass
                    fig_hist = apply_chart_background(fig_hist)
                    render_chart(
                        fig_hist,
                        key=f"{key_prefix}_hist_period_fallback_{idx}",
                        caption_below=f"Факт по периодам, % к сумме плана периода (округление вверх): {label}",
                    )

    elif "week_sum" in filtered_df.columns:
        # Нет отдельной колонки периода (типично для web-выгрузки только с датами в заголовках): факт по подрядчикам
        with st.expander("Нет колонки «Период» в файле", expanded=False):
            st.caption(
                "Показан суммарный факт по подрядчикам (агрегация без оси периода в данных)."
            )
            st.caption(
                "Если суммы «План» и «Факт» по контрагенту почти совпадают: в части web-выгрузок колонка «План» "
                "задана на строку как норма/лимит рядом с теми же неделями, либо строки дублируют одну и ту же "
                "запись — тогда агрегированные суммы сходятся. Сверьте исходный файл: уникальность строк "
                "(проект·контрагент·период), что именно означает «План» в шапке и нет ли копирования блоков."
            )
        sources_fb = []
        if "data_source" in filtered_df.columns:
            sources_fb = filtered_df["data_source"].dropna().unique().tolist()
        else:
            sources_fb = [None]
        labels_fb = []
        for s in sources_fb:
            if s is None:
                labels_fb.append("Данные")
            elif str(s).strip().lower() in ("ресурсы", "ресурс"):
                labels_fb.append("Люди (ресурсы)")
            elif str(s).strip().lower() in ("техника", "tech", "technique"):
                labels_fb.append("Техника")
            else:
                labels_fb.append(str(s))
        fb_cols = st.columns(max(1, len(sources_fb)))
        for fbi, (src_fb, lab_fb) in enumerate(zip(sources_fb, labels_fb)):
            if src_fb is None:
                df_fb = filtered_df.copy()
            else:
                df_fb = filtered_df[_gdrs_match_data_source(filtered_df["data_source"], src_fb)].copy()
            if df_fb.empty or "Контрагент" not in df_fb.columns:
                with fb_cols[fbi]:
                    st.info(f"**{lab_fb}** — нет данных для «Факт по подрядчикам».")
                continue
            agg_map = {
                "week_sum": lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum(),
            }
            if "План_numeric" in df_fb.columns:
                agg_map["План_numeric"] = "sum"
            by_c = df_fb.groupby("Контрагент", as_index=False).agg(agg_map)
            by_c = by_c.rename(columns={"week_sum": "Факт"})
            if "План_numeric" not in by_c.columns:
                by_c["План"] = 0.0
            else:
                by_c["План"] = pd.to_numeric(by_c["План_numeric"], errors="coerce").fillna(0.0)
                by_c = by_c.drop(columns=["План_numeric"], errors="ignore")
            by_c["Факт"] = pd.to_numeric(by_c["Факт"], errors="coerce").fillna(0.0)
            by_c = by_c[(by_c["Факт"].abs() > 0) | (by_c["План"].abs() > 0)].sort_values(
                "Факт", ascending=True
            )
            if by_c.empty:
                with fb_cols[fbi]:
                    st.info(f"**{lab_fb}** — нет ненулевых значений по подрядчикам.")
                continue
            tot = float(by_c["Факт"].sum())
            by_c["pct"] = (by_c["Факт"] / tot * 100.0).round(1) if tot else 0.0
            is_res = "ресурс" in lab_fb.lower() or "люди" in lab_fb.lower()
            col_bar = "#2ecc71" if is_res else "#e67e22"
            col_plan = "#5dade2" if is_res else "#af7ac5"
            _h = max(420, int(28 * max(6, len(by_c))) )
            fig_fb = go.Figure()
            show_plan = float(by_c["План"].sum()) > 0
            _plan_vals = by_c["План"].to_numpy(dtype=float, copy=False)
            _fact_vals = by_c["Факт"].to_numpy(dtype=float, copy=False)
            _near = np.isfinite(_plan_vals) & np.isfinite(_fact_vals) & (
                np.abs(_plan_vals - _fact_vals) <= np.maximum(1.0, np.abs(_plan_vals) * 0.05)
            )
            _near_n = int(np.sum(_near)) if _near.size else 0
            if show_plan:
                _pdiff = _fact_vals - _plan_vals
                _ppct = np.where(
                    np.abs(_plan_vals) > 1e-9,
                    (_pdiff / _plan_vals) * 100.0,
                    np.nan,
                )
                fig_fb.add_trace(
                    go.Bar(
                        y=by_c["Контрагент"].astype(str),
                        x=by_c["План"],
                        name="План (договор)",
                        orientation="h",
                        marker=dict(color=col_plan, line=dict(width=1, color="#aed6f1")),
                        text=[f"{int(round(p))}" if pd.notna(p) else "" for p in by_c["План"]],
                        textposition="outside",
                        textfont=dict(size=10, color="white"),
                        customdata=np.stack(
                            [_fact_vals, _pdiff, _ppct],
                            axis=-1,
                        ),
                        hovertemplate=(
                            "<b>%{y}</b><br>План (договор): %{x:,.0f}"
                            "<br>Факт: %{customdata[0]:,.0f}"
                            "<br>Δ (факт−план): %{customdata[1]:,.0f}"
                            "<br>Отклонение к плану: %{customdata[2]:.1f}%<extra></extra>"
                        ),
                    )
                )
            fig_fb.add_trace(
                go.Bar(
                    y=by_c["Контрагент"].astype(str),
                    x=by_c["Факт"],
                    name="Факт",
                    orientation="h",
                    marker=dict(color=col_bar, line=dict(width=1, color="white")),
                    text=[
                        f"{int(r['Факт'])} ({r['pct']}%)" for _, r in by_c.iterrows()
                    ],
                    textposition="outside",
                    textfont=dict(size=11, color="white"),
                    customdata=np.stack(
                        [
                            by_c["План"].values,
                            np.where(
                                by_c["План"].abs() > 1e-9,
                                (by_c["Факт"] - by_c["План"]) / by_c["План"] * 100.0,
                                np.nan,
                            ),
                        ],
                        axis=-1,
                    ),
                    hovertemplate=(
                        "<b>%{y}</b><br>Факт: %{x:,.0f}<br>План (договор): %{customdata[0]:,.0f}"
                        "<br>Отклонение к плану: %{customdata[1]:.1f}%<extra></extra>"
                    ),
                )
            )
            fig_fb.update_layout(
                title_text="",
                xaxis_title="Человеко-смены / ед. (сумма по строкам)",
                yaxis_title="",
                height=_h,
                barmode="group",
                bargap=0.18,
                showlegend=show_plan,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                    font=dict(size=11, color="#e8eef5"),
                ),
                yaxis=dict(autorange="reversed", automargin=True),
                xaxis=dict(automargin=True),
                margin=dict(l=12, r=28, t=72 if show_plan else 56, b=96),
            )
            fig_fb = _apply_finance_bar_label_layout(fig_fb)
            fig_fb = apply_chart_background(fig_fb)
            _cap_fb = (
                f"Факт и план по подрядчикам (горизонтально; в выгрузке нет колонки периода): {lab_fb}. "
                "Подсказка: план (синий/фиолетовый), факт (зелёный/оранжевый); в hover — план и факт рядом."
            )
            if _near_n > 0:
                _cap_fb += (
                    f" По {_near_n} контрагент(ам) план≈факт (≤5% или ≤1 ед.) — типично для норм/дублей строк в выгрузке; "
                    "сверьте уникальность строк в исходном файле."
                )
            with fb_cols[fbi]:
                render_chart(
                    fig_fb,
                    key=f"{key_prefix}_hist_noperiod_{fbi}",
                    caption_below=_cap_fb,
                )

    plan_fact_row_done = False
    for project_name in projects_to_process:
        project_filtered_df = filtered_df.copy()
        if (
            project_col
            and project_col in project_filtered_df.columns
            and project_name != "Все проекты"
        ):
            project_filtered_df = project_filtered_df[
                project_filtered_df[project_col].astype(str).str.strip()
                == str(project_name).strip()
            ]

        if project_filtered_df.empty:
            continue

        if len(projects_to_process) > 1:
            st.markdown("---")
            st.subheader(f"Проект: {project_name}")

        if not has_plan_data and "Контрагент" in project_filtered_df.columns and "week_sum" in project_filtered_df.columns:
            _bar_avg = (
                project_filtered_df.groupby("Контрагент", as_index=False)["week_sum"]
                .sum()
                .rename(columns={"week_sum": "Среднее за месяц"})
            )
            _bar_avg["Среднее за месяц"] = _bar_avg["Среднее за месяц"].round(1)
            _bar_avg = _bar_avg[_bar_avg["Среднее за месяц"] > 0].sort_values("Среднее за месяц", ascending=False)
            if not _bar_avg.empty:
                fig_avg = px.bar(
                    _bar_avg, x="Контрагент", y="Среднее за месяц",
                    text=_bar_avg["Среднее за месяц"].apply(lambda v: f"{v:.0f}"),
                    color_discrete_sequence=["#2ecc71"],
                )
                _pslug = str(project_name).replace(" ", "_")[:20]
                fig_avg.update_traces(textposition="outside", textfont=dict(size=12, color="white"))
                fig_avg.update_layout(height=500, xaxis=dict(tickangle=-45), yaxis_title="Среднее за месяц")
                fig_avg = _apply_finance_bar_label_layout(fig_avg)
                fig_avg = apply_chart_background(fig_avg)
                render_chart(fig_avg, key=f"{key_prefix}_avg_bar_{_pslug}", caption_below=f"Среднее количество ресурсов — {project_name}")

                total_avg = _bar_avg["Среднее за месяц"].sum()
                if total_avg > 0:
                    fig_pie_avg = px.pie(
                        _bar_avg, values="Среднее за месяц", names="Контрагент",
                        title=None, color_discrete_sequence=px.colors.qualitative.Set3,
                    )
                    fig_pie_avg.update_traces(
                        textinfo="text",
                        texttemplate="%{label}<br>%{value:,.0f} (%{percent:.0%})",
                        textposition="inside",
                        textfont_size=11,
                        insidetextorientation="horizontal",
                        hovertemplate="<b>%{label}</b><br>%{value:,.0f} (%{percent:.0%})<extra></extra>",
                    )
                    fig_pie_avg.update_layout(
                        height=500, showlegend=True,
                        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.05, font=dict(size=10)),
                        uniformtext=dict(minsize=8, mode="hide"),
                    )
                    fig_pie_avg = apply_chart_background(fig_pie_avg)
                    render_chart(fig_pie_avg, key=f"{key_prefix}_avg_pie_{_pslug}", caption_below=f"Распределение ресурсов — {project_name}")
            else:
                st.info("Нет данных для отображения.")
            continue

        if not plan_fact_row_done:
            df_people = project_filtered_df.copy()
            if "data_source" in df_people.columns:
                df_people = df_people[
                    df_people["data_source"].astype(str).str.strip().str.lower() == "ресурсы"
                ].copy()
            if not df_people.empty and "План_numeric" in df_people.columns and "week_sum" in df_people.columns:
                plan_sum = df_people["План_numeric"].sum()
                fact_sum = df_people["week_sum"].sum()
                total_pf = plan_sum + fact_sum
                if total_pf > 0:
                    plan_pct = round(plan_sum / total_pf * 100, 1)
                    fact_pct = round(fact_sum / total_pf * 100, 1)
                    pie_plan_fact = pd.DataFrame({
                        "Тип": ["План", "Факт"],
                        "Значение": [plan_sum, fact_sum],
                        "Текст": [f"План: {int(plan_sum)} ({plan_pct}%)", f"Факт: {int(fact_sum)} ({fact_pct}%)"],
                    })
                    st.subheader("План и факт (люди) по проекту")
                    fig_pie_pf = px.pie(
                        pie_plan_fact,
                        values="Значение",
                        names="Тип",
                        title=None,
                        color_discrete_sequence=["#3498db", "#2ecc71"],
                    )
                    fig_pie_pf.update_traces(
                        textinfo="text",
                        texttemplate="%{label}<br>%{value:,.0f} (%{percent:.0%})",
                        textposition="inside",
                        textfont_size=11,
                        insidetextorientation="horizontal",
                        hovertemplate="<b>%{label}</b><br>%{value:,.0f} (%{percent:.0%})<extra></extra>",
                    )
                    fig_pie_pf.update_layout(
                        height=500,
                        showlegend=True,
                        title_font_size=14,
                        uniformtext=dict(minsize=8, mode="hide"),
                        legend=dict(orientation="v", font=dict(size=10)),
                    )
                    fig_pie_pf = apply_chart_background(fig_pie_pf)
                    render_chart(fig_pie_pf, caption_below=f"План и факт — {project_name}")

        # ========== Chart 1: Pie Chart by Contractor (Delta %) ==========
        st.subheader("Круговая диаграмма: Распределение отклонения % по контрагентам")

        # Group by Контрагент and aggregate for pie chart (Delta %)
        # Ensure Дельта_процент_numeric exists - check if it was created in work_df
        if "Дельта_процент_numeric" not in project_filtered_df.columns:
            # Try to find Дельта (%) column by partial match
            delta_pct_col = None
            if "Дельта (%)" in project_filtered_df.columns:
                delta_pct_col = "Дельта (%)"
            else:
                delta_pct_col = find_column_by_partial(
                    project_filtered_df,
                    [
                        "Дельта (%)",
                        "Дельта %",
                        "дельта (%)",
                        "дельта %",
                        "Delta %",
                        "delta %",
                        "Дельта(%)",
                        "Дельта%",
                    ],
                )

            if delta_pct_col and delta_pct_col in project_filtered_df.columns:
                # Extract percentage values from the column
                def extract_percentage(value):
                    """Extract numeric value from percentage string like '-90%' or '90%', or numeric value"""
                    if pd.isna(value):
                        return 0
                    # If already numeric, return as is
                    if isinstance(value, (int, float)):
                        return float(value)
                    # Otherwise, try to extract from string
                    value_str = str(value).strip()
                    # Remove % sign and convert to float
                    value_str = (
                        value_str.replace("%", "").replace(",", ".").replace(" ", "")
                    )
                    try:
                        return float(value_str)
                    except:
                        return 0

                project_filtered_df["Дельта_процент_numeric"] = project_filtered_df[
                    delta_pct_col
                ].apply(extract_percentage)
            else:
                # Try to calculate from Дельта and План if available
                if (
                    "Дельта_numeric" in project_filtered_df.columns
                    and "План_numeric" in project_filtered_df.columns
                ):
                    project_filtered_df["Дельта_процент_numeric"] = 0.0
                    mask = project_filtered_df["План_numeric"] != 0
                    project_filtered_df.loc[mask, "Дельта_процент_numeric"] = (
                        project_filtered_df.loc[mask, "Дельта_numeric"]
                        / project_filtered_df.loc[mask, "План_numeric"]
                    ) * 100
                    project_filtered_df["Дельта_процент_numeric"] = project_filtered_df[
                        "Дельта_процент_numeric"
                    ].fillna(0)
                else:
                    st.error(
                        "Не удалось найти или рассчитать отклонение %. Отсутствуют необходимые колонки."
                    )
                    st.info(
                        f"Доступные колонки: {', '.join(project_filtered_df.columns)}"
                    )
                    contractor_delta_pct = pd.DataFrame(
                        columns=["Контрагент", "Отклонение %"]
                    )

        # Group by contractor and aggregate
        if "Дельта_процент_numeric" in project_filtered_df.columns:
            # Check if we have any data before grouping
            if (
                not project_filtered_df.empty
                and "Контрагент" in project_filtered_df.columns
            ):
                contractor_delta_pct = (
                    project_filtered_df.groupby("Контрагент")
                    .agg({"Дельта_процент_numeric": "sum"})  # Sum of delta percentages
                    .reset_index()
                )

                contractor_delta_pct.columns = ["Контрагент", "Отклонение %"]
            else:
                contractor_delta_pct = pd.DataFrame(
                    columns=["Контрагент", "Отклонение %"]
                )
        else:
            contractor_delta_pct = pd.DataFrame(columns=["Контрагент", "Отклонение %"])

        # Check if we have data (внутри цикла по проектам — круговая и столбчатая по каждому проекту)
        if contractor_delta_pct.empty or len(contractor_delta_pct) == 0:
            st.info("Нет данных для отображения круговой диаграммы.")
        else:
            # Ensure «Отклонение %» is numeric
            contractor_delta_pct["Отклонение %"] = pd.to_numeric(
                contractor_delta_pct["Отклонение %"], errors="coerce"
            ).fillna(0)

            # Check if we have any non-zero values
            total_abs_sum = contractor_delta_pct["Отклонение %"].abs().sum()

            if total_abs_sum == 0:
                st.info(
                    "Все значения отклонения % равны нулю. Диаграмма не может быть построена."
                )
            else:
                # Remove only exactly zero values (not small values)
                non_zero_data = contractor_delta_pct[
                    contractor_delta_pct["Отклонение %"] != 0
                ].copy()

                # Use non-zero data if available
                if not non_zero_data.empty:
                    contractor_delta_pct = non_zero_data

                # Sort by absolute value for better visualization
                contractor_delta_pct = contractor_delta_pct.sort_values(
                    "Отклонение %", key=abs, ascending=False
                )

                # Create a copy with absolute values for pie chart (pie charts don't support negative values)
                contractor_delta_pct_abs = contractor_delta_pct.copy()
                contractor_delta_pct_abs["Отклонение %_abs"] = contractor_delta_pct_abs[
                    "Отклонение %"
                ].abs()

                # Store original values for display
                original_values = contractor_delta_pct_abs["Отклонение %"].tolist()

                # Create pie chart using absolute values
                fig_pie = px.pie(
                    contractor_delta_pct_abs,
                    values="Отклонение %_abs",
                    names="Контрагент",
                    title=None,
                    color_discrete_sequence=px.colors.qualitative.Set3,
                )

                fig_pie.update_layout(
                    height=600,
                    showlegend=True,
                    legend=dict(
                        orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.1, font=dict(size=10),
                    ),
                    title_font_size=16,
                    uniformtext=dict(minsize=8, mode="hide"),
                )

                fig_pie.update_traces(
                    textinfo="label+percent",
                    textposition="auto",
                    textfont_size=10,
                    insidetextorientation="radial",
                    customdata=original_values,
                    hovertemplate="<b>%{label}</b><br>Отклонение %: %{customdata:.0f}%<br>Процент: %{percent}<br><extra></extra>",
                )

                fig_pie = apply_chart_background(fig_pie)
                render_chart(
                    fig_pie,
                    caption_below="Распределение отклонения % по контрагентам",
                )

        # ========== Таблица по подрядчикам: план, факт, % (факт/план), отклонение ==========
        if "data_source" in project_filtered_df.columns and "Контрагент" in project_filtered_df.columns and "week_sum" in project_filtered_df.columns:
            for _type, type_label, type_key in [
                ("ресурсы", "Люди", "people"),
                ("техника", "Техника", "technique"),
            ]:
                df_type = project_filtered_df[
                    project_filtered_df["data_source"].astype(str).str.strip().str.lower() == _type
                ]
                if df_type.empty:
                    continue
                _agg = {"week_sum": "sum"}
                if "План_numeric" in df_type.columns:
                    _agg["План_numeric"] = "sum"
                _group_cols = []
                if project_col and project_col in df_type.columns:
                    _group_cols.append(project_col)
                _group_cols.append("Контрагент")
                by_contractor = df_type.groupby(_group_cols, as_index=False).agg(_agg)
                by_contractor = by_contractor.rename(
                    columns={"week_sum": "Факт", "План_numeric": "План"}
                )
                if "План" not in by_contractor.columns:
                    by_contractor["План"] = 0.0
                by_contractor["Факт"] = pd.to_numeric(
                    by_contractor["Факт"], errors="coerce"
                ).fillna(0.0)
                by_contractor["План"] = pd.to_numeric(
                    by_contractor["План"], errors="coerce"
                ).fillna(0.0)
                by_contractor["Отклонение"] = by_contractor["Факт"] - by_contractor["План"]
                by_contractor["%"] = by_contractor.apply(
                    lambda r: (
                        round(float(r["Факт"]) / float(r["План"]) * 100.0, 1)
                        if float(r["План"]) != 0.0
                        else None
                    ),
                    axis=1,
                )
                by_contractor = by_contractor[
                    (by_contractor["Факт"] != 0) | (by_contractor["План"] != 0)
                ].copy()
                if by_contractor.empty:
                    continue
                by_contractor = by_contractor.sort_values("План", ascending=False)
                with st.expander(f"Формулы столбцов ({type_label})", expanded=False):
                    st.caption(
                        "План (из договора), СКУД (из выгрузки ресурсов), «%» = факт/план×100%, отклонение = СКУД − план."
                    )
                _display_cols = ["Контрагент", "План", "Факт", "%", "Отклонение"]
                if project_col and project_col in by_contractor.columns:
                    by_contractor = by_contractor.rename(columns={project_col: "Проект"})
                    _display_cols = ["Проект"] + _display_cols
                display_df = by_contractor[_display_cols].copy()
                display_df["План"] = display_df["План"].apply(
                    lambda x: int(round(x, 0)) if pd.notna(x) else 0
                )
                display_df["Факт"] = display_df["Факт"].apply(
                    lambda x: int(round(x, 0)) if pd.notna(x) else 0
                )
                display_df["%"] = display_df["%"].apply(
                    lambda v: f"{v:.1f}%" if v is not None and pd.notna(v) else "—"
                )
                display_df["Отклонение"] = display_df["Отклонение"].apply(
                    lambda x: int(round(x, 0)) if pd.notna(x) else 0
                )
                st.markdown(
                    budget_table_to_html(
                        display_df,
                        finance_deviation_column="Отклонение",
                        deviation_red_if_positive_only=True,
                    ),
                    unsafe_allow_html=True,
                )

        # ========== Chart 2: Bar Chart by Contractor (Plan, Average, Отклонение) ==========
        st.subheader(
            "Столбчатая диаграмма: План, Среднее за месяц, Отклонение (группировка по контрагенту; сортировка по убыванию Плана)"
        )

        # Filter by selected period(s) for this chart
        bar_df = project_filtered_df.copy()
        if period_col and period_col in bar_df.columns and selected_periods:
            bar_df = bar_df[
                bar_df[period_col].astype(str).str.strip().isin([str(p).strip() for p in selected_periods])
            ]

        # Group by Контрагент and aggregate
        if "Дельта_numeric" not in bar_df.columns:
            if "План_numeric" in bar_df.columns and "week_sum" in bar_df.columns:
                bar_df = bar_df.copy()
                bar_df["Дельта_numeric"] = bar_df["План_numeric"] - bar_df["week_sum"]
            else:
                bar_df = bar_df.copy()
                bar_df["Дельта_numeric"] = 0

        contractor_data = (
            bar_df.groupby("Контрагент")
            .agg(
                {
                    "План_numeric": "sum",
                    "week_sum": "sum",
                    "Дельта_numeric": "sum",
                }
            )
            .reset_index()
        )
        contractor_data.columns = ["Контрагент", "План", "Среднее за месяц", "Отклонение"]

        contractor_data["Отклонение"] = pd.to_numeric(
            contractor_data["Отклонение"], errors="coerce"
        ).fillna(0)
        contractor_data = contractor_data.sort_values("План", ascending=False)

        total_plan = contractor_data["План"].sum() or 1
        total_fact = contractor_data["Среднее за месяц"].sum() or 1

        # Create bar chart
        fig_bar = go.Figure()

        # Подписи на столбцах: абсолютное количество и % (без наведения)
        plan_text = [f"{int(x)} ({x / total_plan * 100:.0f}%)" if pd.notna(x) else "0" for x in contractor_data["План"]]
        fact_text = [f"{int(x)} ({x / total_fact * 100:.0f}%)" if pd.notna(x) else "0" for x in contractor_data["Среднее за месяц"]]

        # Add bars for Plan
        fig_bar.add_trace(
            go.Bar(
                name="План",
                x=contractor_data["Контрагент"],
                y=contractor_data["План"],
                marker_color="#3498db",
                text=plan_text,
                textposition="outside",
                textfont=dict(size=12, color="white"),
            )
        )

        # Add bars for Average (Факт)
        fig_bar.add_trace(
            go.Bar(
                name="Среднее за месяц",
                x=contractor_data["Контрагент"],
                y=contractor_data["Среднее за месяц"],
                marker_color="#2ecc71",
                text=fact_text,
                textposition="outside",
                textfont=dict(size=12, color="white"),
            )
        )

        # Отклонение: подпись — абсолютное значение и % от плана контрагента
        delta_values = contractor_data["Отклонение"].fillna(0)
        delta_abs = delta_values.abs()
        plan_vals = contractor_data["План"].replace(0, 1)
        delta_pct = (contractor_data["Отклонение"] / plan_vals * 100).round(0)
        delta_text = [
            f"{int(abs(d))} ({pct:.0f}%)" if abs(d) >= 0.5 else "0"
            for d, pct in zip(delta_values, delta_pct)
        ]

        positive_mask = delta_values > 0
        if positive_mask.any():
            fig_bar.add_trace(
                go.Bar(
                    name="Отклонение (+)",
                    x=contractor_data.loc[positive_mask, "Контрагент"],
                    y=delta_abs[positive_mask],
                    marker_color="#2ecc71",
                    text=[delta_text[i] for i in range(len(delta_text)) if positive_mask.iloc[i]],
                    textposition="outside",
                    textfont=dict(size=12, color="white"),
                    showlegend=False,
                )
            )

        negative_mask = delta_values < 0
        if negative_mask.any():
            fig_bar.add_trace(
                go.Bar(
                    name="Отклонение (-)",
                    x=contractor_data.loc[negative_mask, "Контрагент"],
                    y=delta_abs[negative_mask],
                    marker_color="#e74c3c",
                    text=[delta_text[i] for i in range(len(delta_text)) if negative_mask.iloc[i]],
                    textposition="outside",
                    textfont=dict(size=12, color="white"),
                    showlegend=False,
                )
            )

        zero_mask = delta_values == 0
        if zero_mask.any():
            fig_bar.add_trace(
                go.Bar(
                    name="Отклонение (0)",
                    x=contractor_data.loc[zero_mask, "Контрагент"],
                    y=delta_abs[zero_mask],
                    marker_color="#95a5a6",
                    text=[delta_text[i] for i in range(len(delta_text)) if zero_mask.iloc[i]],
                    textposition="outside",
                    textfont=dict(size=12, color="white"),
                    showlegend=False,
                )
            )

        period_caption = f" Период: {', '.join(str(p) for p in selected_periods[:5])}{'…' if len(selected_periods) > 5 else ''}" if (period_col and selected_periods) else ""
        fig_bar.update_layout(
            title_text="",
            xaxis_title="Контрагент",
            yaxis_title="Значение",
            barmode="group",
            height=600,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
            ),
            xaxis=dict(tickangle=-45),
        )

        fig_bar = _apply_finance_bar_label_layout(fig_bar)
        fig_bar = apply_chart_background(fig_bar)
        render_chart(
            fig_bar,
            caption_below="План, Среднее за месяц и Отклонение по контрагентам" + period_caption,
        )

        # ========== Chart 3: Pie Chart by Contractor (Plan + Average) ==========
        st.subheader(
            "Круговые диаграммы: Рабочие/техника (план/факт) и Рабочие/техника (% фактический по подрядчикам)"
        )

        # Group by Контрагент and aggregate for pie chart (Plan + Average)
        contractor_plan_avg = (
            project_filtered_df.groupby("Контрагент")
            .agg(
                {
                    "План_numeric": "sum",  # Sum of plans
                    "week_sum": "sum",  # Sum of weeks = среднее за месяц
                    "Дельта_numeric": "sum",  # Sum of deltas
                }
            )
            .reset_index()
        )

        contractor_plan_avg.columns = [
            "Контрагент",
            "План",
            "Среднее за месяц",
            "Отклонение",
        ]

        # Calculate sum of Plan + Average for each contractor
        contractor_plan_avg["Сумма"] = (
            contractor_plan_avg["План"] + contractor_plan_avg["Среднее за месяц"]
        )

        # Calculate доля факта (Среднее за месяц / Сумма * 100) and доля отклонения (Отклонение / План * 100)
        contractor_plan_avg["Доля факта (%)"] = 0.0
        contractor_plan_avg["Доля отклонения (%)"] = 0.0
        mask_sum = contractor_plan_avg["Сумма"] != 0
        contractor_plan_avg.loc[mask_sum, "Доля факта (%)"] = (
            contractor_plan_avg.loc[mask_sum, "Среднее за месяц"]
            / contractor_plan_avg.loc[mask_sum, "Сумма"]
        ) * 100
        mask_plan = contractor_plan_avg["План"] != 0
        contractor_plan_avg.loc[mask_plan, "Доля отклонения (%)"] = (
            contractor_plan_avg.loc[mask_plan, "Отклонение"]
            / contractor_plan_avg.loc[mask_plan, "План"]
        ) * 100

        # Remove zero values for pie chart
        contractor_plan_avg = contractor_plan_avg[
            contractor_plan_avg["Сумма"] != 0
        ].copy()

        if contractor_plan_avg.empty:
            st.info("Нет данных для отображения.")
        else:
            contractor_plan_avg.sort_values("Сумма", ascending=False, inplace=True)
            # Круговая «план + среднее по контрагентам» скрыта по макету — используйте сводную таблицу ниже.

        st.subheader("Сводная таблица по контрагентам")

        # Format numbers for display
        summary_table = contractor_data.copy()
        summary_table["План"] = summary_table["План"].apply(
            lambda x: f"{int(x)}" if pd.notna(x) else "0"
        )
        summary_table["Среднее за месяц"] = summary_table["Среднее за месяц"].apply(
            lambda x: f"{int(x)}" if pd.notna(x) else "0"
        )
        summary_table["Отклонение"] = summary_table["Отклонение"].apply(
            lambda x: f"{int(x)}" if pd.notna(x) else "0"
        )

        st.markdown(
            budget_table_to_html(summary_table, finance_deviation_column="Отклонение"),
            unsafe_allow_html=True,
        )

        # Summary metrics
        col1, col2, col3 = st.columns(3)

        with col1:
            total_plan = contractor_data["План"].sum()
            st.metric("Общий план", f"{int(total_plan)}")

        with col2:
            total_average = contractor_data["Среднее за месяц"].sum()
            st.metric("Общее среднее за месяц", f"{int(total_average)}")

        with col3:
            total_delta = contractor_data["Отклонение"].sum()
            st.metric("Общее отклонение", f"{int(total_delta)}")


# ==================== DASHBOARD 8.6.7: Workforce Movement ====================
def dashboard_workforce_movement(df, data_source_filter=None, show_header=True, key_prefix="workforce"):
    """
    График движения рабочей силы (ресурсы и/или техника).
    data_source_filter: "Ресурсы" — только люди, "Техника" — только техника, None — оба.
    show_header: выводить ли заголовок (при вызове из табов можно False).
    key_prefix: префикс для ключей виджетов Streamlit (уникальный при вызове из нескольких табов).
    """
    if show_header:
        _dst = (data_source_filter or "").strip().lower()
        if _dst == "техника":
            st.header("План/факт техника")
        elif _dst == "ресурсы":
            st.header("План/факт рабочие")
        else:
            st.header("ГДРС")

    resources_df = st.session_state.get("resources_data", None)
    technique_df = st.session_state.get("technique_data", None)
    combined_df = None
    _gdrs_src_diag = ""

    def _cols_lc(pdf):
        if pdf is None or getattr(pdf, "empty", True):
            return []
        return [str(c).lower().strip() for c in pdf.columns]

    def _has_pivot_date_columns(pdf):
        """Колонки вида ДД.ММ.ГГГГ (выгрузка web/ с суточными значениями)."""
        if pdf is None or getattr(pdf, "empty", True):
            return False
        return sum(1 for c in pdf.columns if _gdrs_header_is_dd_mm_yyyy(c)) >= 2

    def _like_technique(pdf):
        cl = _cols_lc(pdf)
        if any("среднее за недел" in c for c in cl):
            return True
        if any("среднее значение за день" in c for c in cl):
            return True
        if _has_pivot_date_columns(pdf) and any("тип ресурсов" in c for c in cl):
            return True
        return False

    def _like_resources(pdf):
        cl = _cols_lc(pdf)
        for c in cl:
            if "среднее за месяц" in c or "среднее за мес" in c:
                return True
            if "за месяц" in c and ("ресурс" in c or "количество" in c):
                return True
            if "среднее значение" in c and "за месяц" in c:
                return True
        return False

    def _ensure_row_data_source(pdf, default: str):
        """Не затираем колонку data_source из файла (в одной таблице могут быть и люди, и техника)."""
        out = pdf.copy()
        if "data_source" not in out.columns:
            out["data_source"] = default
        else:
            out["data_source"] = out["data_source"].astype(str).str.strip()
        return out

    # load_all_from_web кладёт *resursi*.csv в resources_data; тип по заголовкам / по колонке data_source строки.
    if data_source_filter == "Техника":
        if technique_df is not None and not technique_df.empty:
            combined_df = _ensure_row_data_source(technique_df.copy(), "Техника")
            _gdrs_src_diag = "session_state.technique_data"
        elif resources_df is not None and not resources_df.empty and (
            _like_technique(resources_df) or _has_pivot_date_columns(resources_df)
        ):
            combined_df = _ensure_row_data_source(resources_df.copy(), "Техника")
            _gdrs_src_diag = (
                "session_state.resources_data — структура как у техники (даты ДД.ММ.ГГГГ / «среднее значение за день» / data_source по строкам)"
            )
        elif resources_df is not None and not resources_df.empty and "data_source" in resources_df.columns:
            _rs = resources_df.copy()
            _ds = _rs["data_source"].astype(str).str.strip().str.lower()
            _tech_mask = _ds.isin({"техника", "tech", "technique"})
            if _tech_mask.any():
                combined_df = _ensure_row_data_source(_rs.loc[_tech_mask].copy(), "Техника")
                _gdrs_src_diag = "session_state.resources_data — строки с data_source = техника"
    elif data_source_filter == "Ресурсы":
        if resources_df is not None and not resources_df.empty:
            combined_df = _ensure_row_data_source(resources_df.copy(), "Ресурсы")
            _gdrs_src_diag = "session_state.resources_data"
        elif technique_df is not None and not technique_df.empty and _like_resources(technique_df):
            combined_df = _ensure_row_data_source(technique_df.copy(), "Ресурсы")
            _gdrs_src_diag = "session_state.technique_data — распознаны как ресурсы по месячному среднему"
    else:
        if resources_df is not None and not resources_df.empty:
            combined_df = _ensure_row_data_source(resources_df.copy(), "Ресурсы")
            _gdrs_src_diag = "session_state.resources_data"
        if technique_df is not None and not technique_df.empty:
            if combined_df is not None:
                technique_copy = _ensure_row_data_source(technique_df.copy(), "Техника")
                combined_df = pd.concat(
                    [combined_df, technique_copy], ignore_index=True, sort=False
                )
                _gdrs_src_diag += " + technique_data"
            else:
                combined_df = _ensure_row_data_source(technique_df.copy(), "Техника")
                _gdrs_src_diag = "session_state.technique_data"

    # df из главного приложения: только если структура совпадает (не подменяем людей техникой).
    if (combined_df is None or combined_df.empty) and df is not None and not getattr(df, "empty", True):
        if data_source_filter == "Техника" and (_like_technique(df) or _has_pivot_date_columns(df)):
            combined_df = _ensure_row_data_source(df.copy(), "Техника")
            _gdrs_src_diag = "аргумент df (техника / суточные колонки)"
        elif data_source_filter == "Ресурсы" and (_like_resources(df) or _has_pivot_date_columns(df)):
            combined_df = _ensure_row_data_source(df.copy(), "Ресурсы")
            _gdrs_src_diag = "аргумент df (ресурсы / сводная структура)"

    if combined_df is None or combined_df.empty:
        st.warning(
            "Для отображения графика движения рабочей силы необходимо загрузить файл с данными о ресурсах или технике."
        )
        if data_source_filter == "Техника":
            st.info(
                "**Вкладка «Техника»:** загрузите отдельный файл выгрузки техники (в имени часто есть «техника» / technique) "
                "или общий файл ресурсов, где в колонке **data_source** для строк указано «Техника», "
                "либо таблицу с колонками **«Среднее за неделю»** / суточными датами ДД.ММ.ГГГГ (см. ТЗ PDF, блок ГДРС)."
            )
        else:
            st.info(
                "Ожидаемые колонки: Проект (или Название), Контрагент, Период, План, "
                "**Среднее за месяц** (люди) или **Среднее за неделю** (техника), 1–5 неделя; "
                "при необходимости — «Дельта» / «Дельта (%)». "
                "Файл техники из web/ с именем *resursi* может оказаться только в «ресурсах» — тогда "
                "техника определяется по наличию колонки «Среднее за неделю» или по строкам data_source=техника."
            )
        return

    # При фильтре по вкладке — без учёта регистра в колонке data_source
    if data_source_filter and "data_source" in combined_df.columns:
        combined_df = combined_df[_gdrs_match_data_source(combined_df["data_source"], data_source_filter)].copy()
        if combined_df.empty:
            st.warning(
                f"Нет данных по источнику «{data_source_filter}». Загрузите соответствующий файл."
            )
            return

    work_df = combined_df.copy()
    work_df.columns = [
        str(c).replace("\ufeff", "").replace("\n", " ").replace("\r", " ").strip()
        for c in work_df.columns
    ]
    _plan_src_w = _gdrs_resolve_plan_column(work_df)
    if _plan_src_w and _plan_src_w != "План":
        work_df["План"] = work_df[_plan_src_w]

    def _gdrs_sanitize_plan_column_if_dates(pdf: pd.DataFrame) -> None:
        """Если «План» по факту содержит даты/строки, а не чел.-дни — не используем как число."""
        if pdf is None or pdf.empty or "План" not in pdf.columns:
            return
        raw = pdf["План"]
        dt = pd.to_datetime(raw, errors="coerce", dayfirst=True)
        n = len(pdf)
        if n == 0:
            return
        date_share = float(dt.notna().sum()) / float(n)
        num = pd.to_numeric(
            raw.astype(str)
            .str.replace("\u00a0", "", regex=False)
            .str.replace(" ", "")
            .str.replace(",", "."),
            errors="coerce",
        )
        num_ok = float(num.notna().sum()) / float(n)
        num_sum = float(num.fillna(0).abs().sum())
        # Преобладают распознанные даты при слабом числовом содержании — сбрасываем в 0 (нет плана в файле)
        if date_share >= 0.45 and (num_ok < 0.35 or num_sum < max(1.0, n * 0.25)):
            pdf["План"] = 0

    _gdrs_sanitize_plan_column_if_dates(work_df)

    # На вкладке «всё вместе» — фильтр вида ресурсов; по умолчанию «Рабочие (ресурсы)»
    if (
        data_source_filter is None
        and "data_source" in work_df.columns
        and work_df["data_source"].astype(str).str.strip().nunique(dropna=True) > 1
    ):
        _rk = st.radio(
            "Вид ресурсов",
            ["Рабочие (ресурсы)", "Техника", "Все"],
            index=0,
            horizontal=True,
            key=f"{key_prefix}_resource_kind",
        )
        _ds = work_df["data_source"].astype(str).str.strip().str.lower()
        if _rk == "Рабочие (ресурсы)":
            work_df = work_df[_ds == "ресурсы"].copy()
        elif _rk == "Техника":
            work_df = work_df[_ds == "техника"].copy()
        if work_df.empty:
            st.warning(
                "Нет данных для выбранного вида ресурсов. Загрузите файл или выберите «Все»."
            )
            return

    date_cols_found = [c for c in work_df.columns if _gdrs_header_is_dd_mm_yyyy(c)]
    if date_cols_found and "Период" not in work_df.columns:
        # Определяем период (месяц) по КАЖДОЙ строке на основе датовых колонок,
        # чтобы строки из нескольких файлов (янв/фев) не схлопывались в один месяц.
        _dc_to_period: dict[str, pd.Period] = {}
        for dc in date_cols_found:
            _dc_norm = re.sub(r"\.{2,3}", ".", str(dc).strip())
            _dc_ts = pd.to_datetime(_dc_norm, errors="coerce", dayfirst=True)
            if pd.notna(_dc_ts):
                _dc_to_period[dc] = _dc_ts.to_period("M")

        id_cols = [c for c in ["Проект", "Контрагент", "тип ресурсов", "data_source"]
                   if c in work_df.columns]
        avg_month_col = None
        for c in work_df.columns:
            cl = str(c).lower()
            if "среднее" in cl and ("за месяц" in cl or "количество ресурсов" in cl):
                vals = pd.to_numeric(work_df[c], errors="coerce")
                if vals.notna().any() and (vals != 0).any():
                    avg_month_col = c
                    break
        if not avg_month_col:
            for c in reversed(list(work_df.columns)):
                cl = str(c).lower()
                if "среднее" in cl and not cl.startswith("тип"):
                    vals = pd.to_numeric(work_df[c], errors="coerce")
                    if vals.notna().any() and (vals != 0).any():
                        avg_month_col = c
                        break

        for dc in date_cols_found:
            work_df[dc] = pd.to_numeric(work_df[dc], errors="coerce")

        _row_period_col = "__gdrs_row_period"
        if _dc_to_period:
            _masks = []
            _vals = []
            for _dc, _pr in _dc_to_period.items():
                if _dc in work_df.columns:
                    _masks.append(work_df[_dc].notna())
                    _vals.append(_pr)
            if _masks:
                _row_period = pd.Series(pd.Period("1970-01", freq="M"), index=work_df.index)
                _has_any = pd.Series(False, index=work_df.index)
                for _mk, _pr in zip(_masks, _vals):
                    _set_now = _mk & (~_has_any)
                    if _set_now.any():
                        _row_period.loc[_set_now] = _pr
                        _has_any |= _set_now
                # fallback-1: если строка без датовых значений — пробуем период из source_file (дата в имени файла).
                _fallback_mask = ~_has_any
                if _fallback_mask.any() and "__source_file" in work_df.columns:
                    def _parse_snapshot_date_local(date_str: str):
                        if not date_str:
                            return None
                        for _fmt in ("%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
                            try:
                                return datetime.strptime(str(date_str).strip(), _fmt).date()
                            except ValueError:
                                continue
                        return None

                    def _src_to_period(v):
                        if v is None:
                            return None
                        parts = str(v).replace("\\", "/").split("/")[-1].replace(".csv", "").replace(".CSV", "").split("_")
                        for p in reversed(parts):
                            sd = _parse_snapshot_date_local(p)
                            if sd is not None:
                                try:
                                    return pd.Timestamp(sd).to_period("M")
                                except Exception:
                                    return None
                        return None
                    _src_period = work_df["__source_file"].map(_src_to_period)
                    _src_ok = _src_period.notna() & _fallback_mask
                    if _src_ok.any():
                        _row_period.loc[_src_ok] = _src_period.loc[_src_ok]
                        _has_any |= _src_ok

                # fallback-2: если совсем нечего — используем первый доступный период.
                if _vals:
                    _row_period.loc[~_has_any] = _vals[0]
                work_df[_row_period_col] = _row_period
                if _row_period_col not in id_cols:
                    id_cols.append(_row_period_col)

        if id_cols:
            agg_spec = {dc: (dc, "mean") for dc in date_cols_found}
            if "План" in work_df.columns and "План" not in id_cols:
                agg_spec["План"] = ("План", "first")
            for _wk in range(1, 7):
                wn = f"{_wk} неделя"
                if wn in work_df.columns and wn not in id_cols:
                    agg_spec[wn] = (wn, "first")
            agg = work_df.groupby(id_cols, dropna=False).agg(**agg_spec).reset_index()
            agg["Среднее за месяц"] = agg[date_cols_found].mean(axis=1).round(1)
            if _row_period_col in agg.columns:
                agg["Период"] = agg[_row_period_col]
                agg = agg.drop(columns=[_row_period_col], errors="ignore")
            if avg_month_col and avg_month_col in work_df.columns:
                month_avg = work_df.groupby(id_cols, dropna=False)[avg_month_col].first().reset_index()
                month_avg["_avg_num"] = pd.to_numeric(month_avg[avg_month_col], errors="coerce")
                if month_avg["_avg_num"].notna().any() and (month_avg["_avg_num"] != 0).any():
                    agg["Среднее за месяц"] = month_avg["_avg_num"].values
            agg = agg.drop(columns=date_cols_found, errors="ignore")
            work_df = agg
        else:
            work_df["Среднее за месяц"] = work_df[date_cols_found].mean(axis=1).round(1)
            work_df = work_df.drop(columns=date_cols_found, errors="ignore")

    def find_column_by_partial(df, possible_names):
        """Find column by possible names (exact or partial match)"""
        for col in df.columns:
            col_lower = str(col).lower().strip()
            for name in possible_names:
                name_lower = str(name).lower().strip()
                if (
                    name_lower == col_lower
                    or name_lower in col_lower
                    or col_lower in name_lower
                ):
                    return col
        return None

    # sample_technique_data.csv: Проект, Контрагент, Период, План, Среднее за неделю, 1–5 неделя, Дельта, Дельта (%)
    # Use Russian column names directly

    # Check required columns - Контрагент is essential
    if "Контрагент" not in work_df.columns:
        # Try to find contractor column by partial match
        contractor_col = find_column_by_partial(
            work_df,
            [
                "Контрагент",
                "контрагент",
                "Подразделение",
                "подразделение",
                "contractor",
            ],
        )
        if contractor_col:
            work_df["Контрагент"] = work_df[contractor_col]
        else:
            st.error(f"Отсутствует необходимая колонка 'Контрагент'")
            st.info(f"Доступные колонки: {', '.join(work_df.columns)}")
            return

    # Find week columns dynamically - also try partial match
    week_columns = []
    for week_num in range(1, 6):
        week_col = f"{week_num} неделя"
        if week_col in work_df.columns:
            week_columns.append(week_col)
        else:
            # Try to find by partial match
            found_col = find_column_by_partial(
                work_df,
                [
                    week_col,
                    f"{week_num} недел",
                    f"недел {week_num}",
                    f"week {week_num}",
                ],
            )
            if found_col:
                week_columns.append(found_col)

    # Check if we have any data
    if work_df.empty:
        st.warning("Данные пусты после обработки.")
        return

    for wc in week_columns:
        if wc in work_df.columns:
            work_df[wc] = work_df[wc].fillna(0)
    if "План" in work_df.columns:
        work_df["План"] = work_df["План"].fillna(0)

    # Process numeric columns
    # Process План
    if "План" in work_df.columns:
        work_df["План_numeric"] = pd.to_numeric(
            work_df["План"].astype(str).str.replace(",", ".").str.replace(" ", ""),
            errors="coerce",
        ).fillna(0)
    else:
        work_df["План_numeric"] = 0

    # Process week columns - convert to numeric, handle empty strings
    for week_col in week_columns:
        work_df[f"{week_col}_numeric"] = pd.to_numeric(
            work_df[week_col]
            .astype(str)
            .str.replace(",", ".")
            .str.replace(" ", "")
            .replace("", "0"),
            errors="coerce",
        ).fillna(0)

    def _period_weeks_series(pdf: pd.DataFrame, fallback_weeks: int) -> pd.Series:
        """Число недель в месяце по периоду строки: ceil(days_in_month / 7)."""
        out = pd.Series(float(fallback_weeks), index=pdf.index, dtype="float64")
        if not period_col or period_col not in pdf.columns:
            return out
        parsed_period = pd.to_datetime(pdf[period_col], errors="coerce", dayfirst=True)
        if parsed_period.notna().any():
            out.loc[parsed_period.notna()] = np.ceil(
                parsed_period.loc[parsed_period.notna()].dt.days_in_month / 7.0
            ).astype(float)
        return out

    # Факт: приоритет — явная сумма 1..5 недели; средние используем только как fallback.
    if week_columns:
        week_numeric_cols = [f"{col}_numeric" for col in week_columns]
        work_df["week_sum"] = work_df[week_numeric_cols].sum(axis=1)
        num_weeks = len(week_columns) if week_columns else 4
        work_df["Среднее_за_неделю_numeric"] = (
            work_df["week_sum"] / num_weeks if num_weeks > 0 else 0
        )
    elif "Среднее за месяц" in work_df.columns:
        # Если есть среднее за месяц — это fallback для факта за период
        work_df["Среднее_за_месяц_numeric"] = pd.to_numeric(
            work_df["Среднее за месяц"]
            .astype(str)
            .str.replace(",", ".")
            .str.replace(" ", ""),
            errors="coerce",
        ).fillna(0)
        work_df["week_sum"] = work_df["Среднее_за_месяц_numeric"]
        num_weeks = len(week_columns) if week_columns else 4
        work_df["Среднее_за_неделю_numeric"] = (
            work_df["week_sum"] / num_weeks if num_weeks > 0 else 0
        )
    elif "Среднее за неделю" in work_df.columns:
        # Если есть только среднее за неделю — приводим к факту периода умножением
        # на число недель месяца.
        work_df["Среднее_за_неделю_numeric"] = pd.to_numeric(
            work_df["Среднее за неделю"]
            .astype(str)
            .str.replace(",", ".")
            .str.replace(" ", ""),
            errors="coerce",
        ).fillna(0)
        num_weeks = len(week_columns) if week_columns else 4
        work_df["week_sum"] = work_df["Среднее_за_неделю_numeric"] * _period_weeks_series(
            work_df, num_weeks
        )
    else:
        work_df["week_sum"] = 0
        work_df["Среднее_за_неделю_numeric"] = 0

    # Факт (week_sum) не распознан по канонич. колонкам — пробуем типичные заголовки из файлов
    _ws_sum = float(
        pd.to_numeric(work_df.get("week_sum"), errors="coerce").fillna(0).abs().sum()
    )
    if _ws_sum == 0:
        _col_m = find_column_by_partial(
            work_df,
            ["Среднее за месяц", "среднее за месяц", "среднее за мес", "Среднее за мес"],
        )
        _col_w = find_column_by_partial(
            work_df, ["Среднее за неделю", "среднее за неделю", "средн за нед"]
        )
        if _col_m and _col_m in work_df.columns:
            work_df["week_sum"] = pd.to_numeric(
                work_df[_col_m].astype(str).str.replace(",", ".").str.replace(" ", ""),
                errors="coerce",
            ).fillna(0.0)
            nw = len(week_columns) if week_columns else 4
            if work_df["week_sum"].abs().sum() > 0:
                work_df["Среднее_за_неделю_numeric"] = (
                    work_df["week_sum"] / nw if nw else work_df["week_sum"]
                )
        elif _col_w and _col_w in work_df.columns:
            work_df["Среднее_за_неделю_numeric"] = pd.to_numeric(
                work_df[_col_w].astype(str).str.replace(",", ".").str.replace(" ", ""),
                errors="coerce",
            ).fillna(0.0)
            _nw = len(week_columns) if week_columns else 4
            work_df["week_sum"] = work_df["Среднее_за_неделю_numeric"] * _period_weeks_series(
                work_df, _nw
            )

    # Process Дельта (Delta) if available - try to find column by partial match
    delta_col = None
    if "Дельта" in work_df.columns:
        delta_col = "Дельта"
    else:
        delta_col = find_column_by_partial(
            work_df, ["Дельта", "дельта", "delta", "Delta", "Дельта (без %)"]
        )

    if delta_col and delta_col in work_df.columns:
        work_df["Дельта_numeric"] = pd.to_numeric(
            work_df[delta_col].astype(str).str.replace(",", ".").str.replace(" ", ""),
            errors="coerce",
        ).fillna(0)
    else:
        # Отклонение по ТЗ: СКУД (факт) - план
        work_df["Дельта_numeric"] = work_df["week_sum"] - work_df["План_numeric"]

    # Process Дельта (%) (Delta %) if available - extract numeric value from percentage string
    # Try to find column by partial match
    delta_pct_col = None
    if "Дельта (%)" in work_df.columns:
        delta_pct_col = "Дельта (%)"
    else:
        delta_pct_col = find_column_by_partial(
            work_df,
            [
                "Дельта (%)",
                "Дельта %",
                "дельта (%)",
                "дельта %",
                "Delta %",
                "delta %",
                "Дельта(%)",
                "Дельта%",
            ],
        )

    if delta_pct_col and delta_pct_col in work_df.columns:

        def extract_percentage(value):
            """Extract numeric value from percentage string like '-90%' or '90%', or numeric value"""
            if pd.isna(value):
                return 0
            # If already numeric, return as is
            if isinstance(value, (int, float)):
                return float(value)
            # Otherwise, try to extract from string
            value_str = str(value).strip()
            # Remove % sign and convert to float
            value_str = value_str.replace("%", "").replace(",", ".").replace(" ", "")
            try:
                return float(value_str)
            except:
                return 0

        work_df["Дельта_процент_numeric"] = work_df[delta_pct_col].apply(
            extract_percentage
        )
    else:
        # Calculate delta percentage if we have delta and plan
        work_df["Дельта_процент_numeric"] = 0.0
        if "Дельта_numeric" in work_df.columns and "План_numeric" in work_df.columns:
            mask = work_df["План_numeric"] != 0
            work_df.loc[mask, "Дельта_процент_numeric"] = (
                work_df.loc[mask, "Дельта_numeric"] / work_df.loc[mask, "План_numeric"]
            ) * 100
        work_df["Дельта_процент_numeric"] = work_df["Дельта_процент_numeric"].fillna(0)

    if "Среднее_за_неделю_numeric" not in work_df.columns:
        num_weeks = len(week_columns) if week_columns else 4
        work_df["Среднее_за_неделю_numeric"] = (
            work_df["week_sum"] / num_weeks if num_weeks > 0 else 0
        )

    has_plan_data = (
        "План_numeric" in work_df.columns
        and work_df["План_numeric"].sum() > 0
    )

    # Find Проект column
    project_col = None
    if "Проект" in work_df.columns:
        project_col = "Проект"
    else:
        project_col = find_column_by_partial(
            work_df,
            [
                "Проект",
                "проект",
                "project",
                "Project",
                "Название",
                "название",
                "Название проекта",
                "Наименование проекта",
            ],
        )

    period_col = _gdrs_resolve_period_column(work_df)
    if period_col is None:
        work_df = work_df.copy()
        # 1) По заголовкам-датам (самый частый кейс web/AI resources).
        _date_cols_fb = [c for c in work_df.columns if _gdrs_header_is_dd_mm_yyyy(c)]
        _dt_fb = pd.Series(dtype="datetime64[ns]")
        if _date_cols_fb:
            _hdr_fb = (
                pd.Series(_date_cols_fb)
                .astype(str)
                .str.replace(r"\.{2,3}", ".", regex=True)
                .str.strip()
            )
            _dt_fb = pd.to_datetime(_hdr_fb, errors="coerce", dayfirst=True).dropna()
        # 2) Из snapshot_date, если есть.
        if _dt_fb.empty and "snapshot_date" in work_df.columns:
            _sdt = pd.to_datetime(work_df["snapshot_date"], errors="coerce").dropna()
            if not _sdt.empty:
                # Берём по строкам из snapshot_date, чтобы в фильтре был выбор месяцев.
                work_df["Период"] = pd.to_datetime(
                    work_df["snapshot_date"], errors="coerce"
                ).dt.to_period("M")
                period_col = "Период"
        if period_col is None and not _dt_fb.empty:
            work_df["Период"] = _dt_fb.iloc[0].to_period("M")
            period_col = "Период"
        if period_col is None:
            # Последний fallback для уже загруженных/старых версий без period/snapshot:
            # не даём фильтру периода пропасть из UI.
            work_df["Период"] = pd.Timestamp.today().to_period("M")
            period_col = "Период"

    col1, col2, col3 = st.columns(3)

    with col1:
        if project_col and project_col in work_df.columns:
            all_projects = sorted(work_df[project_col].dropna().unique().tolist())
            selected_projects = st.multiselect(
                "Фильтр по проектам (можно выбрать несколько)",
                all_projects,
                default=all_projects if len(all_projects) <= 3 else all_projects[:3],
                key=f"{key_prefix}_projects",
                placeholder="Выберите проекты",
            )
        else:
            selected_projects = []
            st.info("Колонка 'Проект' не найдена")

    with col2:
        if "Контрагент" in work_df.columns:
            contractors = ["Все"] + sorted(
                work_df["Контрагент"].dropna().unique().tolist()
            )
            selected_contractor = st.selectbox(
                "Фильтр по контрагенту", contractors, key=f"{key_prefix}_contractor"
            )
        else:
            selected_contractor = "Все"
            st.info("Колонка 'Контрагент' не найдена")

    selected_periods = []
    selected_daily_dates: list[pd.Timestamp] = []
    # Локально вычисляем даты из заголовков, чтобы исключить NameError при любых рефакторах выше.
    _daily_dates: list[pd.Timestamp] = []
    _date_cols_local = [c for c in work_df.columns if _gdrs_header_is_dd_mm_yyyy(c)]
    if _date_cols_local:
        _hdr_local = (
            pd.Series(_date_cols_local)
            .astype(str)
            .str.replace(r"\.{2,3}", ".", regex=True)
            .str.strip()
        )
        _parsed_local = pd.to_datetime(_hdr_local, errors="coerce", dayfirst=True).dropna()
        if not _parsed_local.empty:
            _daily_dates = sorted(
                list({pd.Timestamp(d).normalize() for d in _parsed_local.tolist()})
            )
    with col3:
        # По ТЗ: фильтр периода — диапазон дат.
        _min_dt = None
        _max_dt = None
        if len(_daily_dates) > 1:
            _min_dt = _daily_dates[0].date()
            _max_dt = _daily_dates[-1].date()
        elif period_col and period_col in work_df.columns:
            _pdt = pd.to_datetime(work_df[period_col], errors="coerce", dayfirst=True).dropna()
            if not _pdt.empty:
                _min_dt = _pdt.min().date()
                _max_dt = _pdt.max().date()
        if _min_dt is None or _max_dt is None:
            _min_dt = (date.today().replace(day=1))
            _max_dt = date.today()

        _rng = st.date_input(
            "Период (диапазон дат)",
            value=(_min_dt, _max_dt),
            key=f"{key_prefix}_period_range",
        )
        _d_from = None
        _d_to = None
        try:
            if isinstance(_rng, (tuple, list)) and len(_rng) == 2:
                _d_from, _d_to = _rng[0], _rng[1]
            else:
                _d_from = _rng
                _d_to = _rng
        except Exception:
            _d_from, _d_to = _min_dt, _max_dt
        if _d_from and _d_to and _d_from > _d_to:
            _d_from, _d_to = _d_to, _d_from
        if len(_daily_dates) > 1:
            selected_daily_dates = [
                d for d in _daily_dates if (_d_from <= d.date() <= _d_to)
            ]
        elif period_col and period_col in work_df.columns:
            selected_periods = []
        else:
            st.info("Колонка 'Период' не найдена")

    # Apply filters
    filtered_df = work_df.copy()
    if selected_projects and project_col and project_col in filtered_df.columns:
        project_mask = (
            filtered_df[project_col]
            .astype(str)
            .str.strip()
            .isin([str(p).strip() for p in selected_projects])
        )
        filtered_df = filtered_df[project_mask]
    if selected_contractor != "Все" and "Контрагент" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["Контрагент"].astype(str).str.strip()
            == str(selected_contractor).strip()
        ]
    # Для файлов с суточными колонками: пересчёт План/Факт пропорционально выбранному диапазону дат.
    if len(_daily_dates) > 1:
        total_days = len(_daily_dates)
        picked_days = len(selected_daily_dates) if selected_daily_dates else total_days
        day_ratio = (float(picked_days) / float(total_days)) if total_days else 1.0
        filtered_df = filtered_df.copy()
        if "week_sum" in filtered_df.columns:
            filtered_df["week_sum"] = (
                pd.to_numeric(filtered_df["week_sum"], errors="coerce").fillna(0.0) * day_ratio
            )
        if "План_numeric" in filtered_df.columns:
            filtered_df["План_numeric"] = (
                pd.to_numeric(filtered_df["План_numeric"], errors="coerce").fillna(0.0) * day_ratio
            )
        if "Дельта_numeric" in filtered_df.columns:
            filtered_df["Дельта_numeric"] = filtered_df["week_sum"] - filtered_df["План_numeric"]
    # Для месячных периодов (без суточных колонок): фильтрация/пересчёт по пересечению диапазона дат с месяцем строки.
    if len(_daily_dates) <= 1 and period_col and period_col in filtered_df.columns and _d_from and _d_to:
        _pf = pd.Timestamp(_d_from)
        _pt = pd.Timestamp(_d_to)
        _pser = pd.to_datetime(filtered_df[period_col], errors="coerce", dayfirst=True)
        if _pser.notna().any():
            _month_start = _pser.dt.to_period("M").dt.start_time
            _month_end = _pser.dt.to_period("M").dt.end_time
            _lo = pd.concat([_month_start, pd.Series([_pf] * len(filtered_df), index=filtered_df.index)], axis=1).max(axis=1)
            _hi = pd.concat([_month_end, pd.Series([_pt] * len(filtered_df), index=filtered_df.index)], axis=1).min(axis=1)
            _overlap_days = (_hi - _lo).dt.total_seconds() / 86400.0 + 1.0
            _overlap_days = _overlap_days.clip(lower=0.0)
            _days_in_month = _pser.dt.days_in_month.astype(float)
            _ratio = (_overlap_days / _days_in_month).fillna(0.0).clip(lower=0.0, upper=1.0)
            keep = _ratio > 0.0
            filtered_df = filtered_df[keep].copy()
            if not filtered_df.empty:
                _ratio = _ratio.loc[filtered_df.index]
                for _col in ("week_sum", "План_numeric", "Дельта_numeric"):
                    if _col in filtered_df.columns:
                        filtered_df[_col] = pd.to_numeric(filtered_df[_col], errors="coerce").fillna(0.0) * _ratio
                for _wk in range(1, 7):
                    _wn = f"{_wk} неделя_numeric"
                    if _wn in filtered_df.columns:
                        filtered_df[_wn] = pd.to_numeric(filtered_df[_wn], errors="coerce").fillna(0.0) * _ratio

    if filtered_df.empty:
        st.info("Нет данных для отображения с выбранными фильтрами.")
        return

    # Ensure Контрагент column exists and has values
    if (
        "Контрагент" not in filtered_df.columns
        or filtered_df["Контрагент"].isna().all()
    ):
        st.error("Колонка 'Контрагент' отсутствует или пуста после фильтрации.")
        return

    # Remove rows where Контрагент is NaN before grouping
    filtered_df = filtered_df[filtered_df["Контрагент"].notna()].copy()

    if filtered_df.empty:
        st.info("Нет данных с указанными контрагентами после фильтрации.")
        return

    # Определяем список проектов для обработки
    if selected_projects and project_col and project_col in filtered_df.columns:
        projects_to_process = selected_projects
    else:
        # Если проекты не выбраны или колонка не найдена, обрабатываем все проекты
        if project_col and project_col in filtered_df.columns:
            projects_to_process = sorted(
                filtered_df[project_col].dropna().unique().tolist()
            )
        else:
            projects_to_process = ["Все проекты"]

    # Референсная таблица ГДРС: проект -> контрагент -> вид работ.
    # Маппинг по ТЗ: План = договор, СКУД = выгрузка ресурсов, Отклонение = СКУД - План.
    if "Контрагент" in filtered_df.columns:
        st.markdown("#### График движения рабочей силы (люди)")
        _tbl = filtered_df.copy()

        def _to_num_safe(series):
            s = (
                series.astype(str)
                .str.replace("\u00a0", "", regex=False)
                .str.replace(" ", "", regex=False)
                .str.replace(",", ".", regex=False)
            )
            s = s.str.replace(r"[^0-9\.\-]+", "", regex=True)
            return pd.to_numeric(s, errors="coerce").fillna(0.0)

        # СКУД берём из выгрузки ресурсов.
        if "data_source" in _tbl.columns:
            _res_mask = _gdrs_match_data_source(_tbl["data_source"], "Ресурсы")
            if _res_mask.any():
                _tbl = _tbl.loc[_res_mask].copy()

        if not _tbl.empty:
            _work_type_col = find_column_by_partial(
                _tbl,
                ["Вид работ", "Вид работы", "вид работ", "вид работы", "тип ресурсов", "тип работ", "work type"],
            )

            # План из договора (приоритетно), fallback — План_numeric/План.
            _tbl["_plan_ref_numeric"] = pd.Series(0.0, index=_tbl.index, dtype="float64")
            _plan_candidate = None
            for _c in _tbl.columns:
                _cl = str(_c).lower()
                if "договор" in _cl and ("план" in _cl or "колич" in _cl):
                    _plan_candidate = _c
                    break
            if _plan_candidate is None:
                _plan_candidate = _gdrs_resolve_plan_column(_tbl)
            if _plan_candidate and _plan_candidate in _tbl.columns:
                _tbl["_plan_ref_numeric"] = _to_num_safe(_tbl[_plan_candidate])
            elif "План_numeric" in _tbl.columns:
                _tbl["_plan_ref_numeric"] = pd.to_numeric(
                    _tbl["План_numeric"], errors="coerce"
                ).fillna(0.0)
            elif "План" in _tbl.columns:
                _tbl["_plan_ref_numeric"] = _to_num_safe(_tbl["План"])

            _daily_hdr_cols = [c for c in _tbl.columns if _gdrs_header_is_dd_mm_yyyy(c)]
            _weeks_in_month = 4
            if period_col and period_col in _tbl.columns:
                _period_dt = pd.to_datetime(_tbl[period_col], errors="coerce", dayfirst=True)
                if _period_dt.notna().any():
                    _weeks_in_month = int(np.ceil(_period_dt.dt.days_in_month.dropna().max() / 7.0))
            elif _daily_hdr_cols:
                _parsed_hdr = pd.to_datetime(
                    pd.Series(_daily_hdr_cols).astype(str).str.replace(r"\.{2,3}", ".", regex=True),
                    errors="coerce",
                    dayfirst=True,
                ).dropna()
                if not _parsed_hdr.empty:
                    _weeks_in_month = int(np.ceil(_parsed_hdr.iloc[0].days_in_month / 7.0))
            _weeks_in_month = max(1, min(6, _weeks_in_month))

            _week_cols_out = [f"{i} неделя" for i in range(1, _weeks_in_month + 1)]
            _week_map = {}
            for i in range(1, _weeks_in_month + 1):
                _wcol = find_column_by_partial(
                    _tbl, [f"{i} неделя", f"{i} недел", f"недел {i}", f"week {i}"]
                )
                if _wcol and _wcol in _tbl.columns:
                    _week_map[f"{i} неделя"] = _wcol

            if (not _week_map) and _daily_hdr_cols:
                for i in range(1, _weeks_in_month + 1):
                    _tbl[f"{i} неделя_numeric"] = 0.0
                for _dc in _daily_hdr_cols:
                    _ts = pd.to_datetime(
                        re.sub(r"\.{2,3}", ".", str(_dc).strip()),
                        errors="coerce",
                        dayfirst=True,
                    )
                    if pd.isna(_ts):
                        continue
                    _widx = max(1, min(_weeks_in_month, int(np.ceil(int(_ts.day) / 7.0))))
                    _vals = pd.to_numeric(_tbl[_dc], errors="coerce").fillna(0.0)
                    if float(_vals.abs().sum()) == 0.0:
                        _vals = _to_num_safe(_tbl[_dc])
                    _tbl[f"{_widx} неделя_numeric"] = (
                        pd.to_numeric(_tbl[f"{_widx} неделя_numeric"], errors="coerce").fillna(0.0)
                        + _vals
                    )

            for _w in _week_cols_out:
                if f"{_w}_numeric" not in _tbl.columns:
                    if _w in _week_map:
                        _src = _week_map[_w]
                        _vals = pd.to_numeric(_tbl[_src], errors="coerce").fillna(0.0)
                        if float(_vals.abs().sum()) == 0.0:
                            _vals = _to_num_safe(_tbl[_src])
                        _tbl[f"{_w}_numeric"] = _vals
                    else:
                        _tbl[f"{_w}_numeric"] = 0.0

            _group_cols = []
            if project_col and project_col in _tbl.columns:
                _group_cols.append(project_col)
            _group_cols.append("Контрагент")
            if _work_type_col and _work_type_col in _tbl.columns:
                _group_cols.append(_work_type_col)

            _agg = {"_plan_ref_numeric": "sum"}
            for _w in _week_cols_out:
                _agg[f"{_w}_numeric"] = "sum"
            _ref = _tbl.groupby(_group_cols, as_index=False, dropna=False).agg(_agg)
            _ref = _ref.rename(columns={"_plan_ref_numeric": "План"})

            for _w in _week_cols_out:
                _ref[_w] = pd.to_numeric(_ref[f"{_w}_numeric"], errors="coerce").fillna(0.0)
            _ref["СКУД"] = (
                _ref[_week_cols_out].sum(axis=1) / float(_weeks_in_month)
            ).round(0)
            _ref["План"] = pd.to_numeric(_ref["План"], errors="coerce").fillna(0.0)
            _ref["Отклонение"] = _ref["СКУД"] - _ref["План"]
            _ref["Дельта (%)"] = _ref.apply(
                lambda r: round(float(r["Отклонение"]) / float(r["План"]) * 100.0, 1)
                if float(r["План"]) != 0.0
                else None,
                axis=1,
            )

            if _work_type_col and _work_type_col in _ref.columns:
                _ref = _ref.rename(columns={_work_type_col: "Вид работ"})
            else:
                _ref["Вид работ"] = "—"
            if project_col and project_col in _ref.columns:
                _ref["_Проект"] = _ref[project_col].fillna("Без проекта").astype(str).str.strip()
            else:
                _ref["_Проект"] = "Все проекты"

            def _agg_block(_sub: pd.DataFrame) -> dict:
                _plan = float(pd.to_numeric(_sub["План"], errors="coerce").fillna(0.0).sum())
                _ws = {w: float(pd.to_numeric(_sub[w], errors="coerce").fillna(0.0).sum()) for w in _week_cols_out}
                _skud = int(round(sum(_ws.values()) / float(_weeks_in_month), 0))
                _dev = float(_skud - _plan)
                _pct = round((_dev / _plan) * 100.0, 1) if _plan != 0.0 else None
                return {"План": _plan, "СКУД": _skud, "Отклонение": _dev, **_ws, "Дельта (%)": _pct}

            _rows = []
            for _proj in sorted(_ref["_Проект"].unique(), key=lambda x: str(x)):
                _p = _ref[_ref["_Проект"] == _proj]
                _rows.append(
                    {"Проект": str(_proj), "Контрагент": "", "Вид работ": "", **_agg_block(_p)}
                )
                for _ctr in sorted(_p["Контрагент"].dropna().unique(), key=lambda x: str(x)):
                    _c = _p[_p["Контрагент"].astype(str) == str(_ctr)]
                    _rows.append(
                        {"Проект": "", "Контрагент": str(_ctr), "Вид работ": "", **_agg_block(_c)}
                    )
                    _d = _c.sort_values("Вид работ", na_position="last")
                    for _, _r in _d.iterrows():
                        _rows.append(
                            {
                                "Проект": "",
                                "Контрагент": "",
                                "Вид работ": _r.get("Вид работ", ""),
                                "План": _r["План"],
                                "СКУД": _r["СКУД"],
                                "Отклонение": _r["Отклонение"],
                                **{w: _r[w] for w in _week_cols_out},
                                "Дельта (%)": _r["Дельта (%)"],
                            }
                        )

            _view = pd.DataFrame(_rows)
            _grand = _agg_block(_ref)
            _view = pd.concat(
                [
                    _view,
                    pd.DataFrame(
                        [{"Проект": "Итого", "Контрагент": "", "Вид работ": "", **_grand}]
                    ),
                ],
                ignore_index=True,
            )
            for _c in ["План", "СКУД", "Отклонение"] + _week_cols_out:
                _view[_c] = pd.to_numeric(_view[_c], errors="coerce").fillna(0).round(0).astype(int)
            _view["Дельта (%)"] = _view["Дельта (%)"].apply(
                lambda v: f"{float(v):.1f}%" if v is not None and pd.notna(v) else ""
            )

            # Диагностика кейса «План = Факт»: в референсе это считается подозрительным.
            try:
                _pl_sum = float(pd.to_numeric(_ref["План"], errors="coerce").fillna(0.0).sum())
                _sk_sum = float(pd.to_numeric(_ref["СКУД"], errors="coerce").fillna(0.0).sum())
                if _pl_sum > 0 and _sk_sum > 0 and abs(_pl_sum - _sk_sum) <= max(1.0, 0.001 * _pl_sum):
                    st.caption(
                        "Проверка данных: сумма «План» ≈ сумме «СКУД» (план почти равен факту). "
                        "Если по проекту это не ожидается — проверьте маппинг колонок плана (договор) и факта (ресурсы/недели)."
                    )
            except Exception:
                pass

            _show_cols = (
                ["Проект", "Контрагент", "Вид работ", "План", "СКУД", "Отклонение"]
                + _week_cols_out
                + ["Дельта (%)"]
            )
            st.caption("Иерархия строк: **проект** → **контрагент** → **вид работ**.")
            st.markdown(
                budget_table_to_html(
                    _view[_show_cols],
                    finance_deviation_column="Отклонение",
                    deviation_red_if_negative=True,
                ),
                unsafe_allow_html=True,
            )

    period_col_hist = _gdrs_resolve_period_column(filtered_df)
    if period_col_hist and "week_sum" in filtered_df.columns:
        sources_hist = []
        if "data_source" in filtered_df.columns:
            sources_hist = filtered_df["data_source"].dropna().unique().tolist()
        else:
            sources_hist = [None]
        source_labels_hist = []
        for s in sources_hist:
            if s is None:
                source_labels_hist.append("Данные")
            elif str(s).strip() == "Ресурсы":
                source_labels_hist.append("Люди (ресурсы)")
            elif str(s).strip() == "Техника":
                source_labels_hist.append("Техника")
            else:
                source_labels_hist.append(str(s))
        hist_cols = st.columns(max(1, len(sources_hist)))
        for idx, (src, label) in enumerate(zip(sources_hist, source_labels_hist)):
            if src is None:
                df_hist = filtered_df.copy()
            else:
                df_hist = filtered_df[_gdrs_match_data_source(filtered_df["data_source"], src)].copy()
            if df_hist.empty:
                with hist_cols[idx]:
                    st.info(f"**{label}** — нет данных для графика «Факт по периодам».")
                continue
            # Колонки по неделям (1 неделя_numeric, 2 неделя_numeric, ...)
            week_numeric_cols_hist = [
                c for c in df_hist.columns
                if isinstance(c, str) and "_numeric" in c and "недел" in c.lower()
            ]
            if not week_numeric_cols_hist:
                for i in range(1, 7):
                    cn = f"{i} неделя_numeric"
                    if cn in df_hist.columns:
                        week_numeric_cols_hist.append(cn)
            week_numeric_cols_hist = sorted(week_numeric_cols_hist, key=lambda c: (
                int(c.split()[0]) if c.split() and c.split()[0].isdigit() else 99
            ))
            if week_numeric_cols_hist:
                # Группировка по периоду, точки — по неделям: melt по неделям, затем groupby(период, неделя)
                id_vars = [period_col_hist]
                value_vars = [c for c in week_numeric_cols_hist if c in df_hist.columns]
                if value_vars:
                    long_df = df_hist[id_vars + value_vars].melt(
                        id_vars=id_vars,
                        value_vars=value_vars,
                        var_name="Неделя",
                        value_name="Факт",
                    )
                    long_df["Неделя"] = long_df["Неделя"].str.replace("_numeric", "").str.strip()
                    long_df["Факт"] = pd.to_numeric(long_df["Факт"], errors="coerce").fillna(0)
                    by_period_week = (
                        long_df.groupby([period_col_hist, "Неделя"], as_index=False)["Факт"]
                        .sum()
                    )
                    by_period_week["Период_стр"] = by_period_week[period_col_hist].astype(str).str.strip()
                    by_period_week = _gdrs_point_pct_of_period_plan(
                        by_period_week, df_hist, period_col_hist, "Факт"
                    )
                else:
                    by_period_week = None
            else:
                by_period_week = None
            if by_period_week is not None and not by_period_week.empty:
                fig_hist = go.Figure()
                is_resources = "Ресурсы" in label or "Люди" in label
                base_color = "#3498db" if is_resources else "#e67e22"
                weeks = by_period_week["Неделя"].unique().tolist()
                # Люди и техника: точечная диаграмма — одна линия через все точки по порядку (период → неделя)
                by_period_week = by_period_week.copy()
                by_period_week["x_label"] = (
                    by_period_week["Период_стр"].astype(str)
                    + " — "
                    + by_period_week["Неделя"].astype(str).str.replace(" неделя", "н", regex=False)
                )
                by_period_week = by_period_week.sort_values([period_col_hist, "Неделя"])
                x_order = by_period_week["x_label"].tolist()
                _mk_week_lbl_w = lambda r: (
                    f"{int(r['Факт'])} ({int(np.ceil(float(r['%'])))}%)"
                )
                _mk_week_hover_w = lambda r: (
                    f"Факт: {int(r['Факт'])}<br>"
                    f"План (период): {int(np.ceil(float(r['План_период']))) if pd.notna(r.get('План_период')) and float(r.get('План_период') or 0) > 0 else '—'}<br>"
                    f"К плану: {int(np.ceil(float(r['%'])))}%"
                )
                fig_hist.add_trace(
                    go.Scatter(
                        x=by_period_week["x_label"],
                        y=by_period_week["Факт"],
                        name="Факт",
                        mode="lines+markers+text",
                        line=dict(color=base_color, width=2),
                        marker=dict(size=10, color=base_color, line=dict(width=1, color="white")),
                        text=[_mk_week_lbl_w(r) for _, r in by_period_week.iterrows()],
                        textposition="top center",
                        textfont=dict(size=9, color="white"),
                        hovertext=[_mk_week_hover_w(r) for _, r in by_period_week.iterrows()],
                        hovertemplate="%{x}<br>%{hovertext}<extra></extra>",
                        connectgaps=False,
                        cliponaxis=False,
                    )
                )
                fig_hist.update_layout(
                    title_text="",
                    xaxis_title="Период — неделя",
                    yaxis_title="Количество",
                    height=440,
                    showlegend=False,
                    margin=dict(l=56, r=28, t=56, b=168),
                    uniformtext=dict(minsize=7, mode="show"),
                    xaxis=dict(
                        tickangle=-45,
                        categoryorder="array",
                        categoryarray=x_order,
                        automargin=True,
                    ),
                    yaxis=dict(automargin=True),
                )
                fig_hist = apply_chart_background(fig_hist)
                with hist_cols[idx]:
                    render_chart(
                        fig_hist,
                        key=f"{key_prefix}_hist_period_{idx}",
                        caption_below=(
                            f"Факт по периодам (недели), % к сумме плана периода (округление вверх): {label}"
                        ),
                    )
            else:
                # Нет колонок по неделям — один столбец/точка на период (сумма)
                by_period = (
                    df_hist.groupby(period_col_hist, as_index=False)["week_sum"]
                    .sum()
                    .rename(columns={"week_sum": "Факт"})
                )
                by_period["Период_стр"] = by_period[period_col_hist].astype(str).str.strip()
                by_period = _gdrs_point_pct_of_period_plan(
                    by_period, df_hist, period_col_hist, "Факт"
                )
                by_period = by_period.sort_values(period_col_hist)
                with hist_cols[idx]:
                    fig_hist = go.Figure()
                    is_resources_fb = "Ресурсы" in label or "Люди" in label
                    if is_resources_fb:
                        fig_hist.add_trace(
                            go.Scatter(
                                x=by_period["Период_стр"],
                                y=by_period["Факт"],
                                mode="markers+text",
                                name="Факт",
                                marker=dict(size=14, color="#3498db", line=dict(width=1, color="white")),
                                text=[
                                    f"{int(row['Факт'])} ({int(np.ceil(float(row['%'])))}%)"
                                    for _, row in by_period.iterrows()
                                ],
                                textposition="top center",
                                textfont=dict(size=11, color="white"),
                                cliponaxis=False,
                            )
                        )
                    else:
                        fig_hist.add_trace(
                            go.Bar(
                                x=by_period["Период_стр"],
                                y=by_period["Факт"],
                                text=[
                                    f"{int(row['Факт'])} ({int(np.ceil(float(row['%'])))}%)"
                                    for _, row in by_period.iterrows()
                                ],
                                textposition="outside",
                                textfont=dict(size=11, color="white"),
                                marker_color="#e67e22",
                                name="Факт",
                                cliponaxis=False,
                            )
                        )
                    fig_hist.update_layout(
                        title_text="",
                        xaxis_title="Период",
                        yaxis_title="Количество",
                        height=440,
                        showlegend=False,
                        margin=dict(l=56, r=28, t=56, b=168),
                        uniformtext=dict(minsize=7, mode="show"),
                        xaxis=dict(tickangle=-45, automargin=True),
                        yaxis=dict(automargin=True),
                    )
                    fig_hist = _apply_finance_bar_label_layout(fig_hist)
                    try:
                        fig_hist.update_layout(
                            uniformtext=dict(minsize=6, mode="show"),
                            margin=dict(l=56, r=36, t=88, b=180),
                        )
                    except Exception:
                        pass
                    fig_hist = apply_chart_background(fig_hist)
                    render_chart(
                        fig_hist,
                        key=f"{key_prefix}_hist_period_fallback_{idx}",
                        caption_below=f"Факт по периодам, % к сумме плана периода (округление вверх): {label}",
                    )

    elif "week_sum" in filtered_df.columns:
        with st.expander("Нет колонки «Период» в файле", expanded=False):
            st.caption(
                "Показан суммарный факт по подрядчикам (агрегация без оси периода в данных)."
            )
        sources_wfb = []
        if "data_source" in filtered_df.columns:
            sources_wfb = filtered_df["data_source"].dropna().unique().tolist()
        else:
            sources_wfb = [None]
        labels_wfb = []
        for s in sources_wfb:
            if s is None:
                labels_wfb.append("Данные")
            elif str(s).strip().lower() in ("ресурсы", "ресурс"):
                labels_wfb.append("Люди (ресурсы)")
            elif str(s).strip().lower() in ("техника", "tech", "technique"):
                labels_wfb.append("Техника")
            else:
                labels_wfb.append(str(s))
        wfb_cols = st.columns(max(1, len(sources_wfb)))
        for wfi, (src_wfb, lab_wfb) in enumerate(zip(sources_wfb, labels_wfb)):
            if src_wfb is None:
                df_wfb = filtered_df.copy()
            else:
                df_wfb = filtered_df[_gdrs_match_data_source(filtered_df["data_source"], src_wfb)].copy()
            if df_wfb.empty or "Контрагент" not in df_wfb.columns:
                with wfb_cols[wfi]:
                    st.info(f"**{lab_wfb}** — нет данных для «Факт по подрядчикам».")
                continue
            by_w = (
                df_wfb.groupby("Контрагент", as_index=False)["week_sum"]
                .sum()
                .assign(Факт=lambda x: pd.to_numeric(x["week_sum"], errors="coerce").fillna(0))
            )
            by_w = by_w[by_w["Факт"].abs() > 0].sort_values("Факт", ascending=False)
            if by_w.empty:
                with wfb_cols[wfi]:
                    st.info(f"**{lab_wfb}** — нет ненулевых значений по подрядчикам.")
                continue
            tw = float(by_w["Факт"].sum())
            by_w["pct"] = (by_w["Факт"] / tw * 100.0).round(1) if tw else 0.0
            is_rw = "ресурс" in lab_wfb.lower() or "люди" in lab_wfb.lower()
            cbar = "#3498db" if is_rw else "#e67e22"
            fig_wfb = go.Figure(
                data=[
                    go.Bar(
                        x=by_w["Контрагент"],
                        y=by_w["Факт"],
                        marker_color=cbar,
                        text=[f"{int(r['Факт'])} ({r['pct']}%)" for _, r in by_w.iterrows()],
                        textposition="outside",
                        textfont=dict(size=11, color="white"),
                        cliponaxis=False,
                    )
                ]
            )
            fig_wfb.update_layout(
                title_text="",
                xaxis_title="Контрагент",
                yaxis_title="Факт (сумма)",
                height=440,
                showlegend=False,
                xaxis=dict(tickangle=-45, automargin=True),
                yaxis=dict(automargin=True),
            )
            fig_wfb = _apply_finance_bar_label_layout(fig_wfb)
            try:
                fig_wfb.update_layout(
                    uniformtext=dict(minsize=6, mode="show"),
                    margin=dict(l=56, r=36, t=88, b=168),
                )
            except Exception:
                pass
            fig_wfb = apply_chart_background(fig_wfb)
            with wfb_cols[wfi]:
                render_chart(
                    fig_wfb,
                    key=f"{key_prefix}_hist_noperiod_{wfi}",
                    caption_below=f"Факт по подрядчикам (нет колонки периода): {lab_wfb}",
                )

    # Несколько проектов — круговые «план/факт» в одну строку, сводка справа
    def _gdrs_plan_fact_data_slice(pdf: pd.DataFrame) -> pd.DataFrame:
        if pdf is None or pdf.empty:
            return pdf
        if "data_source" not in pdf.columns:
            return pdf
        dst = (data_source_filter or "").strip().lower()
        if dst == "техника":
            return pdf[
                pdf["data_source"].astype(str).str.strip().str.lower() == "техника"
            ].copy()
        if dst == "ресурсы":
            return pdf[
                pdf["data_source"].astype(str).str.strip().str.lower() == "ресурсы"
            ].copy()
        rk = st.session_state.get(f"{key_prefix}_resource_kind", "Рабочие (ресурсы)")
        if rk == "Техника":
            return pdf[
                pdf["data_source"].astype(str).str.strip().str.lower() == "техника"
            ].copy()
        if rk == "Все":
            return pdf[
                pdf["data_source"].astype(str).str.strip().str.lower() == "ресурсы"
            ].copy()
        return pdf[pdf["data_source"].astype(str).str.strip().str.lower() == "ресурсы"].copy()

    def _gdrs_plan_fact_fig_and_metrics(pdf: pd.DataFrame):
        d = _gdrs_plan_fact_data_slice(pdf)
        if d is None or d.empty or "План_numeric" not in d.columns or "week_sum" not in d.columns:
            return None, None
        plan_sum = float(pd.to_numeric(d["План_numeric"], errors="coerce").fillna(0).sum())
        fact_sum = float(pd.to_numeric(d["week_sum"], errors="coerce").fillna(0).sum())
        if plan_sum <= 0 and fact_sum <= 0:
            return None, None
        dev = fact_sum - plan_sum
        fp_pct = (fact_sum / plan_sum * 100.0) if plan_sum else 0.0
        proj_col_local = "project name" if "project name" in d.columns else ("Проект" if "Проект" in d.columns else None)
        proj_name = "Все проекты"
        if proj_col_local and proj_col_local in d.columns:
            _u = d[proj_col_local].dropna().astype(str).str.strip().unique().tolist()
            if len(_u) == 1:
                proj_name = _u[0]

        def _fact_bar_color(plan_v: float, fact_v: float) -> str:
            # План — отдельный столбец; факт — рыжий при норме; просадка — красный градиент; 0 — ярко-красный.
            _orange = "#e67e22"
            if plan_v <= 0:
                return _orange
            if float(fact_v) <= 0:
                return "#c0392b"
            if fact_v >= plan_v:
                return _orange
            miss_ratio = max(0.0, min(1.0, (plan_v - fact_v) / plan_v))
            lo = (255, 179, 179)
            hi = (192, 57, 43)
            rr = int(round(lo[0] + (hi[0] - lo[0]) * miss_ratio))
            gg = int(round(lo[1] + (hi[1] - lo[1]) * miss_ratio))
            bb = int(round(lo[2] + (hi[2] - lo[2]) * miss_ratio))
            return f"#{rr:02x}{gg:02x}{bb:02x}"

        fact_color = _fact_bar_color(plan_sum, fact_sum)

        def _ceil_int(v: float) -> int:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                return 0
            if fv >= 0:
                return int(np.ceil(fv))
            return -int(np.ceil(abs(fv)))

        plan_i = _ceil_int(plan_sum)
        fact_i = _ceil_int(fact_sum)
        dev_i = _ceil_int(dev)
        # Столбчатая план/факт: подписи над столбцами, нули видны (круговая скрывает нулевой сегмент)
        fig_pie_pf = go.Figure(
            data=[
                go.Bar(
                    x=["План", "Факт"],
                    y=[plan_sum, fact_sum],
                    marker_color=["#5dade2", fact_color],
                    text=[
                        f"{plan_i}",
                        f"{fact_i}<br>Δ {dev_i}",
                    ],
                    textposition="outside",
                    textfont=dict(size=13, color="#ffffff"),
                    cliponaxis=False,
                    customdata=[
                        [proj_name, plan_i, fact_i, dev_i],
                        [proj_name, plan_i, fact_i, dev_i],
                    ],
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "Проект: %{customdata[0]}<br>"
                        "План: %{customdata[1]}<br>"
                        "Факт: %{customdata[2]}<br>"
                        "Отклонение: %{customdata[3]}<extra></extra>"
                    ),
                )
            ]
        )
        fig_pie_pf.update_layout(
            height=420,
            showlegend=False,
            title_font_size=14,
            margin=dict(l=48, r=28, t=56, b=72),
            yaxis=dict(title=""),
            uniformtext=dict(minsize=7, mode="show"),
        )
        fig_pie_pf = _apply_bar_uniformtext(fig_pie_pf)
        try:
            fig_pie_pf.update_layout(uniformtext=dict(minsize=6, mode="show"))
        except Exception:
            pass
        fig_pie_pf = apply_chart_background(fig_pie_pf)
        return fig_pie_pf, {
            "plan": plan_sum,
            "fact": fact_sum,
            "dev": dev,
            "fp_pct": fp_pct,
        }

    def _gdrs_contractor_fact_fig_and_metrics(pdf: pd.DataFrame):
        """Круговая: доля факта по подрядчикам (кусочки = факт), сводка — как у план/факт."""
        d = _gdrs_plan_fact_data_slice(pdf)
        if d is None or d.empty:
            return None, None
        if "Контрагент" not in d.columns or "week_sum" not in d.columns:
            return None, None
        d = d.copy()
        d["_f"] = pd.to_numeric(d["week_sum"], errors="coerce").fillna(0)
        d["_p"] = (
            pd.to_numeric(d["План_numeric"], errors="coerce").fillna(0)
            if "План_numeric" in d.columns
            else 0.0
        )
        by_c = d.groupby("Контрагент", as_index=False)["_f"].sum()
        by_c = by_c[by_c["_f"] > 0].sort_values("_f", ascending=False)
        if by_c.empty or float(by_c["_f"].sum()) <= 0:
            return None, None
        plan_by = d.groupby("Контрагент", as_index=False)["_p"].sum()
        pie_df = by_c.merge(plan_by, on="Контрагент", how="left").fillna({"_p": 0.0})
        pie_df = pie_df.rename(columns={"_f": "Факт", "_p": "План"})
        pie_df["Отклонение"] = pie_df["Факт"] - pie_df["План"]

        labels = pie_df["Контрагент"].astype(str).tolist()
        values = pie_df["Факт"].astype(float).tolist()
        colors = (px.colors.qualitative.Set3 or [])[:]

        fig_cf = go.Figure(
            data=[
                go.Pie(
                    labels=labels,
                    values=values,
                    sort=False,
                    direction="clockwise",
                    textinfo="percent",
                    texttemplate="%{percent:.0%}",
                    textposition="inside",
                    hoverinfo="skip",
                    showlegend=False,
                    marker=dict(line=dict(color="rgba(255,255,255,0.45)", width=1)),
                )
            ]
        )

        # Внешние выноски: план/факт/откл (без %), рядом с сектором; без легенды и hover.
        try:
            total = float(sum(values)) if values else 0.0
            if total > 0:
                cum = 0.0
                anns = []
                cx, cy = 0.5, 0.52
                r = 0.46
                r_txt = 0.78
                for i, (lab, val) in enumerate(zip(labels, values)):
                    frac = float(val) / total if total else 0.0
                    mid = cum + frac / 2.0
                    cum += frac
                    ang = (0.25 - mid) * 2.0 * np.pi  # старт сверху
                    x_txt = cx + r_txt * np.cos(ang)
                    y_txt = cy + r_txt * np.sin(ang)
                    x_anch = "left" if np.cos(ang) >= 0 else "right"
                    plan_v = float(pie_df.iloc[i]["План"])
                    fact_v = float(pie_df.iloc[i]["Факт"])
                    dev_v = float(pie_df.iloc[i]["Отклонение"])
                    txt = (
                        f"{html_module.escape(str(lab))}<br>"
                        f"План: {int(np.ceil(plan_v))}<br>"
                        f"Факт: {int(np.ceil(fact_v))}<br>"
                        f"Откл.: {int(np.ceil(dev_v)) if dev_v >= 0 else -int(np.ceil(abs(dev_v)))}"
                    )
                    anns.append(
                        dict(
                            xref="paper",
                            yref="paper",
                            x=float(x_txt),
                            y=float(y_txt),
                            text=txt,
                            showarrow=False,
                            align="left",
                            xanchor=x_anch,
                            font=dict(size=11, color="#f5f5f5"),
                        )
                    )
                fig_cf.update_layout(annotations=anns)
        except Exception:
            pass

        fig_cf.update_layout(
            height=560,
            margin=dict(l=24, r=24, t=24, b=24),
            uniformtext=dict(minsize=9, mode="hide"),
        )
        fig_cf = apply_chart_background(fig_cf, skip_uniformtext=True)

        plan_sum = float(pd.to_numeric(d["План_numeric"], errors="coerce").fillna(0).sum()) if "План_numeric" in d.columns else 0.0
        fact_sum = float(by_c["_f"].sum())
        dev = fact_sum - plan_sum
        fp_pct = (fact_sum / plan_sum * 100.0) if plan_sum else None
        return fig_cf, {"plan": plan_sum, "fact": fact_sum, "dev": dev, "fp_pct": fp_pct}

    show_plan_fact_row = (
        has_plan_data
        and len(projects_to_process) > 1
        and project_col
        and project_col in filtered_df.columns
    )
    plan_fact_row_done = False
    if show_plan_fact_row:
        if (data_source_filter or "").strip().lower() == "техника":
            st.subheader("План/факт техника")
        else:
            st.subheader("План/факт рабочие")
        pf_cols = st.columns(len(projects_to_process))
        for _ix, _pname in enumerate(projects_to_process):
            _pdf = filtered_df.copy()
            if project_col in _pdf.columns and _pname != "Все проекты":
                _pdf = _pdf[
                    _pdf[project_col].astype(str).str.strip() == str(_pname).strip()
                ]
            fig_pf, met_pf = _gdrs_plan_fact_fig_and_metrics(_pdf)
            with pf_cols[_ix]:
                st.markdown(f"##### {_pname}")
                if fig_pf is not None and met_pf is not None:
                    a1, a2 = st.columns([3, 2])
                    with a1:
                        render_chart(
                            fig_pf,
                            key=f"{key_prefix}_planfact_row_{_ix}",
                            caption_below="",
                        )
                    with a2:
                        _col = "#e74c3c" if met_pf["dev"] > 0 else "#27ae60"
                        st.markdown(
                            f"**План:** {int(round(met_pf['plan']))}\n\n"
                            f"**Факт:** {int(round(met_pf['fact']))}\n\n"
                            f"**Отклонение:** <span style='color:{_col};font-size:1.15em'>●</span> "
                            f"{int(round(met_pf['dev']))}",
                            unsafe_allow_html=True,
                        )
                else:
                    st.markdown("*Нет данных для плана/факта по этому проекту.*")
        plan_fact_row_done = True
        st.markdown("---")

    show_contractor_fact_row = (
        len(projects_to_process) > 1
        and project_col
        and project_col in filtered_df.columns
        and "Контрагент" in filtered_df.columns
        and "week_sum" in filtered_df.columns
    )
    def _gdrs_fp_pct_caption_line(met: dict) -> str:
        """Строка „факт/план“; если плана нет или 0 — без деления на ноль."""
        return ""

    contractor_fact_row_done = False
    if show_contractor_fact_row:
        if (data_source_filter or "").strip().lower() == "техника":
            st.subheader("Доля факта по подрядчикам (техника)")
        else:
            st.subheader("Доля факта по подрядчикам (рабочие)")
        for _ix, _pname in enumerate(projects_to_process):
            _pdf = filtered_df.copy()
            if project_col in _pdf.columns and _pname != "Все проекты":
                _pdf = _pdf[
                    _pdf[project_col].astype(str).str.strip() == str(_pname).strip()
                ]
            fig_cf, met_cf = _gdrs_contractor_fact_fig_and_metrics(_pdf)
            st.markdown(f"#### {_pname}")
            if fig_cf is not None and met_cf is not None:
                render_chart(
                    fig_cf,
                    key=f"{key_prefix}_contractor_fact_row_{_ix}",
                    height=540,
                    max_height=720,
                    caption_below="",
                )
                _cfc = "#e74c3c" if met_cf["dev"] > 0 else "#27ae60"
                _pl = float(met_cf.get("plan") or 0)
                _pl_disp = "—" if _pl == 0.0 else str(int(round(_pl)))
                st.markdown(
                    f"**План:** {_pl_disp}  **Факт:** {int(round(met_cf['fact']))}  "
                    f"**Отклонение:** <span style='color:{_cfc};font-size:1.1em'>●</span> "
                    f"{int(round(met_cf['dev']))}  "
                    + _gdrs_fp_pct_caption_line(met_cf),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown("*Нет данных по факту подрядчиков по этому проекту.*")
            if _ix < len(projects_to_process) - 1:
                st.markdown("---")
        contractor_fact_row_done = True
        st.markdown("---")

    for project_name in projects_to_process:
        project_filtered_df = filtered_df.copy()
        if (
            project_col
            and project_col in project_filtered_df.columns
            and project_name != "Все проекты"
        ):
            project_filtered_df = project_filtered_df[
                project_filtered_df[project_col].astype(str).str.strip()
                == str(project_name).strip()
            ]

        if project_filtered_df.empty:
            continue

        if len(projects_to_process) > 1:
            st.markdown("---")
            st.subheader(f"Проект: {project_name}")

        _pslug = str(project_name).replace(" ", "_")[:20]

        if not has_plan_data and "Контрагент" in project_filtered_df.columns and "week_sum" in project_filtered_df.columns:
            _bar_avg = (
                project_filtered_df.groupby("Контрагент", as_index=False)["week_sum"]
                .sum()
                .rename(columns={"week_sum": "Среднее за месяц"})
            )
            _bar_avg["Среднее за месяц"] = _bar_avg["Среднее за месяц"].round(1)
            _bar_avg = _bar_avg[_bar_avg["Среднее за месяц"] > 0].sort_values("Среднее за месяц", ascending=False)
            if not _bar_avg.empty:
                fig_avg = px.bar(
                    _bar_avg, x="Контрагент", y="Среднее за месяц",
                    text=_bar_avg["Среднее за месяц"].apply(lambda v: f"{v:.0f}"),
                    color_discrete_sequence=["#2ecc71"],
                )
                fig_avg.update_traces(
                    textposition="outside",
                    textfont=dict(size=12, color="white"),
                    cliponaxis=False,
                )
                fig_avg.update_layout(
                    height=520,
                    xaxis=dict(tickangle=-45, automargin=True),
                    yaxis=dict(title="Среднее за месяц", automargin=True),
                )
                fig_avg = _apply_finance_bar_label_layout(fig_avg)
                try:
                    fig_avg.update_layout(
                        uniformtext=dict(minsize=6, mode="show"),
                        margin=dict(l=56, r=36, t=88, b=168),
                    )
                except Exception:
                    pass
                fig_avg = apply_chart_background(fig_avg)
                render_chart(fig_avg, key=f"{key_prefix}_avg_bar_{_pslug}", caption_below=f"Среднее количество ресурсов — {project_name}")

                total_avg = _bar_avg["Среднее за месяц"].sum()
                if total_avg > 0:
                    fig_pie_avg = px.pie(
                        _bar_avg, values="Среднее за месяц", names="Контрагент",
                        title=None, color_discrete_sequence=px.colors.qualitative.Set3,
                    )
                    fig_pie_avg.update_traces(
                        textinfo="text",
                        texttemplate="%{label}<br>%{value:,.0f} (%{percent:.0%})",
                        textposition="inside",
                        textfont_size=11,
                        insidetextorientation="horizontal",
                        hovertemplate="<b>%{label}</b><br>%{value:,.0f} (%{percent:.0%})<extra></extra>",
                    )
                    fig_pie_avg.update_layout(
                        height=500, showlegend=True,
                        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.05, font=dict(size=10)),
                        uniformtext=dict(minsize=8, mode="hide"),
                    )
                    fig_pie_avg = apply_chart_background(fig_pie_avg)
                    render_chart(fig_pie_avg, key=f"{key_prefix}_avg_pie_{_pslug}", caption_below=f"Распределение ресурсов — {project_name}")
            else:
                st.info("Нет данных для отображения.")
            continue

        if not plan_fact_row_done:
            df_people = project_filtered_df.copy()
            if "data_source" in df_people.columns:
                df_people = df_people[
                    df_people["data_source"].astype(str).str.strip().str.lower() == "ресурсы"
                ].copy()
            if not df_people.empty and "План_numeric" in df_people.columns and "week_sum" in df_people.columns:
                fig_pf, met_pf = _gdrs_plan_fact_fig_and_metrics(df_people)
                if fig_pf is not None and met_pf is not None:
                    st.subheader("План/факт рабочие")
                    render_chart(fig_pf, key=f"{key_prefix}_planfact_single_{_pslug}", caption_below="")

        # ========== Chart 1: круговая — доля факта по подрядчикам ==========
        if not contractor_fact_row_done:
            if (data_source_filter or "").strip().lower() == "техника":
                st.subheader("Доля факта по подрядчикам (техника)")
            else:
                st.subheader("Доля факта по подрядчикам (рабочие)")
            fig_cf, met_cf = _gdrs_contractor_fact_fig_and_metrics(project_filtered_df)
            if fig_cf is not None and met_cf is not None:
                cf_c1, cf_c2 = st.columns([3, 2])
                with cf_c1:
                    render_chart(
                        fig_cf,
                        key=f"{key_prefix}_contractor_fact_{_pslug}",
                        caption_below=f"Доля факта по подрядчикам — {project_name}",
                    )
                with cf_c2:
                    _cfc = "#e74c3c" if met_cf["dev"] > 0 else "#27ae60"
                    _pl = float(met_cf.get("plan") or 0)
                    _pl_disp = "—" if _pl == 0.0 else str(int(round(_pl)))
                    st.markdown(
                        f"**План:** {_pl_disp}\n\n"
                        f"**Факт:** {int(round(met_cf['fact']))}\n\n"
                        f"**Отклонение:** <span style='color:{_cfc};font-size:1.15em'>●</span> "
                        f"{int(round(met_cf['dev']))}",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("Нет данных для отображения круговой диаграммы по подрядчикам.")
        # ========== Таблица по подрядчикам: план, факт, отклонение ==========
        if "data_source" in project_filtered_df.columns and "Контрагент" in project_filtered_df.columns and "week_sum" in project_filtered_df.columns:
            for _type, type_label, type_key in [
                ("ресурсы", "Люди", "people"),
                ("техника", "Техника", "technique"),
            ]:
                df_type = project_filtered_df[
                    project_filtered_df["data_source"].astype(str).str.strip().str.lower() == _type
                ]
                if df_type.empty:
                    continue
                _agg = {"week_sum": "sum"}
                if "План_numeric" in df_type.columns:
                    _agg["План_numeric"] = "sum"
                by_contractor = df_type.groupby("Контрагент", as_index=False).agg(_agg)
                by_contractor = by_contractor.rename(
                    columns={"week_sum": "Факт", "План_numeric": "План"}
                )
                if "План" not in by_contractor.columns:
                    by_contractor["План"] = 0.0
                by_contractor["Факт"] = pd.to_numeric(
                    by_contractor["Факт"], errors="coerce"
                ).fillna(0.0)
                by_contractor["План"] = pd.to_numeric(
                    by_contractor["План"], errors="coerce"
                ).fillna(0.0)
                by_contractor["Отклонение"] = by_contractor["План"] - by_contractor["Факт"]
                by_contractor = by_contractor[
                    (by_contractor["Факт"] != 0) | (by_contractor["План"] != 0)
                ].copy()
                if by_contractor.empty:
                    continue
                by_contractor = by_contractor.sort_values("План", ascending=False)
                with st.expander(f"Формулы столбцов ({type_label})", expanded=False):
                    st.caption(
                        "План и факт — суммы по подрядчику; отклонение = план − факт."
                    )
                display_df = by_contractor[
                    ["Контрагент", "План", "Факт", "Отклонение"]
                ].copy()
                display_df["План"] = display_df["План"].apply(
                    lambda x: int(round(x, 0)) if pd.notna(x) else 0
                )
                display_df["Факт"] = display_df["Факт"].apply(
                    lambda x: int(round(x, 0)) if pd.notna(x) else 0
                )
                display_df["Отклонение"] = display_df["Отклонение"].apply(
                    lambda x: int(round(x, 0)) if pd.notna(x) else 0
                )
                st.markdown(
                    budget_table_to_html(
                        display_df,
                        finance_deviation_column="Отклонение",
                        deviation_red_if_positive_only=True,
                    ),
                    unsafe_allow_html=True,
                )

        # ========== Chart 2: Bar Chart by Contractor (Plan, Average, Отклонение) ==========
        st.subheader(
            "Столбчатая диаграмма: План, Среднее за месяц, Отклонение (группировка по контрагенту; сортировка по убыванию Плана)"
        )

        bar_df = project_filtered_df.copy()
        if period_col and period_col in bar_df.columns and selected_periods:
            bar_df = bar_df[
                bar_df[period_col].astype(str).str.strip().isin([str(p).strip() for p in selected_periods])
            ]
        if "Дельта_numeric" not in bar_df.columns and "План_numeric" in bar_df.columns and "week_sum" in bar_df.columns:
            bar_df = bar_df.copy()
            bar_df["Дельта_numeric"] = bar_df["week_sum"] - bar_df["План_numeric"]
        elif "Дельта_numeric" not in bar_df.columns:
            bar_df = bar_df.copy()
            bar_df["Дельта_numeric"] = 0
        contractor_data = (
            bar_df.groupby("Контрагент")
            .agg(
                {
                    "План_numeric": "sum",  # Sum of plans
                    "week_sum": "sum",  # Sum of weeks = среднее за месяц
                    "Дельта_numeric": "sum",  # Sum of deltas
                }
            )
            .reset_index()
        )

        contractor_data.columns = ["Контрагент", "План", "Среднее за месяц", "Отклонение"]

        # Ensure Отклонение column has numeric values
        contractor_data["Отклонение"] = pd.to_numeric(
            contractor_data["Отклонение"], errors="coerce"
        ).fillna(0)

        contractor_data = contractor_data.sort_values("План", ascending=False)

        plan_text = [
            f"{int(np.ceil(float(v)))}" if pd.notna(v) and float(v) > 0 else "0"
            for v in contractor_data["План"]
        ]
        fact_text = [
            f"{int(np.ceil(float(v)))}" if pd.notna(v) and float(v) > 0 else "0"
            for v in contractor_data["Среднее за месяц"]
        ]

        fig_bar = go.Figure()
        fig_bar.add_trace(
            go.Bar(
                name="План",
                x=contractor_data["Контрагент"],
                y=contractor_data["План"],
                marker_color="#3498db",
                text=plan_text,
                textposition="outside",
                textfont=dict(size=12, color="white"),
            )
        )
        fig_bar.add_trace(
            go.Bar(
                name="Среднее за месяц",
                x=contractor_data["Контрагент"],
                y=contractor_data["Среднее за месяц"],
                marker_color="#e67e22",
                text=fact_text,
                textposition="outside",
                textfont=dict(size=12, color="white"),
            )
        )

        delta_values = contractor_data["Отклонение"].fillna(0)
        delta_abs = delta_values.abs()
        delta_text = [
            f"{int(np.ceil(abs(float(d))))}" if abs(float(d)) >= 0.5 else "0"
            for d in delta_values
        ]
        positive_mask = delta_values > 0
        if positive_mask.any():
            fig_bar.add_trace(
                go.Bar(
                    name="Отклонение (+)",
                    x=contractor_data.loc[positive_mask, "Контрагент"],
                    y=delta_abs[positive_mask],
                    marker_color="#2ecc71",
                    text=[delta_text[i] for i in range(len(delta_text)) if positive_mask.iloc[i]],
                    textposition="outside",
                    textfont=dict(size=12, color="white"),
                    showlegend=False,
                )
            )
        negative_mask = delta_values < 0
        if negative_mask.any():
            fig_bar.add_trace(
                go.Bar(
                    name="Отклонение (-)",
                    x=contractor_data.loc[negative_mask, "Контрагент"],
                    y=delta_abs[negative_mask],
                    marker_color="#e74c3c",
                    text=[delta_text[i] for i in range(len(delta_text)) if negative_mask.iloc[i]],
                    textposition="outside",
                    textfont=dict(size=12, color="white"),
                    showlegend=True,
                )
            )
        zero_mask = delta_values == 0
        if zero_mask.any():
            fig_bar.add_trace(
                go.Bar(
                    name="Отклонение (0)",
                    x=contractor_data.loc[zero_mask, "Контрагент"],
                    y=delta_abs[zero_mask],
                    marker_color="#95a5a6",
                    text=[delta_text[i] for i in range(len(delta_text)) if zero_mask.iloc[i]],
                    textposition="outside",
                    textfont=dict(size=12, color="white"),
                    showlegend=False,
                )
            )

        period_caption = f" Период: {', '.join(str(p) for p in selected_periods[:5])}{'…' if len(selected_periods) > 5 else ''}" if (period_col and selected_periods) else ""
        fig_bar.update_layout(
            title_text="",
            xaxis_title="Контрагент",
            yaxis_title="Значение",
            barmode="group",
            height=620,
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.01,
                font=dict(size=11, color="#e8eef5"),
            ),
            xaxis=dict(tickangle=-45, automargin=True),
            yaxis=dict(automargin=True),
        )

        fig_bar = _apply_finance_bar_label_layout(fig_bar)
        try:
            fig_bar.update_layout(
                uniformtext=dict(minsize=6, mode="show"),
                margin=dict(l=56, r=150, t=100, b=168),
            )
            fig_bar.update_traces(cliponaxis=False, selector=dict(type="bar"))
        except Exception:
            pass
        fig_bar = apply_chart_background(fig_bar)
        render_chart(
            fig_bar,
            caption_below="План, Среднее за месяц и Отклонение по контрагентам" + period_caption,
        )

        # Макет: круговые по подрядчикам — выше; отдельный блок «СКУД по неделям» здесь не показываем.

        # Group by Контрагент and aggregate for pie chart (Plan + Average)
        contractor_plan_avg = (
            project_filtered_df.groupby("Контрагент")
            .agg(
                {
                    "План_numeric": "sum",  # Sum of plans
                    "week_sum": "sum",  # Sum of weeks = среднее за месяц
                    "Дельта_numeric": "sum",  # Sum of deltas
                }
            )
            .reset_index()
        )

        contractor_plan_avg.columns = ["Контрагент", "План", "Среднее за месяц", "Отклонение"]

        # Calculate sum of Plan + Average for each contractor
        contractor_plan_avg["Сумма"] = (
            contractor_plan_avg["План"] + contractor_plan_avg["Среднее за месяц"]
        )

        # Calculate доля факта (Среднее за месяц / Сумма * 100) and доля отклонения (Отклонение / План * 100)
        contractor_plan_avg["Доля факта (%)"] = 0.0
        contractor_plan_avg["Доля отклонения (%)"] = 0.0
        mask_sum = contractor_plan_avg["Сумма"] != 0
        contractor_plan_avg.loc[mask_sum, "Доля факта (%)"] = (
            contractor_plan_avg.loc[mask_sum, "Среднее за месяц"]
            / contractor_plan_avg.loc[mask_sum, "Сумма"]
        ) * 100
        mask_plan = contractor_plan_avg["План"] != 0
        contractor_plan_avg.loc[mask_plan, "Доля отклонения (%)"] = (
            contractor_plan_avg.loc[mask_plan, "Отклонение"]
            / contractor_plan_avg.loc[mask_plan, "План"]
        ) * 100

        # Remove zero values for pie chart
        contractor_plan_avg = contractor_plan_avg[contractor_plan_avg["Сумма"] != 0].copy()

        if contractor_plan_avg.empty:
            st.info("Нет данных для отображения.")
        else:
            contractor_plan_avg.sort_values("Сумма", ascending=False, inplace=True)
            # Круговая «план + среднее по контрагентам» скрыта по макету — используйте сводную таблицу ниже.

            # ========== Summary Table ==========
            st.subheader("Сводная таблица по контрагентам")

            # Format numbers for display
            summary_table = contractor_data.copy()
            summary_table["План"] = summary_table["План"].apply(
                lambda x: f"{int(x)}" if pd.notna(x) else "0"
            )
            summary_table["Среднее за месяц"] = summary_table["Среднее за месяц"].apply(
                lambda x: f"{int(x)}" if pd.notna(x) else "0"
            )
            summary_table["Отклонение"] = summary_table["Отклонение"].apply(
                lambda x: f"{int(x)}" if pd.notna(x) else "0"
            )

            st.markdown(
                budget_table_to_html(summary_table, finance_deviation_column="Отклонение"),
                unsafe_allow_html=True,
            )

            # Summary metrics
            col1, col2, col3 = st.columns(3)

            with col1:
                total_plan = contractor_data["План"].sum()
                st.metric("Общий план", f"{int(total_plan)}")

            with col2:
                total_average = contractor_data["Среднее за месяц"].sum()
                st.metric("Общее среднее за месяц", f"{int(total_average)}")

            with col3:
                total_delta = contractor_data["Отклонение"].sum()
                st.metric("Общее отклонение", f"{int(total_delta)}")


# ==================== DASHBOARD 8.6: SKUD Stroyka ====================
def dashboard_skud_stroyka(df):
    st.subheader("СКУД по неделям")

    resources_df = st.session_state.get("resources_data", None)
    if resources_df is None or resources_df.empty:
        st.warning(
            "Для раздела «СКУД по неделям» необходимо загрузить файл с данными о ресурсах."
        )
        st.info(
            "Ожидаемые колонки в файле: Проект, Контрагент, Период, Среднее за неделю или Среднее за месяц"
        )
        return

    work_df = resources_df.copy()

    # Helper function to find columns by partial match
    def find_column_by_partial(df, possible_names):
        """Find column by possible names (exact or partial match)"""
        for col in df.columns:
            col_lower = str(col).lower().strip()
            for name in possible_names:
                name_lower = str(name).lower().strip()
                if (
                    name_lower == col_lower
                    or name_lower in col_lower
                    or col_lower in name_lower
                ):
                    return col
        return None

    # Find required columns
    project_col = find_column_by_partial(
        work_df, ["Проект", "проект", "project", "Project"]
    )
    contractor_col = find_column_by_partial(
        work_df,
        ["Контрагент", "контрагент", "Подразделение", "подразделение", "contractor"],
    )
    period_col = find_column_by_partial(
        work_df, ["Период", "период", "period", "Period", "Месяц", "месяц"]
    )

    # Find average column (Среднее за неделю or Среднее за месяц)
    avg_col = None
    avg_col = None
    avg_candidates = [
        "среднее значение количество ресурсов в день за месяц",
        "Среднее за неделю",
        "Среднее за месяц",
    ]
    for cand in avg_candidates:
        if cand in work_df.columns:
            avg_col = cand
            break
    if not avg_col:
        for c in work_df.columns:
            cl = str(c).lower()
            if "среднее" in cl and "за месяц" in cl:
                avg_col = c
                break
    if not avg_col:
        for c in reversed(list(work_df.columns)):
            cl = str(c).lower()
            if "среднее" in cl:
                test = pd.to_numeric(work_df[c], errors="coerce")
                if test.notna().any():
                    avg_col = c
                    break

    if not avg_col:
        date_cols = [c for c in work_df.columns if _gdrs_header_is_dd_mm_yyyy(c)]
        if date_cols:
            for dc in date_cols:
                work_df[dc] = pd.to_numeric(work_df[dc], errors="coerce")
            work_df["Среднее_расчёт"] = work_df[date_cols].mean(axis=1)
            avg_col = "Среднее_расчёт"

    if not avg_col:
        st.error(
            "Не найдена колонка со средним значением (Среднее за неделю или Среднее за месяц)"
        )
        return

    cleaned = (
        work_df[avg_col]
        .astype(str)
        .str.replace(",", ".", regex=False)
        .str.replace(r"\s+", "", regex=True)
        .str.replace("\u00a0", "", regex=False)
        .str.replace("−", "-", regex=False)
        .str.strip()
    )
    work_df["Среднее_numeric"] = pd.to_numeric(cleaned, errors="coerce")

    if work_df["Среднее_numeric"].isna().all():
        st.warning("Все значения в колонке со средним значением не удалось преобразовать в числа.")
        st.info(
            f"Примеры значений из колонки '{avg_col}': {work_df[avg_col].head(10).tolist()}"
        )
        return

    # Fill NaN with 0 only for display purposes, but keep track of valid data
    work_df["Среднее_numeric"] = work_df["Среднее_numeric"].fillna(0)

    # Process period column - try to convert to datetime/period
    if period_col and period_col in work_df.columns:
        work_df["period_parsed"] = pd.to_datetime(
            work_df[period_col], errors="coerce", dayfirst=True
        )
        mask = work_df["period_parsed"].isna()
        if mask.any():
            def extract_period(val):
                if pd.isna(val):
                    return None
                val_str = str(val)
                try:
                    if "-" in val_str:
                        parts = val_str.split("-")
                        if len(parts) >= 2:
                            year = int(parts[0])
                            month = int(parts[1])
                            return pd.Period(f"{year}-{month:02d}", freq="M")
                    if "." in val_str:
                        parts = val_str.split(".")
                        if len(parts) >= 2:
                            if len(parts) == 3:
                                year = int(parts[2])
                                month = int(parts[1])
                            else:
                                year = int(parts[1])
                                month = int(parts[0])
                            return pd.Period(f"{year}-{month:02d}", freq="M")
                except Exception:
                    pass
                return None

            parsed_values = work_df.loc[mask, period_col].apply(extract_period)
            if parsed_values.notna().any():
                try:
                    work_df["period_parsed"] = work_df["period_parsed"].astype(object)
                    work_df.loc[mask, "period_parsed"] = parsed_values
                except TypeError:
                    work_df["period_parsed"] = work_df["period_parsed"].astype(object)
                    work_df.loc[mask, "period_parsed"] = parsed_values

        work_df["period_month"] = work_df["period_parsed"].apply(
            lambda x: (
                x.to_period("M")
                if pd.notna(x) and isinstance(x, pd.Timestamp)
                else (x if isinstance(x, pd.Period) else None)
            )
        )
    else:
        work_df["period_month"] = None

    # Filters
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        # Grouping filter
        grouping_options = [
            "По проектам",
            "По контрагентам",
            "По проектам и контрагентам",
            "Без группировки",
        ]
        selected_grouping = st.selectbox(
            "Группировка", grouping_options, key="skud_grouping"
        )

    with col2:
        # Фильтр по периоду от
        if period_col and "period_month" in work_df.columns and work_df["period_month"].notna().any():
            available_months = sorted(
                work_df[work_df["period_month"].notna()]["period_month"].unique()
            )
            month_options = ["Все"] + [format_period_ru(m) for m in available_months]
            selected_period_from = st.selectbox(
                "Период от", month_options, key="skud_period_from"
            )
        else:
            selected_period_from = st.selectbox(
                "Период от", ["Все"], key="skud_period_from"
            )

    with col3:
        # Фильтр по периоду до
        if period_col and "period_month" in work_df.columns and work_df["period_month"].notna().any():
            available_months = sorted(
                work_df[work_df["period_month"].notna()]["period_month"].unique()
            )
            month_options = ["Все"] + [format_period_ru(m) for m in available_months]
            selected_period_to = st.selectbox(
                "Период до", month_options, key="skud_period_to"
            )
        else:
            selected_period_to = st.selectbox(
                "Период до", ["Все"], key="skud_period_to"
            )

    with col4:
        # Project filter
        if project_col and project_col in work_df.columns:
            projects = ["Все"] + sorted(work_df[project_col].dropna().unique().tolist())
            selected_project = st.selectbox(
                "Фильтр по проекту", projects, key="skud_project"
            )
        else:
            selected_project = st.selectbox(
                "Фильтр по проекту", ["Все"], key="skud_project"
            )

    with col5:
        # Contractor filter
        if contractor_col and contractor_col in work_df.columns:
            contractors = ["Все"] + sorted(
                work_df[contractor_col].dropna().unique().tolist()
            )
            selected_contractor = st.selectbox(
                "Фильтр по контрагенту", contractors, key="skud_contractor"
            )
        else:
            selected_contractor = st.selectbox(
                "Фильтр по контрагенту", ["Все"], key="skud_contractor"
            )

    # Apply filters
    filtered_df = work_df.copy()

    if selected_project != "Все" and project_col and project_col in filtered_df.columns:
        # More robust filtering - handle NaN values and case-insensitive comparison
        project_mask = (
            filtered_df[project_col].astype(str).str.strip().str.lower()
            == str(selected_project).strip().lower()
        )
        filtered_df = filtered_df[project_mask]

    if (
        selected_contractor != "Все"
        and contractor_col
        and contractor_col in filtered_df.columns
    ):
        # More robust filtering - handle NaN values and case-insensitive comparison
        contractor_mask = (
            filtered_df[contractor_col].astype(str).str.strip().str.lower()
            == str(selected_contractor).strip().lower()
        )
        filtered_df = filtered_df[contractor_mask]

    # Apply period filters (подписи в selectbox — «месяц год» из format_period_ru, не ISO)
    if (
        "period_month" in filtered_df.columns
        and filtered_df["period_month"].notna().any()
    ):
        _avail_pm = sorted(
            work_df[work_df["period_month"].notna()]["period_month"].unique()
        )
        _pm_by_label = {format_period_ru(m): m for m in _avail_pm}
        if selected_period_from != "Все":
            period_from = _pm_by_label.get(selected_period_from)
            if period_from is not None:
                filtered_df = filtered_df[filtered_df["period_month"] >= period_from]
        if selected_period_to != "Все":
            period_to = _pm_by_label.get(selected_period_to)
            if period_to is not None:
                filtered_df = filtered_df[filtered_df["period_month"] <= period_to]

    if filtered_df.empty:
        st.warning("⚠️ Нет данных для отображения с выбранными фильтрами.")
        return

    # Group data based on selected grouping
    group_cols = []
    if (
        selected_grouping == "По проектам"
        and project_col
        and project_col in filtered_df.columns
    ):
        group_cols.append(project_col)
    elif (
        selected_grouping == "По контрагентам"
        and contractor_col
        and contractor_col in filtered_df.columns
    ):
        group_cols.append(contractor_col)
    elif selected_grouping == "По проектам и контрагентам":
        if project_col and project_col in filtered_df.columns:
            group_cols.append(project_col)
        if contractor_col and contractor_col in filtered_df.columns:
            group_cols.append(contractor_col)

    # Always group by period_month for time series (only if not filtering by specific period range)
    # Only add period_month if it has valid (non-NaN) values
    if (
        (selected_period_from == "Все" and selected_period_to == "Все")
        and "period_month" in filtered_df.columns
        and filtered_df["period_month"].notna().any()
    ):
        group_cols.append("period_month")

    if group_cols:
        # Filter out rows where any grouping column is NaN before grouping
        mask = pd.Series([True] * len(filtered_df))
        for col in group_cols:
            if col in filtered_df.columns:
                mask = mask & filtered_df[col].notna()

        if mask.any():
            grouped_data = (
                filtered_df[mask]
                .groupby(group_cols)["Среднее_numeric"]
                .mean()
                .reset_index()
            )
            grouped_data.columns = list(group_cols) + ["Среднее за месяц"]
        else:
            # All grouping columns are NaN, aggregate without grouping
            grouped_data = pd.DataFrame(
                {"Среднее за месяц": [filtered_df["Среднее_numeric"].mean()]}
            )
    else:
        # No grouping, just aggregate by period if available
        if (
            "period_month" in filtered_df.columns
            and filtered_df["period_month"].notna().any()
        ):
            grouped_data = (
                filtered_df.groupby("period_month")["Среднее_numeric"]
                .mean()
                .reset_index()
            )
            grouped_data.columns = ["period_month", "Среднее за месяц"]
        else:
            # No period available, just aggregate all data
            mean_value = filtered_df["Среднее_numeric"].mean()
            if pd.isna(mean_value):
                mean_value = 0
            grouped_data = pd.DataFrame({"Среднее за месяц": [mean_value]})

    if "Среднее за месяц" in grouped_data.columns:
        grouped_data["Среднее за месяц"] = pd.to_numeric(
            grouped_data["Среднее за месяц"], errors="coerce"
        ).round(0)

    if "period_month" in grouped_data.columns:
        grouped_data["Период"] = grouped_data["period_month"].apply(
            format_period_ru
        )

    # Check if we have data to display
    if grouped_data.empty:
        st.warning("⚠️ Нет данных для отображения после применения фильтров.")
        with st.expander("🔍 Детали проблемы", expanded=True):
            st.write(f"**Исходных строк:** {len(work_df)}")
            st.write(f"**Строк после фильтрации:** {len(filtered_df)}")
            st.write(f"**Строк после группировки:** {len(grouped_data)}")
            st.write(f"**Выбранная группировка:** {selected_grouping}")
            st.write(f"**Колонки для группировки:** {group_cols}")
            st.write(f"**Выбранный проект:** {selected_project}")
            st.write(f"**Выбранный контрагент:** {selected_contractor}")
            st.write(f"**Период от:** {selected_period_from}")
            st.write(f"**Период до:** {selected_period_to}")
            if len(filtered_df) > 0:
                st.write("**Данные после фильтрации (первые 10 строк):**")
                st.table(style_dataframe_for_dark_theme(filtered_df.head(10)))
                if "Среднее_numeric" in filtered_df.columns:
                    st.write(f"**Среднее_numeric в отфильтрованных данных:**")
                    st.write(
                        f"- Не пустых значений: {filtered_df['Среднее_numeric'].notna().sum()}"
                    )
                    st.write(
                        f"- Среднее значение: {filtered_df['Среднее_numeric'].mean():.2f}"
                    )
                    st.write(f"- Сумма: {filtered_df['Среднее_numeric'].sum():.2f}")
            else:
                st.write(
                    "**Проблема:** После применения фильтров не осталось ни одной строки."
                )
                st.write("**Возможные причины:**")
                st.write("- Фильтры слишком строгие")
                st.write("- Данные не соответствуют выбранным фильтрам")
                st.write("- Проблемы с типами данных при сравнении")
        return

    # Check if all values are NaN (but allow zeros - zeros are valid data)
    if "Среднее за месяц" in grouped_data.columns:
        if grouped_data["Среднее за месяц"].isna().all():
            st.warning("⚠️ Все значения среднего равны NaN после группировки.")
            with st.expander("🔍 Детали проблемы", expanded=True):
                st.write(f"**Строк после группировки:** {len(grouped_data)}")
                st.table(style_dataframe_for_dark_theme(grouped_data))
            return

    # Create visualization
    has_period = (
        "period_month" in grouped_data.columns
        or "Период" in grouped_data.columns
    )

    if selected_grouping == "Без группировки":
        if has_period:
            # Simple line chart with time series
            x_col = (
                "Период"
                if "Период" in grouped_data.columns
                else "period_month"
            )
            fig = px.line(
                grouped_data,
                x=x_col,
                y="Среднее за месяц",
                text="Среднее за месяц",
                title=None,
                labels={x_col: "Месяц", "Среднее за месяц": "Среднее за месяц (чел.)"},
                markers=True,
            )
            fig.update_traces(textposition="top center", textfont_size=10)
            fig.update_xaxes(tickangle=-45)
            fig = apply_chart_background(fig)
            render_chart(fig, caption_below="Среднее за месяц по людям в динамике")
        else:
            # Single value bar chart
            fig = px.bar(
                grouped_data,
                y="Среднее за месяц",
                title=None,
                labels={"Среднее за месяц": "Среднее за месяц (чел.)"},
                text="Среднее за месяц",
            )
            fig.update_traces(
                textposition="outside", textfont=dict(size=12, color="white")
            )
            fig = _apply_finance_bar_label_layout(fig)
            fig = apply_chart_background(fig)
            render_chart(fig, caption_below="Среднее за месяц по людям")
    else:
        # Grouped visualization
        grouping_cols = [col for col in group_cols if col != "period_month"]

        if has_period and len(grouping_cols) > 0:
            # Grouped bar chart with time series
            x_col = (
                "Период"
                if "Период" in grouped_data.columns
                else "period_month"
            )
            color_col = grouping_cols[0] if len(grouping_cols) == 1 else None

            if color_col:
                fig = px.bar(
                    grouped_data,
                    x=x_col,
                    y="Среднее за месяц",
                    color=color_col,
                    title=None,
                    labels={
                        x_col: "Месяц",
                        "Среднее за месяц": "Среднее за месяц (чел.)",
                    },
                    text="Среднее за месяц",
                )
                fig.update_layout(barmode="group")
                fig.update_xaxes(tickangle=-45)
                fig.update_traces(
                    textposition="outside", textfont=dict(size=12, color="white")
                )
                fig = _apply_finance_bar_label_layout(fig)
                fig = apply_chart_background(fig)
                render_chart(fig, caption_below="Среднее за месяц по людям в динамике")
            elif len(grouping_cols) > 1:
                # Multiple grouping columns - use first for color, show others in hover
                fig = px.bar(
                    grouped_data,
                    x=x_col,
                    y="Среднее за месяц",
                    color=grouping_cols[0],
                    title=None,
                    labels={
                        x_col: "Месяц",
                        "Среднее за месяц": "Среднее за месяц (чел.)",
                    },
                    text="Среднее за месяц",
                    facet_col=grouping_cols[1] if len(grouping_cols) > 1 else None,
                )
                fig.update_layout(barmode="group")
                fig.update_xaxes(tickangle=-45)
                fig.update_traces(
                    textposition="outside", textfont=dict(size=12, color="white")
                )
                fig = _apply_finance_bar_label_layout(fig)
                fig = apply_chart_background(fig)
                render_chart(fig, caption_below="Среднее за месяц по людям в динамике")
            else:
                # Fallback to line chart
                fig = px.line(
                    grouped_data,
                    x=x_col,
                    y="Среднее за месяц",
                    title=None,
                    labels={
                        x_col: "Месяц",
                        "Среднее за месяц": "Среднее за месяц (чел.)",
                    },
                    markers=True,
                )
                fig.update_xaxes(tickangle=-45)
                fig = apply_chart_background(fig)
                render_chart(fig, caption_below="Среднее за месяц по людям в динамике")
        elif len(grouping_cols) > 0:
            # Grouped bar chart without time series (single month selected)
            color_col = grouping_cols[0] if len(grouping_cols) == 1 else None
            if color_col:
                fig = px.bar(
                    grouped_data,
                    x=color_col,
                    y="Среднее за месяц",
                    title=None,
                    labels={"Среднее за месяц": "Среднее за месяц (чел.)"},
                    text="Среднее за месяц",
                )
                fig.update_traces(
                    textposition="outside", textfont=dict(size=12, color="white")
                )
                fig.update_xaxes(tickangle=-45)
                fig = _apply_finance_bar_label_layout(fig)
                fig = apply_chart_background(fig)
                render_chart(fig, caption_below="Среднее за месяц по людям")
            else:
                st.info("Не удалось построить график с выбранной группировкой.")
        else:
            st.info("Не удалось построить график с выбранной группировкой.")

    # Summary table
    if not grouped_data.empty:
        st.subheader("Сводная таблица")
        display_cols = []

        # Add period column only if not filtering by specific period range
        if (selected_period_from == "Все" and selected_period_to == "Все") and (
            "Период" in grouped_data.columns
            or "period_month" in grouped_data.columns
        ):
            display_cols.append(
                "Период"
                if "Период" in grouped_data.columns
                else "period_month"
            )

        # Add grouping columns
        if selected_grouping != "Без группировки":
            for col in group_cols:
                if col != "period_month" and col in grouped_data.columns:
                    display_cols.append(col)

        display_cols.append("Среднее за месяц")

        # Filter to only existing columns
        display_cols = [col for col in display_cols if col in grouped_data.columns]

        summary_table = grouped_data[display_cols].copy()
        summary_table["Среднее за месяц"] = summary_table["Среднее за месяц"].apply(
            lambda x: f"{int(round(float(x)))}" if pd.notna(x) else "0"
        )
        st.table(style_dataframe_for_dark_theme(summary_table))


# ==================== DASHBOARD: график рабочей силы (вкладки) ====================
def dashboard_technique_tabs(df):
    """
    ГДРС: только рабочая сила (без техники и без отдельного отчёта «СКУД по неделям» в меню).
    """
    st.header("График движения рабочей силы")
    dashboard_workforce_movement(
        df, data_source_filter="Ресурсы", show_header=False, key_prefix="gdrs_people"
    )
# ==================== DASHBOARD: Дебиторская и кредиторская задолженность подрядчиков ====================
def _find_col(df, names):
    """Поиск колонки по частичному совпадению (без учёта регистра)."""
    cols_lower = [str(c).lower().strip() for c in df.columns]
    for n in names:
        n_lower = n.lower().strip()
        for i, c in enumerate(cols_lower):
            if n_lower in c or c in n_lower:
                return df.columns[i]
    return None


def _to_num(series):
    """Приведение к числу (пробелы, запятая как десятичный разделитель)."""
    return pd.to_numeric(
        series.astype(str).str.replace(" ", "").str.replace(",", "."),
        errors="coerce",
    ).fillna(0)


def _ref_score_contractor_column(name: str) -> int:
    """Выбор колонки с наименованием контрагента в справочнике 1С (не ИНН/КПП)."""
    n = str(name).lower().replace("_", " ").strip()
    if "инн" in n or "кпп" in n:
        return -100
    if "наименование" not in n and n.startswith("id"):
        return -90
    sc = 0
    if "наименование" in n and "контрагент" in n:
        sc += 60
    if n in ("контрагент", "контрагенты", "название контрагента", "название контрагента"):
        sc += 55
    if "контрагент" in n and "договор" not in n:
        sc += 25
    if "организация" in n:
        sc += 10
    return sc


def _ref_score_project_column(name: str) -> int:
    n = str(name).lower().replace("_", " ").strip()
    sc = 0
    if "номенклатур" in n:
        sc -= 30
    if n == "проект":
        sc += 80
    if "проект" in n and "проектн" not in n:
        sc += 40
    if "id" in n and "проект" in n:
        sc += 15
    return sc


def _ref_pick_best_column(df: pd.DataFrame, scorer) -> str | None:
    best_c = None
    best_s = -10**9
    for c in df.columns:
        s = scorer(str(c))
        if s > best_s:
            best_s = s
            best_c = c
    return best_c if best_s > 0 else None


def dashboard_debit_credit(df):
    """Дебиторская и кредиторская задолженность подрядчиков: график и таблица по данным из файла."""
    st.header("Дебиторская и кредиторская задолженность подрядчиков")

    data = st.session_state.get("debit_credit_data", None)
    if (data is None or data.empty) and (df is not None and not df.empty):
        data = df
    if data is None or data.empty:
        st.warning(
            "Для отчёта загрузите файл с данными по дебиторской/кредиторской задолженности. "
            "Ожидаемые колонки: подрядчик (название организации), тип подрядчика, договор, сумма в договоре, выплачено, аванс, остаток на конец периода."
        )
        return

    work = data.copy()
    work.columns = [str(c).strip() for c in work.columns]

    contractor_col = _find_col(work, ["Название контрагента", "Название организации", "подрядчик", "Подрядчик", "contractor", "Организация"])
    project_col = _find_col(
        work,
        [
            "project name",
            "Проект",
            "проект",
            "ID проекта",
            "id проекта",
            "Project",
            "название проекта",
            "код проекта",
        ],
    )
    project_from_reference = False
    if (not project_col or project_col not in work.columns) and contractor_col:
        keymap_from_ref = {}
        ref_df = st.session_state.get("reference_contractors")
        if ref_df is not None and not getattr(ref_df, "empty", True):
            ref_df = ref_df.copy()
            ref_df.columns = [str(c).strip() for c in ref_df.columns]
            rc = _ref_pick_best_column(ref_df, _ref_score_contractor_column) or _find_col(
                ref_df,
                [
                    "Наименование_Контрагента",
                    "Наименование Контрагента",
                    "Подрядчик",
                    "Контрагент",
                    "контрагент",
                    "организация",
                    "партнёр",
                    "Partner",
                    "Название контрагента",
                    "Название организации",
                    "Наименование контрагента",
                    "Наименование",
                    "полное наименование",
                    "Контрагент (полное наименование)",
                    "Наименование для печати",
                    "name",
                ],
            )
            rp = _ref_pick_best_column(ref_df, _ref_score_project_column) or _find_col(
                ref_df,
                [
                    "Проект",
                    "project name",
                    "ID проекта",
                    "проект",
                    "название проекта",
                    "код проекта",
                    "проект (id)",
                    "идентификатор проекта",
                ],
            )
            if rc and rp and rc in ref_df.columns and rp in ref_df.columns:
                for _, rr in ref_df.iterrows():
                    k = norm_partner_join_key(rr.get(rc, ""))
                    if k:
                        keymap_from_ref[k] = str(rr.get(rp, "")).strip()

        pmap = st.session_state.get("reference_partner_to_project") or {}
        merged = dict(pmap)
        merged.update(keymap_from_ref)

        if merged:
            work["_project_mapped"] = work[contractor_col].map(
                lambda x: merged.get(norm_partner_join_key(x), "")
            )
            project_col = "_project_mapped"
            project_from_reference = True
    type_col = _find_col(work, ["Тип подрядчика", "тип подрядчика", "contractor type"])
    contract_col = _find_col(work, ["Номер договора", "Договор", "договор", "contract"])
    total_col = _find_col(work, ["Сумма в договоре", "сумма в договоре", "Общая сумма", "contract sum"])
    paid_col = _find_col(work, ["Выплачено", "выплачено", "Выплаченная сумма", "ВсегоОплат", "paid"])
    advance_col = _find_col(work, ["Аванс", "аванс", "Авансированная сумма", "ВсегоОплат_Аванс", "advance"])
    balance_col = _find_col(work, ["Остаток на конец периода", "Остаток на период", "ОстатокНаКонецПериода", "остаток", "balance"])

    if not contract_col:
        st.error("Не найдена колонка «Договор». Проверьте заголовки файла.")
        st.info("Доступные колонки: " + ", ".join(work.columns))
        return
    for label, col in [("Выплачено", paid_col), ("Аванс", advance_col), ("Остаток", balance_col)]:
        if not col:
            st.warning(f"Колонка «{label}» не найдена — соответствующие данные не отобразятся.")

    # Числовые колонки
    for c in [total_col, paid_col, advance_col, balance_col]:
        if c:
            work[f"_num_{c}"] = _to_num(work[c])

    st.subheader("Фильтры")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if contractor_col and contractor_col in work.columns:
            all_contractors = ["Все"] + sorted(work[contractor_col].dropna().astype(str).unique().tolist())
            sel_contractor = st.selectbox("Подрядчик", all_contractors, key="debit_credit_contractor")
        else:
            sel_contractor = "Все"
    with c2:
        if type_col and type_col in work.columns:
            all_types = ["Все"] + sorted(work[type_col].dropna().astype(str).unique().tolist())
            sel_type = st.selectbox("Тип подрядчика", all_types, key="debit_credit_type")
        else:
            sel_type = "Все"
    with c3:
        if contract_col:
            all_contracts = ["Все"] + sorted(work[contract_col].dropna().astype(str).unique().tolist())
            sel_contract = st.selectbox("Договор", all_contracts, key="debit_credit_contract")
        else:
            sel_contract = "Все"
    with c4:
        if project_col and project_col in work.columns:
            all_projects = ["Все"] + _unique_project_labels_for_select(work[project_col])
            sel_project = st.selectbox("Проект", all_projects, key="debit_credit_project")
        else:
            st.info("Фильтр по проекту недоступен: в файле нет колонки проекта.")
            sel_project = "Все"

    filtered = work.copy()
    if sel_contractor != "Все" and contractor_col:
        filtered = filtered[filtered[contractor_col].astype(str).str.strip() == str(sel_contractor).strip()]
    if sel_type != "Все" and type_col:
        filtered = filtered[filtered[type_col].astype(str).str.strip() == str(sel_type).strip()]
    if sel_contract != "Все" and contract_col:
        filtered = filtered[filtered[contract_col].astype(str).str.strip() == str(sel_contract).strip()]
    if sel_project != "Все" and project_col:
        filtered = filtered[
            filtered[project_col].map(_project_filter_norm_key)
            == _project_filter_norm_key(sel_project)
        ]

    if filtered.empty:
        st.info("Нет данных при выбранных фильтрах.")
        return

    def _trunc_label(val, max_len: int = 34) -> str:
        s = str(val).strip()
        if len(s) <= max_len:
            return s
        return s[: max_len - 1] + "…"

    chart_group_col = contractor_col if contractor_col else contract_col
    chart_label = "Подрядчик" if contractor_col else "Договор"
    # По ТЗ: на графике должен быть виден проект; при наличии маппинга из справочников — ось X: «Проект | Подрядчик»
    if (
        project_col
        and project_col in filtered.columns
        and contractor_col
        and contractor_col in filtered.columns
    ):
        _fc = filtered.copy()
        _fc["_chart_x"] = (
            _fc[project_col].astype(str).str.strip()
            + " | "
            + _fc[contractor_col].astype(str).str.strip()
        )
        filtered = _fc
        chart_group_col = "_chart_x"
        chart_label = "Проект | Подрядчик"
    if not contractor_col and chart_group_col != "_chart_x":
        st.warning("Колонка подрядчика не найдена — диаграмма сгруппирована по договору.")

    built = {}
    if total_col and f"_num_{total_col}" in filtered.columns:
        built["Сумма в договоре"] = filtered.groupby(chart_group_col)[f"_num_{total_col}"].sum()
    if paid_col and f"_num_{paid_col}" in filtered.columns:
        built["Выплачено"] = filtered.groupby(chart_group_col)[f"_num_{paid_col}"].sum()
    if advance_col and f"_num_{advance_col}" in filtered.columns:
        built["Аванс"] = filtered.groupby(chart_group_col)[f"_num_{advance_col}"].sum()
    if balance_col and f"_num_{balance_col}" in filtered.columns:
        built["Остаток на период"] = filtered.groupby(chart_group_col)[f"_num_{balance_col}"].sum()

    if not built:
        st.warning("Нет числовых колонок для отображения (сумма в договоре, выплачено, аванс, остаток).")
        return

    chart_df = pd.DataFrame(built).reset_index()
    chart_df = chart_df.rename(columns={chart_group_col: chart_label})

    st.subheader("Столбчатая диаграмма по подрядчикам" if contractor_col else "Столбчатая диаграмма по договорам")
    value_cols = [c for c in chart_df.columns if c != chart_label]
    if not value_cols:
        st.info("Нет данных для графика.")
    else:
        fig = go.Figure()
        x = chart_df[chart_label].astype(str).map(_trunc_label)
        colors = {"Сумма в договоре": "#2E86AB", "Выплачено": "#27ae60", "Аванс": "#F39C12", "Остаток на период": "#e74c3c"}
        for col in value_cols:
            fig.add_trace(
                go.Bar(
                    name=col,
                    x=x,
                    y=chart_df[col],
                    marker_color=colors.get(col, None),
                text=chart_df[col].apply(lambda v: f"{v:,.0f}".replace(",", " ") if pd.notna(v) else ""),
                    textposition="outside",
                    textfont=dict(size=10, color="#f0f4f8"),
                )
            )
        fig.update_layout(
            barmode="group",
            height=min(900, max(420, len(chart_df) * 28)),
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02,
            ),
            xaxis=dict(tickangle=-55, tickfont=dict(size=9), categoryorder="total descending"),
            margin=dict(r=230, b=140),
        )
        fig = _apply_finance_bar_label_layout(fig)
        fig = apply_chart_background(fig)
        if chart_label == "Проект | Подрядчик":
            cap = "Суммы по проекту и подрядчику (проект из файла или справочника)"
        else:
            cap = "Суммы по подрядчику" if contractor_col else "Суммы по договору"
        render_chart(fig, caption_below=cap)

    st.subheader("Таблица по подрядчику и договору" if contractor_col else "Таблица по договорам")
    table_group_cols = [contract_col]
    if contractor_col:
        table_group_cols = [contractor_col, contract_col]
    if contractor_col and project_col and project_col in filtered.columns:
        table_group_cols = [project_col, contractor_col, contract_col]
    tbl_built = {}
    if total_col and f"_num_{total_col}" in filtered.columns:
        tbl_built["Сумма в договоре"] = filtered.groupby(table_group_cols)[f"_num_{total_col}"].sum()
    if paid_col and f"_num_{paid_col}" in filtered.columns:
        tbl_built["Выплачено"] = filtered.groupby(table_group_cols)[f"_num_{paid_col}"].sum()
    if advance_col and f"_num_{advance_col}" in filtered.columns:
        tbl_built["Аванс"] = filtered.groupby(table_group_cols)[f"_num_{advance_col}"].sum()
    if balance_col and f"_num_{balance_col}" in filtered.columns:
        tbl_built["Остаток на период"] = filtered.groupby(table_group_cols)[f"_num_{balance_col}"].sum()
    if not tbl_built:
        st.warning("Нет числовых колонок для таблицы.")
        return
    table_df = pd.DataFrame(tbl_built).reset_index()
    rename_map = {}
    if project_col and project_col in table_df.columns:
        rename_map[project_col] = "Проект"
    if contractor_col and contractor_col in table_df.columns:
        rename_map[contractor_col] = "Подрядчик"
    if contract_col and contract_col in table_df.columns:
        rename_map[contract_col] = "Договор"
    if rename_map:
        table_df = table_df.rename(columns=rename_map)
    elif contract_col and contract_col in table_df.columns:
        table_df = table_df.rename(columns={contract_col: "Договор"})
    group_dim_cols = [c for c in ("Проект", "Подрядчик", "Договор") if c in table_df.columns]
    value_cols_t = [c for c in table_df.columns if c not in group_dim_cols]
    total_row = {"Договор": "Итого"}
    if "Проект" in table_df.columns:
        total_row["Проект"] = ""
    if "Подрядчик" in table_df.columns:
        total_row["Подрядчик"] = ""
    for col in value_cols_t:
        total_row[col] = table_df[col].sum()
    table_df = pd.concat([table_df, pd.DataFrame([total_row])], ignore_index=True)
    display_df = table_df.copy()
    for col in value_cols_t:
        display_df[col] = display_df[col].apply(
            lambda x: f"{float(x):,.0f}".replace(",", " ") if pd.notna(x) else "—"
        )
    st.caption(f"Записей: {len(display_df)}")
    _render_html_table(display_df)
    render_dataframe_excel_csv_downloads(
        display_df,
        file_stem="debit_credit",
        key_prefix="debit_credit",
    )


# ── TESSA: поиск колонок и дат (Исполнительная документация / Предписания) ──
def _tessa_find_column(df, candidates):
    """Возвращает имя колонки из df по списку возможных имён (точное и частичное совпадение)."""
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


def _tessa_cell_has_value(v) -> bool:
    if v is None:
        return False
    if isinstance(v, float) and pd.isna(v):
        return False
    s = str(v).strip().lower()
    return s not in ("", "nan", "none", "nat")


def _tessa_norm_join_key(val) -> str:
    """Единый ключ для DocID / CardId: 83, 83.0, «83» → «83»."""
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


def _tessa_row_join_key(row, doc_col, card_col) -> str:
    if doc_col and doc_col in row.index and _tessa_cell_has_value(row[doc_col]):
        return _tessa_norm_join_key(row[doc_col])
    if card_col and card_col in row.index and _tessa_cell_has_value(row[card_col]):
        return _tessa_norm_join_key(row[card_col])
    return ""


def _tessa_to_datetime(series):
    """Парсинг дат из TESSA (dd.mm.yyyy и пр.)."""
    if series is None:
        return pd.Series(dtype="datetime64[ns]")
    return pd.to_datetime(series, errors="coerce", dayfirst=True)


def _krstate_bucket(raw) -> str:
    """Сопоставление с KrStates_Doc_* из PDF (если в данных англ. идентификаторы)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "other"
    s = str(raw).strip()
    sl = s.lower()
    if "declined" in sl or "отказ" in sl:
        return "declined"
    if "active" in sl or "doc_active" in sl:
        return "active"
    if "signed" in sl:
        return "signed"
    return "other"


# ── Исполнительная документация: детальная таблица (тёмная тема, как остальной дашборд) ──
_EXEC_DOC_DETAIL_CSS = """
<style>
.exec-doc-panel {
  background:linear-gradient(180deg, rgba(12,24,38,0.96), rgba(16,37,58,0.94));
  border:1px solid rgba(101,163,255,0.16);
  border-radius:16px;
  padding:16px 18px;
  margin:0.75rem 0 1rem;
  box-shadow:0 10px 24px rgba(0,0,0,0.18);
}
.exec-doc-caption {
  color:#9fb3c8; font-size:13px; margin-top:10px; line-height:1.45;
}
.exec-doc-table-wrap { overflow-x:auto; margin:0.75rem 0 0.5rem; border-radius:14px; border:1px solid rgba(82,104,130,0.45); }
.exec-doc-table { width:100%; border-collapse:collapse; font-size:14px; font-family:Inter,system-ui,sans-serif; }
.exec-doc-table th {
  text-align:left; padding:12px 14px; background:#16283a; color:#f8fbff;
  border-bottom:1px solid rgba(138,160,184,0.28); font-size:11px; font-weight:700;
  text-transform:uppercase; letter-spacing:0.05em; white-space:nowrap;
}
.exec-doc-table td {
  padding:10px 14px; border-bottom:1px solid rgba(82,104,130,0.28); color:#e8eef5;
  vertical-align:middle; max-width:340px;
}
.exec-doc-table tr:nth-child(even) td { background:rgba(255,255,255,0.025); }
.exec-doc-table tr:hover td { background:rgba(48,72,99,0.72); }
.exec-doc-table th a { color:#f8fbff; text-decoration:none; display:inline-flex; gap:6px; align-items:center; }
.exec-doc-table th a:hover { color:#93c5fd; }
.exec-doc-th-sort { color:#8fb4da; font-size:10px; }
.exec-delay-val { color:#5eead4; font-weight:600; font-variant-numeric:tabular-nums; }
.exec-dash { color:#8892a0; }
.exec-pill { display:inline-block; padding:5px 12px; border-radius:999px; font-size:12px; font-weight:700; white-space:nowrap; }
.exec-pill-signed { background:rgba(34,197,94,0.20); color:#bbf7d0; border:1px solid rgba(34,197,94,0.52); }
.exec-pill-customer { background:rgba(251,191,36,0.17); color:#fde68a; border:1px solid rgba(251,191,36,0.42); }
.exec-pill-contractor { background:rgba(56,189,248,0.18); color:#bae6fd; border:1px solid rgba(56,189,248,0.46); }
.exec-pill-declined { background:rgba(239,68,68,0.16); color:#fecaca; border:1px solid rgba(239,68,68,0.48); }
.exec-pill-default { background:#262833; color:#e0e0e0; border:1px solid #444; }
.exec-pill-muted { color:#64748b; border:1px dashed #444; padding:3px 10px; border-radius:8px; font-size:12px; }
.exec-kpi-grid {
  display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  gap:12px; margin:0.5rem 0 1rem;
}
.exec-kpi-card {
  background:rgba(20,35,52,0.92); border:1px solid rgba(104,128,157,0.24);
  border-radius:14px; padding:14px 16px;
}
.exec-kpi-card.exec-kpi-alert { border-color:rgba(239,68,68,0.35); }
.exec-kpi-card.exec-kpi-warn { border-color:rgba(245,158,11,0.35); }
.exec-kpi-card.exec-kpi-ok { border-color:rgba(34,197,94,0.35); }
.exec-kpi-title { color:#8fa7bf; font-size:12px; margin-bottom:8px; }
.exec-kpi-value { color:#f8fbff; font-size:28px; font-weight:800; line-height:1.05; }
.exec-kpi-subtitle { color:#97a9bc; font-size:12px; margin-top:8px; line-height:1.4; }
.exec-kpi-delta-pos { color:#4ade80; font-size:12px; font-weight:700; margin-top:8px; }
.exec-kpi-delta-neg { color:#f87171; font-size:12px; font-weight:700; margin-top:8px; }
</style>
"""


def _exec_status_pill_html(status: str) -> str:
    """Бейджи статуса как на макете: Принят / У Заказчика / У Подрядчика / Отказ."""
    esc = html_module.escape
    s = str(status or "").strip()
    if not s:
        return f'<span class="exec-pill-muted">{esc("—")}</span>'
    sl = s.lower()
    if "на согласован" in sl or sl == "на согласовании":
        return f'<span class="exec-pill exec-pill-customer">{esc("У Заказчика")}</span>'
    if "доработ" in sl:
        return f'<span class="exec-pill exec-pill-contractor">{esc("У Подрядчика")}</span>'
    if "подписан" in sl or ("согласован" in sl and "на согласован" not in sl) or "утвержд" in sl:
        return f'<span class="exec-pill exec-pill-signed">{esc("Принят")}</span>'
    if "отказ" in sl or "declined" in sl:
        return f'<span class="exec-pill exec-pill-declined">{esc("Отказ")}</span>'
    if "заказчик" in sl and "подряд" not in sl:
        return f'<span class="exec-pill exec-pill-customer">{esc("У Заказчика")}</span>'
    if "подряд" in sl and "заказ" not in sl and ("сдач" in sl or "возврат" in sl or "исправ" in sl):
        return f'<span class="exec-pill exec-pill-contractor">{esc("У Подрядчика")}</span>'
    return f'<span class="exec-pill exec-pill-default">{esc(s)}</span>'


def _exec_delay_cell_html(val: str) -> str:
    """Просрочка: выделение цианом для значений вида «+2 дня», «5 дн.»."""
    esc = html_module.escape
    s = str(val or "").strip()
    if not s or s == "—":
        return f'<span class="exec-dash">{esc("—")}</span>'
    if re.search(r"^[\d\s\+\-]+.*дн", s, re.I):
        return f'<span class="exec-delay-val">{esc(s)}</span>'
    return esc(s)


def _exec_query_param_value(name: str, default: str = "") -> str:
    try:
        val = st.query_params.get(name, default)
    except Exception:
        return default
    if isinstance(val, list):
        return str(val[0]) if val else default
    return str(val)


def _exec_sort_link(column: str, current_sort: str, current_order: str) -> str:
    next_order = "desc" if current_sort == column and current_order == "asc" else "asc"
    params = {}
    try:
        params.update(st.query_params.to_dict())
    except Exception:
        pass
    params["exec_sort"] = column
    params["exec_order"] = next_order
    return "?" + urlencode(params, doseq=True)


def _exec_sort_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(range(len(df)), index=df.index)
    if column in {
        "Плановая дата сдачи",
        "Факт сдачи",
        "Дата передачи заказчику",
        "Дата согласования",
        "Дата создания",
    }:
        return pd.to_datetime(df[column], errors="coerce", dayfirst=True)
    if column in {"Просрочка сдачи", "Просрочка соглас."}:
        return (
            df[column]
            .astype(str)
            .str.extract(r"(-?\d+)", expand=False)
            .pipe(pd.to_numeric, errors="coerce")
        )
    return df[column].astype(str).str.casefold()


def _exec_sort_table_df(df: pd.DataFrame, sort_col: str, sort_order: str) -> pd.DataFrame:
    if df is None or df.empty or sort_col not in df.columns:
        return df
    work = df.copy()
    work["_exec_sort_key"] = _exec_sort_series(work, sort_col)
    ascending = str(sort_order).lower() != "desc"
    work = work.sort_values(
        by=["_exec_sort_key", sort_col],
        ascending=[ascending, ascending],
        na_position="last",
        kind="mergesort",
    )
    return work.drop(columns=["_exec_sort_key"], errors="ignore")


def _exec_metric_cards_html(cards: list[dict], *, caption: str | None = None) -> str:
    esc = html_module.escape
    parts = ['<div class="exec-kpi-grid">']
    for card in cards:
        tone = str(card.get("tone") or "").strip()
        title = esc(str(card.get("title", "")))
        value = esc(str(card.get("value", "—")))
        subtitle = esc(str(card.get("subtitle", "")).strip())
        delta = str(card.get("delta") or "").strip()
        delta_cls = ""
        if delta:
            delta_cls = "exec-kpi-delta-pos" if not delta.startswith("-") else "exec-kpi-delta-neg"
        parts.append(f'<div class="exec-kpi-card {"exec-kpi-" + tone if tone else ""}">')
        parts.append(f'<div class="exec-kpi-title">{title}</div>')
        parts.append(f'<div class="exec-kpi-value">{value}</div>')
        if delta:
            parts.append(f'<div class="{delta_cls}">{esc(delta)}</div>')
        if subtitle:
            parts.append(f'<div class="exec-kpi-subtitle">{subtitle}</div>')
        parts.append("</div>")
    parts.append("</div>")
    if caption:
        parts.append(f'<div class="exec-doc-caption">{esc(caption)}</div>')
    return "".join(parts)


def _exec_detail_table_html(
    df: pd.DataFrame,
    max_rows: int = 500,
    *,
    sort_col: str = "",
    sort_order: str = "asc",
) -> str:
    """HTML-таблица детального отчёта ИД: CAPS-заголовки, циан для просрочек, пилюли статусов."""
    esc = html_module.escape
    if df is None or df.empty:
        return f'<p style="color:#8892a0;padding:12px;">{esc("Нет строк для отображения.")}</p>'
    show = df.head(max_rows)
    cols = list(show.columns)
    head_parts = ["<thead><tr>"]
    for c in cols:
        marker = "↕"
        if sort_col == c:
            marker = "↑" if str(sort_order).lower() == "asc" else "↓"
        link = _exec_sort_link(c, sort_col, sort_order)
        head_parts.append(
            f'<th><a href="{esc(link, quote=True)}">{esc(c)} <span class="exec-doc-th-sort">{esc(marker)}</span></a></th>'
        )
    head_parts.append("</tr></thead>")
    thead = "".join(head_parts)
    delay_cols = {"Просрочка сдачи", "Просрочка соглас."}
    status_col = "Статус"
    body_parts = ["<tbody>"]
    for _, row in show.iterrows():
        body_parts.append("<tr>")
        for c in cols:
            v = row.get(c, "")
            if pd.isna(v):
                v = ""
            raw = str(v) if v is not None else ""
            if c == status_col:
                inner = _exec_status_pill_html(raw)
            elif c in delay_cols:
                inner = _exec_delay_cell_html(raw)
            else:
                inner = esc(raw)
            body_parts.append(f"<td>{inner}</td>")
        body_parts.append("</tr>")
    body_parts.append("</tbody>")
    return (
        '<div class="exec-doc-table-wrap"><table class="exec-doc-table">'
        + thead
        + "".join(body_parts)
        + "</table></div>"
    )


# ==================== DASHBOARD: Исполнительная документация (отдельный отчёт в группе «Прочее») ====================
def dashboard_executive_documentation(df):
    """
    Отчёт «Исполнительная документация» — TESSA.
    Исключаются строки KindName «Предписание» (отдельный отчёт «Предписания»).
    """
    st.header("Исполнительная документация")
    with st.expander("О отчёте", expanded=False):
        st.caption("Контроль просрочек подрядчика и заказчика.")
        st.caption(
            "Сводка, детальная таблица и динамика по месяцам собраны в одном отчёте; переключение между разделами — вкладками ниже."
        )

    tessa_df = st.session_state.get("tessa_data", None)
    if tessa_df is None or tessa_df.empty:
        st.warning(
            "Для отчёта «Исполнительная документация» необходимы данные из TESSA. "
            "Загрузите файлы tessa_*.csv через папку web/."
        )
        return

    work = tessa_df.copy()
    work.columns = [str(c).strip() for c in work.columns]
    try:
        # Дополняем строки ИД данными карточки/задачи TESSA по ключам DocID/CardId.
        # Это выравнивает поля сроков, передачи заказчику и согласования с фактическими данными TESSA.
        work = _tessa_fill_card_from_doc_lookup(work)
    except Exception:
        pass

    kind_col = _tessa_find_column(work, ["KindName", "kindname", "Вид"])
    if kind_col:
        mask_pred = work[kind_col].astype(str).str.contains("Предписан", case=False, na=False)
        work = work[~mask_pred].reset_index(drop=True)

    obj_col = _tessa_find_column(work, ["ObjectName", "objectname", "Объект"])
    if obj_col:
        work = work[
            work[obj_col].notna()
            & (~work[obj_col].astype(str).str.strip().isin(["", "nan", "None", "NaN"]))
        ].reset_index(drop=True)

    if work.empty:
        st.info("Нет данных по исполнительной документации (после исключения предписаний и пустых объектов).")
        return

    krstates_df = st.session_state.get("reference_krstates", None)
    status_map = {}
    if krstates_df is not None and not krstates_df.empty:
        for _, row in krstates_df.iterrows():
            name = str(row.get("Название", "")).strip()
            ru = str(row.get("ru", "")).strip()
            if name and ru:
                status_map[name] = ru

    if "KrState" in work.columns:
        work["Статус"] = work["KrState"].apply(
            lambda x: status_map.get(str(x).strip(), str(x).strip()) if pd.notna(x) else "Неизвестно"
        )
    elif "KrStateID" in work.columns:
        work["Статус"] = work["KrStateID"].astype(str)
    else:
        work["Статус"] = "Неизвестно"

    _contr_candidates = ["CONTR", "Контрагент", "contr"]
    contr_col = _tessa_find_column(work, _contr_candidates)
    card_col = _tessa_find_column(work, ["CardId", "CardID", "cardId", "DocID", "DocId"])
    creation_col = _tessa_find_column(work, ["CreationDate", "creationdate", "Дата создания"])
    completed_col = _tessa_find_column(work, ["Completed", "completed", "CompletionDate", "Дата завершения"])
    plan_col = _tessa_find_column(work, ["PlanDate", "DueDate", "Срок", "Плановая дата"])
    transfer_col = _tessa_find_column(
        work,
        ["TransferToCustomer", "Дата передачи", "Передача заказчику", "DateToCustomer", "ПереданоЗаказчику"],
    )
    agree_col = _tessa_find_column(
        work,
        ["AgreementDate", "Дата согласования", "Согласовано", "ApprovalDate", "Дата подписания заказчиком"],
    )

    if creation_col:
        work["_cd"] = _tessa_to_datetime(work[creation_col])
    else:
        work["_cd"] = pd.NaT

    dmin = work["_cd"].min()
    dmax = work["_cd"].max()
    today = date.today()

    st.markdown("**Фильтры**")
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        if obj_col:
            objects = ["Все"] + sorted(work[obj_col].dropna().astype(str).str.strip().unique().tolist())
            sel_obj = st.selectbox("Объект", objects, key="exec_doc_object")
        else:
            sel_obj = "Все"
    with fc2:
        if contr_col:
            contrs = ["Все"] + sorted(work[contr_col].dropna().astype(str).str.strip().unique().tolist())
            sel_contr = st.selectbox("Контрагент", contrs, key="exec_doc_contr")
        else:
            sel_contr = "Все"
    with fc3:
        if kind_col:
            kinds = ["Все"] + sorted(work[kind_col].dropna().astype(str).str.strip().unique().tolist())
            sel_kind = st.selectbox("Вид документа", kinds, key="exec_doc_kind")
        else:
            sel_kind = "Все"

    fp1, fp2 = st.columns(2)
    with fp1:
        if pd.notna(dmin) and pd.notna(dmax):
            preset_options = [
                "Без пресета",
                "Прошлая неделя",
                "Прошлый месяц",
                "Последние 3 месяца",
                "Последние 6 месяцев",
                "Последний год",
                "Последние 2 года",
            ]
            selected_preset = st.selectbox(
                "Быстрый период",
                preset_options,
                index=0,
                key="exec_doc_period_preset",
            )
            preset_start = dmin.date() if hasattr(dmin, "date") else dmin
            preset_end = dmax.date() if hasattr(dmax, "date") else dmax
            today_ts = pd.Timestamp(today)
            if selected_preset == "Прошлая неделя":
                week_start = today_ts - pd.Timedelta(days=today_ts.weekday() + 7)
                week_end = week_start + pd.Timedelta(days=6)
                preset_start = week_start.date()
                preset_end = week_end.date()
            elif selected_preset == "Прошлый месяц":
                prev_month = (today_ts.to_period("M") - 1).to_timestamp()
                preset_start = prev_month.date()
                preset_end = (prev_month + pd.offsets.MonthEnd(0)).date()
            elif selected_preset == "Последние 3 месяца":
                preset_start = (today_ts - pd.DateOffset(months=3)).date()
                preset_end = today
            elif selected_preset == "Последние 6 месяцев":
                preset_start = (today_ts - pd.DateOffset(months=6)).date()
                preset_end = today
            elif selected_preset == "Последний год":
                preset_start = (today_ts - pd.DateOffset(years=1)).date()
                preset_end = today
            elif selected_preset == "Последние 2 года":
                preset_start = (today_ts - pd.DateOffset(years=2)).date()
                preset_end = today
            min_date = dmin.date() if hasattr(dmin, "date") else dmin
            max_date = dmax.date() if hasattr(dmax, "date") else dmax
            if preset_start < min_date:
                preset_start = min_date
            if preset_end > max_date:
                preset_end = max_date
            dr = st.date_input(
                "Период (по дате создания в TESSA)",
                value=(preset_start, preset_end),
                min_value=min_date,
                max_value=max_date,
                key="exec_doc_period",
                format="DD.MM.YYYY",
            )
            if isinstance(dr, tuple) and len(dr) == 2:
                p_start, p_end = dr
            else:
                p_start, p_end = dr, dr
        else:
            p_start = p_end = None
            with st.expander("Период по дате создания", expanded=False):
                st.caption("В данных нет распознанной колонки даты создания — период не применяется.")
    with fp2:
        hide_overdue_if_done = st.checkbox(
            "Не отображать просрочку, если ИД сдана (подписана/согласована)",
            value=True,
            key="exec_doc_hide_overdue_signed",
        )
        st.caption("Остальные дополнительные флаги из старого макета убраны.")

    with st.expander("Колонка контрагента в TESSA", expanded=False):
        if contr_col:
            st.caption(
                f"Для контрагента используется колонка «{contr_col}» "
                f"(поиск по точному или частичному совпадению с: {', '.join(_contr_candidates)})."
            )
        else:
            st.caption(
                "Колонка контрагента в данных TESSA не найдена — фильтр и столбчатые диаграммы по контрагентам недоступны "
                f"(ожидаются имена или вхождения подстрок из списка: {', '.join(_contr_candidates)})."
            )

    filtered_base = work.copy()
    if sel_obj != "Все" and obj_col:
        filtered_base = filtered_base[filtered_base[obj_col].astype(str).str.strip() == sel_obj]
    if sel_contr != "Все" and contr_col:
        filtered_base = filtered_base[filtered_base[contr_col].astype(str).str.strip() == sel_contr]
    if sel_kind != "Все" and kind_col:
        filtered_base = filtered_base[filtered_base[kind_col].astype(str).str.strip() == sel_kind]

    filtered = filtered_base.copy()
    if creation_col and p_start is not None and p_end is not None:
        ts_start = pd.Timestamp(p_start)
        ts_end = pd.Timestamp(p_end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        filtered = filtered[filtered["_cd"].notna() & (filtered["_cd"] >= ts_start) & (filtered["_cd"] <= ts_end)]

    if filtered.empty:
        st.info("Нет данных при выбранных фильтрах.")
        return

    st.markdown('<div class="exec-doc-panel">', unsafe_allow_html=True)

    stu = filtered["Статус"].astype(str)

    def _has_status(s, *parts):
        sl = s.lower()
        return any(p.lower() in sl for p in parts)

    is_signed = stu.map(lambda s: _has_status(s, "Подписан", "Согласован"))
    is_declined = stu.map(lambda s: _has_status(s, "Отказ"))
    sl = stu.str.lower()
    is_on_agree = (sl == "на согласовании") | sl.str.contains("на согласовании", na=False)
    is_rework = stu.map(lambda s: "доработ" in str(s).lower())

    if "KrState" in filtered.columns:
        kb = filtered["KrState"].map(_krstate_bucket)
        is_signed = is_signed | (kb == "signed")
        is_declined = is_declined | (kb == "declined")
        is_on_agree = is_on_agree | (kb == "active")

    overdue_mask = (~is_signed) & (~is_declined)
    cnt_c = int((overdue_mask & is_rework).sum())
    cnt_u = int((overdue_mask & is_on_agree).sum())
    total_overdue_two = cnt_c + cnt_u

    if card_col and card_col in filtered.columns:
        total_docs = filtered[card_col].nunique()
    else:
        total_docs = len(filtered)

    st.subheader("Накопительным итогом")
    summary_cards = [
        {"title": "Всего документов", "value": int(total_docs), "subtitle": "Уникальные документы в текущей выборке"},
        {"title": "Отказы", "value": int(is_declined.sum()), "subtitle": "Документы со статусом отказа", "tone": "alert"},
        {"title": "На согласовании", "value": int(is_on_agree.sum()), "subtitle": "Документы у заказчика", "tone": "warn"},
        {"title": "Принято", "value": int(is_signed.sum()), "subtitle": "Подписано / согласовано", "tone": "ok"},
        {"title": "У подрядчика", "value": int(is_rework.sum()), "subtitle": "Документы на доработке"},
        {"title": "Всего просрочек", "value": int(total_overdue_two), "subtitle": "Подрядчик + заказчик", "tone": "alert"},
    ]
    st.markdown(
        _exec_metric_cards_html(
            summary_cards,
            caption="Показатель «Всего просрочек» = просрочка подрядчика (доработка) + просрочка заказчика (на согласовании).",
        ),
        unsafe_allow_html=True,
    )

    def _exec_n_docs(dfp):
        if card_col and card_col in dfp.columns:
            return int(dfp[card_col].nunique())
        return int(len(dfp))

    def _exec_metrics_snapshot(dfp: pd.DataFrame) -> dict[str, int]:
        if dfp is None or dfp.empty:
            return {
                "Всего документов": 0,
                "Отказы": 0,
                "На согласовании": 0,
                "Принято": 0,
                "У подрядчика": 0,
                "Просрочка подрядчика": 0,
                "Просрочка заказчика": 0,
            }
        stu_loc = dfp["Статус"].astype(str)
        signed_loc = stu_loc.map(lambda s: _has_status(s, "Подписан", "Согласован"))
        declined_loc = stu_loc.map(lambda s: _has_status(s, "Отказ"))
        on_agree_loc = stu_loc.str.lower().str.contains("на согласовании", na=False)
        rework_loc = stu_loc.str.lower().str.contains("доработ", na=False)
        if "KrState" in dfp.columns:
            kb_loc = dfp["KrState"].map(_krstate_bucket)
            signed_loc = signed_loc | (kb_loc == "signed")
            declined_loc = declined_loc | (kb_loc == "declined")
            on_agree_loc = on_agree_loc | (kb_loc == "active")
        overdue_loc = (~signed_loc) & (~declined_loc)
        return {
            "Всего документов": _exec_n_docs(dfp),
            "Отказы": int(declined_loc.sum()),
            "На согласовании": int(on_agree_loc.sum()),
            "Принято": int(signed_loc.sum()),
            "У подрядчика": int(rework_loc.sum()),
            "Просрочка подрядчика": int((overdue_loc & rework_loc).sum()),
            "Просрочка заказчика": int((overdue_loc & on_agree_loc).sum()),
        }

    compare_panel_payload: tuple[str, str] | None = None
    if creation_col and filtered_base["_cd"].notna().any():
        cmp_source = filtered_base[filtered_base["_cd"].notna()].copy()
        cmp_source["_cmp_month"] = cmp_source["_cd"].dt.to_period("M")
        cmp_months = sorted(cmp_source["_cmp_month"].dropna().unique().tolist())
        if cmp_months:
            cmp_labels = {
                f"{RUSSIAN_MONTHS.get(m.month, str(m.month))} {m.year}": m for m in cmp_months
            }
            cmp_col1, cmp_col2 = st.columns([3, 1])
            with cmp_col1:
                st.subheader("Изменения за месяц к предыдущему")
            with cmp_col2:
                selected_cmp_label = st.selectbox(
                    "Выберите месяц",
                    list(cmp_labels.keys()),
                    index=len(cmp_labels) - 1,
                    key="exec_doc_compare_month",
                )
            selected_cmp_month = cmp_labels[selected_cmp_label]
            prev_cmp_month = selected_cmp_month - 1
            cur_cmp_df = cmp_source[cmp_source["_cmp_month"] == selected_cmp_month]
            prev_cmp_df = cmp_source[cmp_source["_cmp_month"] == prev_cmp_month]
            cur_metrics = _exec_metrics_snapshot(cur_cmp_df)
            prev_metrics = _exec_metrics_snapshot(prev_cmp_df)

            compare_cards = []
            tone_map = {
                "Отказы": "alert",
                "Просрочка подрядчика": "alert",
                "Просрочка заказчика": "warn",
                "Принято": "ok",
            }
            for title in (
                "Всего документов",
                "Отказы",
                "На согласовании",
                "Принято",
                "Просрочка подрядчика",
                "Просрочка заказчика",
            ):
                cur_val = int(cur_metrics.get(title, 0))
                prev_val = int(prev_metrics.get(title, 0))
                diff = cur_val - prev_val
                pct = None
                if prev_val != 0:
                    pct = diff / prev_val * 100.0
                delta_txt = f"{diff:+d}"
                if pct is not None:
                    delta_txt = f"{delta_txt} ({pct:+.1f}%)"
                compare_cards.append(
                    {
                        "title": title,
                        "value": cur_val,
                        "delta": delta_txt,
                        "subtitle": f"Было: {prev_val}",
                        "tone": tone_map.get(title, ""),
                    }
                )
            prev_cmp_label = (
                f"{RUSSIAN_MONTHS.get(prev_cmp_month.month, str(prev_cmp_month.month))} {prev_cmp_month.year}"
                if prev_cmp_month in cmp_months
                else "предыдущим месяцем"
            )
            compare_panel_payload = (
                f"Изменения за {selected_cmp_label} по сравнению с {prev_cmp_label}",
                _exec_metric_cards_html(
                    compare_cards,
                    caption=(
                        "Показывает абсолютное изменение и процент относительно предыдущего месяца "
                        "в текущей выборке по фильтрам."
                    ),
                ),
            )

    oc1, oc2 = st.columns(2)

    def _row_days_late_plan(r):
        if not plan_col:
            return np.nan
        pdt = _tessa_to_datetime(pd.Series([r.get(plan_col)])).iloc[0]
        if pd.isna(pdt):
            return np.nan
        pday = pdt.date() if hasattr(pdt, "date") else pdt
        if completed_col:
            fdt = _tessa_to_datetime(pd.Series([r.get(completed_col)])).iloc[0]
            if pd.notna(fdt):
                fday = fdt.date() if hasattr(fdt, "date") else fdt
                return max(0, (fday - pday).days)
        return max(0, (today - pday).days)

    with oc1:
        st.subheader("Просрочка подрядчика (сдача ИД)")
        st.metric("Документов на доработке у подрядчика", cnt_c)
        sub_c = filtered.loc[overdue_mask & is_rework].copy()
        if plan_col and not sub_c.empty:
            sub_c["_late_days"] = sub_c.apply(_row_days_late_plan, axis=1)
            b1 = int(((sub_c["_late_days"] >= 0) & (sub_c["_late_days"] <= 7)).sum())
            b2 = int(((sub_c["_late_days"] > 7) & (sub_c["_late_days"] <= 30)).sum())
            b3 = int((sub_c["_late_days"] > 30).sum())
            bc1, bc2, bc3 = st.columns(3)
            bc1.metric("До 7 дней", b1)
            bc2.metric("7–30 дней", b2)
            bc3.metric("> 30 дней", b3)
            with st.expander("Подсказка по сегментам (подрядчик)", expanded=False):
                if sub_c["_late_days"].notna().any():
                    st.caption(f"Средняя просрочка (дней): {sub_c['_late_days'].mean():.1f}")
                elif cnt_c > 0:
                    st.caption(
                        "Для сегментации 0–7 / 7–30 / >30 дней укажите в TESSA плановую дату "
                        "(PlanDate / DueDate / Срок)."
                    )
        elif cnt_c > 0:
            with st.expander("Подсказка по сегментам (подрядчик)", expanded=False):
                st.caption(
                    "Для сегментации 0–7 / 7–30 / >30 дней укажите в TESSA плановую дату "
                    "(PlanDate / DueDate / Срок)."
                )

        if contr_col and contr_col in filtered.columns and cnt_c > 0:
            sub = filtered[overdue_mask & is_rework]
            by_c = sub.groupby(contr_col).size().reset_index(name="Количество").sort_values("Количество", ascending=True)
            fig_c = px.bar(by_c, y=contr_col, x="Количество", orientation="h", text="Количество", color_discrete_sequence=["#f87171"])
            fig_c.update_traces(textposition="outside", textfont=dict(color="white"))
            fig_c = _apply_bar_uniformtext(fig_c)
            fig_c = apply_chart_background(fig_c)
            fig_c.update_layout(height=max(280, len(by_c) * 32 + 80), yaxis_title="", xaxis_title="")
            render_chart(fig_c, caption_below="Просрочка по подрядчикам (дней)", key="exec_overdue_contractor")
        st.caption("Блок показывает просрочку сдачи исполнительной документации со стороны подрядчика.")
    with oc2:
        st.subheader("Просрочка заказчика (согласование)")
        with st.expander("Пояснение по показателю", expanded=False):
            st.markdown(
                "Показатель «Просрочка согласования Заказчиком»: документы на согласовании у заказчика; "
                "сегменты по дням и диаграмма относятся к этапу согласования заказчиком "
                "(колонка «Просрочка соглас.» в детальном отчёте)."
            )
        st.metric("Документов на согласовании у заказчика", cnt_u)
        sub_u = filtered.loc[overdue_mask & is_on_agree].copy()
        if plan_col and not sub_u.empty:
            sub_u["_late_days"] = sub_u.apply(_row_days_late_plan, axis=1)
            u1, u2, u3 = st.columns(3)
            u1.metric("До 7 дней", int(((sub_u["_late_days"] >= 0) & (sub_u["_late_days"] <= 7)).sum()))
            u2.metric("7–30 дней", int(((sub_u["_late_days"] > 7) & (sub_u["_late_days"] <= 30)).sum()))
            u3.metric("> 30 дней", int((sub_u["_late_days"] > 30).sum()))
        elif cnt_u > 0:
            with st.expander("Подсказка по сегментам (заказчик)", expanded=False):
                st.caption("Для сегментации по дням укажите плановую дату в данных.")

        if contr_col and contr_col in filtered.columns and cnt_u > 0:
            sub = filtered[overdue_mask & is_on_agree]
            by_u = sub.groupby(contr_col).size().reset_index(name="Количество").sort_values("Количество", ascending=True)
            fig_u = px.bar(by_u, y=contr_col, x="Количество", orientation="h", text="Количество", color_discrete_sequence=["#fbbf24"])
            fig_u.update_traces(textposition="outside", textfont=dict(color="white"))
            fig_u = _apply_bar_uniformtext(fig_u)
            fig_u = apply_chart_background(fig_u)
            fig_u.update_layout(height=max(280, len(by_u) * 32 + 80), yaxis_title="", xaxis_title="")
            render_chart(
                fig_u,
                caption_below="Просрочка согласования заказчиком — количество документов на согласовании по контрагентам",
                key="exec_overdue_customer",
            )
        st.caption("Блок показывает документы, зависшие на согласовании у заказчика.")

    if compare_panel_payload is not None:
        compare_title, compare_html = compare_panel_payload
        st.subheader(compare_title)
        st.markdown(compare_html, unsafe_allow_html=True)

    tab_sum, tab_detail, tab_dyn = st.tabs(["Накопительным итогом", "Детальный отчёт", "Динамика по месяцам"])

    with tab_sum:
        st.subheader("Распределение по статусам")
        status_counts = filtered["Статус"].value_counts()
        status_df = status_counts.reset_index()
        status_df.columns = ["Статус", "Количество"]
        fig = px.bar(
            status_df, x="Статус", y="Количество",
            text="Количество",
            color_discrete_sequence=["#2E86AB"],
        )
        fig.update_traces(textposition="outside", textfont=dict(size=13, color="white"))
        fig.update_layout(xaxis_tickangle=-35)
        fig = _apply_finance_bar_label_layout(fig)
        fig = _apply_vertical_category_bar_width(fig)
        fig = apply_chart_background(fig)
        fig.update_layout(height=450, xaxis_title="Статус", yaxis_title="Количество")
        render_chart(fig, caption_below="Документы по статусам", key="exec_status_bar")

        if obj_col and obj_col in filtered.columns:
            st.subheader("Документы по объектам")
            obj_counts = filtered.groupby(obj_col).size().reset_index(name="Количество")
            obj_counts = obj_counts.sort_values("Количество", ascending=False)
            fig2 = px.bar(
                obj_counts, x=obj_col, y="Количество",
                text="Количество",
                color_discrete_sequence=["#06A77D"],
            )
            fig2.update_traces(textposition="outside", textfont=dict(size=13, color="white"))
            fig2 = _apply_finance_bar_label_layout(fig2)
            fig2 = _apply_vertical_category_bar_width(fig2)
            fig2 = apply_chart_background(fig2)
            fig2.update_layout(height=450, xaxis_title="Объект", yaxis_title="Количество", xaxis_tickangle=-45)
            render_chart(fig2, caption_below="Количество документов по объектам", key="exec_obj_bar")

        if creation_col and filtered["_cd"].notna().any():
            rmin = filtered["_cd"].min()
            rmax = filtered["_cd"].max()
            with st.expander("Диапазон дат создания в выборке", expanded=False):
                st.caption(
                    f"{rmin.strftime('%d.%m.%Y') if pd.notna(rmin) else '—'} — "
                    f"{rmax.strftime('%d.%m.%Y') if pd.notna(rmax) else '—'}"
                )

    with tab_detail:
        st.subheader("Детальный отчёт по сдаче и согласованию ИД")
        disp = filtered.loc[~is_signed].copy()
        rows_out = []
        for _, row in disp.iterrows():
            st_l = str(row.get("Статус", ""))
            signed_row = _has_status(st_l, "Подписан", "Согласован")
            hide_ov = hide_overdue_if_done and signed_row
            plan_d = row.get(plan_col) if plan_col else None
            fact_d = row.get(completed_col) if completed_col else None
            plan_dt = _tessa_to_datetime(pd.Series([plan_d])).iloc[0] if plan_col else pd.NaT
            fact_dt = _tessa_to_datetime(pd.Series([fact_d])).iloc[0] if completed_col else pd.NaT
            pr_sub = ""
            pr_cust = ""
            if not hide_ov and pd.notna(plan_dt):
                if pd.notna(fact_dt):
                    pr_sub = f"{max(0, (fact_dt.date() - plan_dt.date()).days)} дн."
                else:
                    pr_sub = f"{max(0, (today - plan_dt.date()).days)} дн." if hasattr(plan_dt, "date") else ""
            if hide_ov:
                pr_sub = "—"
                pr_cust = "—"
            tr = row.get(transfer_col) if transfer_col else None
            ag = row.get(agree_col) if agree_col else None
            t1 = _tessa_to_datetime(pd.Series([tr])).iloc[0] if transfer_col else pd.NaT
            t2 = _tessa_to_datetime(pd.Series([ag])).iloc[0] if agree_col else pd.NaT
            if not hide_ov and pd.notna(t1):
                if pd.notna(t2):
                    pr_cust = f"{max(0, (t2.date() - t1.date()).days)} дн."
                else:
                    pr_cust = f"{max(0, (today - t1.date()).days)} дн."
            row_dict = {
                "Контрагент": row.get(contr_col, "") if contr_col else "",
                "Объект": row.get(obj_col, "") if obj_col else "",
                "№ документа": row.get("DocNumber", row.get("DocID", "")),
                "Тип": row.get(kind_col, "") if kind_col else "",
                "Плановая дата сдачи": plan_dt.strftime("%d.%m.%Y") if pd.notna(plan_dt) else "",
                "Факт сдачи": fact_dt.strftime("%d.%m.%Y") if pd.notna(fact_dt) else "",
                "Просрочка сдачи": pr_sub if not hide_ov else "—",
                "Дата передачи заказчику": t1.strftime("%d.%m.%Y") if pd.notna(t1) else "",
                "Дата согласования": t2.strftime("%d.%m.%Y") if pd.notna(t2) else "",
                "Просрочка соглас.": pr_cust if not hide_ov else "—",
                "Статус": st_l,
                "Дата создания": (
                    _tessa_to_datetime(pd.Series([row.get(creation_col)])).iloc[0].strftime("%d.%m.%Y")
                    if creation_col and pd.notna(_tessa_to_datetime(pd.Series([row.get(creation_col)])).iloc[0])
                    else ""
                ),
            }
            rows_out.append(row_dict)
        table_df = pd.DataFrame(rows_out)
        sort_col = _exec_query_param_value("exec_sort", "Дата создания")
        sort_order = _exec_query_param_value("exec_order", "desc")
        if sort_col in table_df.columns:
            table_df = _exec_sort_table_df(table_df, sort_col, sort_order)
        st.markdown(f"**Записей:** {len(table_df)}")
        st.markdown(
            _EXEC_DOC_DETAIL_CSS
            + '<div class="exec-doc-panel">'
            + _exec_detail_table_html(
                table_df,
                sort_col=sort_col,
                sort_order=sort_order,
            )
            + '<div class="exec-doc-caption">Клик по заголовку сортирует таблицу. '
            + 'Просрочки показываются в днях, а дата создания выводится без времени.</div></div>',
            unsafe_allow_html=True,
        )
        if len(table_df) > 500:
            with st.expander("Ограничение отображения в браузере", expanded=False):
                st.caption("Показано 500 из записей — скачайте CSV или Excel для полного списка.")
        render_dataframe_excel_csv_downloads(
            table_df,
            file_stem="executive_docs",
            key_prefix="exec_doc",
        )

    with tab_dyn:
        st.subheader("Динамика по месяцам (по дате создания)")
        if not creation_col or filtered["_cd"].isna().all():
            st.info("Нет колонки даты создания для построения динамики.")
        else:
            dyn = filtered.assign(_m=filtered["_cd"].dt.to_period("M"))
            dyn = dyn[dyn["_m"].notna()]
            if dyn.empty:
                st.info("Недостаточно дат для динамики.")
            else:
                cnt = dyn.groupby("_m", sort=True).size().reset_index(name="Новых документов")
                cnt = cnt.sort_values("_m")
                cnt["Месяц"] = cnt["_m"].map(
                    lambda p: (
                        f"{(RUSSIAN_MONTHS.get(p.month, '') or '')[:3].lower()} {p.year}".strip()
                        if isinstance(p, pd.Period)
                        else str(p)
                    )
                )
                fig3 = px.bar(
                    cnt,
                    x="Месяц",
                    y="Новых документов",
                    text="Новых документов",
                    color_discrete_sequence=["#60a5fa"],
                )
                fig3.update_traces(textposition="outside", textfont=dict(color="white"))
                fig3 = _apply_finance_bar_label_layout(fig3)
                fig3 = _apply_vertical_category_bar_width(fig3)
                fig3 = apply_chart_background(fig3)
                fig3.update_layout(
                    height=400,
                    xaxis_title="Месяц",
                    yaxis_title="Количество",
                    xaxis=dict(tickangle=-35, categoryorder="array", categoryarray=list(cnt["Месяц"])),
                )
                render_chart(fig3, caption_below="Поступление документов по месяцам", key="exec_month_dyn")
    st.markdown("</div>", unsafe_allow_html=True)


# ==================== DASHBOARD: график рабочей силы (объединённый) ====================
def dashboard_workforce_and_skud(df):
    """
    Объединённый отчёт: основной график движения рабочей силы.
    """
    st.header("График движения рабочей силы")
    dashboard_workforce_movement(df)


def _pd_msp_immediate_parent_names(
    df: pd.DataFrame, level_col: str, name_col: str
) -> pd.Series:
    """Имя ближайшего родителя по иерархии MSP (порядок строк как в выгрузке)."""
    lv = outline_level_numeric(df[level_col])
    nm = df[name_col].map(lambda x: "" if pd.isna(x) else str(x))
    stack = []
    out = []
    for i in range(len(df)):
        raw_l = lv.iloc[i]
        n = nm.iloc[i] or ""
        if pd.isna(raw_l):
            out.append("")
            continue
        l = float(raw_l)
        while stack and stack[-1][0] >= l:
            stack.pop()
        par = stack[-1][1] if stack else ""
        out.append(par)
        stack.append((l, n))
    return pd.Series(out, index=df.index)


def _pd_msp_find_baseline_finish_col(df: pd.DataFrame):
    for c in df.columns:
        cl = str(c).strip().lower()
        if ("baseline" in cl or "базов" in cl) and ("finish" in cl or "оконч" in cl):
            return c
    return None


def _pd_msp_find_schedule_finish_col(df: pd.DataFrame):
    candidates = []
    for c in df.columns:
        cs = str(c).strip()
        cl = cs.lower()
        if "базов" in cl or "baseline" in cl:
            continue
        if cl in ("finish", "окончание") or (
            cl.endswith("окончание") and "план" not in cl and "факт" not in cl
        ):
            candidates.append((len(cs), c))
    if candidates:
        return min(candidates, key=lambda x: x[0])[1]
    if "finish" in df.columns:
        return "finish"
    return None


def _pd_msp_pct_complete_col(df: pd.DataFrame):
    for c in df.columns:
        cl = str(c).strip().lower()
        if "%" in cl and ("заверш" in cl or "complete" in cl):
            return c
        if "процент" in cl and "заверш" in cl:
            return c
    return None


def _pd_msp_actual_finish_col(df: pd.DataFrame):
    for c in df.columns:
        cl = str(c).strip().lower()
        if ("actual" in cl or "фактичес" in cl or cl.startswith("факт")) and (
            "finish" in cl or "оконч" in cl
        ):
            return c
    if "actual finish" in df.columns:
        return "actual finish"
    if "base end" in df.columns:
        return "base end"
    return None


def _pd_cumsum_by_date(dates, row_mask):
    dt = pd.to_datetime(dates, errors="coerce", dayfirst=True, format="mixed")
    m = row_mask.fillna(False) & dt.notna()
    if not m.any():
        return pd.DataFrame(columns=["Дата", "Количество"])
    s = dt.loc[m].dt.normalize()
    daily = s.groupby(s).size().reset_index(name="cnt")
    daily.columns = ["Дата", "cnt"]
    daily = daily.sort_values("Дата")
    daily["Количество"] = daily["cnt"].cumsum()
    return daily[["Дата", "Количество"]]



# ==================== DASHBOARD 8.7: Documentation ====================
def dashboard_documentation(
    df,
    page_title: str = "Рабочая/Проектная документация",
    *,
    embed_delay_at_end: bool = True,
):
    st.header(page_title)

    _doc_fk = (
        "rd_work_"
        if page_title == "Рабочая документация"
        else ("pd_doc_" if page_title == "Проектная документация" else "doc_")
    )
    is_pd = page_title == "Проектная документация"

    if df is None or not hasattr(df, "columns") or df.empty:
        st.warning(
            f"Для отчёта «{page_title}» загрузите файл с данными проекта (CSV/Excel с колонками по задачам и "
            + ("ПД / MS Project." if is_pd else "РД.")
        )
        return

    # Find column names (they might have different formats)
    # Try to find columns by partial name matching
    def find_column(data, possible_names):
        """Find column by possible names"""
        for col in data.columns:
            # Normalize column name: remove newlines, extra spaces, normalize case
            col_normalized = str(col).replace("\n", " ").replace("\r", " ").strip()
            col_lower = col_normalized.lower()

            for name in possible_names:
                name_lower = name.lower().strip()
                # Exact match (case insensitive)
                if name_lower == col_lower:
                    return col
                # Substring match
                if name_lower in col_lower or col_lower in name_lower:
                    return col
                # Check if all key words from name are in column
                name_words = [w for w in name_lower.split() if len(w) > 2]
                if name_words and all(word in col_lower for word in name_words):
                    return col

        # Special handling for RD count column with key words
        if any(
            "разделов" in n.lower() and "рд" in n.lower() and "договор" in n.lower()
            for n in possible_names
        ):
            for col in data.columns:
                col_lower = str(col).lower().replace("\n", " ").replace("\r", " ")
                key_words = ["разделов", "рд", "договор", "количество"]
                if all(word in col_lower for word in key_words if len(word) > 3):
                    return col

        return None

    # Find required columns (sample_project_data_fixed.csv: «РД по Договору», нет «Количество разделов РД по Договору»)
    rd_count_col = find_column(
        df,
        [
            "Количество разделов РД по Договору",
            "Количество разделов РД",
            "РД по Договору",
            "разделов РД",
            "Количетсов разделов РД по Договору",  # Handle typo
            "Количество разделов РД по договору",
        ],
    )

    on_approval_col = find_column(df, ["На согласовании", "согласовании"])
    in_production_col = find_column(
        df,
        [
            "Выдано в производство работ",
            "Разработано",
            "В работе",
            "производство работ",
            "в производство",
        ],
    )
    plan_start_col = (
        "plan start"
        if "plan start" in df.columns
        else find_column(df, ["Старт План", "План Старт"])
    )
    plan_end_col = (
        "plan end"
        if "plan end" in df.columns
        else find_column(df, ["Конец План", "План Конец"])
    )
    base_start_col = (
        "base start"
        if "base start" in df.columns
        else find_column(df, ["Старт Факт", "Факт Старт"])
    )
    base_end_col = (
        "base end"
        if "base end" in df.columns
        else find_column(df, ["Конец Факт", "Факт Конец"])
    )

    # Для РД — колонки выгрузки; для ПД достаточно задач MS Project
    missing_cols = []
    if not is_pd:
        if not rd_count_col:
            missing_cols.append("Количество разделов РД по Договору")
        if not on_approval_col:
            missing_cols.append("На согласовании")
        if not in_production_col:
            missing_cols.append("Выдано в производство работ")

    if missing_cols:
        st.warning(f"⚠️ Отсутствуют необходимые колонки: {', '.join(missing_cols)}")
        st.info("Пожалуйста, убедитесь, что файл содержит все необходимые колонки.")
        return

    section_col = (
        "section" if "section" in df.columns else find_column(df, ["Раздел", "section"])
    )
    contractor_col = find_column(df, ["Выдана подрядчику", "подрядчику"])
    rework_col = find_column(df, ["На доработке", "доработке"])
    period_source_col = (
        plan_end_col if plan_end_col and plan_end_col in df.columns else plan_start_col
    )

    def _to_numeric_series(series):
        return pd.to_numeric(
            series.astype(str)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False),
            errors="coerce",
        ).fillna(0.0)

    def _to_datetime_series(series):
        return pd.to_datetime(series.astype(str), errors="coerce", dayfirst=True, format="mixed")

    # Find project column for filtering
    project_col = (
        "project name"
        if "project name" in df.columns
        else find_column(df, ["Проект", "project"])
    )

    # Add filters
    st.subheader("Фильтры")
    st.markdown(
        """
        <style>
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="column"]) div[data-testid="column"] {
            flex: 1 1 0% !important;
            min-width: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    filter_col1, filter_col2, filter_col3 = st.columns(3, gap="small")

    # Filter by project (несколько проектов; пусто = все)
    selected_projects_doc: list[str] = []
    if project_col and project_col in df.columns:
        with filter_col1:
            _proj_opts = _unique_project_labels_for_select(df[project_col])
            selected_projects_doc = st.multiselect(
                "Фильтр по проекту",
                options=_proj_opts,
                default=st.session_state.get(f"{_doc_fk}project_filter_ms", []),
                key=f"{_doc_fk}project_filter_ms",
                help="Пустой выбор — все проекты.",
                placeholder="Все проекты",
            )

    # Filter by date period
    selected_date_start = None
    selected_date_end = None
    if period_source_col and period_source_col in df.columns:
        with filter_col2:
            df_dates = _to_datetime_series(df[period_source_col])
            valid_dates = df_dates[df_dates.notna()]

            if not valid_dates.empty:
                min_date = valid_dates.min().date()
                max_date = valid_dates.max().date()
                selected_period_mode = st.selectbox(
                    "Период",
                    ["Весь период (за всё время)", "Выбор диапазона дат"],
                    index=0,
                    key=f"{_doc_fk}period_mode",
                )
                if selected_period_mode == "Выбор диапазона дат":
                    selected_period = st.date_input(
                        ("Диапазон дат (по дате сдачи ПД в плане)" if is_pd else "Диапазон дат (по дате сдачи РД в плане)"),
                        value=(min_date, max_date),
                        min_value=min_date,
                        max_value=max_date,
                        key=f"{_doc_fk}date_range",
                        format="DD.MM.YYYY",
                    )
                    if isinstance(selected_period, tuple) and len(selected_period) == 2:
                        selected_date_start, selected_date_end = selected_period
                    else:
                        selected_date_start = selected_period
                        selected_date_end = selected_period
                else:
                    st.caption(f"Весь период: {min_date:%d.%m.%Y} - {max_date:%d.%m.%Y}")

    # Filter by RD section kind (несколько значений; пусто = все)
    selected_sections_doc: list[str] = []
    with filter_col3:
        if section_col and section_col in df.columns:
            section_options = sorted(
                {
                    str(v).strip()
                    for v in df[section_col].dropna().tolist()
                    if str(v).strip() and str(v).strip().lower() not in ("nan", "none")
                },
                key=lambda x: x.casefold(),
            )
            selected_sections_doc = st.multiselect(
                "Фильтр по виду раздела РД",
                options=section_options,
                default=st.session_state.get(f"{_doc_fk}section_filter_ms", []),
                key=f"{_doc_fk}section_filter_ms",
                help="Пустой выбор — все виды разделов.",
                placeholder="Все разделы",
            )
        else:
            st.caption("Колонка раздела РД не найдена.")

    # Filter by RD status — отдельной строкой, чтобы не ломать сетку selectbox’ов
    selected_statuses: list[str] = []
    rd_status_options: list[str] = []
    if on_approval_col and on_approval_col in df.columns:
        rd_status_options.append("На согласовании")
    if in_production_col and in_production_col in df.columns:
        rd_status_options.append("Выдано в производство работ")
    if contractor_col and contractor_col in df.columns:
        rd_status_options.append(
            "Передано подрядчику"
            if page_title == "Рабочая документация"
            else "Выдана подрядчику"
        )
    if rework_col and rework_col in df.columns:
        rd_status_options.append("На доработке")
    if page_title == "Рабочая документация":
        if "Просрочено подрядчиком" not in rd_status_options:
            rd_status_options.append("Просрочено подрядчиком")

    _status_label = (
        "Фильтр по статусу ПД"
        if page_title == "Проектная документация"
        else "Фильтр по статусу РД"
    )
    if rd_status_options:
        selected_statuses = st.pills(
            _status_label,
            rd_status_options,
            selection_mode="multi",
            default=rd_status_options,
            key=f"{_doc_fk}status_filter",
            help="Пустой выбор означает все статусы.",
        )
        if selected_statuses is None:
            selected_statuses = []
    else:
        st.caption("Нет колонок статусов РД/ПД для фильтра.")

    # Apply filters to data
    filtered_df = df.copy()

    # Apply project filter
    if selected_projects_doc and project_col and project_col in df.columns:
        _pk_set_doc = {_project_filter_norm_key(p) for p in selected_projects_doc}
        filtered_df = filtered_df[
            filtered_df[project_col].map(_project_filter_norm_key).isin(_pk_set_doc)
        ]

    if (
        selected_sections_doc
        and section_col
        and section_col in filtered_df.columns
    ):
        _sset = {str(x).strip() for x in selected_sections_doc if str(x).strip()}
        if _sset:
            filtered_df = filtered_df[
                filtered_df[section_col].astype(str).str.strip().isin(_sset)
            ]

    # Apply date filter
    if (
        selected_date_start
        and selected_date_end
        and period_source_col
        and period_source_col in df.columns
    ):
        filtered_df[period_source_col + "_parsed"] = _to_datetime_series(
            filtered_df[period_source_col]
        )
        date_mask = (
            filtered_df[period_source_col + "_parsed"].notna()
            & (filtered_df[period_source_col + "_parsed"].dt.date >= selected_date_start)
            & (filtered_df[period_source_col + "_parsed"].dt.date <= selected_date_end)
        )
        filtered_df = filtered_df[date_mask].copy()

    # Apply status filter: только если выбрано не «все метки» и не пусто (пусто = все)
    if selected_statuses and set(selected_statuses) != set(rd_status_options):
        status_mask = pd.Series([False] * len(filtered_df), index=filtered_df.index)

        if (
            "На согласовании" in selected_statuses
            and on_approval_col
            and on_approval_col in filtered_df.columns
        ):
            on_approval_series = (
                filtered_df[on_approval_col]
                .astype(str)
                .str.replace(",", ".", regex=False)
            )
            on_approval_numeric = pd.to_numeric(
                on_approval_series, errors="coerce"
            ).fillna(0)
            status_mask = status_mask | (on_approval_numeric > 0)

        if (
            "Выдано в производство работ" in selected_statuses
            and in_production_col
            and in_production_col in filtered_df.columns
        ):
            in_production_series = (
                filtered_df[in_production_col]
                .astype(str)
                .str.replace(",", ".", regex=False)
            )
            in_production_numeric = pd.to_numeric(
                in_production_series, errors="coerce"
            ).fillna(0)
            status_mask = status_mask | (in_production_numeric > 0)

        if (
            (
                "Выдана подрядчику" in selected_statuses
                or "Передано подрядчику" in selected_statuses
            )
            and contractor_col
            and contractor_col in filtered_df.columns
        ):
            contractor_series = (
                filtered_df[contractor_col]
                .astype(str)
                .str.replace(",", ".", regex=False)
            )
            contractor_numeric = pd.to_numeric(
                contractor_series, errors="coerce"
            ).fillna(0)
            status_mask = status_mask | (contractor_numeric > 0)

        if (
            "На доработке" in selected_statuses
            and rework_col
            and rework_col in filtered_df.columns
        ):
            rework_series = (
                filtered_df[rework_col].astype(str).str.replace(",", ".", regex=False)
            )
            rework_numeric = pd.to_numeric(rework_series, errors="coerce").fillna(0)
            status_mask = status_mask | (rework_numeric > 0)

        if "Просрочено подрядчиком" in selected_statuses and page_title == "Рабочая документация":
            today_d = date.today()
            pe = pd.Series(pd.NaT, index=filtered_df.index)
            if plan_end_col and plan_end_col in filtered_df.columns:
                pe = pd.to_datetime(
                    filtered_df[plan_end_col].astype(str),
                    errors="coerce",
                    dayfirst=True,
                    format="mixed",
                )
            fe = pd.Series(pd.NaT, index=filtered_df.index)
            if base_end_col and base_end_col in filtered_df.columns:
                fe = pd.to_datetime(
                    filtered_df[base_end_col].astype(str),
                    errors="coerce",
                    dayfirst=True,
                    format="mixed",
                )
            issued = pd.Series(False, index=filtered_df.index)
            if contractor_col and contractor_col in filtered_df.columns:
                issued = (
                    pd.to_numeric(
                        filtered_df[contractor_col]
                        .astype(str)
                        .str.replace(",", ".", regex=False),
                        errors="coerce",
                    ).fillna(0)
                    > 0
                )
            done_on_time = fe.notna() & pe.notna() & (fe.dt.normalize() <= pe.dt.normalize())
            overdue_plan = pe.notna() & (pe.dt.date < today_d)
            oc_mask = issued & overdue_plan & (~done_on_time)
            status_mask = status_mask | oc_mask

        filtered_df = filtered_df[status_mask].copy()

    if project_col and project_col in filtered_df.columns:
        filtered_df = _project_column_apply_canonical(filtered_df, project_col)

    if filtered_df.empty:
        st.info("Нет данных для выбранных фильтров.")
        return

    # Use filtered_df for all subsequent operations
    df = filtered_df

    if is_pd:
        ensure_date_columns(df)
        ensure_msp_hierarchy_columns(df)

    if not is_pd:
        # Prepare data for pie chart "Исполнение РД"
        try:
            total_sections = (
                float(_to_numeric_series(df[rd_count_col]).sum())
                if rd_count_col and rd_count_col in df.columns
                else 0.0
            )
            issued_sum = float(_to_numeric_series(df[in_production_col]).sum())
            on_ap_sum = float(_to_numeric_series(df[on_approval_col]).sum())
            rework_sum = (
                float(_to_numeric_series(df[rework_col]).sum())
                if rework_col and rework_col in df.columns
                else 0.0
            )
            not_accepted_sum = on_ap_sum + rework_sum
            not_issued_sum = max(total_sections - issued_sum - not_accepted_sum, 0.0)

            if (
                total_sections > 0
                or issued_sum > 0
                or not_accepted_sum > 0
                or not_issued_sum > 0
            ):
                st.subheader("Исполнение РД")
                pie_data = {
                    "Выдано в производство": int(round(max(issued_sum, 0.0))),
                    "На согласовании": int(round(max(on_ap_sum, 0.0))),
                    "На доработке": int(round(max(rework_sum, 0.0))),
                    "Не выдано": int(round(max(not_issued_sum, 0.0))),
                }
                pie_data = {k: v for k, v in pie_data.items() if v > 0}

                if pie_data:
                    fig_pie = px.pie(
                        values=list(pie_data.values()),
                        names=list(pie_data.keys()),
                        title=None,
                        color_discrete_map={
                            "Выдано в производство": "#2E86AB",
                            "На согласовании": "#F39C12",
                            "На доработке": "#E67E22",
                            "Не выдано": "#E74C3C",
                        },
                    )
                    fig_pie.update_traces(
                        textinfo="label+percent+value",
                        textposition="auto",
                        textfont_size=10,
                        insidetextorientation="radial",
                        hovertemplate="<b>%{label}</b><br>Значение: %{value}<br>Доля: %{percent}<br><extra></extra>",
                    )
                    fig_pie.update_layout(
                        height=500,
                        showlegend=True,
                        uniformtext=dict(minsize=8, mode="hide"),
                        legend=dict(orientation="v", font=dict(size=10), title_text=""),
                    )
                    fig_pie = apply_chart_background(fig_pie)
                    render_chart(fig_pie, caption_below="Исполнение РД")
                else:
                    st.info("Нет данных для построения графика 'Исполнение РД'.")
            else:
                st.info("Нет данных для построения графика 'Исполнение РД'.")
        except Exception as e:
            st.error(f"Ошибка при построении графика 'Исполнение РД': {str(e)}")


    else:
        try:
            level_col = (
                "level structure"
                if "level structure" in df.columns
                else ("level" if "level" in df.columns else None)
            )
            name_col = (
                "task name"
                if "task name" in df.columns
                else find_column(df, ["Название задачи", "Задача", "Task Name", "Имя задачи"])
            )
            if (
                not level_col
                or not name_col
                or level_col not in df.columns
                or name_col not in df.columns
            ):
                st.warning("Для ПД нужны колонки уровня иерархии MSP и наименование задачи.")
            else:
                parents = _pd_msp_immediate_parent_names(df, level_col, name_col)
                lv = outline_level_numeric(df[level_col])
                tn = df[name_col].astype(str)
                sec_mask = (
                    lv.eq(5)
                    & tn.str.contains("Раздел", case=False, na=False)
                    & parents.astype(str).str.contains(
                        "Проектная документация", case=False, na=False
                    )
                )
                pct_col = _pd_msp_pct_complete_col(df)
                if pct_col and pct_col in df.columns:
                    pc = pd.to_numeric(df[pct_col], errors='coerce').fillna(0.0)
                else:
                    pc = pd.Series(0.0, index=df.index)
                m = sec_mask.fillna(False)
                done_v = int((m & (pc >= 99.99)).sum())
                prog_v = int((m & (pc > 0) & (pc < 99.99)).sum())
                wait_v = int((m & (pc <= 0)).sum())
                if done_v + prog_v + wait_v > 0:
                    st.subheader("Исполнение ПД")
                    pie_data = {
                        "Завершено (100%)": int(done_v),
                        "В работе": int(prog_v),
                        "Не начато": int(wait_v),
                    }
                    pie_data = {k: v for k, v in pie_data.items() if v > 0}
                    if pie_data:
                        fig_pie = px.pie(
                            values=list(pie_data.values()),
                            names=list(pie_data.keys()),
                            title=None,
                            color_discrete_map={
                                "Завершено (100%)": "#2E86AB",
                                "В работе": "#F39C12",
                                "Не начато": "#E74C3C",
                            },
                        )
                        fig_pie.update_traces(
                            textinfo="label+percent+value",
                            textposition="auto",
                            textfont_size=10,
                            insidetextorientation="radial",
                            hovertemplate=(
                                "<b>%{label}</b><br>Значение: %{value}<br>Доля: %{percent}<br><extra></extra>"
                            ),
                        )
                        fig_pie.update_layout(
                            height=500,
                            showlegend=True,
                            uniformtext=dict(minsize=8, mode='hide'),
                            legend=dict(orientation="v", font=dict(size=10), title_text=""),
                        )
                        fig_pie = apply_chart_background(fig_pie)
                        render_chart(fig_pie, caption_below="Исполнение ПД")
                else:
                    st.info("Нет задач разделов ПД (ур.5, «Раздел», родитель «Проектная документация»).")
        except Exception as e:
            st.error(f"Ошибка при построении графика 'Исполнение ПД': {str(e)}")

    if not is_pd:
        # Prepare data for "Динамика выдачи РД"
        # X-axis: "Старт План" (plan start date)
        # Plan (Y-axis): "РД по Договору" (grouped by "Старт План")
        # Fact (Y-axis): "Выдано в производство работ" (grouped by "Старт План")
        try:
            # Find column for plan data: "РД по Договору"
            rd_plan_col = find_column(
                df, ["РД по Договору", "РД по договору", "рд по договору", "РД по Договору"]
            )

            plan_date_col = (
                plan_end_col if plan_end_col and plan_end_col in df.columns else plan_start_col
            )
            fact_date_col = (
                "actual finish"
                if "actual finish" in df.columns
                else find_column(
                    df,
                    [
                        "actual finish",
                        "фактическое окончание",
                        "окончание факт",
                        "факт окончание",
                    ],
                )
            )
            if not fact_date_col or fact_date_col not in df.columns:
                fact_date_col = base_end_col

            # Check if required columns exist
            if not plan_date_col or plan_date_col not in df.columns:
                st.warning(
                    "Для построения графика 'Динамика выдачи РД' необходима колонка плановой даты (plan end / plan start)."
                )
                return

            if not rd_plan_col or rd_plan_col not in df.columns:
                st.warning(
                    "Для построения графика 'Динамика выдачи РД' необходима колонка 'РД по Договору'."
                )
                return

            if not in_production_col or in_production_col not in df.columns:
                st.warning(
                    "Для построения графика 'Динамика выдачи РД' необходима колонка 'Выдано в производство работ'."
                )
                return

            max_plan_end_date = None
            max_fact_end_date = None

            df["rd_plan_numeric"] = _to_numeric_series(df[rd_plan_col])

            # Если «РД по Договору» везде ноль, а есть отдельная колонка «количество разделов РД» с данными — план берём из неё (ТЗ: план не нулевой без причины)
            rd_sections_for_plan_fallback = find_column(
                df,
                [
                    "Количество разделов РД по Договору",
                    "Количество разделов РД",
                    "разделов РД по договору",
                    "Количетсов разделов РД по Договору",
                ],
            )
            if (
                rd_sections_for_plan_fallback
                and rd_sections_for_plan_fallback in df.columns
                and rd_sections_for_plan_fallback != rd_plan_col
            ):
                if float(df["rd_plan_numeric"].sum()) == 0.0:
                    cnt_num = _to_numeric_series(df[rd_sections_for_plan_fallback])
                    if float(cnt_num.sum()) > 0.0:
                        df["rd_plan_numeric"] = cnt_num

            df["in_production_numeric"] = _to_numeric_series(df[in_production_col])
            df["_doc_plan_date"] = _to_datetime_series(df[plan_date_col])
            df["_doc_fact_date"] = (
                _to_datetime_series(df[fact_date_col])
                if fact_date_col and fact_date_col in df.columns
                else pd.Series(pd.NaT, index=df.index)
            )
            if df["_doc_plan_date"].notna().any():
                max_plan_end_date = df["_doc_plan_date"].max().date()
            if isinstance(df["_doc_fact_date"], pd.Series) and df["_doc_fact_date"].notna().any():
                max_fact_end_date = df["_doc_fact_date"].max().date()

            # Prepare data
            dynamics_data = []

            # Plan data: group by planned issue date
            plan_mask = df["_doc_plan_date"].notna()
            if plan_mask.any():
                plan_grouped = (
                    df[plan_mask]
                    .groupby(df[plan_mask]["_doc_plan_date"].dt.normalize())
                    .agg({"rd_plan_numeric": "sum"})
                    .reset_index()
                )
                plan_grouped.columns = ["Дата", "Количество"]
                plan_grouped["Тип"] = "План"
                # Fill NaN with 0 and ensure all values are numeric
                plan_grouped["Количество"] = plan_grouped["Количество"].fillna(0)
                # Always add plan data, even if all values are 0
                dynamics_data.append(plan_grouped)

            # Fact data: group by actual issue date
            fact_mask = df["_doc_fact_date"].notna() & (df["in_production_numeric"] > 0)
            if fact_mask.any():
                fact_grouped = (
                    df[fact_mask]
                    .groupby(df[fact_mask]["_doc_fact_date"].dt.normalize())
                    .agg({"in_production_numeric": "sum"})
                    .reset_index()
                )
                fact_grouped.columns = ["Дата", "Количество"]
                fact_grouped["Тип"] = "Факт"
                # Fill NaN with 0 and ensure all values are numeric
                fact_grouped["Количество"] = fact_grouped["Количество"].fillna(0)
                # Filter out rows where sum is 0 for fact (only show actual production)
                fact_grouped = fact_grouped[fact_grouped["Количество"] > 0]
                if not fact_grouped.empty:
                    dynamics_data.append(fact_grouped)

            if dynamics_data:
                st.subheader("Динамика выдачи РД")
                dynamics_df = pd.concat(dynamics_data, ignore_index=True)
                all_dates = pd.to_datetime(dynamics_df["Дата"], errors="coerce").dropna()
                if not all_dates.empty:
                    start_anchor = (all_dates.min() - pd.Timedelta(days=1)).normalize()
                    zero_rows = pd.DataFrame(
                        {
                            "Дата": [start_anchor, start_anchor],
                            "Количество": [0.0, 0.0],
                            "Тип": ["План", "Факт"],
                        }
                    )
                    dynamics_df = pd.concat([zero_rows, dynamics_df], ignore_index=True)
                dynamics_df = dynamics_df.sort_values(["Тип", "Дата"])

                dynamics_df["Накопительное_значение"] = 0.0
                for typ in dynamics_df["Тип"].unique():
                    mask = dynamics_df["Тип"] == typ
                    dynamics_df.loc[mask, "Накопительное_значение"] = dynamics_df.loc[
                        mask, "Количество"
                    ].cumsum()

                # Используем накопительные значения для графика
                dynamics_df["Количество"] = dynamics_df["Накопительное_значение"]

                # Показатели: план по проекту, план/факт/отклонение на текущую дату, прогноз производительности
                plan_df = dynamics_df[dynamics_df["Тип"] == "План"].sort_values("Дата")
                fact_df = dynamics_df[dynamics_df["Тип"] == "Факт"].sort_values("Дата")
                today = date.today()

                plan_total = float(plan_df["Количество"].max()) if not plan_df.empty else 0.0
                plan_to_date = 0.0
                if not plan_df.empty:
                    dt_plan = pd.to_datetime(plan_df["Дата"])
                    past_plan = plan_df[dt_plan.dt.date <= today]
                    plan_to_date = float(past_plan["Количество"].iloc[-1]) if not past_plan.empty else 0.0
                fact_to_date = 0.0
                if not fact_df.empty:
                    dt_fact = pd.to_datetime(fact_df["Дата"])
                    past_fact = fact_df[dt_fact.dt.date <= today]
                    fact_to_date = float(past_fact["Количество"].iloc[-1]) if not past_fact.empty else 0.0
                deviation_to_date = fact_to_date - plan_to_date

                first_plan_date = plan_df["Дата"].min() if not plan_df.empty else None
                last_plan_date = plan_df["Дата"].max() if not plan_df.empty else None
                if first_plan_date is not None:
                    first_d = pd.to_datetime(first_plan_date).date()
                else:
                    first_d = today
                if last_plan_date is not None:
                    last_d = pd.to_datetime(last_plan_date).date()
                else:
                    last_d = today
                weeks_elapsed = max((today - first_d).days / 7.0, 1.0 / 7.0)
                current_productivity = fact_to_date / weeks_elapsed if weeks_elapsed > 0 else 0.0
                remaining_days = (last_d - today).days
                remaining_weeks = max(remaining_days / 7.0, 0.0)
                remaining_to_plan = max(plan_total - fact_to_date, 0.0)
                required_productivity = (remaining_to_plan / remaining_weeks) if remaining_weeks > 0 else float("inf")

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("План по проекту", f"{plan_total:,.0f}".replace(",", " "))
                with c2:
                    st.metric("План на текущую дату", f"{plan_to_date:,.0f}".replace(",", " "))
                with c3:
                    st.metric("Факт на текущую дату", f"{fact_to_date:,.0f}".replace(",", " "))
                with c4:
                    st.metric("Отклонение на текущую дату", f"{deviation_to_date:+,.0f}".replace(",", " "))

                if page_title == "Рабочая документация":
                    if max_plan_end_date is not None:
                        plan_end_ref = max_plan_end_date
                        use_approx_plan_end = False
                    elif last_plan_date is not None:
                        plan_end_ref = last_d
                        use_approx_plan_end = True
                    else:
                        plan_end_ref = None
                        use_approx_plan_end = False
                    days_to_plan_end = (
                        (plan_end_ref - today).days if plan_end_ref is not None else None
                    )
                    if days_to_plan_end is not None and days_to_plan_end > 0:
                        nec_rd = deviation_to_date / days_to_plan_end * 7.0
                    else:
                        nec_rd = None

                    planned_weekly = None
                    if max_plan_end_date is not None and max_fact_end_date is not None:
                        d12 = (max_plan_end_date - max_fact_end_date).days
                        if d12 > 0:
                            planned_weekly = plan_to_date / d12 * 7.0

                    fact_weekly = None
                    if max_fact_end_date is not None:
                        d13 = (today - max_fact_end_date).days
                        if d13 > 0:
                            fact_weekly = fact_to_date / d13 * 7.0

                    st.caption("Производительность разделов в неделю (п.12–14 ТЗ)")
                    if use_approx_plan_end:
                        st.caption(
                            "Дата окончания плановая: в колонке планового окончания нет валидных дат — "
                            "используется дата по правому краю кривой динамики (приблизительно)."
                        )
                    pw1, pw2, pw3 = st.columns(3)
                    with pw1:
                        st.metric(
                            "Плановая производительность",
                            "—"
                            if planned_weekly is None
                            else f"{planned_weekly:,.1f}".replace(",", " "),
                            help="План на текущую дату / (дата окончания план − дата окончания факт) × 7",
                        )
                    with pw2:
                        st.metric(
                            "Фактическая производительность",
                            "—"
                            if fact_weekly is None
                            else f"{fact_weekly:,.1f}".replace(",", " "),
                            help="Факт на текущую дату / (сегодня − дата окончания факт) × 7; только если дата окончания факт в прошлом",
                        )
                    with pw3:
                        if nec_rd is None:
                            st.metric(
                                "Необходимая производительность",
                                "—",
                                help="Отклонение на текущую дату / (дата окончания план − сегодня) × 7 при положительном остатке дней до планового окончания",
                            )
                        else:
                            st.metric(
                                "Необходимая производительность",
                                f"{nec_rd:,.1f}".replace(",", " "),
                                help="Отклонение на текущую дату / (дата окончания план − сегодня) × 7",
                            )
                else:
                    st.caption("Прогноз производительности (РД в неделю)")
                    p1, p2 = st.columns(2)
                    with p1:
                        st.metric(
                            "Текущая производительность в неделю",
                            f"{current_productivity:,.1f}".replace(",", " "),
                            help="Факт на текущую дату / число недель с начала плана",
                        )
                    with p2:
                        if remaining_weeks <= 0:
                            st.metric(
                                "Необходимая для выполнения плана",
                                "—",
                                help="Плановый срок завершения уже наступил или прошёл",
                            )
                        elif required_productivity == float("inf"):
                            st.metric(
                                "Необходимая для выполнения плана",
                                "—",
                                help="Нет оставшегося срока",
                            )
                        else:
                            st.metric(
                                "Необходимая для выполнения плана",
                                f"{required_productivity:,.1f}".replace(",", " "),
                                help="(План по проекту − Факт на текущую дату) / оставшиеся недели",
                            )

                dynamics_df["Текст"] = dynamics_df["Количество"].apply(
                    lambda x: f"{x:.0f}" if pd.notna(x) and float(x) != 0.0 else ""
                )

                fig_dynamics = px.line(
                    dynamics_df,
                    x="Дата",
                    y="Количество",
                    color="Тип",
                    title=None,
                    markers=True,
                    labels={"Количество": "Количество", "Дата": "Дата"},
                    text="Текст",
                    color_discrete_map={"План": "#2E86AB", "Факт": "#F39C12"},
                )

                fig_dynamics.update_layout(
                    xaxis_title="Период",
                    yaxis_title="Количество",
                    hovermode="x unified",
                    height=550,
                    xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
                    yaxis=dict(rangemode="tozero"),
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                        title_text="",
                    ),
                )
                # Update legend labels to be more descriptive
                fig_dynamics.for_each_trace(
                    lambda t: t.update(
                        name=(
                            "План"
                            if t.name == "План"
                            else (
                                "Факт"
                                if t.name == "Факт"
                                else t.name
                            )
                        )
                    )
                )
                # Add text labels and format - ensure text is always visible
                fig_dynamics.update_traces(
                    line=dict(width=2),
                    marker=dict(size=6),
                    mode="lines+markers+text",
                    textposition="top center",
                    textfont=dict(size=10, color="white"),
                )
                fig_dynamics = apply_chart_background(fig_dynamics)
                render_chart(fig_dynamics, caption_below="Динамика выдачи РД")
            else:
                st.warning("Нет данных для построения графика 'Динамика выдачи РД'.")
        except Exception as e:
            st.error(f"Ошибка при построении графика 'Динамика выдачи РД': {str(e)}")


    else:
        try:
            level_col = (
                "level structure"
                if "level structure" in df.columns
                else ("level" if "level" in df.columns else None)
            )
            name_col = (
                "task name"
                if "task name" in df.columns
                else find_column(df, ["Название задачи", "Задача", "Task Name", "Имя задачи"])
            )
            if not level_col or not name_col or level_col not in df.columns or name_col not in df.columns:
                st.warning("Для графика ПД нужны колонки уровня и наименования задач MSP.")
            else:
                parents = _pd_msp_immediate_parent_names(df, level_col, name_col)
                lv = outline_level_numeric(df[level_col])
                tn = df[name_col].astype(str)
                sec_mask = (
                    lv.eq(5)
                    & tn.str.contains("Раздел", case=False, na=False)
                    & parents.astype(str).str.contains(
                        "Проектная документация", case=False, na=False
                    )
                )
                b_fin_col = _pd_msp_find_baseline_finish_col(df)
                if b_fin_col is None and plan_end_col and plan_end_col in df.columns:
                    b_fin_col = plan_end_col
                    st.caption(
                        "Колонка Baseline Finish не найдена — для плана используется plan end (приближённо)."
                    )
                s_fin_col = _pd_msp_find_schedule_finish_col(df)
                if s_fin_col is None and plan_end_col and plan_end_col in df.columns:
                    s_fin_col = plan_end_col
                pct_col = _pd_msp_pct_complete_col(df)
                if pct_col and pct_col in df.columns:
                    pc = pd.to_numeric(df[pct_col], errors='coerce').fillna(0.0)
                else:
                    pc = pd.Series(0.0, index=df.index)
                act_fn = _pd_msp_actual_finish_col(df)
                bf = pd.to_datetime(df[b_fin_col], errors='coerce', dayfirst=True, format='mixed') if b_fin_col else pd.NaT
                sf = pd.to_datetime(df[s_fin_col], errors='coerce', dayfirst=True, format='mixed') if s_fin_col else pd.NaT
                af = (
                    pd.to_datetime(df[act_fn], errors='coerce', dayfirst=True, format='mixed')
                    if act_fn and act_fn in df.columns
                    else pd.Series(pd.NaT, index=df.index)
                )
                if b_fin_col is None or b_fin_col not in df.columns:
                    st.warning("Нет даты базового окончания (Baseline Finish / plan end) для графика ПД.")
                elif s_fin_col is None or s_fin_col not in df.columns:
                    st.warning("Нет даты окончания по текущему графику (Finish / plan end) для прогноза ПД.")
                else:
                    plan_curve = _pd_cumsum_by_date(df[b_fin_col], sec_mask)
                    plan_curve['Тип'] = 'План (базовый план)'
                    fcst_curve = _pd_cumsum_by_date(df[s_fin_col], sec_mask)
                    fcst_curve['Тип'] = 'Прогноз по проекту'
                    curves = [plan_curve, fcst_curve]
                    dynamics_df = pd.concat(curves, ignore_index=True)
                    all_dates = pd.to_datetime(dynamics_df['Дата'], errors='coerce').dropna()
                    if not all_dates.empty:
                        start_anchor = (all_dates.min() - pd.Timedelta(days=1)).normalize()
                        zplan = pd.DataFrame(
                            {
                                'Дата': [start_anchor],
                                'Количество': [0.0],
                                'Тип': ['План (базовый план)'],
                            }
                        )
                        zfcst = pd.DataFrame(
                            {
                                'Дата': [start_anchor],
                                'Количество': [0.0],
                                'Тип': ['Прогноз по проекту'],
                            }
                        )
                        dynamics_df = pd.concat([zplan, zfcst, dynamics_df], ignore_index=True)
                    dynamics_df = dynamics_df.sort_values(['Тип', 'Дата'])
                    today = date.today()
                    plan_total = float(sec_mask.sum())
                    m = sec_mask.fillna(False)
                    plan_to_date = int((m & bf.notna() & (bf.dt.date <= today)).sum())
                    done = m & (pc >= 99.99)
                    fact_to_date = int((done & (af.isna() | (af.dt.date <= today))).sum())
                    deviation_to_date = float(fact_to_date - plan_to_date)
                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        st.metric("План по проекту (БП)", f"{plan_total:,.0f}".replace(",", " "))
                    with c2:
                        st.metric("План на текущую дату (БП)", f"{plan_to_date:,.0f}".replace(",", " "))
                    with c3:
                        st.metric("Факт на текущую дату", f"{fact_to_date:,.0f}".replace(",", " "))
                    with c4:
                        st.metric("Отклонение на текущую дату", f"{deviation_to_date:+,.0f}".replace(",", " "))
                    last_bf = bf[m].max().date() if (m & bf.notna()).any() else None
                    rem_days = (last_bf - today).days if last_bf is not None else None
                    var_gap = float(plan_to_date - fact_to_date)
                    nec = None
                    if rem_days is not None and rem_days > 0:
                        nec = var_gap / rem_days * 7.0
                    win_start = today - timedelta(days=7)
                    prod7 = int((done & af.notna() & (af.dt.date > win_start) & (af.dt.date <= today)).sum())
                    st.caption('Производительность ПД: последние 7 дней и необходимая (по ТЗ)')
                    pw1, pw2 = st.columns(2)
                    with pw1:
                        st.metric("Текущая производительность в неделю", f"{prod7:,.0f}".replace(",", " "))
                    with pw2:
                        st.metric(
                            "Необходимая производительность (неделя)",
                            "—" if nec is None else f"{round(nec):,.0f}".replace(",", " "),
                        )
                    dynamics_df['Текст'] = dynamics_df['Количество'].apply(
                        lambda x: f"{x:.0f}" if pd.notna(x) and float(x) != 0.0 else ""
                    )
                    fig_dynamics = px.line(
                        dynamics_df,
                        x='Дата',
                        y='Количество',
                        color='Тип',
                        title=None,
                        markers=True,
                        labels={'Количество': 'Количество разделов ПД', 'Дата': 'Дата'},
                        text='Текст',
                        color_discrete_map={
                            "План (базовый план)": "#2E86AB",
                            "Прогноз по проекту": "#F39C12",
                        },
                    )
                    fig_dynamics.update_layout(
                        xaxis_title="Период",
                        yaxis_title="Количество разделов ПД",
                        hovermode='x unified',
                        height=550,
                        xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
                        yaxis=dict(rangemode='tozero'),
                        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1, title_text=''),
                    )
                    fig_dynamics.update_traces(
                        line=dict(width=2),
                        marker=dict(size=6),
                        mode='lines+markers+text',
                        textposition='top center',
                        textfont=dict(size=10, color='white'),
                    )
                    fig_dynamics = apply_chart_background(fig_dynamics)
                    render_chart(fig_dynamics, caption_below="Динамика выдачи ПД")
        except Exception as e:
            st.error(f"Ошибка при построении графика 'Динамика ПД': {str(e)}")

    if embed_delay_at_end:
        st.divider()
        if page_title == "Проектная документация":
            dashboard_pd_delay(df)
        else:
            dashboard_rd_delay(df)


def dashboard_working_documentation(df):
    """Рабочая документация: основной экран + вкладка «Просрочка выдачи РД» (без отдельного пункта меню)."""
    tab_main, tab_delay = st.tabs(["Рабочая документация", "Просрочка выдачи РД"])
    with tab_main:
        dashboard_documentation(
            df, page_title="Рабочая документация", embed_delay_at_end=False
        )
    with tab_delay:
        dashboard_rd_delay(df)


def dashboard_project_documentation(df):
    """Проектная документация: основной экран + вкладка «Просрочка выдачи РД»."""
    tab_main, tab_delay = st.tabs(["Проектная документация", "Просрочка выдачи РД"])
    with tab_main:
        dashboard_documentation(
            df, page_title="Проектная документация", embed_delay_at_end=False
        )
    with tab_delay:
        dashboard_pd_delay(df)


# ==================== DASHBOARD 8: Budget by Type (Plan/Fact/Reserve) ====================
def dashboard_budget_by_type(df):
    st.header("Бюджет план/факт")
    col1, col2, col3 = st.columns(3)

    with col1:
        if "project name" in df.columns:
            projects = ["Все"] + _unique_project_labels_for_select(df["project name"])
            selected_project = st.selectbox(
                "Фильтр по проекту", projects, key="budget_type_project"
            )
        else:
            selected_project = "Все"
            st.info("Колонка 'project name' не найдена")

    with col2:
        if "section" in df.columns:
            sections = ["Все"] + sorted(df["section"].dropna().unique().tolist())
            selected_section = st.selectbox(
                "Фильтр по этапу", sections, key="budget_type_section"
            )
        else:
            selected_section = "Все"

    # Apply filters
    filtered_df = df.copy()
    if selected_project != "Все" and "project name" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["project name"].map(_project_filter_norm_key)
            == _project_filter_norm_key(selected_project)
        ]
    if selected_section != "Все" and "section" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["section"].astype(str).str.strip()
            == str(selected_section).strip()
        ]
    # Check for budget columns (нормализуем русские названия)
    ensure_budget_columns(filtered_df)
    has_budget = (
        "budget plan" in filtered_df.columns and "budget fact" in filtered_df.columns
    )

    if not has_budget:
        st.warning("Столбцы бюджета (budget plan, budget fact) не найдены в данных.")
        return

    # Остаток = План - Факт; Отклонение = Факт - План (>=0 красный, <0 зелёный)
    filtered_df["budget plan"] = pd.to_numeric(
        filtered_df["budget plan"], errors="coerce"
    )
    filtered_df["budget fact"] = pd.to_numeric(
        filtered_df["budget fact"], errors="coerce"
    )
    filtered_df["Остаток"] = (
        filtered_df["budget plan"] - filtered_df["budget fact"]
    )
    filtered_df["reserve budget"] = (
        filtered_df["budget fact"] - filtered_df["budget plan"]
    )

    # Колонка контрактации для % покрытия контрактами = контрактация / план * 100
    def _find_contract_column(d):
        for cand in ("Контрактация", "контрактация", "Контракт", "contract", "Contract", "Покрытие контрактами"):
            if cand in d.columns:
                return cand
        for col in d.columns:
            c = str(col).lower().strip()
            if "контрактация" in c or "контракт" in c and "план" not in c or "покрытие" in c and "контракт" in c:
                return col
        return None
    contract_col = _find_contract_column(filtered_df)
    if contract_col:
        filtered_df["_contract_numeric"] = pd.to_numeric(
            filtered_df[contract_col], errors="coerce"
        ).fillna(0)
    else:
        filtered_df["_contract_numeric"] = 0

    plan_total_abs = float(filtered_df["budget plan"].fillna(0).sum())
    fact_total_abs = float(filtered_df["budget fact"].fillna(0).sum())
    plan_total_mld = plan_total_abs / 1e9
    fact_total_mld = fact_total_abs / 1e9
    plan_total_mln = plan_total_abs / 1e6
    fact_total_mln = fact_total_abs / 1e6
    fact_share_pct = (fact_total_abs / plan_total_abs * 100.0) if plan_total_abs > 0 else 0.0
    overrun_pct = ((fact_total_abs - plan_total_abs) / plan_total_abs * 100.0) if plan_total_abs > 0 else 0.0
    if overrun_pct > 0:
        fact_tone = "#e74c3c"
    elif overrun_pct >= -20:
        fact_tone = "#f39c12"
    else:
        fact_tone = "#27ae60"

    gauge_max_mld = max(plan_total_mld, fact_total_mld, 0.01)
    gauge_number_format = ".3f" if gauge_max_mld < 0.1 else ".2f"
    metric_unit = "млн" if gauge_max_mld < 0.1 else "млрд"
    plan_metric_value = plan_total_mln if metric_unit == "млн" else plan_total_mld
    fact_metric_value = fact_total_mln if metric_unit == "млн" else fact_total_mld
    metric_decimals = 2 if metric_unit == "млн" else 2

    st.subheader("Сводный дашборд план/факт")
    kpi_gauge_col, kpi_plan_col, kpi_fact_col = st.columns([1.3, 1, 1])
    with kpi_gauge_col:
        fig_kpi = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=fact_total_mld,
                number={
                    "suffix": " млрд",
                    "valueformat": gauge_number_format,
                    "font": {"size": 26, "color": "#f8fbff"},
                },
                gauge={
                    "axis": {"range": [0, gauge_max_mld]},
                    "bar": {"color": fact_tone},
                    "bgcolor": "#d8dde6",
                    "steps": [
                        {
                            "range": [0, gauge_max_mld],
                            "color": "rgba(255,255,255,0.08)",
                        }
                    ],
                },
                title={"text": "Исполнение бюджета"},
            )
        )
        fig_kpi.update_layout(height=220, margin=dict(l=16, r=16, t=48, b=16))
        fig_kpi = apply_chart_background(fig_kpi)
        render_chart(fig_kpi, caption_below="План/факт по бюджету")
    with kpi_plan_col:
        st.metric(
            "Расходы план",
            f"{plan_metric_value:,.{metric_decimals}f} {metric_unit}".replace(",", " "),
        )
        st.caption("Сумма планового бюджета по текущим фильтрам.")
    with kpi_fact_col:
        st.metric(
            "Расходы факт",
            f"{fact_metric_value:,.{metric_decimals}f} {metric_unit}".replace(",", " "),
            delta=f"{overrun_pct:+.1f}%"
        )
        st.caption(
            f"Факт составляет {fact_share_pct:.1f}% от плана. Цвет: зеленый < 80%, оранжевый до +20%, красный выше плана."
        )

    # ========== Таблица: План, Факт, Остаток, Отклонение, % выполнения, % покрытия контрактами ==========
    st.subheader("Таблица: План / Факт / Остаток / Отклонение / % выполнения / % покрытия контрактами")
    if "project name" in filtered_df.columns:
        agg_dict = {
            "budget plan": "sum",
            "budget fact": "sum",
            "Остаток": "sum",
            "reserve budget": "sum",
            "_contract_numeric": "sum",
        }
        table_agg = filtered_df.groupby("project name").agg(agg_dict).reset_index()
    else:
        table_agg = pd.DataFrame(
            [{
                "project name": "Итого",
                "budget plan": filtered_df["budget plan"].sum(),
                "budget fact": filtered_df["budget fact"].sum(),
                "Остаток": filtered_df["Остаток"].sum(),
                "reserve budget": filtered_df["reserve budget"].sum(),
                "_contract_numeric": filtered_df["_contract_numeric"].sum(),
            }]
        )
    table_agg["План, млн руб."] = (table_agg["budget plan"] / 1e6).round(2)
    table_agg["Факт, млн руб."] = (table_agg["budget fact"] / 1e6).round(2)
    table_agg["Остаток, млн руб."] = (table_agg["Остаток"] / 1e6).round(2)
    table_agg["Отклонение, млн руб."] = (table_agg["reserve budget"] / 1e6).round(2)
    # % выполнения = факт/план * 100%
    plan_nonzero = table_agg["budget plan"] != 0
    table_agg["% выполнения"] = ""
    table_agg.loc[plan_nonzero, "% выполнения"] = (
        (table_agg.loc[plan_nonzero, "budget fact"] / table_agg.loc[plan_nonzero, "budget plan"] * 100)
        .round(1)
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
    ) + "%"
    table_agg.loc[~plan_nonzero, "% выполнения"] = "—"
    # % покрытия контрактами = контрактация / план * 100 (всегда выводим колонку)
    table_agg["% покрытия контрактами"] = "—"
    if "_contract_numeric" in table_agg.columns:
        mask = plan_nonzero & (table_agg["_contract_numeric"].notna())
        table_agg.loc[mask, "% покрытия контрактами"] = (
            (table_agg.loc[mask, "_contract_numeric"] / table_agg.loc[mask, "budget plan"] * 100)
            .round(1)
            .astype(str)
            .str.replace(r"\.0$", "", regex=True)
        ) + "%"
    display_cols = ["project name", "План, млн руб.", "Факт, млн руб.", "Остаток, млн руб.", "Отклонение, млн руб.", "% выполнения", "% покрытия контрактами"]
    budget_table_display = table_agg[display_cols].copy()
    budget_table_display = budget_table_display.rename(columns={"project name": "Проект"})
    # Строка «Итого» при группировке по проектам
    if "project name" in table_agg.columns and len(table_agg) > 1:
        plan_total = table_agg["budget plan"].sum()
        fact_total = table_agg["budget fact"].sum()
        contract_total = table_agg["_contract_numeric"].sum() if "_contract_numeric" in table_agg.columns else 0
        total_row = {
            "Проект": "Итого",
            "План, млн руб.": round(plan_total / 1e6, 2),
            "Факт, млн руб.": round(fact_total / 1e6, 2),
            "Остаток, млн руб.": round((plan_total - fact_total) / 1e6, 2),
            "Отклонение, млн руб.": round((fact_total - plan_total) / 1e6, 2),
            "% выполнения": f"{(fact_total / plan_total * 100):.1f}%".replace(".0%", "%") if plan_total != 0 else "—",
            "% покрытия контрактами": f"{(contract_total / plan_total * 100):.1f}%".replace(".0%", "%") if plan_total != 0 else "—",
        }
        budget_table_display = pd.concat([
            budget_table_display,
            pd.DataFrame([total_row]),
        ], ignore_index=True)
    # st.table(style_dataframe_for_dark_theme(
    #     budget_table_display,
    #     finance_deviation_column="Отклонение, млн руб.",
    # ))
    st.markdown(format_dataframe_as_html(budget_table_display), unsafe_allow_html=True)
    render_dataframe_excel_csv_downloads(
        budget_table_display,
        file_stem="budget_plan_fact",
        key_prefix="budget_type",
    )

    # ========== Histogram: Budget by Project and Type ==========
    st.subheader("Гистограмма: Бюджет план/факт/корректировка/отклонение по проектам")

    adjusted_budget_col = None
    if "budget adjusted" in df.columns:
        adjusted_budget_col = "budget adjusted"
    elif "adjusted budget" in df.columns:
        adjusted_budget_col = "adjusted budget"

    show_reserve = st.checkbox(
        "Показать отклонение", value=False, key="budget_show_reserve"
    )
    selected_budget_types = ["Бюджет План", "Бюджет Факт"]
    if adjusted_budget_col:
        selected_budget_types.append("Бюджет Корректировка")
    if show_reserve:
        selected_budget_types.append("Отклонение (перерасход)")
        selected_budget_types.append("Отклонение (экономия)")

    # Apply filters for histogram - use filtered_df to respect project filter
    hist_df = filtered_df.copy()

    if selected_section != "Все" and "section" in hist_df.columns:
        hist_df = hist_df[
            hist_df["section"].astype(str).str.strip() == str(selected_section).strip()
        ]

    if hist_df.empty:
        st.info("Нет данных для отображения гистограммы с выбранными фильтрами.")
    else:
        # Convert budget columns to numeric
        hist_df["budget plan"] = pd.to_numeric(
            hist_df["budget plan"], errors="coerce"
        ).fillna(0)
        hist_df["budget fact"] = pd.to_numeric(
            hist_df["budget fact"], errors="coerce"
        ).fillna(0)
        hist_df["reserve budget"] = hist_df["budget fact"] - hist_df["budget plan"]

        # Group by project and aggregate
        if "project name" in hist_df.columns:
            budget_by_project = (
                hist_df.groupby("project name")
                .agg(
                    {
                        "budget plan": "sum",
                        "budget fact": "sum",
                        "reserve budget": "sum",
                    }
                )
                .reset_index()
            )

            # Add adjusted budget if available
            if adjusted_budget_col and adjusted_budget_col in hist_df.columns:
                # Convert to numeric first
                hist_df[adjusted_budget_col] = pd.to_numeric(
                    hist_df[adjusted_budget_col], errors="coerce"
                ).fillna(0)
                budget_by_project["budget adjusted"] = (
                    hist_df.groupby("project name")[adjusted_budget_col].sum().values
                )
            else:
                budget_by_project["budget adjusted"] = 0

            # Transform to long format
            hist_melted = []
            for idx, row in budget_by_project.iterrows():
                project = row["project name"]

                if "Бюджет План" in selected_budget_types:
                    hist_melted.append(
                        {
                            "project name": project,
                            "Тип бюджета": "Бюджет План",
                            "Сумма": row["budget plan"],
                        }
                    )

                if "Бюджет Факт" in selected_budget_types:
                    hist_melted.append(
                        {
                            "project name": project,
                            "Тип бюджета": "Бюджет Факт",
                            "Сумма": row["budget fact"],
                        }
                    )

                if (
                    "Бюджет Корректировка" in selected_budget_types
                    and adjusted_budget_col
                ):
                    hist_melted.append(
                        {
                            "project name": project,
                            "Тип бюджета": "Бюджет Корректировка",
                            "Сумма": row["budget adjusted"],
                        }
                    )

                if "Отклонение (перерасход)" in selected_budget_types and row["reserve budget"] >= 0:
                    hist_melted.append(
                        {
                            "project name": project,
                            "Тип бюджета": "Отклонение (перерасход)",
                            "Сумма": row["reserve budget"],
                        }
                    )
                if "Отклонение (экономия)" in selected_budget_types and row["reserve budget"] < 0:
                    hist_melted.append(
                        {
                            "project name": project,
                            "Тип бюджета": "Отклонение (экономия)",
                            "Сумма": row["reserve budget"],
                        }
                    )

            hist_by_type_df = pd.DataFrame(hist_melted)

            if hist_by_type_df.empty:
                st.info("Нет данных для отображения с выбранными типами бюджета.")
            else:
                # Преобразуем значения в миллионы рублей для отображения на столбцах
                hist_by_type_df["Сумма_млн"] = hist_by_type_df["Сумма"] / 1000000

                # Create histogram
                fig_hist = px.bar(
                    hist_by_type_df,
                    x="project name",
                    y="Сумма",
                    color="Тип бюджета",
                    title=None,
                    labels={"project name": "Проект", "Сумма": "Сумма бюджета (руб.)"},
                    barmode="group",
                    text="Сумма_млн",
                    color_discrete_map={
                        "Бюджет План": "#2E86AB",
                        "Бюджет Факт": "#A23B72",
                        "Бюджет Корректировка": "#F18F01",
                        "Отклонение (перерасход)": "#e74c3c",
                        "Отклонение (экономия)": "#27ae60",
                    },
                )

                # Update layout
                fig_hist.update_layout(
                    xaxis_title="Проект",
                    yaxis_title="Сумма бюджета (руб.)",
                    height=600,
                    xaxis=dict(tickangle=-45, tickfont=dict(size=12)),
                )

                # Add text labels on the edge of bars (в миллионах рублей)
                fig_hist.update_traces(
                    textposition="outside",
                    texttemplate="%{text:.1f} млн руб.",
                    textfont=dict(size=12, color="white"),
                )

                fig_hist = _apply_finance_bar_label_layout(fig_hist)
                fig_hist.update_layout(
                    legend=dict(
                        orientation="v",
                        yanchor="top",
                        y=1,
                        xanchor="left",
                        x=1.02,
                    ),
                    margin=dict(l=56, r=220, t=72, b=120),
                )
                fig_hist = apply_chart_background(fig_hist)
                render_chart(
                    fig_hist,
                    caption_below="Бюджет план/факт/корректировка/отклонение по проектам",
                )

                # Summary table (суммы в млн руб., два знака, подпись в названии колонки)
                st.subheader("Сводная таблица по проектам")
                summary_hist = hist_by_type_df.pivot_table(
                    index="project name",
                    columns="Тип бюджета",
                    values="Сумма",
                    aggfunc="sum",
                    fill_value=0,
                ).reset_index()

                # Переводим в млн руб., два знака после запятой; подпись "млн руб." в названии колонки
                for col in summary_hist.columns:
                    if col != "project name":
                        summary_hist[col] = (
                            (summary_hist[col].astype(float) / 1e6)
                            .round(2)
                            .apply(lambda x: f"{float(x):.2f}" if pd.notna(x) else "0.00")
                        )
                summary_hist = summary_hist.rename(
                    columns={
                        c: f"{c}, млн руб."
                        for c in summary_hist.columns
                        if c != "project name"
                    }
                )

                # st.table(style_dataframe_for_dark_theme(summary_hist))
                st.markdown(format_dataframe_as_html(summary_hist), unsafe_allow_html=True)
                render_dataframe_excel_csv_downloads(
                    summary_hist,
                    file_stem="budget_summary",
                    key_prefix="budget_summary",
                )
        else:
            st.warning(
                "Колонка 'project name' не найдена в данных для построения гистограммы."
            )


# ==================== DASHBOARD 8.1: Budget Old Charts ====================
def dashboard_budget_old_charts(df):
    st.header("БДДС (старые графики)")

    col1, col2, col3 = st.columns(3)

    with col1:
        period_type = st.selectbox(
            "Группировать по", ["Месяц", "Квартал", "Год"], key="budget_old_period"
        )
        period_map = {"Месяц": "Month", "Квартал": "Quarter", "Год": "Year"}
        period_type_en = period_map.get(period_type, "Month")

    with col2:
        if "project name" in df.columns:
            projects = ["Все"] + sorted(df["project name"].dropna().unique().tolist())
            selected_project = st.selectbox(
                "Фильтр по проекту", projects, key="budget_old_project"
            )
        else:
            selected_project = "Все"

    with col3:
        if "section" in df.columns:
            sections = ["Все"] + sorted(df["section"].dropna().unique().tolist())
            selected_section = st.selectbox(
                "Фильтр по этапу", sections, key="budget_old_section"
            )
        else:
            selected_section = "Все"

    # Apply filters
    filtered_df = df.copy()
    if selected_project != "Все" and "project name" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["project name"].astype(str).str.strip()
            == str(selected_project).strip()
        ]
    if selected_section != "Все" and "section" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["section"].astype(str).str.strip()
            == str(selected_section).strip()
        ]
    # Check for budget columns (нормализуем русские названия)
    ensure_budget_columns(filtered_df)
    has_budget = (
        "budget plan" in filtered_df.columns and "budget fact" in filtered_df.columns
    )

    if not has_budget:
        st.warning("Столбцы бюджета (budget plan, budget fact) не найдены в данных.")
        return

    # Determine period column
    if period_type_en == "Month":
        period_col = "plan_month"
        period_label = "Месяц"
    elif period_type_en == "Quarter":
        period_col = "plan_quarter"
        period_label = "Квартал"
    else:
        period_col = "plan_year"
        period_label = "Год"

    if period_col not in filtered_df.columns:
        st.warning(f"Столбец периода '{period_col}' не найден.")
        return

    # Отклонение = факт - план (положительное — перерасход, красный; отрицательное — экономия, зелёный)
    filtered_df["budget plan"] = pd.to_numeric(
        filtered_df["budget plan"], errors="coerce"
    )
    filtered_df["budget fact"] = pd.to_numeric(
        filtered_df["budget fact"], errors="coerce"
    )
    filtered_df["reserve budget"] = (
        filtered_df["budget fact"] - filtered_df["budget plan"]
    )

    # Group by period first to get totals
    budget_by_period = (
        filtered_df.groupby(period_col)
        .agg({"budget plan": "sum", "budget fact": "sum", "reserve budget": "sum"})
        .reset_index()
    )

    budget_by_period[period_col] = budget_by_period[period_col].apply(
        format_period_ru
    )

    # Checkbox to hide/show deviation (default: hidden)
    hide_reserve = st.checkbox(
        "Скрыть отклонение", value=True, key="budget_old_hide_reserve"
    )

    # Transform data to long format - group by budget type
    budget_melted = []
    for idx, row in budget_by_period.iterrows():
        period = row[period_col]
        budget_melted.append(
            {
                period_col: period,
                "Тип бюджета": "Бюджет План",
                "Сумма": row["budget plan"],
            }
        )
        budget_melted.append(
            {
                period_col: period,
                "Тип бюджета": "Бюджет Факт",
                "Сумма": row["budget fact"],
            }
        )
        # Add deviation only if not hidden (split by sign for red/green)
        if not hide_reserve:
            if row["reserve budget"] >= 0:
                budget_melted.append(
                    {
                        period_col: period,
                        "Тип бюджета": "Отклонение (перерасход)",
                        "Сумма": row["reserve budget"],
                    }
                )
            else:
                budget_melted.append(
                    {
                        period_col: period,
                        "Тип бюджета": "Отклонение (экономия)",
                        "Сумма": row["reserve budget"],
                    }
                )

    budget_by_type_df = pd.DataFrame(budget_melted)
    # Суммы в млн руб. (исходные в рублях)
    budget_by_type_df["Сумма"] = (budget_by_type_df["Сумма"] / 1e6).round(2)

    # Visualizations
    col1, col2 = st.columns(2)

    with col1:
        # Stacked area chart showing all budget types
        fig = px.area(
            budget_by_type_df,
            x=period_col,
            y="Сумма",
            color="Тип бюджета",
            title=None,
            labels={period_col: period_label, "Сумма": "Сумма, млн руб."},
            text="Сумма",
            color_discrete_map={
                "Бюджет План": "#2E86AB",
                "Бюджет Факт": "#A23B72",
                "Отклонение (перерасход)": "#e74c3c",
                "Отклонение (экономия)": "#27ae60",
            },
        )
        fig.update_xaxes(tickangle=-45)
        fig.update_traces(textposition="top center")
        fig = apply_chart_background(fig)
        render_chart(fig, caption_below="Бюджет по типам по периоду (накопительно)")

    with col2:
        # Grouped bar chart
        fig = px.bar(
            budget_by_type_df,
            x=period_col,
            y="Сумма",
            color="Тип бюджета",
            title=None,
            labels={period_col: period_label, "Сумма": "Сумма, млн руб."},
            barmode="group",
            text="Сумма",
            color_discrete_map={
                "Бюджет План": "#2E86AB",
                "Бюджет Факт": "#A23B72",
                "Отклонение (перерасход)": "#e74c3c",
                "Отклонение (экономия)": "#27ae60",
            },
        )
        fig.update_xaxes(tickangle=-45)
        fig.update_traces(textposition="outside", textfont=dict(size=14, color="white"))
        fig = _apply_finance_bar_label_layout(fig)
        fig = apply_chart_background(fig)
        render_chart(fig, caption_below="Бюджет по типам по периоду")

    # Line chart comparing all types
    fig = px.line(
        budget_by_type_df,
        x=period_col,
        y="Сумма",
        color="Тип бюджета",
        title=None,
        labels={period_col: period_label, "Сумма": "Сумма, млн руб."},
        markers=True,
        text="Сумма",
        color_discrete_map={
            "Бюджет План": "#2E86AB",
            "Бюджет Факт": "#A23B72",
            "Отклонение (перерасход)": "#e74c3c",
            "Отклонение (экономия)": "#27ae60",
        },
    )
    fig.update_xaxes(tickangle=-45)
    fig.update_traces(textposition="top center")
    fig = apply_chart_background(fig)
    render_chart(fig, caption_below="Сравнение типов бюджета по периоду")

    # Summary metrics (суммы уже в млн руб.)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        total_plan = budget_by_type_df[
            budget_by_type_df["Тип бюджета"] == "Бюджет План"
        ]["Сумма"].sum()
        st.metric("Всего План", f"{total_plan:.2f} млн руб." if pd.notna(total_plan) else "Н/Д")
    with col2:
        total_fact = budget_by_type_df[
            budget_by_type_df["Тип бюджета"] == "Бюджет Факт"
        ]["Сумма"].sum()
        st.metric("Всего Факт", f"{total_fact:.2f} млн руб." if pd.notna(total_fact) else "Н/Д")
    with col3:
        total_dev = (
            budget_by_type_df[
                budget_by_type_df["Тип бюджета"].isin(
                    ["Отклонение (перерасход)", "Отклонение (экономия)"]
                )
            ]["Сумма"].sum()
            if budget_by_type_df["Тип бюджета"].isin(
                ["Отклонение (перерасход)", "Отклонение (экономия)"]
            ).any()
            else 0
        )
        st.metric(
            "Всего Отклонение",
            f"{total_dev:.2f} млн руб." if pd.notna(total_dev) else "Н/Д",
        )
    with col4:
        variance = (
            total_plan - total_fact
            if pd.notna(total_plan) and pd.notna(total_fact)
            else None
        )
        st.metric(
            "Отклонение",
            (
                f"{variance:.2f} млн руб."
                if variance is not None and pd.notna(variance)
                else "Н/Д"
            ),
        )

    # Pivot table for better readability (Сумма уже в млн — budget_by_type_df["Сумма"] = /1e6)
    pivot_table = budget_by_type_df.pivot(
        index=period_col, columns="Тип бюджета", values="Сумма"
    ).fillna(0)

    # Detailed table — суммы в млн руб., два знака, подпись "млн руб." в названии колонки
    st.subheader("Детальная таблица")
    detailed_table = pivot_table.copy()

    # Названия колонок с подписью "млн руб."
    detailed_table = detailed_table.rename(
        columns={c: f"{c}, млн руб." for c in detailed_table.columns}
    )
    # Формат: два знака после запятой
    for col in detailed_table.columns:
        detailed_table[col] = detailed_table[col].apply(
            lambda x: f"{float(x):.2f}" if pd.notna(x) else "0.00"
        )

    st.table(style_dataframe_for_dark_theme(detailed_table))


# ── БДДС прогноз: распределение по месяцам (ТЗ PDF: равномерно или % A/B/C) ──


def _bdds_month_periods_inclusive(start, end):
    """Календарные месяцы от месяца даты «Начало» до месяца «Окончание» включительно."""
    if pd.isna(start) or pd.isna(end):
        return []
    ts = pd.to_datetime(start, errors="coerce", dayfirst=True)
    te = pd.to_datetime(end, errors="coerce", dayfirst=True)
    if pd.isna(ts) or pd.isna(te) or ts > te:
        return []
    cur = pd.Timestamp(ts.year, ts.month, 1)
    end_m = pd.Timestamp(te.year, te.month, 1)
    out = []
    while cur <= end_m:
        out.append(cur.to_period("M"))
        if cur.month == 12:
            cur = pd.Timestamp(cur.year + 1, 1, 1)
        else:
            cur = pd.Timestamp(cur.year, cur.month + 1, 1)
    return out


def _bdds_normalize_abc(a, b, c):
    """A+B+C=100%; при нуле или ошибке — 34/33/33."""
    try:
        x, y, z = float(a), float(b), float(c)
    except (TypeError, ValueError):
        return 34.0, 33.0, 33.0
    s = x + y + z
    if s <= 0:
        return 34.0, 33.0, 33.0
    return 100.0 * x / s, 100.0 * y / s, 100.0 * z / s


def _bdds_distribute_row_uniform(total: float, start, end) -> dict:
    """Равномерно по всем месяцам периода [Начало; Окончание]."""
    months = _bdds_month_periods_inclusive(start, end)
    if not months or total is None or (isinstance(total, float) and pd.isna(total)):
        return {}
    t = float(total)
    if t == 0:
        return {m: 0.0 for m in months}
    per = t / len(months)
    return {m: per for m in months}


def _bdds_distribute_row_abc(total: float, start, end, a, b, c) -> dict:
    """
    % A — в месяце даты «Начало»; % C — в месяце «Окончание»;
    % B — равномерно по месяцам строго между ними; если таких нет — B делится пополам между первым и последним.
    """
    months = _bdds_month_periods_inclusive(start, end)
    if not months or total is None or (isinstance(total, float) and pd.isna(total)):
        return {}
    t = float(total)
    if t == 0:
        return {m: 0.0 for m in months}
    ap, bp, cp = _bdds_normalize_abc(a, b, c)
    ms, me = months[0], months[-1]
    out = {m: 0.0 for m in months}
    out[ms] += t * (ap / 100.0)
    out[me] += t * (cp / 100.0)
    mid_total = t * (bp / 100.0)
    interior = [m for m in months if m > ms and m < me]
    if interior:
        share = mid_total / len(interior)
        for m in interior:
            out[m] += share
    else:
        if len(months) == 1:
            out[ms] += mid_total
        else:
            out[ms] += mid_total / 2.0
            out[me] += mid_total / 2.0
    return out


def _bdds_distribute_row_abc_components(total: float, start, end, a, b, c):
    """
    Те же правила, что и _bdds_distribute_row_abc, но три словаря: доли A, B и C по месяцам (руб.).
    """
    months = _bdds_month_periods_inclusive(start, end)
    if not months or total is None or (isinstance(total, float) and pd.isna(total)):
        return {}, {}, {}
    t = float(total)
    if t == 0:
        z = {m: 0.0 for m in months}
        return z.copy(), z.copy(), z.copy()
    ap, bp, cp = _bdds_normalize_abc(a, b, c)
    ms, me = months[0], months[-1]
    da = {m: 0.0 for m in months}
    db = {m: 0.0 for m in months}
    dc = {m: 0.0 for m in months}
    da[ms] += t * (ap / 100.0)
    dc[me] += t * (cp / 100.0)
    mid_total = t * (bp / 100.0)
    interior = [m for m in months if m > ms and m < me]
    if interior:
        share = mid_total / len(interior)
        for m in interior:
            db[m] += share
    else:
        if len(months) == 1:
            db[ms] += mid_total
        else:
            db[ms] += mid_total / 2.0
            db[me] += mid_total / 2.0
    return da, db, dc


def _bdds_msp_monthly_plan_activity(work_df: pd.DataFrame) -> dict:
    """
    По каждому месяцу — сумма «БДДС план» по строкам, активным в этом месяце (как сводка MSP по пересечению).
    """
    if work_df is None or work_df.empty:
        return {}
    ws = work_df.copy()
    if "plan start" not in ws.columns or "plan end" not in ws.columns or "budget plan" not in ws.columns:
        return {}
    ws["plan start"] = pd.to_datetime(ws["plan start"], errors="coerce", dayfirst=True)
    ws["plan end"] = pd.to_datetime(ws["plan end"], errors="coerce", dayfirst=True)
    ws["budget plan"] = pd.to_numeric(ws["budget plan"], errors="coerce").fillna(0.0)
    all_months = set()
    for _, r in ws.iterrows():
        for m in _bdds_month_periods_inclusive(r["plan start"], r["plan end"]):
            all_months.add(m)
    monthly = {m: 0.0 for m in sorted(all_months)}
    for m in monthly:
        m_start = m.start_time
        m_end = m.end_time
        active = ws[(ws["plan start"] <= m_end) & (ws["plan end"] >= m_start)]
        monthly[m] = float(active["budget plan"].sum())
    return monthly


def compute_bddcs_forecast_monthly(
    work_df: pd.DataFrame,
    distribution_mode: str = "uniform",
    abc_source=None,
    row_modes: Optional[pd.Series] = None,
):
    """
    Возвращает DataFrame: month, bdds_plan_msp, bdds_forecast, bdds_fact;
    при режиме A/B/C — дополнительно bdds_forecast_a, bdds_forecast_b, bdds_forecast_c (руб. по месяцам).
    abc_source: DataFrame с колонками A %, B %, C % (или A_, B_, C_) той же длины, что work_df; иначе 34/33/33.
    row_modes: опционально — для каждой строки «Равномерно» или «% …» (если задано, перекрывает distribution_mode).
    """
    if work_df is None or work_df.empty:
        return pd.DataFrame(), "Нет данных для расчёта прогноза БДДС"
    df = work_df.copy().reset_index(drop=True)
    if abc_source is not None:
        abc_source = abc_source.reset_index(drop=True)
    if row_modes is not None:
        row_modes = row_modes.reset_index(drop=True)
    ensure_budget_columns(df)
    req = ["budget plan", "plan start", "plan end"]
    miss = [c for c in req if c not in df.columns]
    if miss:
        return pd.DataFrame(), f"Отсутствуют колонки: {', '.join(miss)}"
    df["plan start"] = pd.to_datetime(df["plan start"], errors="coerce", dayfirst=True)
    df["plan end"] = pd.to_datetime(df["plan end"], errors="coerce", dayfirst=True)
    df["budget plan"] = pd.to_numeric(df["budget plan"], errors="coerce").fillna(0.0)
    if "budget fact" in df.columns:
        df["budget fact"] = pd.to_numeric(df["budget fact"], errors="coerce").fillna(0.0)
    else:
        df["budget fact"] = 0.0

    mode = (distribution_mode or "uniform").strip().lower()
    use_abc_default = mode in ("abc", "%", "процент", "a/b/c", "a b c")

    def _row_use_abc(pos: int) -> bool:
        if row_modes is None or len(row_modes) <= pos:
            return use_abc_default
        rm = str(row_modes.iloc[pos]).strip()
        sl = rm.casefold()
        if not rm:
            return use_abc_default
        if sl.startswith("%") or "a/b/c" in sl or "распредел" in sl:
            return True
        if "равном" in sl:
            return False
        return use_abc_default

    fc_totals: dict = {}
    fc_totals_a: dict = {}
    fc_totals_b: dict = {}
    fc_totals_c: dict = {}
    fact_totals: dict = {}
    plan_msp = _bdds_msp_monthly_plan_activity(df)
    any_use_abc_components = False

    for pos in range(len(df)):
        r = df.iloc[pos]
        plan_amt = float(r["budget plan"])
        fact_amt = float(r["budget fact"])
        use_abc_row = _row_use_abc(pos)
        if use_abc_row:
            any_use_abc_components = True
        a, b, c = 34.0, 33.0, 33.0
        if use_abc_row and abc_source is not None and len(abc_source) > 0:
            row_abc = abc_source.iloc[min(pos, len(abc_source) - 1)]
            for ca, cb, cc in (
                ("A %", "B %", "C %"),
                ("A, %", "B, %", "C, %"),
                ("A_", "B_", "C_"),
            ):
                if ca in row_abc.index and cb in row_abc.index and cc in row_abc.index:
                    a = row_abc[ca]
                    b = row_abc[cb]
                    c = row_abc[cc]
                    break

        if use_abc_row:
            dp = _bdds_distribute_row_abc(plan_amt, r["plan start"], r["plan end"], a, b, c)
            dfact = _bdds_distribute_row_abc(fact_amt, r["plan start"], r["plan end"], a, b, c)
            da, db, dc = _bdds_distribute_row_abc_components(
                plan_amt, r["plan start"], r["plan end"], a, b, c
            )
            for m, v in da.items():
                fc_totals_a[m] = fc_totals_a.get(m, 0.0) + float(v)
            for m, v in db.items():
                fc_totals_b[m] = fc_totals_b.get(m, 0.0) + float(v)
            for m, v in dc.items():
                fc_totals_c[m] = fc_totals_c.get(m, 0.0) + float(v)
        else:
            dp = _bdds_distribute_row_uniform(plan_amt, r["plan start"], r["plan end"])
            dfact = _bdds_distribute_row_uniform(fact_amt, r["plan start"], r["plan end"])
        for m, v in dp.items():
            fc_totals[m] = fc_totals.get(m, 0.0) + float(v)
        for m, v in dfact.items():
            fact_totals[m] = fact_totals.get(m, 0.0) + float(v)

    all_m = sorted(set(plan_msp.keys()) | set(fc_totals.keys()) | set(fact_totals.keys()))
    if not all_m:
        return pd.DataFrame(), "Нет валидных периодов для распределения БДДС"

    rows = []
    for m in all_m:
        row_out = {
            "month": m,
            "bdds_plan_msp": float(plan_msp.get(m, 0.0)),
            "bdds_forecast": float(fc_totals.get(m, 0.0)),
            "bdds_fact": float(fact_totals.get(m, 0.0)),
        }
        if any_use_abc_components:
            row_out["bdds_forecast_a"] = float(fc_totals_a.get(m, 0.0))
            row_out["bdds_forecast_b"] = float(fc_totals_b.get(m, 0.0))
            row_out["bdds_forecast_c"] = float(fc_totals_c.get(m, 0.0))
        else:
            row_out["bdds_forecast_a"] = 0.0
            row_out["bdds_forecast_b"] = 0.0
            row_out["bdds_forecast_c"] = 0.0
        rows.append(row_out)
    out = pd.DataFrame(rows).sort_values("month").reset_index(drop=True)
    return out, None


# ==================== DASHBOARD: Approved Budget ====================
def calculate_approved_budget(df, rule_name="default"):
    """
    Рассчитывает утвержденный бюджет на основе правил распределения.

    Логика расчета:
    1. Группируем задачи по проекту/разделу/задаче
    2. Для каждой группы находим все месяцы этапа (от минимальной даты начала до максимальной даты окончания)
    3. Для каждого месяца находим все задачи, активные в этом месяце
    4. Суммируем плановый бюджет активных задач - это 100% для месяца
    5. Распределяем эту сумму по правилу между месяцами этапа

    Правила распределения:
    - default: 50% - первый месяц, 45% - равномерно по промежуточным месяцам, 5% - последний месяц

    Args:
        df: DataFrame с данными проектов
        rule_name: название правила из справочника

    Returns:
        DataFrame с распределением утвержденного бюджета по месяцам
    """
    # Справочник правил распределения бюджета
    budget_rules = {
        "default": {
            "first_month_percent": 0.50,  # 50% на первый месяц
            "middle_months_percent": 0.45,  # 45% на промежуточные месяцы
            "last_month_percent": 0.05,  # 5% на последний месяц
            "description": "50% - первый месяц, 45% - равномерно по промежуточным месяцам, 5% - последний месяц",
        }
    }

    # Получаем правило
    if rule_name not in budget_rules:
        rule_name = "default"
    rule = budget_rules[rule_name]

    # Проверяем наличие необходимых колонок
    required_cols = ["budget plan", "plan start", "plan end"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        return (
            pd.DataFrame(),
            f"Отсутствуют необходимые колонки: {', '.join(missing_cols)}",
        )

    # Копируем данные для работы
    work_df = df.copy()

    # Конвертируем даты
    work_df["plan start"] = pd.to_datetime(
        work_df["plan start"], errors="coerce", dayfirst=True
    )
    work_df["plan end"] = pd.to_datetime(
        work_df["plan end"], errors="coerce", dayfirst=True
    )
    work_df["budget plan"] = pd.to_numeric(work_df["budget plan"], errors="coerce")

    # Фильтруем строки с валидными данными
    valid_mask = (
        work_df["plan start"].notna()
        & work_df["plan end"].notna()
        & work_df["budget plan"].notna()
        & (work_df["budget plan"] > 0)
        & (work_df["plan start"] <= work_df["plan end"])
    )
    work_df = work_df[valid_mask].copy()

    if work_df.empty:
        return pd.DataFrame(), "Нет данных с валидными датами и бюджетом"

    # Определяем группировку: группируем по комбинации project + section + task
    # Это позволяет правильно обрабатывать случаи, когда выбраны разные уровни фильтрации
    grouping_cols = []
    if "project name" in work_df.columns:
        grouping_cols.append("project name")
    if "section" in work_df.columns:
        grouping_cols.append("section")
    if "task name" in work_df.columns:
        grouping_cols.append("task name")

    # Если нет колонок для группировки, обрабатываем все задачи вместе
    if not grouping_cols:
        # Создаем фиктивную группу для всех задач
        work_df["_group"] = "all"
        grouping_cols = ["_group"]

    # Список для хранения результатов
    approved_budget_rows = []

    # Группируем задачи
    if grouping_cols:
        grouped = work_df.groupby(grouping_cols)
    else:
        # Если нет колонок для группировки, создаем одну группу
        grouped = [("all", work_df)]

    for group_key, group_df in grouped:
        # Находим минимальную дату начала и максимальную дату окончания для группы
        min_start = group_df["plan start"].min()
        max_end = group_df["plan end"].max()

        if pd.isna(min_start) or pd.isna(max_end):
            continue

        # Генерируем все месяцы этапа
        current_date = min_start.replace(day=1)
        end_month = max_end.replace(day=1)

        months = []
        while current_date <= end_month:
            months.append(current_date.to_period("M"))
            # Переходим к следующему месяцу
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)

        if len(months) == 0:
            continue

        # Для каждого месяца находим активные задачи и суммируем их плановый бюджет
        monthly_budgets = {}
        for month in months:
            month_start = month.start_time
            month_end = month.end_time

            # Находим задачи, активные в этом месяце
            active_tasks = group_df[
                (group_df["plan start"] <= month_end)
                & (group_df["plan end"] >= month_start)
            ]

            # Суммируем плановый бюджет активных задач - это 100% для месяца
            total_budget = active_tasks["budget plan"].sum()
            monthly_budgets[month] = total_budget

        # Рассчитываем распределение бюджета по правилу
        num_months = len(months)

        if num_months == 1:
            # Если только один месяц, весь бюджет идет туда
            first_month_percent = 1.0
            middle_months_percent = 0.0
            last_month_percent = 0.0
        elif num_months == 2:
            # Если два месяца: 50% на первый, 50% на последний
            first_month_percent = rule["first_month_percent"]
            middle_months_percent = 0.0
            last_month_percent = (
                rule["middle_months_percent"] + rule["last_month_percent"]
            )
        else:
            # Если больше двух месяцев: 50% на первый, 45% равномерно на промежуточные, 5% на последний
            first_month_percent = rule["first_month_percent"]
            last_month_percent = rule["last_month_percent"]
            middle_months_percent = rule["middle_months_percent"] / (num_months - 2)

        # Распределяем бюджет по месяцам
        for i, month in enumerate(months):
            # Берем бюджет для этого месяца (100%)
            month_total_budget = monthly_budgets.get(month, 0)

            if month_total_budget == 0:
                continue

            # Определяем процент для этого месяца
            if i == 0:
                # Первый месяц
                month_percent = first_month_percent
            elif i == len(months) - 1:
                # Последний месяц
                month_percent = last_month_percent
            else:
                # Промежуточные месяцы
                month_percent = middle_months_percent

            # Рассчитываем утвержденный бюджет для месяца
            approved_budget = month_total_budget * month_percent

            # Получаем значения группировки
            group_dict = {}
            if grouping_cols:
                if isinstance(group_key, tuple):
                    group_dict = dict(zip(grouping_cols, group_key))
                elif len(grouping_cols) == 1:
                    group_dict = {grouping_cols[0]: group_key}
                else:
                    # Если group_key не кортеж и колонок несколько, возможно это одна группа
                    for col in grouping_cols:
                        if col in group_df.columns:
                            # Берем первое значение из группы
                            group_dict[col] = (
                                group_df[col].iloc[0] if len(group_df) > 0 else ""
                            )

            # Создаем строку с данными
            approved_row = {
                "month": month,
                "approved budget": approved_budget,
                "budget plan": month_total_budget,  # Плановый бюджет для месяца (100%)
                "rule_name": rule_name,
            }

            # Добавляем значения группировки (исключаем фиктивную колонку _group)
            for col in grouping_cols:
                if col != "_group":
                    approved_row[col] = group_dict.get(col, "")

            approved_budget_rows.append(approved_row)

    # Создаем DataFrame из результатов
    if not approved_budget_rows:
        return pd.DataFrame(), "Нет данных для расчета утвержденного бюджета"

    approved_budget_df = pd.DataFrame(approved_budget_rows)

    return approved_budget_df, None


def dashboard_approved_budget(df):
    """Панель для отображения утвержденного бюджета"""
    st.header("Утвержденный бюджет")

    # Фильтры (две колонки: проект, этап) — плотная сетка без «дырок» между колонками
    st.markdown(
        """
        <style>
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="column"]) div[data-testid="column"] {
            flex: 1 1 0% !important;
            min-width: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns(2, gap="small")

    with col1:
        # Check for project column - try English name first (alias from load_data), then Russian
        project_col = None
        if "project name" in df.columns:
            project_col = "project name"
        elif "Проект" in df.columns:
            project_col = "Проект"

        if project_col:
            projects = ["Все"] + _unique_project_labels_for_select(df[project_col])
            selected_project = st.selectbox(
                "Фильтр по проекту", projects, key="approved_budget_project"
            )
        else:
            st.warning("Колонка 'project name' не найдена.")
            selected_project = "Все"

    with col2:
        if "section" in df.columns:
            sections = ["Все"] + sorted(df["section"].dropna().unique().tolist())
            selected_section = st.selectbox(
                "Фильтр по этапу", sections, key="approved_budget_section"
            )
        else:
            selected_section = "Все"

    # Применяем фильтры
    filtered_df = df.copy()
    if selected_project != "Все" and project_col and project_col in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df[project_col].map(_project_filter_norm_key)
            == _project_filter_norm_key(selected_project)
        ]
    if selected_section != "Все" and "section" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["section"].astype(str).str.strip()
            == str(selected_section).strip()
        ]

    if project_col and project_col in filtered_df.columns:
        filtered_df = _project_column_apply_canonical(filtered_df, project_col)

    ensure_budget_columns(filtered_df)
    _proj_key = project_col if project_col and project_col in filtered_df.columns else None
    if (
        _proj_key
        and "budget plan" in filtered_df.columns
        and "budget fact" in filtered_df.columns
    ):
        st.subheader("Детальные данные (таблица)")
        st.caption(
            "По ТЗ: утверждённый бюджет и факт из оборотов; отклонение = план − факт "
            "(красный шрифт при отклонении < 0, зелёный при ≥ 0)."
        )
        _tz = (
            filtered_df.groupby(_proj_key)
            .agg({"budget plan": "sum", "budget fact": "sum"})
            .reset_index()
        )
        _tz["_dev"] = _tz["budget plan"] - _tz["budget fact"]
        _tz_out = pd.DataFrame(
            {
                "Проект": _tz[_proj_key].astype(str),
                "Утверждённый бюджет (план), млн руб.": (_tz["budget plan"] / 1e6).round(2).apply(
                    lambda x: f"{float(x):.2f}" if pd.notna(x) else ""
                ),
                "Фактические расходы, млн руб.": (_tz["budget fact"] / 1e6).round(2).apply(
                    lambda x: f"{float(x):.2f}" if pd.notna(x) else ""
                ),
                "Отклонение, млн руб.": (_tz["_dev"] / 1e6).round(2).apply(
                    lambda x: f"{float(x):.2f}" if pd.notna(x) else ""
                ),
            }
        )
        st.markdown(
            budget_table_to_html(
                _tz_out,
                finance_deviation_column="Отклонение, млн руб.",
                deviation_red_if_negative=True,
            ),
            unsafe_allow_html=True,
        )

    if "budget plan" in filtered_df.columns and "budget fact" in filtered_df.columns:
        _plan_tot = float(pd.to_numeric(filtered_df["budget plan"], errors="coerce").fillna(0.0).sum())
        _fact_tot = float(pd.to_numeric(filtered_df["budget fact"], errors="coerce").fillna(0.0).sum())
        st.subheader("Сводка: бюджет план / факт")
        _pb = _plan_tot / 1e9
        _fb = _fact_tot / 1e9
        _hi = max(_pb, _fb, 1e-9) * 1.08
        if _plan_tot > 0:
            if _fact_tot > _plan_tot:
                _gauge_bar = "#e74c3c"
            elif _fact_tot >= 0.8 * _plan_tot:
                _gauge_bar = "#e67e22"
            else:
                _gauge_bar = "#27ae60"
        else:
            _gauge_bar = "#8892a0"
        _pct_of_plan = (100.0 * _fact_tot / _plan_tot) if _plan_tot > 0 else float("nan")
        _gauge_kw = {
            "axis": {"range": [0.0, float(_hi)]},
            "bar": {"color": _gauge_bar},
            "bgcolor": "rgba(26,28,35,0.85)",
            "borderwidth": 0,
        }
        if _pb > 0:
            _gauge_kw["threshold"] = {
                "line": {"color": "#2E86AB", "width": 3},
                "thickness": 0.82,
                "value": float(_pb),
            }
        _g = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=float(_fb),
                number={"suffix": " млрд", "valueformat": ".2f"},
                title={"text": "Расходы факт (к цели плана)"},
                gauge=_gauge_kw,
            )
        )
        _g = apply_chart_background(_g)
        _gc1, _gc2 = st.columns([1, 1], gap="medium")
        with _gc1:
            render_chart(
                _g,
                height=340,
                caption_below="",
                key=f"approved_budget_gauge_{_project_filter_norm_key(str(selected_project))}",
            )
        with _gc2:
            st.markdown("**Расходы план (все выбранные строки)**")
            st.caption(f"{_pb:.2f} млрд руб. ({_plan_tot/1e6:.2f} млн руб.) — 100%")
            st.markdown("**Расходы факт**")
            if _plan_tot > 0 and np.isfinite(_pct_of_plan):
                st.caption(
                    f"{_fb:.2f} млрд руб. ({_fact_tot/1e6:.2f} млн руб.) — **{_pct_of_plan:.1f}%** от плана"
                )
            else:
                st.caption(f"{_fb:.2f} млрд руб. ({_fact_tot/1e6:.2f} млн руб.)")
            st.caption(
                "Цвет столбца: зелёный — факт ниже 80% плана; оранжевый — от 80% до 100%; красный — выше плана."
            )

    ensure_date_columns(filtered_df)
    if "plan end" in filtered_df.columns:
        plan_end = pd.to_datetime(filtered_df["plan end"], errors="coerce")
        mask = plan_end.notna()
        if mask.any() and "plan_month" not in filtered_df.columns:
            filtered_df.loc[mask, "plan_month"] = plan_end.loc[mask].dt.to_period("M")

    if "budget plan" not in filtered_df.columns or "budget fact" not in filtered_df.columns:
        st.warning("Нет колонок плана/факта бюджета для графика.")
        return

    if "plan_month" not in filtered_df.columns:
        st.info(
            "Для графика «план/факт по месяцам» нужна дата периода (например «Конец план» / plan end) в данных."
        )
        return

    st.subheader("Утверждённый бюджет (план/факт) по месяцам")
    monthly_rows = (
        filtered_df.groupby("plan_month")
        .agg({"budget plan": "sum", "budget fact": "sum"})
        .reset_index()
        .sort_values("plan_month")
    )
    if monthly_rows.empty:
        st.info("Нет строк с периодом для построения графика.")
        return

    monthly_rows["Месяц"] = monthly_rows["plan_month"].apply(format_period_ru)
    monthly_rows["reserve budget"] = monthly_rows["budget fact"] - monthly_rows["budget plan"]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=monthly_rows["Месяц"],
            y=monthly_rows["budget plan"].div(1e6),
            name="БДДС план",
            marker_color="#2E86AB",
            text=_finance_bar_text_mln_rub(monthly_rows["budget plan"]),
            textposition="outside",
            textfont=dict(size=11, color="#f0f4f8"),
            hovertemplate="<b>%{x}</b><br>БДДС план: %{customdata}<extra></extra>",
            customdata=monthly_rows["budget plan"].apply(format_million_rub),
        )
    )
    fig.add_trace(
        go.Bar(
            x=monthly_rows["Месяц"],
            y=monthly_rows["budget fact"].div(1e6),
            name="БДДС факт",
            marker_color="#A23B72",
            text=_finance_bar_text_mln_rub(monthly_rows["budget fact"]),
            textposition="outside",
            textfont=dict(size=11, color="#f0f4f8"),
            hovertemplate="<b>%{x}</b><br>БДДС факт: %{customdata}<extra></extra>",
            customdata=monthly_rows["budget fact"].apply(format_million_rub),
        )
    )
    fig.update_layout(
        title_text="",
        xaxis_title="Месяц",
        yaxis_title="млн руб.",
        barmode="group",
        bargap=0.18,
        bargroupgap=0.08,
        hovermode="x unified",
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,
        ),
        height=600,
        xaxis=dict(tickangle=-45, tickfont=dict(size=9), nticks=18),
        margin=dict(l=56, r=220, t=72, b=120),
    )
    fig = _apply_finance_bar_label_layout(fig)
    if not monthly_rows.empty:
        _ymax = float(
            np.nanmax(
                np.concatenate(
                    [
                        monthly_rows["budget plan"].div(1e6).to_numpy(),
                        monthly_rows["budget fact"].div(1e6).to_numpy(),
                    ]
                )
            )
        )
        if np.isfinite(_ymax) and _ymax > 0:
            fig.update_layout(yaxis=dict(range=[0, _ymax * 1.22]))
    fig = apply_chart_background(fig)
    render_chart(
        fig,
        caption_below="Как в отчёте БДДС: план и факт по месяцам; подписи — сумма и млн руб.",
    )

    st.subheader("Сводная таблица по месяцам")
    summary_table = monthly_rows[
        ["Месяц", "budget plan", "budget fact", "reserve budget"]
    ].copy()
    for c in ("budget plan", "budget fact", "reserve budget"):
        summary_table[c] = (summary_table[c] / 1e6).round(2).apply(
            lambda x: f"{float(x):.2f}" if pd.notna(x) else ""
        )
    summary_table = summary_table.rename(
        columns={
            "budget plan": "БДДС план, млн руб.",
            "budget fact": "БДДС факт, млн руб.",
            "reserve budget": "Отклонение (факт − план), млн руб.",
        }
    )
    st.markdown(
        budget_table_to_html(
            summary_table,
            finance_deviation_column="Отклонение (факт − план), млн руб.",
        ),
        unsafe_allow_html=True,
    )
    render_dataframe_excel_csv_downloads(
        summary_table,
        file_stem="approved_budget_by_month",
        key_prefix="appr_budget_summary",
    )


# ==================== DASHBOARD: Forecast Budget ====================
def calculate_forecast_budget(
    df,
    edited_data=None,
    distribution_mode="uniform",
    abc_source=None,
    row_modes: Optional[pd.Series] = None,
):
    """
    Прогноз БДДС по месяцам: «БДДС план» (сводка по MSP), «БДДС прогноз» (распределение),
    «БДДС факт» (распределение факта по тем же весам).
    """
    work_df = edited_data.copy() if edited_data is not None else df.copy()
    return compute_bddcs_forecast_monthly(
        work_df,
        distribution_mode=distribution_mode,
        abc_source=abc_source,
        row_modes=row_modes,
    )


def _forecast_find_turnover_dataframe():
    """Ищет в session_state DataFrame оборотов 1С (БДДС) по типичным ключам/колонкам."""
    try:
        keys = list(st.session_state.keys())
    except Exception:
        keys = []
    preferred = (
        "budget_1c_data",
        "bddcs_1c",
        "bddcs_turnover",
        "project_budget_1c",
        "dannye_bddcs",
        "turnover_1c",
    )
    for k in preferred:
        if k in keys:
            d = st.session_state.get(k)
            if isinstance(d, pd.DataFrame) and not getattr(d, "empty", True):
                return d
    for k in keys:
        d = st.session_state.get(k)
        if not isinstance(d, pd.DataFrame) or getattr(d, "empty", True):
            continue
        joined = " ".join(str(c).casefold() for c in d.columns)
        if "сценар" in joined and ("сумм" in joined or "amount" in joined):
            if "стать" in joined or "article" in joined or "оборот" in joined:
                return d
    return None


def _forecast_merge_bddcs_from_1c(project_df: pd.DataFrame, project_name: str) -> pd.DataFrame:
    """
    Подставляет суммы план/факт по оборотам 1С: сценарий «Бюджет», статьи без БДР,
    факт — по сценарию «Факт» / «ФАКТ» (если есть).
    Распределение по лотам — пропорционально текущему budget plan в MSP для проекта.
    """
    bdf = _forecast_find_turnover_dataframe()
    if bdf is None or bdf.empty or project_df is None or project_df.empty:
        return project_df
    out = project_df.copy()

    def _col(df, needles):
        cols = {str(c).strip().casefold(): c for c in df.columns}
        for n in needles:
            k = str(n).strip().casefold()
            if k in cols:
                return cols[k]
        for c in df.columns:
            cl = str(c).casefold()
            for n in needles:
                if str(n).casefold() in cl:
                    return c
        return None

    scen = _col(bdf, ("Сценарий", "scenario"))
    art = _col(bdf, ("СтатьяОборотов", "Статья оборотов", "article"))
    amt = _col(bdf, ("Сумма", "amount"))
    proj = _col(bdf, ("Проект", "project"))
    typ = _col(bdf, ("ТипСтатьи", "article_type", "Тип статьи"))
    if not scen or not amt:
        return out

    t = bdf.copy()
    if proj:
        pn = _project_filter_norm_key(project_name)
        t["_pk"] = t[proj].map(_project_filter_norm_key)
        t = t[t["_pk"] == pn]
    if t.empty:
        return out

    def _no_bdr(row) -> bool:
        a = str(row.get(art, "") if art else "").casefold()
        if "(бдр)" in a or a.strip() == "бдр":
            return False
        if typ and typ in row.index:
            tl = str(row.get(typ, "")).casefold()
            if "бдр" in tl and "бддс" not in tl:
                return False
        return True

    t = t[t.apply(_no_bdr, axis=1)]
    if t.empty:
        return out

    sser = t[scen].astype(str)
    plan_mask = sser.str.contains("бюджет", case=False, na=False) | sser.str.contains(
        "budget", case=False, na=False
    )
    fact_mask = sser.str.contains("факт", case=False, na=False) | sser.str.contains(
        "fact", case=False, na=False
    )
    plan_sum = pd.to_numeric(t.loc[plan_mask, amt], errors="coerce").fillna(0.0).sum()
    fact_sum = pd.to_numeric(t.loc[fact_mask, amt], errors="coerce").fillna(0.0).sum()

    w = pd.to_numeric(out.get("budget plan"), errors="coerce").fillna(0.0)
    wsum = float(w.sum())
    if wsum <= 0 and plan_sum > 0:
        w = pd.Series(1.0, index=out.index)
        wsum = float(len(out))
    if wsum > 0 and (plan_sum > 0 or fact_sum > 0):
        out["budget plan"] = w / wsum * float(plan_sum)
        out["budget fact"] = w / wsum * float(fact_sum)
    return out


def dashboard_forecast_budget(df):

    """Панель для отображения и редактирования прогнозного бюджета"""
    st.header("Прогнозный бюджет")

    # Фильтр по проекту (обязательный для прогнозного бюджета)
    # Check English name first (alias created in load_data), then Russian
    project_col = None
    if "project name" in df.columns:
        project_col = "project name"
    elif "Проект" in df.columns:
        project_col = "Проект"

    if not project_col:
        st.warning(
            "Колонка 'project name' не найдена. Необходима для работы с прогнозным бюджетом."
        )
        return

    projects = _unique_project_labels_for_select(df[project_col])
    if not projects:
        st.warning("Проекты не найдены в данных.")
        return

    selected_project = st.selectbox(
        "Выберите проект", projects, key="forecast_budget_project"
    )

    # Фильтруем данные по выбранному проекту
    project_df = df[
        df[project_col].map(_project_filter_norm_key)
        == _project_filter_norm_key(selected_project)
    ].copy()

    if project_df.empty:
        st.info("Нет данных для выбранного проекта.")
        return

    ensure_budget_columns(project_df)
    ensure_date_columns(project_df)
    required_cols = ["budget plan", "plan start", "plan end"]
    missing_cols = [col for col in required_cols if col not in project_df.columns]
    if missing_cols:
        st.warning(f"Отсутствуют необходимые колонки: {', '.join(missing_cols)}")
        return

    if "section" not in project_df.columns:
        project_df["section"] = ""
    if "Название" in project_df.columns and "task name" not in project_df.columns:
        project_df["task name"] = project_df["Название"]
    project_df["section"] = project_df["section"].apply(_clean_display_str)
    if "task name" not in project_df.columns:
        project_df["task name"] = ""

    project_df = _forecast_merge_bddcs_from_1c(project_df, selected_project)

    st.subheader("Редактирование данных задач")
    st.caption(
        "Колонка **Лот** (раньше «Раздел»); даты начала/окончания — из графика MSP (план); "
        "**БДДС план (утверждённый)** подставляется из оборотов 1С при загрузке (сценарий «Бюджет», без БДР) "
        "и распределяется по лотам пропорционально плану MSP. "
        "**Условие распределения**: по умолчанию «Равномерно»; для долей в месяцах начала/середины/окончания — «% распределения» и поля A/B/C (в сумме 100%)."
    )

    def _build_forecast_edit_frame(pdf: pd.DataFrame) -> pd.DataFrame:
        cur = pdf.copy().reset_index(drop=True)
        ps = pd.to_datetime(cur["plan start"], errors="coerce", dayfirst=True)
        pe = pd.to_datetime(cur["plan end"], errors="coerce", dayfirst=True)
        bp = pd.to_numeric(cur["budget plan"], errors="coerce").fillna(0.0)
        if "budget fact" in cur.columns:
            bf = pd.to_numeric(cur["budget fact"], errors="coerce").fillna(0.0)
        else:
            bf = pd.Series(0.0, index=cur.index)
        plan_start_str = ps.dt.strftime("%Y-%m-%d").fillna("")
        plan_end_str = pe.dt.strftime("%Y-%m-%d").fillna("")
        n = len(cur)
        return pd.DataFrame(
            {
                "Лот": cur["section"].astype(str),
                "Условие распределения": ["Равномерно"] * n,
                "План. начало": plan_start_str,
                "План. окончание": plan_end_str,
                "БДДС план (утверждённый), млн руб.": (bp / 1e6).round(4),
                "БДДС факт, млн руб.": (bf / 1e6).round(4),
                "A, %": [34.0] * n,
                "B, %": [33.0] * n,
                "C, %": [33.0] * n,
            }
        )

    _sess_key = f"forecast_edit_v6_{selected_project}"
    if _sess_key not in st.session_state:
        st.session_state[_sess_key] = _build_forecast_edit_frame(project_df)
    elif len(st.session_state[_sess_key]) != len(project_df):
        st.session_state[_sess_key] = _build_forecast_edit_frame(project_df)
    else:
        _ed0 = st.session_state[_sess_key]
        _req_cols = (
            "Лот",
            "Условие распределения",
            "План. начало",
            "План. окончание",
            "БДДС план (утверждённый), млн руб.",
            "БДДС факт, млн руб.",
            "A, %",
            "B, %",
            "C, %",
        )
        if any(c not in _ed0.columns for c in _req_cols):
            st.session_state[_sess_key] = _build_forecast_edit_frame(project_df)

    edit_df = st.session_state[_sess_key].copy()
    if st.button("Сбросить таблицу к данным файла", key=f"forecast_reset_v6_{selected_project}"):
        st.session_state[_sess_key] = _build_forecast_edit_frame(project_df)
        st.rerun()

    _row_px = 44
    _editor_h = max(220, min(560, _row_px * (max(1, len(edit_df)) + 2)))
    _dist_options = ["Равномерно", "% распределения (A/B/C)"]
    _fc = {
        "Лот": st.column_config.TextColumn("Лот", width="medium"),
        "Условие распределения": st.column_config.SelectboxColumn(
            "Условие распределения",
            options=_dist_options,
            required=True,
        ),
        "План. начало": st.column_config.TextColumn(
            "План, начало (MSP)", help="Формат ГГГГ-ММ-ДД — дата начала лота в MSP."
        ),
        "План. окончание": st.column_config.TextColumn(
            "План, окончание (MSP)", help="Формат ГГГГ-ММ-ДД — дата окончания лота в MSP."
        ),
        "БДДС план (утверждённый), млн руб.": st.column_config.NumberColumn(
            "БДДС план (утверждённый), млн", format="%.4f"
        ),
        "БДДС факт, млн руб.": st.column_config.NumberColumn("БДДС факт, млн", format="%.4f"),
        "A, %": st.column_config.NumberColumn("A, %", format="%.2f"),
        "B, %": st.column_config.NumberColumn("B, %", format="%.2f"),
        "C, %": st.column_config.NumberColumn("C, %", format="%.2f"),
    }
    from auth import get_current_user
    _cur_user = get_current_user() or {}
    _can_edit_finance = (_cur_user.get("role") or "") in {"superadmin", "admin", "rp", "financier"}
    if not _can_edit_finance:
        st.info("Редактирование финансовых таблиц доступно только ролям РП, финансист и администраторам.")
    edited_df = st.data_editor(
        edit_df,
        num_rows="fixed",
        key=f"forecast_editor_v6_{selected_project}",
        use_container_width=True,
        height=_editor_h,
        column_config=_fc,
        hide_index=True,
        disabled=not _can_edit_finance,
    )
    st.session_state[_sess_key] = edited_df.copy()

    updated_data = project_df.copy().reset_index(drop=True)
    ed = edited_df.reset_index(drop=True)
    if len(updated_data) != len(ed):
        st.error("Несовпадение числа строк таблицы и данных проекта.")
        return
    updated_data["plan start"] = pd.to_datetime(ed["План. начало"], errors="coerce", dayfirst=True)
    updated_data["plan end"] = pd.to_datetime(ed["План. окончание"], errors="coerce", dayfirst=True)
    updated_data["section"] = ed["Лот"].map(_clean_display_str)
    updated_data["budget plan"] = (
        pd.to_numeric(ed["БДДС план (утверждённый), млн руб."], errors="coerce").fillna(0.0) * 1e6
    )
    updated_data["budget fact"] = (
        pd.to_numeric(ed["БДДС факт, млн руб."], errors="coerce").fillna(0.0) * 1e6
    )

    row_modes = ed["Условие распределения"].astype(str)
    abc_src = ed[["A, %", "B, %", "C, %"]].copy()
    sums = abc_src.sum(axis=1)
    if (sums - 100).abs().max() > 0.5 and row_modes.astype(str).str.contains("%", na=False).any():
        st.warning(
            "Сумма A+B+C по строкам с «% распределения» должна быть **100%** (допуск ±0.5%). "
            "Значения будут автоматически нормализованы при расчёте."
        )

    forecast_budget_df, error = calculate_forecast_budget(
        df,
        edited_data=updated_data,
        distribution_mode="uniform",
        abc_source=abc_src,
        row_modes=row_modes,
    )

    if error:
        st.error(error)
        return

    if forecast_budget_df.empty:
        st.info("Нет данных для расчёта сводки прогнозного бюджета.")
        return

    mf = forecast_budget_df.sort_values("month").copy()
    mf["Месяц"] = mf["month"].apply(format_period_ru)
    mf["bdds_plan_msp_mln"] = (mf["bdds_plan_msp"] / 1e6).round(4)
    mf["bdds_forecast_mln"] = (mf["bdds_forecast"] / 1e6).round(4)
    mf["bdds_fact_mln"] = (mf["bdds_fact"] / 1e6).round(4)
    for _abc in ("bdds_forecast_a", "bdds_forecast_b", "bdds_forecast_c"):
        if _abc not in mf.columns:
            mf[_abc] = 0.0
    mf["bdds_forecast_a_mln"] = (mf["bdds_forecast_a"] / 1e6).round(4)
    mf["bdds_forecast_b_mln"] = (mf["bdds_forecast_b"] / 1e6).round(4)
    mf["bdds_forecast_c_mln"] = (mf["bdds_forecast_c"] / 1e6).round(4)

    compare_to = st.radio(
        "Отклонение от БДДС прогноз считать к",
        ["БДДС план", "БДДС факт"],
        horizontal=True,
        key=f"forecast_dev_basis_{selected_project}",
    )
    base_col = "bdds_plan_msp" if str(compare_to).strip().startswith("БДДС план") else "bdds_fact"
    mf["_dev"] = mf[base_col] - mf["bdds_forecast"]
    hide_dev = st.checkbox("Скрыть отклонение", value=False, key=f"forecast_hide_dev_{selected_project}")

    st.subheader("Сводная таблица по месяцам (млн руб.)")
    _any_use_abc = bool(row_modes.astype(str).str.contains("%", na=False).any())
    _tot_approved_mln = float(
        pd.to_numeric(ed["БДДС план (утверждённый), млн руб."], errors="coerce").fillna(0.0).sum()
    )
    _tot_fact_mln = float(mf["bdds_fact_mln"].fillna(0.0).sum())
    _period_col = "Месяц"
    summary_numeric = pd.DataFrame(
        {
            _period_col: mf["Месяц"].astype(str),
            "БДДС план": mf["bdds_plan_msp_mln"].astype(float),
            "БДДС факт": mf["bdds_fact_mln"].astype(float),
            "БДДС прогноз": mf["bdds_forecast_mln"].astype(float),
        }
    )
    if _any_use_abc:
        summary_numeric["Прогноз A, млн руб."] = mf["bdds_forecast_a_mln"].astype(float)
        summary_numeric["Прогноз B, млн руб."] = mf["bdds_forecast_b_mln"].astype(float)
        summary_numeric["Прогноз C, млн руб."] = mf["bdds_forecast_c_mln"].astype(float)
    if not hide_dev:
        summary_numeric["Отклонение (база − прогноз), млн руб."] = (mf["_dev"] / 1e6).astype(float)

    _total_row = {
        _period_col: "ИТОГО",
        "БДДС план": _tot_approved_mln,
        "БДДС факт": _tot_fact_mln,
        "БДДС прогноз": _tot_approved_mln,
    }
    if _any_use_abc:
        _total_row["Прогноз A, млн руб."] = float(mf["bdds_forecast_a_mln"].fillna(0.0).sum())
        _total_row["Прогноз B, млн руб."] = float(mf["bdds_forecast_b_mln"].fillna(0.0).sum())
        _total_row["Прогноз C, млн руб."] = float(mf["bdds_forecast_c_mln"].fillna(0.0).sum())
    if not hide_dev and "Отклонение (база − прогноз), млн руб." in summary_numeric.columns:
        _base_sum = float(mf[base_col].fillna(0.0).sum()) / 1e6
        _fcst_sum = float(mf["bdds_forecast"].fillna(0.0).sum()) / 1e6
        _total_row["Отклонение (база − прогноз), млн руб."] = _base_sum - _fcst_sum
    summary_numeric = pd.concat([summary_numeric, pd.DataFrame([_total_row])], ignore_index=True)

    _prev_key = f"forecast_summary_prev_v6_{selected_project}"
    _color_cols = [c for c in summary_numeric.columns if c != _period_col]
    _cell_color = pd.DataFrame("", index=summary_numeric.index, columns=summary_numeric.columns)
    _prev = st.session_state.get(_prev_key) or {}
    for _i, _r in summary_numeric.iterrows():
        _pk = str(_r[_period_col])
        _prev_row = _prev.get(_pk) if isinstance(_prev, dict) else None
        if _prev_row is None:
            continue
        for _cn in _color_cols:
            try:
                _cur = float(_r[_cn])
                _old = _prev_row.get(_cn)
                if _old is None or (isinstance(_old, float) and pd.isna(_old)):
                    continue
                _old = float(_old)
                if _cur < _old - 1e-9:
                    _cell_color.at[_i, _cn] = "#6ee7b7"
                elif _cur > _old + 1e-9:
                    _cell_color.at[_i, _cn] = "#f87171"
            except (TypeError, ValueError):
                continue
    try:
        st.session_state[_prev_key] = {
            str(summary_numeric.at[i, _period_col]): {
                c: float(summary_numeric.at[i, c])
                for c in _color_cols
                if pd.notna(summary_numeric.at[i, c])
            }
            for i in summary_numeric.index
        }
    except Exception:
        pass

    summary_table = summary_numeric.copy()
    for c in summary_table.columns:
        if c == _period_col:
            continue
        summary_table[c] = summary_table[c].apply(
            lambda x: f"{float(x):.2f}" if pd.notna(x) else "0.00"
        )
    st.markdown(
        format_dataframe_as_html(summary_table, cell_color=_cell_color),
        unsafe_allow_html=True,
    )
    render_dataframe_excel_csv_downloads(
        summary_table,
        file_stem="forecast_bddcs_summary",
        key_prefix="fcast_summary",
    )

    st.subheader("Детальные строки (лоты) — ввод для расчёта")
    st.markdown(format_dataframe_as_html(edited_df.head(500)), unsafe_allow_html=True)
    render_dataframe_excel_csv_downloads(
        edited_df,
        file_stem="forecast_bddcs_lots",
        key_prefix="fcast_detail",
        csv_label="Скачать CSV (лоты, для Excel)",
    )

    with st.expander(
        "Формирование БДДС прогноза. Порядок расчёта данных",
        expanded=False,
    ):
        st.markdown(
            """
- По каждому **лоту** берутся даты плана из MSP, утверждённый план и факт (обороты 1С при наличии).
- **Равномерно**: сумма лота делится по календарным месяцам между началом и концом.
- **% (A/B/C)**: доли в месяце старта, в промежуточных месяцах и в месяце окончания (нормализация до 100%).
- По месяцам складываются вклады лотов; столбец «БДДС план» в месяце — сводка по MSP (активные лоты); **БДДС прогноз** — после распределения.
- В строке **ИТОГО** план и прогноз совпадают с суммой утверждённого плана по таблице редактирования.
            """.strip()
        )


# ── Предписания: KPI-кружки, легенда и таблица как в Предписания.html (тёмная тема) ──
_PRED_DASH_MOCK_CSS = """
<style>
.pred-kpi-wrap { background:#13151c; border:1px solid #333; border-radius:12px; padding:8px 16px 16px 16px; margin:0; }
.pred-kpi-wrap.pred-kpi-wrap--body { padding-top:14px; }
.pred-kpi-title { font-size:1rem; font-weight:600; color:#fafafa; margin:0 0 12px 0; border-bottom:1px solid #444; padding-bottom:8px; }
.pred-kpi-circles { display:flex; flex-direction:column; gap:14px; }
.pred-kpi-item { display:flex; align-items:center; gap:12px; }
.pred-kpi-circle { width:72px; height:72px; border-radius:50%; display:flex; flex-direction:column; justify-content:center; align-items:center; color:#fff; font-weight:600; flex-shrink:0; box-shadow:0 2px 8px rgba(0,0,0,.35); }
.pred-kpi-circle .n { font-size:22px; line-height:1.1; }
.pred-kpi-circle .s { font-size:9px; opacity:.92; text-transform:uppercase; letter-spacing:.35px; }
.pred-kpi-circle.blue { background:linear-gradient(135deg,#3498db,#2980b9); }
.pred-kpi-circle.green { background:linear-gradient(135deg,#2ecc71,#27ae60); }
.pred-kpi-circle.orange { background:linear-gradient(135deg,#e67e22,#d35400); }
.pred-kpi-circle.red { background:linear-gradient(135deg,#e74c3c,#c0392b); }
.pred-kpi-info h4 { margin:0 0 4px 0; font-size:14px; font-weight:600; color:#fafafa; }
.pred-kpi-info p { margin:0; font-size:12px; color:#a0a0a0; }
.pred-leg { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:8px; padding:8px 12px; background:#1a1c23; border-radius:12px; border:1px solid #444; font-size:13px; color:#e0e0e0; }
.pred-mock-table-wrap { margin-top:4px; overflow-x:auto; border-radius:8px; border:1px solid #444; }
.pred-mock-table-wrap table { width:100%; border-collapse:collapse; font-size:13px; min-width:900px; }
.pred-mock-table-wrap th { text-align:left; padding:10px 12px; background:#1a1c23; color:#fafafa; border-bottom:2px solid #444; font-size:11px; letter-spacing:0.02em; }
.pred-mock-table-wrap td { padding:8px 12px; border-bottom:1px solid #333; color:#e0e0e0; vertical-align:top; }
.pred-mock-table-wrap tr.pred-crit td { background:rgba(231,76,60,0.07); }
.pred-td-contr { font-weight:600; color:#fafafa; background:#1a1c23; }
.pred-td-sub { font-size:11px; color:#8892a0; margin-top:4px; }
.pred-tag { background:#262833; border:1px solid #444; padding:3px 8px; border-radius:20px; font-size:12px; color:#e0e0e0; display:inline-block; }
.pred-days-neg { color:#f87171; font-weight:600; background:rgba(248,113,113,0.12); padding:3px 10px; border-radius:20px; display:inline-block; }
.pred-crit-yes { background:#c0392b; color:#fff; padding:4px 10px; border-radius:20px; font-size:12px; font-weight:500; }
.pred-crit-dash { color:#888; font-size:14px; }
.pred-mock-head { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:12px; }
.pred-mock-title { font-size:1.05rem; font-weight:600; color:#fafafa; }
.pred-mock-sort { font-size:12px; color:#a0a0a0; }
.pred-mock-badge { background:#c0392b; color:#fff; padding:4px 14px; border-radius:20px; font-size:13px; font-weight:500; }
.pred-detail-wrap { overflow-x:auto; border:1px solid #444; border-radius:10px; margin-top:8px; }
.pred-detail-wrap table { width:100%; border-collapse:collapse; min-width:1200px; }
.pred-detail-wrap th { text-align:left; padding:10px 12px; background:#1a1c23; color:#fafafa; border-bottom:2px solid #444; font-size:11px; text-transform:uppercase; }
.pred-detail-wrap th a { color:#fafafa; text-decoration:none; display:inline-flex; gap:6px; align-items:center; }
.pred-detail-wrap th a:hover { color:#93c5fd; }
.pred-sort-icon { color:#8fb4da; font-size:10px; }
.pred-detail-wrap td { padding:9px 12px; border-bottom:1px solid #333; color:#e0e0e0; }
.pred-detail-wrap tr.pred-row-overdue td { background:rgba(255, 111, 145, 0.12); }
.pred-detail-wrap tr.pred-row-resolved td { background:rgba(158, 255, 158, 0.11); }
.pred-detail-wrap tr:hover td { background:rgba(255,255,255,0.04); }
.pred-chip { display:inline-block; padding:3px 8px; border-radius:999px; font-size:12px; font-weight:600; border:1px solid rgba(255,255,255,0.12); }
.pred-chip-overdue { background:rgba(230,126,34,0.18); color:#fdba74; }
.pred-chip-ok { background:rgba(46,204,113,0.18); color:#86efac; }
.pred-chip-neutral { background:rgba(52,152,219,0.18); color:#93c5fd; }
</style>
"""

_PRED_DETAIL_TABLE_COLUMNS = (
    "Статус предписания",
    "Подрядчик",
    "Проект",
    "№ договора",
    "№ документа",
    "№ предписания",
    "Дата выдачи предписания",
    "Блок выдачи предписания",
    "Срок устранения",
    "Фактическая дата устранения предписания",
    "Дней просрочки",
    "Критические предписания",
)

# Заголовки таблицы «Неустраненные предписания» (единые для HTML и полной таблицы)
_PRED_MOCK_TABLE_COLUMNS = (
    "Подрядчик",
    "Проект",
    "№ договора",
    "№ предписания",
    "Срок устранения предписания",
    "Дней просрочки",
    "Критические предписания",
)


def _pred_fmt_days_display(val) -> str:
    """Дни просрочки для таблицы: положительное число дней показываем как −N (как в макете)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    try:
        v = int(round(float(val)))
    except (TypeError, ValueError):
        return str(val).strip()
    if v <= 0:
        return "0" if v == 0 else str(v)
    return f"-{v}"


def _pred_fmt_due(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    dt = pd.to_datetime(val, errors="coerce", dayfirst=True)
    if pd.isna(dt):
        return _clean_display_str(val)
    return dt.strftime("%d.%m.%Y")


def _pred_fmt_num(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)) or str(val).strip() == "":
        return "Без номера"
    try:
        nf = float(val)
        return str(int(nf)) if nf == int(nf) else str(nf).strip()
    except (TypeError, ValueError):
        return str(val).strip()


def _pred_fmt_doc_full(val) -> str:
    """Полный номер документа из файла без приведения к int (сохраняет «12/24», суффиксы)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return "—"
    return s


def _pred_guess_contract_column(df, exclude=None):
    """Если явного столбца договора нет — ищем по подстроке в имени колонки."""
    if df is None or not hasattr(df, "columns"):
        return None
    ex = {str(c).strip().lower() for c in (exclude or []) if c is not None}
    for col in df.columns:
        k = str(col).strip().lower()
        if k in ex:
            continue
        if k in ("contr", "con"):
            continue
        if "подрядчик" in k and "договор" not in k:
            continue
        if "договор" in k or "contract" in k:
            return col
    return None


def _pred_guess_due_column(df, exclude=None):
    """Колонка срока устранения: по подстроке, без дат создания/загрузки; приоритет — «устран», DueDate, deadline."""
    if df is None or not hasattr(df, "columns"):
        return None
    ex = {str(c).strip().lower() for c in (exclude or []) if c is not None}
    scored = []
    for col in df.columns:
        k = str(col).strip().lower()
        if k in ex:
            continue
        if "создан" in k or "creation" in k or "загруз" in k:
            continue
        score = 0
        if "устран" in k:
            score += 6
        kn = k.replace(" ", "")
        if "duedate" in kn or "due_date" in k:
            score += 5
        if "deadline" in k:
            score += 4
        if "контрольный" in k and "срок" in k:
            score += 4
        if "planend" in kn or "plan_end" in k:
            score += 3
        if k == "срок" or (k.startswith("срок ") and "создан" not in k):
            score += 1
        if score > 0:
            scored.append((score, col))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], str(x[1]).lower()))
    return scored[0][1]


def _pred_build_seven_column_df(
    show: pd.DataFrame,
    contr_col,
    obj_col,
    contract_col,
    doc_num_col,
    due_col,
) -> pd.DataFrame:
    """Детальная таблица строго из 7 колонок (как макет), порядок фиксирован; пустые ячейки — «—» или пусто."""
    cols = list(_PRED_MOCK_TABLE_COLUMNS)
    if show is None or show.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for _, row in show.iterrows():
        def _cell(col):
            if not col or col not in show.columns:
                return None
            return row[col]

        sub = _clean_display_str(_cell(contr_col), empty="") if contr_col and contr_col in show.columns else ""
        pod = _clean_display_str(_cell(obj_col), empty="") if obj_col and obj_col in show.columns else ""
        contr_s = sub if sub else "—"
        proj_s = pod if pod else "—"
        dog = _pred_fmt_num(_cell(contract_col)) if contract_col and contract_col in show.columns else "—"
        num = _pred_fmt_num(_cell(doc_num_col)) if doc_num_col and doc_num_col in show.columns else "—"
        due_s = _pred_fmt_due(_cell(due_col)) if due_col and due_col in show.columns else ""
        days = _pred_fmt_days_display(_cell("_overdue_days"))
        cv = _cell("_critical")
        crit = "Критическое" if cv is True else ("—" if cv is False else "")
        rows.append({
            "Подрядчик": contr_s,
            "Проект": proj_s,
            "№ договора": dog,
            "№ предписания": num,
            "Срок устранения предписания": due_s,
            "Дней просрочки": days,
            "Критические предписания": crit,
        })
    return pd.DataFrame(rows, columns=cols)


def _pred_build_detail_table_df(
    show: pd.DataFrame,
    contr_col,
    obj_col,
    contract_col,
    doc_num_col,
    full_doc_col,
    issue_date_col,
    block_col,
    due_col,
    completion_col,
) -> pd.DataFrame:
    if show is None or show.empty:
        return pd.DataFrame(columns=_PRED_DETAIL_TABLE_COLUMNS)
    rows = []
    for _, row in show.iterrows():
        due_raw = row.get(due_col) if due_col and due_col in show.columns else None
        comp_raw = row.get(completion_col) if completion_col and completion_col in show.columns else None
        issue_raw = row.get(issue_date_col) if issue_date_col and issue_date_col in show.columns else None
        block_raw = row.get(block_col) if block_col and block_col in show.columns else None
        critical_raw = row.get("_critical")
        overdue_raw = row.get("_overdue_days")
        resolved_raw = bool(row.get("_resolved", False))
        critical_text = "Да" if bool(critical_raw) else "0"
        try:
            overdue_num = int(round(float(overdue_raw)))
        except (TypeError, ValueError):
            overdue_num = 0
        if full_doc_col and full_doc_col in show.columns:
            doc_full_s = _pred_fmt_doc_full(row.get(full_doc_col))
        elif doc_num_col and doc_num_col in show.columns:
            doc_full_s = _pred_fmt_doc_full(row.get(doc_num_col))
        else:
            doc_full_s = "—"
        rows.append(
            {
                "Статус предписания": _clean_display_str(row.get("Статус"), empty="Неизвестно"),
                "Подрядчик": _clean_display_str(row.get(contr_col), empty="—") if contr_col and contr_col in show.columns else "—",
                "Проект": _clean_display_str(row.get(obj_col), empty="—") if obj_col and obj_col in show.columns else "—",
                "№ договора": _pred_fmt_num(row.get(contract_col)) if contract_col and contract_col in show.columns else "Без номера",
                "№ документа": doc_full_s,
                "№ предписания": _pred_fmt_num(row.get(doc_num_col)) if doc_num_col and doc_num_col in show.columns else "Без номера",
                "Дата выдачи предписания": _pred_fmt_due(issue_raw),
                "Блок выдачи предписания": _clean_display_str(block_raw, empty="—"),
                "Срок устранения": _pred_fmt_due(due_raw),
                "Фактическая дата устранения предписания": _pred_fmt_due(comp_raw),
                "Дней просрочки": str(max(overdue_num, 0)),
                "Критические предписания": critical_text,
                "_resolved_flag": "1" if resolved_raw else "",
            }
        )
    df_out = pd.DataFrame(rows)
    ordered = list(_PRED_DETAIL_TABLE_COLUMNS) + ["_resolved_flag"]
    for c in ordered:
        if c not in df_out.columns:
            df_out[c] = ""
    return df_out[ordered]


def _pred_overdue_mock_table_html(rows: list, overdue_total: int) -> str:
    """Таблица просроченных как в макете: rowspan по подрядчику, бейджи «Критическое», дни со знаком −."""
    esc = html_module.escape
    head = (
        '<div class="pred-mock-head"><div>'
        f'<div class="pred-mock-title">{esc("Неустраненные предписания")}</div>'
        f'<div class="pred-mock-sort">{esc("Сортировка: по подрядчикам ↑, по просрочке ↓, критические вверху")}</div>'
        "</div>"
        f'<span class="pred-mock-badge">{esc(str(overdue_total))} просроченных</span></div>'
    )
    if not rows:
        return _PRED_DASH_MOCK_CSS + head + f'<p style="color:#a0a0a0;padding:16px;">{esc("Нет просроченных предписаний")}</p>'

    thead = (
        "<thead><tr>"
        + "".join(f"<th>{esc(h)}</th>" for h in _PRED_MOCK_TABLE_COLUMNS)
        + "</tr></thead>"
    )
    parts = [_PRED_DASH_MOCK_CSS, head, '<div class="pred-mock-table-wrap"><table>', thead, "<tbody>"]
    for block in rows:
        contr = esc(str(block["contractor"]))
        rowspan = int(block["rowspan"])
        sub = esc(block["subline"])
        for i, r in enumerate(block["lines"]):
            cr = "pred-crit" if r.get("critical") else ""
            parts.append(f'<tr class="{cr}">')
            if i == 0:
                parts.append(
                    f'<td class="pred-td-contr" rowspan="{rowspan}">{contr}'
                    f'<div class="pred-td-sub">{sub}</div></td>'
                )
            parts.append(f'<td><span class="pred-tag">{esc(r["project"])}</span></td>')
            parts.append(f'<td><span class="pred-tag">{esc(r["contract"])}</span></td>')
            parts.append(f"<td>{esc(r['number'])}</td>")
            parts.append(f"<td>{esc(r['due'])}</td>")
            days = int(r["days"]) if pd.notna(r.get("days")) else 0
            parts.append(f'<td><span class="pred-days-neg">-{esc(str(days))}</span></td>')
            if r.get("critical"):
                parts.append(f'<td><span class="pred-crit-yes">{esc("Критическое")}</span></td>')
            else:
                parts.append('<td><span class="pred-crit-dash">—</span></td>')
            parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _pred_kpi_circles_html(
    total_count: int,
    n_unresolved: int,
    n_resolved: int,
    n_overdue: int,
    n_critical: int,
    *,
    with_heading: bool = True,
) -> str:
    """with_heading=False — заголовок «Ключевые показатели» выводится через st.subheader (ровная строка с левым блоком)."""
    e = html_module.escape
    title_html = (
        '<div class="pred-kpi-title">🎯 Ключевые показатели</div>'
        if with_heading
        else ""
    )
    wrap_cls = "pred-kpi-wrap" + (" pred-kpi-wrap--body" if not with_heading else "")
    return (
        _PRED_DASH_MOCK_CSS
        + f'<div class="{wrap_cls}">'
        + title_html
        + '<div class="pred-kpi-circles">'
        + '<div class="pred-kpi-item"><div class="pred-kpi-circle blue"><span class="n">'
        + e(str(total_count))
        + '</span><span class="s">всего</span></div><div class="pred-kpi-info"><h4>Всего предписаний</h4><p>Все записи в выборке</p></div></div>'
        + '<div class="pred-kpi-item"><div class="pred-kpi-circle blue"><span class="n">'
        + e(str(n_unresolved))
        + '</span><span class="s">всего</span></div><div class="pred-kpi-info"><h4>Неустраненные предписания</h4><p>Общее количество</p></div></div>'
        + '<div class="pred-kpi-item"><div class="pred-kpi-circle green"><span class="n">'
        + e(str(n_resolved))
        + '</span><span class="s">всего</span></div><div class="pred-kpi-info"><h4>Устраненные предписания</h4><p>Закрыты или устранены</p></div></div>'
        + '<div class="pred-kpi-item"><div class="pred-kpi-circle orange"><span class="n">'
        + e(str(n_overdue))
        + '</span><span class="s">всего</span></div><div class="pred-kpi-info"><h4>Просроченные предписания</h4><p>Требуют немедленного внимания</p></div></div>'
        + '<div class="pred-kpi-item"><div class="pred-kpi-circle red"><span class="n">'
        + e(str(n_critical))
        + '</span><span class="s">всего</span></div><div class="pred-kpi-info"><h4>Критические предписания</h4><p>Просрочка более 30 дней</p></div></div>'
        + "</div></div>"
    )


def _pred_query_param_value(name: str, default: str = "") -> str:
    try:
        val = st.query_params.get(name, default)
    except Exception:
        return default
    if isinstance(val, list):
        return str(val[0]) if val else default
    return str(val)


def _pred_sort_link(column: str, current_sort: str, current_order: str) -> str:
    next_order = "desc" if current_sort == column and current_order == "asc" else "asc"
    params = {}
    try:
        params.update(st.query_params.to_dict())
    except Exception:
        pass
    params["pred_sort"] = column
    params["pred_order"] = next_order
    return "?" + urlencode(params, doseq=True)


def _pred_sort_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(range(len(df)), index=df.index)
    if column in {
        "Дата выдачи предписания",
        "Срок устранения",
        "Фактическая дата устранения предписания",
    }:
        return pd.to_datetime(df[column], errors="coerce", dayfirst=True)
    if column in {"Дней просрочки"}:
        return (
            df[column]
            .astype(str)
            .str.extract(r"(-?\d+)", expand=False)
            .pipe(pd.to_numeric, errors="coerce")
        )
    return df[column].astype(str).str.casefold()


def _pred_sort_table_df(df: pd.DataFrame, sort_col: str, sort_order: str) -> pd.DataFrame:
    if df is None or df.empty or sort_col not in df.columns:
        return df
    work = df.copy()
    work["_pred_sort_key"] = _pred_sort_series(work, sort_col)
    asc = str(sort_order).lower() != "desc"
    work = work.sort_values(
        by=["_pred_sort_key", sort_col],
        ascending=[asc, asc],
        na_position="last",
        kind="mergesort",
    )
    return work.drop(columns=["_pred_sort_key"], errors="ignore")


def _pred_status_chip_html(status: str, overdue_days, resolved: bool) -> str:
    esc = html_module.escape
    s = str(status or "").strip() or "Неизвестно"
    if resolved:
        return f'<span class="pred-chip pred-chip-ok">{esc(s)}</span>'
    if pd.notna(pd.to_numeric(overdue_days, errors="coerce")) and float(pd.to_numeric(overdue_days, errors="coerce")) > 0:
        return f'<span class="pred-chip pred-chip-overdue">{esc(s)}</span>'
    return f'<span class="pred-chip pred-chip-neutral">{esc(s)}</span>'


def _pred_detail_table_html(
    df: pd.DataFrame,
    *,
    sort_col: str = "",
    sort_order: str = "asc",
    max_rows: int = 700,
) -> str:
    esc = html_module.escape
    if df is None or df.empty:
        return f'<p style="color:#a0a0a0;padding:16px;">{esc("Нет строк для отображения.")}</p>'
    show = df.head(max_rows)
    render_cols = [c for c in show.columns if c != "_resolved_flag"]
    parts = ['<div class="pred-detail-wrap"><table><thead><tr>']
    for col in render_cols:
        marker = "↕"
        if sort_col == col:
            marker = "↑" if str(sort_order).lower() == "asc" else "↓"
        link = _pred_sort_link(col, sort_col, sort_order)
        parts.append(
            f'<th><a href="{esc(link, quote=True)}">{esc(col)} <span class="pred-sort-icon">{esc(marker)}</span></a></th>'
        )
    parts.append("</tr></thead><tbody>")
    for _, row in show.iterrows():
        is_resolved = str(row.get("_resolved_flag", "")).strip() == "1"
        overdue_days = pd.to_numeric(row.get("Дней просрочки"), errors="coerce")
        tr_cls = "pred-row-resolved" if is_resolved else ("pred-row-overdue" if pd.notna(overdue_days) and float(overdue_days) > 0 else "")
        parts.append(f'<tr class="{tr_cls}">')
        for col in render_cols:
            val = row.get(col, "")
            if pd.isna(val):
                val = ""
            if col == "Статус предписания":
                inner = _pred_status_chip_html(str(val), row.get("Дней просрочки"), is_resolved)
            else:
                inner = esc(str(val))
            parts.append(f"<td>{inner}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _pred_build_overdue_mock_blocks(
    overdue_df: pd.DataFrame,
    contr_col,
    obj_col,
    contract_col,
    doc_num_col,
    due_col,
) -> list:
    """Строки для HTML-таблицы просроченных: группировка по подрядчику (rowspan)."""
    if overdue_df is None or overdue_df.empty:
        return []
    sort_cols = ["_critical", "_overdue_days"]
    asc_crit = [False, False]
    if contr_col and contr_col in overdue_df.columns:
        d = overdue_df.sort_values([contr_col] + sort_cols, ascending=[True] + asc_crit).copy()
    else:
        d = overdue_df.sort_values(sort_cols, ascending=asc_crit).copy()

    def _line_from_row(r):
        proj = "—"
        if obj_col and obj_col in d.columns:
            proj = _clean_display_str(r.get(obj_col), empty="—") or "—"
        cnum = "—"
        if contract_col and contract_col in d.columns:
            cnum = _pred_fmt_num(r.get(contract_col))
        num = "—"
        if doc_num_col and doc_num_col in d.columns:
            num = _pred_fmt_num(r.get(doc_num_col))
        due_s = ""
        if due_col and due_col in d.columns:
            due_s = _pred_fmt_due(r.get(due_col))
        od = r.get("_overdue_days")
        try:
            days = int(od) if pd.notna(od) else 0
        except (TypeError, ValueError):
            days = 0
        crit = bool(r.get("_critical"))
        return {
            "project": proj,
            "contract": cnum,
            "number": num,
            "due": due_s,
            "days": days,
            "critical": crit,
        }

    blocks = []
    if contr_col and contr_col in d.columns:
        for contr, g in d.groupby(contr_col, sort=False):
            lines = [_line_from_row(r) for _, r in g.iterrows()]
            if not lines:
                continue
            crit_n = sum(1 for ln in lines if ln.get("critical"))
            sub = f"всего: {len(lines)} | крит: {crit_n}"
            blocks.append({
                "contractor": str(contr).strip() or "—",
                "rowspan": len(lines),
                "subline": sub,
                "lines": lines,
            })
    else:
        lines = [_line_from_row(r) for _, r in d.iterrows()]
        if lines:
            crit_n = sum(1 for ln in lines if ln.get("critical"))
            blocks.append({
                "contractor": "—",
                "rowspan": len(lines),
                "subline": f"всего: {len(lines)} | крит: {crit_n}",
                "lines": lines,
            })
    return blocks


_KIND_ID_CRITICAL = "347986da-8964-4307-8973-28c22842005c"


def _pred_dedupe_by_docid(pred: pd.DataFrame, pred_doc_col: str | None, creation_col_pred: str | None) -> pd.DataFrame:
    """Одна строка на DocID — убирает дубли от нескольких выгрузок в сессию."""
    if pred is None or getattr(pred, "empty", True) or not pred_doc_col or pred_doc_col not in pred.columns:
        return pred
    p = pred.copy()
    m = p[pred_doc_col].notna() & (p[pred_doc_col].astype(str).str.strip() != "")
    p_ok = p.loc[m]
    p_bad = p.loc[~m]
    if not p_ok.empty:
        if creation_col_pred and creation_col_pred in p_ok.columns:
            p_ok = p_ok.sort_values(creation_col_pred, na_position="last", kind="stable")
        p_ok = p_ok.drop_duplicates(subset=[pred_doc_col], keep="first")
    out = pd.concat([p_ok, p_bad], ignore_index=True)
    return out


def _pred_merge_completion_from_tasks(
    pred: pd.DataFrame,
    card_col: str | None,
    doc_col: str | None,
) -> pd.DataFrame:
    """
    Факт устранения из tessa_*task*.csv: TypeCaption «Проверка», OptionCaption «Принято» → Completed.
    Сопоставление по CardId / DocID с идентификаторами в карточке предписания.
    """
    out = pred.copy()
    out["_completion_from_task"] = pd.Series(pd.NaT, index=out.index)
    try:
        tasks = st.session_state.get("tessa_tasks_data")
    except Exception:
        tasks = None
    if tasks is None or getattr(tasks, "empty", True):
        return out
    t = tasks.copy()
    t.columns = [str(c).strip() for c in t.columns]
    tc = _tessa_find_column(t, ["TypeCaption", "typecaption", "TaskTypeCaption"])
    oc = _tessa_find_column(t, ["OptionCaption", "optioncaption", "Option"])
    comp = _tessa_find_column(t, ["Completed", "CompletionDate", "ДатаЗавершения", "Дата завершения"])
    cid = _tessa_find_column(t, ["CardId", "CardID", "cardId", "ИдКарточки"])
    if not (tc and oc and comp and cid):
        return out
    sub = t[
        t[tc].astype(str).str.strip().str.casefold().eq("проверка")
        & t[oc].astype(str).str.strip().str.casefold().eq("принято")
    ].copy()
    sub[comp] = pd.to_datetime(sub[comp], errors="coerce", dayfirst=True)
    sub = sub[sub[comp].notna()]
    if sub.empty:
        return out
    agg = sub.groupby(cid, dropna=False)[comp].min()
    mp: dict = {}
    for raw_k, dt in zip(agg.index.tolist(), agg.values.tolist()):
        nk = _tessa_norm_join_key(raw_k)
        if not nk:
            continue
        if nk not in mp or (pd.notna(dt) and (pd.isna(mp[nk]) or dt < mp[nk])):
            mp[nk] = dt

    def _pick(row) -> object:
        for c in (card_col, doc_col):
            if c and c in out.columns:
                nk = _tessa_norm_join_key(row.get(c))
                if nk and nk in mp:
                    return mp[nk]
        return pd.NaT

    out["_completion_from_task"] = out.apply(_pick, axis=1)
    return out


def _tessa_fill_card_from_doc_lookup(df: pd.DataFrame) -> pd.DataFrame:
    """
    TESSA: строки карточки (DocID) и задачи (CardId) с одним идентификатором — объединяем поля.

    1) Ключ нормализуется (83, 83.0, «83» совпадают).
    2) По каждому ключу собираем «лучшие» непустые значения по всем строкам с этим ключом
       (не только строки «только DocID» — иначе договор/срок не подтягиваются, если CardId везде заполнен).
    3) Вторым проходом заполняем пустые ячейки из агрегата.
    """
    if df is None or df.empty:
        return df
    doc_col = _tessa_find_column(
        df,
        ["DocID", "DocId", "DocumentID", "DocumentId", "ИдДокумента", "Ид документа", "ИдентификаторДокумента"],
    )
    card_col = _tessa_find_column(
        df,
        ["CardId", "CardID", "cardId", "ИдКарточки", "ИдЗадачи", "TaskCardId", "CardIDЗадачи"],
    )
    if not doc_col and not card_col:
        return df
    if doc_col and card_col and str(doc_col) == str(card_col):
        return df
    out = df.copy()
    join_keys = [_tessa_row_join_key(out.loc[i], doc_col, card_col) for i in out.index]
    out["_join_key_tmp"] = join_keys
    merged_by_key: dict = {}
    for _, row in out.iterrows():
        k = row["_join_key_tmp"]
        if not k:
            continue
        if k not in merged_by_key:
            merged_by_key[k] = {}
        tgt = merged_by_key[k]
        for col in out.columns:
            if col == "_join_key_tmp":
                continue
            v = row[col]
            if not _tessa_cell_has_value(v):
                continue
            if col not in tgt or not _tessa_cell_has_value(tgt.get(col)):
                tgt[col] = v
    for idx, row in out.iterrows():
        k = row["_join_key_tmp"]
        if not k or k not in merged_by_key:
            continue
        src = merged_by_key[k]
        for col, v in src.items():
            if col == "_join_key_tmp":
                continue
            cur = out.at[idx, col]
            if _tessa_cell_has_value(cur):
                continue
            if _tessa_cell_has_value(v):
                out.at[idx, col] = v
        if doc_col and doc_col in out.columns and not _tessa_cell_has_value(out.at[idx, doc_col]) and k:
            out.at[idx, doc_col] = k
    out = out.drop(columns=["_join_key_tmp"], errors="ignore")
    return out


def _rd_tessa_task_display_series(msp_df: pd.DataFrame, task_col: str | None) -> pd.Series | None:
    """
    Подпись задачи для РД: при наличии `tessa_tasks_data` в session_state подставляет наименование из TESSA
    (совпадение по CardId / Task ID / точному названию).
    """
    if msp_df is None or getattr(msp_df, "empty", True) or not task_col or task_col not in msp_df.columns:
        return None
    try:
        tdf = st.session_state.get("tessa_tasks_data")
    except Exception:
        tdf = None
    if tdf is None or getattr(tdf, "empty", True):
        return None
    t = tdf.copy()
    t.columns = [str(c).strip() for c in t.columns]
    try:
        t = _tessa_fill_card_from_doc_lookup(t)
    except Exception:
        pass
    name_col = _tessa_find_column(
        t,
        [
            "TaskName",
            "Task Name",
            "Name",
            "Название",
            "Наименование",
            "Title",
            "Задача",
            "Subject",
            "Тема",
        ],
    )
    if not name_col or name_col not in t.columns:
        return None
    card_col = _tessa_find_column(
        t, ["CardId", "CardID", "ИдЗадачи", "ИдКарточки", "TaskCardId"]
    )
    lk: dict[str, str] = {}
    for _, r in t.iterrows():
        nm = str(r[name_col]).strip() if _tessa_cell_has_value(r.get(name_col)) else ""
        if not nm:
            continue
        keys = set()
        keys.add(nm.casefold())
        if card_col and card_col in t.columns and _tessa_cell_has_value(r.get(card_col)):
            keys.add(_tessa_norm_join_key(r[card_col]).casefold())
        for k in keys:
            if k and k not in lk:
                lk[k] = nm
    tid_col = _tessa_find_column(
        msp_df,
        ["Task ID", "task id", "TaskID", "ИдЗадачи", "CardId", "External Task Id", "ExternalTaskId"],
    )
    out: list[str] = []
    for _, row in msp_df.iterrows():
        base = str(row[task_col]).strip() if pd.notna(row.get(task_col)) else ""
        hit = ""
        alt_keys: list[str] = []
        if base:
            alt_keys.append(base.casefold())
        if tid_col and tid_col in msp_df.columns and _tessa_cell_has_value(row.get(tid_col)):
            alt_keys.append(_tessa_norm_join_key(row[tid_col]).casefold())
        for ck in alt_keys:
            if ck and ck in lk:
                hit = lk[ck]
                break
        if not hit and base:
            bf = base.casefold()
            for k, v in lk.items():
                if bf == k or (len(bf) > 6 and (bf in k or k in bf)):
                    hit = v
                    break
        out.append(hit if hit else base)
    return pd.Series(out, index=msp_df.index, dtype=object)


# ==================== DASHBOARD: Неустраненные предписания (TESSA) ====================
def dashboard_predpisania(df):
    """
    Отчёт «Неустраненные предписания» — TESSA, KindName содержит «Предписан»; устранение: KrStateID=13 («Снято»).
    Оформление в общей тёмной теме дашборда (как остальные отчёты).
    """
    st.header("Неустраненные предписания")
    st.caption(
        "Данные TESSA, виды «Предписание». Поля «№ договора» и «Срок устранения» ищутся по типовым именам "
        "(ContractNumber, DueDate и др.); при раздельных файлах Id (DocID) и Tasks (CardId) строки задач "
        "дополняются полями карточки, если CardId совпадает с DocID."
    )

    tessa_df = st.session_state.get("tessa_data", None)
    if tessa_df is None or tessa_df.empty:
        st.warning("Для отчёта необходимы данные из TESSA. Загрузите файлы tessa_*.csv.")
        return

    work = tessa_df.copy()
    work.columns = [str(c).strip() for c in work.columns]
    work = _tessa_fill_card_from_doc_lookup(work)

    kind_col = _tessa_find_column(work, ["KindName", "kindname", "Вид"])
    if kind_col:
        _kind_series = work[kind_col].astype(str).str.strip().str.casefold()
        pred = work[
            _kind_series.eq("предписания")
            | _kind_series.eq("предписание")
            | _kind_series.str.startswith("предпис")
        ].copy()
    else:
        pred = pd.DataFrame()

    if pred.empty:
        st.info("Нет данных по предписаниям в загруженных файлах TESSA.")
        return

    obj_col = _tessa_find_column(pred, ["ObjectName", "objectname", "Объект", "ProjectName", "Проект"])
    if obj_col:
        pred = pred[
            pred[obj_col].notna()
            & (~pred[obj_col].astype(str).str.strip().isin(["", "nan", "None", "NaN"]))
        ].reset_index(drop=True)

    if pred.empty:
        st.info("Нет предписаний с заполненным объектом/проектом.")
        return

    pred_project_options = (
        _unique_project_labels_for_select(pred[obj_col])
        if obj_col and obj_col in pred.columns
        else []
    )

    # Повторно объединяем по ключу уже внутри выборки «предписания» (договор/срок могли быть только в других строках)
    pred = _tessa_fill_card_from_doc_lookup(pred)
    pred_doc_col = _tessa_find_column(
        pred, ["DocID", "DocId", "DocumentID", "DocumentId", "Id", "ID"]
    )
    pred_card_col = _tessa_find_column(
        pred, ["CardId", "CardID", "cardId", "TaskCardId", "ИдКарточки"]
    )

    krstates_df = st.session_state.get("reference_krstates", None)
    status_map = {}
    if krstates_df is not None and not krstates_df.empty:
        for _, row in krstates_df.iterrows():
            name = str(row.get("Название", "")).strip()
            ru = str(row.get("ru", "")).strip()
            if name and ru:
                status_map[name] = ru
    if "KrState" in pred.columns:
        pred["Статус"] = pred["KrState"].apply(
            lambda x: status_map.get(str(x).strip(), str(x).strip()) if pd.notna(x) else "Неизвестно"
        )
    else:
        pred["Статус"] = "Неизвестно"
    _st_stat = pred["Статус"].astype(str).str.strip()
    pred = pred[
        ~(_st_stat.str.casefold().eq("проект") | _st_stat.str.fullmatch(r"\s*Проект\s*", case=False, na=False))
    ].copy()

    contr_col = _tessa_find_column(pred, ["CONTR", "Контрагент", "contr"])
    curator_col = _tessa_find_column(
        pred,
        [
            "Supervisor",
            "Curator",
            "Куратор",
            "КураторПроекта",
            "Author",
            "Автор",
            "Ответственный",
            "Responsible",
            "РуководительПроекта",
            "ФИОКуратора",
        ],
    )
    contract_col = _tessa_find_column(
        pred,
        [
            "ContractNumber",
            "НомерДоговора",
            "Номер договора",
            "Номер_договора",
            "DocContract",
            "DocContractNumber",
            "Contract",
            "Договор",
            "ДоговорНомер",
            "РегистрационныйНомерДоговора",
            "НомерДоговораПодрядчика",
            "РНД",
            "ШифрДоговора",
            "DogNumber",
            "НомерРД",
            "РДПоДоговору",
        ],
    )
    due_col = _tessa_find_column(
        pred,
        [
            "Deadline",
            "DueDate",
            "Срок устранения предписания",
            "Срок устранения",
            "СрокУстранения",
            "PlanEnd",
            "Deadline",
            "Контрольный срок",
            "PlanDate",
            "ДатаПлановогоОкончания",
            "ДатаСрока",
            "СрокПредписания",
            "ExecutionDate",
            "TargetDate",
            "PlanEndDate",
            "СрокИсполнения",
        ],
    )
    completion_col = _tessa_find_column(
        pred,
        [
            "Completed",
            "CompletionDate",
            "Дата завершения",
            "Факт устранения",
            "ActualDueDate",
            "FactDueDate",
            "ФактическаяДатаУстранения",
            "ДатаФактическогоУстранения",
            "СрокУстраненияФакт",
            "ДатаИсполнения",
        ],
    )
    doc_num_col = _tessa_find_column(
        pred,
        [
            "DocNumber",
            "Номер предписания",
            "НомерПредписания",
            "Number",
            "DirectiveNumber",
            "НомерПоручения",
        ],
    )
    full_doc_col = _tessa_find_column(
        pred,
        [
            "FullDocumentNumber",
            "DocumentFullNumber",
            "RegNumber",
            "RegistrationNumber",
            "РегистрационныйНомерДокумента",
            "НомерДокументаПолный",
            "ПолныйНомерДокумента",
            "FullNumber",
            "DocRegNumber",
            "НомерДокумента",
            "DocumentNumber",
        ],
    )
    if (
        full_doc_col
        and doc_num_col
        and str(full_doc_col).strip() == str(doc_num_col).strip()
    ):
        full_doc_col = None
    if not doc_num_col:
        for col in pred.columns:
            k = str(col).strip().lower()
            if contract_col is not None and str(col) == str(contract_col):
                continue
            if "номер" in k and "договор" not in k and "contract" not in k:
                doc_num_col = col
                break
    creation_col_pred = _tessa_find_column(pred, ["CreationDate", "creationdate", "Дата создания"])
    issue_block_col = _tessa_find_column(
        pred,
        [
            "BlockName",
            "IssueBlock",
            "Блок выдачи предписания",
            "Блок выдачи",
            "Блок",
            "Подразделение",
            "Department",
        ],
    )
    stable_sort_cols = [c for c in [pred_doc_col, doc_num_col, pred_card_col, creation_col_pred] if c and c in pred.columns]
    if stable_sort_cols:
        pred = pred.sort_values(stable_sort_cols, kind="stable", na_position="last").reset_index(drop=True)

    pred = _pred_dedupe_by_docid(pred, pred_doc_col, creation_col_pred)
    pred = _pred_merge_completion_from_tasks(pred, pred_card_col, pred_doc_col)

    _excl_guess = [kind_col, contr_col, obj_col, doc_num_col, creation_col_pred, completion_col]
    if not contract_col:
        contract_col = _pred_guess_contract_column(pred, exclude=_excl_guess)
    if not due_col:
        due_col = _pred_guess_due_column(pred, exclude=_excl_guess + [contract_col])

    st_l = pred["Статус"].astype(str)
    pred["_issue_date"] = _tessa_to_datetime(pred[creation_col_pred]) if creation_col_pred else pd.Series(pd.NaT, index=pred.index)
    _base_comp = (
        _tessa_to_datetime(pred[completion_col])
        if completion_col and completion_col in pred.columns
        else pd.Series(pd.NaT, index=pred.index)
    )
    _task_comp = _tessa_to_datetime(pred["_completion_from_task"]) if "_completion_from_task" in pred.columns else pd.Series(pd.NaT, index=pred.index)
    pred["_completion_dt"] = _base_comp.where(_base_comp.notna(), _task_comp)
    pred["_signed"] = st_l.str.contains("Подписан", case=False, na=False) | st_l.str.contains("Согласован", case=False, na=False)
    pred["_resolved"] = False
    if "KrStateID" in pred.columns:
        _krstate_num = pd.to_numeric(pred["KrStateID"], errors="coerce")
        pred["_resolved"] = pred["_resolved"] | (_krstate_num == 13)
    pred["_resolved"] = (
        pred["_resolved"]
        | st_l.str.contains("устран", case=False, na=False)
        | st_l.str.contains("выполн", case=False, na=False)
        | st_l.str.contains("закрыт", case=False, na=False)
    )
    if due_col:
        pred["_due"] = _tessa_to_datetime(pred[due_col])
    else:
        pred["_due"] = pd.NaT

    def _overdue_days_row(r):
        if r["_resolved"]:
            return 0
        if pd.notna(r["_due"]):
            d = r["_due"]
            if hasattr(d, "date"):
                dd = d.date()
            else:
                dd = pd.to_datetime(d, errors="coerce")
                dd = dd.date() if pd.notna(dd) else None
            if dd and date.today() > dd:
                return (date.today() - dd).days
        return 0

    pred["_overdue_days"] = pred.apply(_overdue_days_row, axis=1)
    _tag_col = _tessa_find_column(pred, ["Tessa_Teg", "TessaTag", "Тег", "Тэг"])
    _kind_id_col = _tessa_find_column(pred, ["KindID", "KindId", "kindid"])
    _crit_tag = pd.Series(False, index=pred.index)
    if _tag_col and _tag_col in pred.columns:
        _crit_tag = _crit_tag | pred[_tag_col].astype(str).str.strip().str.casefold().eq("критичный")
    if _kind_id_col and _kind_id_col in pred.columns:
        _crit_tag = _crit_tag | (
            pred[_kind_id_col].astype(str).str.strip().str.casefold()
            == str(_KIND_ID_CRITICAL).casefold()
        )
    pred["_critical"] = _crit_tag | (pred["_overdue_days"] > 30)

    def _pred_axis_upper_bound(xmax: float) -> float:
        try:
            val = float(xmax)
        except (TypeError, ValueError):
            return 5.0
        if not np.isfinite(val) or val <= 0:
            return 5.0
        if val <= 5:
            return 5.0
        if val <= 10:
            return 10.0
        if val <= 25:
            return float(int(np.ceil(val / 5.0)) * 5)
        if val <= 100:
            return float(int(np.ceil(val / 10.0)) * 10)
        return float(int(np.ceil(val / 25.0)) * 25)

    st.markdown("**Фильтры**")
    projects = pred_project_options
    if contr_col:
        contractors_ms = sorted(
            pred[contr_col].dropna().astype(str).str.strip().unique().tolist(),
            key=lambda x: str(x).lower(),
        )
    else:
        contractors_ms = []
    if curator_col:
        curators = ["Все кураторы"] + sorted(
            pred[curator_col].dropna().astype(str).str.strip().unique().tolist(),
            key=lambda x: str(x).lower(),
        )
    else:
        curators = ["Все кураторы"]

    if curator_col:
        fc1, fc2, fc3, fc4, fc5, fb1, fb2 = st.columns([2, 2, 2, 2, 2, 1, 1])
    else:
        fc1, fc2, fc3, fc4, fb1, fb2 = st.columns([2, 2, 2, 2, 1, 1])
        fc5 = None

    with fc1:
        if obj_col:
            sel_obj = st.multiselect(
                "Проект",
                projects,
                default=st.session_state.get("pred_m_p", []),
                key="pred_m_p",
                help="Пустой выбор = все проекты.",
                placeholder="Выберите проекты",
            )
        else:
            sel_obj = []
    with fc2:
        if contr_col:
            sel_contr = st.multiselect(
                "Подрядчик",
                contractors_ms,
                default=st.session_state.get("pred_m_c_ms", []),
                key="pred_m_c_ms",
                help="Пустой выбор = все подрядчики.",
                placeholder="Все подрядчики",
            )
        else:
            sel_contr = []
    if curator_col and fc5 is not None:
        with fc3:
            sel_curator = st.selectbox("Куратор", curators, key="pred_m_curator")
        _fc_contract = fc4
        _fc_period = fc5
    else:
        sel_curator = "Все кураторы"
        _fc_contract = fc3
        _fc_period = fc4
    with _fc_contract:
        contract_q = st.text_input("№ договора (частичный поиск)", "", key="pred_m_contract")
    with _fc_period:
        if pred["_issue_date"].notna().any():
            min_issue = pred["_issue_date"].min().date()
            max_issue = pred["_issue_date"].max().date()
            issue_period = st.date_input(
                "Выбор периода выданных предписаний",
                value=(min_issue, max_issue),
                min_value=min_issue,
                max_value=max_issue,
                key="pred_issue_period",
                format="DD.MM.YYYY",
            )
            if isinstance(issue_period, tuple) and len(issue_period) == 2:
                issue_start, issue_end = issue_period
            else:
                issue_start = issue_period
                issue_end = issue_period
        else:
            issue_start = issue_end = None
            st.caption("Нет даты выдачи в данных.")
    with fb1:
        st.markdown("<br>", unsafe_allow_html=True)
        st.button("Применить", key="pred_m_apply", type="primary", use_container_width=True)
    with fb2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Сбросить", key="pred_m_reset", use_container_width=True):
            if obj_col:
                st.session_state.pred_m_p = []
            if contr_col:
                st.session_state.pred_m_c_ms = []
            if curator_col:
                st.session_state.pred_m_curator = "Все кураторы"
            st.session_state.pred_m_contract = ""
            if pred["_issue_date"].notna().any():
                st.session_state.pred_issue_period = (min_issue, max_issue)
            st.rerun()
    hide_resolved = st.checkbox(
        "Не отображать устраненные предписания",
        value=True,
        key="pred_hide_resolved",
    )

    filtered = pred.copy()
    if obj_col and sel_obj:
        _proj_set = {str(x).strip() for x in sel_obj if str(x).strip()}
        if _proj_set and len(_proj_set) != len(projects):
            filtered = filtered[filtered[obj_col].astype(str).str.strip().isin(_proj_set)]
    if contr_col and sel_contr:
        _cs = {str(x).strip() for x in sel_contr if str(x).strip()}
        if _cs:
            filtered = filtered[filtered[contr_col].astype(str).str.strip().isin(_cs)]
    if sel_curator != "Все кураторы" and curator_col and curator_col in filtered.columns:
        filtered = filtered[filtered[curator_col].astype(str).str.strip() == sel_curator]
    if contract_q.strip() and contract_col:
        filtered = filtered[
            filtered[contract_col].astype(str).str.lower().str.contains(contract_q.strip().lower(), na=False)
        ]
    if issue_start is not None and issue_end is not None:
        filtered = filtered[
            filtered["_issue_date"].notna()
            & (filtered["_issue_date"].dt.date >= issue_start)
            & (filtered["_issue_date"].dt.date <= issue_end)
        ]

    if filtered.empty:
        st.info("Нет данных при выбранных фильтрах.")
        return

    if not due_col:
        st.caption(
            "Срок устранения считается отдельно от даты завершения (Completed). "
            "Укажите DueDate или «Срок устранения» в TESSA."
        )

    unres_mask = ~filtered["_resolved"]
    resolved_mask = filtered["_resolved"]
    n_total = int(len(filtered))
    n_unresolved = int(unres_mask.sum())
    n_resolved = int(resolved_mask.sum())
    n_overdue = int((unres_mask & (filtered["_overdue_days"] > 0)).sum())
    n_critical = int((unres_mask & filtered["_critical"]).sum())

    fu = filtered.loc[unres_mask].copy()
    chart_group_col = None
    chart_group_label = ""
    if contr_col and contr_col in fu.columns and fu[contr_col].astype(str).str.strip().ne("").any():
        chart_group_col = contr_col
        chart_group_label = "подрядчикам"
    elif obj_col and obj_col in fu.columns and fu[obj_col].astype(str).str.strip().ne("").any():
        chart_group_col = obj_col
        chart_group_label = "проектам"
    if issue_start is not None and issue_end is not None:
        st.caption(
            f"Период выдачи предписаний: {issue_start.strftime('%d.%m.%Y')} — {issue_end.strftime('%d.%m.%Y')}"
        )
    pm1, pm2, pm3 = st.columns(3)
    with pm1:
        st.metric("Всего предписаний", n_total)
    with pm2:
        st.metric("Устраненные предписания", n_resolved)
    with pm3:
        st.metric("Неустраненные", n_unresolved)

    col_chart, col_kpi = st.columns([3, 1])

    with col_chart:
        st.markdown(
            _PRED_DASH_MOCK_CSS
            + '<div class="pred-leg"><span style="color:#3498db;font-weight:600;">■</span> Длина столбца — '
            "<strong>неустранённые</strong> предписания; подпись на столбце — <strong>просроченные</strong>. "
            "В подсказке — период <strong>дат выдачи</strong> по группе.</div>",
            unsafe_allow_html=True,
        )
        if chart_group_col and not fu.empty:
            grp = (
                fu.groupby(chart_group_col, as_index=False)
                .agg(
                    Неустранено=(chart_group_col, "size"),
                    Просрочено=("_overdue_days", lambda x: int((x > 0).sum())),
                    Мин_дата=("_issue_date", "min"),
                    Макс_дата=("_issue_date", "max"),
                )
                .sort_values("Неустранено", ascending=False)
            )
            _txt = [
                (f"проср.: {int(o)}" if int(o) > 0 else "")
                for o in grp["Просрочено"]
            ]
            fig1 = go.Figure()
            fig1.add_trace(
                go.Bar(
                    y=grp[chart_group_col],
                    x=grp["Неустранено"],
                    name="Неустраненные предписания",
                    orientation="h",
                    marker=dict(color="#3498db", line=dict(color="rgba(255,255,255,0.12)", width=1)),
                    text=_txt,
                    textposition="inside",
                    insidetextanchor="middle",
                    textfont=dict(color="#ffffff", size=max(12, min(15, 200 // max(1, len(grp))))),
                    customdata=np.stack(
                        [
                            grp["Просрочено"].astype(int),
                            grp["Мин_дата"].dt.strftime("%d.%m.%Y").fillna("—"),
                            grp["Макс_дата"].dt.strftime("%d.%m.%Y").fillna("—"),
                        ],
                        axis=1,
                    ),
                    hovertemplate=(
                        "<b>%{y}</b><br>"
                        "Неустраненных: %{x}<br>"
                        "Просроченных: %{customdata[0]}<br>"
                        "Дата выдачи (мин–макс): %{customdata[1]} — %{customdata[2]}<extra></extra>"
                    ),
                )
            )
            fig1.update_layout(
                bargap=0.26,
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="center", x=0.5),
            )
            xmax = max(
                float(pd.to_numeric(grp["Неустранено"], errors="coerce").fillna(0).max()),
                1.0,
            )
            axis_upper = _pred_axis_upper_bound(xmax)
            _row_h = 58
            fig1.update_layout(
                height=max(520, len(grp) * _row_h + 200),
                yaxis_title="",
                xaxis_title="Количество неустраненных предписаний",
                margin=dict(l=12, r=140, t=72, b=88),
                xaxis=dict(range=[0, axis_upper], title=dict(standoff=18), automargin=True),
                yaxis=dict(automargin=True, tickfont=dict(size=13)),
                uirevision="pred_main_chart",
                title=dict(
                    text="Неустраненные предписания по группе (даты выдачи — в подсказке)",
                    font=dict(size=15),
                    x=0.5,
                    xanchor="center",
                ),
            )
            fig1.update_layout(uniformtext=dict(minsize=11, mode="show"))
            fig1 = apply_chart_background(fig1)
            render_chart(
                fig1,
                key="pred_bar_main",
                caption_below="",
            )
        else:
            if hide_resolved and filtered.loc[~filtered["_resolved"]].empty:
                st.info("Нет данных для диаграммы: по текущим фильтрам все предписания устранены.")
            else:
                st.info("Нет данных для диаграммы.")

    with col_kpi:
        st.markdown(
            _pred_kpi_circles_html(n_total, n_unresolved, n_resolved, n_overdue, n_critical, with_heading=True),
            unsafe_allow_html=True,
        )
        st.caption(
            "Маппинг KPI: «Всего предписаний» = все записи, «Устраненные» = закрытые/устраненные, "
            "«Неустраненные» = открытые, «Просроченные» = открытые с просроченным сроком."
        )

    st.subheader("Детальная таблица по предписаниям")
    with st.expander("Примечание к таблице", expanded=False):
        st.caption("Клик по заголовку сортирует таблицу. Просроченные строки выделены розовым, устраненные — салатовым.")
    show = filtered.copy()
    if hide_resolved:
        show = show.loc[unres_mask].copy()
    show = show.sort_values(["_critical", "_overdue_days"], ascending=[False, False])

    table_df = _pred_build_detail_table_df(
        show,
        contr_col,
        obj_col,
        contract_col,
        doc_num_col,
        full_doc_col,
        creation_col_pred,
        issue_block_col,
        due_col,
        completion_col,
    )
    sort_col = _pred_query_param_value("pred_sort", "Дней просрочки")
    sort_order = _pred_query_param_value("pred_order", "desc")
    if sort_col in table_df.columns:
        table_df = _pred_sort_table_df(table_df, sort_col, sort_order)

    overdue_cnt = int((show["_overdue_days"] > 0).sum())
    st.caption(
        f"Записей: {len(table_df)} · просроченных: {overdue_cnt} · устраненных: {int(show['_resolved'].sum())}"
    )
    st.markdown(
        _PRED_DASH_MOCK_CSS
        + _pred_detail_table_html(table_df, sort_col=sort_col, sort_order=sort_order),
        unsafe_allow_html=True,
    )
    render_dataframe_excel_csv_downloads(
        table_df.drop(columns=["_resolved_flag"], errors="ignore"),
        file_stem="predpisania",
        key_prefix="predpisania",
    )

    with st.expander("По статусам и объектам", expanded=False):
        status_counts = filtered["Статус"].value_counts()
        st.subheader("Предписания по статусам")
        status_df = status_counts.reset_index()
        status_df.columns = ["Статус", "Количество"]
        fig2 = px.pie(
            status_df,
            names="Статус",
            values="Количество",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig2.update_traces(textinfo="label+percent+value", textfont_size=12)
        fig2 = apply_chart_background(fig2)
        fig2.update_layout(height=420)
        render_chart(fig2, key="pred_status_pie", caption_below="Распределение предписаний по статусам")

        if obj_col and obj_col in filtered.columns:
            st.subheader("Предписания по объектам")
            by_obj = (
                filtered.groupby(obj_col)
                .size()
                .reset_index(name="Количество")
                .sort_values("Количество", ascending=False)
            )
            fig3 = px.bar(
                by_obj,
                x=obj_col,
                y="Количество",
                text="Количество",
                labels={obj_col: "Объект"},
                color_discrete_sequence=["#06A77D"],
            )
            fig3.update_traces(textposition="outside", textfont=dict(size=13, color="white"))
            fig3 = _apply_finance_bar_label_layout(fig3)
            fig3 = apply_chart_background(fig3)
            fig3.update_layout(height=450, xaxis_title="Объект", yaxis_title="Количество", xaxis_tickangle=-45)
            render_chart(fig3, key="pred_by_obj", caption_below="Количество предписаний по объектам")


_DEV_DETAIL_TABLE_CSS = """
<style>
/* По правкам (скрин ТЗ): при % выполнения < 100% — оранжевая акцентировка, не красная подложка строки */
.rendered-table tr.dev-detail-row-warn td {
  background: rgba(255, 159, 67, 0.12) !important;
  color: #e8eaed;
}
.rendered-table tr.dev-detail-row-warn td.dev-pct-warn {
  color: #ff9f40 !important;
  font-weight: 600;
}
</style>
"""


def _dev_fmt_cell_nd(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "Н/Д"
    s = str(v).strip()
    if s.lower() in ("", "nan", "none", "nat"):
        return "Н/Д"
    return s


def _dev_fmt_date_ru(v):
    if v is None:
        return "Н/Д"
    # NaT / NaN / NAType — до strftime (у pd.NaT isinstance Timestamp, но strftime падает)
    try:
        if pd.isna(v):
            return "Н/Д"
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and pd.isna(v):
        return "Н/Д"
    if isinstance(v, pd.Timestamp):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, datetime):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    ts = pd.to_datetime(v, errors="coerce")
    if pd.isna(ts):
        return "Н/Д"
    return ts.strftime("%d.%m.%Y")


def _dev_column_looks_like_date(col_name: str) -> bool:
    n = str(col_name).lower()
    if "отклонение" in n or "дней" in n or "%" in n:
        return False
    if any(k in n for k in ("начало", "окончание", "окончан", "дата")):
        return True
    if ("plan" in n or "base" in n) and ("start" in n or "end" in n):
        return True
    return False


def _render_dev_detail_table(df, max_rows=500):
    """Детальная таблица по правкам: даты дд.мм.гггг или «Н/Д»; при % выполнения < 100 — оранжевый акцент (макет правок)."""
    show = df.head(max_rows).copy()
    pct_name = "% выполнения"
    esc = html_module.escape

    thead = "<thead><tr>" + "".join(f"<th>{esc(str(c))}</th>" for c in show.columns) + "</tr></thead>"
    body_parts = []
    for _, row in show.iterrows():
        pct_raw = row[pct_name] if pct_name in show.columns else None
        pct_num = pd.to_numeric(pct_raw, errors="coerce")
        # По ТЗ: подсветка при % выполнения < 100 (не трогаем > 100 как «не завершено»)
        warn = pd.notna(pct_num) and float(pct_num) < 100.0
        tr_o = '<tr class="dev-detail-row-warn">' if warn else "<tr>"
        tds = []
        for col in show.columns:
            v = row[col]
            if col == pct_name:
                if pd.isna(pct_num):
                    cell = "Н/Д"
                elif abs(float(pct_num) - round(float(pct_num))) < 1e-6:
                    cell = str(int(round(float(pct_num))))
                else:
                    cell = f"{float(pct_num):.1f}".replace(".", ",")
                pct_cls = ' class="dev-pct-warn"' if warn else ""
                tds.append(f"<td{pct_cls}>{esc(cell)}</td>")
                continue
            if _dev_column_looks_like_date(str(col)):
                cell = _dev_fmt_date_ru(v)
            else:
                if isinstance(v, (pd.Timestamp, datetime, date)):
                    cell = _dev_fmt_date_ru(v)
                else:
                    num_try = pd.to_numeric(v, errors="coerce")
                    if pd.notna(num_try) and str(v).strip() != "":
                        fv = float(num_try)
                        if abs(fv - round(fv)) < 1e-9:
                            cell = str(int(round(fv)))
                        else:
                            cell = str(fv).replace(".", ",")
                    else:
                        cell = _dev_fmt_cell_nd(v)
            tds.append(f"<td>{esc(cell)}</td>")
        body_parts.append(tr_o + "".join(tds) + "</tr>")
    tbody = "<tbody>" + "".join(body_parts) + "</tbody>"
    html_tbl = '<table class="rendered-table" border="0">' + thead + tbody + "</table>"
    st.markdown(
        _TABLE_CSS + _DEV_DETAIL_TABLE_CSS + '<div class="rendered-table-wrap">' + html_tbl + "</div>",
        unsafe_allow_html=True,
    )
    if len(df) > max_rows:
        with st.expander("Ограничение отображения таблицы", expanded=False):
            st.caption(
                f"Показано {max_rows} из {len(df)} записей. Скачайте CSV или Excel для полных данных."
            )


# ==================== DASHBOARD: Девелоперские проекты ====================
def dashboard_developer_projects(df):
    """
    Отчёт «Девелоперские проекты» — одна таблица: матрица контрольных точек по ТЗ.
    """
    st.header("Девелоперские проекты")

    if df is None or not hasattr(df, "columns") or df.empty:
        st.warning("Загрузите файл с данными проекта (MSP) для отчёта «Девелоперские проекты».")
        return

    work = df.copy()

    def _find(possible):
        for name in possible:
            for c in work.columns:
                if name.strip().lower() == str(c).strip().lower():
                    return c
        return None

    project_col = _find(["project name", "Проект", "проект", "Project"])
    task_col = _find(["task name", "Название", "Task Name"])

    key_col = task_col or project_col
    if key_col:
        work = work[
            work[key_col].notna()
            & (~work[key_col].astype(str).str.strip().isin(["", "nan", "None", "NaN"]))
        ].reset_index(drop=True)

    if not project_col and not task_col:
        st.warning("Не найдены ключевые колонки (проект, задача). Проверьте формат файла.")
        return

    # По правкам ТЗ: в фильтрах только проект
    if project_col and project_col in work.columns:
        projects = ["Все"] + _unique_project_labels_for_select(work[project_col])
        sel_proj = st.selectbox(
            "Проект",
            projects,
            index=0,
            key="dev_proj",
            help="Единственный фильтр отчёта: проект из выгрузки MSP. По умолчанию «Все» — в таблице по одной строке на каждый проект.",
        )
    else:
        sel_proj = "Все"
    # Не фильтруем по «Уровень» в UI: в MSP это не outline; выбор не «Все» оставлял только часть строк —
    # матрица ТЗ (вехи ур. 5 и т.д.) превращалась в сплошные Н/Д. Уровни отбора встроены в матрицу.

    filtered = work.copy()
    if sel_proj != "Все" and project_col:
        _pk = _project_filter_norm_key(sel_proj)
        filtered = filtered[
            filtered[project_col].map(_project_filter_norm_key) == _pk
        ]

    if project_col and project_col in filtered.columns:
        filtered = _project_column_apply_canonical(filtered, project_col)

    if filtered.empty:
        st.info("Нет данных при выбранных фильтрах.")
        return

    uniq_proj_n = (
        int(work[project_col].dropna().astype(str).str.strip().nunique())
        if project_col and project_col in work.columns
        else 1
    )

    st.subheader("Матрица контрольных точек")
    matrix_df = filtered.copy()
    if matrix_df.empty:
        st.info("Нет строк MSP для выбранного проекта.")
        return

    rows_blocks_for_export: list = []
    export_project_names: list = []

    if sel_proj != "Все" or not project_col or uniq_proj_n <= 1:
        rows_tz, _cap = build_dev_tz_matrix_rows(
            matrix_df,
            st.session_state.get("project_data"),
            st.session_state,
        )
        render_dev_tz_matrix(rows_tz, _TABLE_CSS)
        rows_blocks_for_export = [rows_tz]
        if project_col and project_col in matrix_df.columns and matrix_df[project_col].notna().any():
            export_project_names = [
                str(matrix_df[project_col].dropna().astype(str).str.strip().iloc[0]).strip()
            ]
        elif sel_proj and str(sel_proj).strip() != "Все":
            export_project_names = [str(sel_proj).strip()]
        else:
            export_project_names = [""]
    else:
        ordered = sorted(matrix_df[project_col].dropna().astype(str).str.strip().unique().tolist())
        blocks: list = []
        names: list = []
        for pname in ordered:
            sub = matrix_df[matrix_df[project_col].astype(str).str.strip() == pname]
            if sub.empty:
                continue
            rows_p, _cap = build_dev_tz_matrix_rows(
                sub,
                st.session_state.get("project_data"),
                st.session_state,
            )
            blocks.append(rows_p)
            names.append(pname)
        if not blocks:
            st.info("Нет строк MSP для проектов в выборке.")
            return
        render_dev_tz_matrix(blocks, _TABLE_CSS)
        rows_blocks_for_export = blocks
        export_project_names = names

    try:
        export_parts: list = []
        for i, blk in enumerate(rows_blocks_for_export):
            part = pd.DataFrame(blk)
            if "warn" in part.columns:
                part = part.rename(columns={"warn": "Подсветка_менее_100pct"})
            pname = export_project_names[i] if i < len(export_project_names) else ""
            if pname:
                part.insert(0, "проект", pname)
            export_parts.append(part)
        export_df = (
            pd.concat(export_parts, ignore_index=True) if len(export_parts) > 1 else export_parts[0]
        )
        csv_name = "developer_projects_matrix.csv"
        if len(export_parts) > 1:
            csv_name = "developer_projects_matrix_all_projects.csv"
        elif export_project_names and str(export_project_names[0]).strip():
            p0 = str(export_project_names[0]).strip()
            slug = re.sub(r"[\s<>:\"/\\|?*]+", "_", p0).strip("_")[:120] or "project"
            csv_name = f"developer_projects_matrix_{slug}.csv"
        render_dataframe_excel_csv_downloads(
            export_df,
            file_stem=csv_name,
            key_prefix="dev_matrix",
            csv_label="Скачать матрицу (CSV, для Excel)",
        )
    except Exception:
        pass

    st.markdown("---")
    st.subheader("Таблица задач")
    st.caption(
        "Таблица строится по выгрузке MSP: базовые даты (plan start/end) и факт (base start/end), "
        "отклонения начала/окончания, длительности, а также «Причина отклонений» и «Заметки» (если есть в файле)."
    )

    def _dev_find_col(d: pd.DataFrame, names: list[str]):
        if d is None or getattr(d, "empty", True):
            return None
        for nm in names:
            for c in d.columns:
                if str(nm).strip().lower() == str(c).strip().lower():
                    return c
        return None

    def _dev_find_notes_col(d: pd.DataFrame):
        return _find_column_by_keywords(d, ("note", "заметк", "comment", "remark", "notes"))

    tbl_src = filtered.copy()
    ensure_date_columns(tbl_src)
    for dc in ("plan start", "plan end", "base start", "base end"):
        if dc in tbl_src.columns:
            tbl_src[dc] = pd.to_datetime(tbl_src[dc], errors="coerce", dayfirst=True)

    # Колонки «причина/заметки» в разных выгрузках
    reason_col = _dev_find_col(tbl_src, ["reason of deviation", "Причина отклонений", "Причина_отклонений", "причина"])
    notes_col = _dev_find_notes_col(tbl_src)

    # Отбираем только строки с хотя бы одной парой дат (база или факт)
    _has_base = tbl_src.get("plan start").notna() & tbl_src.get("plan end").notna()
    _has_fact = tbl_src.get("base start").notna() & tbl_src.get("base end").notna()
    tbl_src = tbl_src[_has_base | _has_fact].copy()
    if tbl_src.empty:
        st.info("Нет строк с датами для таблицы.")
        return

    def _fmt_date(v):
        if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
            return ""
        try:
            return pd.Timestamp(v).strftime("%d.%m.%Y")
        except Exception:
            return str(v).strip()

    def _days(v):
        if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
            return np.nan
        try:
            return float(v)
        except Exception:
            return np.nan

    # Сбор строк таблицы
    out_rows = []
    for _, r in tbl_src.iterrows():
        pn = _clean_display_str(r.get(project_col)) if project_col else ""
        tn = _clean_display_str(r.get(task_col)) if task_col else ""
        ps = r.get("plan start")
        pe = r.get("plan end")
        fs = r.get("base start")
        fe = r.get("base end")

        # Отклонение начала: (базовое начало − начало), красный если < 0
        dev_start = np.nan
        if pd.notna(ps) and pd.notna(fs):
            dev_start = (pd.Timestamp(ps) - pd.Timestamp(fs)).total_seconds() / 86400.0
        # Отклонение окончания: (окончание − базовое окончание), красный если > 0
        dev_end = np.nan
        if pd.notna(pe) and pd.notna(fe):
            dev_end = (pd.Timestamp(fe) - pd.Timestamp(pe)).total_seconds() / 86400.0

        base_dur = np.nan
        if pd.notna(ps) and pd.notna(pe):
            base_dur = (pd.Timestamp(pe) - pd.Timestamp(ps)).total_seconds() / 86400.0
        dur = np.nan
        if pd.notna(fs) and pd.notna(fe):
            dur = (pd.Timestamp(fe) - pd.Timestamp(fs)).total_seconds() / 86400.0

        row = {
            "Проект": pn,
            "Задача": tn,
            "Начало": _fmt_date(fs),
            "Базовое начало": _fmt_date(ps),
            "Отклонение начала": dev_start,
            "Окончание": _fmt_date(fe),
            "Базовое окончание": _fmt_date(pe),
            "Отклонение окончания": dev_end,
            "Базовая длительность": base_dur,
            "Длительность": dur,
        }
        if reason_col and reason_col in tbl_src.columns:
            row["Причина отклонений"] = _clean_display_str(r.get(reason_col))
        if notes_col and notes_col in tbl_src.columns:
            row["Заметки"] = _clean_display_str(r.get(notes_col))
        out_rows.append(row)

    dev_tbl = pd.DataFrame(out_rows)
    # Числовые колонки — числа, форматирование будет на display-копии
    for c in ("Отклонение начала", "Отклонение окончания", "Базовая длительность", "Длительность"):
        if c in dev_tbl.columns:
            dev_tbl[c] = pd.to_numeric(dev_tbl[c], errors="coerce")

    # Порядок столбцов по ТЗ; «Этап» не выводим.
    desired_cols = [
        "Проект",
        "Задача",
        "Начало",
        "Базовое начало",
        "Отклонение начала",
        "Окончание",
        "Базовое окончание",
        "Отклонение окончания",
        "Базовая длительность",
        "Длительность",
        "Причина отклонений",
        "Заметки",
    ]
    dev_tbl = dev_tbl[[c for c in desired_cols if c in dev_tbl.columns]]

    display_tbl = dev_tbl.copy()

    def _fmt_int(x):
        if pd.isna(x):
            return ""
        try:
            return str(int(round(float(x), 0)))
        except Exception:
            return ""

    for c in ("Отклонение начала", "Отклонение окончания", "Базовая длительность", "Длительность"):
        if c in display_tbl.columns:
            display_tbl[c] = display_tbl[c].apply(_fmt_int)

    def _dev_start_style(v):
        n = pd.to_numeric(v, errors="coerce")
        if pd.isna(n):
            return f"color: {TABLE_TEXT_COLOR}"
        # красный если < 0, иначе зелёный
        return "color: #c0392b; font-weight: 600" if float(n) < 0 else "color: #27ae60; font-weight: 600"

    def _dev_end_style(v):
        n = pd.to_numeric(v, errors="coerce")
        if pd.isna(n):
            return f"color: {TABLE_TEXT_COLOR}"
        # красный если > 0, иначе зелёный
        return "color: #c0392b; font-weight: 600" if float(n) > 0 else "color: #27ae60; font-weight: 600"

    # В старых версиях pandas Styler может не поддерживать applymap/часть API.
    # Поэтому рендерим таблицу вручную как HTML (как в других отчётах проекта).
    _max_rows_show = 220
    show_num = dev_tbl.head(_max_rows_show).copy()
    show_disp = display_tbl.head(_max_rows_show).copy()
    if len(display_tbl) > _max_rows_show:
        st.caption(
            f"Показано {_max_rows_show} из {len(display_tbl)} строк (для полного списка используйте выгрузку)."
        )

    _bg_turq = "rgba(46, 134, 171, 0.22)"  # базовое начало / начало
    _bg_blue = "rgba(59, 130, 246, 0.18)"  # базовое окончание / окончание
    _bg_dur = "rgba(99, 102, 241, 0.16)"  # длительности

    def _cell_bg(col_name: str) -> str:
        if col_name in ("Базовое начало", "Начало"):
            return _bg_turq
        if col_name in ("Базовое окончание", "Окончание"):
            return _bg_blue
        if col_name in ("Базовая длительность", "Длительность"):
            return _bg_dur
        return TABLE_BG_COLOR

    def _dev_start_color(nv) -> str:
        n = pd.to_numeric(nv, errors="coerce")
        if pd.isna(n):
            return TABLE_TEXT_COLOR
        return "#c0392b" if float(n) < 0 else "#27ae60"

    def _dev_end_color(nv) -> str:
        n = pd.to_numeric(nv, errors="coerce")
        if pd.isna(n):
            return TABLE_TEXT_COLOR
        return "#c0392b" if float(n) > 0 else "#27ae60"

    headers = list(show_disp.columns)
    _parts = [
        '<div class="rendered-table-wrap" style="margin-top:0.5rem">',
        '<table class="rendered-table" style="border-collapse:collapse;width:100%">',
        "<thead><tr>",
    ]
    for h in headers:
        _parts.append(f"<th>{html_module.escape(str(h))}</th>")
    _parts.append("</tr></thead><tbody>")
    for i in range(len(show_disp)):
        _parts.append("<tr>")
        for col in headers:
            cell = show_disp.iloc[i][col]
            txt = "" if cell is None else str(cell)
            esc = html_module.escape(txt) if txt.strip() else ""
            bg = _cell_bg(col)
            extra = ""
            if col == "Отклонение начала":
                clr = _dev_start_color(show_num.iloc[i].get(col) if col in show_num.columns else np.nan)
                extra = f"color:{clr};font-weight:600;"
            elif col == "Отклонение окончания":
                clr = _dev_end_color(show_num.iloc[i].get(col) if col in show_num.columns else np.nan)
                extra = f"color:{clr};font-weight:600;"
            _parts.append(
                f'<td style="background:{bg};color:{TABLE_TEXT_COLOR};{extra}border-bottom:1px solid #333;padding:6px 12px;">{esc}</td>'
            )
        _parts.append("</tr>")
    _parts.append("</tbody></table></div>")
    st.markdown(_TABLE_CSS + "".join(_parts), unsafe_allow_html=True)
    render_dataframe_excel_csv_downloads(
        display_tbl,
        file_stem="developer_projects_tasks_table",
        key_prefix="dev_projects_tasks",
        csv_label="Скачать таблицу задач (CSV, для Excel)",
    )


# ── Правки заказчика (Правки 1.pdf): скрытые и новые отчёты ─────────────────
def dashboard_pravki_report_hidden(df):
    """Заглушка: отчёт исключён из меню по правкам."""
    st.info(
        "Отчёт «Значения отклонений от базового плана» скрыт по правкам заказчика. "
        "Используйте «Отклонение от базового плана» или «Причины отклонений»."
    )


def dashboard_id_tessa_placeholder(df):
    """Заглушка для будущего раздела ИД/TESSA."""
    st.header("ИД/TESSA")
    st.info("Раздел в разработке.")


def _render_control_points_admin_on_dashboard():
    """
    Администратор: редактирование названий столбцов (title) и сопоставления с MSP (match)
    на странице отчёта «Контрольные точки» (хранилище: настройка БД control_points_milestones_json).
    """
    try:
        from auth import get_current_user, has_admin_access

        user = get_current_user()
        if not user or not has_admin_access(user.get("role")):
            return
    except Exception:
        return

    from dashboards.dev_projects_tz_matrix import (
        control_point_milestones_default_json,
        get_control_point_milestones_effective,
        save_control_point_milestones_json,
    )
    from settings import get_setting

    with st.expander(
        "Настройка вех, заголовков столбцов и соответствия MSP (администратор)",
        expanded=False,
    ):
        st.caption(
            "**title** — заголовок группы столбцов в таблице; **slug** — стабильный ключ данных; "
            "**match** — правила отбора задач из выгрузки MSP (level, names_any, name_contains, "
            "parent_l2_contains, block_contains, phase_needles, phase_exclude_needles). "
            "Изменения сохраняются в базе и сразу применяются к этому отчёту."
        )
        cur = get_control_point_milestones_effective()
        st.caption(f"Сейчас активно вех: **{len(cur)}**.")
        raw = (get_setting("control_points_milestones_json") or "").strip()
        default_js = control_point_milestones_default_json()
        initial = raw if raw else default_js
        txt = st.text_area(
            "JSON: массив объектов с полями title, slug, match",
            value=initial,
            height=380,
            key="cp_dash_milestones_json",
            help="После сохранения таблица ниже обновится. Пустой сброс — кнопка «Сбросить на встроенные правила».",
        )
        b1, b2, b3 = st.columns(3)
        uname = str(user.get("username") or "admin")
        with b1:
            if st.button("Сохранить", type="primary", key="cp_dash_ms_save"):
                ok, msg = save_control_point_milestones_json(txt, uname)
                if ok:
                    if "cp_dash_milestones_json" in st.session_state:
                        del st.session_state["cp_dash_milestones_json"]
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        with b2:
            if st.button("Сбросить на встроенные правила", key="cp_dash_ms_reset"):
                ok, msg = save_control_point_milestones_json("", uname)
                if ok:
                    if "cp_dash_milestones_json" in st.session_state:
                        del st.session_state["cp_dash_milestones_json"]
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        with b3:
            st.download_button(
                "Скачать шаблон по умолчанию",
                default_js.encode("utf-8-sig"),
                "control_points_milestones_default.json",
                "application/json",
                key="cp_dash_dl_tpl",
            )
        with st.expander("Подсказка по полю match", expanded=False):
            st.markdown(
                "- **level** — уровень задачи MSP (например 5.0).\n"
                "- **names_any** — список подстрок для названия задачи.\n"
                "- **name_contains** — одна подстрока в названии.\n"
                "- **parent_l2_contains** — родитель уровня 2 (часто «Ковенанты»).\n"
                "- **block_contains** — подстрока функционального блока.\n"
                "- **phase_needles** / **phase_exclude_needles** — если в файле есть колонка «Фаза».\n\n"
                "Пустое сохранение через «Сбросить» восстанавливает встроенный список из кода."
            )


def dashboard_control_points(df):
    """
    Контрольные точки (MSP): матрица проектов × вехи по макету правок (скрин file-009).
    Администратор задаёт вехи и маппинг к MSP в блоке настроек на этой странице.
    """
    st.header("Контрольные точки")
    _render_control_points_admin_on_dashboard()
    if df is None or df.empty:
        st.warning("Загрузите данные MSP (проект).")
        return
    work = _control_points_prepare_msp_dates(df.copy())
    has_fact_col = "plan end" in work.columns or "actual finish" in work.columns
    if "base end" not in work.columns or not has_fact_col:
        st.warning(
            "Нужны колонки базового и фактического окончания задачи: **base end** и **plan end** "
            "(или **actual finish**). После загрузки через web/ они обычно уже переименованы; "
            "для «сырого» CSV см. список колонок ниже."
        )
        with st.expander("Диагностика колонок (если таблица не строится)", expanded=False):
            st.caption("Имена колонок в текущем наборе данных:")
            st.code(", ".join(str(c) for c in work.columns))
            hints = [
                c
                for c in work.columns
                if any(
                    k in str(c).lower()
                    for k in (
                        "нач",
                        "окон",
                        "finish",
                        "base",
                        "план",
                        "факт",
                        "baseline",
                    )
                )
            ]
            if hints:
                st.caption("Колонки, похожие на даты окончания:")
                st.code(", ".join(str(c) for c in hints))
        return
    render_control_points_dashboard(st, work, _TABLE_CSS)


def dashboard_project_schedule_chart(df):
    """График проекта: Гант по плану и базе MSP, фильтры, таблица с отклонениями."""

    def _norm_colname(s) -> str:
        """Жёсткая нормализация: BOM, NBSP, узкие пробелы, табы/переносы → один пробел; нижний регистр; trim."""
        t = str(s).replace("\ufeff", "").replace("\u00a0", " ").replace("\u202f", " ").replace("\u2007", " ")
        t = re.sub(r"[\s\t\n\r]+", " ", t).strip().lower()
        return t

    def _sched_col(d, candidates):
        cols_norm = {_norm_colname(c): c for c in d.columns}
        for name in candidates:
            n = _norm_colname(name)
            if n in cols_norm:
                return cols_norm[n]
        return None

    def _sched_wbs_tuple(val):
        try:
            if val is None or pd.isna(val):
                return ()
        except Exception:
            if val is None:
                return ()
        s = str(val).strip()
        if not s or s.lower() in ("nan", "none"):
            return ()
        parts = [p for p in re.split(r"[.\s/|>\\-]+", s) if p != ""]
        out = []
        for p in parts:
            try:
                out.append(int(float(p)))
            except (TypeError, ValueError):
                continue
        return tuple(out) if out else ()

    def _gantt_clean_task_label(s) -> str:
        """Убирает префикс «Задача» и номер из названий MSP («Задача 363248 …»)."""
        t = str(s).strip()
        if not t or t.lower() in ("nan", "none"):
            return ""
        t = re.sub(r"(?i)^\s*задача\s+\d+\s+", "", t)
        t = re.sub(r"(?i)^\s*задача\s+", "", t)
        return t.strip()

    def _gantt_find_percent_column(d: pd.DataFrame):
        """Колонка % выполнения MSP: разные имена в выгрузках / Excel."""
        if d is None or getattr(d, "empty", True):
            return None
        exact = [
            # Английские (MSP, Primavera, стандарт)
            "pct complete",
            "percent complete",
            "% complete",
            "percent_complete",
            "physical % complete",
            "physical percent complete",
            "Physical % Complete",
            "complete",
            "% done",
            "done %",
            "completion %",
            "completion percentage",
            "work complete",
            "% work complete",
            "actual % complete",
            "actual percent complete",
            # Русские (MSP, русская локаль)
            "Процент выполнения",
            "% завершения",
            "процент выполнения",
            "Процент_выполнения",
            "физический % завершения",
            "Физический % завершения",
            "физический процент завершения",
            "% выполнения",
            "Выполнение %",
            "выполнено %",
            "% завершён",
            "готовность %",
        ]
        hit = _sched_col(d, exact)
        if hit:
            return hit
        # Расширенный поиск по подстрокам (нижний регистр)
        for c in d.columns:
            sl = str(c).strip().lower().replace("_", " ")
            if any(x in sl for x in ("приоритет", "priority", "severity", "риск", "baseline")):
                continue
            has_pct = "%" in sl or "percent" in sl or "процент" in sl or "выполн" in sl or "заверш" in sl or "готовн" in sl
            has_done = "complete" in sl or "выполн" in sl or "заверш" in sl or "done" in sl or "готовн" in sl
            if has_pct and has_done:
                return c
        # Последний шанс: любая колонка с "%" в имени с числовыми данными
        for c in d.columns:
            sl = str(c).strip().lower()
            if "%" in sl and not any(x in sl for x in ("приоритет", "priority", "риск", "baseline", "бюджет", "budget")):
                vals = pd.to_numeric(d[c], errors="coerce")
                if vals.notna().sum() >= max(1, len(d) * 0.1):
                    return c
        return None

    def _gantt_coerce_pct_series(raw: pd.Series) -> pd.Series:
        """Число, строки с %, запятая; если все значения в [0,1] — трактуем как долю и ×100."""
        num = pd.to_numeric(raw, errors="coerce")

        def _parse_cell(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return np.nan
            if isinstance(v, (int, np.integer)):
                return float(v)
            if isinstance(v, float) and not pd.isna(v):
                return float(v)
            t = str(v)
            # BOM, NBSP, узкий неразрывный, цифровой пробел, обычные пробелы → ничего
            for ch in ("\ufeff", "\u00a0", "\u202f", "\u2007", " ", "\t", "\r", "\n"):
                t = t.replace(ch, "")
            if not t or t.lower() in ("nan", "nat", "none", "-", "—", ""):
                return np.nan
            tl = t.replace("%", "").replace(",", ".")
            try:
                return float(tl)
            except (TypeError, ValueError):
                return np.nan

        out = num.astype("float64")
        need = out.isna() & raw.notna()
        if need.any():
            out.loc[need] = raw.loc[need].map(_parse_cell)
        if out.notna().any():
            mx = float(out.max(skipna=True))
            mn = float(out.min(skipna=True))
            # MSP часто отдаёт доли 0–1; если максимум ≤ 1 — считаем процентами после ×100.
            if mx <= 1.000001 and mn >= 0.0:
                out = out * 100.0
        return out

    def _gantt_ru_date_ticks(lo, hi, max_ticks: int = 26):
        """Подписи делений оси X: месяцы по-русски (короткие аббревиатуры)."""
        if lo is None or hi is None or pd.isna(lo) or pd.isna(hi):
            return None, None
        lo = pd.Timestamp(lo)
        hi = pd.Timestamp(hi)
        if lo > hi:
            lo, hi = hi, lo
        span_days = max((hi - lo).days, 1)
        if span_days <= 45:
            freq = "1W"
        elif span_days <= 200:
            freq = "MS"
        elif span_days > 365 * 6:
            freq = "YS"
        elif span_days > 365 * 2:
            freq = "6MS"
        else:
            freq = "MS"
        try:
            rng = pd.date_range(lo.normalize(), hi.normalize(), freq=freq)
        except Exception:
            return None, None
        if len(rng) == 0:
            rng = pd.DatetimeIndex([lo, hi])
        if len(rng) > max_ticks:
            step = int(np.ceil(len(rng) / float(max_ticks)))
            rng = rng[:: max(step, 1)]
        abbr = {
            1: "янв.",
            2: "фев.",
            3: "мар.",
            4: "апр.",
            5: "мая",
            6: "июн.",
            7: "июл.",
            8: "авг.",
            9: "сен.",
            10: "окт.",
            11: "нояб.",
            12: "дек.",
        }
        ticktext = []
        for ts in rng:
            if freq == "1W":
                ticktext.append(ts.strftime("%d.%m.%Y"))
            else:
                ticktext.append(f"{abbr.get(ts.month, ts.month)} {ts.year}")
        return list(rng), ticktext

    def _fmt_dev_days(v) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        try:
            n = int(round(float(v)))
        except (TypeError, ValueError):
            return str(v).strip()
        if n == 0:
            return "0 дн."
        sign = "+" if n > 0 else ""
        return f"{sign}{n} дн."

    st.header("График проекта")
    with st.expander("Подсказка", expanded=False):
        st.caption(
            "Фильтры: проект (ур. 1), функциональный блок (ур. 2), уровень структуры MSP (3/4/5 или все), опционально — только лоты. "
            "Полосы: план и базовый план (если есть данные). "
            "Переключатель подписей: дата окончания или % выполнения — подпись сразу справа от конца полос этой строки (план и при наличии — база). "
            "Масштаб и панорама колесом мыши (scroll) включены; при странном поведении подписей — панель инструментов (+/−, рамка). "
            "Названия задач — в полосе слева от полей дат (xaxis.domain + аннотации xref x domain), чтобы не наезжали на полосы."
        )
    if df is None or df.empty:
        st.warning("Загрузите данные MSP.")
        return
    work = df.copy()
    if "plan start" not in work.columns or "plan end" not in work.columns:
        st.warning("Нужны колонки «План: начало» и «План: окончание» (после загрузки MSP: plan start / plan end).")
        pref = [c for c in ("project name", "task name", "plan start", "plan end") if c in work.columns]
        st.dataframe(work[pref].head(80) if pref else work.head(80), use_container_width=True, hide_index=True)
        return

    work["plan start"] = pd.to_datetime(work["plan start"], errors="coerce")
    work["plan end"] = pd.to_datetime(work["plan end"], errors="coerce")
    for bc in ("base start", "base end"):
        if bc in work.columns:
            work[bc] = pd.to_datetime(work[bc], errors="coerce")

    plot_df = work[work["plan start"].notna() & work["plan end"].notna()].copy()
    if plot_df.empty:
        st.info("Нет строк с заполненными «Начало» и «Окончание» плана.")
        return

    def _gantt_resolve_level_column(d: pd.DataFrame):
        """Колонка числового уровня иерархии MSP (Outline Level / level), если имя нестандартное."""
        if d is None or getattr(d, "empty", True):
            return None
        preferred = (
            "level",
            "outline level",
            "outline_level",
            "outline number",
            "исходный уровень",
            "исходный_уровень",
            "уровень",
        )
        cols_lower = {str(c).strip().lower(): c for c in d.columns}
        for w in preferred:
            if w in cols_lower:
                return cols_lower[w]
        for c in d.columns:
            sl = str(c).strip().lower()
            if "outline" in sl and "level" in sl.replace(" ", ""):
                return c
        for c in d.columns:
            sl = str(c).strip().lower()
            if "wbs" in sl and "level" in sl.replace(" ", ""):
                return c
        for c in d.columns:
            sl = str(c).strip().lower()
            if "уровень" in sl and "приоритет" not in sl and "риск" not in sl:
                return c
        return None

    proj_col = _sched_col(plot_df, ["project name", "Проект", "проект", "Project"])
    block_col = _sched_col(
        plot_df,
        ["block", "Блок", "Функциональный блок", "Functional block"],
    )
    level_col = _sched_col(
        plot_df,
        [
            "level",
            "level structure",
            "Outline Level",
            "outline level",
            "outline number",
            "WBS Level",
            "wbs level",
            "Уровень",
            "уровень структуры",
            "Уровень_структуры",
            "уровень иерархии",
            "Исходный уровень",
        ],
    ) or _gantt_resolve_level_column(plot_df)

    def _sched_col_contains(d, needles, exclude=()):
        """Первая колонка, в имени которой есть любая из подстрок (нижний регистр)."""
        if d is None or getattr(d, "empty", True):
            return None
        ex = tuple(str(x).lower() for x in exclude)
        for c in d.columns:
            sl = str(c).strip().lower()
            if any(e in sl for e in ex):
                continue
            for n in needles:
                if n.lower() in sl:
                    return c
        return None

    if not level_col:
        level_col = _sched_col_contains(
            plot_df,
            ("уровень структуры", "уровень_структуры", "outline level", "wbs level", "уровень", "level"),
            exclude=("приоритет", "риск", "severity"),
        )
    if not level_col and "level structure" in plot_df.columns:
        level_col = "level structure"

    def _gantt_best_level_column(d):
        """Эвристика по имени колонки (разные выгрузки MSP/Excel): уровень / outline / WBS."""
        if d is None or getattr(d, "empty", True):
            return None
        best_c, best_sc = None, 0
        for c in d.columns:
            raw = str(c).strip()
            s = raw.lower().replace("_", " ")
            s = re.sub(r"\s+", " ", s).strip()
            if "приоритет" in s or "риск" in s or "severity" in s:
                continue
            score = 0
            if s in ("level", "outline level", "outline_number", "wbs level"):
                score += 8
            if "outline" in s and "level" in s.replace(" ", ""):
                score += 7
            if "level structure" in s or "уровень структуры" in s:
                score += 6
            if s == "уровень" or s.endswith(" уровень"):
                score += 5
            if "wbs" in s and "level" in s.replace(" ", ""):
                score += 5
            if "исходный" in s and "уровень" in s:
                score += 5
            if "уровень" in s and "приоритет" not in s and "риск" not in s:
                score += 3
            if score > best_sc:
                best_sc, best_c = score, c
        return best_c if best_sc >= 3 else None

    if not level_col:
        level_col = _gantt_best_level_column(plot_df)
    lot_col = _sched_col(plot_df, ["lot", "Лот", "ЛОТ"])
    section_col = _sched_col(plot_df, ["section", "Раздел", "БЛОК", "блок"])
    building_col = _sched_col(
        plot_df,
        ["building", "Building", "строение", "Строение", "корпус", "Корпус", "объект", "Объект"],
    ) or _sched_col_contains(
        plot_df,
        ("строени", "building", "корпус", "объект"),
        exclude=("приоритет", "риск", "severity"),
    )

    sel_proj = "Все"
    sel_block = "Все"
    sel_building = "Все"

    _flt_cols = st.columns(5 if building_col else 4)
    f1 = _flt_cols[0]
    f2 = _flt_cols[1]
    _ix = 2
    f_building = None
    if building_col:
        f_building = _flt_cols[_ix]
        _ix += 1
    f_level = _flt_cols[_ix]
    f_view = _flt_cols[_ix + 1]

    with f1:
        if proj_col:
            projs = ["Все"] + sorted(plot_df[proj_col].dropna().astype(str).unique().tolist())
            sel_proj = st.selectbox("Проект (ур. 1)", projs, key="gantt_project_filter")
            if sel_proj != "Все":
                plot_df = plot_df[plot_df[proj_col].astype(str).str.strip() == str(sel_proj).strip()]
        else:
            st.caption("Колонка проекта не найдена.")
    with f2:
        if block_col:
            blocks = ["Все"] + sorted(plot_df[block_col].dropna().astype(str).unique().tolist())
            sel_block = st.selectbox("Функциональный блок (ур. 2)", blocks, key="gantt_block_filter")
            if sel_block != "Все":
                plot_df = plot_df[plot_df[block_col].astype(str).str.strip() == str(sel_block).strip()]
        else:
            st.caption("Нет колонки функционального блока.")
    if f_building is not None:
        with f_building:
            builds = ["Все"] + sorted(plot_df[building_col].dropna().astype(str).unique().tolist())
            sel_building = st.selectbox("Строение", builds, key="gantt_building_filter")
            if sel_building != "Все":
                plot_df = plot_df[
                    plot_df[building_col].astype(str).str.strip() == str(sel_building).strip()
                ]
    with f_level:
        level_opts = (
            "Все уровни",
            "Верхний уровень (4)",
            "Детальный уровень (5)",
            "Строения (3)",
        )
        level_sel = st.selectbox(
            "Уровень отображения задач",
            level_opts,
            index=0,
            key="gantt_level_display",
            help="По умолчанию — все уровни. Узкий фильтр по числу в колонке уровня MSP.",
        )
        if level_col and level_sel != "Все уровни":
            lvl_map = {
                "Верхний уровень (4)": 4,
                "Детальный уровень (5)": 5,
                "Строения (3)": 3,
            }
            target = int(lvl_map[level_sel])
            ln = pd.to_numeric(plot_df[level_col], errors="coerce")
            if ln.notna().any():
                plot_df = plot_df[ln == float(target)]
            else:
                wbs_dep = plot_df[level_col].map(_sched_wbs_tuple).map(
                    lambda t: int(len(t)) if t else np.nan
                )
                if wbs_dep.notna().any():
                    plot_df = plot_df[wbs_dep == target]
        elif not level_col:
            st.caption("Нет колонки уровня.")
    with f_view:
        view_mode = st.selectbox(
            "Вид отображения",
            ("Гантт (полосы)", "Линии дат"),
            index=0,
            key="gantt_view_mode",
            help="Режим визуализации: интервалы Гантта или отдельные точки дат начала/окончания.",
        )

    is_covenants = False
    try:
        if block_col and str(sel_block).strip() != "Все":
            is_covenants = "ковенант" in str(sel_block).strip().lower()
    except Exception:
        is_covenants = False

    lot_row_l, lot_row_r = st.columns(2)
    with lot_row_l:
        show_reasons = st.checkbox(
            "Показать причины отклонений",
            value=False,
            key="gantt_show_deviation_cols",
            help="В таблице под графиком — колонки «Причины отклонений» и «Заметки», если они есть в выгрузке MSP.",
        )
    with lot_row_r:
        show_lots = st.checkbox(
            "Отображать в лотах",
            value=False,
            key="gantt_show_lots",
            help="Только строки с заполненным лотом (если в данных есть колонка лота).",
        )
    if show_lots and lot_col and lot_col in plot_df.columns:
        lc = plot_df[lot_col].astype(str).str.strip()
        plot_df = plot_df[lc.ne("") & lc.str.lower().ne("nan") & plot_df[lot_col].notna()]
    elif show_lots and not lot_col:
        st.caption("Колонка лота не найдена — фильтр «в лотах» недоступен.")
    label_mode = st.radio(
        "Подписи у конца задач",
        ("Дата окончания", "% выполнения"),
        horizontal=True,
        index=0,
        key="gantt_bar_label_mode",
        help="Что показывать у правого края задачи: дату окончания или % выполнения из MSP.",
    )
    label_pct = label_mode == "% выполнения"
    label_density_mode = st.radio(
        "Плотность подписей",
        ("Умная плотность", "Показывать все подписи"),
        horizontal=True,
        index=0,
        key="gantt_label_density_mode",
        help="Умная плотность уменьшает наложение текста на плотных графиках.",
    )
    force_all_labels = label_density_mode == "Показывать все подписи"
    auto_compact_on_zoom = st.toggle(
        "Авто: защита от наложения при масштабировании страницы",
        value=True,
        key="gantt_auto_compact_on_zoom",
        help="Если график становится плотным (часто при zoom страницы), включается безопасная плотность подписей.",
    )

    if plot_df.empty:
        st.info("Нет строк после фильтров.")
        return

    task_col = _sched_col(plot_df, ["task name", "Task Name", "Название"])
    if not task_col:
        plot_df = plot_df.copy()
        plot_df["task name"] = plot_df.index.astype(str)
        task_col = "task name"

    plot_df = plot_df.copy()
    sort_cols = []
    sort_asc = []
    if level_col:
        lvl_num = pd.to_numeric(plot_df[level_col], errors="coerce")
        if lvl_num.notna().any():
            plot_df["_gantt_sort_lvl"] = lvl_num
            sort_cols.append("_gantt_sort_lvl")
            sort_asc.append(True)
        else:
            plot_df["_gantt_wbs"] = plot_df[level_col].map(_sched_wbs_tuple)

            def _sched_wbs_sort_key(t):
                if not t:
                    return ""
                return ".".join(f"{p:010d}" for p in t[:16])

            plot_df["_gantt_wbs_sort"] = plot_df["_gantt_wbs"].map(_sched_wbs_sort_key)
            if plot_df["_gantt_wbs"].map(len).gt(0).any():
                sort_cols.append("_gantt_wbs_sort")
                sort_asc.append(True)
        if section_col:
            sort_cols.append(section_col)
            sort_asc.append(True)
        if block_col:
            sort_cols.append(block_col)
            sort_asc.append(True)
        sort_cols.append(task_col)
        sort_asc.append(True)
        sort_cols.append("plan start")
        sort_asc.append(True)
    else:
        sort_cols = ["plan start"]
        sort_asc = [True]
    plot_df = plot_df.sort_values(sort_cols, ascending=sort_asc, na_position="last").head(400)

    _gantt_pct_col_used = None
    plot_df = plot_df.copy()

    def _pick_best_pct_series(d: pd.DataFrame, col_name) -> pd.Series:
        """Если колонка дублируется (после rename/merge), берём первую с непустыми значениями."""
        sub = d[col_name]
        if isinstance(sub, pd.DataFrame):
            best = None
            best_cnt = -1
            for i in range(sub.shape[1]):
                s = _gantt_coerce_pct_series(sub.iloc[:, i])
                cnt = int(s.notna().sum())
                if cnt > best_cnt:
                    best_cnt = cnt
                    best = s
            return best if best is not None else pd.Series(np.nan, index=d.index)
        return _gantt_coerce_pct_series(sub)

    # Поиск колонки % через _sched_col (регистронезависимый) — охватывает "Pct Complete", "PCT COMPLETE" и т.д.
    _pc_raw = _sched_col(plot_df, ["pct complete"]) or _gantt_find_percent_column(plot_df)
    if _pc_raw:
        plot_df["pct complete"] = _pick_best_pct_series(plot_df, _pc_raw)
        _gantt_pct_col_used = _pc_raw
    else:
        plot_df["pct complete"] = np.nan

    if label_pct:
        _pct_series = plot_df["pct complete"]
        if isinstance(_pct_series, pd.DataFrame):
            _pct_series = _pct_series.iloc[:, 0]
        _has_data = bool(_pct_series.notna().any())
        if _gantt_pct_col_used is None:
            _avail_cols = [c for c in plot_df.columns if "%" in str(c) or any(
                w in str(c).lower() for w in ("percent", "complete", "процент", "выполн", "заверш", "готовн")
            )]
            _hint = (f" Похожие колонки в файле: **{', '.join(_avail_cols[:8])}**." if _avail_cols else
                     f" Колонки файла: {', '.join(str(c) for c in plot_df.columns[:15])}…")
            st.warning("Не найдена колонка процента выполнения — у концов полос будет «н/д»." + _hint)
        elif not _has_data:
            st.caption(
                f"Колонка процента выполнения найдена («{_gantt_pct_col_used}»), "
                "но все значения пустые — у концов полос будет «н/д»."
            )
        # Диагностический блок (открытый по умолчанию только при отсутствии данных).
        with st.expander("Диагностика: колонка % выполнения", expanded=(not _has_data)):
            _all_pct_like = [
                c for c in plot_df.columns
                if "%" in str(c)
                or any(w in str(c).lower() for w in ("percent", "complete", "процент", "выполн", "заверш", "готовн"))
            ]
            st.write(f"Использованная колонка: **{_gantt_pct_col_used or '— не найдена —'}**")
            st.write(f"Не-пустых значений после парсинга: **{int(_pct_series.notna().sum())}** из {len(_pct_series)}")
            st.write(f"Все колонки с признаками %: {_all_pct_like or '—'}")
            # Диагностика скрытых символов в именах: показываем repr() — будет видно \xa0, \ufeff и пр.
            _hidden = []
            for c in _all_pct_like:
                raw = str(c)
                if any(ch in raw for ch in ("\xa0", "\ufeff", "\u202f", "\u2007")) or raw != raw.strip():
                    _hidden.append({"имя (repr)": repr(raw), "коды": [hex(ord(ch)) for ch in raw]})
            if _hidden:
                st.warning("В именах колонок-кандидатов найдены скрытые символы:")
                st.json(_hidden)
            # Подсказка про дубликаты после ремапа MSP-колонок.
            _dups = [c for c in set(map(str, plot_df.columns)) if list(plot_df.columns).count(c) > 1]
            if _dups:
                st.warning(
                    f"Найдены **дублирующиеся колонки** после загрузки: {_dups}. "
                    "Это типично, когда исходный файл уже содержит «pct complete», "
                    "а маппинг MSP добавляет вторую копию из «Процент_завершения». "
                    "Сейчас берётся колонка с большим числом непустых значений."
                )
            if _gantt_pct_col_used and _pc_raw:
                _src = plot_df[_pc_raw]
                if isinstance(_src, pd.DataFrame):
                    _src = _src.iloc[:, 0]
                st.dataframe(
                    _src.dropna().astype(str).head(10).to_frame(name="первые 10 непустых значений"),
                    use_container_width=True,
                )

    lvl_for_indent = None
    if level_col:
        lvl_for_indent = pd.to_numeric(plot_df[level_col], errors="coerce")
    if level_col and (lvl_for_indent is None or not lvl_for_indent.notna().any()):
        wbs_depth = plot_df[level_col].map(_sched_wbs_tuple).map(lambda t: float(len(t)) if t else np.nan)
        if wbs_depth.notna().any():
            lvl_for_indent = wbs_depth
    if lvl_for_indent is None or not lvl_for_indent.notna().any():
        lvl_for_indent = pd.Series(np.nan, index=plot_df.index)
    indents = []
    for ix in plot_df.index:
        v = lvl_for_indent.loc[ix] if ix in lvl_for_indent.index else np.nan
        if pd.notna(v) and np.isfinite(float(v)):
            d = max(0, int(round(float(v))) - 1)
        else:
            d = 0
        indents.append(d)
    names = plot_df[task_col].fillna("").astype(str).map(_gantt_clean_task_label)
    y_labels = []
    for name, d in zip(names.tolist(), indents):
        prefix = ("  " * d) + ("— " if d > 0 else "")
        y_labels.append(prefix + name)

    def _gantt_trunc_label(s, n=86):
        s = str(s)
        return s if len(s) <= n else s[: max(1, n - 1)] + "…"

    def _gantt_readability_policy(d: pd.DataFrame) -> dict:
        """Авто-политика читаемости по плотности данных."""
        n_rows = int(len(d.index))
        lo = pd.to_datetime(d.get("plan start"), errors="coerce").min()
        hi = pd.to_datetime(d.get("plan end"), errors="coerce").max()
        if "base start" in d.columns:
            _bs = pd.to_datetime(d["base start"], errors="coerce")
            if _bs.notna().any():
                lo = min(lo, _bs.min()) if pd.notna(lo) else _bs.min()
        if "base end" in d.columns:
            _be = pd.to_datetime(d["base end"], errors="coerce")
            if _be.notna().any():
                hi = max(hi, _be.max()) if pd.notna(hi) else _be.max()
        span_days = 120.0
        if pd.notna(lo) and pd.notna(hi):
            span_days = max(1.0, (hi - lo).total_seconds() / 86400.0)
        # Подстройка под реальные MSP-выгрузки: читаемость важнее плотности меток.
        is_dense = n_rows > 55 or span_days > 540
        is_very_dense = n_rows > 120 or span_days > 900
        return {
            "date_fmt": "%d.%m.%y" if is_dense else "%d.%m.%Y",
            "label_font": 9 if is_very_dense else (10 if is_dense else 11),
            "task_font": 9 if is_very_dense else (10 if is_dense else 11),
            "max_ticks": 10 if is_very_dense else (16 if is_dense else 24),
            "right_pad_min": 380 if is_dense else 320,
            "right_pad_max": 820 if is_dense else 700,
            "text_step": 4 if is_very_dense else (2 if is_dense else 1),
            "marker_size": 6 if is_very_dense else (7 if is_dense else 8),
            "is_dense": is_dense,
            "is_very_dense": is_very_dense,
        }

    def _build_date_lines_figure(
        d: pd.DataFrame,
        has_base_dates: bool,
        show_pct_labels: bool,
        policy: dict,
    ):
        """Режим «Линии дат»: отдельные серии по датам начала/окончания без интервалов."""
        _df = d.copy()
        _y = _df["_gantt_y_label"].astype(str)
        fig = go.Figure()
        pct_series = pd.to_numeric(_df.get("pct complete"), errors="coerce")
        date_fmt = policy.get("date_fmt", "%d.%m.%Y")
        _effective_force_all = bool(
            force_all_labels and not (auto_compact_on_zoom and policy.get("is_dense"))
        )
        text_step = 1 if _effective_force_all else int(max(1, policy.get("text_step", 1)))

        series_def = [
            ("plan start", "План: начало", "#57b8ff", "circle"),
            ("plan end", "План: окончание", "#2E86AB", "diamond"),
            ("base start", "База: начало", "#b99cff", "circle-open"),
            ("base end", "База: окончание", "#C084FC", "diamond-open"),
        ]
        for col, legend_name, color, symbol in series_def:
            if col not in _df.columns:
                continue
            xvals = pd.to_datetime(_df[col], errors="coerce")
            if not xvals.notna().any():
                continue
            text_vals = [""] * len(_df.index)
            show_end_labels = col in ("plan end", "base end")
            if show_end_labels:
                for i, (xv, pv) in enumerate(zip(xvals.tolist(), pct_series.tolist())):
                    if i % text_step != 0:
                        continue
                    if pd.isna(xv):
                        text_vals[i] = ""
                        continue
                    if show_pct_labels:
                        if pd.notna(pv):
                            try:
                                text_vals[i] = f"{float(pv):.0f} %"
                            except (TypeError, ValueError):
                                text_vals[i] = "н/д"
                        else:
                            text_vals[i] = "н/д"
                    else:
                        text_vals[i] = pd.Timestamp(xv).strftime(date_fmt)

            fig.add_trace(
                go.Scatter(
                    x=xvals,
                    y=_y,
                    mode="markers+text" if show_end_labels else "markers",
                    text=text_vals if show_end_labels else None,
                    textposition="middle right",
                    textfont=dict(size=policy.get("label_font", 11), color="#f8fafc"),
                    marker=dict(
                        size=policy.get("marker_size", 8),
                        color=color,
                        symbol=symbol,
                        line=dict(width=1, color="#ffffff"),
                    ),
                    name=legend_name,
                    customdata=np.stack(
                        [
                            _df[task_col].astype(str).values,
                            xvals.dt.strftime("%d.%m.%Y").fillna("").values,
                        ],
                        axis=-1,
                    ),
                    hovertemplate=(
                        "<b>%{customdata[0]}</b><br>"
                        + f"{legend_name}: "
                        + "%{customdata[1]}<extra></extra>"
                    ),
                )
            )

        n = len(_df.index)
        row_h = 34 if policy.get("is_dense") else 30
        chart_h = min(2600, max(220, 96 + row_h * n))
        max_len = int(_df["_gantt_y_label"].astype(str).str.len().max() or 12)
        left_m = int(
            max(
                170 if policy.get("is_dense") else 160,
                min(560, 110 + int(min(max_len, 150) * (3.0 if policy.get("is_dense") else 3.15))),
            )
        )

        fig.update_layout(
            height=chart_h,
            margin=dict(l=left_m, r=(140 if policy.get("is_dense") else 120), t=48, b=96),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            uirevision="gantt_project_schedule_lines",
        )
        fig.update_yaxes(
            autorange="reversed",
            title=dict(text=""),
            tickfont=dict(size=policy.get("task_font", 11), color=TABLE_TEXT_COLOR),
            showticklabels=True,
            ticklabelposition="outside",
            ticklabeloverflow="allow",
            automargin=True,
            fixedrange=True,
            categoryorder="array",
            categoryarray=_y.tolist(),
        )
        fig.update_xaxes(title_text="Дата", automargin=True, showgrid=True)

        try:
            _lo = pd.to_datetime(_df["plan start"], errors="coerce").min()
            _hi = pd.to_datetime(_df["plan end"], errors="coerce").max()
            if has_base_dates:
                if "base start" in _df.columns:
                    _bs = pd.to_datetime(_df["base start"], errors="coerce")
                    if _bs.notna().any():
                        _lo = min(_lo, _bs.min()) if pd.notna(_lo) else _bs.min()
                if "base end" in _df.columns:
                    _be = pd.to_datetime(_df["base end"], errors="coerce")
                    if _be.notna().any():
                        _hi = max(_hi, _be.max()) if pd.notna(_hi) else _be.max()
            if pd.notna(_lo) and pd.notna(_hi):
                _span = max((_hi - _lo).total_seconds() / 86400.0, 1.0)
                _pad = timedelta(days=max(24.0, _span * 0.07))
                _lo_pad = _lo - _pad
                _hi_pad = _hi + _pad
                fig.update_xaxes(range=[_lo_pad, _hi_pad], autorange=False)
                tvals, ttext = _gantt_ru_date_ticks(_lo_pad, _hi_pad, max_ticks=policy.get("max_ticks", 22))
                if tvals and ttext and len(tvals) == len(ttext):
                    fig.update_xaxes(
                        type="date",
                        tickmode="array",
                        tickvals=[pd.Timestamp(t).strftime("%Y-%m-%d") for t in tvals],
                        ticktext=ttext,
                        tickangle=0,
                        tickformat="",
                    )
        except Exception:
            pass

        fig = apply_chart_background(fig, skip_uniformtext=True)
        return fig

    def _gantt_find_fact_end_column(d: pd.DataFrame):
        """Колонка фактического окончания (если есть) для режима «Ковенанты»."""
        if d is None or getattr(d, "empty", True):
            return None
        hit = _sched_col(
            d,
            [
                "actual finish",
                "Actual Finish",
                "actual end",
                "Actual End",
                "fact end",
                "Fact End",
                "факт окончание",
                "Факт окончание",
                "факт: окончание",
            ],
        )
        if hit:
            return hit
        for c in d.columns:
            sl = str(c).strip().lower().replace("_", " ")
            if ("actual" in sl or "факт" in sl) and any(x in sl for x in ("finish", "end", "оконч")):
                return c
        return None

    def _build_covenants_points_figure(d: pd.DataFrame, policy: dict):
        """Режим «Ковенанты»: базовое окончание (синяя точка) и окончание (красная) с подписями дат."""
        _df = d.copy()
        _y = _df["_gantt_y_label"].astype(str)
        date_fmt = policy.get("date_fmt", "%d.%m.%Y")

        base_end = (
            pd.to_datetime(_df["base end"], errors="coerce") if "base end" in _df.columns else pd.Series(pd.NaT, index=_df.index)
        )
        fact_end_col = _gantt_find_fact_end_column(_df)
        fact_end = (
            pd.to_datetime(_df[fact_end_col], errors="coerce")
            if fact_end_col and fact_end_col in _df.columns
            else pd.to_datetime(_df["plan end"], errors="coerce")
        )
        fact_label = "Факт: окончание" if fact_end_col else "План: окончание"

        def _fmt_ts(ts):
            if ts is None or (isinstance(ts, float) and pd.isna(ts)):
                return ""
            try:
                if pd.isna(ts):
                    return ""
            except Exception:
                pass
            try:
                return pd.Timestamp(ts).strftime(date_fmt)
            except Exception:
                return str(ts).strip()

        base_text = [_fmt_ts(x) for x in base_end.tolist()]
        fact_text = [_fmt_ts(x) for x in fact_end.tolist()]

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=base_end,
                y=_y,
                mode="markers+text",
                text=base_text,
                textposition="middle right",
                textfont=dict(size=policy.get("label_font", 11), color="#f8fafc"),
                marker=dict(
                    size=policy.get("marker_size", 8),
                    color="#3B82F6",
                    symbol="circle",
                    line=dict(width=1, color="#ffffff"),
                ),
                name="Базовое окончание",
                customdata=np.stack(
                    [
                        _df[task_col].astype(str).values,
                        pd.to_datetime(base_end, errors="coerce").dt.strftime("%d.%m.%Y").fillna("").values,
                    ],
                    axis=-1,
                ),
                hovertemplate="<b>%{customdata[0]}</b><br>База: %{customdata[1]}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=fact_end,
                y=_y,
                mode="markers+text",
                text=fact_text,
                textposition="middle right",
                textfont=dict(size=policy.get("label_font", 11), color="#f8fafc"),
                marker=dict(
                    size=policy.get("marker_size", 8),
                    color="#EF4444",
                    symbol="diamond",
                    line=dict(width=1, color="#ffffff"),
                ),
                name=fact_label,
                customdata=np.stack(
                    [
                        _df[task_col].astype(str).values,
                        pd.to_datetime(fact_end, errors="coerce").dt.strftime("%d.%m.%Y").fillna("").values,
                    ],
                    axis=-1,
                ),
                hovertemplate="<b>%{customdata[0]}</b><br>"
                + f"{fact_label}: "
                + "%{customdata[1]}<extra></extra>",
            )
        )

        n = len(_df.index)
        row_h = 34 if policy.get("is_dense") else 30
        chart_h = min(2600, max(220, 96 + row_h * n))
        max_len = int(_df["_gantt_y_label"].astype(str).str.len().max() or 12)
        left_m = int(
            max(
                170 if policy.get("is_dense") else 160,
                min(560, 110 + int(min(max_len, 150) * (3.0 if policy.get("is_dense") else 3.15))),
            )
        )

        fig.update_layout(
            height=chart_h,
            margin=dict(l=left_m, r=(160 if policy.get("is_dense") else 140), t=48, b=96),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            uirevision="gantt_project_schedule_covenants",
        )
        fig.update_yaxes(
            autorange="reversed",
            title=dict(text=""),
            tickfont=dict(size=policy.get("task_font", 11), color=TABLE_TEXT_COLOR),
            showticklabels=True,
            ticklabelposition="outside",
            ticklabeloverflow="allow",
            automargin=True,
            fixedrange=True,
            categoryorder="array",
            categoryarray=_y.tolist(),
        )
        fig.update_xaxes(title_text="Дата", automargin=True, showgrid=True)

        try:
            _lo = pd.concat([base_end, fact_end]).min()
            _hi = pd.concat([base_end, fact_end]).max()
            if pd.notna(_lo) and pd.notna(_hi):
                _span = max((_hi - _lo).total_seconds() / 86400.0, 1.0)
                _pad = timedelta(days=max(24.0, _span * 0.07))
                _lo_pad = _lo - _pad
                _hi_pad = _hi + _pad
                fig.update_xaxes(range=[_lo_pad, _hi_pad], autorange=False)
                tvals, ttext = _gantt_ru_date_ticks(_lo_pad, _hi_pad, max_ticks=policy.get("max_ticks", 22))
                if tvals and ttext and len(tvals) == len(ttext):
                    fig.update_xaxes(
                        type="date",
                        tickmode="array",
                        tickvals=[pd.Timestamp(t).strftime("%Y-%m-%d") for t in tvals],
                        ticktext=ttext,
                        tickangle=0,
                        tickformat="",
                    )
        except Exception:
            pass

        fig = apply_chart_background(fig, skip_uniformtext=True)
        return fig, fact_end_col, fact_label

    plot_df["_gantt_y_label"] = [_gantt_trunc_label(s) for s in y_labels]
    _readability = _gantt_readability_policy(plot_df)
    _effective_force_all = bool(
        force_all_labels and not (auto_compact_on_zoom and _readability.get("is_dense"))
    )
    if force_all_labels and not _effective_force_all:
        st.caption(
            "Режим «Показывать все подписи» автоматически ограничен для защиты от наложений в плотном/масштабированном виде."
        )

    has_base = "base start" in plot_df.columns and "base end" in plot_df.columns
    if has_base:
        has_base = plot_df["base start"].notna().any() and plot_df["base end"].notna().any()
    if not has_base:
        st.info("В данных нет заполненных «Базовое начало» / «Базовое окончание» — на диаграмме только текущий план.")

    plan_texts = []
    base_tasks, base_starts, base_ends = [], [], []

    # Подготовим pct complete как гарантированную Series (на случай дубликатов колонок).
    if "pct complete" in plot_df.columns:
        _pc_obj = plot_df["pct complete"]
        if isinstance(_pc_obj, pd.DataFrame):
            _pc_obj = _pc_obj.iloc[:, 0]
        _pct_values = _pc_obj.tolist()
    else:
        _pct_values = [np.nan] * len(plot_df)

    for _i, (_idx, row) in enumerate(plot_df.iterrows()):
        ps, pe = row["plan start"], row["plan end"]
        pe_d = pe.strftime(_readability["date_fmt"]) if hasattr(pe, "strftime") else str(pe)
        pv = _pct_values[_i] if _i < len(_pct_values) else np.nan
        if label_pct:
            if pd.notna(pv):
                try:
                    plan_texts.append(f"{float(pv):.0f} %")
                except (TypeError, ValueError):
                    plan_texts.append("н/д")
            else:
                plan_texts.append("н/д")
        else:
            plan_texts.append(pe_d)
        if has_base:
            y = row["_gantt_y_label"]
            bs, be = row.get("base start"), row.get("base end")
            if pd.notna(bs) and pd.notna(be):
                base_tasks.append(y)
                base_starts.append(bs)
                base_ends.append(be)

    # Подписи у правого края каждой строки: одна строка текста (без второй строки "база"),
    # чтобы уменьшить наложение при масштабировании страницы.
    right_labels = []
    for i, (_, row) in enumerate(plot_df.iterrows()):
        top = str(plan_texts[i]) if i < len(plan_texts) else ""
        if has_base and not label_pct:
            # Для даты показываем правый конец (макс. из план/база), чтобы подпись стояла у крайнего столбца.
            pev = row.get("plan end")
            bev = row.get("base end")
            ends = []
            if pd.notna(pev):
                ends.append(pd.Timestamp(pev))
            if pd.notna(bev):
                ends.append(pd.Timestamp(bev))
            if ends:
                top = max(ends).strftime(_readability["date_fmt"])
        right_labels.append(top)

    _rl_lens = [len(str(s).replace("\n", " ")) for s in right_labels if str(s).strip()]
    _max_rl = max(_rl_lens, default=0)
    # Запас справа под подписи у концов полос (дата / %).
    # При 15-16px шрифте нужно больше пространства.
    right_m = int(
        min(
            300,
            max(110, 80 + min(_max_rl, 20) * 9),
        )
    )

    vis = pd.DataFrame(
        {
            "План: начало": plot_df["plan start"].values,
            "План: окончание": plot_df["plan end"].values,
            "Название": plot_df["_gantt_y_label"].values,
        },
        index=plot_df.index,
    )
    vis["_полное_название"] = names.values
    vis["_начало_стр"] = pd.to_datetime(plot_df["plan start"], errors="coerce").dt.strftime("%d.%m.%Y")
    vis["_конец_стр"] = pd.to_datetime(plot_df["plan end"], errors="coerce").dt.strftime("%d.%m.%Y")
    # Не задаём color в px.timeline: иначе Express режет данные на несколько trace и
    # text=plan_texts не совпадает с рядами — подписи у полос пропадают.
    _tl_kwargs = dict(
        x_start="План: начало",
        x_end="План: окончание",
        y="Название",
        custom_data=["_полное_название", "_начало_стр", "_конец_стр"],
    )
    try:
        fig_gantt = px.timeline(vis, **_tl_kwargs)
    except Exception as e:
        st.warning(f"Не удалось построить диаграмму: {e}")
        st.dataframe(plot_df.head(50), use_container_width=True)
        return
    # Явно обновляем только trace плана (data[0]): подписи даты/% — отдельным текстовым trace справа (см. ниже),
    # т.к. text на Bar часто не виден при group/barmode и длинной оси X.
    _n_tasks = len(plot_df)
    try:
        fig_gantt.data[0].update(
            hovertemplate=(
                "%{customdata[0]}<br>"
                "План: начало: %{customdata[1]}<br>"
                "План: окончание: %{customdata[2]}<br>"
                "<extra></extra>"
            ),
            marker=dict(color="#2E86AB"),
            text=[""] * _n_tasks,
            textposition="none",
        )
    except Exception as e:
        st.warning(f"Не удалось настроить полосы плана: {e}")

    if base_tasks:
        fig_gantt.add_trace(
            go.Bar(
                x=base_ends,
                base=base_starts,
                y=base_tasks,
                orientation="h",
                name="Базовое начало–окончание",
                marker_color="#C084FC",
                text=[""] * len(base_tasks),
                textposition="none",
                hovertemplate=(
                    "<b>%{y}</b><br>База: %{base|%d.%m.%Y} — %{x|%d.%m.%Y}<extra></extra>"
                ),
            )
        )
        fig_gantt.update_layout(barmode="group")

    n = len(plot_df)
    row_h = 40 if _readability.get("is_dense") else 36
    chart_h = min(3200, max(300, 100 + row_h * n))
    max_len = int(plot_df["_gantt_y_label"].astype(str).str.len().max() or 12)

    # Доля ширины под левую панель с названиями задач (xaxis2).
    # Scatter-trace рендерится на xaxis2 (anchor="y") — стабильно при прокрутке/зуме дат.
    _x_lo = float(min(0.44, max(0.24, 0.16 + min(max_len, 140) * 0.00175)))
    left_m = 6   # margin слева маленький: метки внутри xaxis2, не в margin

    _task_font_size = max(12, _readability.get("task_font", 11) + 1)

    # Y-ось: категории без нативных подписей (заменяем Scatter-trace на xaxis2).
    fig_gantt.update_yaxes(
        autorange="reversed",
        title=dict(text=""),
        side="left",
        showticklabels=False,
        categoryorder="array",
        categoryarray=vis["Название"].tolist(),
        automargin=False,
        fixedrange=True,
    )
    fig_gantt.update_layout(xaxis=dict(
        domain=[_x_lo, 1.0],
        title_text="",
        automargin=False,
        showgrid=True,
    ))

    # Левовыровненные названия задач: Scatter на xaxis2 (домен [0, x_lo], anchor="y").
    # Позиции по Y совпадают с барами, т.к. оба trace делят один yaxis.
    # Позиции по X (xaxis2, fixedrange=True) не сдвигаются при панировании дат.
    fig_gantt.add_trace(
        go.Scatter(
            x=[0.018] * len(plot_df),
            y=plot_df["_gantt_y_label"].tolist(),
            mode="text",
            text=[_gantt_trunc_label(s, 55) for s in plot_df["_gantt_y_label"].tolist()],
            textposition="middle right",
            textfont=dict(size=_task_font_size, color=TABLE_TEXT_COLOR, family="Arial"),
            xaxis="x2",
            yaxis="y",
            showlegend=False,
            hoverinfo="skip",
            cliponaxis=False,
        )
    )
    fig_gantt.update_layout(
        xaxis2=dict(
            domain=[0.0, _x_lo],
            range=[0, 1],
            fixedrange=True,
            showticklabels=False,
            showgrid=False,
            zeroline=False,
            showline=False,
            visible=False,
            anchor="y",          # ключевой параметр: делит yaxis с xaxis
        ),
    )

    _lo_pad = _hi_pad = None
    # Подписи у концов полос — отдельный Scatter(mode=text): на date-оси надёжнее, чем layout.annotations.
    end_label_x: list = []
    end_label_y: list = []
    end_label_text: list = []
    fig_gantt.update_layout(
        height=chart_h,
        margin=dict(l=left_m, r=right_m, t=48, b=48),
        bargap=0.32,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    # Запас по оси X + подписи сразу справа от конца полос этой строки (не одна общая колонка по max(hi)).
    try:
        ps = pd.to_datetime(plot_df["plan start"], errors="coerce")
        pe = pd.to_datetime(plot_df["plan end"], errors="coerce")
        lo = ps.min()
        hi = pe.max()
        if has_base and "base start" in plot_df.columns and "base end" in plot_df.columns:
            bs = pd.to_datetime(plot_df["base start"], errors="coerce")
            be = pd.to_datetime(plot_df["base end"], errors="coerce")
            lo = pd.concat([pd.Series([lo]), bs]).min()
            hi = pd.concat([pd.Series([hi]), be]).max()
        if pd.notna(lo) and pd.notna(hi):
            span_days = max((hi - lo).total_seconds() / 86400.0, 1.0)
            pad = timedelta(days=max(45.0, span_days * 0.09))
            off_ann = timedelta(days=max(4.0, span_days * 0.018))  # отступ увеличен: метка правее баров
            tail = timedelta(days=max(18.0, span_days * 0.09))
            # В режиме % выполнения — всегда показываем все строки (иначе % теряется).
            _step = 1 if (_effective_force_all or label_pct) else int(max(1, _readability.get("text_step", 1)))
            for i, (_, row) in enumerate(plot_df.iterrows()):
                if i % _step != 0:
                    continue
                y = row["_gantt_y_label"]
                ends = []
                pev = row.get("plan end")
                if pd.notna(pev):
                    ends.append(pd.Timestamp(pev))
                if has_base:
                    bs, be = row.get("base start"), row.get("base end")
                    if pd.notna(bs) and pd.notna(be):
                        ends.append(pd.Timestamp(be))
                if not ends:
                    continue
                txt = right_labels[i] if i < len(right_labels) else ""
                if not str(txt).strip():
                    continue
                # Точка чуть правее конца полосы; подпись — textposition middle right (текст правее точки).
                x_mark = max(ends) + off_ann
                end_label_x.append(x_mark)
                end_label_y.append(y)
                end_label_text.append(str(txt))
            _lo_pad = lo - pad
            if end_label_x:
                ann_x_max = max(pd.Timestamp(x) for x in end_label_x)
                _hi_pad = max(hi + pad, ann_x_max + tail)
            else:
                _hi_pad = hi + pad
            fig_gantt.update_layout(xaxis=dict(range=[_lo_pad, _hi_pad], autorange=False))
    except Exception:
        pass
    # skip_uniformtext: глобальный apply_chart_background задаёт uniformtext mode=hide —
    # из‑за этого подписи у горизонтальных полос могут не отображаться.
    fig_gantt = apply_chart_background(fig_gantt, skip_uniformtext=True)
    try:
        fig_gantt.update_yaxes(automargin=False, fixedrange=True, showticklabels=False)
        fig_gantt.update_layout(
            margin=dict(l=left_m, r=right_m, t=48, b=48),
            uirevision="gantt_project_schedule",
            xaxis=dict(domain=[_x_lo, 1.0]),
            xaxis2=dict(
                domain=[0.0, _x_lo],
                range=[0, 1],
                fixedrange=True,
                showticklabels=False,
                showgrid=False,
                zeroline=False,
                showline=False,
                visible=False,
                anchor="y",
            ),
        )
    except Exception:
        pass
    try:
        if len(fig_gantt.data) > 0:
            fig_gantt.data[0].name = "План (начало–окончание)"
    except Exception:
        pass
    # Русские подписи месяцев на оси X (tickvals в ISO — иначе Plotly оставляет англ. локаль).
    try:
        if _lo_pad is not None and _hi_pad is not None:
            tvals, ttext = _gantt_ru_date_ticks(
                _lo_pad,
                _hi_pad,
                max_ticks=int(_readability.get("max_ticks", 26)),
            )
            if tvals and ttext and len(tvals) == len(ttext):
                tickvals_iso = [pd.Timestamp(t).strftime("%Y-%m-%d") for t in tvals]
                fig_gantt.update_layout(xaxis=dict(
                    type="date",
                    tickmode="array",
                    tickvals=tickvals_iso,
                    ticktext=ttext,
                    tickangle=0,
                    tickformat="",
                ))
    except Exception:
        pass
    if _lo_pad is not None and _hi_pad is not None:
        try:
            fig_gantt.update_layout(xaxis=dict(range=[_lo_pad, _hi_pad], autorange=False))
        except Exception:
            pass
    if end_label_x:
        try:
            _lbl_size = max(15, _readability.get("label_font", 11) + 4)
            fig_gantt.add_trace(
                go.Scatter(
                    x=end_label_x,
                    y=end_label_y,
                    mode="text",
                    text=end_label_text,
                    textfont=dict(size=_lbl_size, color="#ffffff", family="Arial"),
                    textposition="middle right",
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            try:
                fig_gantt.data[-1].update(cliponaxis=False)
            except Exception:
                pass
        except Exception as e:
            st.warning(f"Подписи у концов полос: {e}")
    # Названия задач отображаются нативными tick labels Y-оси (showticklabels=True),
    # что гарантирует корректное позиционирование при любом масштабе страницы.

    if is_covenants:
        if "base end" not in plot_df.columns or not pd.to_datetime(plot_df["base end"], errors="coerce").notna().any():
            st.info(
                "Для режима «Ковенанты» нужно «base end» (базовое окончание). Сейчас в данных базовые окончания не заполнены — "
                "точки базового плана будут отсутствовать."
            )
        fig_cov, _fact_end_col, _fact_label = _build_covenants_points_figure(plot_df, policy=_readability)
        render_chart(
            fig_cov,
            key="gantt_project_schedule_covenants",
            caption_below=(
                "Ковенанты: синяя точка — базовое окончание, красная — "
                + _fact_label.lower()
                + "; подписи рядом с точками — даты."
            ),
            skip_clamp_zoom=True,
        )
    elif view_mode == "Линии дат":
        fig_lines = _build_date_lines_figure(
            plot_df,
            has_base_dates=has_base,
            show_pct_labels=label_pct,
            policy=_readability,
        )
        render_chart(
            fig_lines,
            key="gantt_project_schedule_lines",
            caption_below=(
                "Линии дат: План/База по началу и окончанию; подписи справа — "
                + ("% выполнения" if label_pct else "дата окончания")
                + ". Масштаб и панорама — колесом мыши или панелью (+/−, рамка)."
            ),
            skip_clamp_zoom=True,
        )
    else:
        # Гантт: не clamp’ить ось X; scrollZoom — как в общем _PLOTLY_CONFIG (колесо над графиком).
        render_chart(
            fig_gantt,
            key="gantt_project_schedule",
            caption_below="План (Начало–Окончание) и базовый план; подписи — справа от концов полос (план и при наличии — база). Масштаб и панорама — колесом мыши или панелью (+/−, рамка).",
            skip_clamp_zoom=True,
        )

    st.caption("Таблица под графиком")

    dev_start_src = _sched_col(
        plot_df,
        ["deviation start days", "Отклонение_начала", "deviation start"],
    )
    dev_end_src = _sched_col(
        plot_df,
        ["deviation in days", "Отклонение_окончания"],
    )
    reason_src = _sched_col(plot_df, ["reason of deviation", "Причины_отклонений", "причина"])
    notes_src = _sched_col(plot_df, ["notes", "Заметки"])

    if is_covenants:
        base_end = (
            pd.to_datetime(plot_df["base end"], errors="coerce")
            if "base end" in plot_df.columns
            else pd.Series(pd.NaT, index=plot_df.index)
        )
        fact_end_col = _gantt_find_fact_end_column(plot_df)
        end_used = (
            pd.to_datetime(plot_df[fact_end_col], errors="coerce")
            if fact_end_col and fact_end_col in plot_df.columns
            else pd.to_datetime(plot_df["plan end"], errors="coerce")
        )
        if not fact_end_col:
            st.caption("Для ковенантов не найдена колонка фактического окончания — используется «plan end».")

        dev_end = (end_used - base_end).dt.days if base_end.notna().any() else pd.Series(np.nan, index=plot_df.index)
        cov_tbl = pd.DataFrame(
            {
                "Ковенант": plot_df[task_col].fillna("").astype(str).map(_gantt_clean_task_label),
                "Базовое окончание": [x.strftime("%d.%m.%Y") if pd.notna(x) else "" for x in base_end],
                "Окончание": [x.strftime("%d.%m.%Y") if pd.notna(x) else "" for x in end_used],
                "Отклонение Окончания": dev_end.map(_fmt_dev_days),
            },
            index=plot_df.index,
        )
        if show_reasons:
            if reason_src and reason_src in plot_df.columns:
                cov_tbl["Причины отклонений"] = plot_df[reason_src].astype(str).fillna("")
            else:
                cov_tbl["Причины отклонений"] = pd.Series("", index=cov_tbl.index, dtype=object)
            if notes_src and notes_src in plot_df.columns:
                cov_tbl["Заметки"] = plot_df[notes_src].astype(str).fillna("")
            else:
                cov_tbl["Заметки"] = pd.Series("", index=cov_tbl.index, dtype=object)

        _ord = ["Ковенант", "Базовое окончание", "Окончание", "Отклонение Окончания"]
        if show_reasons:
            _ord.extend(["Причины отклонений", "Заметки"])
        _ordered = [c for c in _ord if c in cov_tbl.columns]
        _rest = [c for c in cov_tbl.columns if c not in _ordered]
        tbl_show = cov_tbl[_ordered + _rest]
    else:
        d_start_num = None
        d_end_num = None
        if dev_start_src and dev_start_src in plot_df.columns:
            d_start_num = pd.to_numeric(plot_df[dev_start_src], errors="coerce")
        else:
            if "base start" in plot_df.columns:
                d_start_num = (
                    plot_df["plan start"] - pd.to_datetime(plot_df["base start"], errors="coerce")
                ).dt.days
        if dev_end_src and dev_end_src in plot_df.columns:
            d_end_num = pd.to_numeric(plot_df[dev_end_src], errors="coerce")
        else:
            if "base end" in plot_df.columns:
                d_end_num = (plot_df["plan end"] - pd.to_datetime(plot_df["base end"], errors="coerce")).dt.days

        tbl_pairs = []
        if proj_col and proj_col in plot_df.columns:
            tbl_pairs.append((proj_col, "Проект"))
        if task_col and task_col in plot_df.columns:
            tbl_pairs.append((task_col, "Задача"))
        for src, ru in (
            ("plan start", "План начало"),
            ("plan end", "План окончание"),
            ("base start", "База: начало"),
            ("base end", "База: окончание"),
            ("pct complete", "% выполнения"),
        ):
            if src in plot_df.columns:
                tbl_pairs.append((src, ru))

        tbl_view = plot_df[[c for c, _ in tbl_pairs]].copy() if tbl_pairs else plot_df.head(0).copy()
        if d_start_num is not None:
            tbl_view["Отклонение Начала"] = d_start_num.reindex(tbl_view.index).map(_fmt_dev_days)
        else:
            tbl_view["Отклонение Начала"] = pd.Series("", index=tbl_view.index, dtype=object)
        if d_end_num is not None:
            tbl_view["Отклонение Окончания"] = d_end_num.reindex(tbl_view.index).map(_fmt_dev_days)
        else:
            tbl_view["Отклонение Окончания"] = pd.Series("", index=tbl_view.index, dtype=object)

        if show_reasons:
            if reason_src and reason_src in plot_df.columns:
                tbl_view["Причины отклонений"] = plot_df[reason_src].astype(str).fillna("")
            else:
                tbl_view["Причины отклонений"] = pd.Series("", index=tbl_view.index, dtype=object)
            if notes_src and notes_src in plot_df.columns:
                tbl_view["Заметки"] = plot_df[notes_src].astype(str).fillna("")
            else:
                tbl_view["Заметки"] = pd.Series("", index=tbl_view.index, dtype=object)

        for dc in ("plan start", "plan end", "base start", "base end"):
            if dc in tbl_view.columns:
                _ts = pd.to_datetime(tbl_view[dc], errors="coerce")
                tbl_view[dc] = [x.strftime("%d.%m.%Y") if pd.notna(x) else "" for x in _ts]
        if "pct complete" in tbl_view.columns:
            tbl_view["pct complete"] = pd.to_numeric(tbl_view["pct complete"], errors="coerce")

        rename_map = {c: ru for c, ru in tbl_pairs if c in tbl_view.columns}
        tbl_show = tbl_view.rename(columns=rename_map)
        _gantt_tbl_order = [
            "Проект",
            "Задача",
            "План начало",
            "План окончание",
            "База: начало",
            "База: окончание",
            "% выполнения",
            "Отклонение Начала",
            "Отклонение Окончания",
        ]
        if show_reasons:
            _gantt_tbl_order.extend(["Причины отклонений", "Заметки"])
        _ordered = [c for c in _gantt_tbl_order if c in tbl_show.columns]
        _rest = [c for c in tbl_show.columns if c not in _ordered]
        tbl_show = tbl_show[_ordered + _rest]

    if tbl_show.empty:
        st.info("Нет колонок для таблицы.")
    else:
        _render_gantt_schedule_html_table(tbl_show, max_rows=80)
        if len(plot_df) > 80:
            st.caption(f"Показано 80 из {len(plot_df)} строк (на диаграмме до 400 задач).")


def dashboard_pd_delay(df):
    """Просрочка выдачи РД внутри раздела ПД."""
    st.caption(
        "Источник данных — MSP по разделу «Проектная документация». "
        "Ниже показана просрочка выдачи РД и помесячная динамика по разделам."
    )
    dashboard_rd_delay(df)
