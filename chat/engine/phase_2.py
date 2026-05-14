"""
Fase 2 — DIR (Integridade/Regularidade): extração autônoma de datas via Gemini + PDFExtractor.
"""

import datetime as _dt2
import logging
import re as _re

logger = logging.getLogger(__name__)


def _normalizar_markdown_tabela(texto: str) -> str:
    """
    Normaliza o markdown gerado pelo Gemini para renderização correta no marked.js.

    Problemas conhecidos no output do Gemini:
    1. Separador com primeira célula vazia: "||---|----|" — GFM exige ao menos um '-' por célula.
       Fix: "||..." → "|---|..."
    2. Tabela sem linha em branco após heading: "#### Título\\n| Col |..."
       marked v13 requer linha em branco antes do bloco de tabela.
       Fix: insere "\\n" extra entre linha não-tabela e início de tabela.
    """
    if not texto:
        return texto
    # Fix 1: primeira célula vazia no separador
    texto = _re.sub(r'^\|\|([-: |]+)$', r'|---|\1', texto, flags=_re.MULTILINE)
    # Fix 2: linha em branco antes de bloco de tabela
    texto = _re.sub(r'^([^|\n\r].*)\n(\|)', r'\1\n\n\2', texto, flags=_re.MULTILINE)
    return texto


def get_prompt(parecer) -> str:
    """Exibe a tabela de datas sensíveis gerada e pede confirmação."""
    return (
        f"{parecer.tabela_datas_sensiveis}\n\n"
        f"Digite **'ok'** para prosseguir."
    )


_CAMPOS_F2 = {
    'data_infracao':             ('date',   'Data da Infração'),
    'data_protocolo':            ('date',   'Data do Protocolo'),
    'data_sessao':               ('date',   'Data da Sessão'),
    'prazo_final':               ('date',   'Prazo Final'),
    'data_conhecimento_infracao':('date',   'Data do Conhecimento'),
    'data_conclusao_multa':      ('date',   'Conclusão da Multa'),
    'data_totalizacao_pontos':   ('date',   'Totalização de Pontos'),
    'tipo_penalidade':           ('choice', 'Tipo de Penalidade (multa/advertencia/suspensao/cassacao)'),
    'tem_flagrante':             ('bool',   'Tem Flagrante (sim/nao)'),
    'recorrente':                ('text',   'Nome do Recorrente'),
}


def _parse_field(campo, valor_str):
    """Converte valor_str para o tipo correto do campo. Retorna (valor_parsed, erro_msg)."""
    tipo = _CAMPOS_F2[campo][0]
    valor_str = valor_str.strip()

    if tipo == 'date':
        if not valor_str or valor_str.upper() in ('NULO', 'NONE', '-'):
            return None, None
        for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
            try:
                import datetime as _dt
                return _dt.datetime.strptime(valor_str, fmt).date(), None
            except ValueError:
                pass
        return None, f"Data inválida: '{valor_str}'. Use DD/MM/AAAA."

    if tipo == 'bool':
        if valor_str.lower() in ('sim', 's', 'true', '1', 'yes'):
            return True, None
        if valor_str.lower() in ('nao', 'não', 'n', 'false', '0', 'no'):
            return False, None
        return None, f"Use 'sim' ou 'nao' para o campo '{campo}'."

    if tipo == 'choice':
        _validos = ('multa', 'advertencia', 'suspensao', 'cassacao')
        v = valor_str.lower()
        if v in _validos:
            return v, None
        # Também invalida o campo se o usuário digitar vazio ou nulo
        if not v or v in ('nao_determinado', '-', 'none'):
            return None, None
        return None, f"Tipo de penalidade inválido: '{valor_str}'. Valores válidos: {', '.join(_validos)}."

    # text
    return valor_str[:255] if valor_str else None, None


def _extrair_data_infracao_tabela(tabela_texto: str):
    """Extrai data_infracao da tabela F2 usando as mesmas labels de phase_3.py."""
    import re, datetime as _dt
    for pat in (
        r'\bINFRACAO\b', r'[Ii]nfra[çc][ãa]o', r'Auto\s+de\s+[Ii]nfra[çc][ãa]o', r'\bAIT\b', r'\bAI\b',
    ):
        m = re.search(rf'{pat}[^|\n]{{0,60}}\|\s*(\d{{2}}/\d{{2}}/\d{{4}})', tabela_texto, re.IGNORECASE)
        if not m:
            m = re.search(rf'\|\s*(\d{{2}}/\d{{2}}/\d{{4}})\s*\|[^|\n]{{0,60}}{pat}', tabela_texto, re.IGNORECASE)
        if m:
            try:
                return _dt.datetime.strptime(m.group(1), "%d/%m/%Y").date()
            except Exception:
                pass
    return None


def process(engine, message: str) -> str:
    """Processa a resposta do julgador na fase 2."""
    parecer = engine.parecer

    # Suporte a edição inline de tipo_penalidade / data_totalizacao_pontos via tabela F2.
    # Mensagem: 'F2_FIELDS:{"tipo_penalidade":"multa","data_totalizacao_pontos":"15/03/2022"}'
    if message.startswith('F2_FIELDS:'):
        import json as _json
        try:
            fields = _json.loads(message[len('F2_FIELDS:'):])
            _upd = []
            _tp = fields.get('tipo_penalidade', '').lower().strip()
            if _tp in ('multa', 'advertencia', 'suspensao', 'cassacao', ''):
                parecer.tipo_penalidade = _tp or None
                _upd.append('tipo_penalidade')
            _dtp = fields.get('data_totalizacao_pontos', '').strip()
            if _dtp:
                import datetime as _dt2f
                try:
                    parecer.data_totalizacao_pontos = _dt2f.datetime.strptime(_dtp, '%d/%m/%Y').date()
                    _upd.append('data_totalizacao_pontos')
                except ValueError:
                    pass
            elif 'data_totalizacao_pontos' in fields:
                parecer.data_totalizacao_pontos = None
                _upd.append('data_totalizacao_pontos')
            if _upd:
                parecer._f2_campos_editados = True
                parecer.save(update_fields=_upd)
                logger.info("[FASE2] F2_FIELDS salvos — campos=%s parecer=%s", _upd, parecer.id)
        except Exception as _e:
            logger.warning("[FASE2] F2_FIELDS parse error: %s", _e)
        message = 'ok'

    msg = message.lower().strip()

    if msg == 'ok':
        from chat.engine import FASE_ADMISSIBILIDADE_GERADA, FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE

        # D4 FIX: bloquear avanço quando data_sessao < data_infracao (fatal)
        _data_inf_f2 = _extrair_data_infracao_tabela(parecer.tabela_datas_sensiveis or "")
        if _data_inf_f2 and parecer.data_sessao and parecer.data_sessao < _data_inf_f2:
            return (
                f"⛔ **BLOQUEIO — Inconsistência Cronológica Fatal**\n\n"
                f"A data da sessão (**{parecer.data_sessao.strftime('%d/%m/%Y')}**) é anterior à "
                f"data da infração (**{_data_inf_f2.strftime('%d/%m/%Y')}**) identificada na tabela. "
                "Os cálculos ficariam matematicamente incorretos.\n\n"
                "Corrija antes de prosseguir:\n"
                "- Informe a data da sessão correta no formato DD/MM/AAAA — ou —\n"
                "- Digite **corrigir** para reiniciar com novos documentos."
            )

        # D17 FIX: bloquear quando suspensão por pontos sem data_totalizacao
        if parecer.tipo_penalidade == 'suspensao' and not parecer.data_totalizacao_pontos:
            return (
                "⚠️ **Data de Totalização de Pontos obrigatória**\n\n"
                "O tipo de penalidade é **Suspensão**. Se for **suspensão por acúmulo de pontos**, "
                "a data de totalização é o marco inicial da análise de prescrição punitiva "
                "e sem ela o cálculo ficará errado.\n\n"
                "Informe uma das opções:\n"
                "- A data de totalização de pontos no formato DD/MM/AAAA — para suspensão por pontos;\n"
                "- Ou informe que se trata de suspensão por infração direta (não por acúmulo de pontos)."
            )

        # Invalida pré-cálculo F3 se campos foram editados (admissibilidade_texto pode estar desatualizado)
        # A flag _f2_campos_editados é setada pelo processo de edição inline
        if getattr(parecer, '_f2_campos_editados', False) and parecer.admissibilidade_texto:
            parecer.admissibilidade_texto = None
            parecer.save(update_fields=['admissibilidade_texto'])
            logger.info("[FASE2] campos editados — pré-cálculo F3 invalidado. parecer=%s", parecer.id)

        # Fast-path: FASE3-PRE já calculou admissibilidade — avança direto para fase 31
        if parecer.admissibilidade_texto:
            parecer.status_fase = FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE
            parecer.save(update_fields=['status_fase'])
            logger.info("[FASE2→31] pré-cálculo F3 reutilizado. parecer=%s", parecer.id)
            return engine.get_current_prompt()

        import json
        from chat.tasks import processar_fase3_admissibilidade_task
        parecer.status_fase = FASE_ADMISSIBILIDADE_GERADA
        parecer.save(update_fields=['status_fase'])
        task = processar_fase3_admissibilidade_task.delay(parecer.id)
        return json.dumps({"status": "celery", "task_id": task.id, "type": "FASE3_ADM"})

    if msg == 'corrigir':
        from chat.engine import FASE_COLETA
        parecer.status_fase = FASE_COLETA
        parecer.data_sessao = None
        parecer.prazo_final = None
        parecer.data_protocolo = None
        parecer.paginas_defesa = ""
        parecer.autuacao_pdf_path = None
        parecer.consolidado_pdf_path = None
        parecer.save()
        return "Voltando à Fase 1. Reiniciando a coleta.\n" + engine.get_current_prompt()

    # ── Correção inline de campo via comando de chat ──────────────────────────
    # Formato: "campo: valor"  ex: "data_infracao: 15/03/2022"
    # Também aceita prefixo "editar " ou "set " para clareza
    _RAW = message.strip()
    _sem_prefixo = _RAW
    for _pfx in ('editar ', 'set ', 'EDITAR ', 'SET '):
        if _RAW.startswith(_pfx):
            _sem_prefixo = _RAW[len(_pfx):]
            break

    if ':' in _sem_prefixo:
        _partes = _sem_prefixo.split(':', 1)
        _campo_raw = _partes[0].strip().lower().replace(' ', '_').replace('-', '_')
        _valor_raw = _partes[1].strip()

        if _campo_raw in _CAMPOS_F2:
            valor_parsed, erro = _parse_field(_campo_raw, _valor_raw)
            if erro:
                return f"⚠️ {erro}\n\nUse **'ok'** para prosseguir ou corrija o campo."
            old_val = getattr(parecer, _campo_raw, None)
            setattr(parecer, _campo_raw, valor_parsed)
            # Invalida o pré-cálculo F3 para que rode novamente com o campo corrigido
            update_fields = [_campo_raw]
            if parecer.admissibilidade_texto:
                parecer.admissibilidade_texto = None
                update_fields.append('admissibilidade_texto')
            parecer.save(update_fields=update_fields)
            logger.info("[FASE2] campo corrigido: %s %s→%s | parecer=%s", _campo_raw, old_val, valor_parsed, parecer.id)
            _label = _CAMPOS_F2[_campo_raw][1]
            return (
                f"✅ **{_label}** atualizado: `{old_val}` → `{valor_parsed}`\n\n"
                f"Confirme a tabela ou corrija outro campo. Digite **'ok'** para prosseguir.\n\n"
                f"---\n\n"
                f"**Campos editáveis:**\n"
                + "\n".join(f"- `{c}`: {d[1]}" for c, d in _CAMPOS_F2.items())
            )

    return (
        "Por favor, responda com **'ok'** para prosseguir ou **'corrigir'** para reiniciar.\n\n"
        "Para corrigir um campo específico, use o formato:\n"
        "```\ndata_infracao: 15/03/2022\n```\n"
        "Campos disponíveis: " + ", ".join(f"`{c}`" for c in _CAMPOS_F2)
    )


def run(engine) -> str:
    """
    Executa a Fase 2: extração de datas via PDFExtractor + chamada Gemini para montar tabela.
    Retorna o prompt da fase 2 (tabela gerada) para o julgador confirmar.
    """
    from chat.integrations import AnthropicClient
    from chat.pdf_extractor import PDFExtractor
    from chat.engine import _p

    parecer = engine.parecer
    anthropic = AnthropicClient()

    datas_consolidado = []
    _chars_con = 0

    _con = _p(parecer.consolidado_pdf_path)

    if _con and "upload_simulado" not in _con:
        datas_consolidado, _chars_con = PDFExtractor.extract_dates_from_pdf(_con, "Consolidado")

    contexto_textual_datas = PDFExtractor.format_extraction_for_llm([], datas_consolidado)

    # ── Detecção de PDF ilegível por contagem de chars ────────────────────────
    # O PDFExtractor já tentou OCR quando total_chars < 2000, então _total_chars
    # reflete o melhor resultado disponível (texto nativo OU pós-OCR Tesseract).
    # <500 → OCR falhou ou PDF completamente ilegível (crítico)
    # 500-2000 → OCR tentado mas resultado ainda limitado (alerta)
    # >2000 → extração suficiente (ok)
    _pdfs_enviados = 1 if _con and "upload_simulado" not in _con else 0
    _total_chars = _chars_con
    _aviso_ilegivel = ""
    if _pdfs_enviados > 0:
        if _total_chars < 500:
            _aviso_ilegivel = (
                "**ATENCAO — PDF possivelmente digitalizado sem OCR:** "
                f"O sistema extraiu apenas {_total_chars} caracteres dos documentos enviados (após tentativa de OCR automático). "
                "O PDF pode ser uma imagem de baixa qualidade ou sem texto reconhecível. "
                "A IA tentará análise visual, mas as datas abaixo podem estar incompletas — "
                "**verifique cuidadosamente antes de prosseguir.**\n\n"
            )
            logger.warning(f"[FASE2] PDF crítico pós-OCR — {_total_chars} chars — parecer={parecer.id}, pdfs={_pdfs_enviados}")
        elif _total_chars < 2000:
            _aviso_ilegivel = (
                "**ATENCAO — PDF com texto limitado (OCR aplicado automaticamente):** "
                f"O sistema extraiu {_total_chars} caracteres após processamento OCR. "
                "Podem existir datas não capturadas. "
                "Confira as datas na tabela abaixo antes de prosseguir.\n\n"
            )
            logger.info(f"[FASE2] PDF texto limitado pós-OCR — {_total_chars} chars — parecer={parecer.id}")

    resultado = anthropic.generate_phase2_report(parecer, contexto_textual_datas, pdf_chars=_total_chars)

    # ── Extração de campos estruturados (JSON) ────────────────────────────────
    # generate_phase2_report retorna dict via response_schema — sem regex frágil.
    _aviso_consistencia_f2 = ""
    if isinstance(resultado, dict) and 'erro' not in resultado:
        _rec = resultado.get('recorrente', '')
        if _rec and 'NÃO LOCALIZADO' not in _rec.upper() and '[NOME' not in _rec.upper():
            parecer.recorrente = _rec[:250].upper()  # D1 FIX: forçar MAIÚSCULAS

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

    parecer.tabela_datas_sensiveis = _normalizar_markdown_tabela(
        _aviso_ilegivel + _aviso_consistencia_f2 + texto_tabela
    )
    parecer.save()

    return engine.get_current_prompt()
