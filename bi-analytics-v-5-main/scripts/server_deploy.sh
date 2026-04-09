#!/usr/bin/env bash
# Run on the VPS inside the app directory (clone of this repo).
# Usage: ./scripts/server_deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/venv/bin/python"
PIP="${ROOT}/venv/bin/pip"

if [[ ! -x "$PY" ]]; then
  echo "Creating venv..."
  python3 -m venv "${ROOT}/venv"
fi

"$PIP" install --upgrade pip -q
"$PIP" install -r requirements.txt -q

echo "Ingesting web/ -> data/web_data.db ..."
"$PY" ingest_web_cli.py

# Optional: set in /etc/default/bi-analytics or Environment= in systemd unit
# DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD — only for first start if users.db missing

if command -v systemctl >/dev/null 2>&1; then
  # Requires passwordless sudo for this unit in CI, or run the script as root / with tty.
  sudo systemctl restart bi-analytics
  sudo systemctl --no-pager -l status bi-analytics
else
  echo "systemctl not found; start manually: venv/bin/streamlit run project_visualization_app.py ..."
fi

echo "Deploy finished."
