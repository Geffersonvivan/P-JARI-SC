import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.models import Parecer
from chat.jari_engine import JariEngine

# O cliente reportou falha num parecer que continha o pa '80226/2022' ou sgpe '00140243/2025'
pp = Parecer.objects.filter(sgpe='00140243/2025').order_by('-id').first()
if pp:
    print(f"Testando Parecer ID: {pp.id}")
    pp.status_fase = 2
    pp.save()
    engine = JariEngine(pp)
    try:
        print(engine.process_message('ok', []))
    except Exception as e:
        import traceback
        traceback.print_exc()
else:
    print("Parecer não encontrado")
