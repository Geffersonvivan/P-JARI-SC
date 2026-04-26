import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit
from .home import _get_filter_kwargs


@ratelimit(key='user_or_ip', rate='60/m', method='POST', block=True)
@require_POST
def chat_message_view(request):
    if not request.session.session_key:
        request.session.create()

    filter_kwargs = _get_filter_kwargs(request)

    try:
        from ..services import ChatService
        import json

        if request.content_type and 'multipart/form-data' in request.content_type:
            message = request.POST.get('message', "")
            parecer_id = request.POST.get('parecer_id')
            pasta_id = request.POST.get('pasta_id')
            uploaded_files = ChatService.save_uploaded_files(request.FILES)
        else:
            data = json.loads(request.body)
            message = data.get('message', "")
            parecer_id = data.get('parecer_id')
            pasta_id = data.get('pasta_id')
            uploaded_files = []

        if not (message or uploaded_files):
            return JsonResponse({'error': 'Mensagem inválida'}, status=400)

        if message.strip() == 'RESUMO' and pasta_id:
            return ChatService.handle_resumo_pasta(pasta_id, filter_kwargs)

        elif message.strip() == 'RESUMO_PROJETO' and parecer_id:
            return ChatService.handle_resumo_projeto(parecer_id, filter_kwargs)

        elif not parecer_id and message.strip().lower() == 'iniciar':
            return ChatService.handle_iniciar(request, filter_kwargs)

        elif parecer_id:
            return ChatService.handle_processamento(parecer_id, message, uploaded_files, filter_kwargs)

        return JsonResponse({'reply': "Digite **iniciar** para começar uma nova análise de processo."})

        return JsonResponse({'error': 'Mensagem inválida'}, status=400)
    except Exception as e:
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        return JsonResponse({'error': 'Erro interno. Tente novamente.'}, status=500)


@require_POST
def chat_agent_message_view(request):
    """Novo endpoint isolado para o Agente Lateral (Drawer) da Fase 2."""
    if not request.session.session_key:
        request.session.create()

    filter_kwargs = _get_filter_kwargs(request)

    try:
        import json
        import os
        from django.conf import settings
        from ..models import Parecer
        from ..integrations import GeminiClient, VertexAIClient, PerplexityClient

        data = json.loads(request.body)
        message = data.get('message', "")
        parecer_id = data.get('parecer_id')

        if not message:
            return JsonResponse({'error': 'Mensagem inválida'}, status=400)

        parecer = None
        context_str = "Nenhum processo referenciado. Responda apenas com base na legislação."
        if parecer_id:
            try:
                parecer = Parecer.objects.get(id=parecer_id, **filter_kwargs)
                context_str = (
                    f"PROCESSO (PA): {parecer.pa}\nSGPE: {parecer.sgpe}\n"
                    f"Infração Ocorrida: {parecer.infracao_documento}\n"
                    f"Admissibilidade Contexto: {parecer.admissibilidade_texto}\n"
                    f"Tese do Recorrente: {parecer.tese}\n"
                    f"Datas Sensíveis: {parecer.tabela_datas_sensiveis}\n"
                )
            except Parecer.DoesNotExist:
                pass

        # Le a instrução magna do Agente Lateral (com cache Redis por 1h)
        from django.core.cache import cache
        system_instruction = cache.get('logica_jari_perguntas')
        if system_instruction is None:
            logica_path = os.path.join(settings.BASE_DIR, 'logica_jari_perguntas.md')
            system_instruction = "Você é um Consultor de Rito JARI."
            if os.path.exists(logica_path):
                with open(logica_path, 'r') as f:
                    system_instruction = f.read()
            cache.set('logica_jari_perguntas', system_instruction, timeout=3600)

        # RAG orquestrado e simples
        vertex_results = ""
        perplexity_results = ""

        # Decide se vale acionar o RAG (Heurística simples para não gastar chamadas atoa)
        # Se o usuário perguntar de leis, resoluções ou prazos, aciona Vertex
        msg_lower = message.lower()
        needs_rag = any(kw in msg_lower for kw in ['lei', 'ctb', 'resoluç', 'prazo', 'prescriç', 'decadênc', 'recurso', 'art', 'código'])

        if needs_rag:
            vertex_client = VertexAIClient()
            vertex_results = vertex_client.search_documents(parecer, message, top_k=3)
            # Pula perplexity no fluxo default do agente pra ser rapido (Streaming não está nativo no DJango sem Channels)

        gemini_client = GeminiClient()
        if not gemini_client.client:
             return JsonResponse({'reply': "Simulação: O Agente Lateral está funcionando offline.", 'status': 'success'})

        prompt = (
            f"=== CONTEXTO DO PROCESSO ===\n{context_str}\n\n"
            f"=== JURISPRUDÊNCIA / NORMAS (RAG) ===\n{vertex_results}\n\n"
            f"=== PERGUNTA DO USUÁRIO ===\n{message}\n"
        )

        contents = [prompt]
        response = gemini_client.client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config={'system_instruction': system_instruction}
        )

        if parecer:
            gemini_client._log_tokens(parecer, response, 'Fase 2 (Agente Drawer)', model_name='gemini-2.5-flash')

        return JsonResponse({'reply': response.text, 'status': 'success'})

    except Exception as e:
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        return JsonResponse({'error': 'Erro interno. Tente novamente.'}, status=500)


def check_task_status_view(request, task_id):
    """View endpoint para o frontend perguntar (poll) a cada x segundos se a tarefa pesada de IA no Celery acabou."""
    from celery.result import AsyncResult
    task = AsyncResult(task_id)

    if task.state == 'SUCCESS':
        # Verifica se a task retornou um encadeamento (ex: FASE4 → FASE4_ANALISE)
        result = task.result
        if isinstance(result, str) and result.startswith('{'):
            try:
                import json as _json
                result_data = _json.loads(result)
                if result_data.get('chained'):
                    return JsonResponse({
                        'status': 'CHAINED',
                        'next_task_id': result_data['task_id'],
                        'next_task_type': result_data['task_type'],
                    })
            except Exception:
                pass

        parecer_id = request.GET.get('parecer_id')
        if parecer_id:
            from ..models import Parecer
            try:
                p = Parecer.objects.get(id=parecer_id)
                reply = (
                    f"**Parecer Técnico Gerado com Sucesso!**\n\n"
                    f"{p.parecer_final}\n\n"
                    f"---\n\n"
                    f"Digite **'ok'** para prosseguir."
                )
                return JsonResponse({'status': 'SUCCESS', 'reply': reply, 'status_fase': p.status_fase})
            except Exception as e:
                return JsonResponse({'status': 'FAILURE', 'error': f"Parecer não encontrado. {e}"})

        return JsonResponse({'status': 'SUCCESS', 'reply': "Tarefa concluída, mas Parecer ID não fornecido.", 'status_fase': 6})

    elif task.state == 'FAILURE':
        err = task.info
        err_msg = str(err) if err else 'Falha no processamento. Abra o processo e tente novamente.'
        return JsonResponse({'status': 'FAILURE', 'error': err_msg})

    elif task.state == 'REVOKED':
        return JsonResponse({'status': 'FAILURE', 'error': 'O processamento excedeu o tempo limite e foi interrompido. Abra o processo e tente novamente.'})

    return JsonResponse({'status': 'PROCESSING'})


async def stream_task_status_view(request, task_id):
    """
    View SSE assíncrona (ASGI) — não bloqueia workers Gunicorn.
    Usa redis.asyncio (incluído em redis>=5) e asyncio.sleep para I/O não-bloqueante.
    """
    import asyncio
    import json
    from django.http import StreamingHttpResponse
    from django.conf import settings

    async def event_stream():
        import redis.asyncio as aioredis
        from celery.result import AsyncResult

        r = None
        pubsub = None
        try:
            r = aioredis.from_url(getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0'))
            pubsub = r.pubsub()
            channel_name = f"stream_{task_id}"
            await pubsub.subscribe(channel_name)
        except Exception as e:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
            yield f"data: {json.dumps({'status': 'FAILURE', 'error': 'Redis Inoperante', 'details': str(e)})}\n\n"
            return

        # Timeout máximo: 660s (11 min) — Celery mata tasks em 600s
        import time as _time
        _start = _time.monotonic()
        _MAX_WAIT = 660

        try:
            while True:
                if _time.monotonic() - _start > _MAX_WAIT:
                    yield f"data: {json.dumps({'status': 'FAILURE', 'error': 'O processamento excedeu o tempo limite (11 min). Abra o processo novamente e tente de novo.'})}\n\n"
                    break

                # Await sem bloquear thread — libera o event loop
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message['type'] == 'message':
                    data_str = message['data'].decode('utf-8')
                    yield f"data: {data_str}\n\n"
                else:
                    yield ": keepalive\n\n"
                    # Verifica se a task terminou sem publicar no canal (race condition)
                    try:
                        from asgiref.sync import sync_to_async
                        task = AsyncResult(task_id)
                        if task.state in ['SUCCESS', 'FAILURE', 'REVOKED']:
                            if task.state == 'SUCCESS':
                                try:
                                    parecer_id = request.GET.get('parecer_id')
                                    if parecer_id:
                                        from ..models import Parecer
                                        from ..jari_engine import JariEngine
                                        get_parecer = sync_to_async(Parecer.objects.get)
                                        p = await get_parecer(id=parecer_id)
                                        if p.parecer_final:
                                            reply = (
                                                f"**Parecer Técnico Gerado com Sucesso!**\n\n"
                                                f"{p.parecer_final}\n\n"
                                                f"---\n\n"
                                                f"Digite **'ok'** para prosseguir."
                                            )
                                        else:
                                            get_prompt = sync_to_async(JariEngine(p).get_current_prompt)
                                            reply = await get_prompt()
                                        final_data = json.dumps({'status': 'SUCCESS', 'reply': reply, 'status_fase': p.status_fase})
                                    else:
                                        final_data = json.dumps({'status': 'SUCCESS', 'reply': "Tarefa concluída.", 'status_fase': 6})
                                except Exception as db_err:
                                    final_data = json.dumps({'status': 'FAILURE', 'error': f"Parecer não encontrado. {db_err}"})
                            else:
                                final_data = json.dumps({'status': 'FAILURE', 'error': str(getattr(task, 'info', 'Falha Celery'))})
                            yield f"data: {final_data}\n\n"
                            break
                    except Exception as eval_err:
                        yield f"data: {json.dumps({'status': 'FAILURE', 'error': f'Falha ao ler Task State: {eval_err}'})}\n\n"
                        break
                    await asyncio.sleep(0)  # cede o event loop a outras coroutines
        except Exception as stream_err:
            import logging as _log
            _log.getLogger(__name__).error("SSE async stream error (task=%s): %s", task_id, stream_err)
            try:
                yield f"data: {json.dumps({'status': 'RECONNECT', 'error': str(stream_err)})}\n\n"
            except Exception:
                pass
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception:
                    pass
            if r:
                try:
                    await r.aclose()
                except Exception:
                    pass

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
