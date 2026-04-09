"""
Обёртка для автоматического экспорта CSV/PNG после любого дашборда.
Перехватывает render_chart и st.plotly_chart на время вызова функции отрисовки.
"""
from __future__ import annotations

import re
from typing import Any, Callable, List, Optional

import pandas as pd
import streamlit as st


def slug_report_name(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")
    return (s or "report")[:80]


def run_dashboard_with_auto_export(
    render_fn: Callable,
    export_slug: str,
    df: Any,
    *args,
    **kwargs,
) -> Any:
    from dashboards import _renderers as mod

    last_figs: List[Any] = []
    orig_rc = mod.render_chart
    orig_pc = st.plotly_chart

    def cap_rc(fig, *a, **kw):
        last_figs.clear()
        last_figs.append(fig)
        return orig_rc(fig, *a, **kw)

    def cap_pc(fig, *a, **kw):
        last_figs.clear()
        last_figs.append(fig)
        return orig_pc(fig, *a, **kw)

    mod.render_chart = cap_rc
    st.plotly_chart = cap_pc
    try:
        return render_fn(df, *args, **kwargs)
    finally:
        mod.render_chart = orig_rc
        st.plotly_chart = orig_pc
        fig = last_figs[0] if last_figs else None
        safe_df = None
        if isinstance(df, pd.DataFrame) and df is not None and not df.empty:
            safe_df = df
        key_px = slug_report_name(export_slug)[:40]
        mod.render_export_buttons(
            df=safe_df,
            fig=fig,
            csv_filename=f"{key_px}.csv",
            png_filename=f"{key_px}.png",
            key_prefix=key_px,
        )
