import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings") # adjust if needed
django.setup()

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from chat.views import estatisticas_gerais_view

User = get_user_model()
user = User.objects.filter(is_superuser=True).first()
if getattr(user, 'profile', None) is None:
    print("User has no profile")

factory = RequestFactory()
request = factory.get('/estatisticas-gerais/')
request.user = user
try:
    response = estatisticas_gerais_view(request)
    print("Success:", response.status_code)
except Exception as e:
    import traceback
    traceback.print_exc()

