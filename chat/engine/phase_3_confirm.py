"""
Fase 31 — Confirmação da admissibilidade pelo julgador.
Semântica ABSOLUTA: A/B expressam o resultado final diretamente, sem depender do automático.

  Tempestividade:        A = TEMPESTIVO (recurso admissível)   | B = INTEMPESTIVO (inadmissível)
  Prescrição Punitiva:   A = SIM (prescrito)                   | B = NÃO
  Prescrição Intercorr:  A = SIM (prescrito)                   | B = NÃO
  Decadência:            A = SIM (configurada)                 | B = NÃO / NÃO SE APLICA

  None = sem escolha explícita → usa resultado automático do JariMath.
  "ok"/"confirmo" etc.  → confirma todos os resultados automáticos.

Bloqueios obrigatórios (logica-pjari_v2 §371-374):
  Filtro 1 (data_inf < 12/04/2021): declarar Decadência SIM é VETADO (CETRAN/SC 381/2022).
    Conversão bloqueada — o sistema recusa e exige redigitação sem Decadência SIM.
  Filtro 2 Suspensão/Cassação: julgador_decad=True → permitido, com aviso informativo.
"""

import re
import datetime
import unicodedata
import logging
import json

logger = logging.getLogger(__name__)

# Limiar Filtro 1: infrações anteriores a esta data → aviso CETRAN/SC 381/2022 (julgador pode forçar)
_LIMIAR_FILTRO_1 = datetime.date(2021, 4, 12)
# Mensagens de confirmação simples que aceitam todos os resultados automáticos
_MSG_CONFIRMA = {
    'ok', 'confirmo', 'confirmar', 'sim',
    'confirmar resultados', 'confirmo os resultados', 'confirmar os resultados',
}



def process(engine, message: str) -> str:
    """
    Parseia a resposta do julgador com semântica absoluta e roteia:
    - Algum item prejudica o mérito → FASE_RESULTADO (parecer via Celery).
    - Nenhum item prejudica → FASE4 (extração de teses via Celery).
    """
    parecer = engine.parecer

    # ── Auto-confirma data_infracao inferida (fase de levantamento já passou) ──
    if getattr(parecer, 'data_infracao_fallback', False):
        parecer.data_infracao_fallback = False
        parecer.save(update_fields=['data_infracao_fallback'])
        logger.info("[FASE31] data_infracao auto-confirmada (fallback aceito automaticamente): %s | parecer=%s",
                    parecer.data_infracao, parecer.id)
    # ── fim auto-confirmação ─────────────────────────────────────────────────

    def _n(s):
        """Remove acentos e converte para maiúsculas."""
        return ''.join(
            c for c in unicodedata.normalize('NFD', s)
            if unicodedata.category(c) != 'Mn'
        ).upper()

    def _janela(msg_n, keyword_n, size=55):
        """Janela de texto após a keyword; None se não encontrada."""
        m = re.search(rf'{keyword_n}(.{{0,{size}}})', msg_n)
        return m.group(1) if m else None

    def _abs_prescrição_decad(janela):
        """
        Semântica ABSOLUTA para Prescrição Punitiva, Intercorrente e Decadência.
        True  = SIM / configurada / presente / acolhida.
        False = NÃO / não configurada / não se aplica / não acolhida.
        None  = não identificado.
        """
        # Negativos antes (padrões mais específicos primeiro) — D14: variações naturais incluídas
        neg = [
            r'NAO\s+ACOLHID',
            r'NAO\s+SE\s+APLIC',
            r'NAO\s+CONFIGURAD',
            r'NAO\s+RECONHEC',
            r'NAO\s+OCORR',
            r'\bNAO\b',
            r'\bB\b',
            r'\bNEGO\b',
            r'\bREJEIT',
        ]
        for p in neg:
            if re.search(p, janela):
                return False
        # Positivos — D14: "concordo", "aprovado", "correto", "aceito", "reconheço"
        pos = [
            r'ACOLHID',
            r'CONFIGURAD',
            r'\bSIM\b',
            r'\bA\b',
            r'\bCONCORD',
            r'\bAPROV',
            r'\bCORRET',
            r'\bACEIT',
            r'\bRECONHEC',
            r'\bOCORR',
        ]
        for p in pos:
            if re.search(p, janela):
                return True
        return None

    def _abs_tempestividade(janela):
        """
        Semântica ABSOLUTA para Tempestividade.
        True  = TEMPESTIVO / admissível / NÃO CONFIGURADA.
        False = INTEMPESTIVO / inadmissível / CONFIGURADA.
        None  = não identificado.
        Atenção: "NÃO CONFIGURADA" precede "CONFIGURADA" para evitar falso negativo.
        D14 FIX: variações naturais ("concordo", "aprovado" etc.) incluídas.
        """
        if re.search(r'NAO\s+CONFIGURAD', janela):
            return True   # NÃO CONFIGURADA = tempestivo
        if re.search(r'\bCONFIGURAD', janela):
            return False  # CONFIGURADA (sozinha) = intempestivo
        neg = [r'NAO\s+ACOLHID', r'INTEMPESTIV', r'INADMISSIV', r'\bB\b', r'\bNEGO\b', r'\bREJEIT']
        for p in neg:
            if re.search(p, janela):
                return False
        pos = [r'ACOLHID', r'TEMPESTIV', r'ADMISSIV', r'\bA\b', r'\bCONCORD', r'\bAPROV', r'\bCORRET', r'\bACEIT']
        for p in pos:
            if re.search(p, janela):
                return True
        return None

    msg_n = _n(message)

    j_temp  = _janela(msg_n, 'TEMPESTIVIDADE')
    j_punit = _janela(msg_n, 'PUNITIV')
    # Bienal antes da trienal — "BIENAL" é mais específico
    j_inter_bienal = _janela(msg_n, 'BIENAL')
    # Para a trienal, buscar "INTERCORRENTE" que NÃO seja seguida de "BIENAL"
    _inter_match = re.search(r'INTERCORRENTE(?!\s*BIENAL)(.{0,55})', msg_n)
    j_inter = _inter_match.group(1) if _inter_match else None
    j_decad = _janela(msg_n, 'DECAD')

    r_temp  = _abs_tempestividade(j_temp)            if j_temp  is not None else None
    r_punit = _abs_prescrição_decad(j_punit)         if j_punit is not None else None
    r_inter = _abs_prescrição_decad(j_inter)         if j_inter is not None else None
    r_inter_bienal = _abs_prescrição_decad(j_inter_bienal) if j_inter_bienal is not None else None
    r_decad = _abs_prescrição_decad(j_decad)         if j_decad is not None else None

    _nenhuma  = all(x is None for x in [r_temp, r_punit, r_inter, r_inter_bienal, r_decad])
    _msg_simples = message.strip().lower() in _MSG_CONFIRMA

    if _nenhuma and not _msg_simples:
        return (
            "⚠️ **Não consegui identificar suas escolhas.** Responda no formato:\n\n"
            "```\n"
            "Tempestividade - A\n"
            "Prescrição Punitiva - A\n"
            "Prescrição Intercorrente Trienal - B\n"
            "Prescrição Intercorrente Bienal - B\n"
            "Decadência - A\n"
            "```\n\n"
            "**A** = resultado positivo  "
            "(Tempestividade: **tempestivo** | Prescrição/Decadência: **SIM** / configurada)\n"
            "**B** = resultado negativo  "
            "(Tempestividade: **intempestivo** | Prescrição/Decadência: **NÃO**)\n\n"
            "Ou digite **ok** para confirmar todos os resultados calculados automaticamente."
        )

    # Resultado final: escolha explícita prevalece; None → usa automático
    julgador_temp  = r_temp  if r_temp  is not None else parecer.is_tempestivo
    julgador_punit = r_punit if r_punit is not None else parecer.has_prescricao_punitiva
    julgador_inter = r_inter if r_inter is not None else parecer.has_prescricao_intercorrente
    julgador_inter_bienal = r_inter_bienal if r_inter_bienal is not None else parecer.has_prescricao_intercorrente_bienal
    julgador_decad = r_decad if r_decad is not None else parecer.has_decadencia

    logger.warning(
        "[FASE31] parecer=%s | "
        "parsed: temp=%s punit=%s inter=%s inter_bienal=%s decad=%s | "
        "auto:   temp=%s punit=%s inter=%s inter_bienal=%s decad=%s | "
        "result: temp=%s punit=%s inter=%s inter_bienal=%s decad=%s | "
        "msg=%.120s",
        parecer.id,
        r_temp, r_punit, r_inter, r_inter_bienal, r_decad,
        parecer.is_tempestivo, parecer.has_prescricao_punitiva,
        parecer.has_prescricao_intercorrente, parecer.has_prescricao_intercorrente_bienal, parecer.has_decadencia,
        julgador_temp, julgador_punit, julgador_inter, julgador_inter_bienal, julgador_decad,
        message,
    )

    # ── BLOQUEIO HARD — Filtro 1 (logica-pjari_v2 §371-374) ──────────────────────
    # Declarar Decadência SIM para infrações anteriores a 12/04/2021 é VETADO (CETRAN/SC 381/2022).
    # Conversão bloqueada — o sistema recusa e exige redigitação sem Decadência SIM.
    if julgador_decad is True:
        data_inf = getattr(parecer, 'data_infracao', None)
        if data_inf and data_inf < _LIMIAR_FILTRO_1:
            logger.warning(
                "[FASE31] Filtro 1 BLOQUEIO: parecer=%s data_infracao=%s — declaração de Decadência SIM vetada",
                parecer.id, data_inf,
            )
            try:
                from chat.models import log_audit
                log_audit('filtro_bloqueado', parecer=parecer, fase=31,
                          dados={'filtro': 1, 'data_infracao': str(data_inf)})
            except Exception:
                pass
            return (
                "⛔ **CONVERSÃO BLOQUEADA — Filtro 1 (CETRAN/SC 381/2022)**\n\n"
                f"A infração ocorreu em **{data_inf.strftime('%d/%m/%Y')}**, anterior a 12/04/2021. "
                "O Parecer CETRAN/SC 381/2022 veda absolutamente a declaração de decadência "
                "para infrações neste período (arts. 281-A e 282, §6°-A do CTB não retroagem).\n\n"
                "Não é possível declarar **Decadência: SIM** para este caso. "
                "Redigite suas escolhas sem marcar Decadência."
            )

    aviso_filtro1 = ""

    # ── D5 FIX: BLOQUEIO Filtro 2 Suspensão/Cassação (Nota CETRAN/SC 02/03/2023) ──
    # Declarar Decadência SIM para suspensão/cassação no período 12/04/2021–21/10/2021 é VETADO.
    aviso_filtro2_suspensao = ""
    if julgador_decad is True:
        data_inf_f2  = getattr(parecer, 'data_infracao', None)
        tipo_pen_f2  = (getattr(parecer, 'tipo_penalidade', None) or '').lower()
        _e_grave     = tipo_pen_f2 in ('suspensao', 'cassacao')
        _e_filtro2   = (data_inf_f2 and
                        data_inf_f2 >= _LIMIAR_FILTRO_1 and
                        data_inf_f2 < datetime.date(2021, 10, 22))
        if _e_grave and _e_filtro2:
            logger.warning(
                "[FASE31] Filtro 2 Suspensão BLOQUEIO: parecer=%s tipo=%s data_inf=%s — declaração de Decadência SIM vetada",
                parecer.id, tipo_pen_f2, data_inf_f2,
            )
            try:
                from chat.models import log_audit
                log_audit('filtro_bloqueado', parecer=parecer, fase=31,
                          dados={'filtro': 2, 'tipo_penalidade': tipo_pen_f2, 'data_infracao': str(data_inf_f2)})
            except Exception:
                pass
            return (
                "⛔ **CONVERSÃO BLOQUEADA — Filtro 2 Suspensão/Cassação (Nota CETRAN/SC 02/03/2023)**\n\n"
                f"A infração ocorreu em **{data_inf_f2.strftime('%d/%m/%Y')}** "
                "(período 12/04/2021 a 21/10/2021) com penalidade de **{tipo_pen_f2}**. "
                "A Nota CETRAN/SC 02/03/2023 restringe os prazos decadenciais de 180/360 dias "
                "exclusivamente a multas e advertências neste período. "
                "Suspensões e cassações são encaminhadas à Prescrição Punitiva.\n\n"
                "Não é possível declarar **Decadência: SIM** para este caso. "
                "Redigite suas escolhas sem marcar Decadência."
            )

    parecer.julgador_tempestivo               = julgador_temp
    parecer.julgador_prescricao_punitiva      = julgador_punit
    parecer.julgador_prescricao_intercorrente = julgador_inter
    parecer.julgador_prescricao_intercorrente_bienal = julgador_inter_bienal
    parecer.julgador_decadencia               = julgador_decad
    parecer.save()

    try:
        from chat.models import log_audit
        log_audit('admissibilidade_decisao', parecer=parecer, fase=31, dados={
            'tempestivo':    julgador_temp,
            'punitiva':      julgador_punit,
            'intercorrente': julgador_inter,
            'intercorrente_bienal': julgador_inter_bienal,
            'decadencia':    julgador_decad,
        })
    except Exception:
        pass

    # Roteamento por precedência: C (Decadência) > B (Prescrição) > A (Intempestividade) > D (mérito)
    prejudica = (
        parecer.julgador_prescricao_punitiva
        or parecer.julgador_prescricao_intercorrente
        or parecer.julgador_prescricao_intercorrente_bienal
        or parecer.julgador_decadencia
        or (parecer.julgador_tempestivo is False)
    )

    # Salva avisos informativos antes de rotear (independente da rota)
    from chat.models import ChatMessage
    for aviso in (aviso_filtro1, aviso_filtro2_suspensao):
        if aviso:
            ChatMessage.objects.create(parecer=parecer, role='assistant', content=aviso.strip())

    if prejudica:
        from chat.engine import FASE_RESULTADO
        motivo = []
        if parecer.julgador_prescricao_punitiva:      motivo.append("PRESCRIÇÃO PUNITIVA")
        if parecer.julgador_prescricao_intercorrente: motivo.append("PRESCRIÇÃO INTERCORRENTE TRIENAL")
        if parecer.julgador_prescricao_intercorrente_bienal: motivo.append("PRESCRIÇÃO INTERCORRENTE BIENAL")
        if parecer.julgador_decadencia:               motivo.append("DECADÊNCIA")
        if parecer.julgador_tempestivo is False:      motivo.append("INTEMPESTIVIDADE")
        parecer.tese = f"MÉRITO PREJUDICADO ({' / '.join(motivo)})."
        parecer.status_fase = FASE_RESULTADO
        parecer.save()

        from chat.tasks import gerar_parecer_task
        task = gerar_parecer_task.delay(parecer.id)
        return json.dumps({"status": "celery", "task_id": task.id, "type": "PREJUDICIALIDADE"})

    # Rota D — análise de mérito (extração de teses)
    from chat.tasks import processar_fase4_task
    task = processar_fase4_task.delay(parecer.id)
    return json.dumps({"status": "celery", "task_id": task.id, "type": "FASE4"})
