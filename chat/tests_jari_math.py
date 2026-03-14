from django.test import TestCase
import datetime
from chat.jari_math import JariMath

class TestJariMath(TestCase):

    def test_prescricao_intercorrente(self):
        # Data inicial (Protocolo): 10/01/2020
        data_protocolo = datetime.date(2020, 1, 10)
        
        # Data final (Sessão) igual ao aniversário (10/01/2023) - Não prescrito
        data_sessao_nao_presc = datetime.date(2023, 1, 10)
        presc_bool, msg = JariMath.check_prescription_intercorrente(data_protocolo, data_sessao_nao_presc)
        self.assertFalse(presc_bool)
        self.assertEqual(msg, "Prescrição intercorrente não configurada.")
        
        # Data final (Sessão) posterior ao aniversário (11/01/2023) - Prescrito
        data_sessao_prescrito = datetime.date(2023, 1, 11)
        presc_bool, msg = JariMath.check_prescription_intercorrente(data_protocolo, data_sessao_prescrito)
        self.assertTrue(presc_bool)
        self.assertEqual(msg, "Prescrição intercorrente configurada.")

    def test_prescricao_punitiva(self):
        # 5 anos corridos (1825 dias) = Não prescrito. 1826 dias = Prescrito
        data_infracao = datetime.date(2015, 1, 1)
        data_sessao_1825 = datetime.date(2019, 12, 31) # Dif 1825
        self.assertFalse(JariMath.check_prescription_punitiva(data_infracao, data_sessao_1825))
        
        data_sessao_1826 = datetime.date(2020, 1, 1) # Dif 1826
        self.assertTrue(JariMath.check_prescription_punitiva(data_infracao, data_sessao_1826))

    def test_decadencia_antiga(self):
        # A) Antes de 12/04/2021 (Somente avalia 30 dias de Autuação)
        # Usando 01/01/2021 para não cair no desconto Covid (<= 30/11/2020)
        data_inf = datetime.date(2021, 1, 1)
        data_aut_ok = datetime.date(2021, 1, 31) # 30 dias
        data_aut_ruim = datetime.date(2021, 2, 1) # 31 dias
        
        self.assertFalse(JariMath.check_decadencia(data_inf, data_aut_ok)[0])
        self.assertTrue(JariMath.check_decadencia(data_inf, data_aut_ruim)[0])

    def test_decadencia_transicao(self):
        # B) Entre 12/04/21 e 22/10/21 (180 autuação, 360 final)
        data_inf = datetime.date(2021, 5, 1)
        data_aut_ok = datetime.date(2021, 8, 1) # < 180
        data_dec_ok = datetime.date(2022, 1, 1) # < 360
        data_dec_ruim = datetime.date(2023, 1, 1) # > 360
        
        self.assertFalse(JariMath.check_decadencia(data_inf, data_aut_ok, data_dec_ok)[0])
        self.assertTrue(JariMath.check_decadencia(data_inf, data_aut_ok, data_dec_ruim)[0])

print("Script de Teste Criado.")
