"""
Fase 7 — Seleção de pasta e salvamento do processo.
"""


def get_prompt(parecer) -> str:
    """Exibe o formulário de seleção de pasta."""
    from chat.models import Pasta

    pastas = list(Pasta.objects.filter(user=parecer.user).order_by('nome_pasta'))

    prompt = "[FEEDBACK_FORM]\n\n**Organização e Salvamento**\n\nSelecione qual pasta você deseja usar para salvar esta análise clicando no card correspondente:\n\n"
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
    sgpe = parecer.sgpe if parecer.sgpe else parecer.pa or ''
    recorrente_nome = parecer.recorrente if parecer.recorrente else 'Recorrente Não Informado'
    parecer.nome_processo = f"Parecer {recorrente_nome} - {sgpe}".strip(' -')
    parecer.is_saved = True
    parecer.status_fase = FASE_FINALIZADO
    parecer.save()

    # Desconta 1 crédito ao salvar (apenas usuários não-PRO)
    if parecer.user:
        try:
            profile = parecer.user.profile
            if not profile.is_pro and profile.credits > 0:
                profile.credits -= 1
                profile.save(update_fields=['credits'])
        except Exception:
            pass

    return f"✅ **Sucesso!** O projeto foi salvo na pasta **{target_folder.nome_pasta}**."
