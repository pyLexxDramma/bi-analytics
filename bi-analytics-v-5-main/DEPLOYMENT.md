# Deployment Guide

## Why Vercel Doesn't Work

Vercel is designed for static sites and serverless functions, not for long-running Python applications like Streamlit. Streamlit requires a persistent Python server, which doesn't fit Vercel's deployment model.

## Recommended: Streamlit Cloud (Free & Easy)

Streamlit Cloud is the easiest and most appropriate option for deploying Streamlit applications.

### Steps to Deploy on Streamlit Cloud:

1. **Push your code to GitHub** (if not already done):
   ```bash
   git push origin master
   ```

2. **Sign up for Streamlit Cloud**:
   - Go to https://share.streamlit.io/
   - Sign in with your GitHub account

3. **Deploy your app**:
   - Click "New app"
   - Select your repository: `mk-im/bi-analytics`
   - Select branch: `master`
   - Main file path: `project_visualization_app.py`
   - Click "Deploy!"

4. **Your app will be live** at: `https://your-app-name.streamlit.app`

## Alternative Deployment Options

### 1. Render (Free Tier Available)
- Go to https://render.com
- Create a new Web Service
- Connect your GitHub repository
- Build command: `pip install -r requirements.txt`
- Start command: `streamlit run project_visualization_app.py --server.port $PORT --server.address 0.0.0.0`

### 2. Railway (Free Trial)
- Go to https://railway.app
- Create a new project from GitHub
- Add a Python service
- Railway will auto-detect and deploy

### 3. Heroku (Paid, but has free alternatives)
- Requires a `Procfile` with: `web: streamlit run project_visualization_app.py --server.port=$PORT --server.address=0.0.0.0`
- Requires `setup.sh` for Streamlit configuration

### 4. DigitalOcean App Platform
- Similar to Render, supports Python apps
- Paid service with free trial

## Files Created for Deployment

- `requirements.txt` - Python dependencies (required for all platforms)
- `.streamlit/config.toml` - Streamlit configuration for headless deployment

## Secrets and first admin

- **No keys or passwords are stored in the repository.** Set them in the deployment environment.
- To create the initial superadmin on first run, set environment variables:
  - `DEFAULT_ADMIN_USERNAME` — login for the first admin
  - `DEFAULT_ADMIN_PASSWORD` — password (set only in env / secrets, never in code)
- Copy `.env.example` to `.env` for local runs; for Streamlit Cloud / Render / Railway, use the platform's "Secrets" or "Environment variables" UI.

## Notes

- All platforms require your code to be in a Git repository (GitHub, GitLab, or Bitbucket)
- Make sure `requirements.txt` is in the root of your repository
- The main Streamlit file should be clearly named (e.g., `project_visualization_app.py`)

---

## VPS (закрытый контур, например ai.conall.ru)

На своём сервере доступны **файлы отчётов** на диске: приложение использует `web/` и CLI `ingest_web_cli.py` для `data/web_data.db`. Для такой схемы удобна связка **Linux + systemd + nginx** и деплой из Git.

### Один раз на сервере

1. Установите `git`, `python3`, `python3-venv`, при необходимости `nginx`.
2. Клонируйте репозиторий в каталог деплоя (пример `/opt/bi-analytics`), владелец — пользователь запуска (например `dashai`).
3. При необходимости задайте переменные окружения: см. `scripts/etc-default-bi-analytics.example` → `/etc/default/bi-analytics`, `chmod 600`. Первый вход: после инициализации БД в коде создаётся `admin` / `admin123` — пароль смените в интерфейсе.
4. Скопируйте `scripts/bi-analytics.service` в `/etc/systemd/system/`, поправьте `User`, `WorkingDirectory`, пути в `ExecStart`, затем `systemctl daemon-reload`, `enable`, `start`.
5. Nginx: `scripts/nginx-bi-analytics.conf.example` — прокси на `127.0.0.1:8501`, для Streamlit нужны заголовки WebSocket `Upgrade` и `Connection`.
6. Обновление: из корня клона `./scripts/server_deploy.sh` (venv, `pip`, ingest, `systemctl restart bi-analytics`).

`users.db` и другие `*.db` не в Git — на проде делайте **бэкап** `users.db` перед рискованными операциями. **SSH:** вход по ключу; пароли не коммитьте.

### FTP → папка `web/`

В интерфейсе: **Источник данных → FTP → web/**. Файлы скачиваются в `web/`, затем вызывается та же загрузка, что и для локальной папки.

**Продакшен-контур (сервера dash-ai):** доступ к выгрузкам CSV обычно через **FTP** к хосту **`web.conall.ru`**, пользователь **`ftp-ai`** (пароль выдаётся администратором, в Git не класть). Проверка с терминала: `ftp ftp-ai@web.conall.ru` или интерактивно `open web.conall.ru`, затем логин `ftp-ai`.

Каталог **`remote_dir`** должен совпадать с тем, куда на FTP попадают файлы (часто **`/`** или домашний chroot пользователя — уточните при необходимости у админа).

**Streamlit Cloud / локально — secrets** (файл `.streamlit/secrets.toml`, не коммитить):

```toml
[ftp]
host = "web.conall.ru"
user = "ftp-ai"
password = "УКАЖИТЕ_ПАРОЛЬ_В_SECRETS_UI"
remote_dir = "/"
# port = 21
# use_tls = false
```

**Сервер (systemd / docker):** переменные `BI_FTP_HOST=web.conall.ru`, `BI_FTP_USER=ftp-ai`, `BI_FTP_PASSWORD`, при необходимости `BI_FTP_REMOTE_DIR`, `BI_FTP_PORT`, `BI_FTP_TLS=true`, `BI_FTP_TIMEOUT=60`.

CLI без браузера: `python ftp_sync.py` (после активации venv), затем `python ingest_web_cli.py`.

### Роли и отчёты (RBAC)

В `auth.py`: словари **`_ROLE_REPORT_DENYLIST`** (роль → имена отчётов, которые скрыть) и **`_REPORT_ROLE_ALLOWLIST`** (отчёт → только эти роли; `admin`/`superadmin` всегда видят всё). Пустые `frozenset()` = без ограничений. Сверка колонок с ТЗ: `bi_analytics_report_mapping.md` (в репозитории/соседней папке аналитики) и блок **«Диагностика колонок»** после загрузки из `web/`.

### Автодеплой после push

Файл `.github/workflows/deploy-vps.yml`. В GitHub → **Settings → Secrets and variables → Actions**: `VPS_HOST`, `VPS_USER`, `VPS_PORT`, `VPS_SSH_KEY`, `VPS_DEPLOY_PATH`. На сервере нужны права на `git pull` и перезапуск сервиса (см. комментарии в `server_deploy.sh` и при необходимости `sudoers`).















