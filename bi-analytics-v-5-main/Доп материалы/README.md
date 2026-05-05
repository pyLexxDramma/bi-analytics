# Дополнительные материалы (не часть runtime приложения)

Содержимое перенесено при наведении порядка в локальной копии: артефакты проверок, вспомогательные скрипты Playwright, одноразовые скриншоты из `web/`, папка `tools/` (FTP-утилита и т.п.).

**Не переносилось и не удалялось:** код приложения, `dashboards/`, `web/*.csv` и эталонные JSON/CSV для сверки, `docs/DEV_PROJECTS_QA_VERIFICATION_PLAN.md`, `docs/DEV_PROJECTS_TZ_MATRIX_CHECKLIST.md`, `venv/`.

Структура (по мере переноса):

- `tools/` — прежний каталог `bi-analytics-v-5-main/tools/`
- `scripts_qa/` — необязательные скрипты e2e/проверок дашбордов
- `web_tmp_qa/` — `_tmp*` и служебные PNG из `web/`
- `out_repo_visual_check_out/` — копия/перенос `_visual_check_out` из корня внешнего репозитория (если есть)

Для Git: каталог игнорируется, кроме этого `README.md`.
