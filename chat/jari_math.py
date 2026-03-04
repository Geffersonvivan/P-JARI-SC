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
        Calcula a diferença em dias corridos.
        Conforme roteiro: "Excluir o dia inicial e incluir o dia final na contagem."
        Matematicamente, (data_final - data_inicial).days já faz exatamente isso.
        """
        if isinstance(start_date, str):
            start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        if isinstance(end_date, str):
            end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

        delta = end_date - start_date
        return delta.days

    @staticmethod
    def check_prescription_punitiva(data_infracao, data_sessao, marcos_interruptivos=None):
        """
        Prescrição Punitiva (Lei 9.873/99): 5 anos (1825 dias corridos).
        Roteiro: A cada ato interruptivo válido, reiniciar integralmente a contagem.
        """
        # Se não enviou marcos interruptivos processados, calcula direto a diferença bruta
        # Mas o ideal na F3 é pegar a data do último marco interruptivo.
        ultimo_marco = data_infracao
        if marcos_interruptivos and len(marcos_interruptivos) > 0:
            # Assume que os marcos vêm ordenados ou pega o mais recente válido
            ultimo_marco = max(marcos_interruptivos)
            
        dias_diferenca = JariMath.calculate_days_diff(ultimo_marco, data_sessao)
        
        # Pela regra direta P-JARI/SC: "Se o intervalo for superior a 1825 dias -> Prescrição"
        return dias_diferenca > 1825

    @staticmethod
    def check_prescription_intercorrente(data_protocolo, data_sessao):
        """
        Prescrição Intercorrente (Lei 9.873/99): 3 anos (1095 dias corridos).
        Datas obrigatórias exclusivas: Protocolo JARI (F1/P5) e Sessão (F1/P1).
        Regra de contagem: Excluir dia inicial, incluir final. Se > 1095 -> Prescrito.
        """
        dias_diferenca = JariMath.calculate_days_diff(data_protocolo, data_sessao)
        return dias_diferenca > 1095

    @staticmethod
    def check_decadencia(data_infracao, data_expedicao_autuacao, data_decisao_final=None):
        """
        Decadência CTB (Roteiro Fase 3 - P1):
        Classificação temporal obrigatória.
        """
        if isinstance(data_infracao, str):
            data_infracao = datetime.datetime.strptime(data_infracao, "%Y-%m-%d").date()
        if isinstance(data_expedicao_autuacao, str):
            data_expedicao_autuacao = datetime.datetime.strptime(data_expedicao_autuacao, "%Y-%m-%d").date()
            
        if data_decisao_final and isinstance(data_decisao_final, str):
            data_decisao_final = datetime.datetime.strptime(data_decisao_final, "%Y-%m-%d").date()

        # Marcos legais de transição CTB
        LIMIAR_1_ANTIGA = datetime.date(2021, 4, 12)
        LIMIAR_2_TRANSICAO = datetime.date(2021, 10, 22)
        
        dias_infracao_notificacao = JariMath.calculate_days_diff(data_infracao, data_expedicao_autuacao)

        # C) Infrações posteriores a 22/10/2021
        if data_infracao > LIMIAR_2_TRANSICAO:
            # Infração -> Notificação (180 dias)
            if dias_infracao_notificacao > 180:
                return True
            # Infração -> Decisão Final (360 dias)
            if data_decisao_final:
                dias_infracao_decisao = JariMath.calculate_days_diff(data_infracao, data_decisao_final)
                if dias_infracao_decisao > 360:
                    return True
            return False
            
        # B) Infrações entre 12/04/2021 e 22/10/2021
        elif data_infracao >= LIMIAR_1_ANTIGA and data_infracao <= LIMIAR_2_TRANSICAO:
            # Infração -> Notificação (180 dias)
            if dias_infracao_notificacao > 180:
                return True
            # Infração -> Conclusão do processo (360 dias)
            if data_decisao_final:
                dias_infracao_conclusao = JariMath.calculate_days_diff(data_infracao, data_decisao_final)
                if dias_infracao_conclusao > 360:
                    return True
            return False
            
        # A) Infrações anteriores a 12/04/2021
        else:
            # Aplicar norma antiga CTB art. 281, parágrafo único, II. (Normalmente 30 dias).
            # Para fins do Roteiro, se ultrapassar o limite expresso (que o sistema assumirá 30 dias
            # salvo exceção Sistêmica específica), cai aqui. Assumimos 30:
            if dias_infracao_notificacao > 30:
                return True
            return False

    @staticmethod
    def check_tempestividade(data_protocolo, prazo_final):
        """
        Tempestividade (CTB ART. 285)
        Se protocolo for posterior a limite -> Intempestivo
        """
        if isinstance(data_protocolo, str):
            data_protocolo = datetime.datetime.strptime(data_protocolo, "%Y-%m-%d").date()
        if isinstance(prazo_final, str):
            prazo_final = datetime.datetime.strptime(prazo_final, "%Y-%m-%d").date()
            
        # Retorna True se é Tempestivo
        return data_protocolo <= prazo_final
