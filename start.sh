#!/bin/bash
set -e

echo "Starting migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Ensuring superuser exists and password is up to date..."
python manage.py shell -c "
import os
from django.contrib.auth.models import User

# Get superuser variables
username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')

if username and email and password:
    user, created = User.objects.get_or_create(username=username, defaults={'email': email})
    user.email = email
    user.set_password(password)
    user.is_superuser = True
    user.is_staff = True
    user.save()
    if created:
        print(f'Superuser {username} created successfully.')
    else:
        print(f'Superuser {username} updated successfully.')
"

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

echo "Starting background Celery worker..."
celery -A config worker --loglevel=info &

echo "Starting gunicorn com workers e threads para SaaS..."
exec gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers 3 --threads 4 --timeout 120 --log-file -
