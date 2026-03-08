import os
import django
import sys

# Configure Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.models import Parecer
from chat.tasks import gerar_parecer_task

def test_celery_task_locally():
    print("--- 🧪 INICIANDO TESTE DO WORKER CELERY (MODO SÍNCRONO) ---")
    
    # Busca um parecer ativo ou cria um dummy para simular a FASE 5
    p = Parecer.objects.exclude(tese__exact='').filter(status_fase__in=[4, 41, 5]).first()
    
    if not p:
        print("Criando Parecer Fake Mínimo para Simular Fase 5...")
        from django.contrib.auth.models import User
        user = User.objects.first()
        p = Parecer.objects.create(
            user=user, 
            nome_processo="TESTE CELERY WORKER",
            tese="O condutor alega clonagem através de BO",
            status_fase=41
        )
        p.save()

    print(f"📌 Capturou Parecer ID: {p.id} | Status: {p.status_fase} | Tese: {p.tese}")
    
    print("\n⏳ Simulando a entrada na 'Cozinha' Celery (Irá demorar pois chama LLM Real)...")
    
    try:
        # Chama a Task DIRETAMENTE como Python, não usando o .delay()
        # Se ela quebrar aqui, quebraria no servidor Redis.
        resultado = gerar_parecer_task(p.id)
        
        # Recarrega o Objeto para ver se o BD foi alterado corretamente
        p.refresh_from_db()
        
        print(f"\n✅ SUCESSO DO WORKER! Retorno do Celery: {resultado}")
        print(f"📊 Novo Status Fase: {p.status_fase}")
        print(f"📄 Parecer Final (Amostra): {p.parecer_final[:100]}...")
        
    except Exception as e:
        print(f"\n❌ ERRO FATAL no Worker!")
        print(str(e))
        sys.exit(1)

if __name__ == "__main__":
    test_celery_task_locally()
