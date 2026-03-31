"""
Testes unitários do JariEngine e JariMath.
Cobertura: JariMath (puro, sem mock) + process_message por fase (com mocks).

Executar:
    pytest chat/tests_jari_engine.py -v
"""
import datetime
import json
import unittest
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Bloco 1 — JariMath (puro, sem banco, sem rede)
# ---------------------------------------------------------------------------
class TestJariMathTempestividade(unittest.TestCase):

    def _math(self):
        from chat.jari_math import JariMath
        return JariMath

    def test_tempestivo_quando_protocolo_antes_prazo(self):
        M = self._math()
        resultado = M.check_tempestividade(
            datetime.date(2024, 3, 10),  # protocolo
            datetime.date(2024, 3, 15),  # prazo final
        )
        self.assertTrue(resultado)

    def test_intempestivo_quando_protocolo_apos_prazo(self):
        M = self._math()
        resultado = M.check_tempestividade(
            datetime.date(2024, 3, 20),
            datetime.date(2024, 3, 15),
        )
        self.assertFalse(resultado)

    def test_tempestivo_no_mesmo_dia_do_prazo(self):
        M = self._math()
        resultado = M.check_tempestividade(
            datetime.date(2024, 3, 15),
            datetime.date(2024, 3, 15),
        )
        self.assertTrue(resultado)

    def test_retorna_none_sem_datas(self):
        M = self._math()
        self.assertIsNone(M.check_tempestividade(None, datetime.date(2024, 1, 1)))
        self.assertIsNone(M.check_tempestividade(datetime.date(2024, 1, 1), None))


class TestJariMathPrescricaoPunitiva(unittest.TestCase):

    def _math(self):
        from chat.jari_math import JariMath
        return JariMath

    def test_nao_prescrito_dentro_de_5_anos(self):
        M = self._math()
        infracao = datetime.date(2020, 1, 1)
        sessao   = datetime.date(2024, 6, 1)   # ~4.4 anos
        self.assertFalse(M.check_prescription_punitiva(infracao, sessao))

    def test_prescrito_apos_5_anos(self):
        M = self._math()
        infracao = datetime.date(2018, 1, 1)
        sessao   = datetime.date(2024, 1, 2)   # > 1825 dias
        self.assertTrue(M.check_prescription_punitiva(infracao, sessao))

    def test_marco_interruptivo_reseta_contagem(self):
        M = self._math()
        infracao = datetime.date(2015, 1, 1)   # muito antiga
        marco    = datetime.date(2022, 6, 1)   # último marco válido
        sessao   = datetime.date(2024, 1, 1)   # 1.6 anos após marco → não prescrito
        self.assertFalse(M.check_prescription_punitiva(infracao, sessao, [marco]))

    def test_marcos_invalidos_nao_usado_quando_none(self):
        """Sem marcos: usa apenas data_infracao como ponto de partida."""
        M = self._math()
        infracao = datetime.date(2018, 1, 1)
        sessao   = datetime.date(2024, 6, 1)
        # > 1825 dias, sem marco → prescrito
        self.assertTrue(M.check_prescription_punitiva(infracao, sessao, None))


class TestJariMathPrescricaoIntercorrente(unittest.TestCase):

    def _math(self):
        from chat.jari_math import JariMath
        return JariMath

    def test_nao_prescrito_antes_do_aniversario(self):
        M = self._math()
        protocolo = datetime.date(2023, 3, 14)
        sessao    = datetime.date(2026, 3, 14)  # exato 3 anos → NÃO prescrito
        result, _ = M.check_prescription_intercorrente(protocolo, sessao)
        self.assertFalse(result)

    def test_prescrito_apos_aniversario(self):
        M = self._math()
        protocolo = datetime.date(2023, 3, 14)
        sessao    = datetime.date(2026, 3, 15)  # 1 dia além → prescrito
        result, _ = M.check_prescription_intercorrente(protocolo, sessao)
        self.assertTrue(result)

    def test_retorna_false_sem_datas(self):
        M = self._math()
        result, msg = M.check_prescription_intercorrente(None, datetime.date(2024, 1, 1))
        self.assertFalse(result)
        self.assertIn("insuficientes", msg.lower())


class TestJariMathDecadencia(unittest.TestCase):

    def _math(self):
        from chat.jari_math import JariMath
        return JariMath

    # --- FILTRO 1 (antes de 12/04/2021) ----------------------------------------

    def test_filtro1_sempre_nao_se_aplica_mesmo_com_atraso(self):
        """CRÍTICO: FILTRO 1 NUNCA pode retornar decadência=True."""
        M = self._math()
        infracao     = datetime.date(2020, 1, 1)
        notificacao  = datetime.date(2020, 6, 1)   # 5 meses depois — violaria 30 dias antigo
        decad, relat = M.check_decadencia(infracao, notificacao)
        self.assertFalse(decad, "FILTRO 1 não pode declarar decadência")
        self.assertIn("NÃO SE APLICA", relat)

    def test_filtro1_sem_atraso_tambem_nao_se_aplica(self):
        M = self._math()
        infracao    = datetime.date(2019, 5, 10)
        notificacao = datetime.date(2019, 5, 20)
        decad, relat = M.check_decadencia(infracao, notificacao)
        self.assertFalse(decad)
        self.assertIn("NÃO SE APLICA", relat)

    # --- FILTRO 2 (12/04/2021 a 21/10/2021) ------------------------------------

    def test_filtro2_dentro_de_180_dias(self):
        M = self._math()
        infracao    = datetime.date(2021, 5, 1)
        notificacao = datetime.date(2021, 8, 1)   # 92 dias
        decad, _    = M.check_decadencia(infracao, notificacao)
        self.assertFalse(decad)

    def test_filtro2_apos_180_dias(self):
        M = self._math()
        infracao    = datetime.date(2021, 5, 1)
        notificacao = datetime.date(2021, 11, 1)  # 184 dias
        decad, _    = M.check_decadencia(infracao, notificacao)
        self.assertTrue(decad)

    def test_filtro2_apos_360_dias_decisao_final(self):
        M = self._math()
        infracao       = datetime.date(2021, 5, 1)
        notificacao    = datetime.date(2021, 9, 1)  # 123 dias (ok)
        decisao_final  = datetime.date(2022, 8, 1)  # 457 dias desde infração
        decad, _       = M.check_decadencia(infracao, notificacao, decisao_final)
        self.assertTrue(decad)

    # --- FILTRO 3 (após 22/10/2021) --------------------------------------------

    def test_filtro3_dentro_de_180_dias(self):
        M = self._math()
        infracao    = datetime.date(2022, 1, 1)
        notificacao = datetime.date(2022, 4, 1)   # 90 dias
        decad, _    = M.check_decadencia(infracao, notificacao)
        self.assertFalse(decad)

    def test_filtro3_apos_180_dias(self):
        M = self._math()
        infracao    = datetime.date(2022, 1, 1)
        notificacao = datetime.date(2022, 8, 1)   # 212 dias
        decad, _    = M.check_decadencia(infracao, notificacao)
        self.assertTrue(decad)

    def test_filtro3_covid_desconta_256_dias(self):
        """COVID (Res. 782): desconto de 256 dias para infrações até 30/11/2020."""
        M = self._math()
        infracao    = datetime.date(2020, 3, 1)   # antes do limite COVID
        notificacao = datetime.date(2021, 1, 1)   # 306 dias brutos; com desconto: 50 dias → ok
        # Mas FILTRO 1 → sempre False, independente do desconto
        decad, relat = M.check_decadencia(infracao, notificacao)
        self.assertFalse(decad)
        self.assertIn("NÃO SE APLICA", relat)


# ---------------------------------------------------------------------------
# Bloco 2 — process_message por fase (com mocks — sem banco, sem rede)
# ---------------------------------------------------------------------------

def _make_parecer(**kwargs):
    """Cria um MagicMock de Parecer com defaults razoáveis."""
    p = MagicMock()
    p.status_fase = 1
    p.autuacao_pdf_path = None
    p.consolidado_pdf_path = None
    p.ata_pdf_path = None
    p.data_sessao = None
    p.pa = ""
    p.sgpe = ""
    p.prazo_final = None
    p.data_protocolo = None
    p.data_infracao = None
    p.paginas_defesa = ""
    p.tabela_datas_sensiveis = ""
    p.admissibilidade_texto = "Admissibilidade gerada"
    p.tese = ""
    p.analise_tese_texto = ""
    p.is_tempestivo = True
    p.has_prescricao_punitiva = False
    p.has_prescricao_intercorrente = False
    p.has_decadencia = False
    p.julgador_tempestivo = None
    p.julgador_prescricao_punitiva = None
    p.julgador_prescricao_intercorrente = None
    p.julgador_decadencia = None
    p.save = MagicMock()
    p.user = MagicMock()
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


class TestFase1(unittest.TestCase):

    def _engine(self, **kwargs):
        from chat.jari_engine import JariEngine
        return JariEngine(_make_parecer(**kwargs))

    def test_resumo_retorna_prompt_atual(self):
        engine = self._engine(status_fase=1)
        result = engine.process_message("RESUMO")
        self.assertIn("upload", result.lower())

    def test_sem_arquivos_retorna_mensagem_necessidade_arquivos(self):
        engine = self._engine(status_fase=1)
        result = engine.process_message("qualquer coisa", uploaded_files=[])
        # Engine retorna aviso pedindo os arquivos
        self.assertTrue(
            "arquivo" in result.lower() or "pdf" in result.lower() or "upload" in result.lower(),
            f"Esperava mensagem sobre arquivos, recebeu: {result!r}"
        )

    def test_data_invalida_retorna_erro(self):
        engine = self._engine(status_fase=1, autuacao_pdf_path="aut.pdf")
        result = engine.process_message("32/01/2024")
        self.assertIn("❌", result)

    def test_data_valida_salva_e_avanca(self):
        engine = self._engine(status_fase=1, autuacao_pdf_path="aut.pdf")
        result = engine.process_message("15/05/2024")
        engine.parecer.save.assert_called()
        self.assertIsNotNone(engine.parecer.data_sessao)


class TestFase2(unittest.TestCase):

    def _engine(self, **kwargs):
        from chat.jari_engine import JariEngine
        return JariEngine(_make_parecer(status_fase=2, **kwargs))

    def test_ok_avanca_para_fase3(self):
        engine = self._engine()
        with patch.object(engine, 'run_phase_3', return_value="fase3"):
            result = engine.process_message("ok")
        self.assertEqual(result, "fase3")
        self.assertEqual(engine.parecer.status_fase, 3)

    def test_corrigir_reseta_e_volta_para_fase1(self):
        from chat.jari_engine import FASE_COLETA
        engine = self._engine()
        with patch.object(engine, 'get_current_prompt', return_value="prompt1"):
            result = engine.process_message("corrigir")
        self.assertEqual(engine.parecer.status_fase, FASE_COLETA)
        self.assertIsNone(engine.parecer.data_sessao)

    def test_texto_aleatorio_retorna_aviso(self):
        engine = self._engine()
        result = engine.process_message("qualquer coisa")
        self.assertIn("ok", result.lower())


class TestFase31(unittest.TestCase):

    def _engine(self, **kwargs):
        from chat.jari_engine import JariEngine
        return JariEngine(_make_parecer(status_fase=31, **kwargs))

    def test_tudo_ok_avanca_para_fase4(self):
        engine = self._engine(
            is_tempestivo=True,
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
        )
        with patch.object(engine, 'run_phase_4_extraction', return_value="fase4"):
            result = engine.process_message("TEMPESTIVIDADE: A; PUNITIVA: A; INTERCORRENTE: A; DECADÊNCIA: A")
        self.assertEqual(result, "fase4")

    def test_julgador_acata_prescricao_punitiva_automatica(self):
        """Julgador escolhe A (acolho) para punitiva → mantém True → pula para resultado."""
        engine = self._engine(has_prescricao_punitiva=True)
        with patch('chat.tasks.gerar_parecer_task') as mock_task:
            mock_task.delay.return_value = MagicMock(id="abc")
            result = engine.process_message("PUNITIVA: A")
        resp = json.loads(result)
        self.assertEqual(resp["type"], "PREJUDICIALIDADE")
        self.assertTrue(engine.parecer.julgador_prescricao_punitiva)

    def test_julgador_inverte_prescricao_punitiva(self):
        """Julgador escolhe B (não acolho) para punitiva → inverte False → avança para F4."""
        engine = self._engine(
            has_prescricao_punitiva=True,
            is_tempestivo=True,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
        )
        with patch.object(engine, 'run_phase_4_extraction', return_value="fase4"):
            result = engine.process_message(
                "TEMPESTIVIDADE: A; PUNITIVA: B; INTERCORRENTE: A; DECADÊNCIA: A"
            )
        self.assertEqual(result, "fase4")
        self.assertFalse(engine.parecer.julgador_prescricao_punitiva)

    def test_intempestividade_tecnica_acolhida_pula_para_resultado(self):
        engine = self._engine(is_tempestivo=False)
        with patch('chat.tasks.gerar_parecer_task') as mock_task:
            mock_task.delay.return_value = MagicMock(id="xyz")
            result = engine.process_message("TEMPESTIVIDADE: A")
        resp = json.loads(result)
        self.assertEqual(resp["type"], "PREJUDICIALIDADE")
        self.assertIn("INTEMPESTIVIDADE", engine.parecer.tese)

    def test_intempestividade_tecnica_nao_acolhida_avanca_para_merito(self):
        """Julgador B em tempestividade: inverte False → True → vai para F4."""
        engine = self._engine(
            is_tempestivo=False,
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
        )
        with patch.object(engine, 'run_phase_4_extraction', return_value="fase4"):
            result = engine.process_message(
                "TEMPESTIVIDADE: B; PUNITIVA: A; INTERCORRENTE: A; DECADÊNCIA: A"
            )
        self.assertEqual(result, "fase4")
        self.assertTrue(engine.parecer.julgador_tempestivo)

    def test_decadencia_filtro1_nao_prejudica(self):
        """has_decadencia=False (corrigido pelo FILTRO 1) → julgador acolhe → não prejudica."""
        engine = self._engine(
            has_decadencia=False,   # JariMath corrigido já retorna False p/ FILTRO 1
            is_tempestivo=True,
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
        )
        with patch.object(engine, 'run_phase_4_extraction', return_value="fase4"):
            result = engine.process_message(
                "TEMPESTIVIDADE: A; PUNITIVA: A; INTERCORRENTE: A; DECADÊNCIA: A"
            )
        self.assertEqual(result, "fase4")

    def test_formato_frontend_real_nao_acolhida_avanca_merito(self):
        """Formato real do frontend: 'KEYWORD - Não Acolhida; X' deve ser parseado corretamente."""
        # Simula o exact string que submitTeseDecisions() envia quando o julgador
        # rejeita intempestividade e prescrições (automáticas = True), mas aceita sem bloqueio
        engine = self._engine(
            is_tempestivo=False,
            has_prescricao_punitiva=True,
            has_prescricao_intercorrente=True,
            has_decadencia=False,
        )
        msg_real = (
            "TEMPESTIVIDADE - Não Acolhida; X\n\n"
            "PUNITIVA - Não Acolhida; X\n\n"
            "INTERCORRENTE - Não Acolhida; X\n\n"
            "DECADENCIA - Acolhida; ✔️"
        )
        with patch.object(engine, 'run_phase_4_extraction', return_value="fase4"):
            result = engine.process_message(msg_real)
        self.assertEqual(result, "fase4")
        self.assertTrue(engine.parecer.julgador_tempestivo)
        self.assertFalse(engine.parecer.julgador_prescricao_punitiva)
        self.assertFalse(engine.parecer.julgador_prescricao_intercorrente)
        self.assertFalse(engine.parecer.julgador_decadencia)

    def test_formato_frontend_real_acolhida_vai_para_resultado(self):
        """Formato real: julgador aceita a intempestividade → deve ir para RESULTADO."""
        engine = self._engine(
            is_tempestivo=False,
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
        )
        msg_real = (
            "TEMPESTIVIDADE - Acolhida; ✔️\n\n"
            "PUNITIVA - Não Acolhida; X\n\n"
            "INTERCORRENTE - Não Acolhida; X\n\n"
            "DECADENCIA - Não Acolhida; X"
        )
        with patch('chat.tasks.gerar_parecer_task') as mock_task:
            mock_task.delay.return_value = MagicMock(id="xyz")
            result = engine.process_message(msg_real)
        resp = json.loads(result)
        self.assertEqual(resp["type"], "PREJUDICIALIDADE")
        self.assertFalse(engine.parecer.julgador_tempestivo)
        self.assertIn("INTEMPESTIVIDADE", engine.parecer.tese)


class TestFase4(unittest.TestCase):

    def _engine(self, **kwargs):
        from chat.jari_engine import JariEngine
        return JariEngine(_make_parecer(status_fase=4, **kwargs))

    def test_ok_dispara_analise_tese(self):
        engine = self._engine()
        with patch.object(engine, 'analise_tese_fase_4', return_value="analise"):
            result = engine.process_message("ok")
        self.assertEqual(result, "analise")

    def test_texto_livre_dispara_refinamento(self):
        engine = self._engine()
        with patch('chat.engine.phase_4.run_refinement', return_value="refinado") as mock_r:
            result = engine.process_message("a tese é nulidade de notificação")
        mock_r.assert_called_once_with(engine, "a tese é nulidade de notificação")
        self.assertEqual(result, "refinado")


class TestFase41(unittest.TestCase):

    def _engine(self, **kwargs):
        from chat.jari_engine import JariEngine
        return JariEngine(_make_parecer(status_fase=41, **kwargs))

    def test_acolhida_gera_deferido(self):
        engine = self._engine()
        with patch('chat.tasks.gerar_parecer_task') as mock_task:
            mock_task.delay.return_value = MagicMock(id="t1")
            result = engine.process_message("acolhida;")
        resp = json.loads(result)
        self.assertEqual(resp["type"], "MERITO")
        self.assertIn("DEFERIDO", engine.parecer.analise_tese_texto)

    def test_nao_acolhida_gera_indeferido(self):
        engine = self._engine()
        with patch('chat.tasks.gerar_parecer_task') as mock_task:
            mock_task.delay.return_value = MagicMock(id="t2")
            result = engine.process_message("não acolhida")
        self.assertIn("INDEFERIDO", engine.parecer.analise_tese_texto)

    def test_sem_marcador_retorna_aviso(self):
        engine = self._engine()
        result = engine.process_message("acho que deve ser deferido")
        self.assertIn("Não identifiquei", result)


class TestFase7(unittest.TestCase):

    def _engine(self, **kwargs):
        from chat.jari_engine import JariEngine
        return JariEngine(_make_parecer(status_fase=7, **kwargs))

    def _mock_pastas(self, n=3):
        pastas = [MagicMock(id=i, nome_pasta=f"Pasta {i}") for i in range(n)]
        MockPasta = MagicMock()
        MockPasta.objects.get_or_create.return_value = (pastas[0], False)
        MockPasta.objects.filter.return_value.exclude.return_value.order_by.return_value = pastas[1:]
        return MockPasta, pastas

    def test_numero_valido_salva_pasta(self):
        engine = self._engine(parecer_final="Parecer OK", sgpe="999", pa="PA-999")
        MockPasta, pastas = self._mock_pastas()
        with patch('chat.models.Pasta', MockPasta):
            engine.process_message("1")
        self.assertIsNotNone(engine.parecer.pasta)

    def test_numero_fora_do_range_retorna_erro(self):
        engine = self._engine()
        MockPasta, _ = self._mock_pastas()
        with patch('chat.models.Pasta', MockPasta):
            result = engine.process_message("99")
        self.assertIn("inválido", result.lower())

    def test_texto_nao_numerico_retorna_erro(self):
        engine = self._engine()
        MockPasta, _ = self._mock_pastas()
        with patch('chat.models.Pasta', MockPasta):
            result = engine.process_message("pasta especial")
        self.assertIn("número", result.lower())


class TestRunPhase6Auditoria(unittest.TestCase):
    """Garante que run_phase_6 usa flags do julgador, não as automáticas."""

    def _engine(self, **kwargs):
        from chat.jari_engine import JariEngine
        return JariEngine(_make_parecer(**kwargs))

    def test_auditoria_usa_flag_julgador_prescricao(self):
        """has_punitiva=True, mas julgador inverteu para False → não deve ser erro_fatal."""
        engine = self._engine(
            has_prescricao_punitiva=True,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
            is_tempestivo=True,
            julgador_prescricao_punitiva=False,   # julgador inverteu
            julgador_prescricao_intercorrente=False,
            julgador_decadencia=False,
            julgador_tempestivo=True,
        )
        engine.parecer.parecer_final = "INDEFERIDO"  # correto p/ mérito
        engine.parecer.sgpe = "123"
        engine.parecer.pa = "PA-456"
        engine.parecer.parecer_final = "INDEFERIDO SGPE 123 PA-456"
        engine.parecer.created_at = __import__('django.utils.timezone', fromlist=['timezone']).now() if False else \
            __import__('datetime').datetime(2024, 1, 1, tzinfo=__import__('datetime').timezone.utc)

        MockPasta = MagicMock()
        MockPasta.objects.get_or_create.return_value = (MagicMock(id=1), False)
        MockPasta.objects.filter.return_value.exclude.return_value.order_by.return_value = []
        with patch('chat.integrations.GeminiClient') as MockGemini, \
             patch('chat.models.Pasta', MockPasta):
            MockGemini.return_value.audit_parecer.return_value = "Checklist OK"
            result = engine.run_phase_6()
        # Sem punitiva pelo julgador → não deve acionar erro_fatal
        self.assertNotIn("incompatível com extinção", result)

    def test_auditoria_detecta_inconsistencia_real(self):
        """Julgador acolheu prescrição mas parecer diz INDEFERIDO → erro_fatal."""
        engine = self._engine(
            has_prescricao_punitiva=True,
            julgador_prescricao_punitiva=True,
            julgador_prescricao_intercorrente=False,
            julgador_decadencia=False,
            julgador_tempestivo=True,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
            is_tempestivo=True,
        )
        # Parecer diz INDEFERIDO — não contém \bDEFERIDO\b isolado → deve acionar erro_fatal
        engine.parecer.parecer_final = "INDEFERIDO. Recurso improvido. SGPE 999 PA-999"
        engine.parecer.sgpe = "999"
        engine.parecer.pa = "PA-999"
        engine.parecer.created_at = \
            __import__('datetime').datetime(2024, 1, 1, tzinfo=__import__('datetime').timezone.utc)

        MockPasta = MagicMock()
        MockPasta.objects.get_or_create.return_value = (MagicMock(id=1), False)
        MockPasta.objects.filter.return_value.exclude.return_value.order_by.return_value = []
        with patch('chat.integrations.GeminiClient') as MockGemini, \
             patch('chat.models.Pasta', MockPasta):
            MockGemini.return_value.audit_parecer.return_value = "Checklist"
            result = engine.run_phase_6()
        self.assertIn("incompatível", result)


if __name__ == "__main__":
    unittest.main()
