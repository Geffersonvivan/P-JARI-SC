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
        p = Parecer.objects.only("status_fase", "session_key").get(pk=parecer_id)
        sentry_sdk.set_context("parecer", {
            "id": parecer_id,
            "status_fase": p.status_fase,
        })
        sentry_sdk.set_user({"id": str(p.session_key)})
    except Exception:
        pass

def _is_transient_llm_error(e) -> bool:
    """Retorna True para erros transitórios de LLM (Anthropic ou Gemini)."""
    s = str(e)
    return any(k in s for k in (
        '504', '529', '502', '503',
        'DEADLINE_EXCEEDED', 'ServerError',
        'timeout', 'Timeout', 'overloaded',
        'rate_limit', 'RateLimitError',
        'InternalServerError', 'APIConnectionError',
    ))


def _is_permanent_llm_error(e) -> bool:
    """Retorna True para erros permanentes de LLM (billing, API key, acesso negado).
    Retry não resolve esses erros — requerem intervenção humana."""
    s = str(e)
    return any(k in s for k in (
        'PERMISSION_DENIED', 'denied access',
        'API_KEY_INVALID', 'API key not valid',
        'billing', 'account is inactive',
        'has been denied access',
    ))


_PERMANENT_ERROR_FINGERPRINT = ['llm-permanent-access-error']
_PERMANENT_USER_MSG = (
    "⚠️ O serviço de IA está temporariamente indisponível. "
    "Aguarde alguns instantes e tente novamente. "
    "Se o problema persistir, contate o administrador."
)


def _handle_permanent_error(e, parecer_id: int, fase: str):
    """Trata erros permanentes de LLM: loga CRITICAL, agrupa no Sentry, salva msg amigável."""
    logger.critical(
        "LLM ACESSO NEGADO (Parecer %s, fase %s): %s",
        parecer_id, fase, e,
    )
    sentry_sdk.capture_message(
        f"LLM acesso negado — fase={fase}, parecer={parecer_id}: {str(e)[:200]}",
        level="error",
        fingerprint=_PERMANENT_ERROR_FINGERPRINT,
    )
    try:
        from .models import ChatMessage
        _p = Parecer.objects.get(id=parecer_id)
        ChatMessage.objects.create(parecer=_p, role='assistant', content=_PERMANENT_USER_MSG)
        log_audit('fase_erro', parecer=_p, fase=fase, dados={'erro': f'ACESSO NEGADO: {str(e)[:150]}'})
    except Exception:
        pass
    raise Exception(f"{_PERMANENT_USER_MSG}")


@shared_task(bind=True, time_limit=480, soft_time_limit=420, max_retries=3, queue='fast')
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

        # No modo unificado F1+F2, já temos os dados de datas/tipo_penalidade.
        # Dispara pré-cálculo da F3 para que esteja pronto quando o usuário confirmar.
        from django.conf import settings as django_settings
        if getattr(django_settings, 'UNIFIED_FASE1_FASE2', False) and parecer.tabela_datas_sensiveis:
            try:
                processar_fase3_precompute_task.delay(parecer_id)
                logger.info("F1 unificada: pré-cálculo F3 disparado (Parecer %s)", parecer_id)
            except Exception as e_pre:
                logger.warning("F1 unificada: falha ao disparar pré-cálculo F3 (Parecer %s): %s", parecer_id, e_pre)

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
        if _is_permanent_llm_error(e):
            _handle_permanent_error(e, parecer_id, fase=1)
        trace = traceback.format_exc()
        if _is_transient_llm_error(e):
            countdown = 10 * (self.request.retries + 1)  # 10s, 20s, 30s (retry interno já aguarda 5-15s)
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
        if _is_permanent_llm_error(e):
            _handle_permanent_error(e, parecer_id, fase=2)
        trace = traceback.format_exc()
        if _is_transient_llm_error(e):
            countdown = 10 * (self.request.retries + 1)  # 10s, 20s, 30s (retry interno já aguarda 5-15s)
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
        if _is_permanent_llm_error(e):
            _handle_permanent_error(e, parecer_id, fase='3_adm')
        trace = traceback.format_exc()
        if _is_transient_llm_error(e):
            countdown = 10 * (self.request.retries + 1)
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
        if _is_permanent_llm_error(e):
            _handle_permanent_error(e, parecer_id, fase=4)
        trace = traceback.format_exc()
        if _is_transient_llm_error(e):
            countdown = 10 * (self.request.retries + 1)  # 10s, 20s, 30s (retry interno já aguarda 5-15s)
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
        if _is_permanent_llm_error(e):
            _handle_permanent_error(e, parecer_id, fase='4_analise')
        trace = traceback.format_exc()
        if _is_transient_llm_error(e):
            countdown = 10 * (self.request.retries + 1)  # 10s, 20s, 30s (retry interno já aguarda 5-15s)
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
        # Retry primeiro para erros transitórios (429, 5xx, timeout)
        # — loga como warning, não error, para não poluir Sentry durante retries
        if _is_permanent_llm_error(e):
            _handle_permanent_error(e, parecer_id, fase=5)
        if _is_transient_llm_error(e):
            countdown = 10 * (self.request.retries + 1)  # 10s, 20s (retry interno já esperou 5-15s)
            logger.warning(f"PARECER transitório (Parecer {parecer_id}), retry {self.request.retries + 1}/2 em {countdown}s: {e}")
            try:
                raise self.retry(exc=e, countdown=countdown)
            except self.MaxRetriesExceededError:
                logger.error(f"PARECER max retries esgotados (Parecer {parecer_id}): {e}")
        else:
            trace = traceback.format_exc()
            logger.error(f"ERRO CELERY (Parecer {parecer_id}): {str(e)}\n\n{trace}")
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
    from chat.integrations import VertexAIClient, PerplexityClient, AnthropicClient
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
    anthropic = AnthropicClient()
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

        # Pré-digestão via Anthropic
        pacote = _digerir_pacote(anthropic, infracao_desc, vertex_result, perplexity_result)
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


def _digerir_pacote(anthropic_client, infracao_desc, vertex_result, perplexity_result):
    """Sintetiza Vertex + Perplexity em pacote normativo compacto via Anthropic."""
    return anthropic_client.digest_cag_package(infracao_desc, vertex_result, perplexity_result)


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


@shared_task(time_limit=900, soft_time_limit=840, queue='heavy', ignore_result=True)
def sync_normativo_drive_task():
    """
    Celery Beat — Sincroniza PDFs normativos do Google Drive para o banco local.
    Roda a cada 6h. Baixa PDFs novos/atualizados, gera embeddings e indexa.
    """
    import os
    _log = logging.getLogger(__name__)

    folder_id = os.environ.get('GDRIVE_NORMATIVO_FOLDER_ID', '')
    if not folder_id:
        _log.info("sync_normativo_drive_task: GDRIVE_NORMATIVO_FOLDER_ID não configurado, pulando.")
        return "SKIP: sem folder_id"

    try:
        from chat.integrations.gdrive_sync import sync_from_drive
        stats = sync_from_drive(folder_id=folder_id)
        msg = (f"Drive sync: {stats['downloaded']} novos, "
               f"{stats['skipped']} pulados, {stats['errors']} erros, "
               f"{stats['total_chunks']} chunks criados")
        _log.info(msg)
        return msg
    except Exception as e:
        _log.exception(f"sync_normativo_drive_task falhou: {e}")
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            send_mail(
                "🚨 JARI: Erro na sincronização Drive → RAG",
                f"A task sync_normativo_drive_task falhou.\n\nErro: {str(e)}",
                settings.DEFAULT_FROM_EMAIL,
                ['geffersonvivan@gmail.com'],
                fail_silently=True,
            )
        except Exception:
            pass
        raise
