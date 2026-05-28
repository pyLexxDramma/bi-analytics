#!/usr/bin/env bash
set -euo pipefail
WS=/workspace
if [[ ! -f "$WS/opencode.json" ]]; then
  echo "[opencode] ERROR: $WS/opencode.json missing."
  echo "  Host bind ./workspace is empty — run: git pull && rsync -a workspace/ /path/to/opencode_web/workspace/"
  echo "  Or remove ./workspace volume from docker-compose and rebuild the image."
  exit 1
fi
if [[ ! -d "$WS/.git" ]]; then
  (cd "$WS" && git init -q && git add -A \
    && git -c user.email=xca@local -c user.name=XCA commit -q -m "workspace init" --allow-empty) || true
fi
if [[ -x /usr/local/bin/render_opencode_config.sh ]]; then
  /usr/local/bin/render_opencode_config.sh || true
fi
if [[ -x /usr/local/bin/ensure_web_data_db.sh ]]; then
  /usr/local/bin/ensure_web_data_db.sh || true
fi
exec opencode web --hostname "${OPENCODE_HOST:-127.0.0.1}" --port "${OPENCODE_PORT:-4096}"
