"""
Fase 6 — Auditoria de conformidade (JariMath + Gemini checklist).
"""

import re
import logging

logger = logging.getLogger(__name__)


def process(engine, message: str) -> str:
    """Aguarda 'ok' do julgador para executar a auditoria."""
    msg = message.strip()
    if msg.lower() == 'ok':
        return run(engine)
    if msg.upper().startswith('EDITAR:'):
        return _salvar_edicao(engine, msg[len('EDITAR:'):].strip())
    return "DIGITE 'ok' para auditoria final em tela, ou use o botão **Editar texto** para revisar o parecer."


def _salvar_edicao(engine, novo_texto: str) -> str:
    """Salva o texto editado do parecer e retorna ao prompt da fase 6."""
    if not novo_texto:
        return "Texto vazio — edição não salva. Use o botão **Editar texto** para revisar o parecer."
    parecer = engine.parecer
    parecer.parecer_final = novo_texto
    parecer.save(update_fields=['parecer_final'])
    logger.info("[FASE6] parecer editado manualmente | parecer=%s | chars=%s", parecer.id, len(novo_texto))
    return engine.get_current_prompt()


def run(engine) -> str:
    """Executa a auditoria e avança para FASE_SELECAO_PASTA."""
    from chat.integrations import GeminiClient
    from chat.engine import FASE_SELECAO_PASTA
    from django.utils import timezone

    parecer = engine.parecer

    # ── Validação de compatibilidade (JariMath soberano) ─────────────────────
    erro_fatal = False
    incompatibilidade_msg = ""

    parecer_raw = parecer.parecer_final or ""
    if parecer_raw.startswith("⚠️") or "ERRO DE CONFIGURAÇÃO" in parecer_raw:
        incompatibilidade_msg = "❌ Parecer não gerado: verifique a configuração da API (ANTHROPIC_API_KEY)."
        parecer.blindagem_score = 0
        parecer.blindagem_detalhes = incompatibilidade_msg
        parecer.status_fase = FASE_SELECAO_PASTA
        parecer.save()
        return incompatibilidade_msg

    texto_parecer = parecer_raw.upper()

    flag_punitiva   = parecer.julgador_prescricao_punitiva    if parecer.julgador_prescricao_punitiva    is not None else parecer.has_prescricao_punitiva
    flag_intercorr  = parecer.julgador_prescricao_intercorrente if parecer.julgador_prescricao_intercorrente is not None else parecer.has_prescricao_intercorrente
    flag_decadencia = parecer.julgador_decadencia             if parecer.julgador_decadencia             is not None else parecer.has_decadencia
    flag_tempestivo = parecer.julgador_tempestivo             if parecer.julgador_tempestivo             is not None else parecer.is_tempestivo

    tem_deferido   = bool(re.search(r'\bDEFERIDO\b',   texto_parecer))
    tem_indeferido = bool(re.search(r'\bINDEFERIDO\b', texto_parecer))

    # BUG-E-FIX: ROTA D — tese acolhida na F4 também exige DEFERIDO
    _rota_d = "RESULTADO EXIGIDO NESTE PARECER: DEFERIDO" in (parecer.analise_tese_texto or "")

    if flag_punitiva or flag_intercorr or flag_decadencia or _rota_d:
        if not tem_deferido:
            erro_fatal = True
            motivo_d = "extinção da pretensão punitiva" if (flag_punitiva or flag_intercorr or flag_decadencia) else "tese acolhida pelo julgador (Rota D)"
            incompatibilidade_msg = f"❌ Resultado incompatível com {motivo_d} (Deveria ser DEFERIDO)"
    elif flag_tempestivo is False:
        if not tem_indeferido:
            erro_fatal = True
            incompatibilidade_msg = "❌ Resultado incompatível com a Intempestividade do recurso (Deveria ser INDEFERIDO)"

    # ── Checklist programático (10 itens §504-515) ───────────────────────────
    # M9 FIX: ponderação separada — erro fatal (peso 5) vs advertência (peso 1)
    # Score = (pontos_conformes / 10) * 100. Erros fatais pesam 5x mais que advertências.
    pontos_fatais = 0    # acumulado de erros fatais (máx 5)
    pontos_avisos = 0    # acumulado de advertências (máx 5)
    inconsistencias = []
    advertencias = []    # itens de advertência (cabeçalho, vedações)
    parecer_final = parecer.parecer_final or ""

    # Item 2 — RESULTADO: incompatibilidade fatal (peso 5 de 10)
    if erro_fatal:
        pontos_fatais += 5
        inconsistencias.append(incompatibilidade_msg)

    # Item 1 — CABEÇALHO: PA, SGPE, Recorrente, Data Sessão (peso 1 cada, máx 4)
    if parecer.sgpe and parecer.sgpe not in parecer_final:
        pontos_avisos += 1
        advertencias.append("CABEÇALHO: SGPE ausente ou incorreto no Parecer.")

    if parecer.pa and parecer.pa not in parecer_final:
        pontos_avisos += 1
        advertencias.append("CABEÇALHO: PA ausente ou incorreto no Parecer.")

    if parecer.recorrente:
        nome_partes = parecer.recorrente.strip().split()
        sobrenome = nome_partes[-1] if nome_partes else ""
        if sobrenome and sobrenome.upper() not in parecer_final.upper():
            pontos_avisos += 1
            advertencias.append(f"CABEÇALHO: Nome do recorrente ('{parecer.recorrente}') ausente no Parecer.")

    if parecer.data_sessao:
        data_str_br = parecer.data_sessao.strftime("%d/%m/%Y")
        if data_str_br not in parecer_final:
            pontos_avisos += 1
            advertencias.append(f"CABEÇALHO: Data da sessão ({data_str_br}) ausente no Parecer.")

    # Item 10 — VEDAÇÕES §515: emojis, fases internas, motores de IA (peso 1 total)
    _VEDACOES_AI = ['PERPLEXITY', 'GEMINI', 'VERTEX', 'CLAUDE', 'ANTHROPIC', 'CHATGPT', 'OPENAI']
    texto_upper = parecer_final.upper()
    _ai_encontrada = next((n for n in _VEDACOES_AI if n in texto_upper), None)
    if _ai_encontrada:
        pontos_avisos += 1
        advertencias.append(f"VEDACOES: Parecer menciona motor de IA '{_ai_encontrada}' (vedado §515).")

    if re.search(r'\bFASE\s*\d', parecer_final, re.IGNORECASE):
        pontos_avisos += 1
        advertencias.append("VEDACOES: Parecer menciona fases internas do sistema (vedado §515).")

    if re.search(r'[\U00010000-\U0010FFFF\U00002600-\U000027BF\U0001F000-\U0001FFFF]', parecer_final):
        pontos_avisos += 1
        advertencias.append("VEDACOES: Parecer contém emojis (vedado §515).")

    # Score ponderado: erros fatais (5 pts max) + advertências (5 pts max) = 10 pts total
    pontos_conformes = max(0, 10 - pontos_fatais - pontos_avisos)
    indice = (pontos_conformes / 10) * 100

    # Unificar inconsistencias para log/email — erros fatais primeiro, depois advertências
    inconsistencias += [f"Aviso: {a}" for a in advertencias]

    parecer.blindagem_score = int(indice)

    # ── C2 FIX: bloquear avanço quando há incompatibilidade fatal ────────────
    # O julgador deve usar "Editar texto" para corrigir o parecer e depois digitar "ok" novamente.
    if erro_fatal:
        detalhe_bloco = "\n".join(inconsistencias)
        parecer.blindagem_detalhes = detalhe_bloco
        parecer.save(update_fields=['blindagem_score', 'blindagem_detalhes'])
        logger.warning(
            "[FASE6] BLOQUEIO por incompatibilidade fatal: parecer=%s | %s",
            parecer.id, incompatibilidade_msg,
        )
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            _admin_email = getattr(settings, 'ADMIN_EMAIL', settings.DEFAULT_FROM_EMAIL)
            assunto = f"P-JARI: Inconsistencia Critica detectada na IA ({parecer.sgpe or parecer.nome_processo})"
            mensagem = (
                f"O JariEngine detectou incompatibilidade fatal na Fase 6.\n\n"
                f"Processo: {parecer.nome_processo}\n"
                f"SGPE / PA: {parecer.sgpe or parecer.pa or 'Não Informado'}\n"
                f"Inconsistência: {incompatibilidade_msg}\n\n"
                f"--- Trecho do Parecer ---\n"
                f"{parecer.parecer_final[:1500]}... [Ver Completo na Ferramenta]\n\n"
                f"Session Key: {parecer.session_key}"
            )
            send_mail(
                subject=assunto, message=mensagem,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[_admin_email], fail_silently=True,
            )
        except Exception as e:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
            logger.error("Erro ao disparar email de auditoria Fase 6: %s", e)
        return (
            f"⛔ **AUDITORIA BLOQUEADA — Incompatibilidade Fatal**\n\n"
            f"{incompatibilidade_msg}\n\n"
            f"O parecer não pode avançar com esta inconsistência. Use o botão **Editar texto** "
            f"para corrigir o resultado do parecer e depois digite **ok** novamente."
        )

    if inconsistencias:
        parecer.blindagem_detalhes = "\n".join(inconsistencias)
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            # D15 FIX: avisar explicitamente quando ADMIN_EMAIL não configurado
            _admin_email = getattr(settings, 'ADMIN_EMAIL', None)
            if not _admin_email:
                logger.warning(
                    "[FASE6] ADMIN_EMAIL não configurado — email de auditoria NÃO enviado. "
                    "Configure ADMIN_EMAIL no settings para receber alertas. parecer=%s", parecer.id
                )
            else:
                assunto = f"P-JARI: Inconsistencia Critica detectada na IA ({parecer.sgpe or parecer.nome_processo})"
                mensagem = (
                    f"O JariEngine detectou inconsistências de validação matemática durante a auditoria (Fase 6).\n\n"
                    f"Processo: {parecer.nome_processo}\n"
                    f"SGPE / PA: {parecer.sgpe or parecer.pa or 'Não Informado'}\n"
                    f"Inconsistências Listadas:\n{parecer.blindagem_detalhes}\n\n"
                    f"--- Trecho do Parecer (Problema) ---\n"
                    f"{parecer.parecer_final[:1500]}... [Ver Completo na Ferramenta]\n\n"
                    f"Session Key para Bug Tracking: {parecer.session_key}"
                )
                send_mail(
                    subject=assunto,
                    message=mensagem,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[_admin_email],
                    fail_silently=True,
                )
        except Exception as e:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
            logger.error("Erro ao disparar email de auditoria Fase 6: %s", e)

    parecer.status_fase = FASE_SELECAO_PASTA
    parecer.save()

    # ── Checklist qualitativo via Gemini ──────────────────────────────────────
    gemini = GeminiClient()
    checklist_texto = gemini.audit_parecer(parecer)

    # Salva o relatório completo em blindagem_detalhes (usado pelo wizard JariMatch)
    full_blindagem = "### 🛡️ Auditoria Final de Conformidade\n\n"
    if inconsistencias:
        full_blindagem += f"⚠️ **Inconsistências Críticas (JariMath):** {' '.join(inconsistencias)}\n\n"
    full_blindagem += checklist_texto
    parecer.blindagem_detalhes = full_blindagem
    parecer.save(update_fields=['blindagem_detalhes'])

    # GAP-08: persistir resultado estruturado da auditoria para rastreabilidade
    try:
        parecer.checklist_auditoria_json = {
            "jari_math": {
                "score": parecer.blindagem_score,
                "inconsistencias": inconsistencias,
                "erro_fatal": erro_fatal,
            },
            "checklist_gemini_raw": checklist_texto,
            "timestamp": timezone.now().isoformat(),
        }
        parecer.save(update_fields=['checklist_auditoria_json'])
    except Exception as e:
        # D10 FIX: erro silencioso substituído por log crítico com sentry
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        logger.error(
            "[FASE6] FALHA ao salvar checklist_auditoria_json — rastreabilidade comprometida: "
            "parecer=%s erro=%s", parecer.id, e
        )

    # ── Tempo total de julgamento ─────────────────────────────────────────────
    try:
        inicio = parecer.created_at
        agora = timezone.now()
        diff_segundos = int((agora - inicio).total_seconds())
        parecer.tempo_julgamento_segundos = diff_segundos
        parecer.save(update_fields=['tempo_julgamento_segundos'])
        minutos = diff_segundos // 60
        segundos = diff_segundos % 60
        tempo_str = f"{minutos:02d}m {segundos:02d}s"
    except Exception:
        tempo_str = "00m --s"

    # ── Relatório final ───────────────────────────────────────────────────────
    report = "### 🛡️ Auditoria Final de Conformidade\n\n"

    if indice != 100:
        report += f"⚠️ **Inconsistências Críticas (JariMath):**\n{parecer.blindagem_detalhes}\n\n"

    report += f"---\n\n{checklist_texto}\n\n"
    report += "---\n\n"

    if indice == 100:
        report += f"**JARI-MATH: ÍNDICE DE BLINDAGEM 100% ✅**\n\n⏳ **Tempo de Julgamento da Sessão:** {tempo_str}\n\n"
    else:
        report += f"**JARI-MATH: ÍNDICE DE BLINDAGEM {int(indice)}% ⚠️**\n\n⏳ **Tempo de Julgamento da Sessão:** {tempo_str}\n\n"

    report += f"---\n{engine.get_current_prompt()}"
    return report
