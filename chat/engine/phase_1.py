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
    if not parecer.autuacao_pdf_path:
        return "1. Faça o upload dos arquivos **'Autuação', 'Consolidado' e 'Ata'**. (Envie no mínimo Autuação e Consolidado juntos)"
    elif not parecer.data_sessao:
        return "2. Informe a **Data da Sessão de Julgamento** (DD/MM/AAAA):"
    elif not parecer.pa:
        return "3. Informe o número do **Processo Administrativo**:"
    elif not parecer.sgpe:
        return "4. Informe o número do **SGPE**:"
    elif not parecer.prazo_final:
        return "5. Informe o **Prazo Final para protocolo do recurso JARI** (DD/MM/AAAA):"
    elif not parecer.data_protocolo:
        return "6. Informe a **Data do protocolo do recurso JARI** (DD/MM/AAAA):"
    elif not parecer.paginas_defesa:
        return "7. Informe as **Páginas da defesa Recurso JARI** (ex: 15-24):"
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
    if not parecer.autuacao_pdf_path:
        if uploaded_files:
            return _handle_upload(engine, uploaded_files)
        elif val.lower() == 'ok':
            # Modo simulado offline
            parecer.autuacao_pdf_path = "upload_simulado_autuacao.pdf"
            parecer.consolidado_pdf_path = "upload_simulado_recurso.pdf"
            parecer.infracao_documento = "DIRIGIR SOB A INFLUENCIA DE ALCOOL"
            parecer.save()
            return engine.get_current_prompt()
        else:
            return "❌ Por favor, os arquivos são essenciais para avançarmos. Anexe-os juntos e envie. (Ou digite 'ok' para modo simulado se estiver testando offline)."

    # 2. Dados sequenciais após upload
    if not parecer.data_sessao:
        try:
            parecer.data_sessao = datetime.datetime.strptime(val, "%d/%m/%Y").date()
        except Exception:
            return f"❌ Erro ao ler a data {val}. O formato deve ser DD/MM/AAAA. Ex: 15/05/2024. Tente novamente."
    elif not parecer.pa:
        parecer.pa = val
    elif not parecer.sgpe:
        parecer.sgpe = val
    elif not parecer.prazo_final:
        try:
            parecer.prazo_final = datetime.datetime.strptime(val, "%d/%m/%Y").date()
        except Exception:
            return f"❌ Erro ao ler a data de prazo {val}. O formato deve ser DD/MM/AAAA."
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

    # data_sessao é obrigatória
    ds = payload.get("data_sessao", "").strip()
    if not ds:
        return "❌ A **Data da Sessão** é obrigatória. Preencha o campo e confirme novamente."
    try:
        parecer.data_sessao = datetime.datetime.strptime(ds, "%d/%m/%Y").date()
    except ValueError:
        return f"❌ Data da Sessão inválida: '{ds}'. Use o formato DD/MM/AAAA."

    # Campos opcionais
    parecer.pa = payload.get("pa") or parecer.pa
    parecer.sgpe = payload.get("sgpe") or parecer.sgpe
    parecer.recorrente = payload.get("recorrente") or parecer.recorrente

    pf = payload.get("prazo_final", "").strip()
    if pf:
        try:
            parecer.prazo_final = datetime.datetime.strptime(pf, "%d/%m/%Y").date()
        except ValueError:
            return f"❌ Prazo Final inválido: '{pf}'. Use DD/MM/AAAA."

    dp = payload.get("data_protocolo", "").strip()
    if dp:
        try:
            parecer.data_protocolo = datetime.datetime.strptime(dp, "%d/%m/%Y").date()
        except ValueError:
            return f"❌ Data de Protocolo inválida: '{dp}'. Use DD/MM/AAAA."

    pg = payload.get("paginas_defesa", "").strip()
    if pg:
        parecer.paginas_defesa = pg

    # Validação dos campos mínimos
    faltando = []
    if not parecer.pa:             faltando.append("PA")
    if not parecer.sgpe:           faltando.append("SGPE")
    if not parecer.prazo_final:    faltando.append("Prazo Final")
    if not parecer.data_protocolo: faltando.append("Data do Protocolo")
    if not parecer.paginas_defesa: faltando.append("Páginas da Defesa")
    if faltando:
        return f"❌ Os seguintes campos são obrigatórios: **{', '.join(faltando)}**. Preencha e confirme novamente."

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

    try:
        from chat.integrations import GeminiClient
        dados = GeminiClient().extract_fase1_fields(parecer)
    except Exception as e:
        logger.warning(f"run_fase1_autopreenchimento: erro na extração ({e}). Fallback manual.")
        dados = None

    if not dados:
        return engine.get_current_prompt()

    def _parse_date(s):
        try:
            return datetime.datetime.strptime(s.strip(), "%d/%m/%Y").date() if s else None
        except (ValueError, AttributeError):
            return None

    if dados.get("pa") and not parecer.pa:
        parecer.pa = dados["pa"]
    if dados.get("sgpe") and not parecer.sgpe:
        parecer.sgpe = dados["sgpe"]
    if dados.get("recorrente") and not parecer.recorrente:
        parecer.recorrente = dados["recorrente"]
    if dados.get("prazo_final") and not parecer.prazo_final:
        parecer.prazo_final = _parse_date(dados["prazo_final"])
    if dados.get("data_protocolo") and not parecer.data_protocolo:
        parecer.data_protocolo = _parse_date(dados["data_protocolo"])
    if dados.get("paginas_defesa") and not parecer.paginas_defesa:
        parecer.paginas_defesa = dados["paginas_defesa"]

    from chat.engine import FASE_AGUARDA_CONFIRMACAO_FASE1
    parecer.fase1_extracao_json = dados
    parecer.status_fase = FASE_AGUARDA_CONFIRMACAO_FASE1
    parecer.save()

    logger.info(f"[FASE1_AUTO] parecer={parecer.id} extração OK: {list(dados.keys())}")
    return engine.get_current_prompt()


# ── Auxiliar interno ──────────────────────────────────────────────────────────

def _handle_upload(engine, uploaded_files: list) -> str:
    """Classifica os PDFs recebidos e dispara a task Celery de auto-preenchimento."""
    parecer = engine.parecer
    file_autuacao = file_consolidado = file_ata = None

    if len(uploaded_files) == 1:
        f_lower = uploaded_files[0].lower()
        # Se for apenas uma ATA, ainda faltam os documentos principais
        if any(term in f_lower for term in ["ata"]):
            return (
                "❌ **Upload incompleto.** Você enviou apenas a Ata. "
                "Os documentos **Autuação** e **Consolidado** são obrigatórios.\n\n"
                "Envie no mínimo os dois arquivos ao mesmo tempo."
            )
        # Modo processo simples: mesmo PDF serve como autuação e consolidado
        file_autuacao = uploaded_files[0]
        file_consolidado = uploaded_files[0]
        file_ata = None
    else:
        for f in uploaded_files:
            f_lower = f.lower()
            if any(term in f_lower for term in ["ata"]):
                file_ata = f
            elif any(term in f_lower for term in ["consolidado", "cons", "defesa", "recurso"]):
                file_consolidado = f
            elif any(term in f_lower for term in ["autua", "ait", "termo"]):
                file_autuacao = f
        if not file_autuacao and uploaded_files:
            file_autuacao = uploaded_files[0]
        if not file_consolidado and len(uploaded_files) > 1:
            file_consolidado = uploaded_files[1]

    parecer.autuacao_pdf_path = file_autuacao
    parecer.consolidado_pdf_path = file_consolidado
    if file_ata:
        parecer.ata_pdf_path = file_ata

    parecer.save()
    from chat.tasks import processar_fase1_task
    task = processar_fase1_task.delay(parecer.id)
    return _json.dumps({"status": "celery", "task_id": task.id, "type": "FASE1"})
