# Data Analysis Knowledge Base

**Полные правила:** `/workspace/AI_DATA_RULES.md` (обязательно `cat` перед аналитикой).  
**Типовые вопросы пользователей:** `/workspace/analytics/QUESTIONS_CATALOG.md` (какой скрипт и CSV на каждый вопрос из `questions.md`).

## Источник данных

- **`/workspace/web_data.db`** — таблицы `web_versions`, `web_files`, `web_data` (JSON в `row_data`).
- Проверка: `python3 /workspace/analytics/inspect_web_db.py` (не смотреть старые PNG/CSV в `output/`).
- Активная версия: `web_versions.is_active = 1` AND `status = success`.
- **Финансы и БДДС есть** в `file_type = reference_dannye` (1С обороты: ПЛАН/ФАКТ, БДДС, проект, контрагент, суммы в **тыс. руб.** → в скриптах ×1000).

## file_type

| file_type | Содержание |
|-----------|------------|
| `reference_dannye` | 1С: ПЛАН/ФАКТ, **БДДС**, проект, контрагент, статья, период |
| `debit_credit` | Авансы (ДК) |
| `project` | MSP (сроки, **причины отклонений по срокам**) |
| `resources`, `technique` | ГДРС |
| `tessa`, `tessa_tasks` | ИД |
| `rd_plan` | План РД |

## Главный скрипт финансов и БДДС

**`python /workspace/analytics/analyze_db_finance_plan_fact.py`**

| Запрос | CSV | PNG (если создан) |
|--------|-----|-----------------|
| План/факт по **проекту** | `plan_fact_by_project.csv` | `plan_fact_by_project.png` |
| План/факт по **подрядчику** | `plan_fact_by_contractor.csv` | — |
| **БДДС / динамика по месяцам** | `plan_fact_by_project_month.csv` | `plan_fact_bddds_monthly.png` |
| Недоосвоение **по статьям** | `plan_fact_by_article.csv` | — |
| Авансы | `advances_by_contractor.csv` | — |

Путь output: `/workspace/analytics/output/db_finance_plan_fact/`.  
В `diagnostics.csv` поля `chart_png`, `chart_png_monthly`, `synthetic_monthly_rows` — если `synthetic_monthly_rows > 0`, данные БДДС по месяцам **есть**.

## Сроки (не путать с финансами)

| Запрос | Скрипт | PNG |
|--------|--------|-----|
| Причины отклонений **по срокам** (MSP), доли | `analyze_db_deviations_for_chat.py` | `deviations_reasons_for_chat_pie.png` |
| Просрочки задач | `analyze_db_project_delays.py` | — |
| Отставание по блоку | `analyze_db_msp_by_block.py` | — |

**Не использовать** `analyze_db_deviations_for_chat.py` для вопросов про **бюджет/БДДС/рубли** — только MSP-сроки.

## Другие скрипты

| Скрипт | Назначение |
|--------|------------|
| `analyze_db_resources.py` | Ресурсы ГДРС |
| `analyze_db_prescriptions.py` | Предписания |
| `inspect_web_db.py` | Аудит ключей JSON |

Legacy `esipovo_deviations*`, CSV в `workspace/AI` — **не использовать**.

## Графики в ответе ИИ

Пока **не требуются** в обычных ответах. Строку с PNG добавляй только если пользователь явно просит график/диаграмму.
