#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SUBDIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_SUBDIR/.." && pwd)"

WORK_ROOT="$APP_SUBDIR"
if [[ -f "$REPO_ROOT/streamlit_app.py" ]]; then
  WORK_ROOT="$REPO_ROOT"
fi
cd "$WORK_ROOT"
echo "WORK_ROOT=$WORK_ROOT"

PY=""
for candidate in \
  "$WORK_ROOT/.venv/bin/python" \
  "$APP_SUBDIR/venv/bin/python" \
  "$APP_SUBDIR/.venv/bin/python"; do
  if [[ -x "$candidate" ]]; then
    PY="$candidate"
    break
  fi
done
if [[ -z "$PY" ]]; then
  echo "Creating venv in $WORK_ROOT/.venv"
  python3 -m venv "$WORK_ROOT/.venv"
  PY="$WORK_ROOT/.venv/bin/python"
fi
echo "PY=$PY"

REQ=""
for r in "$APP_SUBDIR/requirements.txt" "$WORK_ROOT/requirements.txt"; do
  if [[ -f "$r" ]]; then
    REQ="$r"
    break
  fi
done
if [[ -z "$REQ" ]]; then
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
  echo "Running ingest in $APP_SUBDIR"
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
  echo "Deploy finished (code + deps, restart app manually)."
  exit 0
fi

UNIT="${BI_SYSTEMD_UNIT:-bi-analytics.service}"
if systemctl --user restart "$UNIT" 2>/dev/null; then
  systemctl --user is-active "$UNIT"
  echo "Deploy finished ($UNIT)."
  exit 0
fi
if sudo -n systemctl restart bi-analytics 2>/dev/null; then
  echo "Deploy finished (bi-analytics)."
  exit 0
fi
echo "WARN: service not restarted. Deploy finished."
