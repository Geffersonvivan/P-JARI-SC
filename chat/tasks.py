from celery import shared_task
from .models import Parecer
from .jari_engine import JariEngine
import traceback
import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True, time_limit=360, soft_time_limit=300, queue='fast')
def processar_fase1_task(self, parecer_id):
    """
    Processa o auto-preenchimento da Fase 1 no worker Celery.
    Evita que o upload + polling do Gemini (até 60s por PDF) bloqueie
    o Gunicorn e cause WORKER TIMEOUT no Railway.
    """
    from billiard.exceptions import SoftTimeLimitExceeded
    try:
        parecer = Parecer.objects.get(id=parecer_id)
        engine = JariEngine(parecer)
        reply = engine.run_fase1_autopreenchimento()
        from .models import ChatMessage
        ChatMessage.objects.create(parecer=parecer, role='assistant', content=reply)
        return "SUCCESS"
    except SoftTimeLimitExceeded:
        # PDF muito grande para o Gemini processar no prazo — cai para fluxo manual
        logger.warning(f"FASE1 soft time limit atingido (Parecer {parecer_id}). Fallback para fluxo manual.")
        try:
            parecer = Parecer.objects.get(id=parecer_id)
            from .models import ChatMessage
            reply = JariEngine(parecer).get_current_prompt()
            ChatMessage.objects.create(parecer=parecer, role='assistant', content=reply)
        except Exception:
            pass
        return "SUCCESS"
    except Parecer.DoesNotExist:
        return f"Processo ({parecer_id}) não encontrado."
    except Exception as e:
        trace = traceback.format_exc()
        logger.error(f"ERRO CELERY FASE1 (Parecer {parecer_id}): {str(e)}\n\n{trace}")
        raise Exception(f"Erro na Fase 1 (Celery Worker): {str(e)}")


@shared_task(bind=True, time_limit=360, soft_time_limit=300, queue='fast')
def processar_fase2_task(self, parecer_id):
    """
    Processa a Fase 2 (extração de datas + tabela via Gemini) no worker Celery.
    Evita que a chamada síncrona ao Gemini (até 60s) bloqueie o Gunicorn.
    """
    from billiard.exceptions import SoftTimeLimitExceeded
    try:
        parecer = Parecer.objects.get(id=parecer_id)
        engine = JariEngine(parecer)
        reply = engine.run_phase_2()
        from .models import ChatMessage
        ChatMessage.objects.create(parecer=parecer, role='assistant', content=reply)
        return "SUCCESS"
    except SoftTimeLimitExceeded:
        logger.warning(f"FASE2 soft time limit atingido (Parecer {parecer_id}). Retornando prompt de fase 2.")
        try:
            parecer = Parecer.objects.get(id=parecer_id)
            from .models import ChatMessage
            reply = JariEngine(parecer).get_current_prompt()
            ChatMessage.objects.create(parecer=parecer, role='assistant', content=reply)
        except Exception:
            pass
        return "SUCCESS"
    except Parecer.DoesNotExist:
        return f"Processo ({parecer_id}) não encontrado."
    except Exception as e:
        trace = traceback.format_exc()
        logger.error(f"ERRO CELERY FASE2 (Parecer {parecer_id}): {str(e)}\n\n{trace}")
        raise Exception(f"Erro na Fase 2 (Celery Worker): {str(e)}")


@shared_task(bind=True, time_limit=600, soft_time_limit=540, max_retries=2, queue='heavy')
def gerar_parecer_task(self, parecer_id, tese=None):
    """
    Worker task que roda as pesadas Fases 5 e 6 do motor JARI.
    Até 2 retries automáticos (intervalo 30s) para falhas transitórias de API.
    """
    try:
        # Puxa o objeto do banco de dados na thread do Worker
        parecer = Parecer.objects.get(id=parecer_id)

        # Inicia a engrenagem (se a tese foi passada ela salva)
        if tese:
            parecer.tese = tese
            parecer.save(update_fields=['tese'])

        engine = JariEngine(parecer)

        # Dispara o processamento demorado.
        # O JariEngine escreve os resultados e seta status_fase = 6.
        result_text = engine.run_llm_phases(task_id=self.request.id)

        # Persiste o resultado no histórico de chat (equivalente ao processar_fase1_task)
        from .models import ChatMessage
        ChatMessage.objects.create(parecer=parecer, role='assistant', content=result_text)

        # Gatilho por contagem: a cada 10 pareceres finalizados, roda os testes
        try:
            total_finalizados = Parecer.objects.filter(status_fase=8).count()
            if total_finalizados > 0 and total_finalizados % 10 == 0:
                rodar_testes_engine_task.delay()
        except Exception:
            pass  # nunca deve travar o fluxo principal

        # Retorna sucesso para a requisição de polling
        return "SUCCESS"

    except Parecer.DoesNotExist:
        return f"Processo ({parecer_id}) não encontrado."
    except Exception as e:
        trace = traceback.format_exc()
        logger.error(f"ERRO CELERY (Parecer {parecer_id}): {str(e)}\n\n{trace}")
        # Retry automático para falhas transitórias de API (até max_retries=2, delay 30s)
        try:
            raise self.retry(exc=e, countdown=30)
        except self.MaxRetriesExceededError:
            raise Exception(f"Erro na Geração do Parecer (Celery Worker, após retries): {str(e)}")

@shared_task
def rodar_testes_engine_task():
    """
    Executa os testes do JariEngine + JariMath + Integração de Fases e salva em TestRun.
    Acionado automaticamente pelo Celery Beat (a cada 6h) ou
    a cada 10 pareceres finalizados (gatilho em gerar_parecer_task).
    Envia e-mail para ADMIN_EMAIL quando há falhas.

    Suites incluídas:
      - chat.tests_jari_engine   (44 testes) Camada 1: unitários JariMath + engine por fase
      - chat.tests.test_jari_math (37 testes) Camada 1: unitários JariMath expandidos
      - chat.tests_integration   (17 testes) Camada 2: integração F2→F3→F31 com banco real
    """
    import unittest
    import time
    from io import StringIO
    from django.core.mail import send_mail
    from django.conf import settings
    from chat.models import TestRun

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromName('chat.tests_jari_engine'))
    suite.addTests(loader.loadTestsFromName('chat.tests.test_jari_math'))
    suite.addTests(loader.loadTestsFromName('chat.tests_integration'))

    buf = StringIO()
    start = time.time()
    runner = unittest.TextTestRunner(stream=buf, verbosity=2)
    result = runner.run(suite)
    duracao_ms = int((time.time() - start) * 1000)

    detalhes = [
        {'nome': str(caso), 'status': 'FALHOU', 'mensagem': str(traceback_str)}
        for caso, traceback_str in result.failures + result.errors
    ]

    num_falhas = len(result.failures) + len(result.errors)

    TestRun.objects.create(
        total=result.testsRun,
        passou=result.testsRun - num_falhas,
        falhou=num_falhas,
        duracao_ms=duracao_ms,
        detalhes_json=detalhes,
    )

    def _camada(nome_teste):
        if 'test_jari_math' in nome_teste:
            return 'Camada 1 — JariMath'
        if 'tests_integration' in nome_teste:
            return 'Camada 2 — Integração de Fases'
        return 'Camada 1 — Engine'

    if num_falhas > 0:
        admin_email = getattr(settings, 'ADMIN_EMAIL', '')
        if admin_email:
            linhas_falha = '\n\n'.join(
                f"[{_camada(d['nome'])}]\nTESTE: {d['nome']}\n{d['mensagem']}"
                for d in detalhes
            )
            send_mail(
                subject=f'[P-JARI] {num_falhas} teste(s) falhando — verificar urgente',
                message=(
                    f"Resultado da execução automática dos testes (Camadas 1 e 2):\n\n"
                    f"  Total: {result.testsRun}\n"
                    f"  Passou: {result.testsRun - num_falhas}\n"
                    f"  Falhou: {num_falhas}\n"
                    f"  Duração: {duracao_ms}ms\n\n"
                    f"  Suites:\n"
                    f"    • Camada 1 — JariMath unitário (tests.test_jari_math): 37 testes\n"
                    f"    • Camada 1 — Engine por fase (tests_jari_engine): 44 testes\n"
                    f"    • Camada 2 — Integração F2→F3→F31 (tests_integration): 17 testes\n\n"
                    f"--- FALHAS ---\n\n{linhas_falha}"
                ),
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'validacao@pjarisc.com.br'),
                recipient_list=[admin_email],
                fail_silently=True,
            )

    return f"{result.testsRun} testes | {num_falhas} falhas | {duracao_ms}ms"


@shared_task
def send_payment_notification_task(nome_cliente, email_cliente, trans_amount, payment_id):
    from django.core.mail import send_mail
    from django.conf import settings
    send_mail(
        subject=f'✅ Nova Venda Confirmada: {nome_cliente}',
        message=f'Sucesso! Um pagamento de R$ {trans_amount} foi aprovado no Mercado Pago e os créditos foram liberados.\n\nDetalhes do Cliente:\nNome: {nome_cliente}\nEmail: {email_cliente}\nID do Pagamento: {payment_id}',
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'validacao@pjarisc.com.br'),
        recipient_list=[getattr(settings, 'ADMIN_EMAIL', settings.DEFAULT_FROM_EMAIL)],
        fail_silently=True,
    )
