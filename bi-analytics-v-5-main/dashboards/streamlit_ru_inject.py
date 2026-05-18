"""Локализация англоязычных подписей Streamlit (multiselect, date_input, dataframe grid).

Вынесено из ``dashboards._renderers``, чтобы ``project_visualization_app`` не тянул тяжёлый модуль
только ради одного вызова ``components.html``.

Public API: ``inject_multiselect_ru_translations``, ``ru_inject_enabled``.

По умолчанию выключено (``BI_ANALYTICS_RU_INJECT=1`` включает): MutationObserver сильно тормозит rerun.
"""

from __future__ import annotations

import os

import streamlit.components.v1 as components


def ru_inject_enabled() -> bool:
    return os.environ.get("BI_ANALYTICS_RU_INJECT", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def inject_multiselect_ru_translations() -> None:
    if not ru_inject_enabled():
        return
    """Локализация англоязычных подписей Streamlit-виджетов (1.50+):
    multiselect (Choose options / Select all / Select N matches / No results),
    date_input range presets (Past Week / Past Month / ...) и
    подписи самого календаря (названия месяцев, сокращения дней недели).

    Также подписи контекстного меню столбцов ``st.dataframe`` / ``st.data_editor`` (Glide Data Grid).

    Использует `st.components.v1.html` с MutationObserver. На каждом rerun Streamlit
    без этого iframe скрипт пропадает — вызываем ``components.html`` каждый раз;
    один наблюдатель на вкладку через флаг на ``window.parent``.
    """
    components.html(
        """
        <script>
        (function(){
            try {
                var HANDLE_KEY = '__BI_RU_TRANSLATIONS_HANDLE_V9__';
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
                    var prev = hostWin[HANDLE_KEY];
                    if (prev) {
                        if (prev.obs && prev.obs.disconnect) prev.obs.disconnect();
                        if (prev.tmr) clearInterval(prev.tmr);
                    }
                } catch (eDisc) {}
                var TRANSLATIONS = {
                    'Choose options': 'Выберите варианты',
                    'Choose or add options': 'Выберите или добавьте варианты',
                    'Choose an option': 'Выберите вариант',
                    'Choose or add an option': 'Выберите или добавьте вариант',
                    'Select all': 'Выбрать все',
                    'Select All': 'Выбрать все',
                    'Clear all': 'Снять выбор',
                    'Clear All': 'Снять выбор',
                    'Search': 'Поиск',
                    'No results': 'Нет результатов',
                    'No options': 'Нет вариантов',
                    'No matches': 'Нет совпадений',
                    'Choose a date range': 'Выберите диапазон дат',
                    'Past Week': 'Прошлая неделя',
                    'Past Month': 'Прошлый месяц',
                    'Past 3 Months': 'Последние 3 месяца',
                    'Past 6 Months': 'Последние 6 месяцев',
                    'Past Year': 'Последний год',
                    'Past 2 Years': 'Последние 2 года',
                    'None': 'Не выбрано',
                    /* Календарь — полные названия месяцев */
                    'January': 'Январь', 'February': 'Февраль', 'March': 'Март',
                    'April': 'Апрель', 'May': 'Май', 'June': 'Июнь',
                    'July': 'Июль', 'August': 'Август', 'September': 'Сентябрь',
                    'October': 'Октябрь', 'November': 'Ноябрь', 'December': 'Декабрь',
                    /* Календарь — сокращения дней недели (BaseWeb DatePicker) */
                    'Mo': 'Пн', 'Tu': 'Вт', 'We': 'Ср', 'Th': 'Чт',
                    'Fr': 'Пт', 'Sa': 'Сб', 'Su': 'Вс',
                    'Mon': 'Пн', 'Tue': 'Вт', 'Wed': 'Ср', 'Thu': 'Чт',
                    'Fri': 'Пт', 'Sat': 'Сб', 'Sun': 'Вс',
                    /* Кнопки навигации календаря */
                    'Previous Month': 'Предыдущий месяц',
                    'Next Month': 'Следующий месяц',
                    'Previous Year': 'Предыдущий год',
                    'Next Year': 'Следующий год',
                    /* st.dataframe / st.data_editor — контекстное меню столбца (Glide Data Grid) */
                    'Sort ascending': 'Сортировать по возрастанию',
                    'Sort descending': 'Сортировать по убыванию',
                    'Sort Ascending': 'Сортировать по возрастанию',
                    'Sort Descending': 'Сортировать по убыванию',
                    'Autosize': 'Автоподбор ширины',
                    'Auto-size': 'Автоподбор ширины',
                    'Auto size': 'Автоподбор ширины',
                    'Pin column': 'Закрепить столбец',
                    'Pin Column': 'Закрепить столбец',
                    'Unpin column': 'Открепить столбец',
                    'Unpin Column': 'Открепить столбец',
                    'Hide column': 'Скрыть столбец',
                    'Hide Column': 'Скрыть столбец',
                    'Format': 'Формат'
                };
                var MENU_PHRASE_KEYS = [
                    'Sort descending','Sort ascending','Sort Descending','Sort Ascending',
                    'Auto-size','Auto size','Autosize',
                    'Unpin column','Unpin Column','Pin column','Pin Column',
                    'Hide column','Hide Column','Format'
                ];
                var MONTH_RE = /^(January|February|March|April|May|June|July|August|September|October|November|December)\\s+(\\d{4})$/;
                var MONTHS_FULL = {
                    January:'Январь', February:'Февраль', March:'Март', April:'Апрель',
                    May:'Май', June:'Июнь', July:'Июль', August:'Август',
                    September:'Сентябрь', October:'Октябрь', November:'Ноябрь', December:'Декабрь'
                };
                var SELECT_N_RE = /^Select (\\d+) matches$/;
                function fixPlaceholders(root) {
                    try {
                        if (!root || !root.querySelectorAll) return;
                        root.querySelectorAll("[placeholder]").forEach(function (node) {
                            var p = node.getAttribute("placeholder");
                            if (!p) return;
                            var pt = p.trim();
                            var slo = pt.toLowerCase();
                            var keys = Object.keys(TRANSLATIONS);
                            for (var ai = 0; ai < keys.length; ai++) {
                                var key = keys[ai];
                                if (pt === key || slo === String(key).toLowerCase()) {
                                    node.setAttribute("placeholder", TRANSLATIONS[key]);
                                    break;
                                }
                            }
                        });
                    } catch (e) {}
                }
                function fixAriaLabels(root) {
                    try {
                        if (!root || !root.querySelectorAll) return;
                        root.querySelectorAll("[aria-label]").forEach(function (node) {
                            var p = node.getAttribute("aria-label");
                            if (!p) return;
                            var pt = p.trim();
                            var slo = pt.toLowerCase();
                            var keys = Object.keys(TRANSLATIONS);
                            for (var bi = 0; bi < keys.length; bi++) {
                                var key = keys[bi];
                                if (pt === key || slo === String(key).toLowerCase()) {
                                    node.setAttribute("aria-label", TRANSLATIONS[key]);
                                    break;
                                }
                            }
                        });
                    } catch (e2) {}
                }
                var MULTI_PATCH_PHRASES = [
                    ['Select All', 'Выбрать все'],
                    ['Select all', 'Выбрать все'],
                    ['select all', 'Выбрать все'],
                    ['Clear All', 'Снять выбор'],
                    ['Clear all', 'Снять выбор'],
                    ['clear all', 'Снять выбор']
                ];
                function patchMultiselectPhrases(raw) {
                    var glued = raw;
                    for (var pi = 0; pi < MULTI_PATCH_PHRASES.length; pi++) {
                        var src = MULTI_PATCH_PHRASES[pi][0];
                        var dst = MULTI_PATCH_PHRASES[pi][1];
                        if (!src || glued.indexOf(src) === -1) continue;
                        glued = glued.split(src).join(dst);
                    }
                    return glued;
                }
                function tr(node) {
                    if (node.nodeType !== 3) return;
                    var t = node.nodeValue;
                    if (!t) return;
                    var patchedMs = patchMultiselectPhrases(t);
                    if (patchedMs !== t) {
                        node.nodeValue = patchedMs;
                        return;
                    }
                    var s = t.trim();
                    if (!s) return;
                    var slo = s.toLowerCase();
                    var keys = Object.keys(TRANSLATIONS);
                    for (var ki = 0; ki < keys.length; ki++) {
                        var key = keys[ki];
                        if (s === key || slo === String(key).toLowerCase()) {
                            node.nodeValue = t.replace(s, TRANSLATIONS[key]);
                            return;
                        }
                    }
                    /* Контекстное меню столбца: фразы могут быть в одном узле с другим текстом */
                    var glued = t;
                    var mkOrder = MENU_PHRASE_KEYS.slice().sort(function(a,b){return String(b).length - String(a).length;});
                    for (var sj = 0; sj < mkOrder.length; sj++) {
                        var kk = mkOrder[sj];
                        var rv = TRANSLATIONS[kk];
                        if (!rv) continue;
                        if (glued.indexOf(kk) !== -1) glued = glued.split(kk).join(rv);
                    }
                    if (glued !== t) {
                        node.nodeValue = glued;
                        return;
                    }
                    var mm = s.match(MONTH_RE);
                    if (mm) {
                        node.nodeValue = t.replace(s, MONTHS_FULL[mm[1]] + ' ' + mm[2]);
                        return;
                    }
                    var m = s.match(SELECT_N_RE);
                    if (m) {
                        node.nodeValue = t.replace(s, 'Выбрать ' + m[1] + ' совпадений');
                    }
                }
                function walk(root) {
                    if (!root) return;
                    if (root.nodeType === 3) { tr(root); return; }
                    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
                    var w = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
                    var n;
                    while ((n = w.nextNode())) tr(n);
                }
                function walkDeep(root) {
                    if (!root) return;
                    if (root.nodeType === 3) {
                        tr(root);
                        return;
                    }
                    walk(root);
                    fixPlaceholders(root);
                    fixAriaLabels(root);
                }
                walkDeep(doc.body);
                try { hostWin[HANDLE_KEY] = {obs: null, tmr: null}; } catch (eH) {}
            } catch(e) { /* noop */ }
        })();
        </script>
        """,
        height=0,
    )


# Обратная совместимость с прежним именем в _renderers.
_inject_multiselect_ru_translations = inject_multiselect_ru_translations
