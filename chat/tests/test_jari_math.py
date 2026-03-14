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

