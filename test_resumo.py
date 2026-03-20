import os
import django
import sys
import json

sys.path.append('/Volumes/D/P-Jari')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from chat.models import Parecer
from chat.services import ChatService

# Pega o ultimo parecer salvo com parecer_final
p = Parecer.objects.filter(is_saved=True).exclude(parecer_final__isnull=True).exclude(parecer_final='').last()

if p:
    print(f"Testando com Parecer ID: {p.id}")
    res = ChatService.handle_resumo_projeto(p.id, {})
    data = json.loads(res.content)
    
    print("KEYS NO JSON:")
    print(data.keys())
    
    print("\nULTIMAS 2 MENSAGENS NO CHAT HISTORY:")
    if 'chat_history' in data:
        for msg in data['chat_history'][-2:]:
            print(f"Role: {msg.get('role')} | Len Content: {len(msg.get('content', ''))}")
            if "Abrir Editor" in msg.get('content', ''):
                print(" -> BOTAO ENCONTRADO NO HISTORY!")
else:
    print("Nenhum parecer salvo encontrado.")
