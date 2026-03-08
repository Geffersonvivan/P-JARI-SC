import os
import django
import json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import RequestFactory
from chat.views import chat_message_view
from chat.models import Parecer

p = Parecer.objects.order_by('-id').first()
p.status_fase = 2
p.save()

factory = RequestFactory()
request = factory.post('/chat/message/', data=json.dumps({
    'message': 'ok',
    'parecer_id': p.id
}), content_type='application/json')
request.session = factory.get('/').session if hasattr(factory.get('/'), 'session') else type('obj', (object,), {'session_key': '123', 'create': lambda: None})()
# mock auth
request.user = p.user if getattr(p, 'user', None) else type('obj', (object,), {'is_authenticated': False})()

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
