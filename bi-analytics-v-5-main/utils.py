
"""
Общие утилиты для дашбордов и приложения.
"""
import html as html_module
import io
import re
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import pytz
import streamlit as st

from config import RUSSIAN_MONTHS

# Часовой пояс Москвы (UTC+3, без перехода на летнее время)
MOSCOW_TZ = pytz.timezone("Europe/Moscow")
UTC_TZ = pytz.UTC

# Маппинг англоязычных названий колонок на русские для отображения в таблицах
TABLE_COLUMN_EN_TO_RU = {
    "project name": "Проект",
    "task name": "Задача",
    "reason of deviation": "Причина отклонений",
    "deviation in days": "Отклонений в днях",
    "plan end": "Конец план",
    "base end": "Конец факт",
    "plan start": "Старт план",
    "base start": "Старт факт",
    "period": "Период",
    "deviation": "Отклонение",
    "section": "Раздел",
    "plan_month": "План (месяц)",
    # Доп. варианты (регистр / экспорт Plotly)
    "project": "Проект",
    "task": "Задача",
    "month": "Месяц",
    "count": "Количество",
    "quantity": "Количество",
    "start": "Начало",
    "end": "Окончание",
    "duration": "Длительность",
    "type": "Тип",
    "value": "Значение",
    "budget plan": "Плановый бюджет",
    "budget fact": "Фактический бюджет",
    "forecast budget": "Прогнозный бюджет",
    "approved budget": "Утверждённый бюджет",
}


def ru_column_header(col: Any) -> str:
    """Заголовок колонки для HTML/таблиц: англ. → рус., иначе как есть."""
    if col is None:
        return ""
    s = str(col).strip()
    if s in TABLE_COLUMN_EN_TO_RU:
        return TABLE_COLUMN_EN_TO_RU[s]
    low = s.lower()
    if low in TABLE_COLUMN_EN_TO_RU:
        return TABLE_COLUMN_EN_TO_RU[low]
    for en, ru in TABLE_COLUMN_EN_TO_RU.items():
        if en.lower() == low:
            return ru
    return s

# Фон HTML-таблиц (чуть темнее карточки контента для контраста)
TABLE_BG_COLOR = "hsl(209,67%,12%)"
# Фон области графиков Plotly — как карточка контента (.main .block-container: rgba(18,56,92,0.8))
CHART_BG_COLOR = "rgba(18, 56, 92, 0.88)"
TABLE_TEXT_COLOR = "#ffffff"

# Размерность сумм: млн рублей
MILLION = 1_000_000


def norm_partner_join_key(val: Any) -> str:
    """
    Ключ для сопоставления наименований контрагентов между файлами (1С ДтКт, справочник, обороты).
    Нижний регистр, пробелы, без кавычек «» и лишних хвостов вроде ООО.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip()
    s = s.replace("«", "").replace("»", "").replace('"', "").replace("'", "")
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(
        r"\s*(\bооо\b|\bзао\b|\bоао\b|\bпао\b|\bип\b)\s*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    return s.strip()


def format_russian_datetime(dt_str: str | None, with_seconds: bool = False) -> str:
    """
    Форматирует ISO-строку времени (предположительно в UTC) в русское представление
    в часовом поясе Москвы (Europe/Moscow).

    Args:
        dt_str: строка в формате ISO 8601 (например '2026-02-18T04:15:00+00:00')
        with_seconds: показывать секунды или только часы:минуты

    Returns:
        Строка вида "18 фев. 2026, 07:15" или "18 фев. 2026, 07:15:23"
    """
    if not dt_str:
        return "-"

    try:
        # Поддержка как с Z, так и с +00:00
        dt_str_clean = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_str_clean)

        # Если нет информации о часовом поясе → считаем UTC
        if dt.tzinfo is None:
            dt = UTC_TZ.localize(dt)

        # Конвертируем в московское время
        local_dt = dt.astimezone(MOSCOW_TZ)

        day = local_dt.day
        month_ru = RUSSIAN_MONTHS.get(local_dt.month, local_dt.strftime("%B"))
        year = local_dt.year
        time_fmt = "%H:%M:%S" if with_seconds else "%H:%M"
        time_str = local_dt.strftime(time_fmt)

        return f"{day} {month_ru} {year}, {time_str}"

    except (ValueError, TypeError) as e:
        # Если парсинг не удался — возвращаем исходную строку или заглушку
        return dt_str or "-"


def ensure_budget_columns(df: Optional[pd.DataFrame]) -> None:
    """Добавляет budget plan / budget fact из русских/альтернативных названий, если их ещё нет."""
    if df is None or not hasattr(df, "columns"):
        return
    if "budget plan" not in df.columns:
        for name in ("Бюджет План", "Бюджет план", "Budget Plan", "budget_plan"):
            if name in df.columns:
                df["budget plan"] = df[name]
                break
    if "budget fact" not in df.columns:
        for name in ("Бюджет Факт", "Бюджет факт", "Budget Fact", "budget_fact"):
            if name in df.columns:
                df["budget fact"] = df[name]
                break


def outline_level_numeric(series: pd.Series) -> pd.Series:
    """
    Числовой уровень иерархии MSP (outline): 2, «2», «Уровень 2».
    Используется в фильтрах «Функциональный блок»/«Строение» и при заполнении level structure.
    """
    if series is None or len(series) == 0:
        return pd.Series(dtype=float)
    num = pd.to_numeric(series, errors="coerce")
    mask_na = num.isna()
    if not mask_na.any():
        return num
    s_rest = series[mask_na].astype(str).str.strip()
    ext = s_rest.str.extract(r"(-?\d+)", expand=False)
    num2 = pd.to_numeric(ext, errors="coerce")
    out = num.copy()
    out.loc[mask_na] = num2.values
    return out


def ensure_date_columns(df: Optional[pd.DataFrame]) -> None:
    """
    Добавляет plan start, plan end, base start, base end из русских названий,
    если английских колонок ещё нет.
    """
    if df is None or not hasattr(df, "columns"):
        return
    date_mapping = [
        ("plan start", ["Старт План", "План Старт", "Plan Start"]),
        ("plan end", ["Конец План", "План Конец", "Plan End"]),
        ("base start", ["Старт Факт", "Факт Старт", "Base Start"]),
        ("base end", ["Конец Факт", "Факт Конец", "Base End"]),
    ]
    for en_name, ru_names in date_mapping:
        if en_name not in df.columns:
            for ru in ru_names:
                if ru in df.columns:
                    df[en_name] = df[ru].copy()
                    break


def ensure_msp_hierarchy_columns(df: Optional[pd.DataFrame]) -> None:
    """
    Добавляет canonical-колонки MSP для дерева задач: task name, level structure, level.

    Ручная загрузка через data_loader не применяет web_loader._MSP_COLUMN_REMAP — без этого
    нет «Уровень_структуры» → level structure, и фильтры «Функциональный блок»/«Строение»
    остаются на колонке block («Блок 1»…).
    """
    if df is None or not hasattr(df, "columns") or getattr(df, "empty", True):
        return

    def _col_by_exact(names: tuple[str, ...]):
        lower_map = {str(c).strip().lower(): c for c in df.columns}
        for n in names:
            key = str(n).strip().lower()
            if key in lower_map:
                return lower_map[key]
        return None

    if "task name" not in df.columns:
        src = _col_by_exact(
            (
                "Название задачи",
                "Название",
                "Task Name",
                "Имя",
                "Имя задачи",
                "Задача",
            )
        )
        if src is not None:
            df["task name"] = df[src]

    src_outline = _col_by_exact(
        (
            "Уровень_структуры",
            "Уровень структуры",
            "Outline Level",
            "outline level",
            "WBS Level",
            "Исходный уровень",
        )
    )
    if src_outline is None:
        for c in df.columns:
            sl = re.sub(r"\s+", " ", str(c).replace("\ufeff", "").strip().lower())
            sl = sl.replace("_", " ")
            if re.search(r"(уровень.*структ|структ.*уровень|outline\s*level|wbs\s*level)", sl):
                if "приоритет" in sl or "риск" in sl:
                    continue
                src_outline = c
                break
    src_level = _col_by_exact(("Уровень", "Level"))

    if "level structure" not in df.columns:
        if src_outline is not None:
            df["level structure"] = outline_level_numeric(df[src_outline])
        elif src_level is not None:
            df["level structure"] = outline_level_numeric(df[src_level])
    elif src_outline is not None and df["level structure"].notna().sum() == 0:
        df["level structure"] = outline_level_numeric(df[src_outline])

    if "level" not in df.columns:
        if src_level is not None:
            df["level"] = outline_level_numeric(df[src_level])
        elif "level structure" in df.columns:
            df["level"] = df["level structure"]
    elif src_level is not None and df["level"].notna().sum() == 0:
        df["level"] = outline_level_numeric(df[src_level])

    for _col in ("level structure", "level"):
        if _col in df.columns:
            df[_col] = outline_level_numeric(df[_col])

    normalize_plan_month_column(df)


def normalize_plan_month_column(df: Optional[pd.DataFrame]) -> None:
    """
    Приводит колонку plan_month к месячным Period (избегает TypeError str vs Period при фильтрах).
    """
    if df is None or not hasattr(df, "columns") or getattr(df, "empty", True):
        return
    if "plan_month" not in df.columns:
        return
    s = df["plan_month"]
    try:
        if isinstance(s.dtype, pd.PeriodDtype):
            return
    except Exception:
        pass
    if str(getattr(s, "dtype", "")).startswith("period"):
        return

    def _one(v: Any) -> Any:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return pd.NaT
        if isinstance(v, pd.Period):
            fs = getattr(v, "freqstr", None) or ""
            if fs == "M" or str(fs).startswith("M"):
                return v
            try:
                return v.asfreq("M")
            except Exception:
                return v
        if isinstance(v, pd.Timestamp):
            return v.to_period("M")
        vs = str(v).strip()
        if not vs or vs.lower() in ("nan", "nat", "none"):
            return pd.NaT
        try:
            if re.match(r"^\d{4}-\d{2}", vs):
                return pd.Period(vs[:7], freq="M")
        except Exception:
            pass
        try:
            ts = pd.to_datetime(vs, errors="coerce", dayfirst=True)
            if pd.notna(ts):
                return ts.to_period("M")
        except Exception:
            pass
        return pd.NaT

    try:
        df["plan_month"] = s.map(_one)
    except Exception:
        return


def get_russian_month_name(period_val: Any) -> str:
    """Возвращает русское название месяца для Period, Timestamp или строки."""
    if isinstance(period_val, pd.Period):
        if period_val.freqstr == "M" or (getattr(period_val, "freqstr", "") or "").startswith("M"):
            month_num = period_val.month
            return RUSSIAN_MONTHS.get(month_num, period_val.strftime("%B"))
        try:
            month_num = period_val.month
            return RUSSIAN_MONTHS.get(month_num, "")
        except Exception:
            return ""
    elif isinstance(period_val, (int, pd.Timestamp)):
        month_num = period_val.month if hasattr(period_val, "month") else period_val
        return RUSSIAN_MONTHS.get(month_num, "")
    elif isinstance(period_val, str):
        try:
            if "-" in period_val:
                parts = period_val.split("-")
                if len(parts) >= 2:
                    month_num = int(parts[1])
                    return RUSSIAN_MONTHS.get(month_num, "")
        except Exception:
            pass
    return ""


def format_period_ru(period_val) -> str:
    if period_val is None or (isinstance(period_val, float) and pd.isna(period_val)):
        return "Н/Д"
    try:
        if pd.isna(period_val):
            return "Н/Д"
    except (TypeError, ValueError):
        pass
    try:
        if isinstance(period_val, pd.Period):
            month_num = period_val.month
            year = period_val.year
            return f"{RUSSIAN_MONTHS.get(month_num, 'Н/Д')} {year}"
        if isinstance(period_val, pd.Timestamp):
            return f"{RUSSIAN_MONTHS.get(period_val.month, 'Н/Д')} {period_val.year}"
        if isinstance(period_val, str):
            s = period_val.strip()
            if not s or s.lower() in ("nan", "nat", "none"):
                return "Н/Д"
            if "-" in s:
                parts = s.split("-")
                if len(parts) >= 2:
                    try:
                        year = int(parts[0])
                        month = int(parts[1])
                        return f"{RUSSIAN_MONTHS.get(month, 'Н/Д')} {year}"
                    except (ValueError, TypeError):
                        pass
            try:
                ts = pd.Timestamp(s)
                if pd.notna(ts):
                    return f"{RUSSIAN_MONTHS.get(ts.month, 'Н/Д')} {ts.year}"
            except Exception:
                pass
            return s
        if hasattr(period_val, "month") and hasattr(period_val, "year"):
            return f"{RUSSIAN_MONTHS.get(period_val.month, 'Н/Д')} {period_val.year}"
    except Exception:
        pass
    out = str(period_val) if period_val is not None else "Н/Д"
    if isinstance(out, str) and out.strip().lower() in ("nan", "nat", "none"):
        return "Н/Д"
    return out


def apply_chart_background(fig, *, skip_uniformtext: bool = False):
    """
    Применяет единый стиль (тёмная тема) ко всем графикам Plotly.
    Вызывается перед st.plotly_chart() в каждом дашборде.

    skip_uniformtext: если True — не задаётся uniformtext (по умолчанию mode=show).
    Нужно для Ганта с подписями textposition='outside' у концов полос, если
    внешние настройки не подходят.
    """
    # Если дашборд уже задал вертикальную легенду и/или увеличенные поля — не затираем
    # (иначе глобальная горизонтальная легенда и margin b=100/r=30 ломают вёрстку).
    layout = fig.layout
    prev_leg = getattr(layout, "legend", None) if layout is not None else None
    prev_m = getattr(layout, "margin", None) if layout is not None else None
    keep_vertical_legend = (
        prev_leg is not None and getattr(prev_leg, "orientation", None) == "v"
    )
    margin_l = 60
    margin_r = 30
    margin_t = 55
    margin_b = 100
    if prev_m is not None:
        for attr, default in (("l", margin_l), ("r", margin_r), ("t", margin_t), ("b", margin_b)):
            v = getattr(prev_m, attr, None)
            if v is not None and float(v) > float(default):
                if attr == "l":
                    margin_l = float(v)
                elif attr == "r":
                    margin_r = float(v)
                elif attr == "t":
                    margin_t = float(v)
                elif attr == "b":
                    margin_b = float(v)

    # Базовый стиль
    layout_kwargs = dict(
        template=None,
        plot_bgcolor=CHART_BG_COLOR,
        paper_bgcolor=CHART_BG_COLOR,
        autosize=True,
        font=dict(
            family="Inter, system-ui, sans-serif",
            color=TABLE_TEXT_COLOR,
            size=13,
        ),
        # text обязателен: иначе во фронтенде Plotly иногда показывает строку «undefined»
        title=dict(
            text="",
            font=dict(color=TABLE_TEXT_COLOR, size=15),
            pad=dict(t=4),
        ),
        margin=dict(l=margin_l, r=margin_r, t=margin_t, b=margin_b),
    )
    if not skip_uniformtext:
        layout_kwargs["uniformtext"] = dict(minsize=8, mode="show")
    if keep_vertical_legend:
        # Только цвета шрифта/фона легенды; положение x/y/orientation оставляем как в дашборде
        layout_kwargs["legend"] = dict(
            font=dict(color=TABLE_TEXT_COLOR, size=12),
            bgcolor="rgba(0,0,0,0)",
        )
    else:
        # Дефолт — полоска легенды под графиком. Если дашборд уже задал y/yanchor (напр. y<0, yanchor=top),
        # не затирать — иначе легенда снова уезжает «вверх»/в центр после этого вызова.
        legend_base = dict(
            font=dict(color=TABLE_TEXT_COLOR, size=12),
            bgcolor="rgba(0,0,0,0)",
            orientation="h",
            yanchor="bottom",
            y=-0.25,
            xanchor="center",
            x=0.5,
        )
        if prev_leg is not None:
            py = getattr(prev_leg, "y", None)
            ya = getattr(prev_leg, "yanchor", None)
            try:
                py_f = float(py) if py is not None else None
            except (TypeError, ValueError):
                py_f = None
            custom_below = (py_f is not None and py_f < 0) or ya == "top"
            if custom_below:
                for key in ("x", "y", "xanchor", "yanchor", "xref", "yref", "orientation"):
                    val = getattr(prev_leg, key, None)
                    if val is not None:
                        legend_base[key] = val
        layout_kwargs["legend"] = legend_base
    fig.update_layout(**layout_kwargs)

    # Оси X
    fig.update_xaxes(
        gridcolor="rgba(255,255,255,0.08)",
        linecolor="rgba(255,255,255,0.25)",
        tickfont=dict(color=TABLE_TEXT_COLOR, size=11),
        title=dict(font=dict(color=TABLE_TEXT_COLOR, size=12)),
        zerolinecolor="rgba(255,255,255,0.2)",
        automargin=True,
        ticklabelstandoff=8,
    )

    # Оси Y
    fig.update_yaxes(
        gridcolor="rgba(255,255,255,0.08)",
        linecolor="rgba(255,255,255,0.25)",
        tickfont=dict(color=TABLE_TEXT_COLOR, size=11),
        title=dict(font=dict(color=TABLE_TEXT_COLOR, size=12)),
        zerolinecolor="rgba(255,255,255,0.2)",
        automargin=True,
    )

    return fig


def format_million_rub(value) -> str:
    """Форматирует сумму в млн руб.: 940346 -> '0.94 млн руб.'"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    try:
        x = float(value) / MILLION
        return f"{x:.2f} млн руб."
    except (TypeError, ValueError):
        return ""


def to_million_rub(value):
    """Возвращает значение в млн руб. (для осей графиков)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value) / MILLION
    except (TypeError, ValueError):
        return None


def _parse_date_cell(v):
    """Парсит ячейку с датой (строка dd.mm.yyyy, yyyy-mm-dd или datetime) в date для сравнения."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date() if pd.notna(v) else None
    if hasattr(v, "date") and callable(getattr(v, "date", None)):
        try:
            return v.date()
        except (TypeError, ValueError):
            pass
    s = str(v).strip()
    if not s or s.lower() in ("nan", "nat", "none", ""):
        return None
    try:
        parsed = pd.to_datetime(s, format="%d.%m.%Y", errors="coerce")
        if pd.notna(parsed):
            return parsed.date() if hasattr(parsed, "date") else parsed
    except (TypeError, ValueError):
        pass
    try:
        parsed = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
        if pd.notna(parsed):
            return parsed.date() if hasattr(parsed, "date") else parsed
    except (TypeError, ValueError):
        pass
    try:
        parsed = pd.to_datetime(s, errors="coerce")
        if pd.notna(parsed):
            return parsed.date() if hasattr(parsed, "date") else parsed
    except (TypeError, ValueError):
        pass
    return None


def style_dataframe_for_dark_theme(
    df: pd.DataFrame,
    days_column: Optional[str] = None,
    finance_deviation_column: Optional[str] = None,
    plan_date_column: Optional[str] = None,
    fact_date_column: Optional[str] = None,
    percent_deviation_gradient_column: Optional[str] = None,
    *,
    extra_days_columns: Optional[tuple] = None,
    finance_deviation_abs_min_mln: float = 0.01,
):
    """
    Styler для тёмной темы (`st.dataframe` / `st.table`): фон, контраст, **§4.8** — плотные ячейки.
    """
    if df is None or df.empty:
        return df.style

    # Переименование англоязычных колонок в русские
    rename_map = {c: TABLE_COLUMN_EN_TO_RU.get(c, c) for c in df.columns}
    df = df.rename(columns=rename_map)

    _cell_dense = {
        "background-color": TABLE_BG_COLOR,
        "color": TABLE_TEXT_COLOR,
        "font-size": "13px",
        "padding": "5px 8px",
        "max-width": "16em",
        "white-space": "nowrap",
        "overflow": "hidden",
        "text-overflow": "ellipsis",
    }
    base = df.style.set_properties(**_cell_dense).set_table_styles(
        [
            {
                "selector": "th",
                "props": [
                    ("background-color", TABLE_BG_COLOR),
                    ("color", TABLE_TEXT_COLOR),
                    ("border", "0"),
                    ("font-size", "13px"),
                    ("padding", "6px 8px"),
                    ("max-width", "18em"),
                    ("white-space", "nowrap"),
                    ("overflow", "hidden"),
                    ("text-overflow", "ellipsis"),
                ],
            },
            {"selector": "th *, td *", "props": [("color", TABLE_TEXT_COLOR)]},
        ]
    )

    # Подсветка по дням отклонения (одна или несколько колонок «дней»)
    def _days_cell_color(series):
        result = []
        for v in series:
            num = pd.to_numeric(v, errors="coerce")
            if pd.isna(num):
                result.append(f"background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR}")
            elif num > 0:
                result.append("background-color: #c0392b; color: #ffffff")
            else:
                result.append("background-color: #27ae60; color: #ffffff")
        return result

    _dev_day_cols = []
    if days_column and days_column in df.columns:
        _dev_day_cols.append(days_column)
    if extra_days_columns:
        for _c in extra_days_columns:
            if _c and _c in df.columns and _c not in _dev_day_cols:
                _dev_day_cols.append(_c)
    for _dc in _dev_day_cols:
        base = base.apply(
            lambda c, _name=_dc: _days_cell_color(c) if c.name == _name else [""] * len(c),
            axis=0,
        )

    # Подсветка финансовых отклонений
    if finance_deviation_column and finance_deviation_column in df.columns:
        _fin_dev_min = float(finance_deviation_abs_min_mln)

        def _finance_cell_color(series):
            result = []
            for v in series:
                num = None
                try:
                    s = str(v).strip().replace(",", ".")
                    if s and s not in ("", "nan", "None"):
                        num = float(s)
                    else:
                        match = re.search(r"-?\d+[.,]?\d*", str(v))
                        if match:
                            num = float(match.group().replace(",", "."))
                except (TypeError, ValueError):
                    pass
                if num is None or pd.isna(num):
                    result.append(f"background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR}")
                elif _fin_dev_min > 0 and abs(float(num)) < _fin_dev_min:
                    result.append(f"background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR}")
                elif num >= 0:
                    result.append("background-color: #c0392b; color: #ffffff")
                else:
                    result.append("background-color: #27ae60; color: #ffffff")
            return result
        base = base.apply(
            lambda c: _finance_cell_color(c) if c.name == finance_deviation_column else [""] * len(c),
            axis=0,
        )

    # Подсветка дат план/факт
    if plan_date_column and fact_date_column and plan_date_column in df.columns and fact_date_column in df.columns:
        plan_series = df[plan_date_column]
        fact_series = df[fact_date_column]

        def _plan_fact_cell_color(idx):
            plan_val = _parse_date_cell(plan_series.iloc[idx])
            fact_val = _parse_date_cell(fact_series.iloc[idx])
            if plan_val is None or fact_val is None:
                return f"background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR}"
            if fact_val < plan_val:
                return "background-color: #27ae60; color: #ffffff"
            if fact_val > plan_val:
                return "background-color: #c0392b; color: #ffffff"
            return f"background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR}"

        def _plan_fact_row_style(series):
            styles = [_plan_fact_cell_color(i) for i in range(len(series))]
            return pd.Series(styles, index=series.index)

        def _apply_plan_fact_style(column):
            if column.name in (plan_date_column, fact_date_column):
                return _plan_fact_row_style(column)
            return pd.Series([""] * len(column), index=column.index)

        base = base.apply(_apply_plan_fact_style, axis=0)

    # Градиент по числовому % отклонения (светло-зелёный → красный) для колонки вроде «Отклонение %»
    if percent_deviation_gradient_column and percent_deviation_gradient_column in df.columns:

        def _pct_gradient_style(series):
            out = []
            nums = pd.to_numeric(series, errors="coerce")
            valid = nums.dropna()
            if valid.empty:
                vmin, vmax = -100.0, 100.0
            else:
                vmin = float(valid.min())
                vmax = float(valid.max())
            span = (vmax - vmin) if vmax != vmin else 1.0
            for v in series:
                num = pd.to_numeric(v, errors="coerce")
                if pd.isna(num):
                    out.append(f"background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR}")
                    continue
                t = (float(num) - vmin) / span
                t = max(0.0, min(1.0, t))
                # зелёный → жёлтый → красный
                if t <= 0.5:
                    r = int(46 + (241 - 46) * (t / 0.5))
                    g = int(204 + (196 - 204) * (t / 0.5))
                    b = int(113 + (15 - 113) * (t / 0.5))
                else:
                    u = (t - 0.5) / 0.5
                    r = int(241 + (192 - 241) * u)
                    g = int(196 + (57 - 196) * u)
                    b = int(15 + (43 - 15) * u)
                out.append(f"background-color: rgb({r},{g},{b}); color: #ffffff; font-weight: 600")
            return out

        base = base.apply(
            lambda c: _pct_gradient_style(c)
            if c.name == percent_deviation_gradient_column
            else [""] * len(c),
            axis=0,
        )

    return base


def _parse_finance_value(v) -> Optional[float]:
    """Извлекает число из ячейки (например '0.94 млн руб.' или '-1.20')."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        s = str(v).strip().replace(",", ".")
        if s and s not in ("", "nan", "None"):
            return float(s)
    except (TypeError, ValueError):
        pass
    match = re.search(r"-?\d+[.,]?\d*", str(v))
    if match:
        try:
            return float(match.group().replace(",", "."))
        except (TypeError, ValueError):
            pass
    return None


def budget_table_to_html(
    df: pd.DataFrame,
    finance_deviation_column: Optional[str] = None,
    *,
    deviation_red_if_positive_only: bool = False,
    deviation_red_if_negative: bool = False,
    deviation_abs_min_mln: float = 0.01,
    deviation_semaphore_style: bool = False,
    row_kind_column: Optional[str] = None,
    emphasize_row_kinds: tuple[str, ...] = ("project", "total"),
    emphasize_row_font_em: float = 1.12,
) -> str:
    """
    Строит HTML таблицы бюджета с раскраской колонки отклонения.

    По умолчанию (финансы бюджета, отклонение = факт − план): значение ≥ 0 — красный шрифт, < 0 — зелёный.

    Если ``deviation_red_if_positive_only=True`` (например, отклонение = план − факт в графике рабочей силы):
    значение > 0 — красный, ≤ 0 — зелёный.

    Если ``deviation_semaphore_style=True`` вместе с ``deviation_red_if_positive_only=True``:
    индикатор ● зелёный при отклонении ≥ 0, красный при < 0; цвет числа — красный при > 0, зелёный при ≤ 0.

    Если ``deviation_red_if_negative=True`` (ТЗ «Утверждённый бюджет»: отклонение = план − факт):
    значение < 0 — красный, ≥ 0 — зелёный.

    Если ``|число| < deviation_abs_min_mln`` (по умолчанию 0.01 млн руб.), ячейка без акцентного цвета — как обычный текст.
    """
    if df is None or df.empty:
        return "<p>Нет данных для отображения.</p>"

    wrap_id = "bdt_" + str(id(df))
    parts = [
        f'<div id="{wrap_id}" class="budget-deviation-table-wrap" style="overflow-x: auto; min-width: 0; margin: 0.75em 0;">',
        f'<style>'
        f'#{wrap_id} table {{ table-layout: auto; font-size: 13px; }}'
        f'#{wrap_id} th, #{wrap_id} td {{ max-width: 16em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}'
        f'#{wrap_id} td.bd-cell-red, #{wrap_id} td.bd-cell-red * {{ color: hsl(348,100%,63%) !important; }} '
        f'#{wrap_id} td.bd-cell-green, #{wrap_id} td.bd-cell-green * {{ color: hsl(148,100%,63%) !important; }}'
        f'</style>',
        f'<table style="width:100%; border-collapse: collapse; background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR}; font-size: 13px;">',
        "<thead><tr>",
    ]
    header_cols = [c for c in df.columns if c != row_kind_column]
    for col in header_cols:
        col_esc = html_module.escape(str(col))
        parts.append(
            f'<th style="border: 1px solid rgba(255,255,255,0.3); padding: 6px 8px; background-color: {TABLE_BG_COLOR};">{col_esc}</th>'
        )
    parts.append("</tr></thead><tbody>")
    visible_cols = [c for c in df.columns if c != row_kind_column]
    for _, row in df.iterrows():
        row_kind = ""
        if row_kind_column and row_kind_column in df.columns:
            try:
                row_kind = str(row.get(row_kind_column, "")).strip().casefold()
            except Exception:
                row_kind = ""
        is_emphasized_row = row_kind in {str(x).strip().casefold() for x in emphasize_row_kinds}
        _efs = float(emphasize_row_font_em) if emphasize_row_font_em and emphasize_row_font_em > 1 else 1.12
        row_style = (
            " style=\"font-weight:700; "
            f"font-size:{_efs}em; border-top:1px solid rgba(255,255,255,0.35);\""
            if is_emphasized_row
            else ""
        )
        parts.append(f"<tr{row_style}>")
        for col in visible_cols:
            val = row[col]
            val_str = "" if (val is None or (isinstance(val, float) and pd.isna(val))) else str(val)
            val_esc = html_module.escape(val_str)
            if finance_deviation_column and col == finance_deviation_column:
                num = _parse_finance_value(val)
                if num is not None:
                    if (
                        deviation_abs_min_mln > 0
                        and abs(float(num)) < float(deviation_abs_min_mln)
                    ):
                        parts.append(
                            f'<td style="border: 1px solid rgba(255,255,255,0.2); padding: 6px 8px; '
                            f'background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR};">{val_esc}</td>'
                        )
                    elif deviation_red_if_negative:
                        cell_class = "bd-cell-red" if num < 0 else "bd-cell-green"
                        parts.append(
                            f'<td class="{cell_class}" style="padding: 6px 8px; font-weight: bold;"><span>{val_esc}</span></td>'
                        )
                    elif deviation_red_if_positive_only:
                        nf = float(num)
                        if deviation_semaphore_style:
                            bullet_color = (
                                "hsl(148,100%,63%)" if nf >= 0 else "hsl(348,100%,63%)"
                            )
                            text_color = (
                                "hsl(348,100%,63%)" if nf > 0 else "hsl(148,100%,63%)"
                            )
                            parts.append(
                                f'<td style="border: 1px solid rgba(255,255,255,0.2); padding: 6px 8px; '
                                f'background-color: {TABLE_BG_COLOR};">'
                                f'<span style="color:{bullet_color};font-weight:700;font-size:1.12em;margin-right:6px">●</span>'
                                f'<span style="color:{text_color}!important;font-weight:700">{val_esc}</span>'
                                f"</td>"
                            )
                        else:
                            cell_class = "bd-cell-red" if nf > 0 else "bd-cell-green"
                            parts.append(
                                f'<td class="{cell_class}" style="padding: 6px 8px; font-weight: bold;"><span>{val_esc}</span></td>'
                            )
                    else:
                        cell_class = "bd-cell-red" if num >= 0 else "bd-cell-green"
                        parts.append(
                            f'<td class="{cell_class}" style="padding: 6px 8px; font-weight: bold;"><span>{val_esc}</span></td>'
                        )
                else:
                    s = val_str.strip()
                    if not s:
                        parts.append(
                            f'<td style="border: 1px solid rgba(255,255,255,0.2); padding: 6px 8px; background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR};">{val_esc}</td>'
                        )
                    else:
                        num_fallback = _parse_finance_value(s)
                        if (
                            num_fallback is not None
                            and deviation_abs_min_mln > 0
                            and abs(float(num_fallback)) < float(deviation_abs_min_mln)
                        ):
                            parts.append(
                                f'<td style="border: 1px solid rgba(255,255,255,0.2); padding: 6px 8px; '
                                f'background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR};">{val_esc}</td>'
                            )
                        elif (
                            deviation_red_if_positive_only
                            and deviation_semaphore_style
                            and num_fallback is not None
                        ):
                            nf = float(num_fallback)
                            bullet_color = (
                                "hsl(148,100%,63%)" if nf >= 0 else "hsl(348,100%,63%)"
                            )
                            text_color = (
                                "hsl(348,100%,63%)" if nf > 0 else "hsl(148,100%,63%)"
                            )
                            parts.append(
                                f'<td style="border: 1px solid rgba(255,255,255,0.2); padding: 6px 8px; '
                                f'background-color: {TABLE_BG_COLOR};">'
                                f'<span style="color:{bullet_color};font-weight:700;font-size:1.12em;margin-right:6px">●</span>'
                                f'<span style="color:{text_color}!important;font-weight:700">{val_esc}</span>'
                                f"</td>"
                            )
                        else:
                            is_neg = s.startswith("-") or bool(re.search(r"^-\d", s))
                            if deviation_red_if_negative:
                                cell_class = "bd-cell-red" if is_neg else "bd-cell-green"
                            elif deviation_red_if_positive_only:
                                cell_class = "bd-cell-red" if not is_neg else "bd-cell-green"
                            else:
                                cell_class = "bd-cell-green" if is_neg else "bd-cell-red"
                            parts.append(
                                f'<td class="{cell_class}" style="padding: 6px 8px; font-weight: bold;"><span>{val_esc}</span></td>'
                            )
            else:
                parts.append(
                    f'<td style="padding: 6px 8px; color: {TABLE_TEXT_COLOR};">{val_esc}</td>'
                )
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def plan_fact_dates_table_to_html(
    df: pd.DataFrame,
    plan_date_column: str,
    fact_date_column: str,
) -> str:
    """
    Строит HTML таблицы «План и факт окончания ПД/РД» с раскраской только колонки «Факт»:
    факт > план — красный шрифт, факт <= план — зелёный шрифт.
    """
    if df is None or df.empty:
        return "<p>Нет данных для отображения.</p>"
    if plan_date_column not in df.columns or fact_date_column not in df.columns:
        return "<p>Нет колонок плана/факта дат.</p>"

    plan_series = df[plan_date_column]
    fact_series = df[fact_date_column]
    row_styles = []
    for i in range(len(df)):
        plan_val = _parse_date_cell(plan_series.iloc[i])
        fact_val = _parse_date_cell(fact_series.iloc[i])
        if plan_val is None or fact_val is None:
            row_styles.append(None)
        elif fact_val > plan_val:
            row_styles.append("red")
        else:
            row_styles.append("green")

    red_color = "#c0392b"
    green_color = "#27ae60"
    parts = [
        '<div style="overflow-x: auto; min-width: 0; margin: 1em 0;">',
        f'<table style="width:100%; border-collapse: collapse; background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR}; font-size: 13px;">',
        "<thead><tr>",
    ]
    for col in df.columns:
        col_esc = html_module.escape(str(col))
        parts.append(
            f'<th style="border: 1px solid rgba(255,255,255,0.3); padding: 6px 8px; max-width: 18em; overflow: hidden; '
            f'text-overflow: ellipsis; white-space: nowrap; background-color: {TABLE_BG_COLOR};">{col_esc}</th>'
        )
    parts.append("</tr></thead><tbody>")
    for i, (_, row) in enumerate(df.iterrows()):
        parts.append("<tr>")
        row_style = row_styles[i] if i < len(row_styles) else None
        for col in df.columns:
            val = row[col]
            val_str = "" if (val is None or (isinstance(val, float) and pd.isna(val))) else str(val)
            val_esc = html_module.escape(val_str)
            if col == fact_date_column and row_style:
                text_color = red_color if row_style == "red" else green_color
                parts.append(
                    f'<td style="border: 1px solid rgba(255,255,255,0.2); padding: 5px 8px; max-width: 16em; overflow: hidden; '
                    f'text-overflow: ellipsis; white-space: nowrap; background-color: {TABLE_BG_COLOR}; color: {text_color}; font-weight: bold;">{val_esc}</td>'
                )
            else:
                parts.append(
                    f'<td style="border: 1px solid rgba(255,255,255,0.2); padding: 5px 8px; max-width: 16em; overflow: hidden; '
                    f'text-overflow: ellipsis; white-space: nowrap; background-color: {TABLE_BG_COLOR}; color: {TABLE_TEXT_COLOR};">{val_esc}</td>'
                )
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def render_styled_table_to_html(styler, hide_index: bool = True) -> str:
    """
    Возвращает HTML строку стилизованной таблицы для вывода через st.markdown(..., unsafe_allow_html=True).
    """
    if styler is None or (hasattr(styler, "data") and styler.data.empty):
        return "<p>Нет данных для отображения.</p>"
    try:
        html = styler.to_html(index=not hide_index)
        return (
            '<div style="overflow-x:auto;min-width:0;margin:1em 0;-webkit-overflow-scrolling:touch;">'
            f"{html}</div>"
        )
    except Exception:
        return ""


def get_report_param_value(report_name: str, parameter_key: str, default: Any = None) -> Any:
    """Возвращает значение параметра отчёта из report_params."""
    try:
        from report_params import get_report_parameter
        param = get_report_parameter(report_name, parameter_key)
        if param and param.get("value") is not None:
            return param["value"]
    except ImportError:
        pass
    return default


def apply_default_filters(report_name: str, user_role: str, filter_widgets: dict) -> dict:
    """Применяет фильтры по умолчанию для отчёта и роли."""
    try:
        from filters import get_default_filters
        default_filters = get_default_filters(user_role, report_name)
        for filter_key, default_value in default_filters.items():
            if filter_key in filter_widgets and filter_widgets[filter_key] is None:
                filter_widgets[filter_key] = default_value
            elif filter_key not in filter_widgets:
                filter_widgets[filter_key] = default_value
    except ImportError:
        pass
    return filter_widgets


def _ru_column_is_integer_days(col) -> bool:
    """Колонки с длительностью/отклонением в днях или разделах — целые, без .00."""
    col_lower = str(col).lower()
    if col_lower.startswith("отклонение ") and any(
        w in col_lower for w in ("начала", "окончания", "длительности")
    ):
        return True
    if "дней" in col_lower or "в днях" in col_lower:
        return True
    if "днях" in col_lower and "отклон" in col_lower:
        return True
    if "отклонение разделов" in col_lower:
        return True
    if "число отклонений" in col_lower:
        return True
    return False


def format_dataframe_as_html(
    df: Optional[pd.DataFrame],
    conditional_cols: Optional[Dict[str, Dict[str, str]]] = None,
    column_colors: Optional[Dict[str, str]] = None,
    cell_color: Optional[pd.DataFrame] = None,
) -> str:
    """Форматирует DataFrame в HTML-таблицу для отображения в Streamlit."""
    if df is None or df.empty:
        return "<p>Нет данных для отображения.</p>"

    def _is_finance_like_column(col_name: Any) -> bool:
        s = str(col_name).lower()
        return any(
            token in s
            for token in (
                "млн",
                "руб",
                "бюджет",
                "budget",
                "%",
                "процент",
                "стоим",
                "сумм",
                "bdds",
                "бддс",
                "бдр",
            )
        )

    # §4.8: плотные ячейки — как `budget_table_to_html` / `style_dataframe_for_dark_theme`
    _th = (
        f"padding:6px 8px;background-color:rgba(18,56,92,0.95);color:{TABLE_TEXT_COLOR};"
        "font-size:13px;max-width:18em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
    )
    _td_base = (
        f"padding:5px 8px;border:1px solid rgba(255,255,255,0.15);background-color:{TABLE_BG_COLOR};"
        f"color:{TABLE_TEXT_COLOR};font-size:13px;max-width:16em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
    )
    html_table = (
        "<div class='bd-table-wrap' style='width:100%;overflow-x:auto;min-width:0;-webkit-overflow-scrolling:touch;'>"
        f"<table style='width:100%;min-width:max-content;border-collapse:collapse;background-color:{TABLE_BG_COLOR};"
        f"color:{TABLE_TEXT_COLOR};font-size:13px;'>"
    )
    html_table += "<thead><tr>"
    for col in df.columns:
        col_escaped = html_module.escape(ru_column_header(col))
        html_table += f"<th style='{_th}'>{col_escaped}</th>"
    html_table += "</tr></thead><tbody>"
    for idx, row in df.iterrows():
        html_table += "<tr>"
        for col in df.columns:
            value = row[col]
            is_scalar = pd.api.types.is_scalar(value)
            if conditional_cols and col in conditional_cols:
                cond_config = conditional_cols[col]
                pos_color = cond_config.get("positive_color", "#ff4444")
                neg_color = cond_config.get("negative_color", "#44ff44")
                col_lower = str(col).lower()
                if is_scalar and not (isinstance(value, (int, float)) and pd.isna(value)):
                    if isinstance(value, (int, float)):
                        color = pos_color if value > 0 else neg_color
                        if _ru_column_is_integer_days(col):
                            formatted_value = f"{int(round(float(value), 0))}"
                        elif isinstance(value, float):
                            formatted_value = f"{value:.2f}"
                        else:
                            formatted_value = f"{int(value)}"
                    else:
                        if _ru_column_is_integer_days(col):
                            try:
                                fv = float(str(value).replace(",", ".").replace(" ", ""))
                                formatted_value = f"{int(round(fv, 0))}"
                                color = pos_color if fv > 0 else neg_color
                            except (TypeError, ValueError):
                                formatted_value = str(value) if value != "" else "0"
                                color = neg_color
                        else:
                            formatted_value = str(value) if value != "" else "0"
                            color = neg_color
                else:
                    formatted_value = "0" if (is_scalar and pd.isna(value)) else str(value)
                    color = neg_color
                formatted_value = html_module.escape(str(formatted_value))
                html_table += (
                    f"<td style='{_td_base}color:{color};font-weight:bold;'>{formatted_value}</td>"
                )
            else:
                if isinstance(value, (int, float)) and is_scalar and not pd.isna(value):
                    col_lower = str(col).lower()
                    # Сначала «в днях» — иначе «отклонения» попадут под денежное .2f
                    if _ru_column_is_integer_days(col):
                        formatted_value = f"{int(round(float(value), 0))}"
                    elif _is_finance_like_column(col_lower):
                        formatted_value = f"{float(value):.2f}"
                    elif "отклонен" in col_lower or "deviation" in col_lower:
                        formatted_value = f"{int(round(float(value), 0))}"
                    elif isinstance(value, float) and (value % 1 != 0 or abs(value) < 1):
                        formatted_value = f"{value:.2f}"
                    else:
                        formatted_value = f"{int(value)}"
                elif _ru_column_is_integer_days(col) and is_scalar and value not in ("", None) and not (
                    isinstance(value, (int, float)) and pd.isna(value)
                ):
                    try:
                        fv = float(str(value).replace(",", ".").replace(" ", ""))
                        formatted_value = f"{int(round(fv, 0))}"
                    except (TypeError, ValueError):
                        formatted_value = "" if pd.isna(value) else str(value)
                else:
                    formatted_value = "" if (is_scalar and pd.isna(value)) else str(value)
                formatted_value = html_module.escape(str(formatted_value))
                cell_style = _td_base
                if column_colors and col in column_colors:
                    cell_style += f"color:{column_colors[col]};"
                if cell_color is not None and col in cell_color.columns:
                    try:
                        _cc = cell_color.at[idx, col]
                        if isinstance(_cc, str) and _cc.startswith("#"):
                            cell_style += f"color:{_cc};font-weight:600;"
                    except Exception:
                        pass
                html_table += f"<td style='{cell_style}'>{formatted_value}</td>"
        html_table += "</tr>"
    html_table += "</tbody></table></div>"
    return html_table

def load_custom_css() -> None:
    """Загружает CSS из static/css/style.css. Единственное место — импортируй отсюда."""
    from pathlib import Path
    css_path = Path(__file__).resolve().parent / "static" / "css" / "style.css"
    if css_path.exists():
        with open(css_path, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def dataframe_to_csv_bytes_for_excel(
    df: pd.DataFrame,
    *,
    sep: str = ";",
) -> bytes:
    """
    CSV для открытия в Microsoft Excel: UTF-8 с BOM и разделитель «;»
    (типичные региональные настройки RU — запятая как десятичный разделитель).
    """
    buf = io.BytesIO()
    df.to_csv(buf, index=False, sep=sep, encoding="utf-8-sig")
    return buf.getvalue()


def _excel_safe_sheet_name(name: str) -> str:
    """Имя листа Excel ≤31 символа, без символов []:*?/\\."""
    s = str(name or "Данные").strip() or "Данные"
    for ch in r"[]:*?/\ ":
        s = s.replace(ch, "_")
    s = "".join(c for c in s if ord(c) >= 32)[:31]
    return s or "Data"


def dataframe_to_xlsx_bytes(df: pd.DataFrame, *, sheet_name: str = "Данные") -> bytes:
    """Таблица в формате .xlsx (движок openpyxl из зависимостей проекта)."""
    buf = io.BytesIO()
    safe = _excel_safe_sheet_name(sheet_name)
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=safe)
    return buf.getvalue()


def _export_file_stem(name: str) -> str:
    """Имя файла без пути и без расширения .csv/.xlsx (для пары выгрузок)."""
    from pathlib import Path

    s = str(name or "export").strip()
    s = Path(s).name
    for suf in (".csv", ".xlsx", ".xls"):
        if s.lower().endswith(suf):
            s = s[: -len(suf)]
            break
    return s or "export"


def _download_button_compat(
    *,
    label: str,
    data: bytes,
    file_name: str,
    mime: str,
    key: str,
    help: Optional[str] = None,
    on_click=None,
) -> None:
    """st.download_button с опциональным on_click; без on_click на старых Streamlit."""
    kw: Dict[str, Any] = {
        "label": label,
        "data": data,
        "file_name": file_name,
        "mime": mime,
        "key": key,
    }
    if help is not None:
        kw["help"] = help
    if on_click is not None:
        try:
            st.download_button(**kw, on_click=on_click)
        except TypeError:
            st.download_button(**kw)
    else:
        st.download_button(**kw)


def render_dataframe_excel_csv_downloads(
    df: pd.DataFrame,
    *,
    file_stem: str,
    key_prefix: str,
    csv_label: str = "Скачать CSV (для Excel)",
    popover_label: str = "Скачать таблицу",
    on_csv_click=None,
    on_xlsx_click=None,
) -> None:
    """
    Одна кнопка-поповер «Скачать таблицу»: внутри — выбор формата (CSV для Excel или .xlsx).
    CSV: UTF-8 BOM и разделитель «;» (типичные региональные настройки RU).
    """
    if df is None or not hasattr(df, "columns"):
        return
    try:
        if df.empty:
            return
    except Exception:
        return
    stem = _export_file_stem(file_stem)
    csv_bytes = dataframe_to_csv_bytes_for_excel(df)
    xlsx_bytes = dataframe_to_xlsx_bytes(df, sheet_name="Данные")
    with st.popover(popover_label):
        _download_button_compat(
            label=csv_label,
            data=csv_bytes,
            file_name=f"{stem}.csv",
            mime="text/csv",
            key=f"{key_prefix}_csv",
            on_click=on_csv_click,
        )
        _download_button_compat(
            label="Скачать Excel (.xlsx)",
            data=xlsx_bytes,
            file_name=f"{stem}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}_xlsx",
            on_click=on_xlsx_click,
        )
