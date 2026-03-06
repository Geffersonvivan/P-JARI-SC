from celery import shared_task
from .models import Parecer
from .jari_engine import JariEngine
import traceback

@shared_task(bind=True)
def gerar_parecer_task(self, parecer_id, tese=None):
    """
    Worker task que roda as pesadas Fases 5 e 6 do motor JARI.
    """
    try:
        # Puxa o objeto do banco de dados na thread do Worker
        parecer = Parecer.objects.get(id=parecer_id)
        
        # Inicia a engrenagem (se a tese foi passada ela salva)
        if tese:
            parecer.tese = tese
            parecer.save(update_fields=['tese'])

        engine = JariEngine(parecer)
        
        # Dispara o processamento demorado
        # O JariEngine irá escrever os resultados e setar status_fase = 6
        engine.run_llm_phases()
        
        # Retorna sucesso para a requisição de polling
        return "SUCCESS"

    except Parecer.DoesNotExist:
        return f"Processo ({parecer_id}) não encontrado."
    except Exception as e:
        trace = traceback.format_exc()
        try:
            with open('debug_jari.txt', 'a') as f:
                f.write(f"ERRO CELERY (Parecer {parecer_id}): {str(e)}\n\n{trace}\n\n")
        except:
            pass
        # O Celery captura esse Exception e marca a Task como "FAILURE" automaticamente.
        raise Exception(f"Erro na Geração do Parecer (Celery Worker): {str(e)}")
