import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from chat.models import Parecer
ps = Parecer.objects.all().order_by('-id')[:5]
for p in ps:
    print(f"ID: {p.id} - Fase: {p.status_fase} - PA: {p.pa} - SGPE: {p.sgpe}")
