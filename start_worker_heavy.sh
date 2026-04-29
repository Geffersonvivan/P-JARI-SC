#!/bin/bash
set -e

echo "Starting Celery worker - fila HEAVY (gerar_parecer)..."
exec celery -A config worker \
    --loglevel=info \
    --concurrency=8 \
    --queues=heavy \
    --max-tasks-per-child=20
