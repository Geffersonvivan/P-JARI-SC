#!/bin/bash
set -e

echo "Starting migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

python manage.py createsuperuser --noinput || true

echo "Starting gunicorn..."
exec gunicorn config.wsgi --bind 0.0.0.0:$PORT --log-file -
