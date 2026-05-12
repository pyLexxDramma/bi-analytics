# XCA AI Chat Integration

Интеграционный проект для запуска бизнес-чата `XCA AI` на базе OpenCode, с UI на Streamlit и опциональным подключением к удаленному AI-серверу через SSH-туннель.

## Что делает проект

- Показывает главное меню Streamlit с кнопкой запуска чата.
- Открывает полноценный AI-чат (`XCA AI chat`) с историей сообщений и уточняющими вопросами.
- Поддерживает возврат в главное меню кнопкой `Назад`.
- Подключается к OpenCode:
  - напрямую по `OPENCODE_URL`, либо
  - через SSH-туннель (`ENABLE_SSH_TUNNEL=true`).
- Отдает web/API-шлюз через Node.js (`/api/v1/*`) для внешних сайтов.
- Использует DB-first аналитический контур (`web_data.db` + `analyze_db_*.py`) для ответов AI по данным проекта.

## Технологический стек

### Backend / Runtime

- `Python 3.x`
- `Streamlit` (UI и пользовательский сценарий чата)
- `requests` (HTTP-клиент к OpenCode API)
- `python-dotenv` (загрузка конфигурации из `.env`)
- `sshtunnel` + `paramiko<4` (SSH-туннель к удаленному OpenCode)
- `sqlite3` (локальная сессионная/служебная БД)

### Аналитика

- `pandas`
- `matplotlib`
- `SQLite` (`web_data.db`)
- Python-скрипты `workspace/analytics/analyze_db_*.py`

### Web/API слой

- `Node.js + Express` (`server.js`)
- REST API `/api/v1` для health, сессий, сообщений
- валидация, ограничение размера сообщений, rate-limit, proxy в OpenCode

### Инфраструктура

- `Docker` / `Docker Compose`
- три сервиса: `opencode`, `web`, `streamlit`

## Структура ключевых файлов

- `streamlit_app.py`  
  Тонкая точка входа: главное меню + переключение в чат.

- `ai_chat_app.py`  
  Основная логика чата: состояние, подключение, обработка событий, рендер сообщений, вопросы/ответы, диагностика.

- `server.js`  
  API-шлюз `/api/v1/*` поверх OpenCode для внешних интеграций.

- `docker-compose.yml`  
  Оркестрация сервисов `opencode`, `web`, `streamlit`.

- `requirements.web.txt`  
  Python-зависимости веб/чат-части.

- `workspace/AI_AGENT_GUIDE.md` и `workspace/analytics/KNOWLEDGE_BASE.md`  
  Правила и сценарии работы AI с данными.

## Как работает скрипт (пошагово)

### 1) Точка входа

`streamlit_app.py` запускает приложение и хранит флаг экрана в `st.session_state`:

- `show_ai_chat = False` -> показывается главное меню.
- `show_ai_chat = True` -> вызывается `ai_chat_app.main(...)`.

### 2) Переходы между экранами

- Кнопка `Открыть чат с ИИ` в главном меню включает экран чата.
- Кнопка `Назад` в чате вызывает callback, который возвращает в главное меню.

### 3) Инициализация чата

В `ai_chat_app.main(...)`:

1. Применяется тема и брендинг `XCA AI`.
2. Инициализируется `session_state`.
3. Выполняется healthcheck OpenCode.
4. Создается/выбирается активная чат-сессия.
5. Рендерятся история, элементы управления и поле ввода.

### 4) Подключение к OpenCode

Поддерживаются 2 режима:

1. **Прямой режим**
   - Используется `OPENCODE_URL`.
2. **SSH-режим**
   - При `ENABLE_SSH_TUNNEL=true` приложение поднимает туннель и использует
     `http://127.0.0.1:<AI_LOCAL_TUNNEL_PORT>`.

Логика подключения в:

- `open_ssh_tunnel()`
- `get_runtime_opencode_url()`

Диагностические события пишутся в сайдбар (`Диагностика подключения`).

### 5) Поток сообщения

1. Пользователь отправляет текст.
2. Текст валидируется и сохраняется в активной сессии.
3. Запрос уходит в OpenCode (асинхронный/потоковый сценарий).
4. При необходимости обрабатываются уточняющие вопросы (`question`).
5. Итоговый ответ ассистента отображается в чате и сохраняется в истории.

## Переменные окружения

Пример:

```env
ENABLE_SSH_TUNNEL=true
AI_SSH_HOST=<AI_SERVER_IP_OR_HOST>
AI_SSH_PORT=22
AI_SSH_USER=<SSH_USER>
AI_SSH_PASSWORD=<SSH_PASSWORD>
AI_OPENCODE_REMOTE_PORT=4096
AI_LOCAL_TUNNEL_PORT=4096
OPENCODE_URL=http://opencode:4096
WEB_AUTH_TOKEN=
```

### Назначение переменных

- `ENABLE_SSH_TUNNEL` — включает SSH-туннель.
- `AI_SSH_*` — реквизиты SSH-доступа к серверу с OpenCode.
- `AI_OPENCODE_REMOTE_PORT` — порт OpenCode на удаленном сервере.
- `AI_LOCAL_TUNNEL_PORT` — локальный порт, куда будет проброшен удаленный OpenCode.
- `OPENCODE_URL` — прямой URL OpenCode (если туннель не используется).
- `WEB_AUTH_TOKEN` — токен для API-слоя (`server.js`), если нужен.

## Запуск

### Вариант 1: локально (без Docker)

```bash
pip install -r requirements.web.txt
streamlit run streamlit_app.py --server.port 8501
```

### Вариант 2: через Docker Compose

```bash
docker compose up -d --build
```

По умолчанию:

- Streamlit: `http://127.0.0.1:8501`
- API/Web: `http://127.0.0.1:4098`
- OpenCode: loopback-публикация для туннеля (`127.0.0.1:<AI_OPENCODE_REMOTE_PORT>`)

## Интеграция в другой Streamlit-сайт

Используй тот же паттерн переключения экрана:

1. Добавь флаг `show_ai_chat` в `st.session_state`.
2. На кнопке открытия вызывай `render_ai_chat(on_back_requested=...)`.
3. В callback `on_back_requested` возвращай `show_ai_chat=False`.

Подробный интеграционный сценарий: `AI_INTEGRATION_GUIDE.md`.

## API-режим (для внешнего сайта)

`server.js` предоставляет единый REST-контракт:

- `GET /api/v1/health`
- `POST /api/v1/sessions`
- `POST /api/v1/chats/:sessionId/messages`
- `GET /api/v1/chats/:sessionId/messages?limit=50`

Ответы в формате:

- успех: `{ "ok": true, "data": {...} }`
- ошибка: `{ "ok": false, "error": {...} }`

## Диагностика и типовые проблемы

### Симптом: чат не отвечает

- Проверь health в сайдбаре (`XCA AI`).
- Проверь `OPENCODE_URL` или SSH-параметры.
- Убедись, что OpenCode поднят на нужном порту.

### Симптом: ошибка SSH-туннеля

- Проверь `AI_SSH_HOST/PORT/USER/PASSWORD`.
- Проверь, что локальный `AI_LOCAL_TUNNEL_PORT` не занят.
- Убедись, что установлен `paramiko<4`.

### Симптом: расхождения в аналитике

- Убедись, что используется `web_data.db`.
- Проверь актуальность скриптов `analyze_db_*.py` и active version в `web_versions`.

## Безопасность

- Не коммить `.env` с реальными паролями/токенами.
- Для прода используй секреты CI/CD или vault.
- Держи OpenCode и web-порт доступными только внутри trusted-сети (VPN/reverse-proxy).

## Минимальный чеклист перед релизом

1. `streamlit_app.py` открывает меню `XCA AI`.
2. Кнопка `Открыть чат с ИИ` открывает `XCA AI chat`.
3. Кнопка `Назад` возвращает в меню без ручного refresh.
4. Зеленый health в сайдбаре.
5. Отправка сообщения и получение ответа проходят стабильно.
