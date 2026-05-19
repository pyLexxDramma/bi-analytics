"""
Production UI: скрытие «серых» служебных подписей Streamlit (`st.caption`) в дашбордах;
единый блок фильтров (popover, сетка фиксированной ширины, чипы активных значений).

См. `mapping_spec_v2` — раздел про отсутствие дебаг/сервисных подсказок в UI.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from html import escape as html_escape
from typing import Any, Generator, List, Optional, Sequence, Tuple

Chip = Tuple[str, str]


def suppress_caption(*_args, **_kwargs) -> None:
    """No-op вместо `st.caption` — не рендерить мелкий серый текст под виджетами."""
    return None


# --- Единый блок фильтров ---------------------------------------------------------

_SESSION_CSS_FLAG_KEY = "_bi_unified_filters_css_v2"
_DEFAULT_FIELD_MIN_PX = 260

UNIFIED_FILTERS_CSS = """
<style>
/* Сетка в popover / expander: равные колонки, без «разъезда» по ширине */
section.main [data-testid="stPopoverBody"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
section.main [data-testid="stExpander"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
section.main div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
section.main .bi-filters-scope div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    flex: 1 1 0% !important;
    min-width: """ + str(_DEFAULT_FIELD_MIN_PX) + """px !important;
    max-width: 320px !important;
}
section.main [data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] > label,
section.main .bi-filters-scope [data-testid="stVerticalBlock"] > label {
    font-size: 13px !important;
    font-weight: 600 !important;
}
.bi-filter-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 8px;
    align-items: center;
    min-height: 2rem;
    padding: 2px 0 4px 0;
}
.bi-filter-chip {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.35;
    color: #e8eef5;
    background: rgba(30, 58, 92, 0.95);
    border: 1px solid rgba(121, 154, 192, 0.45);
    white-space: nowrap;
}
.bi-filter-chip b {
    color: #86efac;
    font-weight: 700;
}
.bi-filters-section-title {
    font-size: 12px;
    font-weight: 700;
    color: #86efac;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin: 8px 0 6px 0;
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


def _reset_button_key(keys: Sequence[str]) -> str:
    raw = "|".join(sorted(str(k) for k in keys))
    return "bi_filters_reset_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def reset_filter_widgets(st: Any, keys: Sequence[str]) -> None:
    """Сбросить значения виджетов по ключам session_state."""
    if not hasattr(st, "session_state"):
        return
    for k in keys:
        st.session_state.pop(str(k), None)


def render_filter_chips(st: Any, chips: Optional[Sequence[Chip]]) -> None:
    """Строка чипов «Поле: значение» (пустой список — ничего не рисуем)."""
    if not chips:
        return
    parts: List[str] = []
    for label, value in chips:
        lab = html_escape(str(label or "").strip())
        val = html_escape(str(value or "").strip())
        if not lab or not val:
            continue
        parts.append(f'<span class="bi-filter-chip"><b>{lab}:</b> {val}</span>')
    if not parts:
        return
    inject_unified_filters_css(st)
    st.markdown(
        '<div class="bi-filter-chips">' + "".join(parts) + "</div>",
        unsafe_allow_html=True,
    )


def filters_section_title(st: Any, title: str) -> None:
    """Подзаголовок секции внутри popover (Иерархия / Отображение / …)."""
    inject_unified_filters_css(st)
    st.markdown(
        f'<p class="bi-filters-section-title">{html_escape(str(title or "").strip())}</p>',
        unsafe_allow_html=True,
    )


@contextmanager
def filters_grid(st: Any, columns: int = 3) -> Generator[List[Any], None, None]:
    """N колонок одинаковой ширины для selectbox/checkbox внутри popover."""
    inject_unified_filters_css(st)
    n = max(1, int(columns))
    yield st.columns(n)


class _FiltersPopoverHandle:
    """Ручка для отрисовки чипов после виджетов внутри popover."""

    def __init__(self, st: Any, chip_column: Any) -> None:
        self._st = st
        self._chip_column = chip_column

    def set_chips(self, chips: Optional[Sequence[Chip]]) -> None:
        with self._chip_column:
            render_filter_chips(self._st, chips)


@contextmanager
def filters_popover(
    st: Any,
    label: str = "Фильтры",
    *,
    active_count: int = 0,
    reset_keys: Optional[Sequence[str]] = None,
) -> Generator[_FiltersPopoverHandle, None, None]:
    """
    Верхняя панель отчёта: чипы сверху, фильтры в свёрнутом expander, «Сбросить» внутри.
    Тело фильтров — внутри ``with filters_popover(...) as fp:`` … ``fp.set_chips([...])``.
    """
    inject_unified_filters_css(st)
    pop_label = str(label or "Фильтры").strip() or "Фильтры"
    if active_count > 0:
        pop_label = f"{pop_label} ({int(active_count)})"
    chip_slot = st.empty()
    handle = _FiltersPopoverHandle(st, chip_slot)
    with st.expander(pop_label, expanded=False):
        if reset_keys:
            _rb_col, _ = st.columns([1, 4])
            with _rb_col:
                if st.button(
                    "Сбросить",
                    key=_reset_button_key(reset_keys),
                    help="Сбросить фильтры этого отчёта к значениям по умолчанию",
                ):
                    reset_filter_widgets(st, reset_keys)
                    st.rerun()
        yield handle


@contextmanager
def filters_panel(
    st: Any,
    title: str = "Фильтры",
    *,
    reset_keys: Optional[Sequence[str]] = None,
) -> Generator[None, None, None]:
    """
    Совместимость: виджеты в ``filters_popover`` (без чипов).
    Новые отчёты с чипами — ``filters_popover`` напрямую.
    """
    with filters_popover(st, label=title, reset_keys=reset_keys) as _fp:
        yield
        _fp.set_chips([])


PROJECT_FILTER_PLACEHOLDER = "Все"
PROJECT_FILTER_LABEL = "Проект"


def migrate_project_multiselect_state(
    st: Any, key: str, options: Sequence[str]
) -> None:
    """Пустой список в session_state = все проекты (placeholder «Все»)."""
    if not hasattr(st, "session_state"):
        return
    opts_set = {str(o).strip() for o in options if str(o).strip()}
    try:
        raw = st.session_state.get(key)
        if isinstance(raw, str):
            s = raw.strip()
            st.session_state[key] = (
                []
                if s in ("", PROJECT_FILTER_PLACEHOLDER, "Все", "Все проекты")
                else [s]
            )
        elif isinstance(raw, list):
            cleaned = [x for x in raw if str(x).strip() in opts_set]
            raw_labels = {str(x).strip() for x in raw}
            if raw_labels & {
                PROJECT_FILTER_PLACEHOLDER,
                "Все",
                "Все проекты",
            }:
                st.session_state[key] = []
            elif cleaned and opts_set and set(cleaned) == opts_set:
                st.session_state[key] = []
            else:
                st.session_state[key] = cleaned
    except Exception:
        pass


def project_filter_multiselect(
    st: Any,
    options: Sequence[str],
    key: str,
    *,
    label: str = PROJECT_FILTER_LABEL,
    help: Optional[str] = None,
) -> tuple[list[str], bool]:
    """
    Фильтр проектов: пустой выбор → все проекты, в поле показывается «Все»;
    при выборе — теги с крестиком (стандартный st.multiselect).
    """
    opts = [str(o).strip() for o in options if str(o).strip()]
    migrate_project_multiselect_state(st, key, opts)
    selected = st.multiselect(
        label,
        options=opts,
        key=key,
        placeholder=PROJECT_FILTER_PLACEHOLDER,
        help=help or "По умолчанию — все проекты. Отметьте один или несколько.",
    )
    sel = list(selected) if selected else []
    return sel, not bool(sel)


def count_chips(chips: Optional[Sequence[Chip]]) -> int:
    """Число непустых чипов для подписи на кнопке popover."""
    if not chips:
        return 0
    n = 0
    for label, value in chips:
        if str(label or "").strip() and str(value or "").strip():
            n += 1
    return n


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
    """
    if _is_release_mode():
        yield False
        return
    with st.expander(title, expanded=expanded):
        yield True
