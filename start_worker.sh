#!/bin/bash
set -e

echo "Starting Celery worker + Beat scheduler..."
exec celery -A config worker \
    --beat \
    --loglevel=info \
    --schedule=/tmp/celerybeat-schedule
