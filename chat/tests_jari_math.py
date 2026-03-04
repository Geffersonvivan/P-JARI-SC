from django.test import TestCase
import datetime
from chat.jari_math import JariMath

class TestJariMath(TestCase):

    def test_prescricao_intercorrente(self):
        # Data inicial (Protocolo): 10/01/2020
        # Data final (Sessão): 09/01/2023 (1095 dias exatos - Não prescrito)
        data_protocolo = datetime.date(2020, 1, 10)
        data_sessao_nao_presc = datetime.date(2023, 1, 9)
        self.assertFalse(JariMath.check_prescription_intercorrente(data_protocolo, data_sessao_nao_presc))
        
        # Data final (Sessão): 10/01/2023 (1096 dias - Prescrito)
        data_sessao_prescrito = datetime.date(2023, 1, 10)
        self.assertTrue(JariMath.check_prescription_intercorrente(data_protocolo, data_sessao_prescrito))

    def test_prescricao_punitiva(self):
        # 5 anos corridos (1825 dias) = Não prescrito. 1826 dias = Prescrito
        data_infracao = datetime.date(2015, 1, 1)
        data_sessao_1825 = datetime.date(2019, 12, 31) # Dif 1825
        self.assertFalse(JariMath.check_prescription_punitiva(data_infracao, data_sessao_1825))
        
        data_sessao_1826 = datetime.date(2020, 1, 1) # Dif 1826
        self.assertTrue(JariMath.check_prescription_punitiva(data_infracao, data_sessao_1826))

    def test_decadencia_antiga(self):
        # A) Antes de 12/04/2021 (Somente avalia 30 dias de Autuação)
        data_inf = datetime.date(2020, 1, 1)
        data_aut_ok = datetime.date(2020, 1, 31) # 30 dias
        data_aut_ruim = datetime.date(2020, 2, 1) # 31 dias
        
        self.assertFalse(JariMath.check_decadencia(data_inf, data_aut_ok))
        self.assertTrue(JariMath.check_decadencia(data_inf, data_aut_ruim))

    def test_decadencia_transicao(self):
        # B) Entre 12/04/21 e 22/10/21 (180 autuação, 360 final)
        data_inf = datetime.date(2021, 5, 1)
        data_aut_ok = datetime.date(2021, 8, 1) # < 180
        data_dec_ok = datetime.date(2022, 1, 1) # < 360
        data_dec_ruim = datetime.date(2023, 1, 1) # > 360
        
        self.assertFalse(JariMath.check_decadencia(data_inf, data_aut_ok, data_dec_ok))
        self.assertTrue(JariMath.check_decadencia(data_inf, data_aut_ok, data_dec_ruim))

print("Script de Teste Criado.")
