# -*- coding: utf-8 -*-
"""Общая инфраструктура светлых превью-вкладок (только dev, не клиентский release)."""
from __future__ import annotations

LIGHT_PREVIEW_SUFFIX = " (превью — светлая)"


def preview_light_name(base: str) -> str:
    """Каноническое имя превью: «БДДС (превью — светлая)»."""
    b = str(base or "").strip()
    if not b:
        return LIGHT_PREVIEW_SUFFIX.strip()
    if b.casefold().endswith(LIGHT_PREVIEW_SUFFIX.casefold()):
        return b
    return f"{b}{LIGHT_PREVIEW_SUFFIX}"


def is_light_preview_report(report_name: str) -> bool:
    """True для любой вкладки «… (превью — светлая)» (в т.ч. ГДРС)."""
    n = str(report_name or "").strip().casefold()
    return "превью" in n and "светл" in n


def light_preview_reports_enabled() -> bool:
    """Показывать ли светлые превью в меню (False на ai.conall.ru / release)."""
    try:
        from config import show_light_preview_reports

        return bool(show_light_preview_reports())
    except Exception:
        return False


def filter_reports_hide_light_preview(report_names: list[str]) -> list[str]:
    if light_preview_reports_enabled():
        return list(report_names)
    return [n for n in report_names if not is_light_preview_report(n)]


def apply_light_table_constants() -> None:
    """Патч палитры HTML-таблиц и Plotly в ``utils`` (только на время превью-run)."""
    import utils as u

    u.TABLE_BG_COLOR = "#ffffff"
    u.TABLE_HEADER_BG_COLOR = "#f3f4f6"
    u.TABLE_GROUP_ROW_BG_COLOR = "#e8ecf1"
    u.TABLE_TOTAL_ROW_BG_COLOR = "#e5e7eb"
    u.TABLE_TEXT_COLOR = "#111827"
    u.TABLE_CELL_BORDER = "1px solid #cbd5e1"
    u.FINANCE_TABLE_CELL_BORDER = "1px solid #94a3b8"
    u.CHART_BG_COLOR = "rgba(255, 255, 255, 0.96)"
    u.CHART_GRID_COLOR = "rgba(148, 163, 184, 0.45)"
    u.CHART_AXIS_LINE_COLOR = "rgba(100, 116, 139, 0.65)"
    u.CHART_ZEROLINE_COLOR = "rgba(100, 116, 139, 0.55)"
    u.TABLE_TOTAL_ROW_FONT_CSS = (
        "font-weight:800;font-size:1.32em;text-transform:uppercase;"
        "letter-spacing:0.05em;color:#111827;"
    )
    u.TABLE_CELL_BORDER_CSS = f"border: {u.TABLE_CELL_BORDER};"


def apply_dark_table_constants() -> None:
    """Восстановить production-палитру ``utils`` (после светлого превью)."""
    import utils as u

    u.TABLE_BG_COLOR = "hsl(209,67%,12%)"
    u.TABLE_HEADER_BG_COLOR = "hsl(209, 72%, 6%)"
    u.TABLE_GROUP_ROW_BG_COLOR = "hsl(209, 70%, 7%)"
    u.TABLE_TOTAL_ROW_BG_COLOR = "hsl(208, 58%, 18%)"
    u.TABLE_TEXT_COLOR = "#ffffff"
    u.TABLE_CELL_BORDER = "1px solid #5a7a9a"
    u.FINANCE_TABLE_CELL_BORDER = "1px solid #7a9ec4"
    u.CHART_BG_COLOR = "rgba(18, 56, 92, 0.88)"
    u.CHART_GRID_COLOR = "rgba(148, 163, 184, 0.45)"
    u.CHART_AXIS_LINE_COLOR = "rgba(100, 116, 139, 0.65)"
    u.CHART_ZEROLINE_COLOR = "rgba(100, 116, 139, 0.55)"
    u.TABLE_TOTAL_ROW_FONT_CSS = (
        "font-weight:800;font-size:1.32em;text-transform:uppercase;"
        "letter-spacing:0.05em;color:#f8fbff;"
    )
    u.TABLE_CELL_BORDER_CSS = f"border: {u.TABLE_CELL_BORDER};"


def is_light_preview_active() -> bool:
    """True, если текущая вкладка — светлое превью."""
    try:
        import streamlit as st

        return is_light_preview_report(str(st.session_state.get("current_dashboard") or ""))
    except Exception:
        return False


def finance_chart_label_color(*, dark: str = "#f0f4f8", light: str = "#111827") -> str:
    return light if is_light_preview_active() else dark


def finance_chart_neutral_label_color() -> str:
    return finance_chart_label_color(dark="#f0f4f8", light="#374151")


def finance_chart_caption_color() -> str:
    return finance_chart_label_color(dark="#e8eef5", light="#374151")


def finance_chart_legend_text_color() -> str:
    return finance_chart_label_color(dark="#e2e8f0", light="#111827")


def maybe_inject_light_filter_widgets(st) -> None:
    """CSS + JS для фильтров на светлом превью (после unified filters css)."""
    if not is_light_preview_active():
        return
    inject_light_filters_css(st)
    inject_light_widgets_fix_js(st)


def inject_light_widgets_fix_js(st) -> None:
    """components.html → parent document: date_input и календарь (emotion inline)."""
    import streamlit.components.v1 as components

    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        _ctx = get_script_run_ctx()
        _run_id = getattr(_ctx, "script_run_id", None) if _ctx else None
    except Exception:
        _run_id = None
    if _run_id is not None and st.session_state.get("_bi_light_widgets_js_run") == _run_id:
        return
    if _run_id is not None:
        st.session_state["_bi_light_widgets_js_run"] = _run_id

    components.html(
        """
<script>
(function(){
  var HANDLE = "__BI_LIGHT_WIDGETS_FIX_V15__";
  function resolveDoc() {
    try {
      if (window.parent && window.parent.document && window.parent.document.body)
        return window.parent.document;
    } catch (e0) {}
    try {
      if (window.top && window.top.document && window.top.document.body)
        return window.top.document;
    } catch (e1) {}
    return document.body ? document : null;
  }
  var doc = resolveDoc();
  if (!doc || !doc.body) return;
  var hostWin = doc.defaultView || window.parent || window;
  try {
    var prev = hostWin[HANDLE];
    if (prev) {
      if (prev.obs && prev.obs.disconnect) prev.obs.disconnect();
      if (prev.debounceTmr) clearTimeout(prev.debounceTmr);
    }
  } catch (eDisc) {}
  doc.documentElement.classList.add("gdrs-light-preview");
  doc.body.classList.add("gdrs-light-preview");
  var cssId = "bi-light-filters-live-css-v11";
  ["bi-light-filters-live-css", "bi-light-filters-live-css-v2", "bi-light-filters-live-css-v3", "bi-light-filters-live-css-v4", "bi-light-filters-live-css-v5", "bi-light-filters-live-css-v6", "bi-light-filters-live-css-v7", "bi-light-filters-live-css-v8", "bi-light-filters-live-css-v9", "bi-light-filters-live-css-v10"].forEach(function(id) {
    var node = doc.getElementById(id);
    if (node) node.remove();
  });
  if (!doc.getElementById(cssId)) {
    var stEl = doc.createElement("style");
    stEl.id = cssId;
    stEl.textContent = [
      "html body .stDateInput > div > div > input,",
      "html body [data-testid=\\"stDateInput\\"] [data-baseweb=\\"input\\"],",
      "html body [data-testid=\\"stDateInput\\"] [data-baseweb=\\"input\\"] > div,",
      "html body [data-testid=\\"stDateInput\\"] [data-baseweb=\\"input\\"] input,",
      "html body [data-testid=\\"stDateInput\\"] input,",
      "html body [data-testid=\\"stDateInput\\"] button,",
      "html body .bi-filters-scope [data-testid=\\"stDateInput\\"] [data-baseweb=\\"input\\"],",
      "html body .bi-filters-scope [data-testid=\\"stDateInput\\"] [data-baseweb=\\"input\\"] > div,",
      "html body .bi-filters-scope [data-testid=\\"stDateInput\\"] button {",
      "background:#fff!important;background-color:#fff!important;",
      "color:#111827!important;-webkit-text-fill-color:#111827!important;",
      "border-color:#cbd5e1!important;}",
      "html body div[data-baseweb=\\"popover\\"] {",
      "background:#fff!important;color:#111827!important;color-scheme:light!important;",
      "border:1px solid #cbd5e1!important;}",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"calendar\\"],",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"datepicker\\"],",
      "html body div[data-baseweb=\\"popover\\"] [role=\\"grid\\"] {",
      "background:#fff!important;color:#111827!important;}",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"calendar\\"] button,",
      "html body div[data-baseweb=\\"popover\\"] [role=\\"gridcell\\"] button {",
      "color:#111827!important;-webkit-text-fill-color:#111827!important;}",
      "html body [data-testid=\\"stCheckbox\\"] label[data-baseweb=\\"checkbox\\"] {",
      "display:inline-flex!important;align-items:flex-start!important;gap:0.5rem!important;background:transparent!important;}",
      "html body [data-testid=\\"stCheckbox\\"] label[data-baseweb=\\"checkbox\\"] > input + div {",
      "width:16px!important;height:16px!important;min-width:16px!important;flex-shrink:0!important;",
      "display:flex!important;align-items:center!important;justify-content:center!important;",
      "border:2px solid #64748b!important;border-radius:4px!important;background:#fff!important;}",
      "html body [data-testid=\\"stCheckbox\\"] label[data-baseweb=\\"checkbox\\"]:has(input:checked) > input + div {",
      "background:#2563eb!important;border-color:#2563eb!important;}",
      "html body [data-testid=\\"stCheckbox\\"] label[data-baseweb=\\"checkbox\\"] > div:has(p) {",
      "background:transparent!important;border:none!important;width:auto!important;flex:1 1 auto!important;}",
      "html body section.main div[data-testid=\\"stHorizontalBlock\\"]:has(> div[data-testid=\\"column\\"] [data-testid=\\"stCheckbox\\"]) > div[data-testid=\\"column\\"] {",
      "flex:1 1 14rem!important;min-width:11rem!important;width:auto!important;max-width:none!important;}",
      "html body [data-testid=\\"stCheckbox\\"] label[data-baseweb=\\"checkbox\\"] p {",
      "white-space:normal!important;min-width:8rem!important;max-width:none!important;color:#111827!important;}",
      "html body div[data-baseweb=\\"popover\\"] li,",
      "html body div[data-baseweb=\\"popover\\"] li span,",
      "html body div[data-baseweb=\\"menu\\"] li,",
      "html body div[data-baseweb=\\"menu\\"] li span {",
      "background:#fff!important;color:#111827!important;}",
      "html body div[data-baseweb=\\"popover\\"] li:hover,",
      "html body div[data-baseweb=\\"popover\\"] li[data-highlighted],",
      "html body div[data-baseweb=\\"popover\\"] li[data-highlighted=\\"true\\"],",
      "html body div[data-baseweb=\\"popover\\"] li[aria-selected=\\"true\\"],",
      "html body div[data-baseweb=\\"menu\\"] li:hover,",
      "html body div[data-baseweb=\\"menu\\"] li[data-highlighted],",
      "html body div[data-baseweb=\\"menu\\"] li[data-highlighted=\\"true\\"],",
      "html body div[data-baseweb=\\"menu\\"] li[aria-selected=\\"true\\"] {",
      "background:#e5e7eb!important;background-color:#e5e7eb!important;color:#111827!important;}",
      "html body div[data-baseweb=\\"popover\\"] [role=\\"listbox\\"] [role=\\"option\\"][data-highlighted=\\"true\\"],",
      "html body div[data-baseweb=\\"popover\\"] [role=\\"listbox\\"] [role=\\"option\\"][aria-selected=\\"true\\"] {",
      "background:#e5e7eb!important;color:#111827!important;}",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"calendar\\"],",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"datepicker\\"],",
      "html body div[data-baseweb=\\"popover\\"] [role=\\"grid\\"] {",
      "background:#fff!important;color:#111827!important;color-scheme:light!important;}",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"calendar\\"] [role=\\"grid\\"] [role=\\"gridcell\\"] {",
      "background:transparent!important;color:#111827!important;}",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"calendar\\"] [role=\\"grid\\"] [role=\\"gridcell\\"]::before,",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"calendar\\"] [role=\\"grid\\"] [role=\\"gridcell\\"]::after {",
      "content:none!important;display:none!important;background:transparent!important;}",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"calendar\\"] [role=\\"gridcell\\"]>div:first-child {",
      "width:2.25rem!important;height:2.25rem!important;margin:0 auto!important;",
      "display:inline-flex!important;align-items:center!important;justify-content:center!important;",
      "border-radius:9999px!important;color:#111827!important;background:transparent!important;}",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"calendar\\"] [role=\\"gridcell\\"]:hover>div:first-child,",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"calendar\\"] [role=\\"gridcell\\"][tabindex=\\"0\\"]>div:first-child {",
      "background:#f3f4f6!important;color:#111827!important;}",
      "html body div[data-baseweb=\\"popover\\"] [data-baseweb=\\"calendar\\"] [role=\\"gridcell\\"][data-bi-selected=\\"1\\"]>div:first-child {",
      "background:#2563eb!important;color:#fff!important;-webkit-text-fill-color:#fff!important;}",
    ].join("\\n");
    (doc.head || doc.body).appendChild(stEl);
  }
  function paintDateInputs() {
    doc.querySelectorAll('[data-testid="stDateInput"]').forEach(function(w) {
      w.querySelectorAll('[data-baseweb="input"], [data-baseweb="input"] > div, input, button').forEach(function(el) {
        if (el.closest('div[data-baseweb="popover"]')) return;
        if (el.getAttribute("data-bi-light") === "1") return;
        el.style.setProperty("background-color", "#ffffff", "important");
        el.style.setProperty("color", "#111827", "important");
        el.style.setProperty("-webkit-text-fill-color", "#111827", "important");
        el.style.setProperty("border-color", "#cbd5e1", "important");
        el.setAttribute("data-bi-light", "1");
      });
    });
  }
  function neutralizeCachedDarkCss() {
    if (doc.documentElement.getAttribute("data-bi-dark-css-off") === "1") return;
    doc.documentElement.setAttribute("data-bi-dark-css-off", "1");
    doc.querySelectorAll("style:not([id^='bi-light']):not([id='gdrs-light-preview-css'])").forEach(function(node) {
      var t = node.textContent || "";
      if (t.indexOf("#2a2a3a") >= 0 && t.indexOf(".stDateInput") >= 0) {
        node.setAttribute("media", "not all");
      }
    });
  }
  function isCalendarNode(el) {
    return !!(el && el.closest && el.closest('[data-baseweb="calendar"], [data-baseweb="datepicker"], [role="grid"]'));
  }
  function fixMenuHighlight() {
    doc.querySelectorAll('div[data-baseweb="popover"]').forEach(function(pop) {
      if (pop.querySelector('[data-baseweb="calendar"], [data-baseweb="datepicker"]')) return;
      pop.querySelectorAll('li[data-highlighted="true"], li[aria-selected="true"], [role="option"][data-highlighted="true"], [role="option"][aria-selected="true"]').forEach(function(el) {
        if (isCalendarNode(el)) return;
        el.style.setProperty("background-color", "#e5e7eb", "important");
        el.style.setProperty("color", "#111827", "important");
        el.querySelectorAll("*").forEach(function(n) {
          n.style.setProperty("background-color", "transparent", "important");
          n.style.setProperty("color", "#111827", "important");
        });
      });
    });
  }
  function isSelectedDayLabel(label) {
    var l = (label || "").toLowerCase();
    return l.indexOf("selected") >= 0 || l.indexOf("выбран") >= 0 || l.indexOf("выбрано") >= 0;
  }
  function repaintCalendarDays() {
    doc.querySelectorAll('div[data-baseweb="popover"] [data-baseweb="calendar"] [role="gridcell"]').forEach(function(cell) {
      var label = cell.getAttribute("aria-label") || "";
      if (isSelectedDayLabel(label)) cell.setAttribute("data-bi-selected", "1");
      else cell.removeAttribute("data-bi-selected");
    });
  }
  function ensureCalendarWatch() {
    doc.querySelectorAll('div[data-baseweb="popover"]').forEach(function(pop) {
      if (!pop.querySelector('[data-baseweb="calendar"]') || pop.getAttribute("data-bi-cal-watch")) return;
      pop.setAttribute("data-bi-cal-watch", "1");
      var tmr = null;
      new MutationObserver(function() {
        if (tmr) return;
        tmr = setTimeout(function() { tmr = null; repaintCalendarDays(); }, 20);
      }).observe(pop, {subtree: true, attributes: true, attributeFilter: ["aria-label", "tabindex", "class"]});
      repaintCalendarDays();
    });
  }
  function paintCalendarShell() {
    doc.querySelectorAll('div[data-baseweb="popover"]').forEach(function(pop) {
      if (!pop.querySelector('[data-baseweb="calendar"], [data-baseweb="datepicker"]')) return;
      pop.style.setProperty("background-color", "#ffffff", "important");
      pop.style.setProperty("color-scheme", "light", "important");
    });
  }
  function fixOpenPopover() {
    var calOpen = false;
    doc.querySelectorAll('div[data-baseweb="popover"]').forEach(function(pop) {
      if (pop.querySelector('[data-baseweb="calendar"], [data-baseweb="datepicker"]')) {
        calOpen = true;
        paintCalendarShell();
        ensureCalendarWatch();
        repaintCalendarDays();
      }
    });
    if (!calOpen) fixMenuHighlight();
  }
  var menuMoveTmr = null;
  function scheduleMenuFix() {
    if (menuMoveTmr) return;
    menuMoveTmr = setTimeout(function() {
      menuMoveTmr = null;
      var pop = doc.querySelector('div[data-baseweb="popover"]');
      if (!pop || pop.querySelector('[data-baseweb="calendar"], [data-baseweb="datepicker"]')) return;
      fixMenuHighlight();
    }, 24);
  }
  function fixCheckedCheckboxLabels() {
    doc.querySelectorAll('[data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked)').forEach(function(lbl) {
      lbl.style.setProperty("background", "transparent", "important");
      lbl.style.setProperty("background-color", "transparent", "important");
      lbl.querySelectorAll(":scope > div:has(p), p").forEach(function(n) {
        n.style.setProperty("background", "transparent", "important");
        n.style.setProperty("background-color", "transparent", "important");
        n.style.setProperty("color", "#111827", "important");
      });
    });
  }
  function tick() {
    neutralizeCachedDarkCss();
    paintDateInputs();
    fixCheckedCheckboxLabels();
  }
  tick();
  setTimeout(tick, 400);
  doc.addEventListener("click", function() {
    setTimeout(fixOpenPopover, 0);
    setTimeout(fixOpenPopover, 50);
    setTimeout(fixOpenPopover, 150);
    setTimeout(fixOpenPopover, 400);
  }, true);
  doc.addEventListener("keydown", function() { setTimeout(fixOpenPopover, 0); scheduleMenuFix(); }, true);
  doc.addEventListener("mousemove", scheduleMenuFix, true);
  doc.addEventListener("change", function(e) {
    if (e.target && e.target.type === "checkbox") fixCheckedCheckboxLabels();
  }, true);
  hostWin[HANDLE] = {};
})();
</script>
""",
        height=0,
        scrolling=False,
    )


def inject_light_filters_css(st) -> None:
    """Фильтры/чекбоксы/дата/календарь — светлая палитра (bi-filters-scope, expander)."""
    st.markdown(
        """
<style id="bi-light-filters-css">
/* Streamlit markdown-обёртки bi-filters-* не оборачивают виджеты — только :has() по DOM */
html body section.main [data-testid="stExpanderDetails"] div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] [data-testid="stCheckbox"]) > div[data-testid="column"],
html body section.main div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] [data-testid="stCheckbox"]) > div[data-testid="column"] {
  flex: 1 1 14rem !important;
  min-width: 11rem !important;
  max-width: none !important;
  width: auto !important;
}
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"] {
  display: inline-flex !important;
  flex-direction: row !important;
  align-items: flex-start !important;
  gap: 0.5rem !important;
  width: 100% !important;
  max-width: none !important;
  color: #111827 !important;
}
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"] p {
  flex: 1 1 auto !important;
  min-width: 8rem !important;
  width: auto !important;
  max-width: none !important;
  white-space: normal !important;
  word-break: normal !important;
  overflow-wrap: anywhere !important;
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body .stCheckbox > label,
html body [data-testid="stCheckbox"] > label {
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body.gdrs-light-preview .bi-filters-section-title,
html body.gdrs-light-preview .bi-filter-chip,
html body.gdrs-light-preview .bi-filter-chip b,
html body .bi-filters-section-title,
html body .bi-filter-chip,
html body .bi-filter-chip b {
  color: #374151 !important;
  -webkit-text-fill-color: #374151 !important;
}
html body.gdrs-light-preview .bi-filter-chip,
html body .bi-filter-chip {
  background: #f3f4f6 !important;
  border: 1px solid #cbd5e1 !important;
}
html body.gdrs-light-preview .bi-filter-chip b,
html body .bi-filter-chip b {
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body.gdrs-light-preview .bi-filters-toggles,
html body .bi-filters-toggles {
  border-top-color: #e5e7eb !important;
}
/* Колонки чекбоксов: ui_quiet width:0 ломает подписи (по букве) */
html.gdrs-light-preview .bi-filters-toggles div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
html body.gdrs-light-preview .bi-filters-toggles div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
html body .bi-filters-scope div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] [data-testid="stCheckbox"]) > div[data-testid="column"],
html body .bi-filters-toggles div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
  flex: 1 1 14rem !important;
  min-width: 10rem !important;
  width: auto !important;
  max-width: none !important;
}
html.gdrs-light-preview .bi-filters-toggles [data-testid="stCheckbox"] label,
html.gdrs-light-preview .bi-filters-toggles [data-testid="stCheckbox"] label p,
html body.gdrs-light-preview .bi-filters-toggles [data-testid="stCheckbox"] label p {
  white-space: normal !important;
  word-break: normal !important;
  overflow-wrap: anywhere !important;
  max-width: none !important;
  line-height: 1.35 !important;
}

/* Чекбоксы — квадрат сразу после input (как радио в gdrs_theme) */
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"],
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"] {
  display: inline-flex !important;
  flex-direction: row !important;
  align-items: flex-start !important;
  gap: 0.5rem !important;
  background: transparent !important;
  background-color: transparent !important;
}
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"] > input,
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"] > input {
  position: absolute !important;
  opacity: 0 !important;
  width: 1px !important;
  height: 1px !important;
  margin: 0 !important;
  pointer-events: none !important;
}
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"] > input + div,
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"] > input + div {
  width: 16px !important;
  height: 16px !important;
  min-width: 16px !important;
  min-height: 16px !important;
  margin-top: 2px !important;
  border: 2px solid #64748b !important;
  border-radius: 4px !important;
  background-color: #ffffff !important;
  box-sizing: border-box !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  flex-shrink: 0 !important;
}
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked) > input + div,
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked) > input + div {
  border-color: #2563eb !important;
  background-color: #2563eb !important;
}
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked),
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked),
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked) > div:has(p),
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked) > div:has(p),
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked) p,
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked) p {
  background: transparent !important;
  background-color: transparent !important;
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"] > input + div > div,
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"] > input + div > div {
  background-color: transparent !important;
}
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"] > div:has(p),
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"] > div:has(p) {
  background: transparent !important;
  border: none !important;
  width: auto !important;
  max-width: none !important;
  min-width: 0 !important;
  height: auto !important;
  flex: 1 1 auto !important;
}
html body section.main [data-testid="stCheckbox"] label[data-baseweb="checkbox"] svg,
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"] svg {
  fill: #ffffff !important;
  color: #ffffff !important;
}

/* Чекбоксы: прозрачный фон строки */
html body.gdrs-light-preview [data-testid="stCheckbox"],
html body.gdrs-light-preview [data-testid="stCheckbox"] > label,
html body.gdrs-light-preview [data-testid="stCheckbox"] label[data-baseweb="checkbox"],
html body.gdrs-light-preview .bi-filters-scope [data-testid="stCheckbox"],
html body.gdrs-light-preview .bi-filters-toggles [data-testid="stCheckbox"],
html body.gdrs-light-preview [data-testid="stExpanderDetails"] [data-testid="stCheckbox"],
html body .bi-filters-scope [data-testid="stCheckbox"],
html body .bi-filters-toggles [data-testid="stCheckbox"],
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] {
  background-color: transparent !important;
  background: transparent !important;
}
html body.gdrs-light-preview .bi-filters-scope [data-testid="stCheckbox"] label,
html body.gdrs-light-preview .bi-filters-scope [data-testid="stCheckbox"] label p,
html body.gdrs-light-preview .bi-filters-scope [data-testid="stCheckbox"] label span,
html body.gdrs-light-preview .bi-filters-toggles [data-testid="stCheckbox"] label,
html body.gdrs-light-preview .bi-filters-toggles [data-testid="stCheckbox"] label p,
html body.gdrs-light-preview .bi-filters-toggles [data-testid="stCheckbox"] label span,
html body.gdrs-light-preview [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label,
html body.gdrs-light-preview [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label p,
html body.gdrs-light-preview [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label span,
html body.gdrs-light-preview [data-testid="stExpander"] [data-testid="stWidgetLabel"],
html body.gdrs-light-preview [data-testid="stExpander"] [data-testid="stWidgetLabel"] p,
html body.gdrs-light-preview .bi-filters-selectors [data-testid="stWidgetLabel"],
html body.gdrs-light-preview .bi-filters-selectors [data-testid="stWidgetLabel"] p,
html body .bi-filters-scope [data-testid="stCheckbox"] label,
html body .bi-filters-scope [data-testid="stCheckbox"] label p,
html body .bi-filters-scope [data-testid="stCheckbox"] label span,
html body .bi-filters-toggles [data-testid="stCheckbox"] label,
html body .bi-filters-toggles [data-testid="stCheckbox"] label p,
html body .bi-filters-toggles [data-testid="stCheckbox"] label span,
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label,
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label p,
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] label span,
html body [data-testid="stExpander"] [data-testid="stWidgetLabel"],
html body [data-testid="stExpander"] [data-testid="stWidgetLabel"] p,
html body .bi-filters-selectors [data-testid="stWidgetLabel"],
html body .bi-filters-selectors [data-testid="stWidgetLabel"] p {
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
  opacity: 1 !important;
}

/* Selectbox / multiselect: выпадающий список — hover и выделение в цвет светлой темы */
html body div[data-baseweb="popover"] ul,
html body div[data-baseweb="popover"] li,
html body div[data-baseweb="popover"] li span,
html body div[data-baseweb="menu"] li,
html body div[data-baseweb="menu"] li span {
  background-color: #ffffff !important;
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body div[data-baseweb="popover"] li:hover,
html body div[data-baseweb="popover"] li[data-highlighted],
html body div[data-baseweb="popover"] li[data-highlighted="true"],
html body div[data-baseweb="popover"] li[aria-selected="true"],
html body div[data-baseweb="menu"] li:hover,
html body div[data-baseweb="menu"] li[data-highlighted],
html body div[data-baseweb="menu"] li[data-highlighted="true"],
html body div[data-baseweb="menu"] li[aria-selected="true"] {
  background-color: #e5e7eb !important;
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body div[data-baseweb="popover"] li[data-highlighted] *,
html body div[data-baseweb="popover"] li[data-highlighted="true"] *,
html body div[data-baseweb="popover"] li[aria-selected="true"] *,
html body div[data-baseweb="menu"] li[data-highlighted] * {
  background-color: transparent !important;
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body div[data-baseweb="popover"] [role="listbox"] [role="option"][data-highlighted="true"],
html body div[data-baseweb="popover"] [role="listbox"] [role="option"][aria-selected="true"],
html body div[data-baseweb="popover"] ul[role="listbox"] ~ * [role="option"][data-highlighted="true"] {
  background-color: #e5e7eb !important;
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body [data-testid="stCheckbox"] > [data-testid="stWidgetLabel"] {
  display: none !important;
}
html body [data-testid="stExpanderDetails"] [data-testid="stCheckbox"] {
  margin-bottom: 0.35rem !important;
}

/* Календарь (date_input range) — не смешивать с menu/select highlight */
html body div[data-baseweb="popover"] [data-baseweb="calendar"],
html body div[data-baseweb="popover"] [data-baseweb="datepicker"],
html body div[data-baseweb="popover"] [data-baseweb="calendar"] > div,
html body div[data-baseweb="popover"] [role="grid"],
html body div[data-baseweb="popover"] [role="presentation"] {
  background-color: #ffffff !important;
  color: #111827 !important;
}
html body div[data-baseweb="popover"] [data-baseweb="calendar"] > div:first-child,
html body div[data-baseweb="popover"] [data-baseweb="datepicker"] > div:first-child,
html body div[data-baseweb="popover"] [data-baseweb="calendar"] header {
  background-color: #f3f4f6 !important;
  color: #111827 !important;
}
/* BaseWeb Day = [role="gridcell"] (не button); чёрные блоки — ::before от darkenedBgMix15 */
html body div[data-baseweb="popover"] [data-baseweb="calendar"] [role="grid"] [role="gridcell"] {
  background: transparent !important;
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body div[data-baseweb="popover"] [data-baseweb="calendar"] [role="grid"] [role="gridcell"]::before,
html body div[data-baseweb="popover"] [data-baseweb="calendar"] [role="grid"] [role="gridcell"]::after {
  content: none !important;
  display: none !important;
  background: transparent !important;
}
html body div[data-baseweb="popover"] [data-baseweb="calendar"] [role="gridcell"] > div:first-child {
  width: 2.25rem !important;
  height: 2.25rem !important;
  margin: 0 auto !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  border-radius: 9999px !important;
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
  background: transparent !important;
}
html body div[data-baseweb="popover"] [data-baseweb="calendar"] [role="gridcell"]:hover > div:first-child,
html body div[data-baseweb="popover"] [data-baseweb="calendar"] [role="gridcell"][tabindex="0"] > div:first-child {
  background-color: #f3f4f6 !important;
  color: #111827 !important;
}
html body div[data-baseweb="popover"] [data-baseweb="calendar"] [role="gridcell"][data-bi-selected="1"] > div:first-child {
  background-color: #2563eb !important;
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
}
html body div[data-baseweb="popover"] [data-baseweb="calendar"] span,
html body div[data-baseweb="popover"] [data-baseweb="calendar"] p,
html body div[data-baseweb="popover"] [role="columnheader"] {
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}

/* Период (st.date_input) — перебивает style.css + Streamlit dark theme */
html.gdrs-light-preview .stDateInput > div > div > input,
html.gdrs-light-preview [data-testid="stDateInput"] label,
html.gdrs-light-preview [data-testid="stDateInput"] [data-testid="stWidgetLabel"],
html.gdrs-light-preview [data-testid="stDateInput"] [data-testid="stWidgetLabel"] p,
html.gdrs-light-preview [data-testid="stDateInput"] label p,
html body.gdrs-light-preview [data-testid="stDateInput"] label,
html body.gdrs-light-preview [data-testid="stDateInput"] [data-testid="stWidgetLabel"],
html body.gdrs-light-preview [data-testid="stDateInput"] [data-testid="stWidgetLabel"] p,
html body.gdrs-light-preview [data-testid="stDateInput"] label p,
html body .bi-filters-scope [data-testid="stDateInput"] label,
html body .bi-filters-scope [data-testid="stDateInput"] [data-testid="stWidgetLabel"],
html body .bi-filters-scope [data-testid="stDateInput"] [data-testid="stWidgetLabel"] p {
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html.gdrs-light-preview [data-testid="stDateInput"] [data-baseweb="input"],
html.gdrs-light-preview [data-testid="stDateInput"] [data-baseweb="input"] > div,
html.gdrs-light-preview [data-testid="stDateInput"] [data-baseweb="input"] input,
html.gdrs-light-preview [data-testid="stDateInput"] input,
html.gdrs-light-preview [data-testid="stDateInput"] button,
html.gdrs-light-preview .stDateInput > div > div,
html.gdrs-light-preview .stDateInput > div > div > input,
html body.gdrs-light-preview [data-testid="stDateInput"] [data-baseweb="input"],
html body.gdrs-light-preview [data-testid="stDateInput"] [data-baseweb="input"] > div,
html body.gdrs-light-preview [data-testid="stDateInput"] [data-baseweb="input"] input,
html body.gdrs-light-preview [data-testid="stDateInput"] input,
html body.gdrs-light-preview .stDateInput > div > div,
html body.gdrs-light-preview .stDateInput > div > div > input,
html body .bi-filters-scope [data-testid="stDateInput"] [data-baseweb="input"],
html body .bi-filters-scope [data-testid="stDateInput"] [data-baseweb="input"] > div,
html body .bi-filters-scope [data-testid="stDateInput"] [data-baseweb="input"] input,
html body .bi-filters-scope [data-testid="stDateInput"] input,
html body .bi-filters-scope .stDateInput > div > div,
html body .bi-filters-scope .stDateInput > div > div > input {
  background-color: #ffffff !important;
  background: #ffffff !important;
  color: #111827 !important;
  border-color: #cbd5e1 !important;
  -webkit-text-fill-color: #111827 !important;
}
html.gdrs-light-preview [data-testid="stDateInput"] [data-baseweb="input"]:focus-within,
html.gdrs-light-preview [data-testid="stDateInput"] input:focus,
html body.gdrs-light-preview [data-testid="stDateInput"] [data-baseweb="input"]:focus-within,
html body .bi-filters-scope [data-testid="stDateInput"] [data-baseweb="input"]:focus-within {
  border-color: #2563eb !important;
  box-shadow: 0 0 0 1px #2563eb !important;
}
html.gdrs-light-preview [data-testid="stDateInput"] button,
html.gdrs-light-preview [data-testid="stDateInput"] [data-baseweb="button"],
html body.gdrs-light-preview [data-testid="stDateInput"] button,
html body .bi-filters-scope [data-testid="stDateInput"] button {
  background-color: #ffffff !important;
  color: #111827 !important;
  border-color: #cbd5e1 !important;
}
html.gdrs-light-preview [data-testid="stDateInput"] svg,
html body.gdrs-light-preview [data-testid="stDateInput"] svg,
html body .bi-filters-scope [data-testid="stDateInput"] svg {
  fill: #475569 !important;
  color: #475569 !important;
}

/* Popover календаря (portaled к body) */
html.gdrs-light-preview div[data-baseweb="popover"],
html body.gdrs-light-preview div[data-baseweb="popover"] {
  background-color: #ffffff !important;
  border: 1px solid #cbd5e1 !important;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.14) !important;
  color-scheme: light !important;
}
html.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] > div:first-child,
html.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="datepicker"] > div:first-child,
html.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] header,
html.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="datepicker"] header,
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] > div:first-child,
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="datepicker"] > div:first-child,
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] header,
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="datepicker"] header {
  background-color: #f3f4f6 !important;
  color: #111827 !important;
}
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] > div:first-child *,
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="datepicker"] > div:first-child *,
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] header * {
  background-color: transparent !important;
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"],
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="datepicker"],
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] > div,
html body.gdrs-light-preview div[data-baseweb="popover"] [role="grid"],
html body.gdrs-light-preview div[data-baseweb="popover"] [role="presentation"] {
  background-color: #ffffff !important;
  color: #111827 !important;
}
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] span,
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] p,
html body.gdrs-light-preview div[data-baseweb="popover"] [role="columnheader"] {
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] [role="grid"] [role="gridcell"]::before,
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] [role="grid"] [role="gridcell"]::after {
  content: none !important;
  display: none !important;
  background: transparent !important;
}
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] [role="gridcell"] > div:first-child {
  width: 2.25rem !important;
  height: 2.25rem !important;
  margin: 0 auto !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  border-radius: 9999px !important;
  color: #111827 !important;
  background: transparent !important;
}
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] [role="gridcell"]:hover > div:first-child,
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] [role="gridcell"][tabindex="0"] > div:first-child {
  background-color: #f3f4f6 !important;
}
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] [role="gridcell"][data-bi-selected="1"] > div:first-child {
  background-color: #2563eb !important;
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
}
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="calendar"] svg,
html body.gdrs-light-preview div[data-baseweb="popover"] [data-baseweb="datepicker"] svg {
  fill: #475569 !important;
  color: #475569 !important;
}

html body.gdrs-light-preview .budget-deviation-table-wrap tr.bd-total-row td,
html body.gdrs-light-preview .bi-light-table .budget-deviation-table-wrap tr.bd-total-row td,
html body .budget-deviation-table-wrap tr.bd-total-row td,
html body .bi-light-table .budget-deviation-table-wrap tr.bd-total-row td {
  background-color: #e5e7eb !important;
  color: #111827 !important;
}
html body.gdrs-light-preview .budget-deviation-table-wrap tr.bd-total-row td *,
html body.gdrs-light-preview .bi-light-table .budget-deviation-table-wrap tr.bd-total-row td *,
html body .budget-deviation-table-wrap tr.bd-total-row td *,
html body .bi-light-table .budget-deviation-table-wrap tr.bd-total-row td * {
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
}
html body.gdrs-light-preview .budget-deviation-table-wrap tr.bd-group-row td,
html body.gdrs-light-preview .bi-light-table .budget-deviation-table-wrap tr.bd-group-row td,
html body .budget-deviation-table-wrap tr.bd-group-row td,
html body .bi-light-table .budget-deviation-table-wrap tr.bd-group-row td {
  background-color: #f3f4f6 !important;
  color: #111827 !important;
}
</style>
""",
        unsafe_allow_html=True,
    )


def inject_light_preview_css(st) -> None:
    """CSS оболочки Streamlit для светлых превью (sidebar, фильтры, заголовки)."""
    from dashboards.gdrs_theme import inject_gdrs_light_preview_css

    inject_gdrs_light_preview_css(st)
    inject_light_filters_css(st)
    if is_light_preview_active():
        inject_light_widgets_fix_js(st)


def light_preview_heading_html(title: str) -> str:
    """H1 для светлого превью (чёрный заголовок, как у ГДРС)."""
    import html as _html

    safe = _html.escape(str(title or "").strip())
    return (
        f'<h1 class="main-header gdrs-light-heading bi-light-preview-heading" '
        f'style="color:#000000!important;-webkit-text-fill-color:#000000!important;'
        f'font-weight:800!important;opacity:1!important;">{safe}</h1>'
    )


def resolve_light_preview_title(report_name: str) -> str:
    """Заголовок H1: для ГДРС — коротко «ГДРС», иначе полное имя без суффикса превью."""
    n = str(report_name or "").strip()
    if not is_light_preview_report(n):
        return n
    nl = n.casefold()
    if nl.startswith("гдрс"):
        return "ГДРС"
    suffix = LIGHT_PREVIEW_SUFFIX
    if nl.endswith(suffix.casefold()):
        return n[: -len(suffix)].strip() or n
    return n
