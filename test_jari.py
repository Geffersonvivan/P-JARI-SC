import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.models import Parecer
from chat.jari_engine import JariEngine

p = Parecer.objects.order_by('-id').first()
print(f"Testando Parecer ID: {p.id} Fase Atual: {p.status_fase}")
engine = JariEngine(p)
try:
    print(engine.run_phase_3())
except Exception as e:
    import traceback
    traceback.print_exc()
