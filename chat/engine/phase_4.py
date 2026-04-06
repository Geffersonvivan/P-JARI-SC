"""
Fase 4 — Extração e análise de teses defensivas.
"""

import logging

logger = logging.getLogger(__name__)


def get_prompt(parecer) -> str:
    """Exibe a tese extraída e pede confirmação."""
    return (
        f"**Extração da Tese da Defesa**\n\n"
        f"O P-JARI analisou o recurso nas páginas informadas ({parecer.paginas_defesa}) e identificou a seguinte tese principal:\n\n"
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
    """Extrai a tese automaticamente do PDF via Gemini."""
    from chat.integrations import GeminiClient
    from chat.engine import FASE_MERITO

    parecer = engine.parecer
    gemini = GeminiClient()
    tese_extraida = gemini.extract_tese(parecer)

    parecer.tese = tese_extraida
    parecer.status_fase = FASE_MERITO
    parecer.save()

    return engine.get_current_prompt()


def run_refinement(engine, user_hint: str) -> str:
    """Refina a tese com base na dica do julgador."""
    from chat.integrations import GeminiClient

    parecer = engine.parecer
    gemini = GeminiClient()
    tese_refinada = gemini.refine_tese(parecer, user_hint)

    parecer.tese = tese_refinada
    parecer.save()

    return engine.get_current_prompt()


def analise_tese(engine) -> str:
    """Dispara Perplexity + Vertex + Gemini para análise cruzada das teses."""
    from chat.integrations import PerplexityClient, GeminiClient, VertexAIClient
    from chat.models import PjariCacheConfig, PjariCacheEntry
    from chat.engine import FASE_AGUARDA_CONFIRMACAO_MERITO
    import concurrent.futures

    parecer = engine.parecer
    perplexity = PerplexityClient()
    gemini = GeminiClient()
    vertex = VertexAIClient()
    tese = parecer.tese or ""

    # ── PJARI-CACHE ───────────────────────────────────────────────────────────
    cache_config, _ = PjariCacheConfig.objects.get_or_create(id=1)
    vertex_result = None
    perplexity_result = None

    if cache_config.is_active:
        cache_config.total_requests += 1
        nucleo = gemini.get_cache_key_from_tese(tese)
        chave = f"tese_{nucleo}"
        cache_entry = PjariCacheEntry.objects.filter(cache_key=chave).first()
        if cache_entry:
            vertex_result = cache_entry.vertex_result
            perplexity_result = cache_entry.perplexity_result
            cache_entry.hit_count += 1
            cache_entry.save()
            cache_config.total_hits += 1
        cache_config.save()

    # ── Busca externa (cache miss ou desativado) ──────────────────────────────
    if not vertex_result or not perplexity_result:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            v_future = executor.submit(vertex.search_documents, parecer, tese)
            p_future = executor.submit(perplexity.search_tese, parecer, tese)
            vertex_result = v_future.result(timeout=90)
            perplexity_result = p_future.result(timeout=90)

        if cache_config.is_active and "erro" not in chave.lower():
            try:
                PjariCacheEntry.objects.create(
                    cache_key=chave,
                    vertex_result=vertex_result,
                    perplexity_result=perplexity_result
                )
            except Exception as e:
                logger.error("Erro ao salvar no PJARI-CACHE: %s", e)

    # ── Análise de teses ──────────────────────────────────────────────────────
    analise_resultado = gemini.analyze_tese(parecer, tese, perplexity_result, vertex_result)

    parecer.analise_tese_texto = analise_resultado
    parecer.vertex_result = vertex_result
    parecer.perplexity_result = perplexity_result
    parecer.status_fase = FASE_AGUARDA_CONFIRMACAO_MERITO
    parecer.save()

    return engine.get_current_prompt()
