import os
import sys
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import RequestFactory
from chat.views import chat_message_view
from chat.models import Parecer

p = Parecer.objects.order_by('-id').first()
if getattr(p, 'status_fase', None) is not None:
    p.status_fase = 2
    p.save()

print(f"Testando Parecer ID: {p.id} com a View Real do Chat...")

factory = RequestFactory()
request = factory.post('/chat/message/', data=json.dumps({
    'message': 'ok',
    'parecer_id': p.id
}), content_type='application/json')

class DummySession(dict):
    session_key = 'simulacao123'
    def create(self): pass

request.session = DummySession()
request.user = p.user if p.user else type('obj', (object,), {'is_authenticated': False, 'profile': None})()

try:
    response = chat_message_view(request)
    print("STATUS CODE:", response.status_code)
    try:
        print("CONTENT:", response.content.decode('utf-8'))
    except:
        print("CONTENT (not utf8):", response.content)
except Exception as e:
    import traceback
    traceback.print_exc()
