#!/bin/bash
set -e

echo "🚀 Запуск OpenCode сервера на порту ${OPENCODE_PORT:-4096}..."
opencode serve \
  --port ${OPENCODE_PORT:-4096} \
  --hostname 0.0.0.0 \
  --cors http://localhost:${WEB_PORT:-4098} &

sleep 2

echo "🌐 Запуск Web UI на порту ${WEB_PORT:-4098}..."
node server.js &

echo "✅ Всё запущено!"
echo "   OpenCode API: http://localhost:${OPENCODE_PORT:-4096}"
echo "   Web UI:       http://localhost:${WEB_PORT:-4098}"

# Ждём все процессы
wait