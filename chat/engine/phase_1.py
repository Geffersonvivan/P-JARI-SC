"""
Fase 1 — Coleta de dados (upload PDFs + campos sequenciais) e
Fase 10 — Confirmação do auto-preenchimento (formulário Gemini).
"""

import datetime
import json as _json
import logging

logger = logging.getLogger(__name__)

# ── Prompts (get_current_prompt) ──────────────────────────────────────────────

def get_prompt(parecer) -> str:
    """Retorna o próximo campo a preencher na coleta sequencial (fase 1)."""
    if not parecer.consolidado_pdf_path:
        return "1. Faça o upload do **Consolidado do processo** (PDF único)."
    elif not parecer.data_sessao:
        return "2. Informe a **Data da Sessão de Julgamento** (DD/MM/AAAA):"
    elif not parecer.data_protocolo:
        return "3. Informe a **Data do protocolo do recurso JARI** (DD/MM/AAAA):"
    elif not parecer.paginas_defesa:
        return "4. Informe as **Páginas da defesa Recurso JARI** (ex: 15-24):"
    return "Fase 1 concluída."


def get_confirm_prompt(parecer) -> str:
    """Retorna o payload JSON para o formulário de confirmação do auto-preenchimento."""
    dados = parecer.fase1_extracao_json or {}
    return f"[FASE1_CONFIRM:{_json.dumps(dados, ensure_ascii=False)}]"


# ── Processamento de mensagens ────────────────────────────────────────────────

def process(engine, message: str, uploaded_files: list) -> str:
    """Processa entradas do usuário durante a coleta sequencial (fase 1)."""
    parecer = engine.parecer
    val = message.strip() if message else ""

    # 1. Upload de PDFs
    if not parecer.consolidado_pdf_path:
        if uploaded_files:
            return _handle_upload(engine, uploaded_files)
        elif val.lower() == 'ok':
            # D12 FIX: modo simulado offline só disponível em DEBUG
            from django.conf import settings as _settings
            if not getattr(_settings, 'DEBUG', False):
                return "❌ Modo simulado indisponível em produção. Anexe o arquivo real para prosseguir."
            parecer.autuacao_pdf_path = "upload_simulado_autuacao.pdf"
            parecer.consolidado_pdf_path = "upload_simulado_recurso.pdf"
            parecer.infracao_documento = "DIRIGIR SOB A INFLUENCIA DE ALCOOL"
            parecer.save()
            return engine.get_current_prompt()
        else:
            return "Por favor, o Consolidado é essencial para avançarmos. Anexe o PDF e envie. (Ou digite 'ok' para modo simulado se estiver testando offline)."

    # 2. Dados sequenciais após upload
    if not parecer.data_sessao:
        try:
            parecer.data_sessao = datetime.datetime.strptime(val, "%d/%m/%Y").date()
        except Exception:
            return f"❌ Erro ao ler a data {val}. O formato deve ser DD/MM/AAAA. Ex: 15/05/2024. Tente novamente."
    elif not parecer.data_protocolo:
        try:
            parecer.data_protocolo = datetime.datetime.strptime(val, "%d/%m/%Y").date()
        except Exception:
            return f"❌ Erro ao ler a data de protocolo {val}. O formato deve ser DD/MM/AAAA."
    elif not parecer.paginas_defesa:
        parecer.paginas_defesa = val
        # Último campo: avança para Fase 2 via Celery
        from chat.engine import FASE_DIR
        parecer.status_fase = FASE_DIR
        parecer.save()
        from chat.tasks import processar_fase2_task
        task = processar_fase2_task.delay(parecer.id)
        return _json.dumps({"status": "celery", "task_id": task.id, "type": "FASE2"})

    try:
        parecer.save()
    except Exception as e:
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        logger.error(f"Erro ao salvar dado na Fase 1 do JariEngine: {e}")
        return f"❌ Erro ao processar a informação inserida. Verifique o formato e tente novamente (Erro: {str(e)[:50]})."

    return engine.get_current_prompt()


def process_confirm(engine, message: str) -> str:
    """Processa o formulário de confirmação do auto-preenchimento (fase 10)."""
    parecer = engine.parecer
    stripped = message.strip()
    if not stripped.startswith("FASE1_CONFIRM:"):
        return "❌ Resposta inesperada. Use o formulário acima para confirmar os dados."
    try:
        payload = _json.loads(stripped[len("FASE1_CONFIRM:"):])
    except Exception:
        return "❌ Erro ao processar formulário. Tente novamente."

    def _parse_date_flex(s):
        """D6 FIX: normaliza datas do Gemini para date — aceita DD/MM/AAAA e YYYY-MM-DD."""
        s = (s or "").strip()
        if not s:
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                pass
        return None

    # data_sessao é obrigatória
    ds = payload.get("data_sessao", "").strip()
    if not ds:
        return "❌ A **Data da Sessão** é obrigatória. Preencha o campo e confirme novamente."
    _ds_parsed = _parse_date_flex(ds)
    if not _ds_parsed:
        return f"❌ Data da Sessão inválida: '{ds}'. Use o formato DD/MM/AAAA."
    parecer.data_sessao = _ds_parsed

    # Campos opcionais
    parecer.recorrente = (payload.get("recorrente") or parecer.recorrente or "").upper() or None

    dp = payload.get("data_protocolo", "").strip()
    if dp:
        _dp_parsed = _parse_date_flex(dp)
        if not _dp_parsed:
            return f"❌ Data de Protocolo inválida: '{dp}'. Use DD/MM/AAAA."
        parecer.data_protocolo = _dp_parsed

    pg = payload.get("paginas_defesa", "").strip()
    if pg:
        parecer.paginas_defesa = pg

    # Validação dos campos mínimos
    faltando = []
    if not parecer.data_protocolo: faltando.append("Data do Protocolo")
    if not parecer.paginas_defesa: faltando.append("Páginas da Defesa")
    if faltando:
        return f"❌ Os seguintes campos são obrigatórios: **{', '.join(faltando)}**. Preencha e confirme novamente."

    # ── Modo unificado: salvar campos F2 do payload e pular direto para F3 ──
    from django.conf import settings as _settings_confirm
    if getattr(_settings_confirm, 'UNIFIED_FASE1_FASE2', False) and parecer.tabela_datas_sensiveis:
        # Salvar edições de tipo_penalidade e data_totalizacao_pontos do formulário
        _tp = payload.get("tipo_penalidade", "").lower().strip()
        if _tp and _tp != 'nao_determinado':
            parecer.tipo_penalidade = _tp
        elif _tp == '':
            pass  # Manter o que o Gemini extraiu

        _dtp = payload.get("data_totalizacao_pontos", "").strip()
        if _dtp:
            _dtp_parsed = _parse_date_flex(_dtp)
            if _dtp_parsed:
                parecer.data_totalizacao_pontos = _dtp_parsed

        # Fast-path: F3-PRE já calculou admissibilidade em background
        from chat.engine import FASE_ADMISSIBILIDADE_GERADA, FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE
        if parecer.admissibilidade_texto:
            parecer.status_fase = FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE
            parecer.save()
            logger.info("[UNIFIED→31] pré-cálculo F3 reutilizado. parecer=%s", parecer.id)
            return engine.get_current_prompt()

        parecer.status_fase = FASE_ADMISSIBILIDADE_GERADA
        parecer.save()
        from chat.tasks import processar_fase3_admissibilidade_task
        task = processar_fase3_admissibilidade_task.delay(parecer.id)
        return _json.dumps({"status": "celery", "task_id": task.id, "type": "FASE3_ADM"})

    # ── Modo legado: disparar Fase 2 separada ──
    from chat.engine import FASE_DIR
    parecer.status_fase = FASE_DIR
    parecer.save()
    from chat.tasks import processar_fase2_task
    task = processar_fase2_task.delay(parecer.id)
    return _json.dumps({"status": "celery", "task_id": task.id, "type": "FASE2"})


# ── Celery task ───────────────────────────────────────────────────────────────

def run_autopreenchimento(engine) -> str:
    """
    Fase 1 — Auto-preenchimento via Gemini.
    Chamado pelo Celery task processar_fase1_task.
    Se bem-sucedido, avança para FASE_AGUARDA_CONFIRMACAO_FASE1 (10).
    Se falhar, volta ao fluxo manual (FASE_COLETA=1).
    """
    parecer = engine.parecer
    
    # Extração pesada em background para não quebrar o gunicorn (Broken Pipe)
    if parecer.consolidado_pdf_path and not parecer.infracao_documento:
        try:
            from chat.pdf_extractor import PDFExtractor
            _con = str(parecer.consolidado_pdf_path) if hasattr(parecer.consolidado_pdf_path, 'name') else str(parecer.consolidado_pdf_path)
            infracao = PDFExtractor.extract_infracao_from_pdf(_con)
            if infracao:
                parecer.infracao_documento = infracao
                parecer.save()
        except Exception as e:
            logger.warning(f"run_fase1_autopreenchimento: erro no pyMuPDF falha silenciosa permitida ({e})")

    # ── Extrair apenas o Recorrente do PDF (sem chamada de API) ──
    try:
        from chat.pdf_extractor import PDFExtractor
        from chat.integrations.perplexity import _p
        import re as _re

        _con = _p(parecer.consolidado_pdf_path)
        if _con and "upload_simulado" not in _con and not parecer.recorrente:
            md = PDFExtractor.extract_structured_markdown(_con, label="CONSOLIDADO", max_pages=10)
            if md:
                # Buscar nome do recorrente via padrões comuns nos documentos
                _patterns = [
                    r'(?:RECORRENTE|CONDUTOR|AUTUADO|INTERESSADO)\s*[:\-–]\s*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ\s\.]{3,60})',
                    r'condutor\(?a?\)?\s+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ\s\.]{3,60})',
                ]
                for pat in _patterns:
                    m = _re.search(pat, md)
                    if m:
                        _nome = m.group(1).strip().rstrip(',.')
                        if len(_nome) > 3:
                            parecer.recorrente = _nome[:250].upper()
                            logger.info(f"[FASE1_AUTO] parecer={parecer.id} recorrente extraído via regex: {parecer.recorrente}")
                            break
    except Exception as e:
        logger.warning(f"[FASE1_AUTO] parecer={parecer.id} erro ao extrair recorrente: {e}")

    from chat.engine import FASE_AGUARDA_CONFIRMACAO_FASE1
    parecer.fase1_extracao_json = {}
    parecer.status_fase = FASE_AGUARDA_CONFIRMACAO_FASE1
    parecer.save()

    logger.info(f"[FASE1_AUTO] parecer={parecer.id} extração OK (somente recorrente via regex)")
    return engine.get_current_prompt()


# ── Auxiliar interno ──────────────────────────────────────────────────────────

def _handle_upload(engine, uploaded_files: list) -> str:
    """Classifica os PDFs recebidos e dispara a task Celery de auto-preenchimento."""
    parecer = engine.parecer

    # O Consolidado é o documento principal — autuacao recebe o mesmo arquivo
    file_consolidado = uploaded_files[0]
    file_autuacao = file_consolidado

    parecer.autuacao_pdf_path = file_autuacao
    parecer.consolidado_pdf_path = file_consolidado

    parecer.save()
    from chat.tasks import processar_fase1_task
    task = processar_fase1_task.delay(parecer.id)
    return _json.dumps({"status": "celery", "task_id": task.id, "type": "FASE1"})
