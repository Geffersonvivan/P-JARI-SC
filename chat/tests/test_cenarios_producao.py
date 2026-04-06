"""
Camada 2.5 — Cenários de Produção (Carga de Julgamentos)

Simula 12 tipos reais de julgamento JARI, cobrindo todos os ramos de decisão
do motor. Cada cenário representa uma situação que chega na JARI todo dia.

CENÁRIOS:
  C01 — Prescrição Punitiva (multa, > 5 anos)
  C02 — Recurso Limpo (tempestivo, sem vícios → Mérito)
  C03 — Intempestividade (protocolo tardio)
  C04 — Prescrição Intercorrente (> 3 anos no processo)
  C05 — Decadência Suspensão Filtro 2 (julgador força SIM via M1-FIX)
  C06 — Blindagem Filtro 1 (tenta inverter decadência pré-2021, bloqueado)
  C07 — Inversão de Tempestividade pelo Julgador (A→B)
  C08 — Suspensão por Acúmulo de Pontos (marco = dia após totalização)
  C09 — Múltiplos Prejudicantes (Prescrição + Intempestividade)
  C10 — Pipeline Completo: Prescrição → DEFERIDO → Auditoria Perfeita (score=100)
  C11 — Pipeline Completo: Rota D (tese acolhida) → DEFERIDO → Auditoria (score=100)
  C12 — Pipeline Completo: IA retorna resultado errado → Blindagem detecta bug (score≤50)

Executar:
    python manage.py test chat.tests.test_cenarios_producao --keepdb -v 2
"""
import datetime
import json
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth.models import User

from chat.models import Parecer
from chat.engine import (
    JariEngine,
    FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE,
    FASE_MERITO,
    FASE_RESULTADO,
    FASE_AUDITORIA,
    FASE_SELECAO_PASTA,
)


# ── Constantes de cenário ─────────────────────────────────────────────────────

_PA  = "AIT-2024/001234"
_SGPE = "SGPE-2024/005678"

_LIMIAR_F1 = datetime.date(2021, 4, 12)   # Filtro 1: infração antes = decadência proibida
_LIMIAR_F2 = datetime.date(2021, 10, 22)  # Filtro 2: entre F1 e F2


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_cenario(**kwargs) -> Parecer:
    """
    Cria um Parecer pré-configurado em FASE_31 para os testes de F31.
    Todos os campos 'calculados' (is_tempestivo, has_*) vêm como kwargs.
    """
    defaults = dict(
        nome_processo="Processo Teste",
        pa=_PA,
        sgpe=_SGPE,
        recorrente="FULANO DE TAL",
        status_fase=FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE,
        is_saved=False,
        # Flags calculadas pela Fase 3 (JariMath) — padrão: recurso limpo
        is_tempestivo=True,
        has_prescricao_punitiva=False,
        has_prescricao_intercorrente=False,
        has_decadencia=False,
        # Datas padrão: infração recente, protocolo dentro do prazo
        data_infracao=datetime.date(2023, 1, 15),
        data_sessao=datetime.date(2025, 3, 10),
        data_protocolo=datetime.date(2023, 3, 1),
        prazo_final=datetime.date(2023, 3, 31),
        tipo_penalidade="multa",
        admissibilidade_texto=(
            "**TEMPESTIVIDADE:** Recurso TEMPESTIVO — protocolo dentro do prazo.\n"
            "**PRESCRIÇÃO PUNITIVA:** NÃO — intervalo inferior a 5 anos.\n"
            "**PRESCRIÇÃO INTERCORRENTE:** NÃO — menos de 3 anos em trâmite.\n"
            "**DECADÊNCIA:** NÃO — dentro dos marcos temporais aplicáveis."
        ),
    )
    defaults.update(kwargs)
    return Parecer.objects.create(**defaults)


def _texto_deferido(pa=_PA, sgpe=_SGPE) -> str:
    """Texto realista de parecer DEFERIDO (>200 chars, contém PA e SGPE)."""
    return (
        f"RELATÓRIO\n\n"
        f"Trata-se de recurso administrativo autuado sob o número {pa}, "
        f"devidamente registrado no sistema SGPE sob o código {sgpe}. "
        f"O recorrente interpõe recurso tempestivo em face de autuação de trânsito, "
        f"alegando vícios no processo administrativo e extinção da pretensão punitiva.\n\n"
        f"ADMISSIBILIDADE\n\n"
        f"O recurso preenche todos os requisitos formais de admissibilidade.\n\n"
        f"TESES DEFENSIVAS\n\n"
        f"Restou configurada a extinção da pretensão punitiva do Estado em razão da "
        f"prescrição quinquenal, tornando o mérito prejudicado.\n\n"
        f"DISPOSITIVO\n\n"
        f"Ante o exposto, VOTO pelo DEFERIDO do presente recurso, com fundamento no "
        f"artigo 281 do Código de Trânsito Brasileiro."
    )


def _texto_indeferido(pa=_PA, sgpe=_SGPE) -> str:
    """Texto realista de parecer INDEFERIDO (>200 chars, contém PA e SGPE)."""
    return (
        f"RELATÓRIO\n\n"
        f"Trata-se de recurso administrativo autuado sob o número {pa}, "
        f"registrado no sistema SGPE sob o código {sgpe}. "
        f"O recorrente interpõe recurso em face de autuação de trânsito, "
        f"tendo sido constatada a intempestividade do recurso interposto.\n\n"
        f"ADMISSIBILIDADE\n\n"
        f"O recurso foi interposto fora do prazo legal de 30 dias, configurando "
        f"INTEMPESTIVIDADE. A documentação apresentada não comprova justa causa.\n\n"
        f"TESES DEFENSIVAS\n\n"
        f"Em razão da intempestividade, as teses de mérito restam prejudicadas "
        f"e não serão apreciadas neste julgamento administrativo.\n\n"
        f"DISPOSITIVO\n\n"
        f"Ante o exposto, VOTO pelo INDEFERIDO do presente recurso por intempestividade, "
        f"mantendo-se a penalidade nos exatos termos da autuação original."
    )


def _mock_apis_fase5(
    texto_parecer: str,
    mock_anth_cls: MagicMock,
    mock_vertex_cls: MagicMock,
    mock_perp_cls: MagicMock,
    mock_gemini_cls: MagicMock,
):
    """Configura todos os mocks necessários para phase_5.run_llm_phases."""
    mock_anth_cls.return_value.validate_and_generate_parecer.return_value = texto_parecer
    mock_vertex_cls.return_value.search_documents.return_value = "Documentação jurídica aplicável ao CTB."
    mock_perp_cls.return_value.search_tese.return_value = "Jurisprudência: STJ REsp 1.123.456."
    mock_gemini_cls.return_value.audit_parecer.return_value = json.dumps({
        "score": 10, "itens": ["Estrutura completa", "Dispositivo presente"]
    })


# ── Classe principal: Cenários F31 (C01–C09) ─────────────────────────────────

class TestCenariosF31(TestCase):
    """
    Cenários C01-C09: Verifica o roteamento correto da Fase 31 para os
    diferentes tipos de julgamento que chegam na JARI diariamente.
    """

    # ── C01 ──────────────────────────────────────────────────────────────────

    @patch("chat.tasks.gerar_parecer_task")
    def test_c01_prescricao_punitiva_multa(self, mock_task):
        """
        C01 — Multa com > 5 anos: prescrição punitiva configurada.
        Julgador confirma 'ok' → F5 via Celery (DEFERIDO obrigatório).
        """
        mock_task.delay.return_value = MagicMock(id="celery-c01")

        parecer = _make_cenario(
            nome_processo="C01 — Prescrição Punitiva Multa",
            data_infracao=datetime.date(2016, 3, 15),  # 9 anos atrás
            data_sessao=datetime.date(2025, 3, 10),
            has_prescricao_punitiva=True,
            admissibilidade_texto=(
                "**PRESCRIÇÃO PUNITIVA:** SIM — 9 anos transcorridos (limite: 5 anos).\n"
                "**TEMPESTIVIDADE:** TEMPESTIVO.\n"
                "**PRESCRIÇÃO INTERCORRENTE:** NÃO.\n"
                "**DECADÊNCIA:** NÃO SE APLICA (Filtro 1, infração anterior a 12/04/2021)."
            ),
        )
        engine = JariEngine(parecer)
        result = engine.process_message("ok")

        mock_task.delay.assert_called_once_with(parecer.id)
        parecer.refresh_from_db()

        self.assertEqual(parecer.status_fase, FASE_RESULTADO)
        self.assertTrue(parecer.julgador_prescricao_punitiva)
        self.assertIn("PRESCRIÇÃO PUNITIVA", parecer.tese)

        data = json.loads(result)
        self.assertEqual(data["type"], "PREJUDICIALIDADE")
        print(f"\n  ✅ C01 — {parecer.tese}")

    # ── C02 ──────────────────────────────────────────────────────────────────

    @patch("chat.tasks.processar_fase4_task")
    def test_c02_recurso_limpo_vai_para_merito(self, mock_fase4):
        """
        C02 — Recurso sem nenhum vício: tempestivo, sem prescrição, sem decadência.
        Julgador confirma 'ok' → despacha Celery FASE4 (extração de teses).
        """
        mock_fase4.delay.return_value = MagicMock(id="celery-c02")

        parecer = _make_cenario(
            nome_processo="C02 — Recurso Limpo",
            is_tempestivo=True,
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
        )
        engine = JariEngine(parecer)
        result = engine.process_message("ok")

        mock_fase4.delay.assert_called_once_with(parecer.id)
        data = json.loads(result)
        self.assertEqual(data["type"], "FASE4")

        parecer.refresh_from_db()
        self.assertTrue(parecer.julgador_tempestivo)
        self.assertFalse(parecer.julgador_prescricao_punitiva)
        self.assertFalse(parecer.julgador_prescricao_intercorrente)
        self.assertFalse(parecer.julgador_decadencia)
        print(f"\n  ✅ C02 — Celery FASE4 enfileirado. julgador_tempestivo={parecer.julgador_tempestivo}")

    # ── C03 ──────────────────────────────────────────────────────────────────

    @patch("chat.tasks.gerar_parecer_task")
    def test_c03_intempestividade_protocolo_tardio(self, mock_task):
        """
        C03 — Protocolo entregue após o prazo: recurso INTEMPESTIVO.
        Julgador confirma 'ok' → F5 com tese INTEMPESTIVIDADE (INDEFERIDO obrigatório).
        """
        mock_task.delay.return_value = MagicMock(id="celery-c03")

        parecer = _make_cenario(
            nome_processo="C03 — Intempestividade",
            data_protocolo=datetime.date(2023, 5, 15),  # 45 dias após o prazo
            prazo_final=datetime.date(2023, 3, 31),
            is_tempestivo=False,
            admissibilidade_texto=(
                "**TEMPESTIVIDADE:** INTEMPESTIVO — protocolo em 15/05/2023, "
                "prazo encerrou em 31/03/2023 (45 dias de atraso).\n"
                "**PRESCRIÇÃO PUNITIVA:** NÃO.\n"
                "**PRESCRIÇÃO INTERCORRENTE:** NÃO.\n"
                "**DECADÊNCIA:** NÃO."
            ),
        )
        engine = JariEngine(parecer)
        result = engine.process_message("ok")

        mock_task.delay.assert_called_once_with(parecer.id)
        parecer.refresh_from_db()

        self.assertEqual(parecer.status_fase, FASE_RESULTADO)
        self.assertFalse(parecer.julgador_tempestivo)
        self.assertIn("INTEMPESTIVIDADE", parecer.tese)
        print(f"\n  ✅ C03 — {parecer.tese}")

    # ── C04 ──────────────────────────────────────────────────────────────────

    @patch("chat.tasks.gerar_parecer_task")
    def test_c04_prescricao_intercorrente(self, mock_task):
        """
        C04 — Processo parado por > 3 anos: prescrição intercorrente configurada.
        'ok' → F5 (DEFERIDO obrigatório).
        """
        mock_task.delay.return_value = MagicMock(id="celery-c04")

        parecer = _make_cenario(
            nome_processo="C04 — Prescrição Intercorrente",
            data_protocolo=datetime.date(2021, 1, 10),  # protocolou em 2021
            data_sessao=datetime.date(2025, 3, 10),     # julgado em 2025 → > 3 anos
            has_prescricao_intercorrente=True,
            admissibilidade_texto=(
                "**TEMPESTIVIDADE:** TEMPESTIVO.\n"
                "**PRESCRIÇÃO PUNITIVA:** NÃO.\n"
                "**PRESCRIÇÃO INTERCORRENTE:** SIM — 4 anos, 2 meses desde o protocolo.\n"
                "**DECADÊNCIA:** NÃO."
            ),
        )
        engine = JariEngine(parecer)
        engine.process_message("ok")

        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, FASE_RESULTADO)
        self.assertTrue(parecer.julgador_prescricao_intercorrente)
        self.assertIn("PRESCRIÇÃO INTERCORRENTE", parecer.tese)
        print(f"\n  ✅ C04 — {parecer.tese}")

    # ── C05 ──────────────────────────────────────────────────────────────────

    @patch("chat.tasks.gerar_parecer_task")
    def test_c05_decadencia_suspensao_filtro2_forcada(self, mock_task):
        """
        C05 — Suspensão no período Filtro 2 (12/04/2021–21/10/2021).
        Automático: NÃO SE APLICA (has_decadencia=False).
        Julgador escolhe 'Decadência - B' → M1-FIX converte NÃO SE APLICA→SIM.
        Resultado: FASE_RESULTADO com DECADÊNCIA.
        """
        mock_task.delay.return_value = MagicMock(id="celery-c05")

        parecer = _make_cenario(
            nome_processo="C05 — Decadência Suspensão Filtro 2",
            data_infracao=datetime.date(2021, 6, 15),   # entre 12/04/2021 e 21/10/2021 = Filtro 2
            tipo_penalidade="suspensao",
            has_decadencia=False,                        # automático: NÃO SE APLICA
            admissibilidade_texto=(
                "**TEMPESTIVIDADE:** TEMPESTIVO.\n"
                "**PRESCRIÇÃO PUNITIVA:** NÃO.\n"
                "**PRESCRIÇÃO INTERCORRENTE:** NÃO.\n"
                "**DECADÊNCIA:** NÃO SE APLICA — penalidade de suspensão, período Filtro 2."
            ),
        )
        engine = JariEngine(parecer)
        engine.process_message("Decadência - B")

        parecer.refresh_from_db()
        # M1-FIX deve ter convertido NÃO SE APLICA → SIM
        self.assertTrue(parecer.julgador_decadencia)
        self.assertEqual(parecer.status_fase, FASE_RESULTADO)
        self.assertIn("DECADÊNCIA", parecer.tese)
        print(f"\n  ✅ C05 — {parecer.tese} (M1-FIX ativado)")

    # ── C06 ──────────────────────────────────────────────────────────────────

    @patch("chat.tasks.processar_fase4_task")
    def test_c06_blindagem_filtro1_bloqueia_decadencia(self, mock_fase4):
        """
        C06 — Infração em 2020 (Filtro 1, < 12/04/2021).
        Julgador tenta 'Decadência - B' para forçar decadência.
        Blindagem Filtro 1 BLOQUEIA a inversão → julgador_decadencia permanece False.
        Sem outros prejudicantes → despacha Celery FASE4.
        """
        mock_fase4.delay.return_value = MagicMock(id="celery-c06")

        parecer = _make_cenario(
            nome_processo="C06 — Blindagem Filtro 1",
            data_infracao=datetime.date(2020, 6, 1),    # Filtro 1: anterior a 12/04/2021
            has_decadencia=False,
            is_tempestivo=True,
            has_prescricao_punitiva=False,
            admissibilidade_texto=(
                "**TEMPESTIVIDADE:** TEMPESTIVO.\n"
                "**PRESCRIÇÃO PUNITIVA:** NÃO.\n"
                "**PRESCRIÇÃO INTERCORRENTE:** NÃO.\n"
                "**DECADÊNCIA:** NÃO SE APLICA — FILTRO 1 (infração anterior a 12/04/2021)."
            ),
        )
        engine = JariEngine(parecer)
        result = engine.process_message("Decadência - B")

        parecer.refresh_from_db()
        # Blindagem deve ter BLOQUEADO a inversão
        self.assertFalse(parecer.julgador_decadencia)
        # Sem outros prejudicantes → Celery FASE4 enfileirado
        mock_fase4.delay.assert_called_once_with(parecer.id)
        data = json.loads(result)
        self.assertEqual(data["type"], "FASE4")
        print(f"\n  ✅ C06 — Blindagem Filtro 1 ativa. julgador_decadencia=False → Celery FASE4")

    # ── C07 ──────────────────────────────────────────────────────────────────

    @patch("chat.tasks.gerar_parecer_task")
    def test_c07_inversao_tempestividade_julgador(self, mock_task):
        """
        C07 — Automático: TEMPESTIVO (is_tempestivo=True).
        Julgador discorda e escolhe 'Tempestividade - B' (inverte para INTEMPESTIVO).
        Resultado: julgador_tempestivo=False → FASE_RESULTADO + INTEMPESTIVIDADE.
        """
        mock_task.delay.return_value = MagicMock(id="celery-c07")

        parecer = _make_cenario(
            nome_processo="C07 — Inversão Tempestividade",
            is_tempestivo=True,   # JariMath diz TEMPESTIVO
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
        )
        engine = JariEngine(parecer)
        engine.process_message("Tempestividade - B")

        parecer.refresh_from_db()
        # B = Inverter → tempestivo True → False
        self.assertFalse(parecer.julgador_tempestivo)
        self.assertEqual(parecer.status_fase, FASE_RESULTADO)
        self.assertIn("INTEMPESTIVIDADE", parecer.tese)
        print(f"\n  ✅ C07 — Julgador inverteu tempestividade. {parecer.tese}")

    # ── C08 ──────────────────────────────────────────────────────────────────

    @patch("chat.tasks.gerar_parecer_task")
    def test_c08_suspensao_acumulo_pontos(self, mock_task):
        """
        C08 — Suspensão por acúmulo de pontos.
        Marco inicial da prescrição = dia seguinte à totalização de pontos.
        has_prescricao_punitiva=True (> 5 anos desde a totalização).
        Resultado: FASE_RESULTADO.
        """
        mock_task.delay.return_value = MagicMock(id="celery-c08")

        parecer = _make_cenario(
            nome_processo="C08 — Suspensão Acúmulo de Pontos",
            tipo_penalidade="suspensao",
            data_infracao=datetime.date(2018, 6, 1),
            data_totalizacao_pontos=datetime.date(2018, 6, 1),  # marco = dia seguinte
            has_prescricao_punitiva=True,  # > 5 anos desde totalização
            admissibilidade_texto=(
                "**TEMPESTIVIDADE:** TEMPESTIVO.\n"
                "**PRESCRIÇÃO PUNITIVA:** SIM — marco: dia seguinte à totalização "
                "(02/06/2018). Intervalo até sessão: 6 anos, 9 meses.\n"
                "**PRESCRIÇÃO INTERCORRENTE:** NÃO.\n"
                "**DECADÊNCIA:** NÃO."
            ),
        )
        engine = JariEngine(parecer)
        engine.process_message("ok")

        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, FASE_RESULTADO)
        self.assertTrue(parecer.julgador_prescricao_punitiva)
        self.assertIn("PRESCRIÇÃO PUNITIVA", parecer.tese)
        print(f"\n  ✅ C08 — {parecer.tese}")

    # ── C09 ──────────────────────────────────────────────────────────────────

    @patch("chat.tasks.gerar_parecer_task")
    def test_c09_multiplos_prejudicantes(self, mock_task):
        """
        C09 — Recurso com prescrição punitiva E intempestividade simultâneas.
        Ambos devem constar na tese gerada.
        Resultado: FASE_RESULTADO, tese com ambos os motivos.
        """
        mock_task.delay.return_value = MagicMock(id="celery-c09")

        parecer = _make_cenario(
            nome_processo="C09 — Múltiplos Prejudicantes",
            data_infracao=datetime.date(2015, 1, 1),
            data_protocolo=datetime.date(2023, 5, 1),  # tardio
            prazo_final=datetime.date(2023, 2, 28),    # prazo já encerrado
            is_tempestivo=False,
            has_prescricao_punitiva=True,
            admissibilidade_texto=(
                "**TEMPESTIVIDADE:** INTEMPESTIVO — 61 dias de atraso.\n"
                "**PRESCRIÇÃO PUNITIVA:** SIM — 10 anos transcorridos.\n"
                "**PRESCRIÇÃO INTERCORRENTE:** NÃO.\n"
                "**DECADÊNCIA:** NÃO SE APLICA (Filtro 1)."
            ),
        )
        engine = JariEngine(parecer)
        engine.process_message("ok")

        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, FASE_RESULTADO)
        self.assertIn("PRESCRIÇÃO PUNITIVA", parecer.tese)
        self.assertIn("INTEMPESTIVIDADE", parecer.tese)
        print(f"\n  ✅ C09 — {parecer.tese}")


# ── Classe: Pipeline Completo (C10–C12) ──────────────────────────────────────

class TestCenariosFullPipeline(TestCase):
    """
    Cenários C10-C12: Executam o pipeline completo F31→F5→F6,
    incluindo geração do parecer (Anthropic mockado) e auditoria de blindagem.
    """

    def _run_pipeline_f5_f6(
        self,
        parecer: Parecer,
        texto_parecer: str,
    ):
        """
        Roda as Fases 5 e 6 com todas as APIs externas mockadas.
        Retorna o parecer atualizado do banco.
        """
        engine = JariEngine(parecer)

        with patch("chat.integrations.AnthropicClient") as MockAnth, \
             patch("chat.integrations.VertexAIClient") as MockVertex, \
             patch("chat.integrations.PerplexityClient") as MockPerp, \
             patch("chat.integrations.GeminiClient") as MockGemini, \
             patch("django.core.mail.send_mail"):

            _mock_apis_fase5(texto_parecer, MockAnth, MockVertex, MockPerp, MockGemini)

            # ── Fase 5: geração do parecer ────────────────────────────────────
            engine.run_llm_phases(task_id="test-task")
            parecer.refresh_from_db()
            self.assertEqual(
                parecer.status_fase, FASE_AUDITORIA,
                f"Após F5, esperava FASE_AUDITORIA(6), got {parecer.status_fase}"
            )
            self.assertIn(
                _PA, parecer.parecer_final or "",
                "Parecer final não contém o número do PA"
            )

            # ── Fase 6: auditoria de blindagem ────────────────────────────────
            engine.process_message("ok")
            parecer.refresh_from_db()
            self.assertEqual(
                parecer.status_fase, FASE_SELECAO_PASTA,
                f"Após F6, esperava FASE_SELECAO_PASTA(7), got {parecer.status_fase}"
            )
            self.assertIsNotNone(
                parecer.blindagem_score,
                "blindagem_score não foi preenchido pela Fase 6"
            )
            self.assertIsNotNone(parecer.checklist_auditoria_json)

        return parecer

    # ── C10 ──────────────────────────────────────────────────────────────────

    def test_c10_pipeline_prescricao_deferido_auditoria_100(self):
        """
        C10 — Pipeline Completo: Prescrição Punitiva → DEFERIDO → Auditoria Perfeita.

        Fluxo:
          F31 (prescrição=True) → F5 (Anthropic gera DEFERIDO) → F6 (score=100)

        A Fase 6 valida:
          ✅ flag_punitiva=True → texto contém "DEFERIDO" → nenhum erro fatal
          ✅ PA e SGPE presentes no texto → sem penalidade de pontuação
          → blindagem_score = 100
        """
        parecer = _make_cenario(
            nome_processo="C10 — Pipeline Completo DEFERIDO",
            status_fase=FASE_RESULTADO,  # injeta pós-F31
            julgador_prescricao_punitiva=True,
            julgador_tempestivo=True,
            julgador_prescricao_intercorrente=False,
            julgador_decadencia=False,
            has_prescricao_punitiva=True,
            is_tempestivo=True,
            tese="MÉRITO PREJUDICADO (PRESCRIÇÃO PUNITIVA).",
            data_infracao=datetime.date(2016, 3, 15),
        )

        parecer = self._run_pipeline_f5_f6(parecer, _texto_deferido())

        self.assertEqual(parecer.blindagem_score, 100)
        self.assertIsNone(parecer.blindagem_detalhes)
        print(f"\n  ✅ C10 — Auditoria perfeita. score={parecer.blindagem_score}")

    # ── C11 ──────────────────────────────────────────────────────────────────

    def test_c11_pipeline_rota_d_tese_acolhida_deferido(self):
        """
        C11 — Pipeline Completo: Rota D (tese acolhida na F41) → DEFERIDO → Auditoria.

        Cenário: Recurso sem prescrição nem intempestividade. O julgador, na F41,
        acolhe a tese de nulidade. O sistema grava 'RESULTADO EXIGIDO: DEFERIDO'
        em analise_tese_texto. A Fase 6 detecta _rota_d=True e exige DEFERIDO.

        Fluxo:
          F5 (analise_tese_texto com Rota D) → F6 (score=100)
        """
        parecer = _make_cenario(
            nome_processo="C11 — Rota D Tese Acolhida",
            status_fase=FASE_RESULTADO,  # pós-F41
            julgador_prescricao_punitiva=False,
            julgador_tempestivo=True,
            julgador_prescricao_intercorrente=False,
            julgador_decadencia=False,
            has_prescricao_punitiva=False,
            is_tempestivo=True,
            tese="Nulidade da notificação de autuação por ausência de identificação do agente.",
            analise_tese_texto=(
                "ANÁLISE DAS TESES DEFENSIVAS\n\n"
                "A tese de nulidade da notificação encontra amparo jurisprudencial.\n\n"
                "--- DECISÕES ABSOLUTAS DO JULGADOR ---\n"
                "Escolhas informadas: acolhida\n"
                "RESULTADO EXIGIDO NESTE PARECER: DEFERIDO\n"
            ),
        )

        parecer = self._run_pipeline_f5_f6(parecer, _texto_deferido())

        # Fase 6 deve reconhecer Rota D e não acusar erro_fatal
        self.assertEqual(parecer.blindagem_score, 100)
        self.assertIsNone(parecer.blindagem_detalhes)
        print(f"\n  ✅ C11 — Rota D. score={parecer.blindagem_score}")

    # ── C12 ──────────────────────────────────────────────────────────────────

    def test_c12_pipeline_ia_retorna_resultado_errado(self):
        """
        C12 — Simulação de BUG: IA retorna INDEFERIDO quando deveria ser DEFERIDO.

        Cenário: Prescrição punitiva configurada → resultado obrigatório = DEFERIDO.
        A Anthropic (mockada com bug) retorna texto com 'INDEFERIDO'.
        A Fase 6 detecta a incompatibilidade e penaliza o score.

        Esperado:
          ✅ erro_fatal=True → blindagem_score ≤ 50
          ✅ blindagem_detalhes contém mensagem de erro
        """
        parecer = _make_cenario(
            nome_processo="C12 — IA com Resultado Errado",
            status_fase=FASE_RESULTADO,
            julgador_prescricao_punitiva=True,
            julgador_tempestivo=True,
            julgador_prescricao_intercorrente=False,
            julgador_decadencia=False,
            has_prescricao_punitiva=True,
            is_tempestivo=True,
            tese="MÉRITO PREJUDICADO (PRESCRIÇÃO PUNITIVA).",
            data_infracao=datetime.date(2016, 1, 1),
        )

        # IA retorna INDEFERIDO — resultado ERRADO para prescrição punitiva
        texto_bugado = _texto_indeferido()
        parecer = self._run_pipeline_f5_f6(parecer, texto_bugado)

        # Blindagem deve ter detectado o erro
        self.assertLessEqual(parecer.blindagem_score, 50)
        self.assertIsNotNone(parecer.blindagem_detalhes)
        self.assertIn("DEFERIDO", parecer.blindagem_detalhes)
        print(
            f"\n  ✅ C12 — Blindagem detectou bug da IA. "
            f"score={parecer.blindagem_score}, erro='{parecer.blindagem_detalhes[:60]}...'"
        )


# ── Classe: Relatório Final ───────────────────────────────────────────────────

class TestRelatorioFinal(TestCase):
    """Gera um sumário de cobertura dos cenários ao final da suite."""

    def test_zzz_sumario_cobertura(self):
        """Imprime o mapa de cobertura dos 12 cenários (sempre passa)."""
        print("\n")
        print("=" * 68)
        print("  RELATÓRIO DE COBERTURA — CENÁRIOS DE PRODUÇÃO P-JARI")
        print("=" * 68)
        linhas = [
            ("C01", "Prescrição Punitiva (multa, >5 anos)",        "F31→F5", "DEFERIDO"),
            ("C02", "Recurso Limpo (sem vícios)",                  "F31→F4", "—"),
            ("C03", "Intempestividade (protocolo tardio)",          "F31→F5", "INDEFERIDO"),
            ("C04", "Prescrição Intercorrente (>3 anos)",           "F31→F5", "DEFERIDO"),
            ("C05", "Decadência Suspensão F2 (M1-FIX)",            "F31→F5", "DEFERIDO"),
            ("C06", "Blindagem Filtro 1 (inversão bloqueada)",      "F31→F4", "—"),
            ("C07", "Inversão Tempestividade pelo Julgador",        "F31→F5", "INDEFERIDO"),
            ("C08", "Suspensão por Acúmulo de Pontos",              "F31→F5", "DEFERIDO"),
            ("C09", "Múltiplos Prejudicantes (Pres. + Intemp.)",   "F31→F5", "DEFERIDO"),
            ("C10", "Pipeline Completo: Prescrição → score=100",    "F5→F6",  "✅ 100"),
            ("C11", "Pipeline Completo: Rota D → score=100",        "F5→F6",  "✅ 100"),
            ("C12", "Pipeline Completo: IA bugada → score≤50",      "F5→F6",  "🚨 ≤50"),
        ]
        print(f"  {'#':<4} {'Cenário':<45} {'Fases':<8} {'Score/Result'}")
        print(f"  {'-'*4} {'-'*45} {'-'*8} {'-'*12}")
        for cod, desc, fases, resultado in linhas:
            print(f"  {cod:<4} {desc:<45} {fases:<8} {resultado}")
        print("=" * 68)
        self.assertTrue(True)  # sempre passa — apenas relatório
