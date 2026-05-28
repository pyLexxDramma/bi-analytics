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

if ! "$PY" -m pip install --upgrade pip -q; then
  echo "ERROR: pip upgrade failed"
  exit 1
fi
if ! "$PY" -m pip install -r "$REQ" -q; then
  echo "ERROR: pip install -r $REQ failed"
  exit 1
fi
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
    [[ "${BI_DEPLOY_FAIL_ON_INGEST:-0}" == "1" ]] && exit "$ingest_rc"
  else
    echo "OK: ingest"
  fi
fi

echo "Deploy finished (code + deps)."
