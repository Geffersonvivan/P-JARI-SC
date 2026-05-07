"""
Fase 5 — Geração do Parecer Técnico Final (Anthropic/Claude via Celery).
"""

import re
import json
import logging

logger = logging.getLogger(__name__)


def process_direct(parecer) -> str:
    """Acionado quando o processo chega à fase 5 sem passar pela confirmação de teses."""
    from chat.tasks import gerar_parecer_task
    task = gerar_parecer_task.delay(parecer.id)
    return json.dumps({"status": "celery", "task_id": task.id, "type": "DIRETO"})


def run_llm_phases(engine, task_id=None) -> str:
    """
    Executa a Fase 5 (Parecer Bloco Único via Anthropic) e avança para Fase 6.
    Chamado pelo Celery task gerar_parecer_task.
    """
    import time as _time
    import concurrent.futures
    from chat.integrations import PerplexityClient, VertexAIClient, AnthropicClient
    from chat.engine import FASE_AUDITORIA
    from chat.engine import _p as _engine_p

    parecer = engine.parecer
    _t0 = _time.time()
    logger.info("[FASE5] START parecer=%s task=%s", parecer.id, task_id)

    perplexity = PerplexityClient()
    vertex = VertexAIClient()
    anthropic = AnthropicClient()

    tese = parecer.tese or "MÉRITO PREJUDICADO."
    logger.info("[FASE5] tese=%s", repr(tese[:80]))

    # ── RAG (Vertex + Perplexity) ─────────────────────────────────────────────
    if "PREJUDICADO" in tese:
        vertex_result = "Não aplicável."
        perplexity_result = "Não aplicável por ausência de mérito."
    else:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        v_future = None
        p_future = None
        try:
            if not parecer.vertex_result:
                v_future = executor.submit(vertex.search_documents, parecer, tese)
            if not parecer.perplexity_result:
                p_future = executor.submit(perplexity.search_tese, parecer, tese)

            try:
                vertex_result = v_future.result(timeout=90) if v_future else parecer.vertex_result
            except concurrent.futures.TimeoutError:
                logger.warning("[FASE5] TIMEOUT Vertex AI (90s) — usando fallback")
                vertex_result = "Sistema RAG offline por timeout. Use conhecimento prévio do CTB."
            except Exception as e:
                logger.error("[FASE5] ERRO Vertex AI: %s", e)
                vertex_result = f"Vertex AI indisponível: {e}"

            try:
                perplexity_result = p_future.result(timeout=90) if p_future else parecer.perplexity_result
            except concurrent.futures.TimeoutError:
                logger.warning("[FASE5] TIMEOUT Perplexity (90s) — usando fallback")
                perplexity_result = "Pesquisa jurisprudencial offline por timeout."
            except Exception as e:
                logger.error("[FASE5] ERRO Perplexity: %s", e)
                perplexity_result = f"Perplexity indisponível: {e}"
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            from django.db import close_old_connections
            close_old_connections()

    # ── Geração do parecer (Claude único) ────────────────────────────────────
    logger.info("[FASE5] Vertex/Perplexity prontos em %.1fs — gerando parecer via Claude", _time.time()-_t0)

    parecer_text = anthropic.validate_and_generate_parecer(
        parecer, tese, perplexity_result, vertex_result, task_id=task_id
    )
    logger.info("[FASE5] Claude concluído em %.1fs — len=%d", _time.time()-_t0, len(parecer_text or ''))

    # ── Extrai Dossiê de Fontes ───────────────────────────────────────────────
    dossie = ""
    match_start = re.search(r'\*?\*?\*?DOSSIE_START\*?\*?\*?', parecer_text)
    match_end = re.search(r'\*?\*?\*?DOSSIE_END\*?\*?\*?', parecer_text)

    if match_start and match_end:
        dossie_bruto = parecer_text[match_start.end():match_end.start()].strip()
        texto_principal = parecer_text[:match_start.start()].strip()
        if texto_principal.endswith("---"):
            texto_principal = texto_principal[:-3].strip()
        parecer_text = texto_principal
        dossie = dossie_bruto

    parecer.parecer_final = parecer_text
    parecer.dossie_fontes = dossie
    parecer.fase5_provider = 'Claude'

    # ── Limpeza de PDFs do storage (somente após parecer válido) ─────────────
    _parecer_valido = (
        parecer_text
        and not parecer_text.startswith("⚠️")
        and "ERRO DE CONFIGURAÇÃO" not in parecer_text
        and len(parecer_text) > 200
    )

    if _parecer_valido:
        from django.core.files.storage import default_storage

        _aut_path = _engine_p(parecer.autuacao_pdf_path)
        if _aut_path and "upload_simulado" not in _aut_path:
            try:
                if default_storage.exists(_aut_path):
                    default_storage.delete(_aut_path)
            except Exception as e:
                logger.error("Erro ao deletar autuação PDF do storage: %s", e)
            parecer.autuacao_pdf_path = None

        _con_path = _engine_p(parecer.consolidado_pdf_path)
        # Evita deletar duas vezes se autuação e consolidado forem o mesmo arquivo
        if _con_path and "upload_simulado" not in _con_path and _con_path != _aut_path:
            try:
                if default_storage.exists(_con_path):
                    default_storage.delete(_con_path)
            except Exception as e:
                logger.error("Erro ao deletar consolidado PDF do storage: %s", e)
            parecer.consolidado_pdf_path = None
    else:
        logger.warning("[FASE5] parecer=%s — geração falhou ou texto inválido; PDFs preservados para reanálise.", parecer.id)

    parecer.status_fase = FASE_AUDITORIA
    parecer.save()

    return (
        f"**Parecer Técnico Gerado com Sucesso!**\n\n"
        f"{parecer.parecer_final}\n\n"
        f"---\n\n"
        f"Digite **'ok'** para prosseguir."
    )
