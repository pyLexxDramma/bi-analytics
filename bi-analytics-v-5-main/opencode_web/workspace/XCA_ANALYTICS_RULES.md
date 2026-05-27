# XCA AI — жёсткие правила аналитики (OpenCode)

## База данных

- Файл: **`/workspace/web_data.db`** (если нет — см. `SYNC_WEB_DATA.md`, не гадай).
- Проверка перед аналитикой:
  ```bash
  ls -lh /workspace/web_data.db
  python3 /workspace/analytics/inspect_web_db.py
  cat /workspace/analytics/output/db_inspect/diagnostics.csv
  ```
- Если `inspect_web_db.py` падает с `FileNotFoundError` — ответ пользователю: «База не загружена на сервер ИИ», без анализа output/.

## Запрещено

- Брать цифры из **`/workspace/analytics/output/`** (старые CSV/PNG) без **нового** запуска `analyze_db_*.py` в этом запросе.
- Смотреть PNG в output как источник фактов.
- Перечислять файлы в output вместо запуска скрипта.
- Писать пользователю **Goal**, **Next Steps**, **Constraints**, **Progress**, **Critical Context**, «лимит шагов», команды и пути разработки.
- После **автосжатия** контекста — кратко сообщить пользователю и рекомендовать **новую сессию** (проект + вопрос).
- Говорить «база пуста», пока не выполнен `inspect_web_db.py` и не прочитан `diagnostics.csv`.

## Обязательный порядок (каждый запрос с цифрами)

1. `cat` → `AI_DATA_RULES.md`, `KNOWLEDGE_BASE.md`, `QUESTIONS_CATALOG.md`
2. `python3 /workspace/analytics/<скрипт>.py`
3. `cat` → `diagnostics.csv` и нужный CSV из output **этого** запуска
4. Ответ человеку: вывод + цифры (до 15 строк таблицы при необходимости)

## Список проектов

- Скрипт: `analyze_db_finance_plan_fact.py` → `plan_fact_by_project.csv`
- Или `inspect_web_db.py` → `active_version_files.csv` (не output/*.png)
