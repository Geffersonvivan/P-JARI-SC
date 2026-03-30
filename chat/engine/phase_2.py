"""
Fase 2 — DIR (Integridade/Regularidade): extração autônoma de datas via Gemini + PDFExtractor.
"""

import datetime as _dt2
import logging

logger = logging.getLogger(__name__)


def get_prompt(parecer) -> str:
    """Exibe a tabela de datas sensíveis gerada e pede confirmação."""
    return (
        f"{parecer.tabela_datas_sensiveis}\n\n"
        f"Digite **'ok'** para prosseguir."
    )


def process(engine, message: str) -> str:
    """Processa a resposta do julgador na fase 2."""
    parecer = engine.parecer
    msg = message.lower().strip()

    if msg == 'ok':
        from chat.engine import FASE_ADMISSIBILIDADE_GERADA
        parecer.status_fase = FASE_ADMISSIBILIDADE_GERADA
        parecer.save()
        return engine.run_phase_3()

    if msg == 'corrigir':
        from chat.engine import FASE_COLETA
        parecer.status_fase = FASE_COLETA
        parecer.data_sessao = None
        parecer.pa = ""
        parecer.sgpe = ""
        parecer.prazo_final = None
        parecer.data_protocolo = None
        parecer.paginas_defesa = ""
        parecer.autuacao_pdf_path = None
        parecer.consolidado_pdf_path = None
        parecer.save()
        return "Voltando à Fase 1. Reiniciando a coleta.\n" + engine.get_current_prompt()

    return "Por favor, responda com **'ok'** para prosseguir ou **'corrigir'** para reiniciar."


def run(engine) -> str:
    """
    Executa a Fase 2: extração de datas via PDFExtractor + chamada Gemini para montar tabela.
    Retorna o prompt da fase 2 (tabela gerada) para o julgador confirmar.
    """
    from chat.integrations import GeminiClient
    from chat.pdf_extractor import PDFExtractor
    from chat.engine import _p

    parecer = engine.parecer
    gemini = GeminiClient()

    datas_autuacao = []
    datas_consolidado = []
    _chars_aut = 0
    _chars_con = 0

    _aut = _p(parecer.autuacao_pdf_path)
    _con = _p(parecer.consolidado_pdf_path)

    if _aut and "upload_simulado" not in _aut:
        datas_autuacao, _chars_aut = PDFExtractor.extract_dates_from_pdf(_aut, "Autuação")

    if _con and "upload_simulado" not in _con:
        if _aut != _con:
            datas_consolidado, _chars_con = PDFExtractor.extract_dates_from_pdf(_con, "Consolidado")

    contexto_textual_datas = PDFExtractor.format_extraction_for_llm(datas_autuacao, datas_consolidado)

    # ── Detecção de PDF ilegível por contagem de chars ────────────────────────
    # <500 chars → imagem sem OCR (crítico); 500-2000 → texto limitado (alerta); >2000 → ok.
    _pdfs_enviados = sum(1 for p in [_aut, _con] if p and "upload_simulado" not in p)
    _total_chars = _chars_aut + _chars_con
    _aviso_ilegivel = ""
    if _pdfs_enviados > 0:
        if _total_chars < 500:
            _aviso_ilegivel = (
                "⚠️ **ATENÇÃO — PDF possivelmente digitalizado sem OCR:** "
                f"O sistema extraiu apenas {_total_chars} caracteres dos documentos enviados. "
                "O PDF pode ser uma imagem sem texto selecionável. "
                "O Gemini tentará análise visual, mas as datas abaixo podem estar incompletas — "
                "**verifique cuidadosamente antes de prosseguir.**\n\n"
            )
            logger.warning(f"[FASE2] PDF crítico — {_total_chars} chars — parecer={parecer.id}, pdfs={_pdfs_enviados}")
        elif _total_chars < 2000:
            _aviso_ilegivel = (
                "ℹ️ **ATENÇÃO — PDF com texto limitado:** "
                f"O sistema extraiu {_total_chars} caracteres dos documentos. "
                "Podem existir datas não capturadas pela varredura automática. "
                "Confira as datas na tabela abaixo antes de prosseguir.\n\n"
            )
            logger.info(f"[FASE2] PDF texto limitado — {_total_chars} chars — parecer={parecer.id}")

    resultado = gemini.generate_phase2_report(parecer, contexto_textual_datas)

    # ── Extração de campos estruturados (JSON) ────────────────────────────────
    # generate_phase2_report retorna dict via response_schema — sem regex frágil.
    _aviso_consistencia_f2 = ""
    if isinstance(resultado, dict) and 'erro' not in resultado:
        _rec = resultado.get('recorrente', '')
        if _rec and 'NÃO LOCALIZADO' not in _rec.upper() and '[NOME' not in _rec.upper():
            parecer.recorrente = _rec[:250]

        _tp = resultado.get('tipo_penalidade', '').lower().strip()
        if _tp and _tp != 'nao_determinado':
            parecer.tipo_penalidade = _tp

        _dc = resultado.get('data_conclusao_multa', '')
        if _dc and 'NAO_SE_APLICA' not in _dc.upper():
            try:
                parecer.data_conclusao_multa = _dt2.datetime.strptime(_dc.strip(), "%d/%m/%Y").date()
            except ValueError:
                pass

        _flag = resultado.get('tem_flagrante', '').upper().strip()
        if _flag == 'SIM':
            parecer.tem_flagrante = True
        elif _flag == 'NAO':
            parecer.tem_flagrante = False

        _dci = resultado.get('data_conhecimento_infracao', '')
        if _dci and 'NAO_SE_APLICA' not in _dci.upper():
            try:
                parecer.data_conhecimento_infracao = _dt2.datetime.strptime(_dci.strip(), "%d/%m/%Y").date()
            except ValueError:
                pass

        _dtp = resultado.get('data_totalizacao_pontos', '')
        if _dtp and 'NAO_SE_APLICA' not in _dtp.upper():
            try:
                parecer.data_totalizacao_pontos = _dt2.datetime.strptime(_dtp.strip(), "%d/%m/%Y").date()
            except ValueError:
                pass

        # ── Validação de consistência cronológica na Fase 2 ─────────────────────
        _data_inf_ext = resultado.get('data_infracao_extraida', '')
        _data_not_ext = resultado.get('data_notificacao_extraida', '')
        if _data_inf_ext and 'NAO_SE_APLICA' not in _data_inf_ext.upper():
            try:
                _d_inf = _dt2.datetime.strptime(_data_inf_ext.strip(), "%d/%m/%Y").date()
                if _data_not_ext and 'NAO_SE_APLICA' not in _data_not_ext.upper():
                    try:
                        _d_not = _dt2.datetime.strptime(_data_not_ext.strip(), "%d/%m/%Y").date()
                        if _d_not < _d_inf:
                            _aviso_consistencia_f2 = (
                                f"⚠️ **INCONSISTÊNCIA DETECTADA:** A notificação ({_data_not_ext}) "
                                f"aparece antes da infração ({_data_inf_ext}) nos documentos. "
                                "Verifique os documentos ou use **'corrigir'** para reenviar.\n\n"
                            )
                            logger.warning(
                                f"[FASE2] Notificação ({_d_not}) < infração ({_d_inf}) — parecer={parecer.id}"
                            )
                    except ValueError:
                        pass
                if parecer.data_sessao and parecer.data_sessao < _d_inf:
                    _aviso_consistencia_f2 += (
                        f"⚠️ **INCONSISTÊNCIA DETECTADA:** A data da sessão ({parecer.data_sessao}) "
                        f"aparece antes da infração ({_data_inf_ext}). "
                        "Verifique os dados do processo.\n\n"
                    )
                    logger.warning(
                        f"[FASE2] Sessão ({parecer.data_sessao}) < infração ({_d_inf}) — parecer={parecer.id}"
                    )
            except ValueError:
                pass

        texto_tabela = resultado.get('tabela_markdown', '')
    else:
        # Fallback: generate_phase2_report retornou erro — usa texto bruto se disponível
        _erro = resultado.get('erro', '') if isinstance(resultado, dict) else str(resultado)
        texto_tabela = resultado.get('tabela_markdown', _erro) if isinstance(resultado, dict) else str(resultado)
        logger.error(f"[FASE2] generate_phase2_report retornou erro — parecer={parecer.id}: {_erro}")

    parecer.tabela_datas_sensiveis = _aviso_ilegivel + _aviso_consistencia_f2 + texto_tabela
    parecer.save()

    return engine.get_current_prompt()
