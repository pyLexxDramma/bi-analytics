"""Интерактивная сортировка HTML-таблиц (клик по заголовку + фильтр по знаку)."""

from __future__ import annotations

import os
import re

import streamlit as st
import streamlit.components.v1 as components

_TABLE_SORT_JS = r"""
(function () {
  function parseNum(t) {
    var s = String(t || "").replace(/\s/g, "").replace(/\u00a0/g, "");
    var m = s.match(/-?\d+[.,]?\d*/);
    if (!m) return NaN;
    return parseFloat(m[0].replace(",", "."));
  }

  function rowKind(tr) {
    if (!tr) return "data";
    if (tr.classList.contains("bd-total-row") || tr.classList.contains("gdrs-rk-grand") || tr.classList.contains("gdrs-rk-total") || tr.classList.contains("rk-total")) return "total";
    if (tr.classList.contains("bd-group-row") || tr.classList.contains("gdrs-rk-subtotal") || tr.classList.contains("gdrs-rk-project") || tr.classList.contains("rk-project")) return "group";
    return "data";
  }

  function cellSortKey(tr, colIdx) {
    if (!tr || !tr.cells || !tr.cells[colIdx]) return "";
    var cell = tr.cells[colIdx];
    var dv = cell.getAttribute("data-sort-val");
    if (dv !== null && dv !== "") return dv;
    return (cell.textContent || "").trim();
  }

  function compareCells(at, bt, sortDir) {
    var an = parseNum(at), bn = parseNum(bt);
    var cmp = 0;
    if (!isNaN(an) && !isNaN(bn)) cmp = an - bn;
    else cmp = at.localeCompare(bt, "ru", { numeric: true, sensitivity: "base" });
    return sortDir > 0 ? cmp : -cmp;
  }

  function splitGroupedRows(rows) {
    var blocks = [];
    var totals = [];
    var cur = null;
    rows.forEach(function (r) {
      var k = rowKind(r);
      if (k === "total") { totals.push(r); return; }
      if (k === "group") {
        if (cur) blocks.push(cur);
        cur = { header: r, body: [] };
        return;
      }
      if (!cur) cur = { header: null, body: [] };
      cur.body.push(r);
    });
    if (cur) blocks.push(cur);
    return { blocks: blocks, totals: totals };
  }

  function tableHasProjectBlocks(rows) {
    return rows.some(function (r) {
      return (r.classList.contains("bd-group-row") || r.classList.contains("gdrs-rk-subtotal") || r.classList.contains("gdrs-rk-project") || r.classList.contains("rk-project"))
        && !r.classList.contains("bd-total-row") && !r.classList.contains("gdrs-rk-grand");
    });
  }

  function isProjectColumn(th, colIdx) {
    var t = (th && th.textContent) ? th.textContent.trim().toLowerCase() : "";
    if (t.indexOf("проект") >= 0) return true;
    return colIdx === 0;
  }

  function sortArrow(sortDir) {
    if (sortDir === -1) return " \u25BC";
    if (sortDir === 1) return " \u25B2";
    return " \u21C5";
  }

  function initTable(tbl) {
    if (!tbl || tbl.getAttribute("data-bi-sort-ready") === "1") return;
    tbl.setAttribute("data-bi-sort-ready", "1");
    if (!tbl.classList.contains("bi-sortable-table")) tbl.classList.add("bi-sortable-table");
    var theadRow = tbl.querySelector("thead tr");
    if (tbl.classList.contains("gdrs-matrix-table") || tbl.querySelector("thead tr.title-row")) {
      var headerRows = tbl.querySelectorAll("thead tr");
      if (headerRows.length > 1) theadRow = headerRows[headerRows.length - 1];
    }
    if (!theadRow) return;
    var ths = theadRow.querySelectorAll("th");
    var clickOnly = tbl.classList.contains("bi-sort-click-only");
    ths.forEach(function (th, colIdx) {
      if (th.getAttribute("data-bi-sort-th") === "1") return;
      th.setAttribute("data-bi-sort-th", "1");
      var labelText = th.getAttribute("data-sort-label") || (th.textContent || "").trim();
      labelText = labelText.replace(/\s[\u21C5\u25B2\u25BC\u2191\u2193]+$/, "").trim();
      th.innerHTML = "";
      th.style.verticalAlign = "middle";
      th.style.cursor = "pointer";
      var wrap = document.createElement("div");
      wrap.style.cssText =
        "display:flex;align-items:center;gap:6px;justify-content:space-between;width:100%;";
      var label = document.createElement("span");
      label.className = "bi-sort-label";
      label.style.cssText =
        "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;cursor:pointer;user-select:none;";
      label.title = "Клик — сортировка по убыванию, повторный клик — по возрастанию";
      var sel = document.createElement("select");
      sel.className = "bi-sort-filter";
      sel.title = "Сортировка и фильтр";
      sel.innerHTML =
        '<option value="">Все</option>' +
        '<option value="asc">\u2191</option>' +
        '<option value="desc">\u2193</option>' +
        '<option value="pos">+</option>' +
        '<option value="neg">\u2212</option>';
      sel.style.cssText =
        "font-size:11px;max-width:54px;background:#143252;color:#e8eef5;border:1px solid #5a7a9a;border-radius:4px;cursor:pointer;";
      wrap.appendChild(label);
      if (!clickOnly) wrap.appendChild(sel);
      th.appendChild(wrap);
      var sortDir = 0;
      var signFilter = "";

      function paintLabel() {
        label.textContent = labelText + sortArrow(sortDir);
      }

      function apply() {
        var tbody = tbl.querySelector("tbody");
        if (!tbody) return;
        var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
        var grouped = tableHasProjectBlocks(rows);
        var byProject = isProjectColumn(th, colIdx);

        function rowVisible(r) {
          if (!signFilter) return true;
          if (!r || !r.cells || !r.cells[colIdx]) return true;
          var n = parseNum(cellSortKey(r, colIdx));
          if (signFilter === "pos") return !isNaN(n) && n > 0;
          if (signFilter === "neg") return !isNaN(n) && n < 0;
          return true;
        }

        if (grouped) {
          var split = splitGroupedRows(rows);
          if (sortDir !== 0) {
            if (byProject) {
              split.blocks.sort(function (a, b) {
                var at = cellSortKey(a.header, colIdx) || cellSortKey(a.body[0], colIdx);
                var bt = cellSortKey(b.header, colIdx) || cellSortKey(b.body[0], colIdx);
                return compareCells(at, bt, sortDir);
              });
            } else {
              split.blocks.forEach(function (blk) {
                blk.body.sort(function (a, b) {
                  return compareCells(cellSortKey(a, colIdx), cellSortKey(b, colIdx), sortDir);
                });
              });
            }
          }
          var ordered = [];
          split.blocks.forEach(function (blk) {
            if (blk.header) ordered.push(blk.header);
            blk.body.forEach(function (r) { ordered.push(r); });
          });
          split.totals.forEach(function (r) { ordered.push(r); });
          ordered.forEach(function (r) {
            r.style.display = rowVisible(r) ? "" : "none";
            tbody.appendChild(r);
          });
          paintLabel();
          return;
        }

        if (sortDir !== 0) {
          var totals = [];
          var dataRows = [];
          rows.forEach(function (r) {
            if (rowKind(r) === "total") totals.push(r);
            else dataRows.push(r);
          });
          dataRows.sort(function (a, b) {
            return compareCells(cellSortKey(a, colIdx), cellSortKey(b, colIdx), sortDir);
          });
          dataRows.forEach(function (r) {
            r.style.display = rowVisible(r) ? "" : "none";
            tbody.appendChild(r);
          });
          totals.forEach(function (r) {
            r.style.display = rowVisible(r) ? "" : "none";
            tbody.appendChild(r);
          });
          paintLabel();
          return;
        }
        rows.forEach(function (r) {
          r.style.display = rowVisible(r) ? "" : "none";
          tbody.appendChild(r);
        });
        paintLabel();
      }

      function toggleSort(ev) {
        if (ev) {
          ev.preventDefault();
          ev.stopPropagation();
        }
        sortDir = sortDir >= 0 ? -1 : 1;
        apply();
      }

      paintLabel();
      label.addEventListener("click", toggleSort);
      th.addEventListener("click", function (ev) {
        if (ev.target && ev.target.classList && ev.target.classList.contains("bi-sort-filter")) return;
        toggleSort(ev);
      });
      if (!clickOnly) {
        sel.addEventListener("change", function (ev) {
          ev.stopPropagation();
          var v = sel.value;
          signFilter = "";
          if (v === "asc") sortDir = 1;
          else if (v === "desc") sortDir = -1;
          else if (v === "pos") { sortDir = 0; signFilter = "pos"; }
          else if (v === "neg") { sortDir = 0; signFilter = "neg"; }
          else sortDir = 0;
          apply();
        });
      }
    });
  }

  function scan(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("table.bi-sortable-table").forEach(initTable);
  }

  function bootDoc(doc) {
    if (!doc || !doc.body) return;
    scan(doc.body);
    [0, 30, 120, 400, 1000].forEach(function (ms) {
      setTimeout(function () { scan(doc.body); }, ms);
    });
  }

  bootDoc(document);
})();
"""

_TABLE_SORT_SCRIPT = f"<script>{_TABLE_SORT_JS}</script>"

_IFRAME_SHELL_CSS = """
<style>
html, body {
  margin: 0; padding: 0;
  background: transparent;
  color: #e0e0e0;
  font-family: Inter, system-ui, sans-serif;
}
.bi-sortable-html-root { width: 100%; max-width: 100%; }
.bi-sortable-html-root table.bi-sortable-table {
  border-collapse: separate !important;
  border-spacing: 0 !important;
  border: 1px solid #7a9ec4 !important;
}
.bi-sortable-html-root table.bi-sortable-table th,
.bi-sortable-html-root table.bi-sortable-table td {
  border-right: 1px solid #7a9ec4 !important;
  border-bottom: 1px solid #7a9ec4 !important;
  border-top: none !important;
  border-left: none !important;
}
.bi-sortable-html-root table.bi-sortable-table thead tr:first-child th {
  border-top: 1px solid #7a9ec4 !important;
}
.bi-sortable-html-root table.bi-sortable-table tr th:first-child,
.bi-sortable-html-root table.bi-sortable-table tr td:first-child {
  border-left: 1px solid #7a9ec4 !important;
}
</style>
"""

_IFRAME_SHELL_CSS_LIGHT = """
<style>
html, body {
  margin: 0; padding: 0;
  background: #ffffff;
  color: #111827;
  font-family: Inter, system-ui, sans-serif;
}
.bi-sortable-html-root { width: 100%; max-width: 100%; color: #111827; }
.bi-sortable-html-root h3.bi-table-caption,
.bi-sortable-html-root .bi-table-caption {
  color: #111827 !important;
  -webkit-text-fill-color: #111827 !important;
  opacity: 1 !important;
}
.bi-sortable-html-root table.bi-sortable-table {
  border-collapse: separate !important;
  border-spacing: 0 !important;
  border: 1px solid #cbd5e1 !important;
}
.bi-sortable-html-root table.bi-sortable-table th,
.bi-sortable-html-root table.bi-sortable-table td {
  border-right: 1px solid #cbd5e1 !important;
  border-bottom: 1px solid #cbd5e1 !important;
  border-top: none !important;
  border-left: none !important;
  color: #111827;
}
.bi-sortable-html-root table.bi-sortable-table thead tr:first-child th {
  border-top: 1px solid #cbd5e1 !important;
}
.bi-sortable-html-root table.bi-sortable-table tr th:first-child,
.bi-sortable-html-root table.bi-sortable-table tr td:first-child {
  border-left: 1px solid #cbd5e1 !important;
}
.bi-sortable-html-root .bi-sort-label { color: #111827 !important; }
.bi-sortable-html-root .bi-sort-filter {
  background: #ffffff !important;
  color: #111827 !important;
  border: 1px solid #94a3b8 !important;
}
</style>
"""


_GDRS_TABLE_WRAP_IFRAME_CSS = """
<style>
html, body {
  overflow-x: hidden !important;
  width: 100% !important;
  max-width: 100% !important;
  box-sizing: border-box !important;
}
.bi-sortable-html-root {
  width: 100% !important;
  max-width: 100% !important;
  overflow-x: hidden !important;
  box-sizing: border-box !important;
}
.gdrs-table-wrap {
  display: block !important;
  width: 100% !important;
  max-width: 100% !important;
  overflow-x: auto !important;
  overflow-y: visible !important;
  -webkit-overflow-scrolling: touch !important;
}
.gdrs-table-wrap .gdrs-matrix-table {
  width: max-content !important;
  min-width: 100% !important;
}
</style>
"""

def _iframe_shell_css(html: str) -> str:
    html_l = html or ""
    base = _IFRAME_SHELL_CSS_LIGHT if "gdrs-light-table" in html_l else _IFRAME_SHELL_CSS
    if "gdrs-table-wrap" in html_l:
        return base + _GDRS_TABLE_WRAP_IFRAME_CSS
    return base


def table_sort_inject_enabled() -> bool:
    return os.environ.get("BI_ANALYTICS_TABLE_SORT", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _split_embedded_style(html: str) -> tuple[str, str]:
    text = html or ""
    m = re.match(r"\s*(<style[^>]*>.*?</style>)\s*(.*)", text, flags=re.I | re.S)
    if m:
        return m.group(1), m.group(2)
    return "", text


def _estimate_html_block_height(html: str) -> int:
    bodies = re.findall(r"<tbody[^>]*>(.*?)</tbody>", html, re.I | re.S)
    if bodies:
        data_rows = sum(part.count("<tr") for part in bodies)
    else:
        data_rows = max(0, html.count("<tr") - 1)
    html_l = html or ""
    if "gdrs-summary-table-wrap" in html_l:
        thead_h = 76
        row_h = 44
        extra = 40
        cap = 1400
    elif "gdrs-matrix-table" in html_l or "gdrs-table-wrap" in html_l:
        thead_h = 132
        row_h = 38
        extra = 56
        cap = 2600
    elif "budget-deviation-table-wrap" in html_l:
        thead_h = 80
        row_h = 48
        extra = 52
        cap = 720
    elif "bi-sortable-table" in html_l:
        thead_h = 68
        row_h = 34
        extra = 24
        cap = 1000
    else:
        thead_h = 44
        row_h = 27
        extra = 16
        cap = 900
    est = thead_h + data_rows * row_h + extra
    return int(min(cap, max(120, est)))


def _build_sortable_html_document(html: str) -> str:
    style_block, body = _split_embedded_style(html)
    return (
        "<!DOCTYPE html><html lang='ru'><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"{style_block}{_iframe_shell_css(html)}"
        "</head><body>"
        f"<div class='bi-sortable-html-root'>{body}{_TABLE_SORT_SCRIPT}</div>"
        "</body></html>"
    )


def render_sortable_html_block(html: str) -> None:
    """Таблица + JS в одном iframe (components.html) — st.html не исполняет inline-скрипты."""
    if not html:
        return
    if not table_sort_inject_enabled():
        st.markdown(html, unsafe_allow_html=True)
        return
    doc = _build_sortable_html_document(html)
    _h = _estimate_html_block_height(html)
    _no_iframe_scroll = (
        "gdrs-summary-table-wrap",
        "budget-deviation-table-wrap",
    )
    _scroll = not any(m in (html or "") for m in _no_iframe_scroll)
    _h = _estimate_html_block_height(html) + (24 if not _scroll else 0)
    components.html(doc, height=_h, scrolling=_scroll)


def inject_sortable_tables_script() -> None:
    if not table_sort_inject_enabled():
        return
    components.html(
        _build_sortable_html_document("<div></div>"),
        height=0,
        scrolling=False,
    )


def rescan_sortable_tables_after_render() -> None:
    """Legacy: таблицы рендерятся через render_sortable_html_block."""
    if not table_sort_inject_enabled():
        return
    inject_sortable_tables_script()
