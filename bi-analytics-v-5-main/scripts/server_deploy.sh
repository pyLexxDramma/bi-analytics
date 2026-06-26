#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SUBDIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_SUBDIR/.." && pwd)"

WORK_ROOT="$REPO_ROOT"
if [[ ! -f "$WORK_ROOT/streamlit_app.py" ]]; then
  WORK_ROOT="$APP_SUBDIR"
fi
cd "$WORK_ROOT"
echo "WORK_ROOT=$WORK_ROOT"

PY="$WORK_ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Creating .venv in $WORK_ROOT"
  python3 -m venv "$WORK_ROOT/.venv"
  PY="$WORK_ROOT/.venv/bin/python"
fi
echo "PY=$PY"

REQ="$WORK_ROOT/requirements.txt"
if [[ ! -f "$REQ" ]]; then
  REQ="$APP_SUBDIR/requirements.txt"
fi
if [[ ! -f "$REQ" ]]; then
  echo "ERROR: requirements.txt not found"
  exit 1
fi
echo "REQ=$REQ"

"$PY" -m pip install --upgrade pip -q
"$PY" -m pip install -r "$REQ" -q
echo "OK: pip install"

if [[ "${BI_DEPLOY_SKIP_INGEST:-0}" == "1" ]]; then
  echo "SKIP: ingest"
elif [[ -f "$APP_SUBDIR/ingest_web_cli.py" ]]; then
  set +e
  (cd "$APP_SUBDIR" && "$PY" ingest_web_cli.py)
  ingest_rc=$?
  set -e
  if [[ "$ingest_rc" -ne 0 ]]; then
    echo "WARN: ingest exited $ingest_rc"
    if [[ "${BI_DEPLOY_FAIL_ON_INGEST:-0}" == "1" ]]; then
      exit "$ingest_rc"
    fi
  else
    echo "OK: ingest"
  fi
fi

if [[ "${BI_DEPLOY_SKIP_SYSTEMD:-0}" == "1" ]]; then
  echo "SKIP: systemd (BI_DEPLOY_SKIP_SYSTEMD=1)"
  echo "Deploy finished (code + deps)."
  exit 0
fi

UNIT="${BI_SYSTEMD_UNIT:-bi-analytics.service}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

echo "Restarting $UNIT ..."
systemctl --user stop "$UNIT" 2>/dev/null || true
sleep 2

if command -v ss >/dev/null 2>&1; then
  stale_pids="$(ss -tlnp 2>/dev/null | grep ':8501 ' | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true)"
  if [[ -n "$stale_pids" ]]; then
    echo "WARN: port 8501 still busy, stopping listener pid(s): $stale_pids"
    while read -r pid; do
      [[ -n "$pid" ]] || continue
      kill "$pid" 2>/dev/null || true
    done <<< "$stale_pids"
    sleep 1
  fi
fi

systemctl --user start "$UNIT"
systemctl --user is-active --quiet "$UNIT"
echo "OK: $UNIT is active"
echo "Deploy finished."
exit 0
