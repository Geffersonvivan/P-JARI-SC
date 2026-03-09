import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pjari.settings')
django.setup()

from chat.models import Parecer, ConfiguracaoParecer
from django.test import RequestFactory
from chat.views import editar_parecer_view

factory = RequestFactory()
request = factory.get('/parecer/1/editor/')

# Get any existing parecer
p = Parecer.objects.first()
if p:
    try:
        response = editar_parecer_view(request, p.id)
        print("Success:", response.status_code)
    except Exception as e:
        import traceback
        traceback.print_exc()
else:
    print("No parecer found in local DB.")
