"""
Production UI: скрытие «серых» служебных подписей Streamlit (`st.caption`) в дашбордах;
единый контейнер/стили блока фильтров (раньше вынесены в filter_layout — см. совместимость).

См. `mapping_spec_v2` — раздел про отсутствие дебаг/сервисных подсказок в UI.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator


def suppress_caption(*_args, **_kwargs) -> None:
    """No-op вместо `st.caption` — не рендерить мелкий серый текст под виджетами."""
    return None


# --- Единый блок фильтров (сетка, рамка) — используется дашбордами -----------------

_SESSION_CSS_FLAG_KEY = "_bi_unified_filters_css_v1"

UNIFIED_FILTERS_CSS = """
<style>
/* Колонки внутри только «рамочных» блоков фильтров — без влияния на графики вне контейнера */
section.main div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    flex: 1 1 0% !important;
    min-width: 0 !important;
}
</style>
"""


def inject_unified_filters_css(st: Any) -> None:
    """Подключить общие стили сетки фильтров (идемпотентно по session_state)."""
    if not hasattr(st, "session_state"):
        return
    if st.session_state.get(_SESSION_CSS_FLAG_KEY):
        return
    st.markdown(UNIFIED_FILTERS_CSS, unsafe_allow_html=True)
    st.session_state[_SESSION_CSS_FLAG_KEY] = True


@contextmanager
def filters_panel(st: Any, title: str = "Фильтры") -> Generator[None, None, None]:
    """
    Общий паттерн: подзаголовок «Фильтры» и ``st.container(border=True)`` для строк selectbox/date_input и т.п.
    """
    inject_unified_filters_css(st)
    st.subheader(title)
    with st.container(border=True):
        yield


# --- Универсальный QA debug-блок (виден на dev/локалке, скрыт в release) ---------

def _is_release_mode() -> bool:
    """True, если запущен release-режим — debug-блоки должны быть скрыты."""
    try:
        from config import is_release_client_mode
        return bool(is_release_client_mode())
    except Exception:
        import os
        for key in ("BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS", "BI_ANALYTICS_RELEASE_MODE"):
            if str(os.environ.get(key, "")).strip().lower() in ("1", "true", "yes", "on"):
                return True
        return False


@contextmanager
def qa_debug_block(
    st: Any,
    title: str = "🔬 Сверка данных с эталоном (debug)",
    expanded: bool = False,
) -> Generator[bool, None, None]:
    """
    Контекст-менеджер для отладочного блока QA на дашборде.

    - На localhost / dev (ветка main) — рендерит ``st.expander(title)``.
    - На release (ветка release / env BI_ANALYTICS_HIDE_DEV_DIAGNOSTICS=1) —
      ничего не рендерит, тело блока не выполняется (yield False).

    Использование:

        with qa_debug_block(st) as on:
            if on:
                st.dataframe(...)
                st.markdown("...")
    """
    if _is_release_mode():
        # Yield False, чтобы пользовательский код пропустил содержимое
        yield False
        return
    with st.expander(title, expanded=expanded):
        yield True
