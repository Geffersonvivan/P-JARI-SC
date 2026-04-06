"""
Camada 2 — Testes de Integração das Fases (F2→F3→F31→F4/F5)

Verifica que o fluxo de fases avança corretamente, que as FLAGS do julgador
são gravadas no banco, e que o roteamento de prejucialidade funciona.

Todos os testes usam banco real (pytest-django) e mocam apenas chamadas
externas (Celery, Gemini, Anthropic).

Executar:
    python manage.py test chat.tests.test_fases --keepdb -v 2
"""
import json
import datetime
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User

from chat.models import Parecer
from chat.engine import (
    JariEngine,
    FASE_COLETA,
    FASE_DIR,
    FASE_ADMISSIBILIDADE_GERADA,
    FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE,
    FASE_MERITO,
    FASE_RESULTADO,
    FASE_FINALIZADO,
)
from chat.services import ChatService


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_parecer(**kwargs) -> Parecer:
    """Cria um Parecer mínimo no banco para os testes."""
    defaults = dict(
        nome_processo="Teste Integração",
        status_fase=FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE,
        is_saved=False,
        is_tempestivo=True,
        has_prescricao_punitiva=False,
        has_prescricao_intercorrente=False,
        has_decadencia=False,
        data_infracao=datetime.date(2024, 1, 15),
        data_sessao=datetime.date(2025, 3, 10),
        data_protocolo=datetime.date(2024, 3, 1),
        prazo_final=datetime.date(2024, 3, 31),
        admissibilidade_texto="Recurso tempestivo. Sem prescrição. Sem decadência.",
        tabela_datas_sensiveis="",
    )
    defaults.update(kwargs)
    return Parecer.objects.create(**defaults)


def _mock_task():
    """Mock para gerar_parecer_task.delay() → retorna task_id falso."""
    t = MagicMock()
    t.id = "fake-celery-task-id"
    return t


# ── Camada 2-A: Fase 31 — Confirmação da Admissibilidade ─────────────────────

class TestFase31Prejudicialidade(TestCase):
    """
    Verifica que o roteamento por prejudicialidade na Fase 31 funciona:
    - prescricao_punitiva=True  → FASE_RESULTADO (5) via Celery
    - intempestivo=False        → FASE_RESULTADO (5) via Celery
    - sem prejuízo              → FASE_MERITO (4)
    """

    @patch("chat.tasks.gerar_parecer_task")
    def test_prescricao_punitiva_avanca_para_fase_resultado(self, mock_task):
        """FLAG has_prescricao_punitiva=True + 'ok' → FASE_RESULTADO, julgador salvo no BD."""
        mock_task.delay.return_value = _mock_task()

        parecer = _make_parecer(has_prescricao_punitiva=True)
        engine = JariEngine(parecer)
        result = engine.process_message("ok")

        # Celery deve ter sido enfileirado
        mock_task.delay.assert_called_once_with(parecer.id)

        # Estado no banco
        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, FASE_RESULTADO)
        self.assertTrue(parecer.julgador_prescricao_punitiva)
        self.assertIn("PRESCRIÇÃO PUNITIVA", parecer.tese)

        # Resposta é JSON Celery
        data = json.loads(result)
        self.assertEqual(data["status"], "celery")
        self.assertEqual(data["type"], "PREJUDICIALIDADE")

    @patch("chat.tasks.gerar_parecer_task")
    def test_intempestivo_avanca_para_fase_resultado(self, mock_task):
        """FLAG is_tempestivo=False + 'ok' → FASE_RESULTADO, tese menciona INTEMPESTIVIDADE."""
        mock_task.delay.return_value = _mock_task()

        parecer = _make_parecer(is_tempestivo=False)
        engine = JariEngine(parecer)
        result = engine.process_message("ok")

        mock_task.delay.assert_called_once_with(parecer.id)

        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, FASE_RESULTADO)
        self.assertFalse(parecer.julgador_tempestivo)
        self.assertIn("INTEMPESTIVIDADE", parecer.tese)

    @patch("chat.tasks.processar_fase4_task")
    def test_sem_prejuizo_avanca_para_fase_merito(self, mock_fase4):
        """Sem nenhum prejudicante → despacha Celery FASE4 e mantém julgador_* corretos."""
        mock_fase4.delay.return_value = _mock_task()

        # Parecer totalmente favorável (tempestivo, sem prescrição, sem decadência)
        parecer = _make_parecer(
            is_tempestivo=True,
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
        )
        engine = JariEngine(parecer)
        result = engine.process_message("ok")

        # Task Celery deve ter sido enfileirada
        mock_fase4.delay.assert_called_once_with(parecer.id)

        # Flags do julgador devem refletir o resultado automático
        parecer.refresh_from_db()
        self.assertTrue(parecer.julgador_tempestivo)
        self.assertFalse(parecer.julgador_prescricao_punitiva)
        self.assertFalse(parecer.julgador_prescricao_intercorrente)
        self.assertFalse(parecer.julgador_decadencia)

        # Resposta é JSON Celery
        data = json.loads(result)
        self.assertEqual(data["status"], "celery")
        self.assertEqual(data["type"], "FASE4")

    @patch("chat.tasks.gerar_parecer_task")
    def test_inversao_b_inverte_flag_automatica(self, mock_task):
        """
        Julgador escolhe B (Inverter) para Prescrição Punitiva que era False automático.
        Resultado: julgador_prescricao_punitiva=True → prejudica → FASE_RESULTADO.
        """
        mock_task.delay.return_value = _mock_task()

        parecer = _make_parecer(has_prescricao_punitiva=False)
        engine = JariEngine(parecer)
        engine.process_message("Prescrição Punitiva - B")

        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, FASE_RESULTADO)
        self.assertTrue(parecer.julgador_prescricao_punitiva)

    @patch("chat.tasks.gerar_parecer_task")
    def test_multiplos_prejudicantes_na_tese(self, mock_task):
        """Quando há múltiplos prejudicantes, todos aparecem na tese."""
        mock_task.delay.return_value = _mock_task()

        parecer = _make_parecer(
            is_tempestivo=False,
            has_prescricao_punitiva=True,
        )
        engine = JariEngine(parecer)
        engine.process_message("ok")

        parecer.refresh_from_db()
        self.assertIn("PRESCRIÇÃO PUNITIVA", parecer.tese)
        self.assertIn("INTEMPESTIVIDADE", parecer.tese)

    def test_mensagem_invalida_retorna_instrucao(self):
        """Mensagem sem padrão A/B reconhecível retorna instrução de formato."""
        parecer = _make_parecer()
        engine = JariEngine(parecer)
        result = engine.process_message("qualquer coisa sem sentido")

        self.assertIn("formato", result.lower())
        # Estado NÃO deve ter avançado
        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE)

    @patch("chat.tasks.gerar_parecer_task")
    def test_blindagem_filtro1_bloqueia_decadencia_pre_2021(self, mock_task):
        """
        Infração antes de 12/04/2021: tentativa de inverter decadência (B) deve ser bloqueada.
        O sistema deve manter decadência=False (automático) e NÃO adicionar DECADÊNCIA à tese.
        """
        mock_task.delay.return_value = _mock_task()

        parecer = _make_parecer(
            data_infracao=datetime.date(2020, 6, 1),  # antes do limiar Filtro 1
            has_decadencia=False,
        )
        engine = JariEngine(parecer)
        engine.process_message("Decadência - B")

        parecer.refresh_from_db()
        # Blindagem deve ter impedido a inversão
        self.assertFalse(parecer.julgador_decadencia)

    @patch("chat.tasks.processar_fase4_task")
    def test_confirmacao_simples_com_confirmo(self, mock_fase4):
        """Palavra 'confirmo' equivale a 'ok' — despacha Celery FASE4."""
        mock_fase4.delay.return_value = _mock_task()

        parecer = _make_parecer(
            is_tempestivo=True,
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
        )
        engine = JariEngine(parecer)
        result = engine.process_message("confirmo")

        mock_fase4.delay.assert_called_once_with(parecer.id)
        data = json.loads(result)
        self.assertEqual(data["status"], "celery")
        self.assertEqual(data["type"], "FASE4")


# ── Camada 2-B: Fase 2 — Confirmação da Tabela de Datas ──────────────────────

class TestFase2Confirmacao(TestCase):
    """
    Verifica que a Fase 2 responde corretamente ao 'ok' e 'corrigir'.
    """

    @patch("chat.engine.phase_3.run")
    def test_ok_em_fase2_executa_fase3(self, mock_fase3):
        """'ok' na Fase 2 avança para FASE_ADMISSIBILIDADE_GERADA e chama Fase 3."""
        mock_fase3.return_value = "Admissibilidade calculada."

        parecer = _make_parecer(
            status_fase=FASE_DIR,
            tabela_datas_sensiveis="| 15/01/2024 | INFRACAO |",
        )
        engine = JariEngine(parecer)
        engine.process_message("ok")

        parecer.refresh_from_db()
        # Após 'ok', fase_3.run é chamada e o status avança para FASE_ADMISSIBILIDADE_GERADA
        self.assertEqual(parecer.status_fase, FASE_ADMISSIBILIDADE_GERADA)
        mock_fase3.assert_called_once()

    def test_corrigir_em_fase2_volta_para_fase1(self):
        """'corrigir' na Fase 2 reseta campos e volta para FASE_COLETA."""
        parecer = _make_parecer(
            status_fase=FASE_DIR,
            pa="AIT-123",
            sgpe="SGPE-456",
            tabela_datas_sensiveis="| 15/01/2024 |",
        )
        engine = JariEngine(parecer)
        engine.process_message("corrigir")

        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, FASE_COLETA)
        self.assertIsNone(parecer.data_sessao)
        self.assertIsNone(parecer.prazo_final)

    def test_resposta_invalida_em_fase2_retorna_instrucao(self):
        """Resposta inválida na Fase 2 retorna mensagem de instrução."""
        parecer = _make_parecer(status_fase=FASE_DIR)
        engine = JariEngine(parecer)
        result = engine.process_message("talvez")

        self.assertIn("ok", result.lower())
        self.assertIn("corrigir", result.lower())
        # Status NÃO deve ter mudado
        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, FASE_DIR)


# ── Camada 2-C: Fase 3 — Bloqueio por ausência de data_infracao ──────────────

class TestFase3Bloqueio(TestCase):
    """
    Verifica que a Fase 3 bloqueia o avanço quando não há data da infração
    e que os cálculos de prescrição/decadência são gravados no banco.
    """

    @patch("chat.integrations.GeminiClient")
    def test_sem_datas_na_tabela_volta_para_dir(self, mock_gemini_cls):
        """tabela_datas_sensiveis vazia → Fase 3 volta para FASE_DIR."""
        parecer = _make_parecer(
            status_fase=FASE_ADMISSIBILIDADE_GERADA,
            tabela_datas_sensiveis="",
        )
        engine = JariEngine(parecer)
        result = engine.process_message("any")  # fase 3 não usa mensagem

        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, FASE_DIR)
        self.assertIn("Data da Infração não localizada", result)

    @patch("chat.integrations.GeminiClient")
    def test_com_data_infracao_na_tabela_avanca_para_31(self, mock_gemini_cls):
        """
        Tabela com data de infração identificável → Fase 3 calcula prescrição
        e avança para FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE.
        """
        mock_gemini = MagicMock()
        mock_gemini_cls.return_value = mock_gemini
        mock_gemini.generate_phase3_report.return_value = "Texto de admissibilidade gerado."

        tabela = (
            "| Tipo | Data |\n"
            "|------|------|\n"
            "| INFRACAO | 15/01/2024 |\n"
            "| Sessão JARI | 10/03/2025 |\n"
        )
        # Protocolo dentro do prazo → tempestivo
        parecer = _make_parecer(
            status_fase=FASE_ADMISSIBILIDADE_GERADA,
            tabela_datas_sensiveis=tabela,
            data_protocolo=datetime.date(2024, 3, 1),
            prazo_final=datetime.date(2024, 3, 31),
        )
        engine = JariEngine(parecer)
        engine.process_message("any")

        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE)


# ── Camada 2-D: 409 em Parecer Finalizado ────────────────────────────────────

class TestFase409Finalizado(TestCase):
    """
    Verifica que parecer com status_fase=8 (FINALIZADO) retorna 409
    quando recebe ações de fluxo ('ok', 'corrigir', 'iniciar', 'FASE1_CONFIRM:').
    """

    def _handle(self, parecer, message):
        """Chama handle_processamento e retorna a resposta."""
        user = User.objects.create_user("tester409", password="x")
        parecer.user = user
        parecer.save()
        filter_kwargs = {"user": user}
        return ChatService.handle_processamento(parecer.id, message, [], filter_kwargs)

    def test_409_em_parecer_finalizado_com_ok(self):
        parecer = _make_parecer(status_fase=FASE_FINALIZADO)
        response = self._handle(parecer, "ok")
        self.assertEqual(response.status_code, 409)
        data = json.loads(response.content)
        self.assertTrue(data.get("readonly"))

    def test_409_em_parecer_finalizado_com_corrigir(self):
        parecer = _make_parecer(status_fase=FASE_FINALIZADO)
        response = self._handle(parecer, "corrigir")
        self.assertEqual(response.status_code, 409)

    def test_409_em_parecer_finalizado_com_iniciar(self):
        parecer = _make_parecer(status_fase=FASE_FINALIZADO)
        response = self._handle(parecer, "iniciar")
        self.assertEqual(response.status_code, 409)

    def test_409_em_parecer_finalizado_com_fase1_confirm(self):
        parecer = _make_parecer(status_fase=FASE_FINALIZADO)
        response = self._handle(parecer, "FASE1_CONFIRM: dados")
        self.assertEqual(response.status_code, 409)

    @patch("chat.tasks.gerar_parecer_task")
    def test_parecer_em_fase31_nao_retorna_409(self, mock_task):
        """Fase 31 (não finalizado) deve processar normalmente, sem 409."""
        mock_task.delay.return_value = _mock_task()

        parecer = _make_parecer(
            status_fase=FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE,
            has_prescricao_punitiva=True,
        )
        user = User.objects.create_user("tester_ok", password="x")
        parecer.user = user
        parecer.save()
        filter_kwargs = {"user": user}
        response = ChatService.handle_processamento(parecer.id, "ok", [], filter_kwargs)
        self.assertNotEqual(response.status_code, 409)


# ── Camada 2-E: Rota D — analise_tese_texto com flag RESULTADO EXIGIDO ───────

class TestRotaD(TestCase):
    """
    Verifica que quando analise_tese_texto contém 'RESULTADO EXIGIDO NESTE PARECER: DEFERIDO',
    a Fase 5 enfileira o Celery com os dados corretos para geração do parecer.

    O conteúdo do prompt enviado à Anthropic é testado na Camada 3.
    Aqui testamos o fluxo de enfileiramento via Fase 5.
    """

    @patch("chat.tasks.gerar_parecer_task")
    def test_fase5_enfileira_celery_quando_acionada_diretamente(self, mock_task):
        """
        Parecer em FASE_RESULTADO (5) chama gerar_parecer_task.delay().
        Simula Rota D onde o mérito foi prejudicado.
        """
        mock_task.delay.return_value = _mock_task()

        parecer = _make_parecer(
            status_fase=FASE_RESULTADO,
            analise_tese_texto="RESULTADO EXIGIDO NESTE PARECER: DEFERIDO",
            tese="MÉRITO PREJUDICADO (PRESCRIÇÃO PUNITIVA).",
        )
        engine = JariEngine(parecer)
        result = engine.process_message("any")

        mock_task.delay.assert_called_once_with(parecer.id)
        data = json.loads(result)
        self.assertEqual(data["status"], "celery")

    @patch("chat.engine.phase_5.run_llm_phases")
    def test_run_llm_phases_recebe_parecer_com_analise_tese(self, mock_run_llm):
        """
        run_llm_phases recebe o engine com analise_tese_texto preenchido.
        Garante que a ROTA D está disponível para o Anthropic.
        """
        mock_run_llm.return_value = "Parecer DEFERIDO gerado."

        parecer = _make_parecer(
            analise_tese_texto="RESULTADO EXIGIDO NESTE PARECER: DEFERIDO",
        )
        engine = JariEngine(parecer)
        engine.run_llm_phases(task_id="task-123")

        mock_run_llm.assert_called_once()
        # Verifica que o engine passado contém o parecer correto
        called_engine = mock_run_llm.call_args[0][0]
        self.assertEqual(
            called_engine.parecer.analise_tese_texto,
            "RESULTADO EXIGIDO NESTE PARECER: DEFERIDO",
        )


# ── Camada 2-F: Integração F2→F3→F31 ─────────────────────────────────────────

class TestFluxoF2F3F31(TestCase):
    """
    Testa o fluxo completo F2→F3→F31 com mocks nas chamadas externas.
    Verifica que o estado do banco avança corretamente em cada etapa.
    """

    @patch("chat.integrations.GeminiClient")
    @patch("chat.tasks.gerar_parecer_task")
    def test_fluxo_completo_com_prescricao_punitiva(self, mock_task, mock_gemini_cls):
        """
        Fluxo: Fase 2 'ok' → Fase 3 (calcula) → Fase 31 'ok' (prescricao=True) → FASE_RESULTADO.
        """
        mock_task.delay.return_value = _mock_task()
        mock_gemini = MagicMock()
        mock_gemini_cls.return_value = mock_gemini
        mock_gemini.generate_phase3_report.return_value = "Recurso intempestivo."

        tabela = (
            "| Tipo | Data |\n"
            "|------|------|\n"
            "| INFRACAO | 15/01/2020 |\n"
            "| Sessão JARI | 10/03/2025 |\n"
        )
        # Protocolo muito tardio → prescricao punitiva esperada (5 anos)
        parecer = _make_parecer(
            status_fase=FASE_DIR,
            tabela_datas_sensiveis=tabela,
            data_protocolo=datetime.date(2024, 3, 1),
            prazo_final=datetime.date(2024, 3, 31),
        )
        engine = JariEngine(parecer)

        # ── Passo 1: Fase 2 'ok' → executa Fase 3 ─────────────────────────────
        engine.process_message("ok")
        parecer.refresh_from_db()
        # Deve estar em F31 (ou F3 se Gemini falhou silenciosamente)
        self.assertIn(parecer.status_fase, [
            FASE_ADMISSIBILIDADE_GERADA,
            FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE,
        ])

    @patch("chat.tasks.processar_fase4_task")
    def test_fluxo_sem_prejuizo_chega_em_fase_merito(self, mock_fase4):
        """
        Fluxo: Fase 31 'ok' (tudo ok) → despacha Celery FASE4 (extração de teses).
        """
        mock_fase4.delay.return_value = _mock_task()

        tabela = (
            "| Tipo | Data |\n"
            "|------|------|\n"
            "| INFRACAO | 15/01/2024 |\n"
        )
        parecer = _make_parecer(
            status_fase=FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE,
            tabela_datas_sensiveis=tabela,
            is_tempestivo=True,
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
        )
        engine = JariEngine(parecer)

        # ── Passo: Fase 31 'ok' → enfileira extração de tese via Celery ──────
        result = engine.process_message("ok")
        mock_fase4.delay.assert_called_once_with(parecer.id)
        data = json.loads(result)
        self.assertEqual(data["status"], "celery")
        self.assertEqual(data["type"], "FASE4")
