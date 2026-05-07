"""
Fase 4 — Extração e análise de teses defensivas.
"""

import logging

logger = logging.getLogger(__name__)


def get_prompt(parecer) -> str:
    """Exibe a tese extraída e pede confirmação."""
    return (
        f"**Extração da Tese da Defesa**\n\n"
        f"O recurso nas páginas informadas ({parecer.paginas_defesa}) foi analisado e a seguinte tese principal foi identificada:\n\n"
        f"**{parecer.tese}**\n\n"
        f"Digite **'ok'** para prosseguir."
    )


def process(engine, message: str) -> str:
    """Processa a resposta do julgador na fase 4."""
    import json
    if message.lower().strip() != 'ok':
        return run_refinement(engine, message.strip())
    # Análise de teses (Perplexity + Vertex + Gemini) pode ultrapassar o timeout do gunicorn.
    # Despacha para o worker Celery, igual ao padrão das demais fases com chamadas LLM.
    from chat.tasks import processar_fase4_analise_task
    task = processar_fase4_analise_task.delay(engine.parecer.id)
    return json.dumps({"status": "celery", "task_id": task.id, "type": "FASE4_ANALISE"})


def run_extraction(engine) -> str:
    """Extrai a tese automaticamente do PDF via Gemini.
    Se nenhuma tese for identificada, seta mensagem padrão e roteia diretamente para INDEFERIDO (§425-427).
    """
    import json
    from chat.integrations import AnthropicClient
    from chat.engine import FASE_MERITO, FASE_RESULTADO

    parecer = engine.parecer
    anthropic = AnthropicClient()
    tese_extraida = anthropic.extract_tese(parecer)

    # C5 FIX §425-427: tese vazia → INDEFERIDO por ausência de fundamentação recursal
    if not tese_extraida or not tese_extraida.strip():
        logger.warning("[FASE4] Nenhuma tese identificada — roteando para INDEFERIDO (§425-427): parecer=%s", parecer.id)
        parecer.tese = "Nenhuma tese defensiva identificada na peça recursal."
        parecer.status_fase = FASE_RESULTADO
        parecer.save()
        from chat.tasks import gerar_parecer_task
        task = gerar_parecer_task.delay(parecer.id)
        # Retorna marcador interno para processar_fase4_task encadear via SSE
        return json.dumps({"__chained": True, "task_id": task.id, "task_type": "PREJUDICIALIDADE"})

    parecer.tese = tese_extraida
    parecer.status_fase = FASE_MERITO
    parecer.save()

    return engine.get_current_prompt()


def run_refinement(engine, user_hint: str) -> str:
    """Refina a tese com base na dica do julgador."""
    from chat.integrations import AnthropicClient

    parecer = engine.parecer
    anthropic = AnthropicClient()
    tese_refinada = anthropic.refine_tese(parecer, user_hint)

    parecer.tese = tese_refinada
    parecer.save()

    return engine.get_current_prompt()


def analise_tese(engine) -> str:
    """Dispara Perplexity + Vertex + Gemini para análise cruzada das teses."""
    from chat.integrations import PerplexityClient, AnthropicClient, VertexAIClient
    from chat.models import PjariCacheConfig, PjariCacheEntry
    from chat.engine import FASE_AGUARDA_CONFIRMACAO_MERITO
    import concurrent.futures

    parecer = engine.parecer
    perplexity = PerplexityClient()
    anthropic = AnthropicClient()
    vertex = VertexAIClient()
    tese = parecer.tese or ""

    # ── PJARI-CACHE (com suporte a pacotes pré-digeridos CAG) ───────────────
    cache_config, _ = PjariCacheConfig.objects.get_or_create(id=1)
    vertex_result = None
    perplexity_result = None
    _pacote_cag = None
    chave = None

    if cache_config.is_active:
        cache_config.total_requests += 1

        # 1) Tenta pacote pré-digerido por tipo de infração (CAG — mais rápido)
        _infracao = parecer.infracao_documento or ""
        if _infracao:
            # Busca por artigo do CTB na descrição da infração
            import re as _re_norm
            _nums = _re_norm.findall(r'\d{3}', _infracao)
            _cag_entry = None
            for _n in _nums:
                _cag_entry = PjariCacheEntry.objects.filter(
                    tipo_infracao__icontains=_n,
                    pacote_compilado__isnull=False,
                ).first()
                if _cag_entry:
                    break
            # Fallback: busca por substring no cache_key
            if not _cag_entry:
                for _n in _nums:
                    _cag_entry = PjariCacheEntry.objects.filter(
                        cache_key__icontains=_n,
                        pacote_compilado__isnull=False,
                    ).first()
                    if _cag_entry:
                        break
            if _cag_entry and not _cag_entry.is_stale:
                vertex_result = _cag_entry.vertex_result
                perplexity_result = _cag_entry.perplexity_result
                _pacote_cag = _cag_entry.pacote_compilado
                _cag_entry.hit_count += 1
                _cag_entry.save(update_fields=['hit_count'])
                cache_config.total_hits += 1
                logger.info("[FASE4-CAG] Hit pacote pré-digerido '%s' (hits=%d) para parecer=%s",
                            _cag_entry.cache_key, _cag_entry.hit_count, parecer.id)

        # 2) Fallback: cache por núcleo da tese (padrão existente)
        if not vertex_result or not perplexity_result:
            nucleo = anthropic.get_cache_key_from_tese(tese)
            import re as _re_cache
            nucleo = _re_cache.sub(r'[^a-zA-Z0-9_\-]', '_', nucleo)[:200]
            chave = f"tese_{nucleo}"
            cache_entry = PjariCacheEntry.objects.filter(cache_key=chave).first()
            if cache_entry:
                vertex_result = cache_entry.vertex_result
                perplexity_result = cache_entry.perplexity_result
                cache_entry.hit_count += 1
                cache_entry.save(update_fields=['hit_count'])
                cache_config.total_hits += 1

        cache_config.save()

    # ── Busca externa (cache miss ou desativado) ──────────────────────────────
    if not vertex_result or not perplexity_result:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        try:
            v_future = executor.submit(vertex.search_documents, parecer, tese)
            p_future = executor.submit(perplexity.search_tese, parecer, tese)

            try:
                vertex_result = v_future.result(timeout=120)  # M8: 120s (era 90s)
            except concurrent.futures.TimeoutError:
                logger.warning("Vertex timeout na análise de tese (parecer=%s) — fallback vazio.", parecer.id)
                vertex_result = ""
            except Exception as e:
                logger.warning("Vertex erro na análise de tese (parecer=%s): %s — fallback vazio.", parecer.id, e)
                vertex_result = ""

            try:
                perplexity_result = p_future.result(timeout=150)  # M8: 150s para Perplexity em consultas complexas (era 90s)
            except concurrent.futures.TimeoutError:
                logger.warning("Perplexity timeout na análise de tese (parecer=%s) — fallback vazio.", parecer.id)
                perplexity_result = ""
            except Exception as e:
                logger.warning("Perplexity erro na análise de tese (parecer=%s): %s — fallback vazio.", parecer.id, e)
                perplexity_result = ""
        finally:
            # shutdown(wait=False): não bloqueia o worker aguardando threads travadas de rede.
            # Threads daemon são encerradas automaticamente quando o processo termina.
            executor.shutdown(wait=False)
            # Fecha conexões DB deixadas pelas threads (Vertex/Perplexity abrem logs de tokens).
            # Sem isso, conexões ficam em estado inconsistente para o próximo save() do worker.
            from django.db import close_old_connections
            close_old_connections()

        if cache_config.is_active:
            if not chave:
                nucleo = anthropic.get_cache_key_from_tese(tese)
                import re as _re_cache2
                nucleo = _re_cache2.sub(r'[^a-zA-Z0-9_\-]', '_', nucleo)[:200]
                chave = f"tese_{nucleo}"
            if "erro" not in chave.lower():
                try:
                    PjariCacheEntry.objects.create(
                        cache_key=chave,
                        vertex_result=vertex_result,
                        perplexity_result=perplexity_result,
                    )
                except Exception as e:
                    logger.error("Erro ao salvar no PJARI-CACHE: %s", e)

    # ── Análise de teses ──────────────────────────────────────────────────────
    analise_resultado = anthropic.analyze_tese(parecer, tese, perplexity_result, vertex_result)

    parecer.analise_tese_texto = analise_resultado
    parecer.vertex_result = vertex_result
    parecer.perplexity_result = perplexity_result

    # Quando prejudicado (prescrição/decadência/inadmissibilidade), o gemini retorna texto
    # sem marcadores [DECISAO_TESE_X]. Nesse caso não há confirmação do julgador —
    # vai direto para FASE_RESULTADO e dispara o parecer automaticamente.
    if '[DECISAO_TESE_' not in analise_resultado:
        import json as _json
        from chat.engine import FASE_RESULTADO
        parecer.status_fase = FASE_RESULTADO
        parecer.save()
        from chat.tasks import gerar_parecer_task
        task = gerar_parecer_task.delay(parecer.id)
        return _json.dumps({"__chained": True, "task_id": task.id, "task_type": "PREJUDICIALIDADE"})

    parecer.status_fase = FASE_AGUARDA_CONFIRMACAO_MERITO
    parecer.save()

    return engine.get_current_prompt()
