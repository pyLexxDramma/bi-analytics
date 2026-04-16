"""
Отрисовка дашбордов. Код перенесён из project_visualization_app.py для уменьшения главного файла.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
import numpy as np
import re
import textwrap
import html as html_module

from config import MSP_PROJECT_FILTER_EXCLUDE_NAMES, RUSSIAN_MONTHS

from dashboards.dev_projects_tz_matrix import (
    build_dev_tz_matrix_rows,
    render_dev_tz_matrix,
    render_control_points_dashboard,
)


def _project_name_select_options(series: pd.Series) -> list:
    """Уникальные значения project name для фильтров; без меток из MSP_PROJECT_FILTER_EXCLUDE_NAMES."""
    raw = (
        series.dropna()
        .astype(str)
        .map(str.strip)
    )
    uniq = sorted({p for p in raw if p and p.lower() not in ("nan", "none")})
    return [p for p in uniq if p not in MSP_PROJECT_FILTER_EXCLUDE_NAMES]


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
                f"Показано {max_rows} из {len(df)} записей. Скачайте CSV для полных данных."
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
                f"Показано {max_rows} из {len(df)} записей. Скачайте CSV для полных данных."
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
    style_dataframe_for_dark_theme,
    plan_fact_dates_table_to_html,
    render_styled_table_to_html,
    budget_table_to_html,
    format_million_rub,
    to_million_rub,
    format_dataframe_as_html,
    norm_partner_join_key,
)

# Максимальное число строк, передаваемых в Plotly для scatter/line-графиков.
# Для агрегированных (bar, pie) ограничение не нужно — там строк обычно немного.
_MAX_CHART_ROWS = 5_000


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
    """Колонка числового уровня иерархии MSP (Outline Level и т.п.)."""
    if d is None or getattr(d, "empty", True):
        return None
    preferred = (
        "level",
        "outline level",
        "outline_level",
        "Outline Level",
        "исходный уровень",
        "исходный_уровень",
        "уровень структуры",
        "Уровень_структуры",
        "уровень иерархии",
        "Исходный уровень",
        "wbs level",
        "WBS Level",
    )
    cols_lower = {str(c).strip().lower(): c for c in d.columns}
    for w in preferred:
        wn = w.lower()
        if wn in cols_lower:
            return cols_lower[wn]
    for c in d.columns:
        sl = str(c).strip().lower()
        if "outline" in sl and "level" in sl.replace(" ", "") and "number" not in sl:
            return c
        if "wbs" in sl and "level" in sl.replace(" ", ""):
            return c
        if "уровень" in sl and "приоритет" not in sl and "риск" not in sl:
            return c
    return None


def _dev_tasks_build_ancestor_keys(df: pd.DataFrame, level_col, task_col) -> pd.DataFrame:
    """
    По порядку строк MSP и колонке уровня строит ключи для фильтров:
    задача ур. 2 (функциональный блок) и ур. 3 (строение) как предки текущей строки.
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
    lvl = pd.to_numeric(work[level_col], errors="coerce")
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
            if le == 2:
                a2 = nn
            if le == 3:
                a3 = nn
        k2 = nm if L == 2 else a2
        k3 = nm if L == 3 else a3
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
    if re.match(r"^\d{1,2}\.\d{1,2}\.\d{4}", t):
        return True
    if re.match(r"^\d{1,2}\.{2,3}\d{1,2}\.\d{4}", t):
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
    # Выгрузки договора: явное количество по ТЗ (ГДРС)
    for c in df.columns:
        if _gdrs_is_plan_column_false_positive(c):
            continue
        tl = str(c).strip().lower()
        if "количество" in tl and (
            "работник" in tl or "спецтех" in tl or "техник" in tl or "ресурс" in tl
        ):
            return c
    return None


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
    Рисует кнопки экспорта CSV и/или PNG под графиком.

    Args:
        df:           DataFrame для скачивания в CSV (опционально)
        fig:          Plotly-фигура для скачивания в PNG (опционально)
        csv_filename: Имя CSV-файла
        png_filename: Имя PNG-файла
        key_prefix:   Уникальный префикс для ключей виджетов
    """
    buttons = []
    if df is not None and not df.empty:
        csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        buttons.append(("csv", csv_bytes, csv_filename))

    if fig is not None:
        try:
            png_bytes = fig.to_image(format="png", width=1400, height=700, scale=2)
            buttons.append(("png", png_bytes, png_filename))
        except Exception:
            pass  # kaleido не установлен — PNG недоступен

    if not buttons:
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

    cols = st.columns(len(buttons))
    for col, (fmt, data, name) in zip(cols, buttons):
        mime = "text/csv" if fmt == "csv" else "image/png"
        label = f"Скачать {fmt.upper()}"
        try:
            col.download_button(
                label=label,
                data=data,
                file_name=name,
                mime=mime,
                key=f"{key_prefix}_{fmt}",
                on_click=lambda fn=name, ft=fmt: _log_export(ft, fn),
            )
        except TypeError:
            col.download_button(
                label=label,
                data=data,
                file_name=name,
                mime=mime,
                key=f"{key_prefix}_{fmt}",
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


def _render_deviations_combined_shared_filters(df):
    with st.expander("Подсказка по общим фильтрам", expanded=False):
        st.caption(
            "Общие фильтры для всех вкладок: проект, этап, причина, функциональный блок, строение (если есть в данных), "
            "период по месяцу плана. Переключение вкладок не сбрасывает выбранные значения."
        )
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
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if "project name" in df.columns:
            _session_reset_project_if_excluded("devcombo_project")
            projects = ["Все"] + _project_name_select_options(df["project name"])
            st.selectbox("Проект", projects, key="devcombo_project")
    with col2:
        if "section" in df.columns:
            sections = ["Все"] + sorted(df["section"].dropna().unique().tolist())
            st.selectbox("Этап", sections, key="devcombo_section")
    with col3:
        if "reason of deviation" in df.columns:
            reasons = ["Все"] + sorted(
                df["reason of deviation"].dropna().unique().tolist()
            )
            st.selectbox("Причина", reasons, key="devcombo_reason")
    with col4:
        if "block" in df.columns:
            blocks = ["Все"] + sorted(
                df["block"].dropna().astype(str).str.strip().unique().tolist()
            )
            st.selectbox("Функциональный блок", blocks, key="devcombo_block")

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

    r2a, r2b, r2c = st.columns(3)
    with r2a:
        if building_col:
            bvals = ["Все"] + sorted(
                df[building_col].dropna().astype(str).str.strip().unique().tolist()
            )
            st.selectbox("Строение", bvals, key="devcombo_building")
    with r2b:
        if len(available_months) > 0:
            months_opts = ["Все"] + available_months
            st.selectbox("Период с", months_opts, key="devcombo_period_from")
        else:
            st.selectbox("Период с", ["Все"], key="devcombo_period_from", disabled=True)
    with r2c:
        if len(available_months) > 0:
            months_opts = ["Все"] + available_months
            st.selectbox("Период по", months_opts, key="devcombo_period_to")
        else:
            st.selectbox("Период по", ["Все"], key="devcombo_period_to", disabled=True)

    filtered_df = df.copy()
    selected_project = (
        st.session_state.get("devcombo_project", "Все")
        if "project name" in filtered_df.columns
        else "Все"
    )
    selected_section = (
        st.session_state.get("devcombo_section", "Все")
        if "section" in filtered_df.columns
        else "Все"
    )
    selected_reason = (
        st.session_state.get("devcombo_reason", "Все")
        if "reason of deviation" in filtered_df.columns
        else "Все"
    )
    selected_block = (
        st.session_state.get("devcombo_block", "Все")
        if "block" in filtered_df.columns
        else "Все"
    )
    selected_building = (
        st.session_state.get("devcombo_building", "Все")
        if building_col and building_col in df.columns
        else "Все"
    )
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
    if selected_reason != "Все" and "reason of deviation" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["reason of deviation"].astype(str).str.strip()
            == str(selected_reason).strip()
        ]
    if selected_section != "Все" and "section" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["section"].astype(str).str.strip()
            == str(selected_section).strip()
        ]
    if selected_block != "Все" and "block" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["block"].astype(str).str.strip() == str(selected_block).strip()
        ]
    if (
        selected_building != "Все"
        and building_col
        and building_col in filtered_df.columns
    ):
        filtered_df = filtered_df[
            filtered_df[building_col].astype(str).str.strip()
            == str(selected_building).strip()
        ]

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
    filtered_shared, building_col = _render_deviations_combined_shared_filters(df)
    tab_by_month, tab_dynamics, tab_reasons = st.tabs(
        ["Доли причин по проекту", "Динамика по периодам", "Динамика причин"]
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

    # При hide_shared_filters фильтры задаются в общем блоке; локальные selectbox не рисуются — задаём значения по умолчанию.
    selected_project = "Все"

    if building_col is None:
        building_col = _find_column_by_keywords(
            df, ("building", "строение", "лот", "lot", "bldg")
        )

    if not hide_shared_filters:
        st.header("Доли причин отклонений по проекту")
        with st.expander("Подсказка", expanded=False):
            st.caption(
                "По умолчанию — все проекты и доступные периоды. Фильтры совпадают с объединённым отчётом "
                "«Причины отклонений»; динамику по периодам см. вкладку «Динамика по периодам» в том же отчёте."
            )

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

        col1, col2, col3, col4 = st.columns(4)

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
            try:
                has_section_column = "section" in df.columns
            except (AttributeError, TypeError):
                has_section_column = False

            if has_section_column:
                sections = ["Все"] + sorted(df["section"].dropna().unique().tolist())
                selected_section = st.selectbox("Этап", sections, key="reason_section")
            else:
                selected_section = "Все"

        with col3:
            try:
                has_reason_column = "reason of deviation" in df.columns
            except (AttributeError, TypeError):
                has_reason_column = False

            if has_reason_column:
                reasons = ["Все"] + sorted(
                    df["reason of deviation"].dropna().unique().tolist()
                )
                selected_reason = st.selectbox("Причина", reasons, key="reason_filter")
            else:
                selected_reason = "Все"

        with col4:
            try:
                has_block_column = "block" in df.columns
            except (AttributeError, TypeError):
                has_block_column = False

            if has_block_column:
                blocks = ["Все"] + sorted(df["block"].dropna().astype(str).str.strip().unique().tolist())
                selected_block = st.selectbox("Функциональный блок", blocks, key="reason_block")
            else:
                selected_block = "Все"

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

        r2a, r2b, r2c = st.columns(3)
        with r2a:
            if building_col:
                bvals = ["Все"] + sorted(
                    df[building_col].dropna().astype(str).str.strip().unique().tolist()
                )
                selected_building = st.selectbox(
                    "Строение", bvals, key="reason_building"
                )
            else:
                selected_building = "Все"
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
        selected_section = "Все"
        selected_reason = "Все"
        selected_block = "Все"
        selected_building = "Все"
        period_from = "Все"
        period_to = "Все"
        available_months = []

    filtered_df = df.copy()

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
        has_reason_col = "reason of deviation" in filtered_df.columns
    except (AttributeError, TypeError):
        has_reason_col = False

    if selected_reason != "Все" and has_reason_col:
        filtered_df = filtered_df[
            filtered_df["reason of deviation"].astype(str).str.strip()
            == str(selected_reason).strip()
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

    if selected_block != "Все" and "block" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["block"].astype(str).str.strip() == str(selected_block).strip()
        ]

    if (
        selected_building != "Все"
        and building_col
        and building_col in filtered_df.columns
    ):
        filtered_df = filtered_df[
            filtered_df[building_col].astype(str).str.strip()
            == str(selected_building).strip()
        ]

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
        fig.update_layout(
            yaxis=dict(range=[0, max(1.0, _ymax * 1.2)], title="Количество")
        )
        n = len(reason_counts)
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

    # Подпись текущего проекта (макет правок)
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
    notes_col_m = _find_column_by_keywords(
        filtered_df, ("note", "заметк", "comment", "remark", "notes")
    )
    work_m = filtered_df.copy()
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
        _maket_csv = pd.DataFrame(_maket_out).to_csv(
            index=False, encoding="utf-8-sig"
        ).encode("utf-8-sig")
        st.download_button(
            "Скачать CSV (по макету)",
            _maket_csv,
            "deviations_detail_maket.csv",
            "text/csv",
            key="devtable_csv_maket",
        )

    with st.expander("Полная выгрузка по фильтрам", expanded=False):
        st.caption("Ниже — полная таблица по текущим фильтрам (не только строки «по макету»).")
    display_cols = []
    for c in ("project name", "task name", "section"):
        if c in filtered_df.columns:
            display_cols.append(c)
    if "block" in filtered_df.columns:
        display_cols.append("block")
    if building_col and building_col in filtered_df.columns:
        display_cols.append(building_col)
    if "reason of deviation" in filtered_df.columns:
        display_cols.append("reason of deviation")
    for c in ("plan start", "plan end", "base start", "base end"):
        if c in filtered_df.columns:
            display_cols.append(c)
    if "deviation in days" in filtered_df.columns:
        display_cols.append("deviation in days")
    if "snapshot_date" in filtered_df.columns:
        display_cols.append("snapshot_date")

    display_df = filtered_df[display_cols].copy() if display_cols else filtered_df.copy()
    col_ru = {
        "project name": "Проект",
        "task name": "Задача",
        "section": "Этап",
        "block": "Функциональный блок",
        "reason of deviation": "Причина отклонения",
        "plan start": "План: начало",
        "plan end": "План: окончание",
        "base start": "Факт: начало",
        "base end": "Факт: окончание",
        "deviation in days": "Отклонение, дней",
        "snapshot_date": "Дата снимка",
    }
    if building_col and building_col in display_df.columns:
        col_ru[building_col] = "Строение"
    display_df = display_df.rename(
        columns={c: col_ru[c] for c in display_df.columns if c in col_ru}
    )
    if "Отклонение, дней" in display_df.columns:
        display_df["Отклонение, дней"] = display_df["Отклонение, дней"].apply(
            lambda x: int(round(float(x), 0)) if pd.notna(x) and str(x).strip() != "" else x
        )

    def _date_only(val):
        if pd.isna(val):
            return "Н/Д"
        if hasattr(val, "strftime"):
            return val.strftime("%d.%m.%Y")
        try:
            dt = pd.to_datetime(val, errors="coerce", dayfirst=True)
            return dt.strftime("%d.%m.%Y") if pd.notna(dt) else str(val)
        except Exception:
            return str(val)

    for date_col in (
        "План: начало",
        "План: окончание",
        "Факт: начало",
        "Факт: окончание",
        "Дата снимка",
    ):
        if date_col in display_df.columns:
            display_df[date_col] = pd.to_datetime(
                display_df[date_col], errors="coerce", dayfirst=True
            ).apply(_date_only)
    st.markdown(f"**Записей:** {len(display_df)}")
    _render_html_table(display_df)
    _csv = display_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("Скачать CSV", _csv, "deviations_detail.csv", "text/csv", key="devtable_csv_1")


# ==================== DASHBOARD 2: Dynamics of Deviations ====================
def dashboard_dynamics_of_deviations(df, hide_shared_filters=False):

    if df is None or not hasattr(df, "columns"):
        st.warning(
            "Нет данных для отображения. Пожалуйста, загрузите данные проекта."
        )
        return

    if hide_shared_filters:
        st.subheader("Динамика отклонений по периодам")
        with st.expander("Подсказка", expanded=False):
            st.markdown(
                "Проект, этап, причина, блок, строение и период по плану — **общие фильтры выше**. "
                "Здесь задаются ось времени (plan end или дата снимка) и шаг группировки."
            )
    else:
        st.header("Динамика отклонений по месяцам")
        with st.expander("Подсказка", expanded=False):
            st.markdown(
                "По правкам: ось времени — по **дате окончания плана** (plan end) или по **дате снимка файла** "
                "(несколько выгрузок MSP в web/; полный набор снимков хранится до схлопывания по проекту)."
            )

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
                projects = ["Все"] + sorted(source_df["project name"].dropna().unique().tolist())
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
                filtered_df["project name"].astype(str).str.strip()
                == str(selected_project).strip()
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

    grouped_data["period"] = grouped_data["period"].apply(format_period_ru)

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
            # Агрегируем данные по периоду и причинам (один столбец за месяц с секторами по причинам)
            if "project name" in group_cols:
                # Сначала суммируем по проектам и причинам, затем по периодам
                reason_data = (
                    grouped_data.groupby(["period", "reason of deviation"])
                    .agg({"Всего дней отклонений": "sum", "Количество задач": "sum"})
                    .reset_index()
                )
            else:
                reason_data = grouped_data

            # Вычисляем суммарные значения по каждому периоду для отображения над столбцами
            period_totals = (
                reason_data.groupby("period")["Всего дней отклонений"]
                .sum()
                .reset_index()
            )

            reason_data = reason_data.copy()
            fig = px.bar(
                reason_data,
                x="period",
                y="Всего дней отклонений",
                color="reason of deviation",
                title=None,
                labels={
                    "period": "Период",
                    "Всего дней отклонений": "Дни отклонений",
                    "reason of deviation": "Причина отклонения",
                },
            )
            # Накопление: легенда справа + запас по полям, подписи секторов скрыты (итог — аннотации сверху)
            fig.update_layout(
                barmode="stack",
                legend=dict(
                    title=dict(text="Причина"),
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
            fig.update_traces(textposition="none")

            # Добавляем суммарные значения над столбцами
            annotations = []
            for idx, row in period_totals.iterrows():
                period = row["period"]
                total = row["Всего дней отклонений"]
                # Для положительных значений - над столбцом (от верхней точки)
                # Для отрицательных значений - над столбцом (от верхней точки, которая находится внизу на y=0)
                if total >= 0:
                    # Положительное значение: аннотация над столбцом
                    y_coord = total
                    y_anchor = "bottom"
                    y_shift = (
                        20  # Фиксированное расстояние 20px от верхней точки столбца
                    )
                else:
                    # Отрицательное значение: аннотация над столбцом (который идет вниз)
                    # Верхняя точка отрицательного столбца находится на y=0, нижняя - на y=total
                    y_coord = 0  # Позиционируем относительно верхней точки (y=0)
                    y_anchor = "bottom"
                    y_shift = (
                        20  # Фиксированное расстояние 20px от верхней точки столбца
                    )

                annotations.append(
                    dict(
                        x=period,
                        y=y_coord,
                        text=f"{int(round(total, 0))}",
                        showarrow=False,
                        xanchor="center",
                        yanchor=y_anchor,
                        yshift=y_shift,
                        font=dict(size=14, color="white", weight="bold"),
                    )
                )
            fig.update_layout(annotations=annotations)

            fig = _apply_bar_uniformtext(fig)
            fig = apply_chart_background(fig)
            render_chart(fig, caption_below="Дни отклонений по периоду и причинам")

    # Summary table
    # If project is in group, show summary grouped by project overall (aggregate across all periods)
    if "project name" in group_cols:
        # Create project-level summary (aggregate across all periods, not by day/period)
        project_summary_cols = ["project name"]
        if "reason of deviation" in group_cols:
            project_summary_cols.append("reason of deviation")

        # Получаем доступные периоды из grouped_data для фильтра
        available_periods = []
        if "period" in grouped_data.columns:
            available_periods = sorted(
                grouped_data["period"].dropna().unique().tolist()
            )

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
        _csv = project_summary.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button("Скачать CSV", _csv, "project_summary.csv", "text/csv", key="proj_summary_csv")
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
        _csv = display_grouped.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button("Скачать CSV", _csv, "grouped_summary.csv", "text/csv", key="grouped_csv")


# ==================== DASHBOARD 3: Plan/Fact Dates for Tasks ====================
def dashboard_plan_fact_dates(df):
    st.header("Отклонение от базового плана")
    if df is None or not hasattr(df, "columns") or df.empty:
        st.warning("Нет данных для отображения. Загрузите файл с задачами MSP.")
        return

    with st.expander("Откуда берутся сроки и почему таблицы могут отличаться", expanded=False):
        st.markdown(
            """
**Таблица «Отклонение от базового плана (таблица)»** строится **по строкам задач** из выгрузки MSP после ваших фильтров
(проект, этап, блок, строение, уровень и т.д.). В ячейках — **базовые (плановые) и фактические даты** из колонок вроде
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
    dates_pct_col = _find_column_by_keywords(
        df, ("percent complete", "% заверш", "выполн", "complete", "percent")
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
            ],
        )
    dates_notes_col = _find_column_by_keywords(
        df, ("note", "заметк", "comment", "remark", "notes")
    )
    dates_lot_col = _find_column_by_keywords(df, ("lot", "лот", "LOT"))

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if "project name" in df.columns:
            _session_reset_project_if_excluded("dates_project")
            projects = ["Все"] + _project_name_select_options(df["project name"])
            selected_project = st.selectbox(
                "Фильтр по проекту", projects, key="dates_project"
            )
        else:
            selected_project = "Все"

    with col2:
        if "section" in df.columns:
            sections = ["Все"] + sorted(df["section"].dropna().unique().tolist())
            selected_section = st.selectbox(
                "Фильтр по этапу", sections, key="dates_section"
            )
        else:
            selected_section = "Все"

    with col3:
        level_options = [
            "Сводные (1–3 ур.)",
            "Укрупнённо (уровень 4)",
            "Детально (уровень 5)",
            "Все уровни",
        ]
        if "level" in df.columns:
            selected_level = st.selectbox(
                "Детализация (уровень MSP)",
                level_options,
                index=0,
                key="dates_level",
                help="Уровень 4 — укрупнённо, уровень 5 — детально (по колонке level в выгрузке).",
            )
        else:
            selected_level = "Все уровни"

    with col4:
        only_negative_dev_dates = st.checkbox(
            "Только диаграммы с отклонением окончания < 0",
            value=False,
            key="dates_only_neg_end",
            help="Оставить строки, где отклонение окончания (база − план) < 0.",
        )

    d2a, d2b, d2c, d2d = st.columns(4)
    with d2a:
        if "block" in df.columns:
            blks = ["Все"] + sorted(
                df["block"].dropna().astype(str).str.strip().unique().tolist()
            )
            selected_block_dates = st.selectbox(
                "Функциональный блок", blks, key="dates_block"
            )
        else:
            selected_block_dates = "Все"
    with d2b:
        if dates_building_col:
            bopts = ["Все"] + sorted(
                df[dates_building_col].dropna().astype(str).str.strip().unique().tolist()
            )
            selected_building_dates = st.selectbox(
                "Строение", bopts, key="dates_building"
            )
        else:
            selected_building_dates = "Все"
    with d2c:
        hide_completed_dates = st.checkbox(
            "Скрыть завершённые (100%)",
            value=False,
            key="dates_hide_done",
            help=(
                "Скрыть задачи со 100% выполнения по колонке % из MSP."
                + (""
                if dates_pct_col
                else " Колонка процента не найдена — фильтр не применится.")
            ),
        )
    with d2d:
        if dates_lot_col:
            task_label_mode = st.radio(
                "Подписи задач на графике",
                ("По наименованию MSP", "По лоту"),
                horizontal=True,
                key="dates_task_label_mode",
                help="«По лоту» — в подписях используется колонка лота, если заполнена.",
            )
        else:
            task_label_mode = "По наименованию MSP"

    d3a, d3b, d3c = st.columns(3)
    with d3a:
        dates_value_type = st.selectbox(
            "Тип значения",
            ["Даты (план/факт)", "Отклонение (дней)"],
            index=0,
            key="dates_value_type",
            help="Макет: даты или акцент на отклонениях в днях в итоговой таблице.",
        )
    with d3b:
        _sort_opts = [
            "Отклонение — по убыванию",
            "Отклонение — по возрастанию",
            "Отклонение начала — по убыванию",
            "Отклонение начала — по возрастанию",
            "Базовое начало — по возрастанию",
            "Базовое окончание — по возрастанию",
        ]
        _legacy_sort_map = {
            "Отклонение конца — по убыванию": "Отклонение — по убыванию",
            "Отклонение конца — по возрастанию": "Отклонение — по возрастанию",
        }
        if "dates_sort_order" in st.session_state:
            _cur = st.session_state["dates_sort_order"]
            if _cur in _legacy_sort_map:
                st.session_state["dates_sort_order"] = _legacy_sort_map[_cur]
            elif _cur not in _sort_opts:
                st.session_state["dates_sort_order"] = _sort_opts[0]
        dates_sort_order = st.selectbox(
            "Сортировка таблицы",
            _sort_opts,
            index=0,
            key="dates_sort_order",
        )
    with d3c:
        dates_show_reason_notes = st.checkbox(
            "Колонки причина и заметки (если есть в данных)",
            value=True,
            key="dates_show_reason_notes",
        )

    tbl_opt1, tbl_opt2, tbl_opt3 = st.columns(3)
    with tbl_opt1:
        tbl_show_end = st.checkbox(
            "Таблица: отклонение окончания",
            value=True,
            key="dates_tbl_end",
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

    tbl_only_pos_end_dev = st.checkbox(
        "Таблица: только строки с отклонением окончания > 0",
        value=True,
        key="dates_tbl_pos_end",
        help=(
            "Оставить строки, где отклонение окончания в днях > 0. "
            "Считается как base end − plan end (в выгрузке MSP: фактическое окончание минус плановое)."
        ),
    )
    tbl_native_sort = st.checkbox(
        "Таблица: сортировка по клику (встроенная)",
        value=False,
        key="dates_tbl_native_sort",
        help="Показывает таблицу Streamlit со сортировкой по столбцам по клику на заголовок (вместо HTML).",
    )

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
    if selected_block_dates != "Все" and "block" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["block"].astype(str).str.strip()
            == str(selected_block_dates).strip()
        ]
    if (
        selected_building_dates != "Все"
        and dates_building_col
        and dates_building_col in filtered_df.columns
    ):
        filtered_df = filtered_df[
            filtered_df[dates_building_col].astype(str).str.strip()
            == str(selected_building_dates).strip()
        ]
    # Фильтр по уровню иерархии (макет: сводные 1–3, верхний 4, детальный 5)
    if "level" in filtered_df.columns:
        level_num = pd.to_numeric(filtered_df["level"], errors="coerce")
        if selected_level == "Сводные (1–3 ур.)":
            mask_level = level_num.notna() & (level_num <= 3)
            if mask_level.any():
                filtered_df = filtered_df[mask_level]
        elif selected_level in ("Уровень 4 (верхний)", "Укрупнённо (уровень 4)"):
            filtered_df = filtered_df[level_num == 4]
        elif selected_level in ("Уровень 5 (детальный)", "Детально (уровень 5)"):
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

    if hide_completed_dates and dates_pct_col and dates_pct_col in filtered_df.columns:
        _pct = pd.to_numeric(filtered_df[dates_pct_col], errors="coerce")
        filtered_df = filtered_df[_pct.isna() | (_pct < 100.0001)]

    if only_negative_dev_dates:
        filtered_df = filtered_df[
            filtered_df["plan_end_diff"].notna()
            & (filtered_df["plan_end_diff"] < 0)
        ]

    if tbl_only_pos_end_dev:
        filtered_df = filtered_df[
            filtered_df["plan_end_diff"].notna()
            & (pd.to_numeric(filtered_df["plan_end_diff"], errors="coerce") > 0)
        ]

    if filtered_df.empty:
        st.info(
            "Нет данных после фильтров «Скрыть завершённые» / «Только отрицательное отклонение» "
            "/ «Только отклонение окончания > 0»."
        )
        return

    # Sort by task name (alphabetically) for consistent display
    filtered_df = filtered_df.sort_values("task name", ascending=True)

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
    # Get unique tasks in sorted order (by task name)
    unique_tasks = filtered_df["task name"].unique().tolist()

    # Prepare data for bar chart - plan and fact side by side for each task
    # If "Все" projects selected, show all tasks from all projects
    bar_data = []
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
        (selected_section != "Все" and _text_indicates_covenant(selected_section))
        or (
            selected_block_dates != "Все"
            and _text_indicates_covenant(selected_block_dates)
        )
    )
    covenant_auto_from_data = False
    if selected_section == "Все":
        for col in ("section", "block"):
            if col in filtered_df.columns and filtered_df[col].astype(str).map(
                _text_indicates_covenant
            ).any():
                covenant_auto_from_data = True
                break
    show_covenant_ui = covenant_filter_selected or covenant_auto_from_data
    covenant_rows_df = filtered_df
    if covenant_auto_from_data and not covenant_filter_selected:
        covenant_rows_df = filtered_df.loc[_covenant_row_mask(filtered_df)].copy()
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
            height=max(400, len(section_dev) * 44),
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
        with st.expander("Режим «Ковенанты»", expanded=False):
            if covenant_filter_selected:
                st.caption(
                    "Нижние диаграммы из общего макета скрыты; показан таймлайн вех "
                    "(базовое окончание и окончание) и таблица ковенантов."
                )
            else:
                st.caption(
                    "Обнаружены строки раздела «Ковенанты» в данных: ниже — таймлайн и таблица по ним "
                    "(фильтр этапа «Все»)."
                )
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
                            symbol="square",
                            size=12,
                            color="#2E86AB",
                            line=dict(width=1, color="#e0e0e0"),
                        ),
                        text=tdf_vis[pe_col].apply(
                            lambda d: d.strftime("%d.%m.%Y") if pd.notna(d) else ""
                        ),
                        textposition="top center",
                        textfont=dict(size=11, color="white"),
                        hovertemplate="%{y}<br>Базовое окончание: %{x|%d.%m.%Y}<extra></extra>",
                    )
                )
                fig_cov.add_trace(
                    go.Scatter(
                        x=tdf_vis[fe_col],
                        y=tdf_vis["_y"],
                        mode="markers+text",
                        name="Окончание (факт)",
                        marker=dict(
                            symbol="diamond",
                            size=12,
                            color="#FF6347",
                            line=dict(width=1, color="#e0e0e0"),
                        ),
                        text=tdf_vis[fe_col].apply(
                            lambda d: d.strftime("%d.%m.%Y") if pd.notna(d) else ""
                        ),
                        textposition="bottom center",
                        textfont=dict(size=11, color="white"),
                        hovertemplate="%{y}<br>Окончание: %{x|%d.%m.%Y}<extra></extra>",
                    )
                )
                nuniq = tdf_vis["_y"].nunique()
                fig_cov.update_layout(
                    xaxis_title="Дата",
                    yaxis_title="Задача",
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
                fig_cov = apply_chart_background(fig_cov)
                render_chart(fig_cov, caption_below="Ковенанты: базовое окончание и факт (таймлайн)")
            else:
                st.info("Нет дат для отображения таймлайна.")

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
                _cov_csv = cov_display.to_csv(
                    index=False, encoding="utf-8-sig"
                ).encode("utf-8-sig")
                st.download_button(
                    "Скачать CSV (ковенанты)",
                    _cov_csv,
                    "covenant_plan_fact.csv",
                    "text/csv",
                    key="covenant_table_csv",
                )
    elif bar_df.empty:
        st.info("Нет данных для отображения графика.")
    else:
        # Checkbox to show/hide completion percentage
        show_completion = st.checkbox(
            "Показать процент выполнения",
            value=False,
            key="show_completion_percent_dates",
        )

        # Calculate completion percentage if needed
        if show_completion:
            # Calculate completion percentage for each task
            for idx, row in bar_df.iterrows():
                if row["Тип"] == "План" and row["Длительность"] > 0:
                    # Find corresponding fact entry
                    fact_row = bar_df[
                        (bar_df["Задача"] == row["Задача"]) & (bar_df["Тип"] == "Факт")
                    ]
                    if not fact_row.empty:
                        fact_duration = fact_row.iloc[0]["Длительность"]
                        plan_duration = row["Длительность"]
                        if plan_duration > 0:
                            # Percentage = (fact / plan) * 100
                            completion_pct = (fact_duration / plan_duration) * 100
                            completion_pct_str = f"{completion_pct:.1f}%"
                            bar_df.loc[idx, "Процент выполнения"] = completion_pct_str
                            # Также сохраняем процент для соответствующей фактической записи
                            fact_idx = fact_row.index[0]
                            bar_df.loc[fact_idx, "Процент выполнения"] = (
                                completion_pct_str
                            )
                        else:
                            bar_df.loc[idx, "Процент выполнения"] = "Н/Д"
                    else:
                        bar_df.loc[idx, "Процент выполнения"] = "Н/Д"
                elif (
                    row["Тип"] == "Факт" and "Процент выполнения" not in bar_df.columns
                ):
                    bar_df.loc[idx, "Процент выполнения"] = ""

        # Sort tasks by start date (earliest first)
        if not bar_df.empty:
            # Get unique tasks and sort by earliest start date
            task_start_dates = (
                bar_df.groupby("Задача")["Дата начала"].min().sort_values()
            )
            task_order = {task: idx for idx, task in enumerate(task_start_dates.index)}
            bar_df["sort_order"] = bar_df["Задача"].map(task_order)
            bar_df = bar_df.sort_values(["sort_order", "Тип"], ascending=[True, True])
            bar_df = bar_df.drop("sort_order", axis=1)
            bar_df = bar_df.reset_index(drop=True)

        # График «План/факт по этапам»: ось Y — названия этапов и задача (без План/Факт в подписи)
        plan_df = bar_df[bar_df["Тип"] == "План"].copy()
        fact_df = bar_df[bar_df["Тип"] == "Факт"].copy()
        # def _y_label(row):
        #     stage = row.get("Этап", "—")
        #     if pd.isna(stage) or str(stage).strip() == "":
        #         stage = "—"
        #     return f"{stage} — {row['Задача']}"
        def _y_label(row):
            stage = row.get("Этап", "—")
            if pd.isna(stage) or str(stage).strip() == "":
                stage = "—"
            full = f"{stage} — {row['Задача']}"
            # Перенос строки каждые 40 символов
            words = full.split(" ")
            lines = []
            current = ""
            for word in words:
                # if len(current) + len(word) + 1 > 40:
                #     lines.append(current)
                #     current = word
                if len(current) + len(word) + 1 > 20:
                    lines.append(current)
                    current = word
                else:
                    current = (current + " " + word).strip()
            if current:
                lines.append(current)
            return "<br>".join(lines)


        # По оси Y только этап и задача (названия этапов); План и Факт — два столбца в одной строке
        plan_df["_y"] = plan_df.apply(_y_label, axis=1)
        fact_df["_y"] = fact_df.apply(_y_label, axis=1)
        all_y = list(plan_df["_y"].dropna().unique()) + list(fact_df["_y"].dropna().unique())
        seen = set()
        unique_tasks_sorted = []
        for y in all_y:
            if y not in seen:
                seen.add(y)
                unique_tasks_sorted.append(y)
        def _sort_key(s):
            parts = s.split(" — ", 2)
            stage = parts[0] if len(parts) > 0 else ""
            task = parts[1] if len(parts) > 1 else ""
            return (stage, task)
        unique_tasks_sorted = sorted(unique_tasks_sorted, key=_sort_key)

        def _edges_for_plotly_gantt_bar(start_date, end_date):
            """Plotly Bar (base, x): положительная длина; даты без tz для стабильной оси."""
            if start_date is None or end_date is None or pd.isna(start_date) or pd.isna(end_date):
                return None, None
            s = pd.to_datetime(start_date, errors="coerce", utc=True)
            e = pd.to_datetime(end_date, errors="coerce", utc=True)
            if pd.isna(s):
                s = pd.to_datetime(start_date, errors="coerce", dayfirst=True)
            if pd.isna(e):
                e = pd.to_datetime(end_date, errors="coerce", dayfirst=True)
            if pd.isna(s) or pd.isna(e):
                return None, None
            s = pd.Timestamp(s)
            e = pd.Timestamp(e)
            if s.tzinfo is not None:
                s = pd.Timestamp(s.tz_convert("UTC").to_pydatetime().replace(tzinfo=None))
            if e.tzinfo is not None:
                e = pd.Timestamp(e.tz_convert("UTC").to_pydatetime().replace(tzinfo=None))
            if s > e:
                s, e = e, s
            # Вехи с нулевой длительностью (начало = конец) не рисуются в Plotly Bar (base=x).
            if e <= s:
                e = s + pd.Timedelta(days=1)
            return s, e

        fig_gantt = go.Figure()

        # План — отдельный столбец; при «Показать процент выполнения» показываем только Факт
        if not show_completion and not plan_df.empty:
            plan_tasks = []
            plan_starts = []
            plan_ends = []
            plan_texts = []
            for idx, row in plan_df.iterrows():
                start_date = row["Дата начала"]
                end_date = row["Дата окончания"]
                s0, e0 = _edges_for_plotly_gantt_bar(start_date, end_date)
                if s0 is not None and e0 is not None:
                    plan_tasks.append(row["_y"])
                    plan_starts.append(s0)
                    plan_ends.append(e0)
                    plan_texts.append(e0.strftime("%d.%m.%Y"))
            if plan_tasks:
                fig_gantt.add_trace(
                    go.Bar(
                        x=plan_ends,
                        base=plan_starts,
                        y=plan_tasks,
                        orientation="h",
                        name="План",
                        marker_color="#2E86AB",
                        text=plan_texts,
                        textposition="outside",
                        textfont=dict(size=11, color="white"),
                        cliponaxis=False,
                        hovertemplate="<b>%{y}</b><br>Начало: %{base|%d.%m.%Y}<br>Окончание: %{x|%d.%m.%Y}<br><extra></extra>",
                    )
                )

        if not fact_df.empty:
            fact_tasks = []
            fact_starts = []
            fact_ends = []
            fact_texts = []
            for idx, row in fact_df.iterrows():
                start_date = row["Дата начала"]
                end_date = row["Дата окончания"]
                s0, e0 = _edges_for_plotly_gantt_bar(start_date, end_date)
                if s0 is not None and e0 is not None:
                    fact_tasks.append(row["_y"])
                    fact_starts.append(s0)
                    fact_ends.append(e0)
                    end_date_str = e0.strftime("%d.%m.%Y")
                    if show_completion and "Процент выполнения" in row and pd.notna(row.get("Процент выполнения")) and row["Процент выполнения"] != "":
                        fact_texts.append(f"{end_date_str} ({row['Процент выполнения']})")
                    else:
                        fact_texts.append(end_date_str)
            if fact_tasks:
                fig_gantt.add_trace(
                    go.Bar(
                        x=fact_ends,
                        base=fact_starts,
                        y=fact_tasks,
                        orientation="h",
                        name="Факт",
                        marker_color="#FF6347",
                        text=fact_texts,
                        textposition="outside",
                        textfont=dict(size=11, color="white"),
                        cliponaxis=False,
                        hovertemplate="<b>%{y}</b><br>Начало: %{base|%d.%m.%Y}<br>Окончание: %{x|%d.%m.%Y}<br><extra></extra>",
                    )
                )
        if not fig_gantt.data:
            st.warning(
                "График «План/факт по этапам» не построен: нет строк с корректными датами начала и окончания "
                "(после фильтров проверьте колонки план/факт в выгрузке)."
            )
        else:
            fig_gantt.update_layout(
                xaxis_title="Дата",
                yaxis_title="Этапы",
                height=max(600, len(unique_tasks_sorted) * 150),
                barmode="group",
                hovermode="closest",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                xaxis=dict(type="date", tickformat="%d.%m.%Y"),
                yaxis=dict(
                    categoryorder="array",
                    categoryarray=list(reversed(unique_tasks_sorted)),
                ),
                margin=dict(l=250),
                bargap=0.3,
                bargroupgap=0.1,
            )
            # uniformtext mode=hide в apply_chart_background скрывает подписи/иногда ломает Gantt;
            # для горизонтальных полос по датам — skip_uniformtext (как «График проекта»).
            fig_gantt = apply_chart_background(fig_gantt, skip_uniformtext=True)
            max_line_len = max(
                max(len(line) for line in s.split("<br>"))
                for s in unique_tasks_sorted
            ) if unique_tasks_sorted else 20
            left_margin = min(max_line_len * 8, 400)
            fig_gantt.update_layout(margin=dict(l=left_margin, r=30, t=50, b=150))
            fig_gantt.update_yaxes(tickfont=dict(size=12))
            fig_gantt.update_xaxes(autorange=True)
            render_chart(
                fig_gantt,
                caption_below="План/факт по этапам",
                skip_clamp_zoom=True,
            )

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

    _task_id_col = None
    for k in ("task id", "Task ID", "id", "UID", "identifier"):
        if k in filtered_df.columns:
            _task_id_col = k
            break

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

    for idx, row in filtered_df.iterrows():
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
            "Отклонение": end_diff,
            "Отклонение длительности": dur_diff,
        }
        if (
            task_label_mode == "По наименованию MSP"
            and "section" in filtered_df.columns
        ):
            rec["Раздел"] = _clean_display_str(row.get("section"))
        if _task_id_col:
            _tid = row.get(_task_id_col)
            rec["ID задачи (MSP)"] = (
                str(_tid).strip() if pd.notna(_tid) and str(_tid).strip() not in ("", "nan") else ""
            )
        if "reason of deviation" in filtered_df.columns:
            rec["Причина отклонения"] = _clean_display_str(
                row.get("reason of deviation")
            )
        if dates_notes_col and dates_notes_col in filtered_df.columns:
            rec["Заметки"] = _clean_display_str(row.get(dates_notes_col))
        summary_data.append(rec)

    summary_df = pd.DataFrame(summary_data)
    for col in (
        "Отклонение начала",
        "Отклонение",
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

    sort_key = "Отклонение"
    ascending = False
    if dates_sort_order == "Отклонение — по возрастанию":
        ascending = True
    elif dates_sort_order == "Отклонение начала — по убыванию":
        sort_key = "Отклонение начала"
        ascending = False
    elif dates_sort_order == "Отклонение начала — по возрастанию":
        sort_key = "Отклонение начала"
        ascending = True
    elif dates_sort_order == "Базовое начало — по возрастанию":
        sort_key = "Базовое начало"
        ascending = True
    elif dates_sort_order == "Базовое окончание — по возрастанию":
        sort_key = "Базовое окончание"
        ascending = True

    if sort_key in summary_df.columns:
        if sort_key in ("Базовое начало", "Базовое окончание"):
            _dt_key = pd.to_datetime(
                summary_df[sort_key], format="%d.%m.%Y", errors="coerce", dayfirst=True
            )
            summary_df = summary_df.assign(_sort_dt=_dt_key).sort_values(
                "_sort_dt", ascending=ascending, na_position="last"
            ).drop(columns=["_sort_dt"])
        else:
            summary_df = summary_df.sort_values(
                sort_key, ascending=ascending, na_position="last"
            )

    out_cols = ["Проект", "Задача"]
    if task_label_mode == "По наименованию MSP" and "Раздел" in summary_df.columns:
        out_cols.append("Раздел")
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
        out_cols.append("Отклонение")
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
    for col in ("Отклонение начала", "Отклонение", "Отклонение длительности"):
        if col in summary_display.columns:
            summary_display[col] = summary_display[col].apply(_format_int_days)

    _dates_table_tooltips = {
        "Проект": "Название проекта из выгрузки MSP.",
        "Задача": "Наименование задачи (или лот — при выборе «По лоту» в подписях графика, если задан лот).",
        "Раздел": "Этап / раздел из колонки section (только при подписях «По наименованию MSP»).",
        "ID задачи (MSP)": "Идентификатор задачи в MSP (если есть в файле).",
        "Базовое начало": "Плановая дата начала из MSP (колонка plan start / аналог).",
        "Базовое окончание": "Плановая дата окончания из MSP (колонка plan end / аналог).",
        "Начало (факт)": "Фактическая дата начала (base start / аналог).",
        "Окончание": "Фактическая дата окончания (base end / аналог).",
        "Отклонение начала": "В днях: base start − plan start (при наличии обеих дат).",
        "Отклонение": "В днях: base end − plan end (при наличии обеих дат).",
        "Отклонение длительности": "Разница длительностей факт vs план (в днях).",
        "Причина отклонения": "Поле причины отклонения из выгрузки (если есть).",
        "Заметки": "Заметки / комментарии из выгрузки (если есть).",
    }
    _dates_column_role = {
        "Базовое начало": "baseline",
        "Базовое окончание": "baseline",
        "Начало (факт)": "fact",
        "Окончание": "fact",
        "Отклонение": "dev",
        "Отклонение начала": "dev",
        "Отклонение длительности": "dev",
    }
    if dates_value_type == "Отклонение (дней)" and not any(
        c in summary_df.columns
        for c in (
            "Отклонение начала",
            "Отклонение",
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

    if "task name" in filtered_df.columns:
        zos_subset = filtered_df[
            filtered_df["task name"].astype(str).map(_is_zos_task_name)
        ].copy()
    else:
        zos_subset = filtered_df.iloc[0:0].copy()

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
        if tbl_native_sort:
            _styled = style_dataframe_for_dark_theme(
                summary_numeric,
                days_column="Отклонение" if "Отклонение" in summary_numeric.columns else None,
                plan_date_column=(
                    "Базовое окончание" if "Базовое окончание" in summary_numeric.columns else None
                ),
                fact_date_column="Окончание" if "Окончание" in summary_numeric.columns else None,
            )
            st.dataframe(
                _styled,
                hide_index=True,
                use_container_width=True,
                height=min(700, 50 + max(1, len(summary_numeric)) * 35),
            )
        else:
            _render_html_table(
                summary_display,
                column_tooltips=_dates_table_tooltips,
                column_role=_dates_column_role,
                cell_titles=True,
            )

    if not show_covenant_ui:
        st.subheader("Отклонение от базового плана (таблица)")
        with st.expander("Сводка по таблице", expanded=False):
            st.caption(
                f"Записей: {len(summary_df)} · тип: {dates_value_type} · сортировка: {dates_sort_order}"
            )
        _render_dates_main_table()
        _csv = summary_display.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button("Скачать CSV", _csv, "detail_dates.csv", "text/csv", key="detail_dates_csv")
    else:
        with st.expander("Полная таблица отклонений по всем задачам фильтра", expanded=False):
            st.markdown(
                "Полная таблица по всем задачам фильтра не выводится отдельным блоком, чтобы не дублировать "
                "таблицу **Ковенанты** выше. Ниже — развёртка со всеми колонками (план/факт, отклонения), если нужен экспорт."
            )
            st.caption(
                f"Записей: {len(summary_df)} · тип: {dates_value_type} · сортировка: {dates_sort_order}"
            )
            _render_dates_main_table()
            _csv_all = summary_display.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                "Скачать CSV (все задачи фильтра)",
                _csv_all,
                "detail_dates.csv",
                "text/csv",
                key="detail_dates_csv_all_tasks_cov",
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

    all_projects = sorted(df[project_col].dropna().unique().tolist())
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
            base[project_col].astype(str).str.strip() == str(selected_project).strip()
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
        block_opts = ["Все"] + sorted(
            work_h.loc[ln == 2, task_col].dropna().astype(str).str.strip().unique().tolist()
        )
        with f_block:
            selected_block = st.selectbox(
                "Функциональный блок",
                block_opts,
                key="deviation_tasks_block_l2",
                help="Задачи уровня 2 (иерархия MSP по колонке уровня).",
            )
        w3 = work_h[ln == 3]
        if selected_block != "Все":
            w3 = w3[
                w3["_dt_lvl2_key"].astype(str).str.strip()
                == str(selected_block).strip()
            ]
        build_opts = ["Все"] + sorted(
            w3[task_col].dropna().astype(str).str.strip().unique().tolist()
        )
        with f_build:
            selected_building = st.selectbox(
                "Строение",
                build_opts,
                key="deviation_tasks_building_l3",
                help="Задачи уровня 3 в выбранном функциональном блоке.",
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
                    csv_data = table_display.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                    st.download_button(
                        label="Скачать CSV",
                        data=csv_data,
                        file_name="deviation_details.csv",
                        mime="text/csv",
                        key="deviation_detail_csv_export",
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
        with st.expander("Подсказка", expanded=False):
            st.markdown(
                "Проект, этап, причина, функциональный блок, строение и период по плану — **общие фильтры выше**."
            )
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
            fig.update_layout(
                yaxis=dict(range=[0, reason_summary["Количество"].max() * 1.2])
            )
        else:
            # View 2: By months - month on X-axis, count on Y-axis, reasons as colors (stacked)
            # If "Все" projects selected, show aggregated view (one column per period)
            if selected_project == "Все":
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
            if selected_project == "Все":
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
        _csv = summary_by_reason.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button("Скачать CSV", _csv, "reasons_summary.csv", "text/csv", key="reasons_csv")
    else:
        st.warning("Столбец 'reason of deviation' не найден в данных.")


# ==================== DASHBOARD 6: Budget Plan/Fact/Reserve by Project by Period ====================
def dashboard_budget_by_period(df):
    st.header("БДДС")
    with st.expander("Вид отображения", expanded=False):
        st.caption("По месяцам или накопительно — переключатель в блоке графика ниже.")
    with st.expander("Источник данных", expanded=False):
        st.caption(
            "БДДС (денежные потоки): план и факт по оборотам из загруженных бюджетных данных "
            "(в т.ч. связка с задачами/проектами MSP при наличии колонок). "
            "Отчёты «Утверждённый бюджет» и «Прогнозный бюджет» — отдельные представления по тем же проектам."
        )

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
            projects = ["Все"] + sorted(df["project name"].dropna().unique().tolist())
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
            filtered_df["project name"].astype(str).str.strip()
            == str(selected_project).strip()
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
    with st.expander("Подсказка", expanded=False):
        st.caption(
            "Накопительные суммы по периоду; таблицы и подписи — в том же стиле, что отчёт «БДДС» (ТЗ, правки)."
        )

    col1, col2 = st.columns(2)

    with col1:
        period_type = st.selectbox(
            "Группировать по", ["Месяц", "Квартал", "Год"], key="budget_cum_period"
        )
        period_map = {"Месяц": "Month", "Квартал": "Quarter", "Год": "Year"}
        period_type_en = period_map.get(period_type, "Month")

    with col2:
        if "project name" in df.columns:
            projects = ["Все"] + sorted(df["project name"].dropna().unique().tolist())
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
            filtered_df["project name"].astype(str).str.strip()
            == str(selected_project).strip()
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
        chart_src = bs[bs["project name"].astype(str).str.strip() == str(selected_project).strip()].copy()
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
        bs2 = bs2[bs2["project name"].astype(str).str.strip() == str(selected_project).strip()].copy()
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
    with st.expander("Источник данных", expanded=False):
        st.caption(
            "По ТЗ: план/факт расходов по статьям БДР (признаки «Бюджет»/«ФАКТ» и «(БДР)» в загрузке). "
            "Ниже — агрегация по колонкам план/факт в данных MSP после нормализации."
        )

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
    with st.expander("Подсказка", expanded=False):
        st.caption("План и факт расходов по периоду.")

    col1, col2 = st.columns(2)
    with col1:
        period_type = st.selectbox(
            "Группировать по", ["Месяц", "Квартал", "Год"], key="bdr_period"
        )
        period_map = {"Месяц": "Month", "Квартал": "Quarter", "Год": "Year"}
        period_type_en = period_map.get(period_type, "Month")
    with col2:
        if "project name" in df.columns:
            projects = ["Все"] + sorted(df["project name"].dropna().unique().tolist())
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
            filtered_df["project name"].astype(str).str.strip()
            == str(selected_project).strip()
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
    fact_end_col = "base end" if "base end" in df.columns else find_column(df, ["Конец Факт", "Факт Конец", "Факт окончания ПД/РД"])

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

    # Колонка для фильтра по виду документации (ПД/РД)
    doc_type_col = find_column(
        df,
        ["Вид документации", "Тип документации", "ПД/РД", "Вид док", "Document type", "document type"],
    )

    # Add filters
    st.subheader("Фильтры")
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    # Project filter
    with filter_col1:
        try:
            projects = ["Все"] + sorted(df[project_col].dropna().unique().tolist())
            selected_project = st.selectbox(
                "Фильтр по проекту", projects, key="rd_delay_project"
            )
        except Exception as e:
            st.error(f"Ошибка при загрузке списка проектов: {str(e)}")
            return

    # Filter by documentation type (ПД / РД) — вместо фильтра по разделу
    with filter_col2:
        doc_type_options = ["Все", "Рабочая документация (РД)", "Проектная документация (ПД)"]
        selected_doc_type = st.selectbox(
            "Фильтр по виду документации",
            doc_type_options,
            key="rd_delay_doc_type",
        )

    # Apply filters
    filtered_df = df.copy()

    if selected_project != "Все":
        filtered_df = filtered_df[
            filtered_df[project_col].astype(str).str.strip()
            == str(selected_project).strip()
        ]

    if selected_doc_type != "Все" and doc_type_col and doc_type_col in filtered_df.columns:
        doc_str = filtered_df[doc_type_col].astype(str).str.strip().str.upper()
        if "Рабочая документация (РД)" in selected_doc_type or selected_doc_type == "РД":
            filtered_df = filtered_df[doc_str.str.contains("РД", na=False) | doc_str.str.contains("РАБОЧАЯ", na=False)]
        elif "Проектная документация (ПД)" in selected_doc_type or selected_doc_type == "ПД":
            filtered_df = filtered_df[doc_str.str.contains("ПД", na=False) | doc_str.str.contains("ПРОЕКТНАЯ", na=False)]
    elif selected_doc_type != "Все" and (not doc_type_col or doc_type_col not in df.columns):
        with st.expander("Ограничение фильтра ПД/РД", expanded=False):
            st.caption(
                "В данных нет колонки для фильтра по виду документации (например, «Вид документации» или «ПД/РД»)."
            )

    if filtered_df.empty:
        st.info("Нет данных для выбранных фильтров.")
        return

    # Prepare data for "Просрочка выдачи РД"
    # X-axis: "Задача" (each task is a separate bar)
    # Y-axis: "Отклонение разделов РД" (deviation values)
    try:
        # Convert "Отклонение разделов РД" to numeric - handle comma as decimal separator
        # First, get the raw column values
        rd_deviation_raw = filtered_df[rd_deviation_col].copy()

        # Convert to string, handling NaN properly
        rd_deviation_str = rd_deviation_raw.astype(str)

        # Replace various representations of empty/NaN values with empty string
        rd_deviation_str = rd_deviation_str.replace(
            ["nan", "None", "NaN", "NaT", "<NA>", "None"], ""
        )

        # Strip whitespace
        rd_deviation_str = rd_deviation_str.str.strip()

        # Replace comma with dot for decimal separator FIRST (European format: 6,00 -> 6.00)
        rd_deviation_str = rd_deviation_str.str.replace(",", ".", regex=False)

        # Now replace empty strings with '0' AFTER comma replacement
        rd_deviation_str = rd_deviation_str.replace("", "0")

        # Convert to numeric - this handles most cases
        filtered_df["rd_deviation_numeric"] = pd.to_numeric(
            rd_deviation_str, errors="coerce"
        ).fillna(0)

        # Числовые колонки для % выполнения РД/ПД
        if rd_plan_col and rd_plan_col in filtered_df.columns:
            filtered_df["_rd_plan_n"] = pd.to_numeric(
                filtered_df[rd_plan_col].astype(str).str.replace(",", ".").str.replace(" ", ""),
                errors="coerce",
            ).fillna(0)
        else:
            filtered_df["_rd_plan_n"] = 0
        if rd_fact_col and rd_fact_col in filtered_df.columns:
            filtered_df["_rd_fact_n"] = pd.to_numeric(
                filtered_df[rd_fact_col].astype(str).str.replace(",", ".").str.replace(" ", ""),
                errors="coerce",
            ).fillna(0)
        else:
            filtered_df["_rd_fact_n"] = 0

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
            chart_data = chart_data.drop(columns=["_rd_plan_n", "_rd_fact_n"], errors="ignore")

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
                chart_data = chart_data.drop(columns=["_rd_plan_n", "_rd_fact_n"], errors="ignore")
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
            if pd.notna(val):
                dev_str = f"{int(round(val, 0))}"
                text_values.append(f"{dev_str}  ({pct})" if pct and str(pct).strip() != "—" else dev_str)
            else:
                text_values.append(pct if pct else "")

        # Create horizontal bar chart
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
            color_discrete_sequence=["#2E86AB"],  # Single color for all bars
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
        _csv = summary_table.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button("Скачать CSV", _csv, "rd_delay_summary.csv", "text/csv", key="rd_delay_csv")

        # Таблица: План окончания ПД/РД и Факт окончания ПД/РД
        if (plan_end_col and plan_end_col in filtered_df.columns) or (fact_end_col and fact_end_col in filtered_df.columns):
            st.subheader("План и факт окончания ПД/РД")
            date_df = filtered_df.copy()
            if plan_end_col and plan_end_col in date_df.columns:
                date_df["План окончания ПД/РД"] = pd.to_datetime(date_df[plan_end_col], errors="coerce")
                date_df["План окончания ПД/РД"] = date_df["План окончания ПД/РД"].dt.strftime("%d.%m.%Y")
            else:
                date_df["План окончания ПД/РД"] = ""
            if fact_end_col and fact_end_col in date_df.columns:
                date_df["Факт окончания ПД/РД"] = pd.to_datetime(date_df[fact_end_col], errors="coerce")
                date_df["Факт окончания ПД/РД"] = date_df["Факт окончания ПД/РД"].dt.strftime("%d.%m.%Y")
            else:
                date_df["Факт окончания ПД/РД"] = ""
            tab_cols = []
            if project_col and project_col in date_df.columns:
                tab_cols.append(project_col)
            if section_col and section_col in date_df.columns:
                tab_cols.append(section_col)
            if task_col and task_col in date_df.columns:
                tab_cols.append(task_col)
            tab_cols.extend(["План окончания ПД/РД", "Факт окончания ПД/РД"])
            date_table = date_df[[c for c in tab_cols if c in date_df.columns]].drop_duplicates()
            rename_map = {}
            if project_col and project_col in date_table.columns:
                rename_map[project_col] = "Проект"
            if section_col and section_col in date_table.columns:
                rename_map[section_col] = "Раздел"
            if task_col and task_col in date_table.columns:
                rename_map[task_col] = "Задача"
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

    with st.expander("Источник данных", expanded=False):
        st.caption("Данные из загруженного файла с данными о технике.")

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
    if date_cols_found and "Период" not in work_df.columns:
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

    # Факт: sample_resources_data.csv — «Среднее за месяц»; sample_technique_data.csv — «Среднее за неделю»
    if "Среднее за месяц" in work_df.columns:
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
        work_df["week_sum"] = work_df["Среднее_за_неделю_numeric"]
    elif week_columns:
        week_numeric_cols = [f"{col}_numeric" for col in week_columns]
        work_df["week_sum"] = work_df[week_numeric_cols].sum(axis=1)
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

    col1, col2 = st.columns(2)

    with col1:
        if project_col and project_col in work_df.columns:
            all_projects = sorted(work_df[project_col].dropna().unique().tolist())
            selected_projects = st.multiselect(
                "Фильтр по проектам (можно выбрать несколько)",
                all_projects,
                default=all_projects if len(all_projects) <= 3 else all_projects[:3],
                key="technique_projects",
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

    # Apply filters
    filtered_df = work_df.copy()
    if selected_projects and project_col and project_col in filtered_df.columns:
        # Фильтруем по выбранным проектам
        project_mask = (
            filtered_df[project_col]
            .astype(str)
            .str.strip()
            .isin([str(p).strip() for p in selected_projects])
        )
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
                    total_fact = by_period_week["Факт"].sum()
                    by_period_week["%"] = (
                        (by_period_week["Факт"] / total_fact * 100).round(1)
                        if total_fact and total_fact != 0 else 0
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
                fig_hist.add_trace(
                    go.Scatter(
                        x=by_period_week["x_label"],
                        y=by_period_week["Факт"],
                        name="Факт",
                        mode="lines+markers+text",
                        line=dict(color=base_color, width=2),
                        marker=dict(size=10, color=base_color, line=dict(width=1, color="white")),
                        text=[f"{int(r['Факт'])} ({r['%']}%)" for _, r in by_period_week.iterrows()],
                        textposition="top center",
                        textfont=dict(size=9, color="white"),
                        hovertemplate="%{x}<br>Факт: %{y}<extra></extra>",
                        connectgaps=False,
                    )
                )
                fig_hist.update_layout(
                    title_text="",
                    xaxis_title="Период — неделя",
                    yaxis_title="Количество",
                    height=400,
                    showlegend=False,
                    xaxis=dict(
                        tickangle=-45,
                        categoryorder="array",
                        categoryarray=x_order,
                    ),
                )
                fig_hist = apply_chart_background(fig_hist)
                with hist_cols[idx]:
                    render_chart(
                        fig_hist,
                        key=f"{key_prefix}_hist_period_{idx}",
                        caption_below=f"Фактическое количество по периодам (точки — недели): {label}",
                    )
            else:
                # Нет колонок по неделям — один столбец/точка на период (сумма)
                by_period = (
                    df_hist.groupby(period_col_hist, as_index=False)["week_sum"]
                    .sum()
                    .rename(columns={"week_sum": "Факт"})
                )
                by_period["Период_стр"] = by_period[period_col_hist].astype(str).str.strip()
                total_fact = by_period["Факт"].sum()
                by_period["%"] = (
                    (by_period["Факт"] / total_fact * 100).round(1)
                    if total_fact and total_fact != 0 else 0
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
                                text=[f"{int(row['Факт'])} ({row['%']}%)" for _, row in by_period.iterrows()],
                                textposition="top center",
                                textfont=dict(size=11, color="white"),
                            )
                        )
                    else:
                        fig_hist.add_trace(
                            go.Bar(
                                x=by_period["Период_стр"],
                                y=by_period["Факт"],
                                text=[f"{int(row['Факт'])} ({row['%']}%)" for _, row in by_period.iterrows()],
                                textposition="outside",
                                textfont=dict(size=11, color="white"),
                                marker_color="#e67e22",
                                name="Факт",
                            )
                        )
                    fig_hist.update_layout(
                        title_text="",
                        xaxis_title="Период",
                        yaxis_title="Количество",
                        height=400,
                        showlegend=False,
                        xaxis=dict(tickangle=-45),
                    )
                    fig_hist = _apply_finance_bar_label_layout(fig_hist)
                    fig_hist = apply_chart_background(fig_hist)
                    render_chart(
                        fig_hist,
                        key=f"{key_prefix}_hist_period_fallback_{idx}",
                        caption_below=f"Фактическое количество по периодам: {label}",
                    )

    elif "week_sum" in filtered_df.columns:
        # Нет отдельной колонки периода (типично для web-выгрузки только с датами в заголовках): факт по подрядчикам
        with st.expander("Нет колонки «Период» в файле", expanded=False):
            st.caption(
                "Показан суммарный факт по подрядчикам (агрегация без оси периода в данных)."
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
            by_c = (
                df_fb.groupby("Контрагент", as_index=False)["week_sum"]
                .sum()
                .assign(Факт=lambda x: pd.to_numeric(x["week_sum"], errors="coerce").fillna(0))
            )
            by_c = by_c[by_c["Факт"].abs() > 0].sort_values("Факт", ascending=False)
            if by_c.empty:
                with fb_cols[fbi]:
                    st.info(f"**{lab_fb}** — нет ненулевых значений по подрядчикам.")
                continue
            tot = float(by_c["Факт"].sum())
            by_c["pct"] = (by_c["Факт"] / tot * 100.0).round(1) if tot else 0.0
            is_res = "ресурс" in lab_fb.lower() or "люди" in lab_fb.lower()
            col_bar = "#3498db" if is_res else "#e67e22"
            fig_fb = go.Figure(
                data=[
                    go.Bar(
                        x=by_c["Контрагент"],
                        y=by_c["Факт"],
                        marker_color=col_bar,
                        text=[f"{int(r['Факт'])} ({r['pct']}%)" for _, r in by_c.iterrows()],
                        textposition="outside",
                        textfont=dict(size=11, color="white"),
                    )
                ]
            )
            fig_fb.update_layout(
                title_text="",
                xaxis_title="Контрагент",
                yaxis_title="Факт (сумма)",
                height=420,
                showlegend=False,
                xaxis=dict(tickangle=-45),
            )
            fig_fb = apply_chart_background(fig_fb)
            with fb_cols[fbi]:
                render_chart(
                    fig_fb,
                    key=f"{key_prefix}_hist_noperiod_{fbi}",
                    caption_below=f"Факт по подрядчикам (в выгрузке нет колонки периода): {lab_fb}",
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
                        "План, факт, «%» = факт/план×100%, отклонение = план − факт по подрядчикам."
                    )
                display_df = by_contractor[
                    ["Контрагент", "План", "Факт", "%", "Отклонение"]
                ].copy()
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
        st.header("👥 График движения рабочей силы")

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

    with st.expander("Источник данных", expanded=False):
        st.caption("Данные из загруженных файлов (ресурсы и/или техника).")

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

    # Calculate sum of weeks (fact for the month = среднее за месяц)
    # Handle both "Среднее за неделю" (resources) and "Среднее за месяц" (technique)
    if "Среднее за неделю" in work_df.columns:
        # If we have Среднее за неделю (resources), multiply by number of weeks (typically 4-5)
        work_df["Среднее_за_неделю_numeric"] = pd.to_numeric(
            work_df["Среднее за неделю"]
            .astype(str)
            .str.replace(",", ".")
            .str.replace(" ", ""),
            errors="coerce",
        ).fillna(0)
        # Calculate week_sum as Среднее за неделю * number of weeks
        num_weeks = len(week_columns) if week_columns else 4
        work_df["week_sum"] = work_df["Среднее_за_неделю_numeric"] * num_weeks
    elif "Среднее за месяц" in work_df.columns:
        # If we have Среднее за месяц (technique), use it directly as week_sum
        work_df["Среднее_за_месяц_numeric"] = pd.to_numeric(
            work_df["Среднее за месяц"]
            .astype(str)
            .str.replace(",", ".")
            .str.replace(" ", ""),
            errors="coerce",
        ).fillna(0)
        work_df["week_sum"] = work_df["Среднее_за_месяц_numeric"]
        # Also create Среднее_за_неделю_numeric for consistency (divide by number of weeks)
        num_weeks = len(week_columns) if week_columns else 4
        work_df["Среднее_за_неделю_numeric"] = (
            work_df["week_sum"] / num_weeks if num_weeks > 0 else 0
        )
    elif week_columns:
        # Calculate from week columns if available
        week_numeric_cols = [f"{col}_numeric" for col in week_columns]
        work_df["week_sum"] = work_df[week_numeric_cols].sum(axis=1)
        # Calculate average per week
        num_weeks = len(week_columns) if week_columns else 4
        work_df["Среднее_за_неделю_numeric"] = (
            work_df["week_sum"] / num_weeks if num_weeks > 0 else 0
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
            work_df["week_sum"] = work_df["Среднее_за_неделю_numeric"] * _nw

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

    col1, col2 = st.columns(2)

    with col1:
        if project_col and project_col in work_df.columns:
            all_projects = sorted(work_df[project_col].dropna().unique().tolist())
            selected_projects = st.multiselect(
                "Фильтр по проектам (можно выбрать несколько)",
                all_projects,
                default=all_projects if len(all_projects) <= 3 else all_projects[:3],
                key=f"{key_prefix}_projects",
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

    # Табличное представление строк (правки: в UI — «Отклонение» / «Отклонение %», градиент по %)
    with st.expander("Таблица данных (план, факт, отклонение, отклонение %)", expanded=False):
        t = filtered_df.copy()
        tbl = pd.DataFrame()
        if project_col and project_col in t.columns:
            tbl["Проект"] = t[project_col].astype(str)
        if "Контрагент" in t.columns:
            tbl["Контрагент"] = t["Контрагент"].astype(str)
        if "Период" in t.columns:
            tbl["Период"] = t["Период"].apply(
                lambda v: format_period_ru(v)
                if v is not None
                else "Н/Д"
            )
        if "data_source" in t.columns:
            tbl["Источник"] = t["data_source"].astype(str)
        if "План_numeric" in t.columns:
            tbl["План"] = (
                pd.to_numeric(t["План_numeric"], errors="coerce")
                .round(0)
                .map(lambda x: f"{int(x)}" if pd.notna(x) else "")
            )
        if "week_sum" in t.columns:
            tbl["Факт"] = (
                pd.to_numeric(t["week_sum"], errors="coerce")
                .round(0)
                .map(lambda x: f"{int(x)}" if pd.notna(x) else "")
            )
        if "Дельта_numeric" in t.columns:
            tbl["Отклонение"] = (
                pd.to_numeric(t["Дельта_numeric"], errors="coerce")
                .round(0)
                .map(lambda x: f"{int(x)}" if pd.notna(x) else "")
            )
        if "Дельта_процент_numeric" in t.columns:
            tbl["Отклонение %"] = pd.to_numeric(
                t["Дельта_процент_numeric"], errors="coerce"
            ).round(1)
        if not tbl.empty:
            st.table(
                style_dataframe_for_dark_theme(
                    tbl,
                    percent_deviation_gradient_column="Отклонение %" if "Отклонение %" in tbl.columns else None,
                )
            )
        else:
            st.info("Нет колонок для таблицы с выбранными фильтрами.")

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
                    total_fact = by_period_week["Факт"].sum()
                    by_period_week["%"] = (
                        (by_period_week["Факт"] / total_fact * 100).round(1)
                        if total_fact and total_fact != 0 else 0
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
                fig_hist.add_trace(
                    go.Scatter(
                        x=by_period_week["x_label"],
                        y=by_period_week["Факт"],
                        name="Факт",
                        mode="lines+markers+text",
                        line=dict(color=base_color, width=2),
                        marker=dict(size=10, color=base_color, line=dict(width=1, color="white")),
                        text=[f"{int(r['Факт'])} ({r['%']}%)" for _, r in by_period_week.iterrows()],
                        textposition="top center",
                        textfont=dict(size=9, color="white"),
                        hovertemplate="%{x}<br>Факт: %{y}<extra></extra>",
                        connectgaps=False,
                    )
                )
                fig_hist.update_layout(
                    title_text="",
                    xaxis_title="Период — неделя",
                    yaxis_title="Количество",
                    height=400,
                    showlegend=False,
                    xaxis=dict(
                        tickangle=-45,
                        categoryorder="array",
                        categoryarray=x_order,
                    ),
                )
                fig_hist = apply_chart_background(fig_hist)
                with hist_cols[idx]:
                    render_chart(
                        fig_hist,
                        key=f"{key_prefix}_hist_period_{idx}",
                        caption_below=f"Фактическое количество по периодам (точки — недели): {label}",
                    )
            else:
                # Нет колонок по неделям — один столбец/точка на период (сумма)
                by_period = (
                    df_hist.groupby(period_col_hist, as_index=False)["week_sum"]
                    .sum()
                    .rename(columns={"week_sum": "Факт"})
                )
                by_period["Период_стр"] = by_period[period_col_hist].astype(str).str.strip()
                total_fact = by_period["Факт"].sum()
                by_period["%"] = (
                    (by_period["Факт"] / total_fact * 100).round(1)
                    if total_fact and total_fact != 0 else 0
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
                                text=[f"{int(row['Факт'])} ({row['%']}%)" for _, row in by_period.iterrows()],
                                textposition="top center",
                                textfont=dict(size=11, color="white"),
                            )
                        )
                    else:
                        fig_hist.add_trace(
                            go.Bar(
                                x=by_period["Период_стр"],
                                y=by_period["Факт"],
                                text=[f"{int(row['Факт'])} ({row['%']}%)" for _, row in by_period.iterrows()],
                                textposition="outside",
                                textfont=dict(size=11, color="white"),
                                marker_color="#e67e22",
                                name="Факт",
                            )
                        )
                    fig_hist.update_layout(
                        title_text="",
                        xaxis_title="Период",
                        yaxis_title="Количество",
                        height=400,
                        showlegend=False,
                        xaxis=dict(tickangle=-45),
                    )
                    fig_hist = _apply_finance_bar_label_layout(fig_hist)
                    fig_hist = apply_chart_background(fig_hist)
                    render_chart(
                        fig_hist,
                        key=f"{key_prefix}_hist_period_fallback_{idx}",
                        caption_below=f"Фактическое количество по периодам: {label}",
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
                    )
                ]
            )
            fig_wfb.update_layout(
                title_text="",
                xaxis_title="Контрагент",
                yaxis_title="Факт (сумма)",
                height=420,
                showlegend=False,
                xaxis=dict(tickangle=-45),
            )
            fig_wfb = _apply_finance_bar_label_layout(fig_wfb)
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
        dev = plan_sum - fact_sum
        fp_pct = (fact_sum / plan_sum * 100.0) if plan_sum else 0.0
        # Столбчатая план/факт: подписи над столбцами, нули видны (круговая скрывает нулевой сегмент)
        fig_pie_pf = go.Figure(
            data=[
                go.Bar(
                    x=["План", "Факт"],
                    y=[plan_sum, fact_sum],
                    marker_color=["#3498db", "#2ecc71"],
                    text=[
                        f"{int(round(plan_sum))}",
                        f"{int(round(fact_sum))}",
                    ],
                    textposition="outside",
                    textfont=dict(size=13, color="#ffffff"),
                    hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
                )
            ]
        )
        fig_pie_pf.update_layout(
            height=420,
            showlegend=False,
            title_font_size=14,
            margin=dict(l=48, r=24, t=24, b=48),
            yaxis=dict(title=""),
        )
        fig_pie_pf = _apply_bar_uniformtext(fig_pie_pf)
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
        by_c = d.groupby("Контрагент", as_index=False)["_f"].sum()
        by_c = by_c[by_c["_f"] > 0].sort_values("_f", ascending=False)
        if by_c.empty or float(by_c["_f"].sum()) <= 0:
            return None, None
        pie_df = by_c.rename(columns={"_f": "Факт"})
        fig_cf = px.pie(
            pie_df,
            values="Факт",
            names="Контрагент",
            title=None,
            color_discrete_sequence=px.colors.qualitative.Set3,
        )
        # Подписи только % в сегментах; названия подрядчиков — в легенде под кругом
        fig_cf.update_traces(
            textinfo="percent",
            texttemplate="%{percent:.0%}",
            textposition="inside",
            textfont_size=12,
            insidetextorientation="horizontal",
            hovertemplate="<b>%{label}</b><br>Факт: %{value:,.0f} (%{percent:.0%})<extra></extra>",
        )
        _n_parts = max(1, len(pie_df.index))
        # Легенда под кругом (не справа): на всю ширину колонку не сжимает подписи
        _leg_lines = max(2, int((_n_parts + 2) // 3))
        _bottom_pad = min(260, 96 + 22 * _leg_lines)
        fig_cf.update_layout(
            height=520,
            showlegend=True,
            title_font_size=14,
            uniformtext=dict(minsize=8, mode="hide"),
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.06,
                x=0.5,
                xanchor="center",
                font=dict(size=11),
                bgcolor="rgba(0,0,0,0)",
                traceorder="normal",
            ),
            margin=dict(l=48, r=48, t=32, b=_bottom_pad),
        )
        fig_cf = apply_chart_background(fig_cf)
        # Снова поджимаем легенду к области графика — общий стиль задаёт y=-0.25
        fig_cf.update_layout(
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.02,
                x=0.5,
                xanchor="center",
                font=dict(size=11),
                bgcolor="rgba(0,0,0,0)",
            ),
            margin=dict(l=48, r=48, t=36, b=_bottom_pad),
            height=540,
        )
        plan_sum = (
            float(pd.to_numeric(d["План_numeric"], errors="coerce").fillna(0).sum())
            if "План_numeric" in d.columns
            else 0.0
        )
        fact_sum = float(by_c["_f"].sum())
        dev = plan_sum - fact_sum
        fp_pct = (fact_sum / plan_sum * 100.0) if plan_sum else None
        return fig_cf, {
            "plan": plan_sum,
            "fact": fact_sum,
            "dev": dev,
            "fp_pct": fp_pct,
        }

    show_plan_fact_row = (
        has_plan_data
        and len(projects_to_process) > 1
        and project_col
        and project_col in filtered_df.columns
    )
    plan_fact_row_done = False
    if show_plan_fact_row:
        if (data_source_filter or "").strip().lower() == "техника":
            st.subheader("Техника (план/факт)")
        else:
            st.subheader("Рабочие (план/факт)")
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
                            f"{int(round(met_pf['dev']))}\n\n"
                            f"*({met_pf['fp_pct']:.1f}% — факт/план)*",
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
        fp = met.get("fp_pct")
        pl = float(met.get("plan") or 0)
        if fp is None or pl == 0.0:
            return "*(% к плану недоступен — в данных нет или ноль в «План»)*"
        return f"*({fp:.1f}% — факт/план)*"

    contractor_fact_row_done = False
    if show_contractor_fact_row:
        if (data_source_filter or "").strip().lower() == "техника":
            st.subheader("Техника (% фактический по подрядчикам)")
        else:
            st.subheader("Рабочие (% фактический по подрядчикам)")
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

        # ========== Chart 1: круговая — % фактический по подрядчикам ==========
        if not contractor_fact_row_done:
            if (data_source_filter or "").strip().lower() == "техника":
                st.subheader("Техника (% фактический по подрядчикам)")
            else:
                st.subheader("Рабочие (% фактический по подрядчикам)")
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
                        f"{int(round(met_cf['dev']))}\n\n"
                        + _gdrs_fp_pct_caption_line(met_cf),
                        unsafe_allow_html=True,
                    )
            else:
                st.info("Нет данных для отображения круговой диаграммы по подрядчикам.")
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
                        "План, факт, «%» = факт/план×100%, отклонение = план − факт по подрядчикам."
                    )
                display_df = by_contractor[
                    ["Контрагент", "План", "Факт", "%", "Отклонение"]
                ].copy()
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

        bar_df = project_filtered_df.copy()
        if period_col and period_col in bar_df.columns and selected_periods:
            bar_df = bar_df[
                bar_df[period_col].astype(str).str.strip().isin([str(p).strip() for p in selected_periods])
            ]
        if "Дельта_numeric" not in bar_df.columns and "План_numeric" in bar_df.columns and "week_sum" in bar_df.columns:
            bar_df = bar_df.copy()
            bar_df["Дельта_numeric"] = bar_df["План_numeric"] - bar_df["week_sum"]
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

        total_plan = contractor_data["План"].sum() or 1
        total_fact = contractor_data["Среднее за месяц"].sum() or 1
        plan_text = [f"{int(x)} ({x / total_plan * 100:.0f}%)" if pd.notna(x) else "0" for x in contractor_data["План"]]
        fact_text = [f"{int(x)} ({x / total_fact * 100:.0f}%)" if pd.notna(x) else "0" for x in contractor_data["Среднее за месяц"]]

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
                marker_color="#2ecc71",
                text=fact_text,
                textposition="outside",
                textfont=dict(size=12, color="white"),
            )
        )

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
            height=600,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
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
    График движения рабочей силы: вкладки — рабочая сила, техника, динамика, СКУД по неделям.
    """
    st.header("График движения рабочей силы")
    with st.expander("Источник данных", expanded=False):
        st.caption(
            "Данные из загруженных файлов ресурсов и техники. Если данных нет — загрузите соответствующие CSV-файлы."
        )
    tab1, tab2, tab3, tab4 = st.tabs([
        "Рабочая сила",
        "Техника",
        "Динамика людей и техники",
        "СКУД по неделям",
    ])
    with tab1:
        st.subheader("График движения рабочей силы")
        dashboard_workforce_movement(df, data_source_filter="Ресурсы", show_header=False, key_prefix="gdrs_people")
    with tab2:
        st.subheader("График движения техники")
        dashboard_workforce_movement(df, data_source_filter="Техника", show_header=False, key_prefix="gdrs_technique")
    with tab3:
        st.subheader("Динамика людей и техники")
        dashboard_workforce_movement(df, data_source_filter=None, show_header=False, key_prefix="gdrs_dynamics")
    with tab4:
        dashboard_skud_stroyka(df)


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
    if project_from_reference:
        st.caption(
            "Колонка «Проект» подставлена по **справочнику** (`spravochniki.json` — пара контрагент/проект, если обе колонки есть) "
            "и/или по файлу **данные 1С** (`*dannye*.json` — из оборотов строится карта «контрагент → проект»). "
            "Совпадение по нормализованному наименованию (регистр, пробелы, ООО). "
            "Или укажите проект в файле ДтКт."
        )
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
            all_projects = ["Все"] + sorted(work[project_col].dropna().astype(str).unique().tolist())
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
        filtered = filtered[filtered[project_col].astype(str).str.strip() == str(sel_project).strip()]

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
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
            xaxis=dict(tickangle=-55, tickfont=dict(size=9), categoryorder="total descending"),
            margin=dict(b=140),
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
    _csv = display_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("Скачать CSV", _csv, "debit_credit.csv", "text/csv", key="debit_credit_csv")


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
.exec-doc-table-wrap { overflow-x:auto; margin:0.75rem 0 1rem; border-radius:8px; border:1px solid #333; }
.exec-doc-table { width:100%; border-collapse:collapse; font-size:13px; font-family:Inter,system-ui,sans-serif; }
.exec-doc-table th {
  text-align:left; padding:10px 12px; background:#1a1c23; color:#fafafa;
  border-bottom:2px solid #444; font-size:11px; font-weight:600;
  text-transform:uppercase; letter-spacing:0.04em; white-space:nowrap;
}
.exec-doc-table td {
  padding:8px 12px; border-bottom:1px solid #333; color:#e8eef5;
  vertical-align:middle; max-width:340px;
}
.exec-doc-table tr:nth-child(even) td { background:rgba(255,255,255,0.02); }
.exec-doc-table tr:hover td { background:#262833; }
.exec-delay-val { color:#5eead4; font-weight:600; font-variant-numeric:tabular-nums; }
.exec-dash { color:#8892a0; }
.exec-pill { display:inline-block; padding:4px 12px; border-radius:999px; font-size:12px; font-weight:600; white-space:nowrap; }
.exec-pill-signed { background:rgba(34,197,94,0.18); color:#86efac; border:1px solid rgba(34,197,94,0.45); }
.exec-pill-customer { background:rgba(251,191,36,0.15); color:#fcd34d; border:1px solid rgba(251,191,36,0.45); }
.exec-pill-contractor { background:rgba(248,113,113,0.14); color:#fca5a5; border:1px solid rgba(248,113,113,0.45); }
.exec-pill-declined { background:rgba(148,163,184,0.12); color:#cbd5e1; border:1px solid #64748b; }
.exec-pill-default { background:#262833; color:#e0e0e0; border:1px solid #444; }
.exec-pill-muted { color:#64748b; border:1px dashed #444; padding:3px 10px; border-radius:8px; font-size:12px; }
</style>
"""


def _exec_status_pill_html(status: str) -> str:
    """Бейджи статуса как на макете: Подписано / У Заказчика / У Подрядчика."""
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
        return f'<span class="exec-pill exec-pill-signed">{esc("Подписано")}</span>'
    if "отказ" in sl or "declined" in sl:
        return f'<span class="exec-pill exec-pill-declined">{esc(s)}</span>'
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


def _exec_detail_table_html(df: pd.DataFrame, max_rows: int = 500) -> str:
    """HTML-таблица детального отчёта ИД: CAPS-заголовки, циан для просрочек, пилюли статусов."""
    esc = html_module.escape
    if df is None or df.empty:
        return f'<p style="color:#8892a0;padding:12px;">{esc("Нет строк для отображения.")}</p>'
    show = df.head(max_rows)
    cols = list(show.columns)
    thead = "<thead><tr>" + "".join(f"<th>{esc(c)}</th>" for c in cols) + "</tr></thead>"
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
            dr = st.date_input(
                "Период (по дате создания в TESSA)",
                value=(dmin.date() if hasattr(dmin, "date") else dmin, dmax.date() if hasattr(dmax, "date") else dmax),
                key="exec_doc_period",
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
        show_signed_in_table = st.checkbox(
            "Отображать сданную ИД в детальной таблице",
            value=False,
            key="exec_doc_show_signed_table",
        )
        compare_prev_period = st.checkbox(
            "Сравнить с предыдущим периодом той же длительности (по дате создания)",
            value=False,
            key="exec_doc_compare_prev_period",
        )

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
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Всего документов", int(total_docs))
    m2.metric("Отказы", int(is_declined.sum()))
    m3.metric("На согласовании", int(is_on_agree.sum()))
    m4.metric("Подписано", int(is_signed.sum()))
    m5.metric("Всего просрочек (два типа)", total_overdue_two)
    st.caption(
        "Показатель «Всего просрочек» = просрочка подрядчика (доработка) "
        "+ просрочка заказчика (на согласовании)."
    )

    if compare_prev_period and creation_col and p_start is not None and p_end is not None:
        span_days = (p_end - p_start).days + 1
        if span_days < 1:
            span_days = 1
        b_end = p_start - timedelta(days=1)
        b_start = b_end - timedelta(days=span_days - 1)
        ts_b0 = pd.Timestamp(b_start)
        ts_b1 = pd.Timestamp(b_end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        filt_b = filtered_base[
            filtered_base["_cd"].notna()
            & (filtered_base["_cd"] >= ts_b0)
            & (filtered_base["_cd"] <= ts_b1)
        ]

        def _exec_n_docs(dfp):
            if card_col and card_col in dfp.columns:
                return int(dfp[card_col].nunique())
            return int(len(dfp))

        n_cur = _exec_n_docs(filtered)
        n_prev = _exec_n_docs(filt_b)
        st.caption(
            f"Сравнение по дате создания: предыдущий интервал {b_start.strftime('%d.%m.%Y')}—{b_end.strftime('%d.%m.%Y')} "
            f"({span_days} дн., сразу перед выбранным периодом)."
        )
        _cmp_notes = []
        if n_cur + n_prev < 4:
            _cmp_notes.append("Мало документов в одном или обоих периодах — сравнение ориентировочное.")
        if n_prev == 0:
            _cmp_notes.append("В предыдущем периоде по выбранным фильтрам нет документов.")
        if _cmp_notes:
            st.info(" ".join(_cmp_notes))
        cmp_a, cmp_b = st.columns(2)
        with cmp_a:
            st.metric(
                "Документов (выбранный период)",
                n_cur,
                delta=int(n_cur - n_prev),
                delta_color="normal",
            )
        with cmp_b:
            st.metric("Документов (предыдущий период)", n_prev)

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
        disp = filtered.copy()
        if not show_signed_in_table:
            disp = disp.loc[~is_signed].copy()
        rows_out = []
        for _, row in disp.iterrows():
            st_l = str(row.get("Статус", ""))
            signed_row = _has_status(st_l, "Подписан", "Согласован")
            hide_ov = hide_overdue_if_done and signed_row
            plan_d = row.get(plan_col) if plan_col else None
            fact_d = row.get(completed_col) if completed_col else None
            pr_sub = ""
            pr_cust = ""
            if not hide_ov and plan_col and pd.notna(_tessa_to_datetime(pd.Series([plan_d])).iloc[0]):
                pdt = _tessa_to_datetime(pd.Series([plan_d])).iloc[0]
                if pd.notna(pdt):
                    if completed_col and pd.notna(_tessa_to_datetime(pd.Series([fact_d])).iloc[0]):
                        fdt = _tessa_to_datetime(pd.Series([fact_d])).iloc[0]
                        if pd.notna(fdt):
                            pr_sub = f"{max(0, (fdt.date() - pdt.date()).days)} дн."
                    elif pd.notna(pdt):
                        pr_sub = f"{max(0, (today - pdt.date()).days)} дн." if hasattr(pdt, "date") else ""
            if hide_ov:
                pr_sub = "—"
                pr_cust = "—"
            tr = row.get(transfer_col) if transfer_col else None
            ag = row.get(agree_col) if agree_col else None
            if not hide_ov and transfer_col and agree_col and pd.notna(_tessa_to_datetime(pd.Series([tr])).iloc[0]) and pd.notna(_tessa_to_datetime(pd.Series([ag])).iloc[0]):
                t1 = _tessa_to_datetime(pd.Series([tr])).iloc[0]
                t2 = _tessa_to_datetime(pd.Series([ag])).iloc[0]
                if pd.notna(t1) and pd.notna(t2):
                    pr_cust = f"{max(0, (t2.date() - t1.date()).days)} дн."
            elif hide_ov:
                pr_cust = "—"
            row_dict = {
                "Контрагент": row.get(contr_col, "") if contr_col else "",
                "Объект": row.get(obj_col, "") if obj_col else "",
                "№ документа": row.get("DocNumber", row.get("DocID", "")),
                "Тип": row.get(kind_col, "") if kind_col else "",
                "Плановая дата сдачи": plan_d if plan_col else "",
                "Факт сдачи": fact_d if completed_col else "",
                "Просрочка сдачи": pr_sub if not hide_ov else "—",
                "Дата передачи заказчику": row.get(transfer_col, "") if transfer_col else "",
                "Дата согласования": row.get(agree_col, "") if agree_col else "",
                "Просрочка соглас.": pr_cust if not hide_ov else "—",
                "Статус": st_l,
                "Дата создания": row.get(creation_col, "") if creation_col else "",
            }
            rows_out.append(row_dict)
        table_df = pd.DataFrame(rows_out)
        st.markdown(f"**Записей:** {len(table_df)}")
        st.markdown(
            _EXEC_DOC_DETAIL_CSS + _exec_detail_table_html(table_df),
            unsafe_allow_html=True,
        )
        if len(table_df) > 500:
            with st.expander("Ограничение отображения в браузере", expanded=False):
                st.caption("Показано 500 из записей — скачайте CSV для полного списка.")
        csv_bytes = table_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button("Скачать CSV", csv_bytes, "executive_docs.csv", "text/csv", key="exec_doc_csv")

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
                fig3 = apply_chart_background(fig3)
                fig3.update_layout(
                    height=400,
                    xaxis_title="Месяц",
                    yaxis_title="Количество",
                    xaxis=dict(tickangle=-35, categoryorder="array", categoryarray=list(cnt["Месяц"])),
                )
                render_chart(fig3, caption_below="Поступление документов по месяцам", key="exec_month_dyn")


# ==================== DASHBOARD: график рабочей силы (объединённый) ====================
def dashboard_workforce_and_skud(df):
    """
    Объединённый отчёт: основной график и факт СКУД по неделям (данные ресурсов).
    """
    st.header("График движения рабочей силы")
    with st.expander("Источник данных", expanded=False):
        st.caption(
            "Вкладки: ресурсы (рабочая сила) и СКУД по неделям. Данные — из загруженных в приложении файлов."
        )
    tab1, tab2 = st.tabs(["Рабочая сила", "СКУД по неделям"])
    with tab1:
        dashboard_workforce_movement(df)
    with tab2:
        dashboard_skud_stroyka(df)


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

    if page_title == "Проектная документация":
        with st.expander("Примечание по проектной документации", expanded=False):
            st.markdown(
                "По правкам заказчика ПД строится на задачах MSP (уровень 5, родитель «Проектная документация»). "
                "Ниже — текущий экран РД/выдачи; отдельная логика и графики ПД будут уточнены на следующих шагах."
            )

    if df is None or not hasattr(df, "columns") or df.empty:
        st.warning(
            f"Для отчёта «{page_title}» загрузите файл с данными проекта (CSV/Excel с колонками по задачам и РД)."
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

    # Check if required columns exist
    missing_cols = []
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

    # Find project column for filtering
    project_col = (
        "project name"
        if "project name" in df.columns
        else find_column(df, ["Проект", "project"])
    )

    # Add filters
    st.subheader("Фильтры")
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    # Filter by project
    selected_project = "Все"
    if project_col and project_col in df.columns:
        with filter_col1:
            projects = ["Все"] + sorted(df[project_col].dropna().unique().tolist())
            selected_project = st.selectbox(
                "Фильтр по проекту", projects, key=f"{_doc_fk}project_filter"
            )

    # Filter by date period
    selected_date_start = None
    selected_date_end = None
    if plan_start_col and plan_start_col in df.columns:
        with filter_col2:
            # Convert dates for filtering
            plan_start_str = df[plan_start_col].astype(str)
            df_dates = pd.to_datetime(
                plan_start_str, errors="coerce", dayfirst=True, format="mixed"
            )
            valid_dates = df_dates[df_dates.notna()]

            if not valid_dates.empty:
                min_date = valid_dates.min().date()
                max_date = valid_dates.max().date()
                selected_date_start = st.date_input(
                    "Дата начала периода",
                    value=min_date,
                    min_value=min_date,
                    max_value=max_date,
                    key=f"{_doc_fk}date_start",
                    format="DD.MM.YYYY",
                )
                selected_date_end = st.date_input(
                    "Дата окончания периода",
                    value=max_date,
                    min_value=min_date,
                    max_value=max_date,
                    key=f"{_doc_fk}date_end",
                    format="DD.MM.YYYY",
                )

    # Filter by RD status
    with filter_col3:
        rd_status_options = ["Все"]
        if on_approval_col and on_approval_col in df.columns:
            rd_status_options.append("На согласовании")
        if in_production_col and in_production_col in df.columns:
            rd_status_options.append("Выдано в производство работ")

        # Find other status columns
        contractor_col = find_column(df, ["Выдана подрядчику", "подрядчику"])
        rework_col = find_column(df, ["На доработке", "доработке"])

        if contractor_col and contractor_col in df.columns:
            rd_status_options.append("Выдана подрядчику")
        if rework_col and rework_col in df.columns:
            rd_status_options.append("На доработке")

        _status_label = (
            "Фильтр по статусу ПД"
            if page_title == "Проектная документация"
            else "Фильтр по статусу РД"
        )
        selected_statuses = st.multiselect(
            _status_label,
            options=rd_status_options,
            default=["Все"],
            key=f"{_doc_fk}status_filter",
        )

    # Apply filters to data
    filtered_df = df.copy()

    # Apply project filter
    if selected_project != "Все" and project_col and project_col in df.columns:
        filtered_df = filtered_df[
            filtered_df[project_col].astype(str).str.strip()
            == str(selected_project).strip()
        ]

    # Apply date filter
    if (
        selected_date_start
        and selected_date_end
        and plan_start_col
        and plan_start_col in df.columns
    ):
        plan_start_str = filtered_df[plan_start_col].astype(str)
        filtered_df[plan_start_col + "_parsed"] = pd.to_datetime(
            plan_start_str, errors="coerce", dayfirst=True, format="mixed"
        )
        date_mask = (
            filtered_df[plan_start_col + "_parsed"].notna()
            & (filtered_df[plan_start_col + "_parsed"].dt.date >= selected_date_start)
            & (filtered_df[plan_start_col + "_parsed"].dt.date <= selected_date_end)
        )
        filtered_df = filtered_df[date_mask].copy()

    # Apply status filter
    if "Все" not in selected_statuses and selected_statuses:
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
            "Выдана подрядчику" in selected_statuses
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

        filtered_df = filtered_df[status_mask].copy()

    if filtered_df.empty:
        st.info("Нет данных для выбранных фильтров.")
        return

    # Use filtered_df for all subsequent operations
    df = filtered_df

    # Prepare data for pie chart "Исполнение РД"
    # Sum values for "На согласовании" and "Выдано в производство работ"
    try:
        # Convert to numeric, handling comma as decimal separator
        on_approval_series = (
            df[on_approval_col].astype(str).str.replace(",", ".", regex=False)
        )
        on_approval_sum = (
            pd.to_numeric(on_approval_series, errors="coerce").fillna(0).sum()
        )

        in_production_series = (
            df[in_production_col].astype(str).str.replace(",", ".", regex=False)
        )
        in_production_sum = (
            pd.to_numeric(in_production_series, errors="coerce").fillna(0).sum()
        )

        # Create pie chart
        if on_approval_sum > 0 or in_production_sum > 0:
            st.subheader("Исполнение РД")
            # Округляем значения до целых
            pie_data = {
                "На согласовании": int(round(on_approval_sum)),
                "Выдано в производство работ": int(round(in_production_sum)),
            }

            fig_pie = px.pie(
                values=list(pie_data.values()),
                names=list(pie_data.keys()),
                title=None,
                color_discrete_map={
                    "На согласовании": "#2E86AB",
                    "Выдано в производство работ": "#06A77D",
                },
            )
            # На круговой диаграмме: абсолютное значение и процент в подписи (без наведения)
            fig_pie.update_traces(
                textinfo="label+percent",
                textposition="auto",
                textfont_size=10,
                insidetextorientation="radial",
                hovertemplate="<b>%{label}</b><br>Значение: %{value}<br>Процент: %{percent}<br><extra></extra>",
            )
            fig_pie.update_layout(
                height=500,
                showlegend=True,
                uniformtext=dict(minsize=8, mode="hide"),
                legend=dict(orientation="v", font=dict(size=10)),
            )

            fig_pie = apply_chart_background(fig_pie)
            render_chart(fig_pie, caption_below="Исполнение РД")
        else:
            st.info("Нет данных для построения графика 'Исполнение РД'.")
    except Exception as e:
        st.error(f"Ошибка при построении графика 'Исполнение РД': {str(e)}")

    # Prepare data for "Динамика выдачи РД"
    # X-axis: "Старт План" (plan start date)
    # Plan (Y-axis): "РД по Договору" (grouped by "Старт План")
    # Fact (Y-axis): "Выдано в производство работ" (grouped by "Старт План")
    try:
        # Find column for plan data: "РД по Договору"
        rd_plan_col = find_column(
            df, ["РД по Договору", "РД по договору", "рд по договору", "РД по Договору"]
        )

        # Check if required columns exist
        if not plan_start_col or plan_start_col not in df.columns:
            st.warning(
                "Для построения графика 'Динамика выдачи РД' необходима колонка 'Старт План' (plan start)."
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
        if plan_end_col and plan_end_col in df.columns:
            _mpe = pd.to_datetime(
                df[plan_end_col].astype(str), errors="coerce", dayfirst=True, format="mixed"
            )
            if _mpe.notna().any():
                max_plan_end_date = _mpe.max().date()
        _fact_end_col_rd = (
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
        _fact_end_use = _fact_end_col_rd or base_end_col
        if _fact_end_use and _fact_end_use in df.columns:
            _mfe = pd.to_datetime(
                df[_fact_end_use].astype(str), errors="coerce", dayfirst=True, format="mixed"
            )
            if _mfe.notna().any():
                max_fact_end_date = _mfe.max().date()

        # Convert columns to numeric - handle comma as decimal separator
        # Replace comma with dot for numeric conversion
        # Plan: use "РД по Договору"
        rd_plan_series = df[rd_plan_col].astype(str).str.replace(",", ".", regex=False)
        df["rd_plan_numeric"] = pd.to_numeric(rd_plan_series, errors="coerce").fillna(0)

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
                cnt_series = (
                    df[rd_sections_for_plan_fallback]
                    .astype(str)
                    .str.replace(",", ".", regex=False)
                )
                cnt_num = pd.to_numeric(cnt_series, errors="coerce").fillna(0.0)
                if float(cnt_num.sum()) > 0.0:
                    df["rd_plan_numeric"] = cnt_num

        # Convert "Выдано в производство работ" to numeric - handle comma as decimal separator
        in_production_series = (
            df[in_production_col].astype(str).str.replace(",", ".", regex=False)
        )
        df["in_production_numeric"] = pd.to_numeric(
            in_production_series, errors="coerce"
        ).fillna(0)

        # Convert dates - handle DD.MM.YYYY format
        # First convert to string, then parse with dayfirst=True
        plan_start_str = df[plan_start_col].astype(str)
        df[plan_start_col] = pd.to_datetime(
            plan_start_str, errors="coerce", dayfirst=True, format="mixed"
        )

        # Prepare data
        # Both Plan and Fact are grouped by plan_start_col (Старт план)
        dynamics_data = []

        # Plan data: group by plan start date, sum "РД по Договору"
        # Always include plan data, even if some values are 0
        plan_mask = df[plan_start_col].notna()
        if plan_mask.any():
            plan_grouped = (
                df[plan_mask]
                .groupby(df[plan_mask][plan_start_col].dt.date)
                .agg({"rd_plan_numeric": "sum"})
                .reset_index()
            )
            plan_grouped.columns = ["Дата", "Количество"]
            plan_grouped["Тип"] = "План"
            # Fill NaN with 0 and ensure all values are numeric
            plan_grouped["Количество"] = plan_grouped["Количество"].fillna(0)
            # Always add plan data, even if all values are 0
            dynamics_data.append(plan_grouped)

        # Fact data: group by plan start date (same as Plan!), sum "Выдано в производство работ"
        fact_mask = df[plan_start_col].notna()  # Use plan_start_col for both!
        if fact_mask.any():
            fact_grouped = (
                df[fact_mask]
                .groupby(df[fact_mask][plan_start_col].dt.date)
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

        # Always show graph if we have plan data, even if fact data is empty
        if dynamics_data:
            st.subheader("Динамика выдачи РД")
            dynamics_df = pd.concat(dynamics_data, ignore_index=True)
            dynamics_df = dynamics_df.sort_values("Дата")

            # Вычисляем накопительные значения для каждого типа отдельно
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

            # Create line chart with text labels always visible
            # Prepare text labels for each data point
            dynamics_df["Текст"] = dynamics_df["Количество"].apply(
                lambda x: f"{x:.0f}" if pd.notna(x) else ""
            )

            fig_dynamics = px.line(
                dynamics_df,
                x="Дата",
                y="Количество",
                color="Тип",
                title=None,
                markers=True,
                labels={"Количество": "Количество", "Дата": "Дата (Старт План)"},
                text="Текст",
            )

            fig_dynamics.update_layout(
                xaxis_title="Период",
                yaxis_title="Количество",
                hovermode="x unified",
                height=550,
                xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
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
                        "План (РД по Договору)"
                        if t.name == "План"
                        else (
                            "Факт (Выдано в производство работ)"
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
    """Проектная документация: основной экран + вкладка «Просрочка выдачи ПД»."""
    tab_main, tab_delay = st.tabs(["Проектная документация", "Просрочка выдачи ПД"])
    with tab_main:
        dashboard_documentation(
            df, page_title="Проектная документация", embed_delay_at_end=False
        )
    with tab_delay:
        dashboard_pd_delay(df)


# ==================== DASHBOARD 8: Budget by Type (Plan/Fact/Reserve) ====================
def dashboard_budget_by_type(df):
    st.header("Бюджет план/факт")
    with st.expander("Источник данных", expanded=False):
        st.caption(
            "Сводный план/факт по бюджету в разрезе проекта и этапа из загруженных данных; "
            "для сравнения с отчётом «БДДС» (обороты) используйте оба отчёта на одном наборе файлов."
        )

    col1, col2, col3 = st.columns(3)

    with col1:
        if "project name" in df.columns:
            projects = ["Все"] + sorted(df["project name"].dropna().unique().tolist())
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

    with col3:
        pass

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
    _csv = budget_table_display.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("Скачать CSV", _csv, "budget_plan_fact.csv", "text/csv", key="budget_type_csv")

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
                    legend=dict(
                        orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
                    ),
                    xaxis=dict(tickangle=-45, tickfont=dict(size=12)),
                )

                # Add text labels on the edge of bars (в миллионах рублей)
                fig_hist.update_traces(
                    textposition="outside",
                    texttemplate="%{text:.1f} млн руб.",
                    textfont=dict(size=12, color="white"),
                )

                fig_hist = _apply_finance_bar_label_layout(fig_hist)
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
                _csv = summary_hist.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                st.download_button("Скачать CSV", _csv, "budget_summary.csv", "text/csv", key="budget_summary_csv")
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


def compute_bddcs_forecast_monthly(work_df: pd.DataFrame, distribution_mode: str = "uniform", abc_source=None):
    """
    Возвращает DataFrame: month, bdds_plan_msp, bdds_forecast, bdds_fact;
    при режиме A/B/C — дополнительно bdds_forecast_a, bdds_forecast_b, bdds_forecast_c (руб. по месяцам).
    abc_source: DataFrame с колонками A %, B %, C % (или A_, B_, C_) той же длины, что work_df; иначе 34/33/33.
    """
    if work_df is None or work_df.empty:
        return pd.DataFrame(), "Нет данных для расчёта прогноза БДДС"
    df = work_df.copy().reset_index(drop=True)
    if abc_source is not None:
        abc_source = abc_source.reset_index(drop=True)
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
    use_abc = mode in ("abc", "%", "процент", "a/b/c", "a b c")

    fc_totals: dict = {}
    fc_totals_a: dict = {}
    fc_totals_b: dict = {}
    fc_totals_c: dict = {}
    fact_totals: dict = {}
    plan_msp = _bdds_msp_monthly_plan_activity(df)

    for pos in range(len(df)):
        r = df.iloc[pos]
        plan_amt = float(r["budget plan"])
        fact_amt = float(r["budget fact"])
        a, b, c = 34.0, 33.0, 33.0
        if use_abc and abc_source is not None and len(abc_source) > 0:
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

        if use_abc:
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
        if use_abc:
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
    with st.expander("Источник данных", expanded=False):
        st.caption(
            "По ТЗ детальный отчёт строится из CSV «ОборотыПоБюджетам» (колонки «сценарий», «Статья оборотов»). "
            "Блок ниже с распределением по месяцам — из задач и плановых сумм в MSP; при наличии колонок план/факт в данных — дополнительная сводка по проекту."
        )
        st.caption(
            "**Единицы:** график и таблицы ниже — **млн руб.** (внутренние суммы в рублях переводятся при отображении)."
        )

    with st.expander("Правила отображения", expanded=False):
        st.markdown(
            "Основной график — **план/факт по месяцам** в том же стиле, что отчёт «БДДС» (ТЗ, правки). "
            "Таблица по проекту: отклонение = **план − факт**."
        )
    with st.expander("Требования ТЗ (PDF): утверждённый бюджет", expanded=False):
        st.markdown(
            "Источник данных: CSV **«ОборотыПоБюджетам»**. Детальная таблица: проект; "
            "утверждённый бюджет (сценарий «Бюджет», статья без «(БДР)»); фактические расходы; "
            "отклонение с цветом по знаку (см. PDF «Правки»)."
        )

    # Фильтры (две колонки: проект, этап)
    col1, col2 = st.columns(2)

    with col1:
        # Check for project column - try English name first (alias from load_data), then Russian
        project_col = None
        if "project name" in df.columns:
            project_col = "project name"
        elif "Проект" in df.columns:
            project_col = "Проект"

        if project_col:
            projects = ["Все"] + sorted(df[project_col].dropna().unique().tolist())
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
            filtered_df[project_col].astype(str).str.strip()
            == str(selected_project).strip()
        ]
    if selected_section != "Все" and "section" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["section"].astype(str).str.strip()
            == str(selected_section).strip()
        ]

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
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=600,
        xaxis=dict(tickangle=-45, tickfont=dict(size=9), nticks=18),
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
    _csv = summary_table.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "Скачать CSV", _csv, "approved_budget_by_month.csv", "text/csv", key="appr_budget_summary_csv"
    )


# ==================== DASHBOARD: Forecast Budget ====================
def calculate_forecast_budget(df, edited_data=None, distribution_mode="uniform", abc_source=None):
    """
    Прогноз БДДС по месяцам: «БДДС план» (сводка по MSP), «БДДС прогноз» (распределение),
    «БДДС факт» (распределение факта по тем же весам).
    """
    work_df = edited_data.copy() if edited_data is not None else df.copy()
    return compute_bddcs_forecast_monthly(
        work_df, distribution_mode=distribution_mode, abc_source=abc_source
    )


def dashboard_forecast_budget(df):

    """Панель для отображения и редактирования прогнозного бюджета"""
    st.header("Прогнозный бюджет")
    with st.expander("Источник данных", expanded=False):
        st.caption(
            "Прогноз строится от распределения утверждённого бюджета по задачам MSP; "
            "при появлении отдельной загрузки «ОборотыПоБюджетам» логику можно согласовать с файлом оборотов."
        )
        st.caption(
            "**Единицы:** график и сводная таблица — **млн руб.**; в редакторе лотов суммы тоже в млн руб."
        )

    with st.expander("Требования ТЗ (PDF): БДДС утверждённый/прогнозный", expanded=False):
        st.markdown(
            "Отчёт **БДДС (утверждённый/прогнозный)** по PDF: визуалы как у «БДДС месяцы/накопительно»; "
            "столбцы **БДДС план**, **БДДС факт**, **БДДС прогноз**; прогноз считается от дат **Начало/Окончание** "
            "в MS Project по лоту и правил распределения (равномерно или % A/B/C). "
            "Блок редактирования ниже соответствует идее «Формирование БДДС прогноз»."
        )
    # Кратко: логика в expander «Требования ТЗ»; без дублирующего серого info (П.9)

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

    projects = sorted(df[project_col].dropna().unique().tolist())
    if not projects:
        st.warning("Проекты не найдены в данных.")
        return

    selected_project = st.selectbox(
        "Выберите проект", projects, key="forecast_budget_project"
    )

    # Фильтруем данные по выбранному проекту
    project_df = df[
        df[project_col].astype(str).str.strip() == str(selected_project).strip()
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

    st.subheader("Формирование БДДС прогноз")
    dist_label = st.radio(
        "Условие распределения денежных средств (по ТЗ PDF)",
        ["Равномерно", "% A / B / C"],
        horizontal=True,
        key=f"forecast_dist_mode_{selected_project}",
    )
    dist_key = "abc" if str(dist_label).startswith("%") else "uniform"

    def _build_forecast_edit_frame(pdf: pd.DataFrame) -> pd.DataFrame:
        cur = pdf.copy().reset_index(drop=True)
        ps = pd.to_datetime(cur["plan start"], errors="coerce", dayfirst=True)
        pe = pd.to_datetime(cur["plan end"], errors="coerce", dayfirst=True)
        bp = pd.to_numeric(cur["budget plan"], errors="coerce").fillna(0.0)
        if "budget fact" in cur.columns:
            bf = pd.to_numeric(cur["budget fact"], errors="coerce").fillna(0.0)
        else:
            bf = pd.Series(0.0, index=cur.index)
        # Даты как строки YYYY-MM-DD: `datetime.date` / NaT в Glide (st.data_editor) давали пустой блок без сетки.
        plan_start_str = ps.dt.strftime("%Y-%m-%d").fillna("")
        plan_end_str = pe.dt.strftime("%Y-%m-%d").fillna("")
        return pd.DataFrame(
            {
                "Лот": cur["section"].astype(str),
                "План. начало": plan_start_str,
                "План. окончание": plan_end_str,
                "БДДС план (утверждённый), млн руб.": (bp / 1e6).round(4),
                "БДДС факт, млн руб.": (bf / 1e6).round(4),
                "A, %": 34.0,
                "B, %": 33.0,
                "C, %": 33.0,
            }
        )

    _sess_key = f"forecast_edit_v4_{selected_project}"
    if _sess_key not in st.session_state:
        st.session_state[_sess_key] = _build_forecast_edit_frame(project_df)
    elif len(st.session_state[_sess_key]) != len(project_df):
        st.session_state[_sess_key] = _build_forecast_edit_frame(project_df)

    edit_df = st.session_state[_sess_key].copy()
    st.caption(
        "По PDF: столбец «Раздел» заменён на **Лот**; суммы в млн руб.; для режима A/B/C совокупно A+B+C=100% "
        "(при отклонении значения нормализуются). Редактирование таблицы сразу влияет на расчёт."
    )
    if st.button("Сбросить таблицу к данным файла", key=f"forecast_reset_v4_{selected_project}"):
        st.session_state[_sess_key] = _build_forecast_edit_frame(project_df)
        st.rerun()

    _row_px = 44
    _editor_h = max(220, min(560, _row_px * (max(1, len(edit_df)) + 2)))
    # Без min/max на числах — жёсткие ограничения иногда ломают отрисовку Glide при странных значениях.
    _fc = {
        "Лот": st.column_config.TextColumn("Лот", width="medium"),
        "План. начало": st.column_config.TextColumn(
            "План. начало", help="Формат ГГГГ-ММ-ДД; пусто — дата не задана."
        ),
        "План. окончание": st.column_config.TextColumn(
            "План. окончание", help="Формат ГГГГ-ММ-ДД; пусто — дата не задана."
        ),
        "БДДС план (утверждённый), млн руб.": st.column_config.NumberColumn(
            "БДДС план, млн", format="%.4f"
        ),
        "БДДС факт, млн руб.": st.column_config.NumberColumn("БДДС факт, млн", format="%.4f"),
        "A, %": st.column_config.NumberColumn("A, %", format="%.2f"),
        "B, %": st.column_config.NumberColumn("B, %", format="%.2f"),
        "C, %": st.column_config.NumberColumn("C, %", format="%.2f"),
    }
    edited_df = st.data_editor(
        edit_df,
        num_rows="fixed",
        key=f"forecast_editor_v4_{selected_project}",
        use_container_width=True,
        height=_editor_h,
        column_config=_fc,
        hide_index=True,
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

    abc_src = None
    if dist_key == "abc":
        abc_src = ed[["A, %", "B, %", "C, %"]].copy()
        sums = abc_src.sum(axis=1)
        if (sums - 100).abs().max() > 0.5:
            st.warning(
                "Сумма A+B+C по строкам должна быть **100%** (допуск ±0.5%). "
                "Значения будут автоматически нормализованы при расчёте."
            )

    forecast_budget_df, error = calculate_forecast_budget(
        df,
        edited_data=updated_data,
        distribution_mode=dist_key,
        abc_source=abc_src,
    )

    if error:
        st.error(error)
        return

    if forecast_budget_df.empty:
        st.info("Нет данных для построения графика прогнозного бюджета.")
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
        ["БДДС план (сводка MSP)", "БДДС факт"],
        horizontal=True,
        key=f"forecast_dev_basis_{selected_project}",
    )
    base_col = "bdds_plan_msp" if "сводка" in compare_to else "bdds_fact"
    mf["_dev"] = mf[base_col] - mf["bdds_forecast"]
    hide_dev = st.checkbox("Скрыть отклонение", value=False, key=f"forecast_hide_dev_{selected_project}")

    def _fmt_million_dot(x):
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        return f"{float(x):.2f}".replace(",", ".")

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=mf["Месяц"],
            y=mf["bdds_forecast_mln"],
            name="БДДС прогноз",
            marker_color="#06A77D",
            text=mf["bdds_forecast_mln"].apply(lambda x: _fmt_million_dot(x) if pd.notna(x) else ""),
            textposition="outside",
            textfont=dict(size=12, color="white"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=mf["Месяц"],
            y=mf["bdds_plan_msp_mln"],
            name="БДДС план (сводка MSP)",
            mode="lines+markers",
            line=dict(color="#F18F01", width=2),
            marker=dict(size=8, color="#F18F01"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=mf["Месяц"],
            y=mf["bdds_fact_mln"],
            name="БДДС факт",
            mode="lines+markers",
            line=dict(color="#3498db", width=2),
            marker=dict(size=8, color="#3498db"),
        )
    )
    if not hide_dev:
        fig.add_trace(
            go.Scatter(
                x=mf["Месяц"],
                y=(mf["_dev"] / 1e6).round(4),
                name="Отклонение (база − прогноз), млн руб.",
                mode="lines+markers",
                line=dict(color="#e74c3c", width=1, dash="dot"),
                marker=dict(size=6, color="#e74c3c"),
        )
    )

    fig.update_layout(
        yaxis_title="млн руб.",
        hovermode="x unified",
        height=600,
        xaxis=dict(
            title=dict(text="Месяц", standoff=26),
            tickangle=-45,
            tickfont=dict(size=10),
        ),
    )
    fig = _apply_finance_bar_label_layout(fig)
    fig = _plotly_legend_horizontal_below_plot(fig)
    fig = apply_chart_background(fig)
    try:
        ymax = float(
            max(
                mf["bdds_forecast_mln"].fillna(0).max(),
                mf["bdds_plan_msp_mln"].fillna(0).max(),
                mf["bdds_fact_mln"].fillna(0).max(),
            )
        )
    except Exception:
        ymax = 0.0
    if not hide_dev:
        try:
            ymax = max(ymax, float((mf["_dev"].abs() / 1e6).fillna(0).max()))
        except Exception:
            pass
    if not np.isfinite(ymax) or ymax <= 0:
        st.warning(
            "На графике **все значения нулевые** (или суммы/периоды не сходятся): проверьте **БДДС план/факт** "
            "и даты **План. начало / План. окончание** в таблице выше. При нулях столбцы и линии лежат на оси 0 и "
            "визуально «пропадают»."
        )
        try:
            fig.update_yaxes(range=[0, 1], rangemode="tozero")
        except Exception:
            pass
    render_chart(
        fig,
        caption_below=f"БДДС: план (сводка MSP) / факт / прогноз — проект: {selected_project}",
    )

    st.subheader("Сводная таблица по месяцам (млн руб.)")
    summary_table = mf[
        ["Месяц", "bdds_plan_msp_mln", "bdds_fact_mln", "bdds_forecast_mln"]
    ].copy()
    summary_table.columns = [
        "Месяц",
        "БДДС план (сводка MSP)",
        "БДДС факт",
        "БДДС прогноз",
    ]
    if dist_key == "abc":
        summary_table["Прогноз A, млн руб."] = mf["bdds_forecast_a_mln"]
        summary_table["Прогноз B, млн руб."] = mf["bdds_forecast_b_mln"]
        summary_table["Прогноз C, млн руб."] = mf["bdds_forecast_c_mln"]
    if not hide_dev:
        summary_table["Отклонение (база − прогноз)"] = (mf["_dev"] / 1e6).round(4)
    for c in summary_table.columns:
        if c == "Месяц":
            continue
        summary_table[c] = summary_table[c].apply(
            lambda x: f"{float(x):.2f}" if pd.notna(x) else "0.00"
        )
    st.markdown(format_dataframe_as_html(summary_table), unsafe_allow_html=True)
    _csv = summary_table.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("Скачать CSV", _csv, "forecast_bddcs_summary.csv", "text/csv", key="fcast_summary_csv")

    st.subheader("Детальные строки (лоты) — ввод для расчёта")
    st.markdown(format_dataframe_as_html(edited_df.head(500)), unsafe_allow_html=True)
    _csv2 = edited_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "Скачать CSV (лоты)",
        _csv2,
        "forecast_bddcs_lots.csv",
        "text/csv",
        key="fcast_detail_csv",
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
</style>
"""

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
        return "—"
    try:
        nf = float(val)
        return str(int(nf)) if nf == int(nf) else str(nf).strip()
    except (TypeError, ValueError):
        return str(val).strip()


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
    n_unresolved: int,
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
        + e(str(n_unresolved))
        + '</span><span class="s">всего</span></div><div class="pred-kpi-info"><h4>Неустраненные предписания</h4><p>Общее количество</p></div></div>'
        + '<div class="pred-kpi-item"><div class="pred-kpi-circle orange"><span class="n">'
        + e(str(n_overdue))
        + '</span><span class="s">всего</span></div><div class="pred-kpi-info"><h4>Просроченные предписания</h4><p>Требуют немедленного внимания</p></div></div>'
        + '<div class="pred-kpi-item"><div class="pred-kpi-circle red"><span class="n">'
        + e(str(n_critical))
        + '</span><span class="s">всего</span></div><div class="pred-kpi-info"><h4>Критические предписания</h4><p>Просрочка более 30 дней</p></div></div>'
        + "</div></div>"
    )


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


# ==================== DASHBOARD: Предписания по подрядчикам ====================
def dashboard_predpisania(df):
    """
    Отчёт «Предписания по подрядчикам» — TESSA, KindName содержит «Предписан».
    Оформление в общей тёмной теме дашборда (как остальные отчёты).
    """
    st.header("Предписания по подрядчикам")
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
        pred = work[work[kind_col].astype(str).str.contains("Предписан", case=False, na=False)].copy()
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

    # Повторно объединяем по ключу уже внутри выборки «предписания» (договор/срок могли быть только в других строках)
    pred = _tessa_fill_card_from_doc_lookup(pred)

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

    contr_col = _tessa_find_column(pred, ["CONTR", "Контрагент", "contr"])
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
            "ДатаИсполнения",
            "ExecutionDate",
            "TargetDate",
        ],
    )
    completion_col = _tessa_find_column(
        pred,
        ["Completed", "CompletionDate", "Дата завершения", "Факт устранения"],
    )
    doc_num_col = _tessa_find_column(
        pred,
        [
            "DocNumber",
            "Номер предписания",
            "НомерПредписания",
            "НомерДокумента",
            "Number",
        ],
    )
    if not doc_num_col:
        for col in pred.columns:
            k = str(col).strip().lower()
            if contract_col is not None and str(col) == str(contract_col):
                continue
            if "номер" in k and "договор" not in k and "contract" not in k:
                doc_num_col = col
                break
    creation_col_pred = _tessa_find_column(pred, ["CreationDate", "creationdate", "Дата создания"])

    _excl_guess = [kind_col, contr_col, obj_col, doc_num_col, creation_col_pred, completion_col]
    if not contract_col:
        contract_col = _pred_guess_contract_column(pred, exclude=_excl_guess)
    if not due_col:
        due_col = _pred_guess_due_column(pred, exclude=_excl_guess + [contract_col])

    st_l = pred["Статус"].astype(str)
    pred["_signed"] = st_l.str.contains("Подписан", case=False, na=False) | st_l.str.contains("Согласован", case=False, na=False)
    if due_col:
        pred["_due"] = _tessa_to_datetime(pred[due_col])
    else:
        pred["_due"] = pd.NaT

    def _overdue_days_row(r):
        if r["_signed"]:
            return 0
        if completion_col:
            cd = _tessa_to_datetime(pd.Series([r.get(completion_col)])).iloc[0]
            if pd.notna(cd):
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
    pred["_critical"] = pred["_overdue_days"] > 30

    st.markdown("**Фильтры**")
    fc1, fc2, fc3, fb1, fb2 = st.columns([2, 2, 2, 1, 1])
    if obj_col:
        projects = ["Все проекты"] + sorted(pred[obj_col].dropna().astype(str).str.strip().unique().tolist())
    else:
        projects = ["Все проекты"]
    if contr_col:
        contractors = ["Все подрядчики"] + sorted(
            pred[contr_col].dropna().astype(str).str.strip().unique().tolist(),
            key=lambda x: str(x).lower(),
        )
    else:
        contractors = ["Все подрядчики"]

    with fc1:
        if obj_col:
            sel_obj = st.selectbox("Проект", projects, key="pred_m_p")
        else:
            sel_obj = "Все проекты"
    with fc2:
        if contr_col:
            sel_contr = st.selectbox("Подрядчик", contractors, key="pred_m_c")
        else:
            sel_contr = "Все подрядчики"
    with fc3:
        contract_q = st.text_input("№ договора (частичный поиск)", "", key="pred_m_contract")
    with fb1:
        st.markdown("<br>", unsafe_allow_html=True)
        st.button("Применить", key="pred_m_apply", type="primary", use_container_width=True)
    with fb2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Сбросить", key="pred_m_reset", use_container_width=True):
            if obj_col:
                st.session_state.pred_m_p = "Все проекты"
            if contr_col:
                st.session_state.pred_m_c = "Все подрядчики"
            st.session_state.pred_m_contract = ""
            st.rerun()

    filtered = pred.copy()
    if sel_obj != "Все проекты" and obj_col:
        filtered = filtered[filtered[obj_col].astype(str).str.strip() == sel_obj]
    if sel_contr != "Все подрядчики" and contr_col:
        filtered = filtered[filtered[contr_col].astype(str).str.strip() == sel_contr]
    if contract_q.strip() and contract_col:
        filtered = filtered[
            filtered[contract_col].astype(str).str.lower().str.contains(contract_q.strip().lower(), na=False)
        ]

    if filtered.empty:
        st.info("Нет данных при выбранных фильтрах.")
        return

    if not due_col:
        st.caption(
            "Срок устранения считается отдельно от даты завершения (Completed). "
            "Укажите DueDate или «Срок устранения» в TESSA."
        )

    unres_mask = ~filtered["_signed"]
    n_unresolved = int(unres_mask.sum())
    n_overdue = int((unres_mask & (filtered["_overdue_days"] > 0)).sum())
    n_critical = int((unres_mask & filtered["_critical"]).sum())

    fu = filtered.loc[unres_mask]
    # Заголовок секции на всю ширину; ниже легенда и KPI в одной строке — верх легенды и блока «Ключевые показатели» совпадают
    st.subheader("Предписания по подрядчикам")

    col_chart, col_kpi = st.columns([2, 1])

    with col_chart:
        st.markdown(
            _PRED_DASH_MOCK_CSS
            + '<div class="pred-leg"><span style="color:#3498db;font-weight:600;">■</span> Неустраненные (всего) '
            "&nbsp;·&nbsp; <span style=\"color:#e67e22;font-weight:600;\">■</span> Просроченные "
            "&nbsp;·&nbsp; Числа у синих столбцов — всего неустранённых по подрядчику.</div>",
            unsafe_allow_html=True,
        )
        if contr_col and contr_col in fu.columns and not fu.empty:
            grp = (
                fu.groupby(contr_col, as_index=False)
                .agg(
                    Всего=(contr_col, "size"),
                    Просрочено=("_overdue_days", lambda x: int((x > 0).sum())),
                )
                .sort_values("Всего", ascending=False)
            )
            fig1 = go.Figure()
            fig1.add_trace(
                go.Bar(
                    y=grp[contr_col],
                    x=grp["Всего"],
                    name="Неустраненные",
                    orientation="h",
                    marker_color="#3498db",
                    text=grp["Всего"],
                    textposition="outside",
                    textfont=dict(color="#ffffff", size=14),
                )
            )
            fig1.add_trace(
                go.Bar(
                    y=grp[contr_col],
                    x=grp["Просрочено"],
                    name="Просроченные",
                    orientation="h",
                    marker_color="#e67e22",
                    text=grp["Просрочено"],
                    textposition="outside",
                    textfont=dict(color="#ffffff", size=14),
                )
            )
            fig1.update_layout(
                barmode="group",
                bargap=0.28,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
            )
            xmax = max(
                float(pd.to_numeric(grp["Всего"], errors="coerce").fillna(0).max()),
                float(pd.to_numeric(grp["Просрочено"], errors="coerce").fillna(0).max()),
                1.0,
            )
            fig1.update_layout(
                height=max(320, len(grp) * 36 + 100),
                yaxis_title="",
                xaxis_title="Количество",
                margin=dict(l=8, r=48, t=40, b=8),
                xaxis=dict(range=[0, xmax * 1.35]),
                uniformtext=dict(minsize=9, mode="show"),
            )
            fig1 = apply_chart_background(fig1)
            fig1.update_layout(uniformtext=dict(minsize=9, mode="show"))
            render_chart(fig1, key="pred_bar_main", caption_below="По подрядчикам: неустраненные и просроченные")
        else:
            st.info("Нет данных для диаграммы (нужна колонка подрядчика и неустраненные строки).")

    with col_kpi:
        st.markdown(
            _pred_kpi_circles_html(n_unresolved, n_overdue, n_critical, with_heading=True),
            unsafe_allow_html=True,
        )

    overdue_only = filtered.loc[unres_mask & (filtered["_overdue_days"] > 0)].copy()
    mock_blocks = _pred_build_overdue_mock_blocks(
        overdue_only, contr_col, obj_col, contract_col, doc_num_col, due_col
    )
    st.markdown(_pred_overdue_mock_table_html(mock_blocks, n_overdue), unsafe_allow_html=True)

    st.subheader("Все неустраненные предписания — детальная таблица")
    with st.expander("Примечание к таблице", expanded=False):
        st.caption("Сортировка: критические и просрочка сверху.")
    show = filtered.loc[unres_mask].copy()
    show = show.sort_values(["_critical", "_overdue_days"], ascending=[False, False])

    # Ровно 7 колонок в фиксированном порядке (как макет)
    table_df = _pred_build_seven_column_df(
        show, contr_col, obj_col, contract_col, doc_num_col, due_col
    )

    overdue_cnt = int((show["_overdue_days"] > 0).sum())
    st.caption(f"Записей: {len(table_df)} · просроченных: {overdue_cnt}")
    _render_html_table(table_df)
    csv_bytes = table_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("Скачать CSV", csv_bytes, "predpisania.csv", "text/csv", key="pred_csv")

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
                f"Показано {max_rows} из {len(df)} записей. Скачайте CSV для полных данных."
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
    section_col = _find(["section", "Раздел", "БЛОК"])
    block_col = _find(["block", "Блок", "Функциональный блок", "Functional block"])
    building_col = _find(["building", "Строение", "строение", "Сооружение"])
    lot_col = _find(["lot", "LOT", "Лот", "лот"])

    key_col = task_col or project_col
    if key_col:
        work = work[
            work[key_col].notna()
            & (~work[key_col].astype(str).str.strip().isin(["", "nan", "None", "NaN"]))
        ].reset_index(drop=True)

    if not project_col and not task_col:
        st.warning("Не найдены ключевые колонки (проект, задача). Проверьте формат файла.")
        return

    f1, f2 = st.columns(2)
    with f1:
        if project_col and project_col in work.columns:
            projects = ["Все"] + sorted(work[project_col].dropna().astype(str).str.strip().unique().tolist())
            sel_proj = st.selectbox("Проект", projects, key="dev_proj")
        else:
            sel_proj = "Все"
    with f2:
        if section_col and section_col in work.columns:
            sections = ["Все"] + sorted(work[section_col].dropna().astype(str).str.strip().unique().tolist())
            sel_section = st.selectbox("Раздел / верхний уровень (по колонке раздела)", sections, key="dev_section")
        else:
            sel_section = "Все"

    f3, f4 = st.columns(2)
    with f3:
        if block_col and block_col in work.columns:
            blocks = ["Все"] + sorted(work[block_col].dropna().astype(str).str.strip().unique().tolist())
            sel_block = st.selectbox("Функциональный блок", blocks, key="dev_block")
        else:
            sel_block = "Все"
    with f4:
        if building_col and building_col in work.columns:
            bopts = ["Все"] + sorted(work[building_col].dropna().astype(str).str.strip().unique().tolist())
            sel_building = st.selectbox("Строение", bopts, key="dev_building")
        else:
            sel_building = "Все"

    only_lot_rows = st.checkbox(
        "Отображение в ЛОТАХ",
        value=False,
        help="Показывать только строки с заполненным ЛОТ (если в файле есть колонка ЛОТ).",
        key="dev_only_lots",
    )
    # Не фильтруем по «Уровень» в UI: в MSP это не outline; выбор не «Все» оставлял только часть строк —
    # матрица ТЗ (вехи ур. 5 и т.д.) превращалась в сплошные Н/Д. Уровни отбора встроены в матрицу.

    filtered = work.copy()
    if sel_proj != "Все" and project_col:
        filtered = filtered[filtered[project_col].astype(str).str.strip() == sel_proj]
    if sel_section != "Все" and section_col:
        filtered = filtered[filtered[section_col].astype(str).str.strip() == sel_section]
    if sel_block != "Все" and block_col:
        filtered = filtered[filtered[block_col].astype(str).str.strip() == sel_block]
    if sel_building != "Все" and building_col:
        filtered = filtered[filtered[building_col].astype(str).str.strip() == sel_building]
    if only_lot_rows and lot_col and lot_col in filtered.columns:
        s = filtered[lot_col].astype(str).str.strip()
        filtered = filtered[s.ne("") & ~s.str.lower().isin(["nan", "none", "н/д"])]

    if filtered.empty:
        st.info("Нет данных при выбранных фильтрах.")
        return

    matrix_df = filtered.copy()
    uniq_proj_n = (
        int(work[project_col].dropna().astype(str).str.strip().nunique())
        if project_col and project_col in work.columns
        else 1
    )

    st.subheader("Матрица контрольных точек")
    if sel_proj == "Все" and project_col and uniq_proj_n > 1:
        st.info(
            "Выберите один проект в фильтре «Проект» — матрица строится по одному MSP-проекту "
            "(иначе смешиваются задачи разных проектов)."
        )
        return
    if matrix_df.empty:
        st.info("Нет строк MSP для выбранного проекта.")
        return

    rows_tz, _cap = build_dev_tz_matrix_rows(
        matrix_df,
        st.session_state.get("project_data"),
        st.session_state,
    )
    render_dev_tz_matrix(rows_tz, _TABLE_CSS)

    try:
        p_export = ""
        if project_col and project_col in matrix_df.columns and matrix_df[project_col].notna().any():
            p_export = str(
                matrix_df[project_col].dropna().astype(str).str.strip().iloc[0]
            ).strip()
        elif sel_proj and str(sel_proj).strip() != "Все":
            p_export = str(sel_proj).strip()
        export_df = pd.DataFrame(rows_tz)
        if "warn" in export_df.columns:
            export_df = export_df.rename(columns={"warn": "Подсветка_менее_100pct"})
        csv_name = "developer_projects_matrix.csv"
        if p_export:
            export_df.insert(0, "проект", p_export)
            slug = re.sub(r"[\s<>:\"/\\|?*]+", "_", p_export).strip("_")[:120] or "project"
            csv_name = f"developer_projects_matrix_{slug}.csv"
        csv_bytes = export_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "Скачать матрицу (CSV)",
            csv_bytes,
            csv_name,
            "text/csv",
            key="dev_matrix_csv_dl",
        )
    except Exception:
        pass


# ── Правки заказчика (Правки 1.pdf): скрытые и новые отчёты ─────────────────
def dashboard_pravki_report_hidden(df):
    """Заглушка: отчёт исключён из меню по правкам."""
    st.info(
        "Отчёт «Значения отклонений от базового плана» скрыт по правкам заказчика. "
        "Используйте «Отклонение от базового плана» или «Причины отклонений»."
    )


def dashboard_control_points(df):
    """
    Контрольные точки (MSP): матрица проектов × вехи по макету правок (скрин file-009).
    Админ-маппинг задач и журнал — отдельно.
    """
    st.header("Контрольные точки")
    with st.expander("Подсказка по фильтрам", expanded=False):
        st.caption(
            "Фильтры по выгрузке MSP: проект и при наличии колонки — строение. "
            "В «Статус» — цветовой индикатор (зелёный / красный; при % выполнения ≠ 100% для ГПЗУ и экспертизы — оранжевый фон в План/Факт/Откл.)."
        )
    if df is None or df.empty:
        st.warning("Загрузите данные MSP (проект).")
        return
    work = df.copy()
    has_fact_col = "plan end" in work.columns or "actual finish" in work.columns
    if "base end" not in work.columns or not has_fact_col:
        st.warning(
            "Нужны колонки базового и фактического окончания (base end и plan end / actual finish после загрузки MSP)."
        )
        return
    render_control_points_dashboard(st, work, _TABLE_CSS)


def dashboard_project_schedule_chart(df):
    """График проекта: Гант по плану и базе MSP, фильтры, таблица с отклонениями."""

    def _sched_col(d, candidates):
        for name in candidates:
            for c in d.columns:
                if str(name).strip().lower() == str(c).strip().lower():
                    return c
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
            "Переключатель подписей: на концах полос — дата окончания или % выполнения."
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

    f1, f2, f3, f4 = st.columns(4)
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
            sel_block = st.selectbox(
                "Функциональный блок (ур. 2)", blocks, key="gantt_block_filter"
            )
            if sel_block != "Все":
                plot_df = plot_df[plot_df[block_col].astype(str).str.strip() == str(sel_block).strip()]
        else:
            st.caption("Нет колонки функционального блока.")
    with f3:
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
    with f4:
        label_mode = st.radio(
            "Подписи у конца полос",
            ("Дата окончания", "% выполнения"),
            horizontal=True,
            index=0,
            key="gantt_bar_label_mode",
            help="Вид подписи у правого края полосы: дата окончания по плану или % выполнения из MSP.",
        )
        label_pct = label_mode == "% выполнения"

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

    if "pct complete" not in plot_df.columns:
        _pct_src = _sched_col(
            plot_df,
            [
                "percent complete",
                "% complete",
                "percent_complete",
                "Процент выполнения",
                "% завершения",
            ],
        )
        if _pct_src:
            plot_df = plot_df.copy()
            plot_df["pct complete"] = pd.to_numeric(plot_df[_pct_src], errors="coerce")

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

    plot_df["_gantt_y_label"] = [_gantt_trunc_label(s) for s in y_labels]

    has_base = "base start" in plot_df.columns and "base end" in plot_df.columns
    if has_base:
        has_base = plot_df["base start"].notna().any() and plot_df["base end"].notna().any()
    if not has_base:
        st.info("В данных нет заполненных «Базовое начало» / «Базовое окончание» — на диаграмме только текущий план.")

    plan_texts = []
    base_tasks, base_starts, base_ends, base_texts = [], [], [], []

    for _idx, row in plot_df.iterrows():
        ps, pe = row["plan start"], row["plan end"]
        pe_d = pe.strftime("%d.%m.%Y") if hasattr(pe, "strftime") else str(pe)
        pv = row["pct complete"] if "pct complete" in plot_df.columns else np.nan
        if label_pct and pd.notna(pv):
            try:
                plan_texts.append(f"{float(pv):.0f} %")
            except (TypeError, ValueError):
                plan_texts.append(pe_d)
        else:
            plan_texts.append(pe_d)
        if has_base:
            y = row["_gantt_y_label"]
            bs, be = row.get("base start"), row.get("base end")
            if pd.notna(bs) and pd.notna(be):
                base_tasks.append(y)
                base_starts.append(bs)
                base_ends.append(be)
                be_d = be.strftime("%d.%m.%Y") if hasattr(be, "strftime") else str(be)
                pv2 = row["pct complete"] if "pct complete" in plot_df.columns else np.nan
                if label_pct and pd.notna(pv2):
                    try:
                        base_texts.append(f"{float(pv2):.0f} %")
                    except (TypeError, ValueError):
                        base_texts.append(be_d)
                else:
                    base_texts.append(be_d)

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
    # Явно обновляем только trace плана (data[0]): подписи даты/% — через annotations (см. ниже),
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
    row_h = 26
    chart_h = min(2600, max(220, 96 + row_h * n))
    max_len = int(plot_df["_gantt_y_label"].astype(str).str.len().max() or 12)
    # Запас слева под длинные названия — без наложения на начало полос
    left_m = int(min(880, max(260, 10 * min(max_len, 96) + 72)))

    fig_gantt.update_yaxes(
        autorange="reversed",
        title=dict(text=""),
        tickfont=dict(size=11),
        side="left",
        ticklabelposition="outside",
        ticklabeloverflow="allow",
        ticklabelstandoff=20,
        categoryorder="array",
        categoryarray=vis["Название"].tolist(),
    )
    fig_gantt.update_xaxes(title_text="Дата", automargin=True, showgrid=True)
    _lo_pad = _hi_pad = None
    fig_gantt.update_layout(
        height=chart_h,
        margin=dict(l=left_m, r=300, t=48, b=96),
        bargap=0.28,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    # Запас по оси X, чтобы подписи у конца полос не упирались в край области графика.
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
            pad = timedelta(days=max(35.0, span_days * 0.08))
            _lo_pad = lo - pad
            _hi_pad = hi + pad
            fig_gantt.update_xaxes(range=[_lo_pad, _hi_pad], autorange=False)
    except Exception:
        pass
    # skip_uniformtext: глобальный apply_chart_background задаёт uniformtext mode=hide —
    # из‑за этого подписи у горизонтальных полос могут не отображаться.
    fig_gantt = apply_chart_background(fig_gantt, skip_uniformtext=True)
    try:
        if len(fig_gantt.data) > 0:
            fig_gantt.data[0].name = "План (начало–окончание)"
    except Exception:
        pass
    # Русские подписи месяцев на оси X (tickvals в ISO — иначе Plotly оставляет англ. локаль).
    try:
        if _lo_pad is not None and _hi_pad is not None:
            tvals, ttext = _gantt_ru_date_ticks(_lo_pad, _hi_pad)
            if tvals and ttext and len(tvals) == len(ttext):
                tickvals_iso = [pd.Timestamp(t).strftime("%Y-%m-%d") for t in tvals]
                fig_gantt.update_xaxes(
                    type="date",
                    tickmode="array",
                    tickvals=tickvals_iso,
                    ticktext=ttext,
                    tickangle=0,
                    tickformat="",
                )
    except Exception:
        pass
    try:
        fig_gantt.update_yaxes(title=dict(text=""))
    except Exception:
        pass
    # Подписи даты / % у правого края полос (в координатах данных — надёжнее, чем text у Bar).
    try:
        anns = []
        for i, (_, row) in enumerate(plot_df.iterrows()):
            y = row["_gantt_y_label"]
            pe = row["plan end"]
            if pd.notna(pe) and i < len(plan_texts):
                # Чередование сдвига, чтобы подписи с одинаковой датой не наезжали друг на друга
                xs = 4 + (i % 7) * 5
                ys = 6 + (i % 3) * 3
                anns.append(
                    dict(
                        x=pe,
                        y=y,
                        xref="x",
                        yref="y",
                        text=str(plan_texts[i]),
                        showarrow=False,
                        xanchor="left",
                        yanchor="middle",
                        xshift=xs,
                        yshift=ys,
                        font=dict(size=9, color="#f8fafc"),
                        bgcolor="rgba(18,28,40,0.55)",
                        borderpad=2,
                    )
                )
        if has_base and base_texts:
            bi = 0
            for i, (_, row) in enumerate(plot_df.iterrows()):
                bs, be = row.get("base start"), row.get("base end")
                if pd.notna(bs) and pd.notna(be) and bi < len(base_texts):
                    y = row["_gantt_y_label"]
                    xs = 4 + (i % 7) * 5
                    ys = -8 - (i % 3) * 3
                    anns.append(
                        dict(
                            x=be,
                            y=y,
                            xref="x",
                            yref="y",
                            text=str(base_texts[bi]),
                            showarrow=False,
                            xanchor="left",
                            yanchor="middle",
                            xshift=xs,
                            yshift=ys,
                            font=dict(size=8, color="#e9d5ff"),
                            bgcolor="rgba(40,18,48,0.55)",
                            borderpad=2,
                        )
                    )
                    bi += 1
        if anns:
            fig_gantt.update_layout(annotations=anns)
    except Exception as e:
        st.warning(f"Подписи у концов полос: {e}")

    # Подписи задач слева: не используем translateX на сотни px — в SVG подписи уезжают за край и не видны.
    # Выравнивание задаётся margin.l + ticklabelstandoff (см. update_yaxes/update_layout выше).
    render_chart(
        fig_gantt,
        caption_below="План (Начало–Окончание) и базовый план; подписи у конца полосы — дата или % выполнения.",
    )

    with st.expander("Таблица (первые строки)", expanded=False):
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
                d_end_num = (
                    plot_df["plan end"] - pd.to_datetime(plot_df["base end"], errors="coerce")
                ).dt.days

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
                st.caption(
                    f"Показано 80 из {len(plot_df)} строк (на диаграмме до 400 задач)."
                )


def dashboard_pd_delay(df):
    """Просрочка выдачи ПД — по правкам на базе MSP (временно общий каркас с РД)."""
    st.caption(
        "По правкам: источник — MSP; фильтры «Проект», «Разделы ПД»; замена РД→ПД в подписях. "
        "Ниже — тот же расчёт просрочки, что и для РД, пока не выделен отдельный набор колонок ПД."
    )
    dashboard_rd_delay(df)
