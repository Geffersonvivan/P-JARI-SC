"""
Fase 31 — Confirmação da admissibilidade pelo julgador.
Parseia as escolhas A/B (Acolhida / Não Acolhida) e roteia para F4 ou F5.
"""

import re
import datetime
import unicodedata
import logging
import json

logger = logging.getLogger(__name__)

# Limiar Filtro 1: infrações anteriores a esta data → decadência PROIBIDA (Parecer CETRAN/SC 381/2022)
_LIMIAR_FILTRO_1 = datetime.date(2021, 4, 12)
# Mensagens de confirmação simples que significam "aceito os resultados automáticos"
_MSG_CONFIRMA = {'ok', 'confirmo', 'confirmar', 'sim', 'confirmar resultados', 'confirmo os resultados', 'confirmar os resultados'}


def process(engine, message: str) -> str:
    """
    Parseia a resposta do julgador sobre cada item de admissibilidade e:
    - Se algum item prejudica o mérito → vai para F5 (FASE_RESULTADO) via Celery.
    - Caso contrário → vai para F4 (extração de teses).
    """
    parecer = engine.parecer

    def _strip_accents(s):
        return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

    def _escolha(msg, keyword):
        """Retorna True se acolheu, False se não acolheu, None se não encontrou."""
        msg_n = _strip_accents(msg).upper()
        kw_n = _strip_accents(keyword).upper()
        if re.search(rf'{kw_n}.{{0,30}}NAO ACOLHID', msg_n):
            return False
        if re.search(rf'{kw_n}.{{0,30}}ACOLHID', msg_n):
            return True
        m = re.search(rf'{kw_n}\w*\s*[-:\s]\s*([AB])\b', msg_n)
        if m:
            return m.group(1) == 'A'
        return None

    acolhe_temp  = _escolha(message, 'TEMPESTIVIDADE')
    acolhe_punit = _escolha(message, 'PUNITIV')
    acolhe_inter = _escolha(message, 'INTERCORRENTE')
    acolhe_decad = _escolha(message, 'DECAD')

    # ── DIV-05: parser silencioso — avisar quando nenhuma escolha foi detectada ──
    _nenhuma_escolha = all(x is None for x in [acolhe_temp, acolhe_punit, acolhe_inter, acolhe_decad])
    _msg_simples = message.strip().lower() in _MSG_CONFIRMA

    if _nenhuma_escolha and not _msg_simples:
        return (
            "⚠️ **Não consegui identificar suas escolhas.** Responda no formato:\n\n"
            "```\n"
            "Tempestividade - A\n"
            "Prescrição Punitiva - B\n"
            "Prescrição Intercorrente - A\n"
            "Decadência - A\n"
            "```\n\n"
            "Ou digite **ok** para confirmar todos os resultados automáticos do JariMath."
        )

    logger.warning(
        f"[FASE31] parecer={parecer.id} | "
        f"temp={acolhe_temp} punit={acolhe_punit} inter={acolhe_inter} decad={acolhe_decad} | "
        f"auto: temp={parecer.is_tempestivo} punit={parecer.has_prescricao_punitiva} "
        f"inter={parecer.has_prescricao_intercorrente} decad={parecer.has_decadencia} | "
        f"msg_preview={repr(message[:120])}"
    )

    def _flag(acolhe, automatico):
        """
        Semântica RELATIVA: A = CONFIRMAR (mantém o resultado automático),
        B = INVERTER (oposto do resultado automático).
        None = sem escolha explícita → usa resultado automático do JariMath.
        """
        if acolhe is None:
            return automatico
        if acolhe is True:   # A (Confirmar) → mantém o automático
            return automatico
        # acolhe is False: B (Inverter) → inverte o automático
        return (not automatico) if automatico is not None else False

    # ── DIV-03: Blindagem Filtro 1 — decadência para infrações < 12/04/2021 é PROIBIDA ──
    # Semântica RELATIVA (pós BUG-B): acolhe_decad=False significa B (INVERTER), ou seja,
    # o julgador está tentando forçar SIM a partir de um automático NÃO/NÃO SE APLICA.
    # É exatamente esse caso que deve ser bloqueado para infrações no Filtro 1.
    aviso_filtro1 = ""
    if acolhe_decad is False:  # B (INVERTER) = julgador tentando forçar SIM
        data_inf = getattr(parecer, 'data_infracao', None)
        if data_inf and data_inf < _LIMIAR_FILTRO_1:
            acolhe_decad = True  # força A (CONFIRMAR): mantém automático = NÃO SE APLICA
            aviso_filtro1 = (
                "\n\n⚠️ **CONVERSÃO BLOQUEADA — Blindagem Filtro 1 (CETRAN/SC 381/2022)**\n"
                "A infração ocorreu antes de 12/04/2021. A declaração de decadência de 180/360 dias "
                "é expressamente proibida para este período. A tentativa de inversão foi bloqueada."
            )
            logger.warning(
                f"[FASE31] Filtro 1 blindagem ativada: parecer={parecer.id} "
                f"data_infracao={data_inf} — declaração de decadência bloqueada"
            )

    # M1-FIX: Conversão NÃO SE APLICA → SIM para Filtro 2 Suspensão/Cassação.
    # Spec logica_jari.md §371-373: quando o resultado automático é NÃO SE APLICA (Filtro 2 Suspensão)
    # e o julgador escolhe B (Afastar), o sistema deve converter para SIM — julgador força análise decadencial.
    aviso_filtro2_suspensao = ""
    if (acolhe_decad is False                    # julgador escolheu B (afastar)
            and parecer.has_decadencia is False  # automático retornou NÃO SE APLICA
            and aviso_filtro1 == ""):            # não bloqueado pelo Filtro 1
        data_inf_m1 = getattr(parecer, 'data_infracao', None)
        tipo_pen_m1 = (getattr(parecer, 'tipo_penalidade', None) or '').lower()
        _e_grave_m1 = tipo_pen_m1 in ('suspensao', 'cassacao')
        _e_filtro2_m1 = (data_inf_m1 and
                         data_inf_m1 >= _LIMIAR_FILTRO_1 and
                         data_inf_m1 < datetime.date(2021, 10, 22))
        if _e_grave_m1 and _e_filtro2_m1:
            # acolhe_decad permanece False (B=inverter): _flag(False, False) = True = SIM
            # NÃO mudar acolhe_decad para True — isso bloquearia a conversão (bug M1-FIX)
            aviso_filtro2_suspensao = (
                "\n\n✅ **CONVERSÃO FILTRO 2 SUSPENSÃO — NÃO SE APLICA → SIM**\n"
                "O julgador escolheu B (Afastar) para penalidade de suspensão/cassação no período "
                "Filtro 2 (12/04/2021–21/10/2021). A Nota CETRAN/SC 02/03/2023 não é absoluta; "
                "o julgador pode forçar análise decadencial. Decadência convertida para **SIM**."
            )
            logger.warning(
                "[FASE31] Filtro 2 Suspensão NÃO SE APLICA→SIM: parecer=%s tipo=%s data_inf=%s",
                parecer.id, tipo_pen_m1, data_inf_m1,
            )

    parecer.julgador_tempestivo               = _flag(acolhe_temp,  parecer.is_tempestivo)
    parecer.julgador_prescricao_punitiva      = _flag(acolhe_punit, parecer.has_prescricao_punitiva)
    parecer.julgador_prescricao_intercorrente = _flag(acolhe_inter, parecer.has_prescricao_intercorrente)
    parecer.julgador_decadencia               = _flag(acolhe_decad, parecer.has_decadencia)
    parecer.save()

    # Roteamento por precedência: C (Decadência) > B (Prescrição) > A (Intempestividade) > D (mérito)
    prejudica = (
        parecer.julgador_prescricao_punitiva
        or parecer.julgador_prescricao_intercorrente
        or parecer.julgador_decadencia
        or (parecer.julgador_tempestivo is False)
    )

    if prejudica:
        from chat.engine import FASE_RESULTADO
        motivo = []
        if parecer.julgador_prescricao_punitiva:      motivo.append("PRESCRIÇÃO PUNITIVA")
        if parecer.julgador_prescricao_intercorrente: motivo.append("PRESCRIÇÃO INTERCORRENTE")
        if parecer.julgador_decadencia:               motivo.append("DECADÊNCIA")
        if parecer.julgador_tempestivo is False:      motivo.append("INTEMPESTIVIDADE")
        parecer.tese = f"MÉRITO PREJUDICADO ({' / '.join(motivo)})."
        parecer.status_fase = FASE_RESULTADO
        parecer.save()

        from chat.tasks import gerar_parecer_task
        task = gerar_parecer_task.delay(parecer.id)
        # aviso_filtro1 não pode ser embutido no JSON Celery; se existir, será registrado no log
        return json.dumps({"status": "celery", "task_id": task.id, "type": "PREJUDICIALIDADE"})

    return engine.run_phase_4_extraction() + aviso_filtro1 + aviso_filtro2_suspensao
