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

    itens_conformes = 10
    inconsistencias = []

    if erro_fatal:
        itens_conformes -= 5
        inconsistencias.append(incompatibilidade_msg)

    if parecer.sgpe and parecer.sgpe not in parecer.parecer_final:
        itens_conformes -= 1
        inconsistencias.append("❌ Inconsistente: SGPE ausente ou errado no Parecer.")

    if parecer.pa and parecer.pa not in parecer.parecer_final:
        itens_conformes -= 1
        inconsistencias.append("❌ Inconsistente: Processo Administrativo ausente ou errado no Parecer.")

    indice = (itens_conformes / 10) * 100
    if erro_fatal and indice > 50:
        indice = 50.0

    parecer.blindagem_score = int(indice)
    if inconsistencias:
        parecer.blindagem_detalhes = "\n".join(inconsistencias)
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            _admin_email = getattr(settings, 'ADMIN_EMAIL', settings.DEFAULT_FROM_EMAIL)
            assunto = f"🚨 P-JARI: Inconsistência Crítica detectada na IA ({parecer.sgpe or parecer.nome_processo})"
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
            print(f"Erro ao disparar email de auditoria Fase 6: {str(e)}")

    parecer.status_fase = FASE_SELECAO_PASTA
    parecer.save()

    # ── Checklist qualitativo via Gemini ──────────────────────────────────────
    gemini = GeminiClient()
    checklist_texto = gemini.audit_parecer(parecer)

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
        logger.warning(f"Erro ao salvar checklist_auditoria_json: {e}")

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
