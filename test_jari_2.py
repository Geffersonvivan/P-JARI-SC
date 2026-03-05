import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.models import Parecer
from chat.jari_engine import JariEngine

p = Parecer.objects.order_by('-id').first()
# Pode ser que ele bateu na fase 3, falhou e parou na 3. Vamos forcar pra Fase 2 e rodar
p.status_fase = 2
p.save()

print(f"Testando Parecer ID: {p.id}")
engine = JariEngine(p)
try:
    print(engine.process_message('ok', []))
except Exception as e:
    import traceback
    traceback.print_exc()
