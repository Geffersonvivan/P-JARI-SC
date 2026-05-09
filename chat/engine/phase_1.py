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
            # D12 FIX: modo simulado offline só disponível em DEBUG
            from django.conf import settings as _settings
            if not getattr(_settings, 'DEBUG', False):
                return "❌ Modo simulado indisponível em produção. Anexe os arquivos reais para prosseguir."
            parecer.autuacao_pdf_path = "upload_simulado_autuacao.pdf"
            parecer.consolidado_pdf_path = "upload_simulado_recurso.pdf"
            parecer.infracao_documento = "DIRIGIR SOB A INFLUENCIA DE ALCOOL"
            parecer.save()
            return engine.get_current_prompt()
        else:
            return "Por favor, os arquivos são essenciais para avançarmos. Anexe-os juntos e envie. (Ou digite 'ok' para modo simulado se estiver testando offline)."

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
    parecer.pa = payload.get("pa") or parecer.pa
    parecer.sgpe = payload.get("sgpe") or parecer.sgpe
    parecer.recorrente = (payload.get("recorrente") or parecer.recorrente or "").upper() or None

    pf = payload.get("prazo_final", "").strip()
    if pf:
        _pf_parsed = _parse_date_flex(pf)
        if not _pf_parsed:
            return f"❌ Prazo Final inválido: '{pf}'. Use DD/MM/AAAA."
        parecer.prazo_final = _pf_parsed

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
    if not parecer.pa:             faltando.append("PA")
    if not parecer.sgpe:           faltando.append("SGPE")
    if not parecer.prazo_final:    faltando.append("Prazo Final")
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

    try:
        from django.conf import settings as _settings
        from chat.pdf_extractor import PDFExtractor
        from chat.integrations.perplexity import _p

        # Extrair Markdown estruturado dos PDFs (usado por ambos os modos)
        markdown_texts = {}
        for path_field, label in [
            (parecer.autuacao_pdf_path, 'autuacao'),
            (parecer.consolidado_pdf_path, 'consolidado'),
            (parecer.ata_pdf_path, 'ata'),
        ]:
            _path = _p(path_field)
            if _path and "upload_simulado" not in _path:
                md = PDFExtractor.extract_structured_markdown(_path, label=label.upper())
                if md:
                    markdown_texts[label] = md

        if getattr(_settings, 'UNIFIED_FASE1_FASE2', False):
            # ── Modo unificado: F1+F2 numa única chamada ──
            # Extrair datas brutas via regex (input para a tabela de datas sensíveis)
            datas_aut, _chars_aut = [], 0
            datas_con, _chars_con = [], 0
            _aut = _p(parecer.autuacao_pdf_path)
            _con = _p(parecer.consolidado_pdf_path)
            if _aut and "upload_simulado" not in _aut:
                datas_aut, _chars_aut = PDFExtractor.extract_dates_from_pdf(_aut, "Autuação")
            if _con and "upload_simulado" not in _con and _aut != _con:
                datas_con, _chars_con = PDFExtractor.extract_dates_from_pdf(_con, "Consolidado")
            contexto_datas = PDFExtractor.format_extraction_for_llm(datas_aut, datas_con)
            _total_chars = _chars_aut + _chars_con

            logger.info(f"[UNIFIED] parecer={parecer.id} docs={list(markdown_texts.keys())} "
                        f"md_chars={sum(len(v) for v in markdown_texts.values())} pdf_chars={_total_chars}")

            from chat.integrations.anthropic import AnthropicClient
            dados = AnthropicClient().extract_unified_fase1_fase2(
                parecer, markdown_texts, contexto_datas, pdf_chars=_total_chars
            )
    except Exception as e:
        logger.warning(f"run_fase1_autopreenchimento: erro na extração ({e}). Fallback manual.")
        dados = None

    if not dados:
        dados = {}

    def _parse_date(s):
        try:
            return datetime.datetime.strptime(s.strip(), "%d/%m/%Y").date() if s else None
        except (ValueError, AttributeError):
            return None

    # ── Salvar campos F1 (administrativos) ──
    _nulos = {'nulo', 'null', 'none', 'n/a', 'não encontrado', 'nao encontrado',
              'não localizado', 'nao localizado', 'não informado', 'nao informado', ''}

    def _val(key):
        """Retorna valor do dict ou None se for string nula/vazia."""
        v = dados.get(key)
        if not v:
            return None
        return None if str(v).strip().lower() in _nulos else str(v).strip()

    if _val("pa") and not parecer.pa:
        parecer.pa = _val("pa")
    if _val("sgpe") and not parecer.sgpe:
        parecer.sgpe = _val("sgpe")
    if _val("recorrente") and not parecer.recorrente:
        parecer.recorrente = _val("recorrente")
    if _val("prazo_final") and not parecer.prazo_final:
        parecer.prazo_final = _parse_date(_val("prazo_final"))
    if _val("data_protocolo") and not parecer.data_protocolo:
        parecer.data_protocolo = _parse_date(_val("data_protocolo"))
    if _val("paginas_defesa") and not parecer.paginas_defesa:
        parecer.paginas_defesa = _val("paginas_defesa")

    # ── Salvar campos F2 (DIR) se modo unificado ──
    from django.conf import settings as _settings
    if getattr(_settings, 'UNIFIED_FASE1_FASE2', False) and dados.get("tabela_markdown"):
        _tp = (dados.get('tipo_penalidade') or '').lower().strip()
        if _tp and _tp != 'nao_determinado':
            parecer.tipo_penalidade = _tp

        _flag = (dados.get('tem_flagrante') or '').upper().strip()
        if _flag == 'SIM':
            parecer.tem_flagrante = True
        elif _flag == 'NAO':
            parecer.tem_flagrante = False

        _dc = dados.get('data_conclusao_multa', '')
        if _dc and 'NAO_SE_APLICA' not in _dc.upper():
            parecer.data_conclusao_multa = _parse_date(_dc)

        _dci = dados.get('data_conhecimento_infracao', '')
        if _dci and 'NAO_SE_APLICA' not in _dci.upper():
            parecer.data_conhecimento_infracao = _parse_date(_dci)

        _dtp = dados.get('data_totalizacao_pontos', '')
        if _dtp and 'NAO_SE_APLICA' not in _dtp.upper():
            parecer.data_totalizacao_pontos = _parse_date(_dtp)

        _rec = (dados.get('recorrente') or '').strip()
        if _rec and 'NÃO LOCALIZADO' not in _rec.upper():
            parecer.recorrente = _rec[:250].upper()

        # Normalizar markdown da tabela
        from chat.engine.phase_2 import _normalizar_markdown_tabela
        parecer.tabela_datas_sensiveis = _normalizar_markdown_tabela(dados['tabela_markdown'])

        logger.info(f"[UNIFIED] parecer={parecer.id} campos F2 salvos: tp={_tp} flag={_flag}")

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
