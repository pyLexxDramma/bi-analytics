#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SUBDIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_SUBDIR/.." && pwd)"
WORK_ROOT="$APP_SUBDIR"
if [[ -f "$REPO_ROOT/streamlit_app.py" ]]; then WORK_ROOT="$REPO_ROOT"; fi
cd "$WORK_ROOT"
PY=""; for candidate in "$WORK_ROOT/.venv/bin/python" "$APP_SUBDIR/venv/bin/python" "$APP_SUBDIR/.venv/bin/python"; do
  [[ -x "$candidate" ]] && PY="$candidate" && PIP="$(dirname "$candidate")/pip" && break
done
[[ -z "$PY" ]] && python3 -m venv "$WORK_ROOT/.venv" && PY="$WORK_ROOT/.venv/bin/python" && PIP="$WORK_ROOT/.venv/bin/pip"
REQ=""; for r in "$WORK_ROOT/requirements.txt" "$APP_SUBDIR/requirements.txt"; do [[ -f "$r" ]] && REQ="$r" && break; done
[[ -z "$REQ" ]] && echo "ERROR: requirements.txt not found" && exit 1
"$PIP" install --upgrade pip -q && "$PIP" install -r "$REQ" -q && echo "OK: pip"
if [[ -f "$APP_SUBDIR/ingest_web_cli.py" && "${BI_DEPLOY_SKIP_INGEST:-0}" != "1" ]]; then
  set +e; (cd "$APP_SUBDIR" && "$PY" ingest_web_cli.py); ingest_rc=$?; set -e
  [[ "$ingest_rc" -ne 0 && "${BI_DEPLOY_FAIL_ON_INGEST:-0}" == "1" ]] && exit "$ingest_rc"
fi
[[ "${BI_DEPLOY_SKIP_SYSTEMD:-0}" == "1" ]] && echo "Deploy finished." && exit 0
UNIT="${BI_SYSTEMD_UNIT:-bi-analytics.service}"
systemctl --user restart "$UNIT" 2>/dev/null && systemctl --user is-active "$UNIT" && exit 0
sudo -n systemctl restart bi-analytics 2>/dev/null && exit 0
echo "WARN: service not restarted. Deploy finished."
