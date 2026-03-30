"""
Fase 8 — Processo finalizado. Exibe o parecer salvo.
"""


def get_prompt(parecer) -> str:
    res = f"**{parecer.nome_processo} - Parecer Finalizado**\n\n"
    if parecer.parecer_final:
        res += parecer.parecer_final + "\n\n"
        if parecer.dossie_fontes:
            res += (
                "<details class='mt-4 mb-2 bg-blue-50/50 rounded-xl border border-blue-100/50 overflow-hidden shadow-sm'>"
                "<summary class='px-4 py-3 bg-white/50 cursor-pointer text-[#444746] font-medium flex items-center gap-2 hover:bg-blue-50/50 transition-colors outline-none'>"
                "🔎 FUNDAMENTAÇÃO NORMATIVA - PARECER</summary>"
                f"<div class='p-4 text-sm text-[#444746] leading-relaxed border-t border-blue-100/50 bg-white/30 whitespace-pre-wrap'>{parecer.dossie_fontes}</div>"
                "</details>"
            )
    else:
        res += "*(Sem parecer técnico gerado para este processo)*"
    return res
