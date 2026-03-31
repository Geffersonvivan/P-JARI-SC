import datetime
from django.test import TestCase
from chat.jari_math import JariMath


class JariMathTests(TestCase):

    def test_is_leap_year(self):
        self.assertTrue(JariMath.is_leap_year(2020))
        self.assertTrue(JariMath.is_leap_year(2024))
        self.assertFalse(JariMath.is_leap_year(2021))
        self.assertFalse(JariMath.is_leap_year(2023))

    def test_count_leap_years(self):
        # 2020 and 2024 are leap years
        self.assertEqual(JariMath.count_leap_years(2020, 2025), 2)
        # Only 2024
        self.assertEqual(JariMath.count_leap_years(2022, 2025), 1)

    def test_calculate_days_diff(self):
        # 1 day difference
        self.assertEqual(JariMath.calculate_days_diff("2024-01-01", "2024-01-02"), 1)
        # 365 days (non-leap year interval)
        self.assertEqual(JariMath.calculate_days_diff("2021-01-01", "2022-01-01"), 365)
        # 366 days (leap year interval crossing Feb 29)
        self.assertEqual(JariMath.calculate_days_diff("2023-03-01", "2024-03-01"), 366)

    def test_check_prescription_intercorrente(self):
        protocol_date = datetime.date(2017, 1, 1)

        # On exact anniversary - should NOT trigger prescription
        session_date = datetime.date(2020, 1, 1)
        is_prescrito, msg = JariMath.check_prescription_intercorrente(protocol_date, session_date)
        self.assertFalse(is_prescrito)
        self.assertEqual(msg, "Prescrição intercorrente não configurada.")

        # After exact anniversary - should trigger prescription
        session_date_late = datetime.date(2020, 1, 2)
        is_prescrito, msg = JariMath.check_prescription_intercorrente(protocol_date, session_date_late)
        self.assertTrue(is_prescrito)
        self.assertEqual(msg, "Prescrição intercorrente configurada.")

    def test_check_tempestividade(self):
        # On the exact final day
        self.assertTrue(JariMath.check_tempestividade("2024-05-10", "2024-05-10"))
        # Before the final day
        self.assertTrue(JariMath.check_tempestividade("2024-05-09", "2024-05-10"))
        # After the final day
        self.assertFalse(JariMath.check_tempestividade("2024-05-11", "2024-05-10"))


# ---------------------------------------------------------------------------
# Prescrição Punitiva (Lei 9.873/99)
# ---------------------------------------------------------------------------

class TestPrescricaoPunitiva(TestCase):

    def test_sem_marcos_nao_prescrito_no_aniversario(self):
        """Sessão exatamente no aniversário de 5 anos → NÃO prescrito."""
        infracao = datetime.date(2016, 6, 15)
        sessao   = datetime.date(2021, 6, 15)  # exato aniversário
        self.assertFalse(JariMath.check_prescription_punitiva(infracao, sessao))

    def test_sem_marcos_prescrito_um_dia_apos_aniversario(self):
        """Sessão um dia depois do aniversário → prescrito."""
        infracao = datetime.date(2016, 6, 15)
        sessao   = datetime.date(2021, 6, 16)
        self.assertTrue(JariMath.check_prescription_punitiva(infracao, sessao))

    def test_com_marcos_interruptivos_reinicia_contagem(self):
        """Marco interruptivo 2 anos depois → aniversário se desloca para 5 anos do marco."""
        infracao = datetime.date(2015, 1, 1)
        marco    = datetime.date(2017, 1, 1)   # 2 anos depois — reinicia
        # Sessão é 4 anos após o marco (dentro dos 5 anos do marco) → não prescrito
        sessao   = datetime.date(2021, 1, 1)
        self.assertFalse(JariMath.check_prescription_punitiva(infracao, sessao, [marco]))

    def test_com_marcos_prescrito_apos_5_anos_do_ultimo(self):
        """5 anos e 1 dia após o último marco → prescrito."""
        infracao = datetime.date(2015, 1, 1)
        marco    = datetime.date(2017, 3, 10)
        sessao   = datetime.date(2022, 3, 11)  # 5 anos e 1 dia após o marco
        self.assertTrue(JariMath.check_prescription_punitiva(infracao, sessao, [marco]))

    def test_desconto_covid_estende_prazo(self):
        """256 dias de desconto COVID deslocam o aniversário para frente."""
        infracao = datetime.date(2015, 6, 1)
        # Sem desconto: aniversário em 2020-06-01; sessão em 2020-06-02 seria prescrito
        sessao_sem_covid = datetime.date(2020, 6, 2)
        self.assertTrue(JariMath.check_prescription_punitiva(infracao, sessao_sem_covid))
        # Com desconto de 256 dias: aniversário se desloca para ~2021-02-12; mesma sessão → não prescrito
        self.assertFalse(JariMath.check_prescription_punitiva(infracao, sessao_sem_covid, desconto_covid_dias=256))

    def test_data_infracao_29fev_bissexto_aniversario_em_28fev(self):
        """Infração em 29/02 → aniversário em ano não-bissexto usa 28/02 (conservador)."""
        infracao = datetime.date(2016, 2, 29)  # 2016 é bissexto
        # Aniversário em 2021 (não-bissexto) → 28/02/2021
        sessao_no_dia = datetime.date(2021, 2, 28)
        self.assertFalse(JariMath.check_prescription_punitiva(infracao, sessao_no_dia))
        sessao_depois = datetime.date(2021, 3, 1)
        self.assertTrue(JariMath.check_prescription_punitiva(infracao, sessao_depois))

    def test_multiplos_marcos_usa_o_mais_recente(self):
        """Com vários marcos, o mais recente define o prazo."""
        infracao = datetime.date(2013, 1, 1)
        marcos   = [
            datetime.date(2014, 1, 1),
            datetime.date(2016, 6, 1),  # mais recente
            datetime.date(2015, 3, 1),
        ]
        # 5 anos do mais recente (2016-06-01) = 2021-06-01
        sessao_ok = datetime.date(2021, 6, 1)
        self.assertFalse(JariMath.check_prescription_punitiva(infracao, sessao_ok, marcos))
        sessao_tarde = datetime.date(2021, 6, 2)
        self.assertTrue(JariMath.check_prescription_punitiva(infracao, sessao_tarde, marcos))


# ---------------------------------------------------------------------------
# Decadência (CTB) — FILTRO 1 / 2 / 3
# ---------------------------------------------------------------------------

class TestDecadenciaFiltro1(TestCase):
    """FILTRO 1: infrações até 11/04/2021 — decadência NUNCA se aplica (Parecer CETRAN/SC 381/2022)."""

    def test_hard_stop_mesmo_com_atraso_extremo(self):
        """Mesmo com 2 anos de atraso, FILTRO 1 retorna False."""
        infracao    = datetime.date(2019, 1, 1)
        notificacao = datetime.date(2021, 1, 1)  # 730 dias — violaria qualquer prazo
        decad, relat = JariMath.check_decadencia(infracao, notificacao)
        self.assertFalse(decad)
        self.assertIn("NÃO SE APLICA", relat)

    def test_hard_stop_limite_do_filtro(self):
        """Infração em 11/04/2021 (último dia do FILTRO 1) → NÃO SE APLICA."""
        infracao    = datetime.date(2021, 4, 11)
        notificacao = datetime.date(2022, 1, 1)
        decad, relat = JariMath.check_decadencia(infracao, notificacao)
        self.assertFalse(decad)
        self.assertIn("NÃO SE APLICA", relat)


class TestDecadenciaFiltro2(TestCase):
    """FILTRO 2: infrações de 12/04/2021 a 21/10/2021."""

    def test_notificacao_dentro_180_nao_decadente(self):
        infracao    = datetime.date(2021, 5, 1)
        notificacao = datetime.date(2021, 8, 1)   # 92 dias
        decad, _ = JariMath.check_decadencia(infracao, notificacao)
        self.assertFalse(decad)

    def test_notificacao_exatamente_180_nao_decadente(self):
        infracao    = datetime.date(2021, 5, 1)
        notificacao = infracao + datetime.timedelta(days=180)
        decad, _ = JariMath.check_decadencia(infracao, notificacao)
        self.assertFalse(decad)

    def test_notificacao_apos_180_decadente(self):
        infracao    = datetime.date(2021, 5, 1)
        notificacao = datetime.date(2021, 11, 1)  # 184 dias
        decad, _ = JariMath.check_decadencia(infracao, notificacao)
        self.assertTrue(decad)

    def test_decisao_final_apos_360_dias_decadente(self):
        """Notificação tempestiva mas decisão final > 360 dias → decadência."""
        infracao      = datetime.date(2021, 5, 1)
        notificacao   = datetime.date(2021, 9, 1)  # 123 dias — ok
        decisao_final = datetime.date(2022, 8, 1)  # 457 dias
        decad, relat  = JariMath.check_decadencia(infracao, notificacao, decisao_final)
        self.assertTrue(decad)
        self.assertIn("360", relat)

    def test_suspensao_cassacao_nao_se_aplica(self):
        """Suspensão/cassação no FILTRO 2 → NÃO SE APLICA (Nota CETRAN/SC 02/03/2023)."""
        infracao    = datetime.date(2021, 6, 1)
        notificacao = datetime.date(2022, 6, 1)   # muito além de 180 dias
        decad, relat = JariMath.check_decadencia(infracao, notificacao, tipo_penalidade='suspensao')
        self.assertFalse(decad)
        self.assertIn("NÃO SE APLICA", relat)

    def test_cassacao_nao_se_aplica(self):
        infracao    = datetime.date(2021, 8, 1)
        notificacao = datetime.date(2022, 8, 1)
        decad, relat = JariMath.check_decadencia(infracao, notificacao, tipo_penalidade='cassacao')
        self.assertFalse(decad)
        self.assertIn("NÃO SE APLICA", relat)

    def test_sem_flagrante_360_dias_do_conhecimento(self):
        """Sem flagrante com data_conhecimento: prazo é 360 dias do conhecimento."""
        infracao     = datetime.date(2021, 5, 1)
        conhecimento = datetime.date(2021, 5, 10)
        # Notificação 370 dias após conhecimento → decadente
        notificacao  = conhecimento + datetime.timedelta(days=370)
        decad, relat = JariMath.check_decadencia(
            infracao, notificacao,
            tem_flagrante=False,
            data_conhecimento_infracao=conhecimento
        )
        self.assertTrue(decad)

    def test_sem_flagrante_dentro_360_dias_do_conhecimento(self):
        infracao     = datetime.date(2021, 5, 1)
        conhecimento = datetime.date(2021, 5, 10)
        notificacao  = conhecimento + datetime.timedelta(days=350)
        decad, _ = JariMath.check_decadencia(
            infracao, notificacao,
            tem_flagrante=False,
            data_conhecimento_infracao=conhecimento
        )
        self.assertFalse(decad)


class TestDecadenciaFiltro3(TestCase):
    """FILTRO 3: infrações a partir de 22/10/2021."""

    def test_flagrante_dentro_180_nao_decadente(self):
        infracao    = datetime.date(2022, 1, 1)
        notificacao = datetime.date(2022, 4, 1)   # 90 dias
        decad, _ = JariMath.check_decadencia(infracao, notificacao, tem_flagrante=True)
        self.assertFalse(decad)

    def test_flagrante_exatamente_180_nao_decadente(self):
        infracao    = datetime.date(2022, 3, 1)
        notificacao = infracao + datetime.timedelta(days=180)
        decad, _ = JariMath.check_decadencia(infracao, notificacao, tem_flagrante=True)
        self.assertFalse(decad)

    def test_flagrante_apos_180_decadente(self):
        infracao    = datetime.date(2022, 1, 1)
        notificacao = datetime.date(2022, 8, 1)   # 212 dias
        decad, _ = JariMath.check_decadencia(infracao, notificacao, tem_flagrante=True)
        self.assertTrue(decad)

    def test_sem_flagrante_360_dias_do_conhecimento(self):
        infracao     = datetime.date(2022, 2, 1)
        conhecimento = datetime.date(2022, 2, 15)
        notificacao  = conhecimento + datetime.timedelta(days=370)
        decad, _ = JariMath.check_decadencia(
            infracao, notificacao,
            tem_flagrante=False,
            data_conhecimento_infracao=conhecimento
        )
        self.assertTrue(decad)

    def test_sem_flagrante_dentro_360_nao_decadente(self):
        infracao     = datetime.date(2022, 2, 1)
        conhecimento = datetime.date(2022, 2, 15)
        notificacao  = conhecimento + datetime.timedelta(days=350)
        decad, _ = JariMath.check_decadencia(
            infracao, notificacao,
            tem_flagrante=False,
            data_conhecimento_infracao=conhecimento
        )
        self.assertFalse(decad)

    def test_suspensao_360_dias_da_conclusao_multa(self):
        """Suspensão: prazo de 360 dias a partir da conclusão da multa originária."""
        infracao         = datetime.date(2022, 1, 1)
        conclusao_multa  = datetime.date(2022, 6, 1)
        # Instauração 370 dias após conclusão da multa → decadente
        instauracao      = conclusao_multa + datetime.timedelta(days=370)
        decad, relat = JariMath.check_decadencia(
            infracao, instauracao,
            tipo_penalidade='suspensao',
            data_conclusao_multa=conclusao_multa
        )
        self.assertTrue(decad)
        self.assertIn("360", relat)

    def test_suspensao_dentro_360_nao_decadente(self):
        infracao        = datetime.date(2022, 1, 1)
        conclusao_multa = datetime.date(2022, 6, 1)
        instauracao     = conclusao_multa + datetime.timedelta(days=350)
        decad, _ = JariMath.check_decadencia(
            infracao, instauracao,
            tipo_penalidade='suspensao',
            data_conclusao_multa=conclusao_multa
        )
        self.assertFalse(decad)

    def test_limite_primeiro_dia_filtro3(self):
        """Infração em 22/10/2021 (primeiro dia FILTRO 3) — regras do FILTRO 3 se aplicam."""
        infracao    = datetime.date(2021, 10, 22)
        notificacao = datetime.date(2022, 6, 1)   # 222 dias → decadente
        decad, relat = JariMath.check_decadencia(infracao, notificacao, tem_flagrante=True)
        self.assertTrue(decad)
        self.assertIn("Após 22/10/2021", relat)


# ---------------------------------------------------------------------------
# Tempestividade — cenários-limite
# ---------------------------------------------------------------------------

class TestTempestividadeEdgeCases(TestCase):

    def test_nenhuma_data_retorna_none(self):
        self.assertIsNone(JariMath.check_tempestividade(None, datetime.date(2024, 1, 1)))
        self.assertIsNone(JariMath.check_tempestividade(datetime.date(2024, 1, 1), None))
        self.assertIsNone(JariMath.check_tempestividade(None, None))

    def test_intempestivo_um_dia_apos_prazo(self):
        prazo    = datetime.date(2024, 3, 15)
        protocolo = prazo + datetime.timedelta(days=1)
        self.assertFalse(JariMath.check_tempestividade(protocolo, prazo))

    def test_tempestivo_mesmo_dia_do_prazo(self):
        prazo = datetime.date(2024, 3, 15)
        self.assertTrue(JariMath.check_tempestividade(prazo, prazo))

    def test_string_input_funciona(self):
        """Interface aceita strings no formato ISO além de date objects."""
        self.assertTrue(JariMath.check_tempestividade("2024-06-01", "2024-06-10"))
        self.assertFalse(JariMath.check_tempestividade("2024-06-11", "2024-06-10"))


# ---------------------------------------------------------------------------
# Prescrição Intercorrente — cenários-limite
# ---------------------------------------------------------------------------

class TestPrescricaoIntercorrenteEdgeCases(TestCase):

    def test_protocolo_29fev_bissexto_aniversario_em_28fev(self):
        """Protocolo em 29/02 → aniversário de 3 anos usa 28/02 do ano não-bissexto."""
        protocolo = datetime.date(2020, 2, 29)  # 2020 é bissexto
        # Aniversário em 2023 (não-bissexto) → 28/02/2023
        sessao_ok    = datetime.date(2023, 2, 28)
        prescrito, _ = JariMath.check_prescription_intercorrente(protocolo, sessao_ok)
        self.assertFalse(prescrito)

        sessao_tarde = datetime.date(2023, 3, 1)
        prescrito, _ = JariMath.check_prescription_intercorrente(protocolo, sessao_tarde)
        self.assertTrue(prescrito)

    def test_dados_insuficientes_retorna_false(self):
        prescrito, msg = JariMath.check_prescription_intercorrente(None, datetime.date(2024, 1, 1))
        self.assertFalse(prescrito)
        self.assertIn("Dados insuficientes", msg)

    def test_string_input_funciona(self):
        prescrito, _ = JariMath.check_prescription_intercorrente("2017-01-01", "2019-12-31")
        self.assertFalse(prescrito)
        prescrito, _ = JariMath.check_prescription_intercorrente("2017-01-01", "2020-01-02")
        self.assertTrue(prescrito)
