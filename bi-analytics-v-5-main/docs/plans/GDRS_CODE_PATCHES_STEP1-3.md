# Патчи ГДРС (шаги 1–3) — применять при выключенном Plan mode

Файл: `dashboards/_renderers.py`.

## Шаг 1 — Отклонение = План − Факт

1. Заменить комментарий и строку после ветки без колонки «Дельта» (~12543):

```python
    else:
        # Отклонение по правкам заказчика (PDF ГДРС): План − Факт (Факт ≈ week_sum / СКУД).
        work_df["Дельта_numeric"] = work_df["План_numeric"] - work_df["week_sum"]
```

2. После пересчёта при суточных колонках (~12854–12855):

```python
        if "Дельта_numeric" in filtered_df.columns:
            filtered_df["Дельта_numeric"] = filtered_df["План_numeric"] - filtered_df["week_sum"]
```

3. В эталонной таблице (~13066–13067):

```python
            _ref["Отклонение"] = _ref["План"] - _ref["СКУД"]
```

4. В `_agg_block` (~13096–13097):

```python
                _dev = float(_plan - _skud)
```

## Шаг 2 — Заголовки «ГДРС»

В `dashboard_technique_tabs` / `dashboard_gdrs_equipment` (~14462–14474):

```python
def dashboard_technique_tabs(df):
    st.header("ГДРС")
    st.caption("График движения рабочей силы · рабочие")
    dashboard_workforce_movement(...)

def dashboard_gdrs_equipment(df):
    st.header("ГДРС")
    st.caption("График движения рабочей силы · техника")
    dashboard_workforce_movement(...)
```

В HTML эталонной таблицы заменить текст заголовка таблицы (~13197):

- было: `График движения рабочей силы (люди)`
- стало: строка по `_gdrs_tab_is_tech`: `ГДРС — техника` / `ГДРС — рабочие`

Подпись колонки «Дельта (%)» в `<th>` (~13206): **`(отклонение %)`** (данные по-прежнему можно держать в колонке `_view["Дельта (%)"]`).

## Шаг 3 — фильтр по колонке признака (аналог столбца H)

После функции `_format_gdrs_period_range_dd_mm_yyyy` добавить хелпер:

```python
def _gdrs_detect_csv_resource_kind_column(pdf: pd.DataFrame) -> Optional[str]:
    """Колонка признака «Рабочие / Техника» в CSV (PDF: столбец H)."""
    if pdf is None or getattr(pdf, "empty", True):
        return None
    exclude_lc = {
        "проект", "контрагент", "период", "план", "факт", "скуд",
        "data_source", "тип ресурсов", "вид работы", "вид работ",
        "__source_file", "snapshot_date",
    }
    best_c = None
    best_score = 0.0
    for c in pdf.columns:
        cl = str(c).strip().lower()
        if cl in exclude_lc or _gdrs_header_is_dd_mm_yyyy(c):
            continue
        raw = pdf[c].astype(str).str.strip()
        ser = raw.str.casefold().replace({"nan": "", "none": ""})
        ser = ser[ser.ne("")]
        if ser.empty:
            continue
        uniq = ser.unique().tolist()
        if len(uniq) > 14:
            continue
        u = set(uniq)
        score = 0.0
        if any("рабоч" in v for v in u):
            score += 3.0
        if any("тех" in v for v in u):
            score += 3.0
        if any(v in {"ресурсы", "ресурс", "люди"} for v in u):
            score += 1.0
        if 2 <= len(u) <= 10:
            score += 1.0
        if score > best_score:
            best_score = score
            best_c = str(c)
    return best_c if best_score >= 4.0 else None
```

Перед `col1, col2, col3 = st.columns(3)` в `dashboard_workforce_movement` вставить блок `selectbox` «Вид ресурсов (по файлу)» и фильтрацию `work_df` — см. полный текст в чате агента или повторите запрос в **Agent mode**.

## Шаг 4 — docs

Обновить `docs/логика/16_ГДРС_рабочие.md`: **Отклонение = План − Факт** (как в PDF); пометить прежнюю формулу как устаревшую при необходимости.

---

После правок: `python -m py_compile dashboards/_renderers.py` и ручная проверка отчётов «ГДРС» / «ГДРС Техника».
