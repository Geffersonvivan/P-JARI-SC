from celery import shared_task
from .models import Parecer
from .jari_engine import JariEngine
import traceback
import logging

logger = logging.getLogger(__name__)

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
        logger.error(f"ERRO CELERY (Parecer {parecer_id}): {str(e)}\n\n{trace}")
        # O Celery captura esse Exception e marca a Task como "FAILURE" automaticamente.
        raise Exception(f"Erro na Geração do Parecer (Celery Worker): {str(e)}")

@shared_task
def send_payment_notification_task(nome_cliente, email_cliente, trans_amount, payment_id):
    from django.core.mail import send_mail
    from django.conf import settings
    send_mail(
        subject=f'✅ Nova Venda Confirmada: {nome_cliente}',
        message=f'Sucesso! Um pagamento de R$ {trans_amount} foi aprovado no Mercado Pago e os créditos foram liberados.\n\nDetalhes do Cliente:\nNome: {nome_cliente}\nEmail: {email_cliente}\nID do Pagamento: {payment_id}',
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'validacao@pjarisc.com.br'),
        recipient_list=['geffersonvivan@gmail.com'],
        fail_silently=True,
    )
