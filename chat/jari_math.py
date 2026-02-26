import datetime
import calendar

class JariMath:
    @staticmethod
    def is_leap_year(year):
        """Verifica se um ano é bissexto."""
        return calendar.isleap(year)

    @staticmethod
    def count_leap_years(start_year, end_year):
        """Conta quantos anos bissextos existem em um intervalo."""
        count = 0
        for year in range(start_year, end_year + 1):
            if JariMath.is_leap_year(year):
                count += 1
        return count

    @staticmethod
    def calculate_days_diff(start_date, end_date):
        """
        Calcula a diferença em dias corridos,
        excluindo o primeiro dia e incluindo o último.
        """
        if isinstance(start_date, str):
            start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        if isinstance(end_date, str):
            end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

        delta = end_date - start_date
        return delta.days

    @staticmethod
    def check_prescription_punitiva(data_infracao, data_sessao):
        """
        Prescrição Punitiva (Art. 1º, Lei 9.873/99):
        Ação punitiva prescreve em 5 anos (>= 1825 dias, ou 1826 se bissexto).
        """
        dias_diferenca = JariMath.calculate_days_diff(data_infracao, data_sessao)
        
        # Lógica simplificada: aproximação de 5 anos considerando os bissextos.
        anos_bissextos = JariMath.count_leap_years(data_infracao.year, data_sessao.year)
        limite_dias = (5 * 365) + anos_bissextos
        
        return dias_diferenca >= limite_dias

    @staticmethod
    def check_prescription_intercorrente(data_protocolo, data_sessao):
        """
        Prescrição Intercorrente (Art. 1º, § 1º, Lei 9.873/99):
        Paralisação do processo por mais de 3 anos (1095 dias).
        """
        dias_diferenca = JariMath.calculate_days_diff(data_protocolo, data_sessao)
        return dias_diferenca > 1095

    @staticmethod
    def check_tempestividade(data_protocolo, prazo_final):
        """Verifica se o protocolo ocorreu dentro do prazo."""
        if isinstance(data_protocolo, str):
            data_protocolo = datetime.datetime.strptime(data_protocolo, "%Y-%m-%d").date()
        if isinstance(prazo_final, str):
            prazo_final = datetime.datetime.strptime(prazo_final, "%Y-%m-%d").date()
            
        return data_protocolo <= prazo_final
