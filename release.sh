#!/bin/bash
set -e

# Release Command do Railway — roda UMA VEZ antes de qualquer réplica subir.
# Garante que migrations, superuser e configurações de Site/SocialApp
# não colidam quando múltiplas réplicas sobem em paralelo.

echo "Running migrations..."
python manage.py migrate --noinput

echo "Ensuring superuser exists and password is up to date..."
python manage.py shell -c "
import os
from django.contrib.auth.models import User

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

site1, _ = Site.objects.get_or_create(id=getattr(settings, 'SITE_ID', 1))
site1.domain = 'pjarisc.com.br'
site1.name = 'P-JARI SC'
site1.save()

site2, _ = Site.objects.get_or_create(domain='web-production-28e5.up.railway.app', defaults={'name': 'Railway P-JARI SC'})

client_id = os.environ.get('GOOGLE_CLIENT_ID', 'DUMMY')
secret = os.environ.get('GOOGLE_CLIENT_SECRET', 'DUMMY')
app, _ = SocialApp.objects.get_or_create(provider='google', defaults={'name': 'Google Auth', 'client_id': client_id, 'secret': secret})
app.client_id = client_id
app.secret = secret
app.save()

app.sites.add(site1, site2)
"

echo "Release steps completed."
