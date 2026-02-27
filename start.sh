#!/bin/bash
set -e

echo "Starting migrations..."
python manage.py migrate --noinput

echo "Ensuring Site object exists..."
python manage.py shell -c "
from django.contrib.sites.models import Site
from django.conf import settings
Site.objects.get_or_create(id=getattr(settings, 'SITE_ID', 1), defaults={'domain': 'app.localhost', 'name': 'App Localhost'})
"

echo "Starting gunicorn..."
exec gunicorn config.wsgi --bind 0.0.0.0:$PORT --log-file -
