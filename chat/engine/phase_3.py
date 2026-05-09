"""
Fase 3 — Cálculos matemáticos de admissibilidade (JariMath) + geração de texto via Gemini.
"""

import re
import datetime
import logging
import unicodedata

logger = logging.getLogger(__name__)


def _normalizar(texto: str) -> str:
    """Remove acentos e converte para maiúsculas — normalização para matching robusto."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    ).upper()


def process(engine) -> str:
    """
    Fase 3 acionada quando o julgador confirma a tabela F2.
    Despacha para Celery para evitar que o Gemini bloqueie o Gunicorn indefinidamente.
    """
    import json
    from chat.tasks import processar_fase3_admissibilidade_task
    task = processar_fase3_admissibilidade_task.delay(engine.parecer.id)
    return json.dumps({"status": "celery", "task_id": task.id, "type": "FASE3_ADM"})


def run(engine) -> str:
    """
    Executa a Fase 3:
    1. Parser semântico de datas da tabela F2.
    2. Cálculos matemáticos via JariMath.
    3. Chamada Gemini para gerar o texto de admissibilidade.
    4. Avança para FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE.
    """
    from chat.jari_math import JariMath
    from chat.engine import FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE

    parecer = engine.parecer
    texto_tabela = parecer.tabela_datas_sensiveis or ""

    # ── Parser semântico de datas ─────────────────────────────────────────────
    datas_processadas = []
    for d in re.findall(r'(\d{2}/\d{2}/\d{4})', texto_tabela):
        try:
            datas_processadas.append(datetime.datetime.strptime(d, "%d/%m/%Y").date())
        except Exception:
            pass
    datas_processadas.sort()

    # Datas da Fase 1 não são marcos interruptivos de prescrição punitiva
    _datas_fase1 = {d for d in [parecer.data_protocolo, parecer.prazo_final] if d is not None}
    _datas_sem_fase1 = [d for d in datas_processadas if d not in _datas_fase1]

    # Versão normalizada da tabela (sem acentos, uppercase) para matching robusto.
    # Resolve casos em que o Gemini gera INFRAÇÃO, Infração, AIT etc. com variações de encoding.
    # As datas DD/MM/AAAA não são afetadas pela normalização.
    _texto_norm = _normalizar(texto_tabela)

    def _data_por_label(texto, *patterns):
        """M6 FIX: regex robusta — aceita pipe Markdown E formatos sem delimitador.
        Tenta primeiro no texto original, depois no texto normalizado (sem acentos/uppercase).
        """
        # Versão normalizada dos patterns (sem acentos, uppercase) para busca no texto normalizado
        def _norm_pat(p):
            return _normalizar(p.replace(r'\b', '').replace('[Ii]', 'I').replace('[çc]', 'C').replace('[ãa]', 'A').replace('[Çç]', 'C').replace('[Ãã]', 'A'))

        for orig_texto, busca_texto in [(texto, texto), (_texto_norm, _texto_norm)]:
            for pat in patterns:
                t = busca_texto
                # Ao usar texto normalizado, normaliza também o pattern
                p = _normalizar(pat.replace('\\b', '').replace('[Ii]', 'I').replace('[çc]', 'C').replace('[ãa]', 'A')) if t is _texto_norm else pat
                # 1. Formato tabela Markdown: label ... | DD/MM/AAAA
                m = re.search(rf'{p}[^|\n]{{0,60}}\|\s*(\d{{2}}/\d{{2}}/\d{{4}})', t, re.IGNORECASE)
                if not m:
                    # 2. Formato invertido: DD/MM/AAAA | ... label
                    m = re.search(rf'\|\s*(\d{{2}}/\d{{2}}/\d{{4}})\s*\|[^|\n]{{0,60}}{p}', t, re.IGNORECASE)
                if not m:
                    # 3. Formato livre: label seguido de data (ex: "Infração: 15/03/2022")
                    m = re.search(rf'{p}[^\n\d]{{0,40}}(\d{{2}}/\d{{2}}/\d{{4}})', t, re.IGNORECASE)
                if not m:
                    # 4. Data antes do label (ex: "15/03/2022 — Infração")
                    m = re.search(rf'(\d{{2}}/\d{{2}}/\d{{4}})\s*[—\-–]\s*{p}', t, re.IGNORECASE)
                if m:
                    try:
                        return datetime.datetime.strptime(m.group(1), "%d/%m/%Y").date()
                    except Exception:
                        pass
        return None

    # Labels canônicos emitidos pelo Gemini F2 (coluna Tipo) têm prioridade sobre regex textual.
    # Fallback: menor data (infração costuma ser a mais antiga) em vez de posição [0]
    # que pode mudar se o Gemini inserir novas linhas no topo da tabela.
    _fallback_infracao = (
        min(_datas_sem_fase1) if _datas_sem_fase1 else
        (min(datas_processadas) if datas_processadas else None)
    )
    # D13: emitir aviso quando fallback é usado (data pode ser errada em processos complexos)
    _usou_fallback_infracao = False
    data_infracao = _data_por_label(
        texto_tabela,
        r'\bINFRACAO\b', r'[Ii]nfra[çc][ãa]o', r'Auto\s+de\s+[Ii]nfra[çc][ãa]o', r'\bAIT\b', r'\bAI\b',
    ) or _fallback_infracao

    # D13: log quando fallback é usado e sinaliza no model para bloqueio na F31
    if data_infracao and data_infracao == _fallback_infracao:
        _usou_fallback_infracao = True
        parecer.data_infracao_fallback = True
        logger.warning(
            "[FASE3] data_infracao via fallback min() — pode ser data errada em processos complexos: "
            "%s | parecer=%s", data_infracao, parecer.id if hasattr(parecer, 'id') else '?'
        )
    else:
        parecer.data_infracao_fallback = False

    # ── Bloqueio: data_infracao obrigatória para cálculos corretos ────────────
    if not data_infracao:
        logger.error(f"[FASE3] data_infracao não encontrada — bloqueando avanço. parecer={parecer.id}")
        from chat.engine import FASE_DIR
        parecer.status_fase = FASE_DIR
        parecer.save()
        return (
            "⚠️ **Data da Infração não localizada na tabela.**\n\n"
            "Não foi possível identificar a data da infração na tabela de datas. "
            "Sem essa data, os cálculos de prescrição punitiva e decadência ficam matematicamente incorretos.\n\n"
            "**O que fazer:**\n"
            "- Digite **corrigir** para voltar ao início e reenviar os documentos;\n"
            "- Ou edite manualmente a tabela (o campo *Tipo* deve conter exatamente a infração) e depois reinicie com **corrigir**.\n\n"
            "O processo foi retornado à etapa anterior aguardando sua decisão."
        )

    data_na = _data_por_label(
        texto_tabela,
        r'\bNA\b',
        r'Notifica[çc][ãa]o\s+de\s+Autua[çc][ãa]o',
        r'Notifica[çc][ãa]o\s+Auto',
        r'\bAUTUA[CÇ][AÃ]O\b',          # D3 FIX: rótulo "Autuação" sem prefixo "Notificação"
        r'Auto\s+de\s+[Ii]nfra[çc][ãa]o',
    )

    data_np = _data_por_label(
        texto_tabela,
        r'\bNP\b',
        r'Notifica[çc][ãa]o\s+de\s+Penalidade',
        r'\bPENALIDADE\b',              # D3 FIX: rótulo "Penalidade" isolado
        r'Notifica[çc][ãa]o\s+[Pp]uniti',
    )

    data_instauracao = _data_por_label(
        texto_tabela,
        r'\bINSTAURACAO\b',
        r'[Ii]nstaura[çc][ãa]o\s+do\s+[Pp]rocesso',
        r'[Ii]nstaura[çc][ãa]o',
        r'[Aa]bertura\s+do\s+[Pp]rocesso',
        r'\bPAD\b',                     # D3 FIX: "PAD" = Processo Administrativo Disciplinar
        r'[Ii]nicio\s+do\s+[Pp]rocesso',
    )

    _datas_apos_infracao = [d for d in _datas_sem_fase1 if d > data_infracao] if data_infracao else []
    data_notificacao_autuacao = (
        data_np
        or data_na
        or (_datas_apos_infracao[0] if _datas_apos_infracao else data_infracao)
    )

    _marcos_semanticos = sorted({
        d for d in [data_na, data_np, data_instauracao]
        if d is not None
        and data_infracao is not None
        and data_infracao < d < (parecer.data_sessao or datetime.date.max)
    })

    # ── Validação de consistência cronológica das datas ────────────────────────
    _avisos_consistencia = []
    if data_infracao and data_notificacao_autuacao and data_notificacao_autuacao < data_infracao:
        _avisos_consistencia.append(
            f"⚠️ **INCONSISTÊNCIA:** Data de notificação/autuação ({data_notificacao_autuacao}) "
            f"é anterior à data da infração ({data_infracao}). Verifique a tabela F2."
        )
        logger.warning(f"[FASE3] Notificação ({data_notificacao_autuacao}) < infração ({data_infracao}) — parecer={parecer.id}")
    if data_infracao and parecer.data_sessao and parecer.data_sessao < data_infracao:
        _avisos_consistencia.append(
            f"⚠️ **INCONSISTÊNCIA:** Data da sessão ({parecer.data_sessao}) "
            f"é anterior à data da infração ({data_infracao}). Verifique os dados do processo."
        )
        logger.warning(f"[FASE3] Sessão ({parecer.data_sessao}) < infração ({data_infracao}) — parecer={parecer.id}")
    _bloco_consistencia = "\n".join(_avisos_consistencia) + ("\n\n" if _avisos_consistencia else "")

    # ── Cálculos JariMath ─────────────────────────────────────────────────────
    # Salva data_infracao no model para uso na blindagem Filtro 1 (phase_3_confirm.py)
    if data_infracao:
        parecer.data_infracao = data_infracao
    else:
        logger.warning(f"[FASE3] data_infracao não encontrada na tabela — parecer={parecer.id}")

    parecer.is_tempestivo = JariMath.check_tempestividade(parecer.data_protocolo, parecer.prazo_final)

    # ── Marco inicial da prescrição punitiva ──────────────────────────────────
    # logica_jari §221: suspensão por acúmulo de pontos → marco = dia seguinte à totalização.
    # Para todos os demais casos, o marco inicial é a própria data da infração.
    _data_totalizacao = getattr(parecer, 'data_totalizacao_pontos', None)
    _e_suspensao_pontos = (
        parecer.tipo_penalidade == 'suspensao'
        and _data_totalizacao is not None
    )
    if _e_suspensao_pontos:
        data_inicio_prescricao_punitiva = _data_totalizacao + datetime.timedelta(days=1)
        logger.info(
            f"[FASE3] Suspensão por pontos detectada — marco inicial da punitiva: "
            f"{data_inicio_prescricao_punitiva} (totalização: {_data_totalizacao}) — parecer={parecer.id}"
        )
    else:
        data_inicio_prescricao_punitiva = data_infracao

    if _marcos_semanticos:
        marcos_validos = _marcos_semanticos
    else:
        # Sem marcos semânticos tipados (NA/NP/INSTAURACAO), não aceitar datas
        # não classificadas — evita reiniciar indevidamente o prazo de 5 anos
        # com datas administrativas internas que não constituem marcos legais.
        marcos_validos = []

    # COVID-19 (Res. CONTRAN 782/2020): suspensão de dias se último marco ≤ FIM_COVID
    # D8 FIX: desconto proporcional para marcos dentro do período COVID (20/03-30/11/2020)
    _ultimo_marco_punit = max(marcos_validos) if marcos_validos else data_inicio_prescricao_punitiva
    if _ultimo_marco_punit and _ultimo_marco_punit <= JariMath.FIM_COVID_SUSPENSAO:
        if _ultimo_marco_punit >= JariMath.INICIO_COVID_SUSPENSAO:
            # Marco dentro do período COVID → desconto proporcional (dias restantes do período)
            _desconto_covid_punit = (JariMath.FIM_COVID_SUSPENSAO - _ultimo_marco_punit).days + 1
        else:
            # Marco anterior ao COVID → desconto integral (256 dias)
            _desconto_covid_punit = JariMath.DIAS_SUSPENSAO_COVID
    else:
        _desconto_covid_punit = 0

    parecer.has_prescricao_punitiva = JariMath.check_prescription_punitiva(
        data_inicio_prescricao_punitiva, parecer.data_sessao, marcos_validos or None,
        desconto_covid_dias=_desconto_covid_punit,
    )

    inter_bool, relatorio_intercorrente = JariMath.check_prescription_intercorrente(
        parecer.data_protocolo, parecer.data_sessao
    )
    parecer.has_prescricao_intercorrente = inter_bool

    decadencia_bool, relatorio_decadencia = JariMath.check_decadencia(
        data_infracao,
        data_notificacao_autuacao,
        parecer.data_sessao,
        tipo_penalidade=parecer.tipo_penalidade,
        data_conclusao_multa=parecer.data_conclusao_multa,
        tem_flagrante=parecer.tem_flagrante,
        data_conhecimento_infracao=parecer.data_conhecimento_infracao,
    )
    parecer.has_decadencia = decadencia_bool

    # ── Log estruturado de rastreabilidade ────────────────────────────────────
    # Permite diagnóstico sem precisar ler o texto gerado pelo LLM.
    # Exemplo de busca: grep "[FASE3] resultado" app.log | grep "decadencia=True"
    logger.info(
        "[FASE3] resultado | parecer=%s | tempestivo=%s | punitiva=%s | "
        "intercorrente=%s | decadencia=%s | "
        "data_infracao=%s | data_sessao=%s | data_protocolo=%s | "
        "marco_punit_inicio=%s | marcos_semanticos=%s | e_suspensao_pontos=%s",
        parecer.id,
        parecer.is_tempestivo, parecer.has_prescricao_punitiva,
        parecer.has_prescricao_intercorrente, parecer.has_decadencia,
        data_infracao, parecer.data_sessao, parecer.data_protocolo,
        data_inicio_prescricao_punitiva, _marcos_semanticos, _e_suspensao_pontos,
    )

    # ── Resumo matemático para o LLM ──────────────────────────────────────────
    dias_tempestividade = 0
    if parecer.prazo_final and parecer.data_protocolo:
        dias_tempestividade = JariMath.calculate_days_diff(parecer.prazo_final, parecer.data_protocolo)

    _datas_marcos = _marcos_semanticos if _marcos_semanticos else [d for d in datas_processadas if d not in _datas_fase1]
    ultimo_marco = max(_datas_marcos) if _datas_marcos else data_infracao
    dias_punitiva = 0
    if parecer.data_sessao:
        dias_punitiva = JariMath.calculate_days_diff(ultimo_marco, parecer.data_sessao)

    if "NÃO SE APLICA" in relatorio_decadencia:
        decadencia_final = "NÃO SE APLICA"
    elif parecer.has_decadencia:
        decadencia_final = "SIM"
    else:
        decadencia_final = "NÃO"

    _aviso_data_infracao = ""
    if not data_infracao:
        _aviso_data_infracao = (
            "⚠️ **ATENÇÃO AO JULGADOR:** A data da infração não foi localizada automaticamente "
            "na tabela de datas. Os cálculos de prescrição punitiva e decadência podem estar incorretos. "
            "Verifique a tabela e use 'corrigir' na Fase 2 se necessário.\n\n"
        )
    elif _usou_fallback_infracao:
        # D13: aviso de fallback — data pode estar errada em processos complexos
        _aviso_data_infracao = (
            f"⚠️ **ATENÇÃO:** A data da infração ({data_infracao.strftime('%d/%m/%Y')}) foi inferida "
            "automaticamente como a menor data da tabela (rótulo 'INFRACAO' não localizado). "
            "Confirme se está correta antes de prosseguir.\n\n"
        )

    matematica_detalhes = _bloco_consistencia + _aviso_data_infracao + (
        f"- Tempestividade: Diferença em dias corridos (Protocolo x Prazo Final) = {dias_tempestividade} dias de atraso "
        f"(valores positivos indicam atraso). "
        f"(Conclusão:{'RECURSO TEMPESTIVO – dentro do prazo' if parecer.is_tempestivo else 'RECURSO INTEMPESTIVO – fora do prazo'}).\n"
        f"- Prescrição Punitiva (Exige atingir 5 anos civis, verificado data a data): "
        + (
            f"⚠️ SUSPENSÃO POR PONTOS — marco inicial = dia seguinte à totalização ({data_inicio_prescricao_punitiva}, "
            f"totalização em {_data_totalizacao}). "
            if _e_suspensao_pontos else
            f"Marco inicial = data da infração ({data_infracao}). "
        )
        + f"Maior intervalo desde último marco válido identificado = {dias_punitiva} dias corridos calculados. "
        f"(Valor calculado:{'SIM' if parecer.has_prescricao_punitiva else 'NÃO'}).\n"
        f"- Prescrição Intercorrente (Aniversário de 3 anos alcançado): {relatorio_intercorrente} "
        f"(Valor calculado:{'SIM' if parecer.has_prescricao_intercorrente else 'NÃO'}).\n"
        f"- Decadência (Regimes temporais do CTB / Resolução):\n{relatorio_decadencia}\n"
        f"(Valor calculado:{decadencia_final})\n"
    )

    # ── Geração do texto de admissibilidade via Gemini ────────────────────────
    # Idempotente: se já foi pré-calculado em background (processar_fase3_task),
    # pula a chamada Gemini e apenas avança a fase.
    if parecer.admissibilidade_texto:
        logger.info("[FASE3] admissibilidade_texto já disponível (pré-calculado) — pulando Gemini. parecer=%s", parecer.id)
    else:
        from chat.integrations.gemini import GeminiClient
        gemini = GeminiClient()
        try:
            parecer.admissibilidade_texto = gemini.generate_phase3_report(parecer, matematica_detalhes)
        except Exception as e:
            logger.error("[FASE3] Falha ao chamar Gemini — parecer=%s | erro=%s", parecer.id, e)
            return (
                "⚠️ O serviço de IA está temporariamente indisponível. "
                "Aguarde alguns instantes e tente novamente."
            )

    parecer.status_fase = FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE
    parecer.save()

    return engine.get_current_prompt()


def run_precompute(parecer) -> bool:
    """
    Pré-computa F3 em background enquanto o julgador ainda revisa F2.
    Executa JariMath + Gemini e salva admissibilidade_texto SEM avançar status_fase.
    Retorna True se o pré-cálculo foi realizado, False se foi pulado.
    """
    from chat.jari_math import JariMath
    from chat.engine import FASE_DIR

    # Guard: só pré-calcula se ainda está em F2 e F3 ainda não foi calculada
    if parecer.status_fase != FASE_DIR or parecer.admissibilidade_texto:
        logger.info("[FASE3-PRE] skipped | parecer=%s | fase=%s | ja_calculado=%s",
                    parecer.id, parecer.status_fase, bool(parecer.admissibilidade_texto))
        return False

    # Cria um engine temporário para reutilizar run()
    from chat.engine import JariEngine
    engine = JariEngine(parecer)

    # Executa run() completo — ele avançará status_fase para 31.
    # Depois revertemos o status_fase para FASE_DIR para que o usuário ainda veja F2.
    run(engine)

    # Reverte o status para FASE_DIR — o usuário ainda precisa confirmar F2.
    # Quando confirmar, phase_2.process() verá admissibilidade_texto já preenchido
    # e phase_3.run() pulará a chamada Gemini (idempotente acima).
    parecer.refresh_from_db(fields=['status_fase'])
    if parecer.status_fase != FASE_DIR:
        parecer.status_fase = FASE_DIR
        parecer.save(update_fields=['status_fase'])
        logger.info("[FASE3-PRE] pré-cálculo concluído, status revertido para FASE_DIR. parecer=%s", parecer.id)

    return True
