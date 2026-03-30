"""
Fase 7 — Seleção de pasta e salvamento do processo.
"""


def get_prompt(parecer) -> str:
    """Exibe o formulário de seleção de pasta."""
    from chat.models import Pasta

    pasta_outros, _ = Pasta.objects.get_or_create(user=parecer.user, nome_pasta="Outros")
    pastas_dinamicas = list(
        Pasta.objects.filter(user=parecer.user).exclude(id=pasta_outros.id).order_by('-created_at')
    )
    pastas = [pasta_outros] + pastas_dinamicas

    prompt = "[FEEDBACK_FORM]\n\n**Organização e Salvamento**\n\nSelecione qual pasta você deseja usar para salvar esta análise clicando no card correspondente:\n\n"
    folder_payloads = [f"{i}::{p.nome_pasta}" for i, p in enumerate(pastas, 1)]
    prompt += f"[FOLDER_SELECT:{'|'.join(folder_payloads)}]"
    return prompt


def process(engine, message: str) -> str:
    """Salva o processo na pasta selecionada."""
    from chat.models import Pasta
    from chat.engine import FASE_FINALIZADO

    parecer = engine.parecer
    pasta_outros, _ = Pasta.objects.get_or_create(user=parecer.user, nome_pasta="Outros")
    pastas_dinamicas = list(
        Pasta.objects.filter(user=parecer.user).exclude(id=pasta_outros.id).order_by('-created_at')
    )
    pastas = [pasta_outros] + pastas_dinamicas

    try:
        idx = int(message.strip()) - 1
        if 0 <= idx < len(pastas):
            target_folder = pastas[idx]
            parecer.pasta = target_folder
            sgpe = parecer.sgpe if parecer.sgpe else parecer.pa or ''
            recorrente_nome = parecer.recorrente if parecer.recorrente else 'Recorrente Não Informado'
            parecer.nome_processo = f"Parecer {recorrente_nome} - {sgpe}".strip(' -')
            parecer.is_saved = True
            parecer.status_fase = FASE_FINALIZADO
            parecer.save()
            return f"✅ **Sucesso!** O projeto foi salvo na pasta **{target_folder.nome_pasta}**. Você pode consultá-lo na barra lateral no futuro."
        else:
            return f"Número inválido. Por favor, escolha um número de 1 a {len(pastas)}."
    except ValueError:
        return "Por favor, digite apenas o **número** correspondente à pasta desejada."
