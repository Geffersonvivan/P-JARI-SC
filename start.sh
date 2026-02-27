#!/bin/bash
set -e

echo "Starting migrations..."
python manage.py migrate --noinput

echo "Ensuring Site object exists..."
python manage.py shell -c "
import os
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp
from django.conf import settings

site, _ = Site.objects.get_or_create(id=getattr(settings, 'SITE_ID', 1))
site.domain = 'web-production-28e5.up.railway.app'
site.name = 'P-JARI SC'
site.save()

client_id = os.environ.get('GOOGLE_CLIENT_ID', 'DUMMY')
secret = os.environ.get('GOOGLE_CLIENT_SECRET', 'DUMMY')
app, _ = SocialApp.objects.get_or_create(provider='google', defaults={'name': 'Google Auth', 'client_id': client_id, 'secret': secret})
app.client_id = client_id
app.secret = secret
app.save()
app.sites.add(site)
"

python manage.py createsuperuser --noinput || true

echo "Starting gunicorn..."
exec gunicorn config.wsgi --bind 0.0.0.0:$PORT --log-file -
