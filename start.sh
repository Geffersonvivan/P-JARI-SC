#!/bin/bash
set -e

# Setup (migrate, superuser, Site/SocialApp) está no Release Command do Railway:
# Settings → Deploy → Release Command: bash release.sh
# Roda apenas 1 vez antes de qualquer réplica subir.

echo "Starting gunicorn ASGI com uvicorn worker (SSE não-bloqueante)..."
exec gunicorn config.asgi:application \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:$PORT \
  --workers 8 \
  --timeout 300 \
  --graceful-timeout 120 \
  --keep-alive 65 \
  --worker-tmp-dir /dev/shm \
  --log-file -
