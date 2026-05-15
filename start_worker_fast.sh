#!/bin/bash
set -e

echo "Starting Celery worker - fila FAST (fases 1-4) + Beat..."
exec celery -A config worker \
    --beat \
    --loglevel=info \
    --concurrency=16 \
    --queues=fast \
    --max-tasks-per-child=100 \
    --schedule=/tmp/celerybeat-schedule
