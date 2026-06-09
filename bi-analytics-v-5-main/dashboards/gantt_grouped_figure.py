"""Построение grouped Gantt (план/факт) и кэш fig для «Графика проекта»."""
from __future__ import annotations

import json
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def gantt_resolve_date_label_mode(n_rows: int) -> str:
    """Режим подписей дат по числу строк: full → end_only → hover_only.

    Плавная деградация защищает от тормозов на больших выборках (полные подписи
    для каждой полосы строятся как отдельные точки текста — это дорого).
    """
    from dashboards._renderers import (
        _GANTT_DATE_LABELS_END_ONLY_ROWS,
        _GANTT_DATE_LABELS_FULL_ROWS,
    )

    if n_rows <= _GANTT_DATE_LABELS_FULL_ROWS:
        return "full"
    if n_rows <= _GANTT_DATE_LABELS_END_ONLY_ROWS:
        return "end_only"
    return "hover_only"


def _msp_pick_col(d: pd.DataFrame, candidates: tuple[str, ...]) -> Optional[str]:
    cols_lower = {str(c).strip().lower(): c for c in d.columns}
    for name in candidates:
        n = str(name).strip().lower()
        if n in cols_lower:
            return cols_lower[n]
    return None


def _find_fact_end_column(d: pd.DataFrame) -> Optional[str]:
    if d is None or getattr(d, "empty", True):
        return None
    hit = _msp_pick_col(
        d,
        (
            "actual finish",
            "Actual Finish",
            "actual end",
            "Actual End",
            "fact end",
            "Fact End",
            "факт окончание",
            "Факт окончание",
            "факт: окончание",
        ),
    )
    if hit:
        return hit
    for c in d.columns:
        sl = str(c).strip().lower().replace("_", " ")
        if ("actual" in sl or "факт" in sl) and any(
            x in sl for x in ("finish", "end", "оконч")
        ):
            return c
    return None


def _find_fact_start_column(d: pd.DataFrame) -> Optional[str]:
    if d is None or getattr(d, "empty", True):
        return None
    hit = _msp_pick_col(
        d,
        (
            "actual start",
            "Actual Start",
            "fact start",
            "Fact Start",
            "факт начало",
            "Факт начало",
            "факт: начало",
        ),
    )
    if hit:
        return hit
    for c in d.columns:
        sl = str(c).strip().lower().replace("_", " ")
        if ("actual" in sl or "факт" in sl) and any(
            x in sl for x in ("start", "begin", "начал")
        ):
            return c
    return None


def _gantt_ru_date_ticks(lo, hi, max_ticks: int = 26):
    from dashboards._renderers import _CHART_PLOT_DATE_FMT

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
    ticktext = [pd.Timestamp(ts).strftime(_CHART_PLOT_DATE_FMT) for ts in rng]
    return list(rng), ticktext


def build_grouped_plan_fact_gantt_figure(
    d: pd.DataFrame,
    policy: dict,
    *,
    label_pct: bool,
    pct_values: list,
    date_fmt: str,
    show_covenant_markers: bool = False,
    row_block_scale: float = 2.0,
) -> go.Figure:
    from dashboards._renderers import (
        _CHART_PLOT_DATE_FMT,
        _GANTT_MIN_LABEL_FONT,
        _GANTT_SCHEDULE_BAR_WIDTH,
        _GANTT_SCHEDULE_BARGROUPGAP,
        _gantt_grouped_bar_lane_offset,
        _project_schedule_gantt_apply_y_labels,
        _project_schedule_gantt_chart_height,
        _project_schedule_gantt_x_range,
    )
    from dashboards.ui_quiet import suppress_caption
    from utils import apply_chart_background

    local = d.copy()
    # Даты в данных — ISO (YYYY-MM-DD). dayfirst=True ломал их (менял местами
    # месяц/день: «2025-04-02» → 2025-02-04), из-за чего интервалы инвертировались
    # или обнулялись и полосы становились невидимыми (пустота). Парсим как остальное
    # приложение — без dayfirst.
    for _dc in ("plan start", "plan end", "base start", "base end"):
        if _dc in local.columns:
            local[_dc] = pd.to_datetime(local[_dc], errors="coerce")

    fact_end_col = _find_fact_end_column(local)
    fact_start_col = _find_fact_start_column(local)
    if fact_end_col and fact_end_col in local.columns:
        local[fact_end_col] = pd.to_datetime(local[fact_end_col], errors="coerce")
    if fact_start_col and fact_start_col in local.columns:
        local[fact_start_col] = pd.to_datetime(local[fact_start_col], errors="coerce")

    def _epoch_ms(ts) -> Optional[float]:
        if ts is None or (isinstance(ts, float) and pd.isna(ts)):
            return None
        t = pd.Timestamp(ts)
        if pd.isna(t):
            return None
        return float(t.timestamp() * 1000.0)

    def _fmt_bar_date(ts) -> str:
        if ts is None or (isinstance(ts, float) and pd.isna(ts)):
            return ""
        try:
            tt = pd.Timestamp(ts)
            if pd.isna(tt):
                return ""
            return tt.strftime(date_fmt)
        except Exception:
            return ""

    def _resolve_fact_interval(row):
        bs = row.get("base start")
        be = row.get("base end")
        fs = row.get(fact_start_col) if fact_start_col else None
        fe = row.get(fact_end_col) if fact_end_col else None
        start = bs if pd.notna(bs) else fs
        end = be if pd.notna(be) else fe
        ps = row.get("plan start")
        if pd.notna(end) and pd.isna(start) and pd.notna(ps):
            start = ps
        if pd.notna(start) and pd.notna(end):
            try:
                if pd.Timestamp(end) < pd.Timestamp(start):
                    return (None, None)
            except Exception:
                return (None, None)
            return (pd.Timestamp(start), pd.Timestamp(end))
        return (None, None)

    y_labels: list[str] = []
    plan_len_ms: list[float] = []
    plan_base_ms: list[float] = []
    fact_len_ms: list[float] = []
    fact_base_ms: list[float] = []
    cust_plan: list[tuple[str, str]] = []
    cust_fact: list[tuple[str, str]] = []
    base_end_x: list = []
    base_end_y_idx: list[int] = []
    _row_meta: list[dict] = []
    _seen_y: dict[str, int] = {}
    _n_fact_ok = 0
    _use_baseline_as_plan = not label_pct

    for i, (_, row) in enumerate(local.iterrows()):
        cs = row.get("plan start")
        ce = row.get("plan end")
        if pd.isna(cs) or pd.isna(ce):
            continue

        if _use_baseline_as_plan:
            plan_s = row.get("base start")
            plan_e = row.get("base end")
        else:
            plan_s, plan_e = cs, ce
        p0 = _epoch_ms(plan_s)
        p1 = _epoch_ms(plan_e)
        # «Видимая» полоса — только с положительной длительностью. Нулевая длина
        # (старт = окончание) рисуется невидимой полосой и даёт две наложенные
        # одинаковые подписи дат — такие интервалы не считаем видимыми.
        plan_ok = p0 is not None and p1 is not None and p1 > p0

        if _use_baseline_as_plan:
            fs, fe = (cs, ce)
        else:
            fs, fe = _resolve_fact_interval(row)
        f0 = _epoch_ms(fs)
        f1 = _epoch_ms(fe)
        fact_ok = f0 is not None and f1 is not None and f1 > f0

        # Строка без единой видимой полосы (нет дат / нулевая длительность) только
        # занимает место по оси Y (пустота сверху графика) и показывает дубль
        # одинаковых дат — пропускаем её целиком. В режиме «Показать %» рисуется
        # только полоса плана, поэтому там нужна видимая плановая полоса.
        if label_pct:
            if not plan_ok:
                continue
        elif not plan_ok and not fact_ok:
            continue

        y = str(row["_gantt_y_label"])
        if y in _seen_y:
            _seen_y[y] += 1
            y = f"{y} #{_seen_y[y]}"
        else:
            _seen_y[y] = 1
        y_labels.append(y)

        if plan_ok:
            plan_base_ms.append(float(p0))
            plan_len_ms.append(float(p1 - p0))
            cust_plan.append((_fmt_bar_date(plan_s), _fmt_bar_date(plan_e)))
        else:
            plan_base_ms.append(0.0)
            plan_len_ms.append(0.0)
            cust_plan.append(("—", "—"))

        if fact_ok:
            fact_base_ms.append(float(f0))
            fact_len_ms.append(float(f1 - f0))
            cust_fact.append((_fmt_bar_date(fs), _fmt_bar_date(fe)))
            _n_fact_ok += 1
        else:
            fact_base_ms.append(0.0)
            fact_len_ms.append(0.0)
            cust_fact.append(("—", "—"))
        ps, pe = plan_s, plan_e

        if show_covenant_markers:
            be = row.get("base end")
            if pd.notna(be):
                base_end_x.append(pd.Timestamp(be))
                base_end_y_idx.append(len(y_labels) - 1)

        pv = pct_values[i] if i < len(pct_values) else np.nan
        _row_meta.append(
            {
                "y": y,
                "y_idx": len(y_labels) - 1,
                "ps": pd.Timestamp(ps) if pd.notna(ps) else None,
                "pe": pd.Timestamp(pe) if pd.notna(pe) else None,
                "fs": fs,
                "fe": fe,
                "pct": pv,
                "plan_ok": plan_ok,
                "fact_ok": fact_ok,
            }
        )

    fig = go.Figure()
    if not y_labels:
        return fig

    _lbl_font = max(_GANTT_MIN_LABEL_FONT, int(policy.get("label_font", 13)))
    _date_text: dict[tuple[str, str], dict[str, list]] = {
        ("plan", "start"): {"x": [], "y": [], "text": []},
        ("plan", "end"): {"x": [], "y": [], "text": []},
        ("fact", "start"): {"x": [], "y": [], "text": []},
        ("fact", "end"): {"x": [], "y": [], "text": []},
    }
    _GANTT_PLAN_COLOR = "#14b8a6"
    _GANTT_FACT_COLOR = "#fb923c"
    _chart_has_fact_trace = not label_pct and _n_fact_ok > 0

    def _lane_y_pos(y_idx: int, lane: str) -> float:
        return float(y_idx) + _gantt_grouped_bar_lane_offset(
            lane,
            has_fact_trace=_chart_has_fact_trace,
        )

    def _add_bar_edge_date_label(
        x_edge: pd.Timestamp,
        y_idx: int,
        text: str,
        *,
        lane: str,
        edge: str,
    ) -> None:
        if not text or x_edge is None:
            return
        _bucket = _date_text.get((lane, edge))
        if _bucket is None:
            return
        _bucket["x"].append(pd.Timestamp(x_edge))
        _bucket["y"].append(_lane_y_pos(y_idx, lane))
        _bucket["text"].append(text)

    def _flush_date_text_traces() -> None:
        # Даты — СНАРУЖИ полос, как на «Ковенантах»: начало слева от левого края,
        # окончание справа от правого края (не внутри полосы).
        _pos = {"start": "middle left", "end": "middle right"}
        # Зазор от края полосы до подписи — 4 неразрывных пробела (как в «Ковенантах»):
        # scatter-текст не поддерживает пиксельный сдвиг, поэтому добиваем пробелами
        # со стороны полосы.
        _gap = "\u00a0\u00a0\u00a0\u00a0"
        for (lane, edge), data in _date_text.items():
            if not data["x"]:
                continue
            _color = _GANTT_FACT_COLOR if lane == "fact" else _GANTT_PLAN_COLOR
            if edge == "end":
                _txt = [_gap + str(t) for t in data["text"]]
            else:
                _txt = [str(t) + _gap for t in data["text"]]
            fig.add_trace(
                go.Scatter(
                    x=data["x"],
                    y=data["y"],
                    mode="text",
                    text=_txt,
                    textposition=_pos[edge],
                    textfont=dict(size=_lbl_font, color=_color, family="Arial"),
                    hoverinfo="skip",
                    showlegend=False,
                    cliponaxis=False,
                )
            )

    if label_pct:
        _plan_trace_text: list[str] = []
        for meta in _row_meta:
            txt = "н/д"
            if pd.notna(meta.get("pct")):
                try:
                    txt = f"{int(round(float(meta['pct'])))}%"
                except (TypeError, ValueError):
                    pass
            _plan_trace_text.append(txt)
    else:
        _plan_trace_text = [""] * len(y_labels)

    _plan_y = [_lane_y_pos(i, "plan") for i in range(len(y_labels))]
    _fact_y = [_lane_y_pos(i, "fact") for i in range(len(y_labels))]
    fig.add_trace(
        go.Bar(
            name="План",
            orientation="h",
            x=plan_len_ms,
            y=_plan_y,
            base=plan_base_ms,
            width=_GANTT_SCHEDULE_BAR_WIDTH,
            marker=dict(color=_GANTT_PLAN_COLOR),
            text=_plan_trace_text,
            textposition="none",
            textfont=dict(size=_lbl_font, color=_GANTT_PLAN_COLOR),
            showlegend=False,
            cliponaxis=False,
            hovertemplate="%{customdata[2]}<br>План: %{customdata[0]} — %{customdata[1]}<extra></extra>",
            customdata=[(*row, y_labels[i]) for i, row in enumerate(cust_plan)],
        )
    )
    if not label_pct and _n_fact_ok > 0:
        fig.add_trace(
            go.Bar(
                name="Факт",
                orientation="h",
                x=fact_len_ms,
                y=_fact_y,
                base=fact_base_ms,
                width=_GANTT_SCHEDULE_BAR_WIDTH,
                marker=dict(color=_GANTT_FACT_COLOR),
                text=[""] * len(y_labels),
                textposition="none",
                textfont=dict(size=_lbl_font, color=_GANTT_FACT_COLOR),
                showlegend=False,
                cliponaxis=False,
                hovertemplate="%{customdata[2]}<br>Факт: %{customdata[0]} — %{customdata[1]}<extra></extra>",
                customdata=[(*row, y_labels[i]) for i, row in enumerate(cust_fact)],
            )
        )
    elif not label_pct:
        suppress_caption(
            "Полоса «Факт» не построена: в выборке нет пар дат "
            "«Старт факт / Конец факт» (base start / base end) или actual start / actual finish."
        )
    fig.update_layout(barmode="group")

    if label_pct:
        for meta in _row_meta:
            pe = meta.get("pe")
            if pe is None or not meta.get("plan_ok"):
                continue
            pv = meta.get("pct")
            _ptxt = "н/д"
            if pd.notna(pv):
                try:
                    _ptxt = f"{int(round(float(pv)))}%"
                except (TypeError, ValueError):
                    _ptxt = "н/д"
            _add_bar_edge_date_label(
                pe,
                int(meta["y_idx"]),
                _ptxt,
                lane="plan",
                edge="end",
            )

    def _same_day(a, b) -> bool:
        # Полное совпадение дат план/факт по дню: дубль подписи не нужен.
        if a is None or b is None:
            return False
        try:
            ta, tb = pd.Timestamp(a), pd.Timestamp(b)
            if pd.isna(ta) or pd.isna(tb):
                return False
            return ta.normalize() == tb.normalize()
        except Exception:
            return False

    _date_mode = str(policy.get("date_label_mode") or "full")
    if not label_pct and _date_mode in ("full", "end_only"):
        for meta in _row_meta:
            y_idx = int(meta["y_idx"])
            ps, pe = meta["ps"], meta["pe"]
            fs, fe = meta["fs"], meta["fe"]
            _plan_ok = bool(meta.get("plan_ok"))
            _fact_ok = bool(meta.get("fact_ok"))
            if _date_mode == "full":
                if _plan_ok and ps is not None and pe is not None:
                    _add_bar_edge_date_label(
                        ps, y_idx, _fmt_bar_date(ps), lane="plan", edge="start"
                    )
                    _add_bar_edge_date_label(
                        pe, y_idx, _fmt_bar_date(pe), lane="plan", edge="end"
                    )
                if _fact_ok and fs is not None and fe is not None:
                    # Если дата факта совпадает с планом по дню — не дублируем подпись
                    # (иначе бирюзовая и оранжевая печатаются стопкой). Рисуем факт
                    # только когда есть расхождение и план-подпись не показана.
                    if not (_plan_ok and _same_day(fs, ps)):
                        _add_bar_edge_date_label(
                            fs, y_idx, _fmt_bar_date(fs), lane="fact", edge="start"
                        )
                    if not (_plan_ok and _same_day(fe, pe)):
                        _add_bar_edge_date_label(
                            fe, y_idx, _fmt_bar_date(fe), lane="fact", edge="end"
                        )
            else:
                if _plan_ok and pe is not None:
                    _add_bar_edge_date_label(
                        pe, y_idx, _fmt_bar_date(pe), lane="plan", edge="end"
                    )
                if _fact_ok and fe is not None and not (_plan_ok and _same_day(fe, pe)):
                    _add_bar_edge_date_label(
                        fe, y_idx, _fmt_bar_date(fe), lane="fact", edge="end"
                    )

    _flush_date_text_traces()

    if show_covenant_markers and base_end_x:
        fig.add_trace(
            go.Scatter(
                x=base_end_x,
                y=base_end_y_idx,
                mode="markers",
                name="Базовое окончание (ковенанта)",
                marker=dict(
                    symbol="diamond",
                    size=int(policy.get("marker_size", 10)) + 2,
                    color="#C084FC",
                    line=dict(color="rgba(255,255,255,0.75)", width=1),
                ),
                hovertemplate="%{y}<br>Базовое окончание: %{x|"
                + _CHART_PLOT_DATE_FMT
                + "}<extra></extra>",
                showlegend=False,
            )
        )

    n_rows = len(y_labels)
    chart_h = _project_schedule_gantt_chart_height(
        n_rows,
        dense=bool(policy.get("is_dense")),
        row_block_scale=row_block_scale,
        y_labels=y_labels,
        task_font=int(policy.get("task_font", 11)),
    )
    left_m, _x_domain_start, _y_name_ann = _project_schedule_gantt_apply_y_labels(
        fig,
        y_labels,
        dense=bool(policy.get("is_dense")),
        task_font=int(policy.get("task_font", 11)),
        numeric_row_y=True,
    )
    _right_m = 48
    fig.update_layout(
        autosize=True,
        width=None,
        height=chart_h,
        xaxis_title=dict(text="Период", standoff=22),
        yaxis_title=None,
        margin=dict(l=left_m, r=_right_m, t=36, b=112),
        showlegend=False,
        bargap=0.78,
        bargroupgap=_GANTT_SCHEDULE_BARGROUPGAP,
        uirevision="gantt_project_schedule_bars",
        hovermode="closest",
        dragmode=False,
    )
    if _y_name_ann:
        fig.update_layout(annotations=list(_y_name_ann))
    fig.update_xaxes(
        type="date",
        tickformat=_CHART_PLOT_DATE_FMT,
        automargin=True,
        domain=[_x_domain_start, 1.0],
        fixedrange=True,
    )
    fig.update_yaxes(fixedrange=True)

    try:
        _bar_dates: list = []
        _bar_starts: list = []
        _label_left_x: list = []
        _label_right_x: list = []
        for _meta in _row_meta:
            for _dk in ("ps", "pe", "fs", "fe"):
                _dv = _meta.get(_dk)
                if _dv is not None:
                    _bar_dates.append(_dv)
            for _sk in ("ps", "fs"):
                _sv = _meta.get(_sk)
                if _sv is not None:
                    _bar_starts.append(_sv)
            if _date_mode == "full":
                for _lk, _side in (("ps", "left"), ("pe", "right"), ("fs", "left"), ("fe", "right")):
                    _lv = _meta.get(_lk)
                    if _lv is not None:
                        (_label_left_x if _side == "left" else _label_right_x).append(_lv)
            elif _date_mode == "end_only":
                for _lk in ("pe", "fe"):
                    _lv = _meta.get(_lk)
                    if _lv is not None:
                        _label_right_x.append(_lv)
        _bar_dates.extend(base_end_x)
        lo_pad, hi_pad = _project_schedule_gantt_x_range(
            _bar_dates,
            bar_starts=_bar_starts,
            label_left_x=_label_left_x or None,
            label_right_x=_label_right_x or None,
        )
        if lo_pad is not None and hi_pad is not None:
            # Небольшой запас по краям под подписи дат (начало — слева, окончание —
            # справа). Раньше брали 12% диапазона: на многолетней выборке это давало
            # широкую пустую полосу до первых полос. Теперь запас пропорционален
            # диапазону, но с жёстким верхним ограничением, чтобы пустоты не было.
            _span_days = max(1.0, (pd.Timestamp(hi_pad) - pd.Timestamp(lo_pad)).days)
            _extra = pd.Timedelta(days=min(45.0, max(10.0, _span_days * 0.05)))
            lo_pad = pd.Timestamp(lo_pad) - _extra
            hi_pad = pd.Timestamp(hi_pad) + _extra
            fig.update_xaxes(range=[lo_pad, hi_pad], autorange=False, fixedrange=True)
            tvals, ttext = _gantt_ru_date_ticks(
                lo_pad,
                hi_pad,
                max_ticks=int(policy.get("max_ticks", 22)),
            )
            if tvals and ttext and len(tvals) == len(ttext):
                fig.update_xaxes(
                    tickmode="array",
                    tickvals=[pd.Timestamp(t).strftime("%Y-%m-%d") for t in tvals],
                    ticktext=ttext,
                    tickangle=-25,
                    tickformat="",
                )
    except Exception:
        pass

    try:
        _today_ts = pd.Timestamp.today().normalize()
        fig.add_vline(
            x=_today_ts,
            line_dash="dot",
            line_color="rgba(255,255,255,0.45)",
            line_width=1.2,
            annotation_text="Сегодня",
            annotation_position="top",
            annotation_font_color="rgba(255,255,255,0.75)",
            annotation_font_size=10,
        )
    except Exception:
        pass

    fig = apply_chart_background(fig, skip_uniformtext=True)
    fig.update_xaxes(domain=[_x_domain_start, 1.0])
    return fig


@st.cache_data(show_spinner=False, ttl=300)
def cached_grouped_gantt_figure(
    plot_df: pd.DataFrame,
    policy_json: str,
    label_pct: bool,
    pct_values: tuple,
    date_fmt: str,
    show_covenant_markers: bool,
    row_block_scale: float,
    _fig_cache_version: int = 18,
) -> go.Figure:
    """Кэш построения fig — ускоряет rerun при тех же фильтрах."""
    policy = json.loads(policy_json)
    return build_grouped_plan_fact_gantt_figure(
        plot_df,
        policy,
        label_pct=label_pct,
        pct_values=list(pct_values),
        date_fmt=date_fmt,
        show_covenant_markers=show_covenant_markers,
        row_block_scale=row_block_scale,
    )
