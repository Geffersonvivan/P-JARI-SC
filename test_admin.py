import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User

# Hard set the password to ensure login works
user = User.objects.filter(is_superuser=True).first()
if not user:
    user = User.objects.create_superuser('testadmin', 'test@example.com', 'password')
else:
    user.set_password('password')
    user.save()

c = Client()
success = c.login(username=user.username, password='password')
print(f"Login success: {success}")

response = c.get('/admin/', HTTP_HOST='localhost:8000')
print(f'Status Code for /admin/: {response.status_code}')

if response.status_code == 500:
    import traceback
    try:
        c.get('/admin/', HTTP_HOST='localhost:8000')
    except Exception:
        traceback.print_exc()
