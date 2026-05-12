# Интеграция XCA AI в основной Streamlit-сайт

Этот гайд для разработчика, который встраивает чат в другой Streamlit-проект.

## 1) Что уже реализовано в этом репозитории

- Полная логика чата находится в **`ai_chat_app.py`**.
- Точка входа с главным меню и кнопкой запуска чата находится в **`streamlit_app.py`**.
- Подключение к удаленному AI-серверу идет через SSH-туннель (если включен `ENABLE_SSH_TUNNEL=true`).
- Возврат из чата в главное меню реализован через callback `on_back_requested`.

## 2) Условия, при которых интеграция гарантированно рабочая

Ниже обязательные условия. Если все пункты выполнены, чат поднимется и будет работать стабильно:

1. На AI-сервере доступен SSH (`AI_SSH_HOST`, `AI_SSH_PORT`).
2. У пользователя SSH есть права на подключение (`AI_SSH_USER`, `AI_SSH_PASSWORD`).
3. На AI-сервере реально запущен OpenCode на `AI_OPENCODE_REMOTE_PORT` (обычно `4096`).
4. На стороне Streamlit установлены Python-зависимости из **`requirements.web.txt`**.
5. В `.env` корректно заполнены все переменные SSH и OpenCode URL.

## 3) Переменные окружения (`.env`)

Пример (значения подставить свои):

```env
ENABLE_SSH_TUNNEL=true
AI_SSH_HOST=<AI_SERVER_IP_OR_HOST>
AI_SSH_PORT=22
AI_SSH_USER=<SSH_USER>
AI_SSH_PASSWORD=<SSH_PASSWORD>
AI_OPENCODE_REMOTE_PORT=4096
AI_LOCAL_TUNNEL_PORT=4096
OPENCODE_URL=http://opencode:4096
```

### Важные правила

- `ENABLE_SSH_TUNNEL=true` для удаленного AI-сервера.
- `AI_LOCAL_TUNNEL_PORT` должен быть свободен на хосте Streamlit.
- `paramiko` должен быть версии `<4.0.0` (это уже зафиксировано в **`requirements.web.txt`**).

## 4) Как проверить порт OpenCode на сервере

На AI-сервере:

```bash
ss -lntp | rg opencode
```

Дополнительно:

```bash
rg "OPENCODE_PORT|opencode serve|--port" docker-compose.yml Dockerfile* entrypoint.sh .env
```

## 5) Быстрый старт локально

```bash
pip install -r requirements.web.txt
streamlit run streamlit_app.py --server.port 8501
```

После запуска:

- главное меню (`XCA AI`) содержит кнопку **`Открыть чат с ИИ`**;
- в чате (`XCA AI chat`) есть кнопка **`Назад`** для возврата в меню.

## 6) Как встроить в другой Streamlit-проект

Минимальный шаблон:

```python
import streamlit as st
from ai_chat_app import main as render_ai_chat

SHOW_CHAT_KEY = "show_ai_chat"


def open_chat() -> None:
    st.session_state[SHOW_CHAT_KEY] = True


def back_to_menu() -> None:
    st.session_state[SHOW_CHAT_KEY] = False


if SHOW_CHAT_KEY not in st.session_state:
    st.session_state[SHOW_CHAT_KEY] = False

if st.session_state[SHOW_CHAT_KEY]:
    render_ai_chat(on_back_requested=back_to_menu)
else:
    st.title("Главное меню")
    if st.button("Открыть чат с ИИ"):
        open_chat()
        st.rerun()
```

## 7) Проверочный чеклист перед релизом

1. Health в сайдбаре чата зеленый (`XCA AI` доступен).
2. Создается новая сессия и отправляется сообщение.
3. Возвращение по кнопке `Назад` работает без перезагрузки страницы вручную.
4. После рестарта Streamlit туннель поднимается автоматически.
5. В логах подключения нет ошибок `DSSKey` и `connection refused`.

## 8) Где смотреть диагностику

- Внутри чата открой блок **`Диагностика подключения`** в сайдбаре.
- Там отображаются этапы: резолв backend URL, подключение SSH-туннеля, статус healthcheck.

## 9) Полная настройка: чат (`opencode_web`) + кнопка в основном BI

Два независимых процесса: **чат** (этот каталог) и **дашборд BI** (родительский `project_visualization_app`). Переменные не смешивайте в один файл без понимания, кто их читает.

### Шаг A — поднять XCA AI (чат)

1. Создай **`opencode_web/.env`** из **`env.example`** и заполни блок SSH/OpenCode из раздела 3 (или оставь `ENABLE_SSH_TUNNEL=false`, если OpenCode уже доступен локально по `OPENCODE_URL`).
2. Установи зависимости: `pip install -r requirements.web.txt` (из каталога **`opencode_web`**).
3. Запуск: `streamlit run streamlit_app.py --server.port 8501` (порт любой свободный).
4. Открой в браузере `http://localhost:8501`, проверь чеклист из раздела 7.

### Шаг B — правила ответа (`AI_ASSISTANT_RULES.md`)

Файл **`AI_ASSISTANT_RULES.md`** задаёт бизнес-стиль ответов; его подхватывает **`ai_chat_app.py`** при старте.

- В Docker/сервере с примонтированным **`/workspace`**: положи копию правил в **`/workspace/AI_ASSISTANT_RULES.md`** или задай **`AI_ASSISTANT_RULES_PATH`** в **`opencode_web/.env`** на реальный путь к `.md`.
- Локально на Windows, если нет каталога **`/workspace`**: в **`opencode_web/.env`** укажи, например:  
  `AI_ASSISTANT_RULES_PATH=D:/.../opencode_web/AI_ASSISTANT_RULES.md`  
  (абсолютный путь к файлу из репозитория).

### Шаг C — кнопка «ИИ помощник» в сайдбаре BI

В **окружении процесса основного BI** (или в **`st.secrets`**) задай публичный URL, по которому пользователи открывают чат в браузере:

```env
AI_ASSISTANT_URL=http://<хост-где-крутится-чат>:8501/
```

Подойдут и синонимы: **`XCA_AI_CHAT_URL`**, **`AI_CHAT_PUBLIC_URL`** (см. `config.get_ai_assistant_open_url()`).  
Важно: это **не** `http://opencode:4096` с хоста пользователя — только адрес **Streamlit-чата**, который ты поднял в шаге A (или reverse-proxy перед ним).

### Краткий чеклист

| Где | Что задать |
|-----|------------|
| `opencode_web/.env` | SSH-туннель и `OPENCODE_URL` (раздел 3), при необходимости `AI_ASSISTANT_RULES_PATH` |
| `.env` / secrets **BI** | `AI_ASSISTANT_URL` = URL из шага A (видимый из браузера) |

### Запуск BI через корневой `streamlit_app.py` (ветки **main** / **release**)

Точка входа в корне репозитория (`streamlit_app.py`) делает `chdir` во вложенный каталог и запускает `project_visualization_app.py` — сайдбар и кнопка те же. Переменные подхватываются из **двух** файлов (если есть оба): сначала **`.env` рядом с корневым `streamlit_app.py`**, затем **`bi-analytics-v-5-main/.env`** (второй перекрывает совпадающие ключи). Удобно для Streamlit Cloud: один `.env` или secrets в панели.

### Деплой на свой домен (например `http://ai.conall.ru`)

`AI_ASSISTANT_URL` должен быть **полным URL чата**, который браузер пользователя открывает с интернета: тот же хост/путь, что у развёрнутого `opencode_web`/Streamlit чата (или отдельный поддомен). Пример: `https://chat.example.com/` или `https://ai.conall.ru:8501/` если чат слушает этот порт снаружи. Дашборд и чат могут быть на одном хосте — тогда укажи порт/путь чата явно; относительный путь без домена в `link_button` не подойдёт.

## 10) Ветки **main** / **release** и Streamlit Community Cloud: ИИ не на ПК, а в облаке

Цель: **OpenCode и Qwen/vLLM** крутятся на **сервере команды** (или у клиента позже); на Streamlit Cloud идут только **лёгкие** процессы Streamlit (дашборд BI и UI чата). На ноутбуке разработчика **ничего слушать на 4096 не обязано**.

### Два приложения в одном репозитории (рекомендуется)

| Приложение в Cloud | Main file path | Requirements (Advanced) |
|--------------------|----------------|-------------------------|
| **BI (дашборды)** | `streamlit_app.py` | по умолчанию корневой `requirements.txt` |
| **XCA AI chat** | `bi-analytics-v-5-main/opencode_web/streamlit_app.py` | `requirements-opencode-chat.txt` (в корне репозитория) |

У каждого приложения свой URL вида `https://*.streamlit.app`. В **secrets** приложения BI задай `AI_ASSISTANT_URL` = **публичный URL второго приложения** (чата).

В **secrets** приложения чата задай переменные из раздела 3 (как минимум для удалённого OpenCode):

- `ENABLE_SSH_TUNNEL` = `true`
- `AI_SSH_HOST`, `AI_SSH_PORT`, `AI_SSH_USER`, `AI_SSH_PASSWORD`
- `AI_OPENCODE_REMOTE_PORT`, `AI_LOCAL_TUNNEL_PORT`, `OPENCODE_URL` (часто `http://opencode:4096` только внутри Docker; для Cloud через SSH — см. раздел 3: туннель до `127.0.0.1:4096` **на сервере**, куда вы подключаетесь по SSH)

Процесс чата на Cloud при старте поднимает **SSH-туннель** к вашему AI-серверу и шлёт HTTP на локальный порт туннеля — **это выполняется в облаке Streamlit**, не на ПК.

### Ветки main и release

В панели Streamlit Cloud для **каждого** из двух приложений можно выбрать ветку (**main** или **release**). Обычно оба приложения вешают на одну ветку; для предрелиза — чат на `release`, BI на `main` и т.д., по политике команды.

### Позже: сервер клиента

Тот же split: контейнеры/VM с **OpenCode** + отдельный сервис **Streamlit чата** (`opencode_web`) и **Streamlit BI**; в env клиента — публичные URL и секреты SSH/токены без хранения в Git. Кнопка в BI по-прежнему только открывает `AI_ASSISTANT_URL`.

### 11) Как «правильно» с точки зрения архитектуры

**Инвариант:** после установления SSH-сессии чат ходит в OpenCode по адресу **`127.0.0.1:<AI_OPENCODE_REMOTE_PORT>` на той же удалённой машине**, куда вы подключились (`AI_SSH_HOST`). Там **обязан** слушать HTTP API OpenCode (проверка: `ss -lntp | grep ':4096'` или ваш порт).

| Слой | Где крутится | Зачем |
|------|----------------|------|
| **BI** | `streamlit_app.py` (Cloud или сервер клиента) | Дашборды; кнопка «ИИ помощник» → `AI_ASSISTANT_URL` |
| **Чат** | `opencode_web/streamlit_app.py` | UI; SSH-туннель (если включён) и запросы к OpenCode |
| **OpenCode + модели** | Обычно **тот же хост**, что и `AI_SSH_HOST`, либо отдельный сервер с опубликованным портом | Бэкенд `/session`, health и т.д. |

**Типичная ошибка:** SSH на хост **A**, а OpenCode ждут на **A**, но на **A** порт **4096** не открыт (как на `dash-ai-01`, где есть только Streamlit BI на **8501**). Решения: **поднять OpenCode на A** или **сменить `AI_SSH_*` на хост B**, где OpenCode реально слушает `127.0.0.1:4096`.

**Сейчас (main / release, Streamlit Cloud):** два приложения из одного репозитория (раздел 10), ветку можно выбрать **одинаково** для BI и чата или разнести по политике. Секреты **разные**: у BI — в основном `AI_ASSISTANT_URL`; у чата — SSH и порты OpenCode.

**У клиента в проде:** всё на их инфраструктуре: reverse-proxy (HTTPS) → два процесса Streamlit (или один хост, два порта) + OpenCode (часто Docker). Те же переменные, что в secrets Cloud, переносятся в **`.env` / vault** на сервере, без Git.
