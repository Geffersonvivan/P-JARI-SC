"""
Testes de integração das fases do JariEngine.

Ao contrário dos testes unitários (tests_jari_engine.py), aqui o Parecer é
salvo em banco real (SQLite de teste) e as transições são validadas via
refresh_from_db() — capturando bugs de save() incorreto entre fases.

Mocking: apenas chamadas externas (GeminiClient, PDFExtractor.extract_dates_from_pdf).
JariMath roda de verdade — sem mock.

Executar:
    pytest chat/tests_integration.py -v
    ou
    python manage.py test chat.tests_integration
"""
import datetime
import json
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth.models import User


# ── Dados de teste fixos ──────────────────────────────────────────────────────

# Tabela mínima compatível com o parser de phase_3.py:
#   INFRACAO encontrada pelo _data_por_label via regex '\bINFRACAO\b'
#   NA       encontrada via '\bNA\b' — torna-se marco interruptivo semântico
#
# Datas escolhidas para que o cenário base NÃO gere nenhuma prejudicialidade:
#   infração 15/01/2025 → sessão 01/06/2025 = 137 dias (< 180 e < 360) → sem decadência
#   NA 20/02/2025 → 36 dias após infração (< 180) → sem decadência por notificação
#   Marco punitiva: NA = 2025-02-20, aniversário 5a = 2030-02-20 > sessão → sem prescrição
#   Intercorrente: protocolo 2025-01-10, aniversário 3a = 2028-01-10 > sessão → sem prescrição
_TABELA_F2_NORMAL = (
    "| Tipo | Data | Descritivo | Origem | Observações |\n"
    "| --- | --- | --- | --- | --- |\n"
    "| INFRACAO | 15/01/2025 | Auto de infração | Autuação | |\n"
    "| NA | 20/02/2025 | Notificação de autuação | Autuação | |\n"
)

# Retorno JSON estruturado que o GeminiClient.generate_phase2_report devolveria
_RETORNO_GEMINI_F2 = {
    'recorrente': 'João da Silva',
    'tipo_penalidade': 'multa',
    'data_conclusao_multa': 'NAO_SE_APLICA',
    'tem_flagrante': 'NAO_DETERMINADO',
    'data_conhecimento_infracao': 'NAO_SE_APLICA',
    'data_totalizacao_pontos': 'NAO_SE_APLICA',
    'data_infracao_extraida': '15/01/2025',
    'data_notificacao_extraida': '20/02/2025',
    'tabela_markdown': _TABELA_F2_NORMAL,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_user(username='julgador_integ'):
    return User.objects.create_user(username=username, password='test123')


def _create_parecer(user, **kwargs):
    from chat.models import Parecer
    defaults = dict(
        user=user,
        nome_processo='Integração PA-001/2025',
        status_fase=2,
        pa='PA-001/2025',
        sgpe='00001',
        data_sessao=datetime.date(2025, 6, 1),
        data_protocolo=datetime.date(2025, 1, 10),
        prazo_final=datetime.date(2025, 1, 15),
    )
    defaults.update(kwargs)
    return Parecer.objects.create(**defaults)


# ── Testes de F2 (DIR) ────────────────────────────────────────────────────────

class TestFase2Integracao(TestCase):
    """
    Verifica que run_phase_2() persiste corretamente os campos estruturados
    retornados pelo Gemini no banco de dados.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = _create_user('f2_user')

    @patch('chat.integrations.GeminiClient')
    @patch('chat.pdf_extractor.PDFExtractor.extract_dates_from_pdf')
    def test_f2_salva_tabela_e_campos_estruturados(self, mock_pdf, MockGemini):
        """Campos recorrente, tipo_penalidade e tabela_datas_sensiveis são salvos no banco."""
        mock_pdf.return_value = ([], 0)
        MockGemini.return_value.generate_phase2_report.return_value = _RETORNO_GEMINI_F2

        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        parecer = _create_parecer(self.user)
        JariEngine(parecer).run_phase_2()

        parecer.refresh_from_db()
        self.assertEqual(parecer.recorrente, 'João da Silva')
        self.assertEqual(parecer.tipo_penalidade, 'multa')
        self.assertIn('INFRACAO', parecer.tabela_datas_sensiveis)
        self.assertIn('NA', parecer.tabela_datas_sensiveis)

    @patch('chat.integrations.GeminiClient')
    @patch('chat.pdf_extractor.PDFExtractor.extract_dates_from_pdf')
    def test_f2_aviso_pdf_critico_menos_500_chars(self, mock_pdf, MockGemini):
        """PDFs com < 500 chars devem gerar aviso crítico de OCR na tabela."""
        mock_pdf.return_value = ([], 100)   # 100 chars — crítico
        retorno = dict(_RETORNO_GEMINI_F2)
        retorno['tabela_markdown'] = '| INFRACAO | 15/01/2023 |'
        MockGemini.return_value.generate_phase2_report.return_value = retorno

        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        parecer = _create_parecer(self.user, autuacao_pdf_path='uploads/fake.pdf')
        JariEngine(parecer).run_phase_2()

        parecer.refresh_from_db()
        self.assertIn('OCR', parecer.tabela_datas_sensiveis.upper())

    @patch('chat.integrations.GeminiClient')
    @patch('chat.pdf_extractor.PDFExtractor.extract_dates_from_pdf')
    def test_f2_aviso_pdf_texto_limitado_500_a_2000_chars(self, mock_pdf, MockGemini):
        """PDFs com 500-2000 chars devem gerar aviso de texto limitado (ℹ️)."""
        mock_pdf.return_value = ([], 1200)  # 1200 chars — limitado
        retorno = dict(_RETORNO_GEMINI_F2)
        retorno['tabela_markdown'] = '| INFRACAO | 15/01/2023 |'
        MockGemini.return_value.generate_phase2_report.return_value = retorno

        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        parecer = _create_parecer(self.user, autuacao_pdf_path='uploads/fake.pdf')
        JariEngine(parecer).run_phase_2()

        parecer.refresh_from_db()
        self.assertIn('texto limitado', parecer.tabela_datas_sensiveis.lower())

    @patch('chat.integrations.GeminiClient')
    @patch('chat.pdf_extractor.PDFExtractor.extract_dates_from_pdf')
    def test_f2_sem_aviso_pdf_normal_acima_2000_chars(self, mock_pdf, MockGemini):
        """PDFs com > 2000 chars não devem gerar aviso de legibilidade."""
        mock_pdf.return_value = ([], 5000)  # 5000 chars — normal
        MockGemini.return_value.generate_phase2_report.return_value = _RETORNO_GEMINI_F2

        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        parecer = _create_parecer(self.user, autuacao_pdf_path='uploads/fake.pdf')
        JariEngine(parecer).run_phase_2()

        parecer.refresh_from_db()
        self.assertNotIn('OCR', parecer.tabela_datas_sensiveis.upper())
        self.assertNotIn('texto limitado', parecer.tabela_datas_sensiveis.lower())

    @patch('chat.integrations.GeminiClient')
    @patch('chat.pdf_extractor.PDFExtractor.extract_dates_from_pdf')
    def test_f2_inconsistencia_notificacao_antes_infracao(self, mock_pdf, MockGemini):
        """
        Se data_notificacao_extraida < data_infracao_extraida, deve aparecer
        aviso de INCONSISTÊNCIA na tabela antes de exibir ao julgador.
        """
        mock_pdf.return_value = ([], 0)
        retorno = dict(_RETORNO_GEMINI_F2)
        retorno['data_notificacao_extraida'] = '01/01/2025'   # ANTES da infração 15/01/2025
        MockGemini.return_value.generate_phase2_report.return_value = retorno

        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        parecer = _create_parecer(self.user)
        JariEngine(parecer).run_phase_2()

        parecer.refresh_from_db()
        self.assertIn('INCONSISTÊNCIA', parecer.tabela_datas_sensiveis.upper())


# ── Testes de F3 (JariMath) ───────────────────────────────────────────────────

class TestFase3Integracao(TestCase):
    """
    Verifica que os cálculos do JariMath são salvos corretamente no banco.

    Datas de referência do cenário padrão:
        data_infracao     = 15/01/2023
        data_na           = 20/02/2023  (36 dias → sem decadência)
        data_protocolo    = 10/01/2025
        prazo_final       = 15/01/2025  (protocolo <= prazo → tempestivo)
        data_sessao       = 01/06/2025  (~2.5 anos desde infração → sem prescrição)
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = _create_user('f3_user')

    @patch('chat.integrations.GeminiClient')
    def test_f3_flags_corretas_salvas_no_banco(self, MockGemini):
        """
        Cenário normal: tempestivo, sem prescrições, sem decadência.
        Verifica que os 4 campos booleanos são salvos com o valor certo.
        """
        MockGemini.return_value.generate_phase3_report.return_value = 'OK'

        from chat.models import Parecer
        from chat.engine.phase_3 import run
        from chat.jari_engine import JariEngine
        parecer = _create_parecer(
            self.user, status_fase=3, tabela_datas_sensiveis=_TABELA_F2_NORMAL,
        )
        run(JariEngine(parecer))

        parecer.refresh_from_db()
        self.assertTrue(parecer.is_tempestivo,
            "Protocolo 10/01/2025 ≤ prazo 15/01/2025 — deve ser TEMPESTIVO")
        self.assertFalse(parecer.has_prescricao_punitiva,
            "Último marco 20/02/2025 → sessão 01/06/2025 = ~3 meses < 5 anos — NÃO prescrito")
        self.assertFalse(parecer.has_prescricao_intercorrente,
            "Protocolo 10/01/2025 → sessão 01/06/2025 < 3 anos — NÃO prescrito")
        self.assertFalse(parecer.has_decadencia,
            "NA 20/02/2025, infração 15/01/2025 = 36 dias < 180 — SEM decadência")
        self.assertEqual(parecer.status_fase, 31)
        self.assertIsNotNone(parecer.data_infracao)
        self.assertEqual(parecer.data_infracao, datetime.date(2025, 1, 15))

    @patch('chat.integrations.GeminiClient')
    def test_f3_bloqueio_sem_data_infracao_retorna_para_fase2(self, MockGemini):
        """
        Quando tabela não contém INFRACAO, phase_3 deve retornar à FASE_DIR (2)
        e a mensagem de retorno deve mencionar 'Data da Infração'.
        """
        MockGemini.return_value.generate_phase3_report.return_value = 'N/A'

        from chat.models import Parecer
        from chat.engine.phase_3 import run
        from chat.jari_engine import JariEngine
        # Tabela sem NENHUMA data — garante que o fallback também fica vazio.
        # (Uma tabela com datas de F1 como PROTOCOLO ainda forneceria um fallback
        # via datas_processadas — por isso aqui só texto descritivo, sem datas.)
        tabela_sem_infracao = (
            "| Tipo | Descritivo |\n"
            "| --- | --- |\n"
            "| PROTOCOLO | Protocolo do recurso JARI |\n"
        )
        parecer = _create_parecer(
            self.user, status_fase=3, tabela_datas_sensiveis=tabela_sem_infracao,
        )
        resultado = run(JariEngine(parecer))

        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, 2,
            "Sem data_infracao → deve regredir para FASE_DIR (2)")
        self.assertIn('Data da Infração', resultado)

    @patch('chat.integrations.GeminiClient')
    def test_f3_prescricao_punitiva_configurada(self, MockGemini):
        """Infração muito antiga sem marcos → deve configurar prescrição punitiva."""
        MockGemini.return_value.generate_phase3_report.return_value = 'Prescrito'

        from chat.models import Parecer
        from chat.engine.phase_3 import run
        from chat.jari_engine import JariEngine

        tabela_antiga = (
            "| Tipo | Data | Descritivo | Origem | Observações |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| INFRACAO | 15/01/2019 | Auto de infração | Autuação | |\n"
        )
        # Sessão em 2025 → mais de 5 anos após 2019 → prescrito
        # Marco = data_infracao = 2019-01-15; aniversário 5a = 2024-01-15;
        # com COVID (2019-01-15 <= FIM_COVID): aniversário + 256 = 2024-09-28 < sessão 2025-06-01 → prescrito
        parecer = _create_parecer(
            self.user, status_fase=3,
            tabela_datas_sensiveis=tabela_antiga,
            data_sessao=datetime.date(2025, 6, 1),
            data_protocolo=datetime.date(2025, 1, 10),
            prazo_final=datetime.date(2025, 1, 15),
        )
        run(JariEngine(parecer))

        parecer.refresh_from_db()
        self.assertTrue(parecer.has_prescricao_punitiva,
            "Infração 15/01/2019 → sessão 01/06/2025 (com COVID) > 5 anos — PRESCRITO")

    @patch('chat.integrations.GeminiClient')
    def test_f3_decadencia_configurada_filtro3(self, MockGemini):
        """FILTRO 3: notificação com mais de 180 dias após infração → decadência."""
        MockGemini.return_value.generate_phase3_report.return_value = 'Decadência'

        from chat.models import Parecer
        from chat.engine.phase_3 import run
        from chat.jari_engine import JariEngine

        # Infração 01/01/2023, NA 10/08/2023 = 221 dias > 180 → decadência
        tabela_decadencia = (
            "| Tipo | Data | Descritivo | Origem | Observações |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| INFRACAO | 01/01/2023 | Auto | Autuação | |\n"
            "| NA | 10/08/2023 | Notificação | Autuação | |\n"
        )
        parecer = _create_parecer(
            self.user, status_fase=3,
            tabela_datas_sensiveis=tabela_decadencia,
            data_sessao=datetime.date(2025, 6, 1),
            data_protocolo=datetime.date(2025, 1, 10),
            prazo_final=datetime.date(2025, 1, 15),
        )
        run(JariEngine(parecer))

        parecer.refresh_from_db()
        self.assertTrue(parecer.has_decadencia,
            "NA em 221 dias > 180 (FILTRO 3) — deve declarar decadência")

    @patch('chat.integrations.GeminiClient')
    def test_f3_intempestividade_salva_corretamente(self, MockGemini):
        """Protocolo após prazo final → is_tempestivo=False salvo no banco."""
        MockGemini.return_value.generate_phase3_report.return_value = 'Intempestivo'

        from chat.models import Parecer
        from chat.engine.phase_3 import run
        from chat.jari_engine import JariEngine

        parecer = _create_parecer(
            self.user, status_fase=3,
            tabela_datas_sensiveis=_TABELA_F2_NORMAL,
            data_protocolo=datetime.date(2025, 1, 20),   # APÓS prazo
            prazo_final=datetime.date(2025, 1, 15),
        )
        run(JariEngine(parecer))

        parecer.refresh_from_db()
        self.assertFalse(parecer.is_tempestivo,
            "Protocolo 20/01/2025 > prazo 15/01/2025 — INTEMPESTIVO")


# ── Testes de F31 (confirmação admissibilidade) ────────────────────────────────

class TestFase31Integracao(TestCase):
    """
    Verifica que as escolhas A/B do julgador são persistidas no banco
    e que o roteamento (F4 ou F5) é feito corretamente.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = _create_user('f31_user')

    def _parecer_f31(self, **kwargs):
        defaults = dict(
            status_fase=31,
            is_tempestivo=True,
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
            admissibilidade_texto='Todos os prazos regulares.',
            data_infracao=datetime.date(2023, 1, 15),
        )
        defaults.update(kwargs)
        return _create_parecer(self.user, **defaults)

    def test_f31_sem_prejudicialidade_avanca_para_merito(self):
        """
        Julgador confirma 'ok' (aceita todos os resultados automáticos, todos False) → despacha FASE4.

        Semântica: 'ok' = _flag(None, automático) para cada item.
        Com flags automáticas = False/False/False/True(tempestivo), nenhum prejudica → Celery FASE4.
        """
        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        parecer = self._parecer_f31()
        engine = JariEngine(parecer)

        with patch('chat.tasks.processar_fase4_task') as mock_fase4:
            mock_fase4.delay.return_value = MagicMock(id='t-f4')
            result = engine.process_message("ok")

        mock_fase4.delay.assert_called_once_with(parecer.id)
        data = json.loads(result)
        self.assertEqual(data["type"], "FASE4")
        parecer.refresh_from_db()
        self.assertTrue(parecer.julgador_tempestivo)
        self.assertFalse(parecer.julgador_prescricao_punitiva)
        self.assertFalse(parecer.julgador_prescricao_intercorrente)
        self.assertFalse(parecer.julgador_decadencia)

    def test_f31_decadencia_acolhida_pula_para_resultado(self):
        """Julgador acolhe decadência → vai para F5 (PREJUDICIALIDADE) e tese registrada."""
        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        parecer = self._parecer_f31(
            has_decadencia=True,
            data_infracao=datetime.date(2022, 6, 1),  # após 12/04/2021 — blindagem não bloqueia
        )
        engine = JariEngine(parecer)

        with patch('chat.tasks.gerar_parecer_task') as mock_task:
            mock_task.delay.return_value = MagicMock(id='task-001')
            resultado = engine.process_message("DECADÊNCIA: A")

        resp = json.loads(resultado)
        self.assertEqual(resp['type'], 'PREJUDICIALIDADE')
        parecer.refresh_from_db()
        self.assertTrue(parecer.julgador_decadencia)
        self.assertIn('DECADÊNCIA', parecer.tese.upper())

    def test_f31_prescricao_punitiva_acolhida_pula_para_resultado(self):
        """Julgador acolhe prescrição punitiva → F5 com tese de prescrição."""
        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        parecer = self._parecer_f31(has_prescricao_punitiva=True)
        engine = JariEngine(parecer)

        with patch('chat.tasks.gerar_parecer_task') as mock_task:
            mock_task.delay.return_value = MagicMock(id='task-002')
            resultado = engine.process_message("PUNITIVA: A")

        resp = json.loads(resultado)
        self.assertEqual(resp['type'], 'PREJUDICIALIDADE')
        parecer.refresh_from_db()
        self.assertTrue(parecer.julgador_prescricao_punitiva)

    def test_f31_julgador_inverte_punitiva_e_vai_para_merito(self):
        """
        Julgador escolhe B para punitiva True → inverte para False → avança para F4.
        Semântica: A = condição existe; B = condição não existe.
        PUNITIVA: B = confirmo que não há prescrição punitiva → False → sem prejudicialidade.
        """
        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        parecer = self._parecer_f31(has_prescricao_punitiva=True)
        engine = JariEngine(parecer)

        with patch.object(engine, 'run_phase_4_extraction', return_value='f4'):
            engine.process_message(
                "TEMPESTIVIDADE: A; PUNITIVA: B; INTERCORRENTE: B; DECADÊNCIA: B"
            )

        parecer.refresh_from_db()
        self.assertFalse(parecer.julgador_prescricao_punitiva,
            "Julgador escolheu B (não acolhida) — deve salvar False")

    def test_f31_flags_julgador_persistidas_independentemente_das_automaticas(self):
        """
        Regressão crítica: save() do julgador não deve sobrescrever
        has_prescricao_punitiva com o valor julgador_prescricao_punitiva,
        nem vice-versa.
        """
        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        parecer = self._parecer_f31(
            has_prescricao_punitiva=True,    # automático = True
            has_prescricao_intercorrente=True,
        )
        engine = JariEngine(parecer)

        # Julgador inverte punitiva e intercorrente para B; decadência também B (tudo sem prejudicialidade)
        with patch('chat.tasks.processar_fase4_task') as mock_fase4:
            mock_fase4.delay.return_value = MagicMock(id='t-f4')
            engine.process_message(
                "TEMPESTIVIDADE: A; PUNITIVA: B; INTERCORRENTE: B; DECADÊNCIA: B"
            )

        parecer.refresh_from_db()
        # Flags automáticas permanecem inalteradas
        self.assertTrue(parecer.has_prescricao_punitiva,
            "Flag automática não deve ser sobrescrita pela decisão do julgador")
        self.assertTrue(parecer.has_prescricao_intercorrente,
            "Flag automática não deve ser sobrescrita pela decisão do julgador")
        # Flags do julgador refletem a inversão
        self.assertFalse(parecer.julgador_prescricao_punitiva)
        self.assertFalse(parecer.julgador_prescricao_intercorrente)


# ── Teste de fluxo encadeado F2 → F3 → F31 ────────────────────────────────────

class TestFluxoEncadeadoF2F3F31(TestCase):
    """
    Executa F2 → F3 → F31 em sequência recarregando o Parecer do banco a cada
    etapa. Garante que nenhum save() intermediário sobrescreve campo necessário
    à fase seguinte.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = _create_user('fluxo_user')

    @patch('chat.integrations.GeminiClient')
    @patch('chat.pdf_extractor.PDFExtractor.extract_dates_from_pdf')
    def test_cadeia_f2_f3_f31_merito(self, mock_pdf, MockGemini):
        """
        Fluxo completo sem prejudicialidade:
        F2 salva tabela → F3 calcula flags → F31 julgador confirma → F4 (mérito).
        """
        mock_pdf.return_value = ([], 0)
        MockGemini.return_value.generate_phase2_report.return_value = _RETORNO_GEMINI_F2
        MockGemini.return_value.generate_phase3_report.return_value = 'Admissibilidade OK.'

        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        from chat.engine.phase_3 import run as run_f3

        # Cria parecer no status inicial F2
        parecer = _create_parecer(self.user)

        # ── F2: run + confirmação do julgador ────────────────────────────────
        engine = JariEngine(parecer)
        engine.run_phase_2()
        parecer.refresh_from_db()
        # Após run_phase_2, fase ainda é 2 — aguarda 'ok' do julgador
        self.assertEqual(parecer.status_fase, 2)
        self.assertIn('INFRACAO', parecer.tabela_datas_sensiveis)

        # Julgador confirma F2 com 'ok' — agora despacha FASE3_ADM para Celery (não síncrono)
        # Mockamos a task Celery para controlar a fronteira
        with patch('chat.tasks.processar_fase3_admissibilidade_task') as mock_f3_task:
            mock_f3_task.delay.return_value = MagicMock(id='test-f3-task')
            engine.process_message('ok')
        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, 3)

        # ── F3: executa com JariMath real (simula o worker Celery rodando a task)
        # Recarrega engine do banco para simular nova requisição HTTP
        engine2 = JariEngine(Parecer.objects.get(pk=parecer.pk))
        run_f3(engine2)

        parecer.refresh_from_db()
        self.assertEqual(parecer.status_fase, 31)
        self.assertTrue(parecer.is_tempestivo)
        self.assertFalse(parecer.has_prescricao_punitiva)
        self.assertFalse(parecer.has_decadencia)
        self.assertIsNotNone(parecer.admissibilidade_texto)
        self.assertEqual(parecer.data_infracao, datetime.date(2025, 1, 15),
            "data_infracao deve ser persistida no banco para usar na blindagem F31")

        # ── F31: julgador confirma "ok" (aceita todos os automáticos = sem prejudicialidade) ──
        engine3 = JariEngine(Parecer.objects.get(pk=parecer.pk))
        with patch('chat.tasks.processar_fase4_task') as mock_fase4:
            mock_fase4.delay.return_value = MagicMock(id='t-f4')
            result = engine3.process_message("ok")

        mock_fase4.delay.assert_called_once_with(parecer.id)
        data = json.loads(result)
        self.assertEqual(data["type"], "FASE4")
        parecer.refresh_from_db()
        self.assertIsNotNone(parecer.julgador_tempestivo)
        self.assertIsNotNone(parecer.julgador_prescricao_punitiva)
        self.assertIsNotNone(parecer.julgador_prescricao_intercorrente)
        self.assertIsNotNone(parecer.julgador_decadencia)

    @patch('chat.integrations.GeminiClient')
    @patch('chat.pdf_extractor.PDFExtractor.extract_dates_from_pdf')
    def test_cadeia_f2_f3_f31_prejudicialidade_decadencia(self, mock_pdf, MockGemini):
        """
        Fluxo com decadência:
        F2 salva tabela com NA tardio → F3 calcula decadência=True → F31 → F5.
        """
        mock_pdf.return_value = ([], 0)
        # NA em 221 dias (01/01/2023 → 10/08/2023) → decadência FILTRO 3
        tabela_decadencia = (
            "| Tipo | Data | Descritivo | Origem | Observações |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| INFRACAO | 01/01/2023 | Auto | Autuação | |\n"
            "| NA | 10/08/2023 | Notificação | Autuação | |\n"
        )
        retorno_f2 = dict(_RETORNO_GEMINI_F2)
        retorno_f2['data_infracao_extraida'] = '01/01/2023'
        retorno_f2['data_notificacao_extraida'] = '10/08/2023'
        retorno_f2['tabela_markdown'] = tabela_decadencia
        MockGemini.return_value.generate_phase2_report.return_value = retorno_f2
        MockGemini.return_value.generate_phase3_report.return_value = 'Decadência configurada.'

        from chat.models import Parecer
        from chat.jari_engine import JariEngine
        from chat.engine.phase_3 import run as run_f3

        parecer = _create_parecer(self.user)

        # F2
        engine = JariEngine(parecer)
        engine.run_phase_2()
        with patch('chat.tasks.processar_fase3_admissibilidade_task') as mock_f3_task:
            mock_f3_task.delay.return_value = MagicMock(id='test-f3-task')
            engine.process_message('ok')

        # F3
        engine2 = JariEngine(Parecer.objects.get(pk=parecer.pk))
        run_f3(engine2)
        parecer.refresh_from_db()
        self.assertTrue(parecer.has_decadencia,
            "NA com 221 dias > 180 (FILTRO 3) — deve ser decadência=True")

        # F31: julgador acolhe decadência → F5
        engine3 = JariEngine(Parecer.objects.get(pk=parecer.pk))
        with patch('chat.tasks.gerar_parecer_task') as mock_task:
            mock_task.delay.return_value = MagicMock(id='task-decadencia')
            resultado = engine3.process_message("DECADÊNCIA: A")

        resp = json.loads(resultado)
        self.assertEqual(resp['type'], 'PREJUDICIALIDADE')
        parecer.refresh_from_db()
        self.assertTrue(parecer.julgador_decadencia)
        self.assertIn('DECADÊNCIA', parecer.tese.upper())
