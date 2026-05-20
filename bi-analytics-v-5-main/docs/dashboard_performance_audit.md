# Аудит производительности дашбордов

Дата: 2026-05-20. Контекст: после ускорения «График проекта» (SQLite, лимиты, упрощение Plotly-annotations).

## Уже оптимизировано

| Механизм | Где |
|----------|-----|
| Загрузка данных из SQLite | `web_loader.read_version_to_session`, `project_visualization_app.py` |
| `st.fragment` для тела отчёта | `project_visualization_app.py` |
| График проекта: кэш фильтров, одна annotation/метка, лимит 60×1200 px (снятие — галочка) | `_renderers.py` ~31338–33180 |

## Топ-10 самых тяжёлых отчётов

### 1. График проекта
- **Функция:** `dashboard_project_schedule_chart` (~2000 строк)
- **Узкие места:** `iterrows` при сборке Gantt (`32589`), подготовка таблицы MSP (`30305`), множественные `.copy()` до фильтров, нет `@st.cache_data` на prep
- **Статус:** частично исправлено; полный режим (без лимита) осознанно медленнее

### 2. Прогнозный бюджет
- **Функция:** `dashboard_forecast_budget` (~2853 строки)
- **Узкие места:** `.copy()` до фильтров (`25692`), `max_height=None` (`26221`), `iterrows` в сводной таблице (`26408`), кэш только для `_load_dogovor_lookup`

### 3. Отклонение от базового плана
- **Функция:** `dashboard_plan_fact_dates` (~1870 строк, 38× `.copy()`)
- **Узкие места:** `filtered_df = df.copy()` (`6419`), Gantt через `iterrows` (`6814`), каскад копий chart/table (`6758`), без кэша

### 4. Причины отклонений
- **Функция:** `dashboard_deviations_combined` + 3 таба
- **Узкие места:** пересчёт каждого таба, `add_annotation` в stacked bar (`4681`, `5189–5221`), `.copy()` в подотчётах, без кэша

### 5. БДР
- **Функция:** `dashboard_bdr` (~1852 строки)
- **Узкие места:** `iterrows` по иерархии MSP (`10561`), `max_height=None` (`11219`, `11562`), `.copy()` до derive (`10518`)

### 6. БДДС
- **Функция:** `dashboard_budget_by_period` (~1037 строк)
- **Узкие места:** `_derive_bdds_dimensions` + `iterrows` (`8817`, `8851`), `max_height=None` (`9528`), без кэша на derive

### 7. ГДРС (люди / техника)
- **Функции:** `dashboard_gdrs` + `gdrs_resursi.py`
- **Узкие места:** HTML-матрица через `iterrows` (`gdrs_resursi.py:2271`), 4 графика без кэша; загрузка CSV кэшируется (`17994`)

### 8. Контрольные точки
- **Функции:** `dashboard_control_points` → `dev_projects_tz_matrix.py`
- **Узкие места:** `build_control_points_df`, `iterrows` на каждую ячейку вехи (`4115`), base64-панели, нет кэша на build

### 9. Девелоперские проекты
- **Функции:** `dashboard_developer_projects` → `dev_projects_tz_matrix.py`
- **Узкие места:** `build_dev_tz_matrix_rows` (тяжёлая матрица), HTML `iterrows` (`3815`, `4115`); session-cache смягчает только повторные прогоны

### 10. Рабочая / проектная документация
- **Функции:** `dashboard_working_documentation`, `dashboard_rd_delay`, `dashboard_pd_delay`
- **Узкие места:** `iterrows` для подписей bar chart (`12357`, `12905`), два таба, без кэша

## Повторяющиеся паттерны

| Паттерн | Примеры строк |
|---------|----------------|
| `max_height=None` на тяжёлых Plotly | БДДС `9528`, БДР `11219`/`11562`, Прогнозный бюджет `26221` |
| `iterrows` в рендере | Gantt, БДР derive, ГДРС HTML, КТ, РД |
| `.copy()` до фильтров | Отклонение `6419`, Прогнозный бюджет `25692`, БДР `10518` |
| Нет `@st.cache_data` на prep | большинство отчётов (кэш только в 6 местах `_renderers.py`) |

## Рекомендуемый порядок следующих правок

1. БДДС / БДР / Прогнозный бюджет — `max_height=900–1200` на finance charts
2. Отклонение от базового плана — кэш prep + vectorized Gantt вместо `iterrows`
3. ГДРС — кэш `build_main_table` и HTML-матрицы по hash df
4. Контрольные точки / Девелоперские — кэш `build_*_df`, lazy render ячеек
