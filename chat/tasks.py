from celery import shared_task
from .models import Parecer, log_audit
from .jari_engine import JariEngine
import traceback
import logging
import sentry_sdk

logger = logging.getLogger(__name__)


def _sentry_task_context(parecer_id: int, task_name: str):
    """Define contexto rico no Sentry para cada task Celery."""
    sentry_sdk.set_tag("task", task_name)
    sentry_sdk.set_tag("parecer_id", str(parecer_id))
    try:
        p = Parecer.objects.only("pa", "sgpe", "status_fase", "session_key").get(pk=parecer_id)
        sentry_sdk.set_context("parecer", {
            "id": parecer_id,
            "pa": p.pa,
            "sgpe": p.sgpe,
            "status_fase": p.status_fase,
        })
        sentry_sdk.set_user({"id": str(p.session_key)})
    except Exception:
        pass

def _is_gemini_transient(e) -> bool:
    """Retorna True para erros transitórios do Gemini (504, DEADLINE_EXCEEDED, timeout)."""
    s = str(e)
    return any(k in s for k in ('504', 'DEADLINE_EXCEEDED', 'ServerError', 'timeout', 'Timeout'))


@shared_task(time_limit=180, soft_time_limit=150, max_retries=1, queue='fast',
             ignore_result=True)
def pre_upload_gemini_task(parecer_id):
    """
    Pré-aquece o cache Redis com os file handles do Gemini Files API.
    Disparada em paralelo com processar_fase1_task logo após o upload dos PDFs.
    Quando a Fase 1 (e fases seguintes) chamar upload_file(), encontrará cache hit
    e pulará upload+polling (~30s economizados por PDF).
    """
    try:
        parecer = Parecer.objects.only(
            'autuacao_pdf_path', 'consolidado_pdf_path', 'ata_pdf_path'
        ).get(id=parecer_id)
        from chat.integrations import GeminiClient
        client = GeminiClient()
        if not client.client:
            return
        from chat.integrations.perplexity import _p
        paths = []
        for field in [parecer.autuacao_pdf_path, parecer.consolidado_pdf_path, parecer.ata_pdf_path]:
            p = _p(field)
            if p and 'upload_simulado' not in p and p not in paths:
                paths.append(p)
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=len(paths) or 1) as ex:
            list(ex.map(client.upload_file, paths))
        logger.info("pre_upload_gemini OK: parecer=%s paths=%s", parecer_id, paths)
    except Exception as e:
        logger.warning("pre_upload_gemini falhou (parecer=%s): %s — não bloqueia fluxo", parecer_id, e)


@shared_task(bind=True, time_limit=360, soft_time_limit=300, max_retries=3, queue='fast')
def processar_fase1_task(self, parecer_id):
    """
    Processa o auto-preenchimento da Fase 1 no worker Celery.
    Evita que o upload + polling do Gemini (até 60s por PDF) bloqueie
    o Gunicorn e cause WORKER TIMEOUT no Railway.
    """
    from billiard.exceptions import SoftTimeLimitExceeded
    _sentry_task_context(parecer_id, "fase1")
    try:
        parecer = Parecer.objects.get(id=parecer_id)
        engine = JariEngine(parecer)
        reply = engine.run_fase1_autopreenchimento()
        from .models import ChatMessage
        ChatMessage.objects.create(parecer=parecer, role='assistant', content=reply)
        log_audit('fase_concluida', parecer=parecer, fase=1)
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
        if _is_gemini_transient(e):
            countdown = 30 * (self.request.retries + 1)  # 30s, 60s, 90s
            logger.warning(f"FASE1 Gemini transitório (Parecer {parecer_id}), retry {self.request.retries + 1}/3 em {countdown}s: {e}")
            try:
                raise self.retry(exc=e, countdown=countdown)
            except self.MaxRetriesExceededError:
                pass
        try:
            _p = Parecer.objects.get(id=parecer_id)
            log_audit('fase_erro', parecer=_p, fase=1, dados={'erro': str(e)[:200]})
        except Exception:
            pass
        logger.error(f"ERRO CELERY FASE1 (Parecer {parecer_id}): {str(e)}\n\n{trace}")
        raise Exception(f"Erro na Fase 1 (Celery Worker): {str(e)}")


@shared_task(bind=True, time_limit=360, soft_time_limit=300, max_retries=3, queue='fast')
def processar_fase2_task(self, parecer_id):
    """
    Processa a Fase 2 (extração de datas + tabela via Gemini) no worker Celery.
    Evita que a chamada síncrona ao Gemini (até 60s) bloqueie o Gunicorn.
    Ao terminar, dispara pré-cálculo da Fase 3 em background (otimização UX).
    Retry automático (3x, backoff 30s) para erros transitórios do Gemini (504/DEADLINE_EXCEEDED).
    """
    from billiard.exceptions import SoftTimeLimitExceeded
    _sentry_task_context(parecer_id, "fase2")
    try:
        parecer = Parecer.objects.get(id=parecer_id)
        engine = JariEngine(parecer)
        reply = engine.run_phase_2()
        from .models import ChatMessage
        ChatMessage.objects.create(parecer=parecer, role='assistant', content=reply)
        # Dispara pré-cálculo F3 enquanto julgador revisa tabela F2 (best-effort)
        try:
            processar_fase3_precompute_task.delay(parecer_id)
        except Exception:
            pass  # Nunca deve bloquear o fluxo principal
        log_audit('fase_concluida', parecer=parecer, fase=2)
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
        if _is_gemini_transient(e):
            countdown = 30 * (self.request.retries + 1)  # 30s, 60s, 90s
            logger.warning(f"FASE2 Gemini transitório (Parecer {parecer_id}), retry {self.request.retries + 1}/3 em {countdown}s: {e}")
            try:
                raise self.retry(exc=e, countdown=countdown)
            except self.MaxRetriesExceededError:
                pass
        try:
            _p = Parecer.objects.get(id=parecer_id)
            log_audit('fase_erro', parecer=_p, fase=2, dados={'erro': str(e)[:200]})
        except Exception:
            pass
        logger.error(f"ERRO CELERY FASE2 (Parecer {parecer_id}): {str(e)}\n\n{trace}")
        raise Exception(f"Erro na Fase 2 (Celery Worker): {str(e)}")


@shared_task(bind=True, time_limit=360, soft_time_limit=300, max_retries=3, queue='fast')
def processar_fase3_admissibilidade_task(self, parecer_id):
    """
    Executa a Fase 3 (JariMath + Gemini) no worker Celery quando o julgador confirma a tabela F2.
    Evita que a chamada síncrona ao Gemini bloqueie o Gunicorn indefinidamente (bug "99% travado").
    Se admissibilidade_texto já foi pré-calculado, apenas avança o status (caminho rápido sem Gemini).
    Retry automático (3x, backoff 30s) para erros transitórios do Gemini.
    """
    from billiard.exceptions import SoftTimeLimitExceeded
    _sentry_task_context(parecer_id, "fase3_adm")
    try:
        parecer = Parecer.objects.get(id=parecer_id)
        engine = JariEngine(parecer)
        from chat.engine.phase_3 import run as run_fase3
        result = run_fase3(engine)
        # run() retorna string de erro (⚠️/❌) sem lançar exceção em alguns casos (ex: data_infracao ausente)
        if result and isinstance(result, str) and (result.startswith('⚠️') or result.startswith('❌')):
            raise Exception(result)
        log_audit('fase_concluida', parecer=parecer, fase='3_adm')
        return "SUCCESS"
    except SoftTimeLimitExceeded:
        logger.warning(f"FASE3_ADM soft time limit atingido (Parecer {parecer_id}).")
        return "SUCCESS"
    except Parecer.DoesNotExist:
        return f"Processo ({parecer_id}) não encontrado."
    except Exception as e:
        trace = traceback.format_exc()
        if _is_gemini_transient(e):
            countdown = 30 * (self.request.retries + 1)
            logger.warning(f"FASE3_ADM Gemini transitório (Parecer {parecer_id}), retry {self.request.retries + 1}/3 em {countdown}s: {e}")
            try:
                raise self.retry(exc=e, countdown=countdown)
            except self.MaxRetriesExceededError:
                pass
        try:
            _p = Parecer.objects.get(id=parecer_id)
            log_audit('fase_erro', parecer=_p, fase='3_adm', dados={'erro': str(e)[:200]})
        except Exception:
            pass
        logger.error(f"ERRO CELERY FASE3_ADM (Parecer {parecer_id}): {str(e)}\n\n{trace}")
        raise Exception(f"Erro na Fase 3/Admissibilidade (Celery Worker): {str(e)}")


@shared_task(bind=True, time_limit=120, soft_time_limit=100, queue='fast')
def processar_fase3_precompute_task(self, parecer_id):
    """
    Pré-calcula a Fase 3 em background enquanto o julgador revisa F2.
    Executa JariMath + Gemini e persiste admissibilidade_texto sem avançar o status.
    Quando o julgador confirmar F2, phase_3.run() detecta admissibilidade_texto já preenchido
    e pula a chamada Gemini — elimina ~30s de espera percebida.
    Não retenta em falha (best-effort): se falhar, F3 roda normalmente no fluxo principal.
    """
    try:
        parecer = Parecer.objects.get(id=parecer_id)
        from chat.engine.phase_3 import run_precompute
        result = run_precompute(parecer)
        return "PRECOMPUTED" if result else "SKIP"
    except Parecer.DoesNotExist:
        return f"Processo ({parecer_id}) não encontrado."
    except Exception as e:
        logger.warning("FASE3-PRE falhou (best-effort, sem retry) — Parecer %s: %s", parecer_id, e)
        return f"ERRO (ignorado): {e}"


@shared_task(bind=True, time_limit=360, soft_time_limit=300, max_retries=3, queue='fast')
def processar_fase4_task(self, parecer_id):
    """
    Extrai a tese defensiva via Gemini (Fase 4) no worker Celery.
    Evita que a chamada síncrona ao Gemini bloqueie o Gunicorn e cause WORKER TIMEOUT.
    Retry automático (3x, backoff 30s) para erros transitórios do Gemini (504/DEADLINE_EXCEEDED).
    """
    from billiard.exceptions import SoftTimeLimitExceeded
    _sentry_task_context(parecer_id, "fase4")
    try:
        import json as _json
        parecer = Parecer.objects.get(id=parecer_id)
        engine = JariEngine(parecer)
        reply = engine.run_phase_4_extraction()
        from .models import ChatMessage
        # Detecta encadeamento (PREJUDICIALIDADE ou rota normal)
        try:
            _chained = _json.loads(reply)
            if _chained.get('__chained'):
                # PREJUDICIALIDADE: gerar_parecer_task já disparado dentro de run_extraction
                logger.info(f"FASE4 encadeando para {_chained['task_type']} (Parecer {parecer_id})")
                ChatMessage.objects.create(parecer=parecer, role='assistant', content="Recurso sem tese identificada — gerando parecer automaticamente.")
                return _json.dumps({"chained": True, "task_id": _chained['task_id'], "task_type": _chained['task_type']})
        except (ValueError, KeyError, TypeError):
            pass
        # Tese extraída com sucesso — auto-dispara análise sem confirmação do usuário
        ChatMessage.objects.create(parecer=parecer, role='assistant', content=reply)
        log_audit('fase_concluida', parecer=parecer, fase=4)
        analise_task = processar_fase4_analise_task.delay(parecer_id)
        logger.info(f"FASE4 tese extraída — encadeando FASE4_ANALISE task={analise_task.id} (Parecer {parecer_id})")
        return _json.dumps({"chained": True, "task_id": analise_task.id, "task_type": "FASE4_ANALISE"})
    except SoftTimeLimitExceeded:
        logger.warning(f"FASE4 soft time limit atingido (Parecer {parecer_id}). Retornando prompt de fase 4.")
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
        if _is_gemini_transient(e):
            countdown = 30 * (self.request.retries + 1)  # 30s, 60s, 90s
            logger.warning(f"FASE4 Gemini transitório (Parecer {parecer_id}), retry {self.request.retries + 1}/3 em {countdown}s: {e}")
            try:
                raise self.retry(exc=e, countdown=countdown)
            except self.MaxRetriesExceededError:
                pass
        try:
            _p = Parecer.objects.get(id=parecer_id)
            log_audit('fase_erro', parecer=_p, fase=4, dados={'erro': str(e)[:200]})
        except Exception:
            pass
        logger.error(f"ERRO CELERY FASE4 (Parecer {parecer_id}): {str(e)}\n\n{trace}")
        raise Exception(f"Erro na Fase 4 (Celery Worker): {str(e)}")


@shared_task(bind=True, time_limit=480, soft_time_limit=420, max_retries=3, queue='fast')
def processar_fase4_analise_task(self, parecer_id):
    """
    Executa a análise cruzada de teses (Perplexity + Vertex + Gemini) no worker Celery.
    Evita que as chamadas síncronas às APIs (~90s cada) bloqueiem o Gunicorn.
    Retry automático (3x, backoff 30s) para erros transitórios do Gemini (504/DEADLINE_EXCEEDED).
    """
    from billiard.exceptions import SoftTimeLimitExceeded
    _sentry_task_context(parecer_id, "fase4_analise")
    try:
        import json as _json
        parecer = Parecer.objects.get(id=parecer_id)
        engine = JariEngine(parecer)
        reply = engine.analise_tese_fase_4()
        from .models import ChatMessage
        # Detecta encadeamento (prejudicialidade sem teses para confirmar)
        try:
            _chained = _json.loads(reply)
            if _chained.get('__chained'):
                logger.info(f"FASE4-ANALISE prejudicada — encadeando {_chained['task_type']} (Parecer {parecer_id})")
                ChatMessage.objects.create(parecer=parecer, role='assistant', content="Processo prejudicado — gerando parecer automaticamente.")
                return _json.dumps({"chained": True, "task_id": _chained['task_id'], "task_type": _chained['task_type']})
        except (ValueError, KeyError, TypeError):
            pass
        ChatMessage.objects.create(parecer=parecer, role='assistant', content=reply)
        return "SUCCESS"
    except SoftTimeLimitExceeded:
        logger.warning(f"FASE4-ANALISE soft time limit atingido (Parecer {parecer_id}).")
        try:
            import sentry_sdk
            sentry_sdk.capture_message(
                f"FASE4-ANALISE SoftTimeLimitExceeded — parecer={parecer_id}",
                level="warning",
            )
        except Exception:
            pass
        try:
            parecer = Parecer.objects.get(id=parecer_id)
            from .models import ChatMessage
            if parecer.analise_tese_texto:
                # Análise foi salva antes do timeout — avança normalmente
                reply = JariEngine(parecer).get_current_prompt()
                ChatMessage.objects.create(parecer=parecer, role='assistant', content=reply)
                logger.info(f"FASE4-ANALISE timeout mas analise_tese_texto presente — avançando. Parecer {parecer_id}")
                return "SUCCESS"
            else:
                # Save não completou — salva mensagem de erro no chat e lança exceção
                # para que o Celery marque a task como FAILURE (o SSE frontend exibe o modal de erro)
                ChatMessage.objects.create(
                    parecer=parecer, role='assistant',
                    content=(
                        "⚠️ **Tempo limite atingido durante a análise de teses.**\n\n"
                        "O processamento foi interrompido antes de concluir. "
                        "Clique em **Recarregar** ou aguarde alguns instantes e tente novamente."
                    ),
                )
                logger.error(f"FASE4-ANALISE timeout SEM analise_tese_texto — lançando FAILURE. Parecer {parecer_id}")
        except Exception as _inner:
            logger.error(f"FASE4-ANALISE timeout handler falhou: {_inner} — Parecer {parecer_id}")
        raise Exception(f"FASE4-ANALISE timeout sem resultado salvo — Parecer {parecer_id}")
    except Parecer.DoesNotExist:
        return f"Processo ({parecer_id}) não encontrado."
    except Exception as e:
        trace = traceback.format_exc()
        if _is_gemini_transient(e):
            countdown = 30 * (self.request.retries + 1)  # 30s, 60s, 90s
            logger.warning(f"FASE4-ANALISE Gemini transitório (Parecer {parecer_id}), retry {self.request.retries + 1}/3 em {countdown}s: {e}")
            try:
                raise self.retry(exc=e, countdown=countdown)
            except self.MaxRetriesExceededError:
                pass
        logger.error(f"ERRO CELERY FASE4-ANALISE (Parecer {parecer_id}): {str(e)}\n\n{trace}")
        raise Exception(f"Erro na Fase 4 Análise (Celery Worker): {str(e)}")


@shared_task(bind=True, time_limit=600, soft_time_limit=540, max_retries=2, queue='heavy')
def gerar_parecer_task(self, parecer_id, tese=None):
    """
    Worker task que roda as pesadas Fases 5 e 6 do motor JARI.
    Até 2 retries automáticos (intervalo 30s) para falhas transitórias de API.
    """
    _sentry_task_context(parecer_id, "parecer")
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
        # Retry apenas para erros transitórios do Gemini (504, timeout, etc.)
        # Erros de código (AttributeError, KeyError) nunca se resolvem com retry
        # e monopolizariam um slot heavy por até 30 min (3 × 600s)
        if _is_gemini_transient(e):
            countdown = 30 * (self.request.retries + 1)
            logger.warning(f"PARECER Gemini transitório (Parecer {parecer_id}), retry {self.request.retries + 1}/2 em {countdown}s: {e}")
            try:
                raise self.retry(exc=e, countdown=countdown)
            except self.MaxRetriesExceededError:
                pass
        try:
            _p = Parecer.objects.get(id=parecer_id)
            log_audit('fase_erro', parecer=_p, fase=5, dados={'erro': str(e)[:200]})
        except Exception:
            pass
        raise Exception(f"Erro na Geração do Parecer (Celery Worker): {str(e)}")

@shared_task(time_limit=600, soft_time_limit=540, max_retries=0, queue='fast')
def rodar_testes_engine_task():
    """
    Executa os testes do JariEngine + JariMath + Integração de Fases e salva em TestRun.
    Acionado automaticamente pelo Celery Beat (a cada 6h) ou
    a cada 10 pareceres finalizados (gatilho em gerar_parecer_task).
    Envia e-mail para ADMIN_EMAIL quando há falhas.

    Suites incluídas:
      - chat.tests_jari_engine              (44 testes) Camada 1: unitários JariMath + engine por fase
      - chat.tests.test_jari_math           (37 testes) Camada 1: unitários JariMath expandidos
      - chat.tests_integration              (17 testes) Camada 2: integração F2→F3→F31 com banco real
      - chat.tests.test_fases               (22 testes) Camada 2: integração F31→F4/F5 + 409 + Rota D
      - chat.tests.test_cenarios_producao   (13 testes) Camada 2.5: cenários reais de produção
      - chat.tests.test_contratos_api       (26 testes) Camada 3: contratos de API
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
    suite.addTests(loader.loadTestsFromName('chat.tests.test_fases'))
    suite.addTests(loader.loadTestsFromName('chat.tests.test_cenarios_producao'))
    suite.addTests(loader.loadTestsFromName('chat.tests.test_contratos_api'))

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
        if 'test_fases' in nome_teste:
            return 'Camada 2 — Fases F31/F4/F5'
        if 'test_cenarios_producao' in nome_teste:
            return 'Camada 2.5 — Cenários de Produção'
        if 'test_contratos_api' in nome_teste:
            return 'Camada 3 — Contratos de API'
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
                    f"Resultado da execução automática dos testes (Camadas 1, 2 e 3):\n\n"
                    f"  Total: {result.testsRun}\n"
                    f"  Passou: {result.testsRun - num_falhas}\n"
                    f"  Falhou: {num_falhas}\n"
                    f"  Duração: {duracao_ms}ms\n\n"
                    f"  Suites:\n"
                    f"    • Camada 1 — JariMath unitário (tests.test_jari_math): 37 testes\n"
                    f"    • Camada 1 — Engine por fase (tests_jari_engine): 44 testes\n"
                    f"    • Camada 2 — Integração F2→F3→F31 (tests_integration): 17 testes\n"
                    f"    • Camada 2 — Fases F31/F4/F5 (tests.test_fases): 22 testes\n"
                    f"    • Camada 2.5 — Cenários de Produção (tests.test_cenarios_producao): 13 testes\n"
                    f"    • Camada 3 — Contratos de API (tests.test_contratos_api): 26 testes\n\n"
                    f"--- FALHAS ---\n\n{linhas_falha}"
                ),
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'validacao@pjarisc.com.br'),
                recipient_list=[admin_email],
                fail_silently=True,
            )

    return f"{result.testsRun} testes | {num_falhas} falhas | {duracao_ms}ms"


@shared_task(time_limit=600, soft_time_limit=540, queue='heavy', ignore_result=True)
def predigerir_pacotes_task():
    """
    Celery Beat — Pré-digere pacotes normativos para as infrações mais comuns.
    Roda 1x/dia. Consulta Vertex + Perplexity e sintetiza via Gemini em pacotes
    compactos (~2000 tokens) reutilizáveis nas Fases 4/5.
    """
    from django.db.models import Count
    from chat.models import PjariCacheEntry, PjariCacheConfig
    from chat.integrations import VertexAIClient, PerplexityClient, GeminiClient
    import concurrent.futures

    logger.info("[CAG] Iniciando pré-digestão de pacotes normativos")

    # ── Taxonomia: infrações mais frequentes nos últimos 90 dias ──────────
    from django.utils import timezone
    import datetime
    cutoff = timezone.now() - datetime.timedelta(days=90)
    top_infracoes = (
        Parecer.objects
        .filter(created_at__gte=cutoff, infracao_documento__isnull=False)
        .exclude(infracao_documento='')
        .values('infracao_documento')
        .annotate(total=Count('id'))
        .order_by('-total')[:25]
    )

    if not top_infracoes:
        logger.info("[CAG] Nenhuma infração encontrada — abortando")
        return "0 pacotes"

    # Normaliza tipo de infração para chave de cache
    _TIPO_MAP = {
        '165': 'art_165_embriaguez',
        '165-a': 'art_165a_recusa_bafometro',
        '170': 'art_170_manobra_perigosa',
        '175': 'art_175_velocidade_incompativel',
        '218': 'art_218_excesso_velocidade',
        '230': 'art_230_cnh_vencida',
        '232': 'art_232_conduzir_sem_cnh',
        '244': 'art_244_sem_capacete',
        '252': 'art_252_celular',
        '261': 'art_261_pontuacao',
    }

    def _normalizar_infracao(descricao):
        """Extrai tipo normalizado a partir da descrição da infração."""
        desc = (descricao or '').lower()
        for artigo, tipo in _TIPO_MAP.items():
            if artigo in desc:
                return tipo
        # Fallback: primeiras 3 palavras como chave
        import re
        palavras = re.sub(r'[^a-z0-9\s]', '', desc).split()[:3]
        return '_'.join(palavras)[:50] if palavras else 'generico'

    vertex = VertexAIClient()
    perplexity = PerplexityClient()
    gemini = GeminiClient()
    pacotes_gerados = 0
    tipos_processados = set()

    for item in top_infracoes:
        infracao_desc = item['infracao_documento']
        tipo = _normalizar_infracao(infracao_desc)

        # Evita duplicatas de tipo normalizado
        if tipo in tipos_processados:
            continue
        tipos_processados.add(tipo)

        # Verifica se já existe pacote válido (< 7 dias)
        cache_key = f"tese_{tipo}"
        existing = PjariCacheEntry.objects.filter(cache_key=cache_key).first()
        if existing and not existing.is_stale and existing.pacote_compilado:
            logger.info("[CAG] Pacote '%s' ainda válido (hits=%d) — skip", cache_key, existing.hit_count)
            continue

        # Busca Vertex + Perplexity em paralelo
        query_vertex = f"Legislação e normas aplicáveis à infração: {infracao_desc}"
        query_perplexity = f"Jurisprudência CETRAN-SC e CONTRAN sobre: {infracao_desc}"

        vertex_result = ""
        perplexity_result = ""

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                v_fut = ex.submit(vertex.search_documents, None, query_vertex)
                p_fut = ex.submit(perplexity.search_tese, None, query_perplexity)
                try:
                    vertex_result = v_fut.result(timeout=120) or ""
                except Exception as e:
                    logger.warning("[CAG] Vertex falhou para '%s': %s", tipo, e)
                try:
                    perplexity_result = p_fut.result(timeout=150) or ""
                except Exception as e:
                    logger.warning("[CAG] Perplexity falhou para '%s': %s", tipo, e)
        finally:
            from django.db import close_old_connections
            close_old_connections()

        if not vertex_result and not perplexity_result:
            logger.warning("[CAG] Sem resultado RAG para '%s' — skip", tipo)
            continue

        # Pré-digestão via Gemini
        pacote = _digerir_pacote(gemini, infracao_desc, vertex_result, perplexity_result)
        if not pacote:
            continue

        # Salva ou atualiza
        if existing:
            existing.vertex_result = vertex_result
            existing.perplexity_result = perplexity_result
            existing.pacote_compilado = pacote
            existing.tipo_infracao = tipo
            existing.save()
        else:
            PjariCacheEntry.objects.create(
                cache_key=cache_key,
                vertex_result=vertex_result,
                perplexity_result=perplexity_result,
                pacote_compilado=pacote,
                tipo_infracao=tipo,
            )

        pacotes_gerados += 1
        logger.info("[CAG] Pacote '%s' gerado/atualizado com sucesso (%d chars)", cache_key, len(pacote))

    logger.info("[CAG] Concluído: %d pacotes gerados/atualizados de %d tipos", pacotes_gerados, len(tipos_processados))
    return f"{pacotes_gerados} pacotes"


def _digerir_pacote(gemini, infracao_desc, vertex_result, perplexity_result):
    """Sintetiza Vertex + Perplexity em pacote normativo compacto via Gemini."""
    if not gemini.client:
        return None

    prompt = (
        f"INFRAÇÃO: {infracao_desc}\n\n"
        f"=== CORPUS NORMATIVO (Vertex AI) ===\n{vertex_result[:6000]}\n\n"
        f"=== JURISPRUDÊNCIA (Perplexity) ===\n{perplexity_result[:6000]}\n\n"
        "Sintetize o material acima em um PACOTE NORMATIVO COMPACTO contendo:\n"
        "1. Artigos do CTB aplicáveis (com redação resumida)\n"
        "2. Resoluções CONTRAN/CETRAN-SC relevantes (número + ementa)\n"
        "3. Top 5 jurisprudências mais citadas (tribunal + número + tese)\n"
        "4. Teses de defesa mais comuns para esta infração\n"
        "5. Pontos de atenção para o relator\n\n"
        "REGRAS:\n"
        "- Máximo 2000 tokens\n"
        "- Sem opinião — apenas fatos normativos\n"
        "- Formato: texto corrido com subtítulos em negrito\n"
        "- Cite artigos e resoluções com números exatos"
    )

    try:
        import time
        start = time.time()
        response = gemini.client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt],
            config={'temperature': 0.1},
        )
        result = (response.text or "").strip()
        gemini._log_tokens(None, response, 'CAG Pré-digestão', model_name='gemini-2.5-flash', start_time=start)
        if len(result) < 100:
            logger.warning("[CAG] Pacote muito curto para '%s' (%d chars)", infracao_desc[:50], len(result))
            return None
        return result
    except Exception as e:
        logger.error("[CAG] Digestão falhou para '%s': %s", infracao_desc[:50], e)
        return None


@shared_task
def send_payment_notification_task(nome_cliente, email_cliente, trans_amount, payment_id):
    from django.core.mail import send_mail
    from django.conf import settings
    admin_email = getattr(settings, 'ADMIN_EMAIL', '') or getattr(settings, 'DEFAULT_FROM_EMAIL', 'validacao@pjarisc.com.br')
    send_mail(
        subject=f'[P-JARI] Nova Venda Confirmada — {nome_cliente}',
        message=(
            f"Pagamento aprovado via Stripe e créditos liberados com sucesso.\n\n"
            f"Cliente : {nome_cliente}\n"
            f"E-mail  : {email_cliente}\n"
            f"Valor   : R$ {trans_amount:.2f}\n"
            f"ID      : {payment_id}\n"
        ),
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'validacao@pjarisc.com.br'),
        recipient_list=[admin_email],
        fail_silently=False,
    )
