"""Замер времени рендера отчётов: где именно уходят секунды.

Назначение: одноразовая диагностика «долгой прогрузки». Оборачивает рендер
активного дашборда в ``cProfile`` и показывает топ функций по совокупному
времени (cumulative), плюс общий тайминг этапа. По результату решаем, что
кэшировать через ``st.cache_data``.

Включение (любой из вариантов):
  * переменная окружения ``BI_ANALYTICS_PROFILE=1``;
  * флаг сессии ``st.session_state["_bi_profile_render"] = True`` (для админа).

Результат:
  * пишется в stderr (видно в логах Streamlit Cloud);
  * показывается в раскрывающемся блоке в UI (для админа / dev-режима).

Накладные расходы при выключенном профайлере — нулевые (просто вызывается
функция рендера напрямую).
"""

from __future__ import annotations

import cProfile
import io
import os
import pstats
import time
from contextlib import contextmanager
from typing import Callable, List, Optional, Tuple

import streamlit as st


_TRUE = ("1", "true", "yes", "on")


def profiling_enabled() -> bool:
    if str(st.session_state.get("_bi_profile_render") or "").strip().lower() in _TRUE:
        return True
    # URL-переключатель ?profile=1 (без перезапуска): запоминаем в сессию.
    try:
        qp = st.query_params
        v = qp.get("profile", "")
        if isinstance(v, list):
            v = v[0] if v else ""
        if str(v).strip().lower() in _TRUE:
            st.session_state["_bi_profile_render"] = True
            return True
    except Exception:
        pass
    return os.environ.get("BI_ANALYTICS_PROFILE", "").strip().lower() in _TRUE


@contextmanager
def stage_timer(label: str):
    """Ручной замер именованного этапа: ``with stage_timer("сбор данных"): ...``.

    Длительности копятся в ``st.session_state["_bi_render_stages"]`` и выводятся
    рядом с профилем. Безвреден при выключенном профайлере (всё равно дёшево).
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        try:
            stages: List[Tuple[str, float]] = st.session_state.setdefault(
                "_bi_render_stages", []
            )
            stages.append((str(label), float(dt)))
        except Exception:
            pass


def _format_profile(pr: "cProfile.Profile", *, top: int = 25) -> str:
    buf = io.StringIO()
    try:
        stats = pstats.Stats(pr, stream=buf)
        stats.sort_stats("cumulative")
        stats.print_stats(top)
    except Exception as e:  # noqa: BLE001
        return f"(не удалось сформировать профиль: {e!r})"
    return buf.getvalue()


def profiled_render(
    render_fn: Callable[..., None],
    *args,
    report_name: str = "",
    **kwargs,
) -> None:
    """Вызвать ``render_fn(*args, **kwargs)``; при включённом профайлере — замерить.

    При выключенном профайлере — прямой вызов без накладных расходов.
    """
    if not profiling_enabled():
        render_fn(*args, **kwargs)
        return

    st.session_state["_bi_render_stages"] = []
    pr = cProfile.Profile()
    t0 = time.perf_counter()
    pr.enable()
    try:
        render_fn(*args, **kwargs)
    finally:
        pr.disable()
        total = time.perf_counter() - t0

    report = _format_profile(pr, top=30)
    stages: List[Tuple[str, float]] = st.session_state.get("_bi_render_stages", []) or []

    header = f"[profile] report={report_name!r} total={total:.3f}s"
    try:
        from auto_ingest import safe_stderr_log

        safe_stderr_log(header)
        for lbl, dt in stages:
            safe_stderr_log(f"[profile]   stage {lbl}: {dt:.3f}s")
        for line in report.splitlines()[:35]:
            safe_stderr_log(f"[profile] {line}")
    except Exception:
        pass

    try:
        with st.expander(f"⏱ Профиль рендера: {total:.2f}s", expanded=False):
            st.caption(
                "Диагностика времени рендера (BI_ANALYTICS_PROFILE). "
                "Смотрите столбец cumtime — функции с наибольшим совокупным временем."
            )
            if stages:
                st.markdown("**Этапы (ручные замеры):**")
                for lbl, dt in sorted(stages, key=lambda x: x[1], reverse=True):
                    st.markdown(f"- `{dt:6.3f}s` — {lbl}")
            st.code(report, language="text")
    except Exception:
        pass
