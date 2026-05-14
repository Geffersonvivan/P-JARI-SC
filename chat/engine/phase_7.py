"""
Fase 7 — Seleção de pasta e salvamento do processo.
"""


def get_prompt(parecer) -> str:
    """Exibe o formulário de seleção de pasta."""
    from chat.models import Pasta

    pastas = list(Pasta.objects.filter(user=parecer.user).order_by('nome_pasta'))

    prompt = "**Organização e Salvamento**\n\nSelecione qual pasta você deseja usar para salvar esta análise clicando no card correspondente:\n\n"
    folder_payloads = [f"{i}::{p.nome_pasta}" for i, p in enumerate(pastas, 1)]
    prompt += f"[FOLDER_SELECT:{'|'.join(folder_payloads)}]"
    return prompt


def process(engine, message: str) -> str:
    """Salva o processo na pasta selecionada (mensagem = nome da pasta)."""
    from chat.models import Pasta
    from chat.engine import FASE_FINALIZADO

    parecer = engine.parecer
    nome_pasta = message.strip()

    try:
        target_folder = Pasta.objects.get(user=parecer.user, nome_pasta=nome_pasta)
    except Pasta.DoesNotExist:
        # Fallback: tenta por índice numérico (compatibilidade com cliente legado)
        try:
            idx = int(nome_pasta) - 1
            pastas = list(Pasta.objects.filter(user=parecer.user).order_by('nome_pasta'))
            if 0 <= idx < len(pastas):
                target_folder = pastas[idx]
            else:
                return f"Pasta não encontrada. Por favor, selecione uma pasta válida."
        except (ValueError, IndexError):
            return f"Pasta não encontrada: {nome_pasta}"

    parecer.pasta = target_folder
    recorrente_nome = parecer.recorrente if parecer.recorrente else 'Recorrente Não Informado'
    parecer.nome_processo = f"Parecer {recorrente_nome}".strip()
    parecer.is_saved = True
    parecer.status_fase = FASE_FINALIZADO
    parecer.save()

    # Desconta 1 crédito ao salvar (apenas usuários não-PRO)
    # D16 FIX: decremento atômico via F() para evitar race condition de crédito negativo
    if parecer.user:
        try:
            from django.db.models import F
            from django.db import transaction
            profile = parecer.user.profile
            if not profile.is_pro:
                with transaction.atomic():
                    updated = profile.__class__.objects.filter(
                        pk=profile.pk, credits__gt=0
                    ).update(credits=F('credits') - 1)
                    if not updated:
                        import logging as _log
                        _log.getLogger(__name__).warning(
                            "[FASE7] Crédito não decrementado — saldo zero ou conta PRO. user=%s", parecer.user.id
                        )
        except Exception:
            pass

    try:
        from chat.models import log_audit
        profile = parecer.user.profile if parecer.user else None
        log_audit('parecer_finalizado', parecer=parecer, fase=8, dados={
            'pasta': target_folder.nome_pasta,
            'blindagem_score': parecer.blindagem_score,
            'tempo_julgamento_segundos': parecer.tempo_julgamento_segundos,
        })
        if profile and not profile.is_pro:
            log_audit('credito_consumido', parecer=parecer, fase=8, dados={
                'saldo_anterior': profile.credits + 1,
                'saldo_atual': profile.credits,
            })
    except Exception:
        pass

    return f"**Sucesso!** O projeto foi salvo na pasta **{target_folder.nome_pasta}**."
