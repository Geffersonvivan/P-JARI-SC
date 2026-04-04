"""
chat/engine — Motor de fases do P-JARI (JariEngine refatorado).

A classe JariEngine mantém a mesma interface pública de antes:
    - get_current_prompt()
    - process_message(message, uploaded_files)
    - run_fase1_autopreenchimento()
    - run_llm_phases(task_id=None)

Cada fase foi extraída para seu próprio módulo (phase_X.py).
O dispatch é feito aqui de forma limpa: sem blocos if/elif paralelos.
"""

from chat.models import Parecer

# ── Constantes de fase ────────────────────────────────────────────────────────
FASE_COLETA = 1
FASE_AGUARDA_CONFIRMACAO_FASE1 = 10
FASE_DIR = 2
FASE_ADMISSIBILIDADE_GERADA = 3
FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE = 31
FASE_MERITO = 4
FASE_AGUARDA_CONFIRMACAO_MERITO = 41
FASE_RESULTADO = 5
FASE_AUDITORIA = 6
FASE_SELECAO_PASTA = 7
FASE_FINALIZADO = 8


def _p(field):
    """Normaliza FileField para string de caminho, ou None."""
    if not field:
        return None
    return field.name if hasattr(field, 'name') else (str(field) or None)


class JariEngine:
    def __init__(self, parecer: Parecer):
        self.parecer = parecer

    # ── get_current_prompt ────────────────────────────────────────────────────

    def get_current_prompt(self) -> str:
        """Retorna o prompt da fase atual. Dispatch sem if/elif paralelo."""
        fase = self.parecer.status_fase

        if fase == 1:
            from .phase_1 import get_prompt
            return get_prompt(self.parecer)

        if fase == 10:
            from .phase_1 import get_confirm_prompt
            return get_confirm_prompt(self.parecer)

        if fase == 2:
            from .phase_2 import get_prompt
            return get_prompt(self.parecer)

        if fase == 3:
            return "Processando Prazos e Admissibilidade... (Simulando loading)"

        if fase == 31:
            return self.parecer.admissibilidade_texto or ""

        if fase == 4:
            from .phase_4 import get_prompt
            return get_prompt(self.parecer)

        if fase == 41:
            from .phase_4_confirm import get_prompt
            return get_prompt(self.parecer)

        if fase == 5:
            return "Gerando Parecer Técnico Final em Bloco Único... (Aguarde...)"

        if fase == 6:
            return (
                f"**Parecer Técnico Gerado com Sucesso!**\n\n"
                f"{self.parecer.parecer_final or ''}\n\n"
                f"---\n\n"
                f"Digite **'ok'** para executar a auditoria final de conformidade."
            )

        if fase == 7:
            from .phase_7 import get_prompt
            return get_prompt(self.parecer)

        if fase == 8:
            from .phase_8 import get_prompt
            return get_prompt(self.parecer)

        return "Processo finalizado ou estado inválido."

    # ── process_message ───────────────────────────────────────────────────────

    def process_message(self, message: str, uploaded_files=None) -> str:
        """Processa a mensagem do usuário e avança a fase se apropriado."""
        if uploaded_files is None:
            uploaded_files = []

        if message.strip() == 'RESUMO':
            return self.get_current_prompt()

        # ── Handler global: reiniciar processo ────────────────────────────────
        if message.strip().lower() == 'reiniciar':
            return self._reiniciar_para_fase1()

        fase = self.parecer.status_fase

        if fase == 1:
            from .phase_1 import process
            return process(self, message, uploaded_files)

        if fase == 10:
            from .phase_1 import process_confirm
            return process_confirm(self, message)

        if fase == 2:
            from .phase_2 import process
            return process(self, message)

        if fase == 3:
            from .phase_3 import process
            return process(self)

        if fase == 31:
            from .phase_3_confirm import process
            return process(self, message)

        if fase == 4:
            from .phase_4 import process
            return process(self, message)

        if fase == 41:
            from .phase_4_confirm import process
            return process(self, message)

        if fase == 5:
            from .phase_5 import process_direct
            return process_direct(self.parecer)

        if fase == 6:
            from .phase_6 import process
            return process(self, message)

        if fase == 7:
            from .phase_7 import process
            return process(self, message)

        return "Processo encontra-se finalizado."

    # ── Métodos chamados pelas Celery tasks ───────────────────────────────────

    def run_fase1_autopreenchimento(self) -> str:
        from .phase_1 import run_autopreenchimento
        return run_autopreenchimento(self)

    def run_llm_phases(self, task_id=None) -> str:
        from .phase_5 import run_llm_phases
        return run_llm_phases(self, task_id=task_id)

    # ── Métodos internos chamados entre fases ─────────────────────────────────
    # Mantidos como métodos do engine para que os módulos de fase os chamem
    # sem precisar importar o engine (evita circular import).

    def run_phase_2(self) -> str:
        from .phase_2 import run
        return run(self)

    def run_phase_3(self) -> str:
        from .phase_3 import run
        return run(self)

    def run_phase_4_extraction(self) -> str:
        from .phase_4 import run_extraction
        return run_extraction(self)

    def run_phase_4_refinement(self, user_hint: str) -> str:
        from .phase_4 import run_refinement
        return run_refinement(self, user_hint)

    def analise_tese_fase_4(self) -> str:
        from .phase_4 import analise_tese
        return analise_tese(self)

    def run_phase_6(self) -> str:
        from .phase_6 import run
        return run(self)

    def _reiniciar_para_fase1(self) -> str:
        """Reseta todos os campos computados e retorna o processo à FASE_COLETA."""
        import logging as _logging
        _log = _logging.getLogger(__name__)

        p = self.parecer
        if p.status_fase <= FASE_COLETA:
            return "O processo já está na fase inicial. Preencha os dados para começar."
        if p.status_fase >= FASE_SELECAO_PASTA:
            return "Este processo já foi finalizado e salvo. Não é possível reiniciá-lo."

        _campos_nullables = [
            'pa', 'sgpe', 'recorrente', 'data_sessao', 'data_protocolo', 'prazo_final',
            'paginas_defesa', 'fase1_extracao_json', 'tipo_penalidade', 'data_conclusao_multa',
            'tem_flagrante', 'data_conhecimento_infracao', 'data_infracao', 'data_totalizacao_pontos',
            'is_tempestivo', 'has_prescricao_punitiva', 'has_prescricao_intercorrente', 'has_decadencia',
            'julgador_tempestivo', 'julgador_prescricao_punitiva',
            'julgador_prescricao_intercorrente', 'julgador_decadencia',
            'admissibilidade_texto', 'tese', 'vertex_result', 'perplexity_result',
            'analise_tese_texto', 'parecer_final', 'tabela_datas_sensiveis',
            'infracao_documento', 'dossie_fontes', 'nota_blindagem',
            'blindagem_score', 'blindagem_detalhes', 'checklist_auditoria_json',
            'tempo_julgamento_segundos',
        ]
        for campo in _campos_nullables:
            setattr(p, campo, None)

        p.status_fase = FASE_COLETA
        p.save()

        _log.info("[ENGINE] reiniciar | parecer=%s", p.id)

        from .phase_1 import get_prompt
        return "🔄 **Processo reiniciado.** Todos os dados foram apagados.\n\n" + get_prompt(p)
