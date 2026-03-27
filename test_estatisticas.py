import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from chat.views import estatisticas_view, estatisticas_gerais_view

user = User.objects.filter(is_superuser=True).first()
if not user:
    user = User.objects.first()

factory = RequestFactory()
request = factory.get('/estatisticas/')
request.user = user

print("Testing estatisticas_view...")
try:
    response = estatisticas_view(request)
    print("Estatisticas View Response:", response.status_code)
except Exception as e:
    import traceback
    traceback.print_exc()

print("Testing estatisticas_gerais_view...")
request_geral = factory.get('/estatisticas-gerais/')
request_geral.user = user
try:
    response_geral = estatisticas_gerais_view(request_geral)
    print("Estatisticas Gerais View Response:", response_geral.status_code)
except Exception as e:
    import traceback
    traceback.print_exc()

