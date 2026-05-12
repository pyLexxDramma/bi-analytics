#!/usr/bin/env bash
# Запуск на сервере: git pull ветки release, зависимости, перезапуск Streamlit (systemd --user).
set -euo pipefail

if [[ -n "${DEPLOY_APP_DIR:-}" ]]; then
  APP_DIR="${DEPLOY_APP_DIR}"
else
  APP_DIR="${HOME}/apps/bi-analytics"
fi
UNIT="${DEPLOY_SYSTEMD_UNIT:-bi-analytics.service}"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

cd "${APP_DIR}"

git fetch origin
git checkout release
git pull --ff-only origin release

if [[ -x .venv/bin/pip ]]; then
  .venv/bin/pip install --quiet -r requirements.txt
elif command -v python3 >/dev/null 2>&1; then
  python3 -m pip install --quiet -r requirements.txt
else
  echo "ERROR: нет .venv/bin/pip и нет python3" >&2
  exit 1
fi

systemctl --user restart "${UNIT}"
systemctl --user is-active "${UNIT}" >/dev/null

echo "Deploy OK: $(git rev-parse --short HEAD) on $(hostname)"
