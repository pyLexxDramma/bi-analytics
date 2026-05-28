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

if [[ -x .venv/bin/python ]]; then
  if ! .venv/bin/python -m pip --version &>/dev/null; then
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip-gha.py
    .venv/bin/python /tmp/get-pip-gha.py --no-warn-script-location
    rm -f /tmp/get-pip-gha.py
  fi
  .venv/bin/python -m pip install --quiet -r requirements.txt
elif [[ -x .venv/bin/pip ]]; then
  .venv/bin/pip install --quiet -r requirements.txt
elif python3 -m pip --version &>/dev/null; then
  python3 -m pip install --quiet -r requirements.txt
else
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip-gha.py
  python3 /tmp/get-pip-gha.py --user --no-warn-script-location
  rm -f /tmp/get-pip-gha.py
  python3 -m pip install --quiet -r requirements.txt
fi

if [[ "$UNIT" == "skip" || "$UNIT" == "none" ]]; then
  echo "SKIP: systemctl (DEPLOY_SYSTEMD_UNIT=skip|none)"
else
  LOAD="$(systemctl --user show "$UNIT" --property=LoadState --value 2>/dev/null || echo not-found)"
  if [[ "$LOAD" == "not-found" ]]; then
    echo "ERROR: unit не найден: $UNIT" >&2
    exit 5
  fi
  systemctl --user restart "${UNIT}"
  systemctl --user is-active "${UNIT}" >/dev/null
fi

echo "Deploy OK: $(git rev-parse --short HEAD) on $(hostname)"
