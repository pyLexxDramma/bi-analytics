# opencode_only

## Деплой

```bash
cd opencode_only
bash scripts/redeploy.sh
```

Сбрасывает volumes `opencode_config` и `opencode_share` (старый `steps` в global ломал чат).

## Проверка (обязательно)

```bash
docker exec xca-opencode verify_effective_agent.sh
```

Должно: `OK: xca.steps not set` и `agent.xca: ... steps=__UNSET__`.

Если `xca.steps=1` или `24` — на сервере **не обновлён** `workspace/opencode.json`.

## Дублирующиеся ответы (документация OpenCode)

Источник: https://opencode.ai/docs/agents/#max-steps

- Если задан `agent.*.steps`, при достижении лимита OpenCode вставляет `max-steps.txt` — **второе** сообщение с текстом «достигнут лимит шагов / оставшиеся задачи».
- Если `steps` **не задан**: «agent will continue to iterate until the model chooses to stop».

Исправление: **не задавать `steps`** у `xca` (скрипт `render_opencode_config.sh` удаляет его при старте).

## URL

`http://127.0.0.1:4096/L3dvcmtzcGFjZQ/`
