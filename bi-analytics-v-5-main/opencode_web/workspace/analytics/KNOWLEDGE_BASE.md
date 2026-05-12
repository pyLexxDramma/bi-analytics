# Data Analysis Knowledge Base (DB-first)

Используй этот файл как карту работы с `web_data.db` и DB-скриптами.

## Основной источник данных

- Главный источник: SQLite `web_data.db`.
- Путь задается аргументом `--db` или ищется автоматически в:
  - `/workspace/web_data.db`
  - `/workspace/data/web_data.db`
  - `/workspace/analytics/web_data.db`

## Структура БД

- `web_versions` — версии загрузок (status, files_count, rows_count, is_active)
- `web_files` — мета-файлы версии (file_type, file_name, rel_path, rows_count)
- `web_data` — построчные данные:
  - `version_id`
  - `file_type`
  - `source_file`
  - `row_data` (JSON-строка)

## Готовые DB-скрипты (Python-only)

- `python /workspace/analytics/analyze_db_fast_answers.py`
  - Быстрый пакет: inventory + msp/resources/rd.
- `python /workspace/analytics/analyze_db_msp.py`
  - MSP: прогресс и долгие открытые задачи.
- `python /workspace/analytics/analyze_db_project_health.py`
  - KPI здоровья проектов (open share, long open).
- `python /workspace/analytics/analyze_db_project_delays.py`
  - Детализация просрочек по задачам.
- `python /workspace/analytics/analyze_db_delay_reasons.py`
  - Частоты причин отклонений по проектам.
- `python /workspace/analytics/analyze_db_deviations_for_chat.py`
  - Каноническая сводка отклонений для чата + круговая диаграмма по причинам.
- `python /workspace/analytics/analyze_db_resources.py`
  - Ресурсы/техника.
- `python /workspace/analytics/analyze_db_contractors.py`
  - Снимок по подрядчикам и средней нагрузке.
- `python /workspace/analytics/analyze_db_rd_registry.py`
  - Реестр РД.
- `python /workspace/analytics/analyze_db_tessa.py`
  - TESSA tasks / RD / ID.
- `python /workspace/analytics/analyze_db_tessa_overdue.py`
  - Распределение TESSA по статусам/объектам.
- `python /workspace/analytics/analyze_db_finance.py`
  - 1C dannye и DK.
- `python /workspace/analytics/analyze_db_finance_scenarios.py`
  - Агрегация сумм по сценариям/периодам.
- `python /workspace/analytics/inspect_web_db.py`
  - Аудит структуры БД и JSON-ключей.

## Правила выбора скрипта

1. По умолчанию сначала `analyze_db_fast_answers.py`.
2. По домену:
   - MSP -> `analyze_db_msp.py` / `analyze_db_project_health.py` / `analyze_db_project_delays.py`
   - Причины отклонений -> `analyze_db_deviations_for_chat.py` (в первую очередь), затем `analyze_db_delay_reasons.py`
   - Ресурсы/техника -> `analyze_db_resources.py` / `analyze_db_contractors.py`
   - РД -> `analyze_db_rd_registry.py`
   - TESSA -> `analyze_db_tessa.py` / `analyze_db_tessa_overdue.py`
   - Финансы -> `analyze_db_finance.py` / `analyze_db_finance_scenarios.py`
3. При странном результате сначала `inspect_web_db.py`.

## Ограничение режима

Работаем только с `web_data.db` через `analyze_db_*.py`.
Сценарии с `.csv` как основным источником отключены.
Legacy-выгрузки `output/esipovo_deviations*` не использовать для ответов.
Перед ответом по отклонениям всегда пересоздавать свежие файлы через `analyze_db_deviations_for_chat.py`.
