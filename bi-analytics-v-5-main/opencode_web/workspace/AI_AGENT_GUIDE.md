# AI Agent Data Guide (DB-first)

Этот файл определяет, как агенту работать с актуальными данными в режиме **DB-first**.

## Где лежат данные

- Основной источник истины: `web_data.db`:
  - `/workspace/web_data.db`
  - `/workspace/data/web_data.db`
  - `/workspace/analytics/web_data.db`
- Скрипты DB-аналитики: `/workspace/analytics/analyze_db_*.py`
- Выходные отчеты: `/workspace/analytics/output/**`

## Базовый workflow

1. Для быстрого ответа всегда сначала запускай:
   - `python /workspace/analytics/analyze_db_fast_answers.py`
2. Для детального разбора запускай профильный DB-скрипт по домену.
3. Используй `diagnostics.csv` и `data_inventory.csv` для проверки полноты источников.
4. Ответ формируй по цифрам из CSV-результатов, а не по предположениям.
5. Если данные неполные, указывай, каких типов файлов не хватает (`project/resources/tessa/reference_dannye/debit_credit`).

## Соответствие "запрос -> DB-скрипт"

- Быстрые сводки по всем доменам -> `analyze_db_fast_answers.py`
- MSP / сроки / долгие задачи -> `analyze_db_msp.py`
- MSP: здоровье проектов (KPI) -> `analyze_db_project_health.py`
- MSP: просрочки задач -> `analyze_db_project_delays.py`
- MSP: причины отклонений -> `analyze_db_delay_reasons.py`
- MSP: сводка отклонений для чата + круговая диаграмма -> `analyze_db_deviations_for_chat.py`
- Ресурсы и техника -> `analyze_db_resources.py`
- Подрядчики и ресурсная нагрузка -> `analyze_db_contractors.py`
- Реестр РД -> `analyze_db_rd_registry.py`
- TESSA (tasks/rd/id) -> `analyze_db_tessa.py`
- TESSA статусы/просрочки -> `analyze_db_tessa_overdue.py`
- Финансы 1C и ДК -> `analyze_db_finance.py`
- Финансы по сценариям -> `analyze_db_finance_scenarios.py`
- Аудит структуры БД и JSON-ключей -> `inspect_web_db.py`

## Ограничение режима

Использовать только DB-скрипты. Работа с `.csv` как с источником аналитики запрещена.
Запрещено использовать legacy-файлы из `/workspace/analytics/output/esipovo_deviations*` и любые старые отчеты вне DB-скриптов текущего запроса.
Перед ответом по отклонениям обязательно сначала заново запускать `analyze_db_deviations_for_chat.py`, даже если в output уже есть старые CSV/PNG.
