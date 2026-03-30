"""
Fase 41 — Confirmação da análise de teses pelo julgador.
Parseia as decisões Acolhida/Não Acolhida e dispara a geração do parecer.
"""

import re
import json
import logging

logger = logging.getLogger(__name__)


def get_prompt(parecer) -> str:
    """Exibe a conclusão prévia das teses."""
    return_str = f"**Conclusão Prévia das Teses**\n\n{parecer.analise_tese_texto}"
    return return_str.strip()


def process(engine, message: str) -> str:
    """Parseia as escolhas do julgador e dispara a Fase 5 via Celery."""
    parecer = engine.parecer
    escolhas = message.lower().strip()

    if not escolhas:
        return "Por favor, informe a opção escolhida para cada tese."

    # Remove ocorrências de "não acolhida" antes de buscar "acolhida" avulso
    _sem_nao = re.sub(r'n[aã]o\s+acolhid[ao]?', '', escolhas, flags=re.IGNORECASE)
    has_acolhida = (
        bool(re.search(r'\bacolhid[ao]?\b', _sem_nao, re.IGNORECASE))
        # "A" como escolha isolada: após delimitador ou início/fim de linha (evita artigos)
        or bool(re.search(r'(?:^|[-:\|,])\s*a\s*(?:$|\n|;|,)', escolhas, re.MULTILINE))
        or escolhas.strip() in ('a', 'deferir', 'deferido')
    )
    has_nao = (
        bool(re.search(r'n[aã]o\s+acolhid', escolhas, re.IGNORECASE))
        or bool(re.search(r'(?:^|[-:\|,])\s*b\s*(?:$|\n|;|,)', escolhas, re.MULTILINE))
        or bool(re.search(r'n[aã]o\s+acolher', escolhas, re.IGNORECASE))
        or escolhas.strip() in ('b', 'indeferir', 'indeferido')
    )

    if not has_acolhida and not has_nao:
        return "Não identifiquei as opções de Acolhimento na sua resposta."

    resultado_marcado = "DEFERIDO" if has_acolhida else "INDEFERIDO"

    parecer.analise_tese_texto += (
        f"\n\n--- DECISÕES ABSOLUTAS DO JULGADOR ---\n"
        f"Escolhas informadas: {escolhas}\n"
        f"RESULTADO EXIGIDO NESTE PARECER: {resultado_marcado}\n"
        f"DIRETRIZ FASE 5: Você DEVE acatar as alternativas escolhidas ("
        f"se o julgador escolheu 'Acolhida'/'A', transcreva a linha de raciocínio da Alternativa A de acolhimento; "
        f"se escolheu 'Não Acolhida'/'B', transcreva a Alternativa B de não acolhimento). "
        f"Ignore a alternativa descartada. O resultado final deve ser {resultado_marcado}."
    )

    from chat.engine import FASE_RESULTADO
    parecer.status_fase = FASE_RESULTADO
    parecer.save()

    from chat.tasks import gerar_parecer_task
    task = gerar_parecer_task.delay(parecer.id)
    return json.dumps({"status": "celery", "task_id": task.id, "type": "MERITO"})
