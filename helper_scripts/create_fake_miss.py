import os
import django
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from chat.models import AiRequestLog, Parecer, User

try:
    user = User.objects.first()
    parecer = Parecer.objects.filter(user=user).first()
    
    AiRequestLog.objects.create(
        parecer_referencia=parecer,
        user=user,
        provider='Vertex AI (Search)',
        fase='Pesquisa Base (RAG)',
        input_tokens=0,
        output_tokens=1,
        query_text='Resolução Inexistente 99999/2026',
        is_miss=True,
        data_requisicao=timezone.now()
    )
    print("Fake miss created successfully.")
except Exception as e:
    print(f"Error: {e}")
