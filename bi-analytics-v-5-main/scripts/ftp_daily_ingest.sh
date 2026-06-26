#!/usr/bin/env bash
# Ежедневное FTP → web/ → SQLite после выгрузки файлов на FTP (07:00 МСК).
# Запуск на VPS: cron 15 7 * * * TZ=Europe/Moscow /path/to/ftp_daily_ingest.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SUBDIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_SUBDIR/.." && pwd)"

WORK_ROOT="$REPO_ROOT"
if [[ ! -f "$WORK_ROOT/streamlit_app.py" ]]; then
  WORK_ROOT="$APP_SUBDIR"
fi

PY="$WORK_ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

echo "[ftp_daily_ingest] $(date '+%Y-%m-%d %H:%M:%S %Z') start"
cd "$APP_SUBDIR"
"$PY" ingest_web_cli.py
echo "[ftp_daily_ingest] done"
