"""Интерактивная сортировка HTML-таблиц (клик по заголовку + фильтр по знаку)."""

from __future__ import annotations

import os

import streamlit.components.v1 as components


def table_sort_inject_enabled() -> bool:
    return os.environ.get("BI_ANALYTICS_TABLE_SORT", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def inject_sortable_tables_script() -> None:
    if not table_sort_inject_enabled():
        return
    components.html(
        """
        <script>
        (function () {
          var KEY = "__BI_TABLE_SORT_V1__";
          try {
            var hostWin = window.parent || window;
            if (hostWin[KEY]) return;
            hostWin[KEY] = true;
          } catch (e0) { return; }

          function docRoot() {
            try {
              if (window.parent && window.parent.document && window.parent.document.body)
                return window.parent.document;
            } catch (e1) {}
            return document;
          }

          function parseNum(t) {
            var s = String(t || "").replace(/\\s/g, "").replace(/\\u00a0/g, "");
            var m = s.match(/-?\\d+[.,]?\\d*/);
            if (!m) return NaN;
            return parseFloat(m[0].replace(",", "."));
          }

          function initTable(tbl) {
            if (!tbl || tbl.getAttribute("data-bi-sort-ready") === "1") return;
            tbl.setAttribute("data-bi-sort-ready", "1");
            if (!tbl.classList.contains("bi-sortable-table")) tbl.classList.add("bi-sortable-table");
            var theadRow = tbl.querySelector("thead tr");
            if (!theadRow) return;
            var ths = theadRow.querySelectorAll("th");
            ths.forEach(function (th, colIdx) {
              if (th.getAttribute("data-bi-sort-th") === "1") return;
              th.setAttribute("data-bi-sort-th", "1");
              var labelText = (th.textContent || "").trim();
              th.innerHTML = "";
              th.style.verticalAlign = "middle";
              var wrap = document.createElement("div");
              wrap.style.cssText = "display:flex;align-items:center;gap:6px;justify-content:space-between;width:100%;";
              var label = document.createElement("span");
              label.textContent = labelText;
              label.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;";
              label.title = "Клик — сортировка по возрастанию / убыванию";
              var sel = document.createElement("select");
              sel.className = "bi-sort-filter";
              sel.title = "Сортировка и фильтр";
              sel.innerHTML =
                '<option value="">Все</option>' +
                '<option value="asc">↑</option>' +
                '<option value="desc">↓</option>' +
                '<option value="pos">+</option>' +
                '<option value="neg">−</option>';
              sel.style.cssText =
                "font-size:11px;max-width:54px;background:#143252;color:#e8eef5;border:1px solid #5a7a9a;border-radius:4px;cursor:pointer;";
              wrap.appendChild(label);
              wrap.appendChild(sel);
              th.appendChild(wrap);
              var sortDir = 0;
              var signFilter = "";
              function apply() {
                var tbody = tbl.querySelector("tbody");
                if (!tbody) return;
                var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
                if (sortDir !== 0) {
                  rows.sort(function (a, b) {
                    var ac = a.cells[colIdx], bc = b.cells[colIdx];
                    var at = ac ? ac.textContent.trim() : "";
                    var bt = bc ? bc.textContent.trim() : "";
                    var an = parseNum(at), bn = parseNum(bt);
                    var cmp = 0;
                    if (!isNaN(an) && !isNaN(bn)) cmp = an - bn;
                    else cmp = at.localeCompare(bt, "ru", { numeric: true, sensitivity: "base" });
                    return sortDir > 0 ? cmp : -cmp;
                  });
                }
                rows.forEach(function (r) {
                  var cell = r.cells[colIdx];
                  var show = true;
                  if (signFilter && cell) {
                    var n = parseNum(cell.textContent);
                    if (signFilter === "pos") show = !isNaN(n) && n > 0;
                    else if (signFilter === "neg") show = !isNaN(n) && n < 0;
                  }
                  r.style.display = show ? "" : "none";
                  tbody.appendChild(r);
                });
              }
              label.addEventListener("click", function (ev) {
                ev.preventDefault();
                ev.stopPropagation();
                sortDir = sortDir <= 0 ? 1 : -1;
                apply();
              });
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
            });
          }

          function scan(root) {
            if (!root || !root.querySelectorAll) return;
            root.querySelectorAll("table.bi-sortable-table").forEach(initTable);
          }

          var doc = docRoot();
          scan(doc.body || doc);
          try {
            var obs = new MutationObserver(function () { scan(doc.body); });
            if (doc.body) obs.observe(doc.body, { childList: true, subtree: true });
          } catch (eObs) {}
        })();
        </script>
        """,
        height=0,
    )
