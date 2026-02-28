#!/bin/bash
set -e

echo "Starting migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

python manage.py createsuperuser --noinput || true

echo "Ensuring exact Site and SocialApp configuration..."
python manage.py shell -c "
import os
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp
from django.conf import settings

# 1. Ensure domain Site exists
site1, _ = Site.objects.get_or_create(id=getattr(settings, 'SITE_ID', 1))
site1.domain = 'pjarisc.com.br'
site1.name = 'P-JARI SC'
site1.save()

# 2. Ensure railway Site exists
site2, _ = Site.objects.get_or_create(domain='web-production-28e5.up.railway.app', defaults={'name': 'Railway P-JARI SC'})

# 3. Configure Google App and link it to all sites
client_id = os.environ.get('GOOGLE_CLIENT_ID', 'DUMMY')
secret = os.environ.get('GOOGLE_CLIENT_SECRET', 'DUMMY')
app, _ = SocialApp.objects.get_or_create(provider='google', defaults={'name': 'Google Auth', 'client_id': client_id, 'secret': secret})
app.client_id = client_id
app.secret = secret
app.save()

# Ensure both sites are attached to this SocialApp
app.sites.add(site1, site2)
"

echo "Starting gunicorn..."
exec gunicorn config.wsgi --bind 0.0.0.0:$PORT --log-file -
