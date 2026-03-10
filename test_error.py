import os
import django
import sys

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pjari.settings')
django.setup()

from chat.models import Parecer
from chat.jari_engine import JariEngine
from django.contrib.auth.models import User

# Simulate the user flow
user = User.objects.first()
parecer = Parecer.objects.create(
    user=user,
    nome_processo="Test Process",
    status_fase=1
)

engine = JariEngine(parecer)

try:
    print(engine.process_message("15/05/2024")) # Data sessao
    print(engine.process_message("12345/PA"))  # PA
    print(engine.process_message("12345/SGPE")) # SGPE
    print(engine.process_message("14/02/2023")) # Prazo final
except Exception as e:
    import traceback
    traceback.print_exc()

parecer.delete()
