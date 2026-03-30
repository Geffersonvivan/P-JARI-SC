#!/bin/bash
set -e

# Em produção (Railway): sem auto-reload, apenas o worker padrão
if [ "$RAILWAY_ENVIRONMENT" != "" ]; then
    echo "Starting Celery worker (production)..."
    exec celery -A config worker \
        --beat \
        --loglevel=info \
        --schedule=/tmp/celerybeat-schedule
fi

# Em desenvolvimento: watchmedo reinicia automaticamente ao salvar qualquer .py
echo "Starting Celery worker com auto-reload (desenvolvimento)..."
exec watchmedo auto-restart \
    --directory=./chat \
    --pattern="*.py" \
    --recursive \
    -- \
    celery -A config worker \
        --loglevel=info \
        --logfile=/tmp/pjari_celery.log \
        --concurrency=4
