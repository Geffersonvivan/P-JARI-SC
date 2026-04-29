#!/bin/bash
set -e

echo "Starting Celery worker - fila FAST (fases 1-4)..."
exec celery -A config worker \
    --loglevel=info \
    --concurrency=16 \
    --queues=fast
