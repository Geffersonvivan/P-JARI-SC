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
        if not start_date or not end_date:
            return 0
            
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
        if not data_protocolo or not data_sessao:
            return False
            
        if isinstance(data_protocolo, str):
            data_protocolo = datetime.datetime.strptime(data_protocolo, "%Y-%m-%d").date()
        if isinstance(data_sessao, str):
            data_sessao = datetime.datetime.strptime(data_sessao, "%Y-%m-%d").date()

        # Calcula o aniversário de 3 anos (Calendário Civil - data a data)
        try:
            aniversario = data_protocolo.replace(year=data_protocolo.year + 3)
        except ValueError:
            # Lida com caso excepcional onde data_protocolo seja dia 29 de fevereiro em ano bissexto
            aniversario = data_protocolo.replace(year=data_protocolo.year + 3, day=28)
            
        return data_sessao > aniversario

    @staticmethod
    def check_decadencia(data_infracao, data_expedicao_autuacao, data_decisao_final=None):
        """
        Decadência CTB (Roteiro Fase 3 - P1):
        Evidencia: Faixa Temporal, Regra Aplicada e Incidência COVID.
        Retorno: Tuple (True/False para decadência, String_Relatorio)
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
        FIM_COVID_SUSPENSAO = datetime.date(2020, 11, 30)
        
        dias_infracao_notificacao = JariMath.calculate_days_diff(data_infracao, data_expedicao_autuacao)
        desconto_covid = 0
        incidencia_covid_texto = "Não aplicável."

        if data_infracao <= FIM_COVID_SUSPENSAO:
            desconto_covid = 256
            dias_infracao_notificacao = max(0, dias_infracao_notificacao - desconto_covid)
            incidencia_covid_texto = "Sim (Res. 782/CONTRAN gerou desconto de -256 dias ao cômputo)."

        faixa_temporal = ""
        regra_aplicada = ""
        decadencia_encontrada = False
        detalhe_calculo = ""

        # C) Infrações posteriores a 22/10/2021
        if data_infracao > LIMIAR_2_TRANSICAO:
            faixa_temporal = "Após 22/10/2021"
            regra_aplicada = "180 dias Notificação / 360 dias Conclusão"
            
            # Infração -> Notificação (180 dias)
            if dias_infracao_notificacao > 180:
                decadencia_encontrada = True
                detalhe_calculo = f"Notificação excedeu 180 dias ({dias_infracao_notificacao} dias contabilizados)."
            # Infração -> Decisão Final (360 dias)
            elif data_decisao_final:
                dias_infracao_decisao = max(0, JariMath.calculate_days_diff(data_infracao, data_decisao_final) - desconto_covid)
                if dias_infracao_decisao > 360:
                    decadencia_encontrada = True
                    detalhe_calculo = f"Decisão Final excedeu 360 dias ({dias_infracao_decisao} dias contabilizados)."
                else:
                    detalhe_calculo = f"Dentro do limite de 360 dias ({dias_infracao_decisao} dias transcorridos)."
            else:
                detalhe_calculo = f"Dentro do limite de 180 dias para notificação ({dias_infracao_notificacao} dias transcorridos)."
            
        # B) Infrações entre 12/04/2021 e 22/10/2021
        elif data_infracao >= LIMIAR_1_ANTIGA and data_infracao <= LIMIAR_2_TRANSICAO:
            faixa_temporal = "De 12/04/2021 a 22/10/2021"
            regra_aplicada = "180 dias Notificação / 360 dias Decisão Final"
            
            # Infração -> Notificação (180 dias)
            if dias_infracao_notificacao > 180:
                decadencia_encontrada = True
                detalhe_calculo = f"Notificação excedeu 180 dias ({dias_infracao_notificacao} dias contabilizados)."
            # Infração -> Conclusão do processo (360 dias)
            elif data_decisao_final:
                dias_infracao_conclusao = max(0, JariMath.calculate_days_diff(data_infracao, data_decisao_final) - desconto_covid)
                if dias_infracao_conclusao > 360:
                    decadencia_encontrada = True
                    detalhe_calculo = f"Decisão Final excedeu 360 dias ({dias_infracao_conclusao} dias contabilizados)."
                else:
                    detalhe_calculo = f"Dentro do limite de 360 dias ({dias_infracao_conclusao} dias transcorridos)."
            else:
                detalhe_calculo = f"Dentro do limite de 180 dias para notificação ({dias_infracao_notificacao} dias transcorridos)."
            
        # A) Infrações anteriores a 12/04/2021
        else:
            faixa_temporal = "Antes 12/04/2021"
            regra_aplicada = "Lei 9.873 / Art. 281 CTB (Limiar 30 dias para notificação)"
            
            if dias_infracao_notificacao > 30:
                decadencia_encontrada = True
                detalhe_calculo = f"Notificação excedeu 30 dias ({dias_infracao_notificacao} dias contabilizados pós-descontos)."
            else:
                detalhe_calculo = f"Dentro do limite de 30 dias para notificação ({dias_infracao_notificacao} dias transcorridos)."

        relatorio_decadencia = (
            f"  - **Data da Infração**: {data_infracao.strftime('%d/%m/%Y')}\n"
            f"  - **Faixa Temporal Identificada**: {faixa_temporal}\n"
            f"  - **Regra Aplicada**: {regra_aplicada}\n"
            f"  - **Incidência COVID (Res. 782)**: {incidencia_covid_texto}\n"
            f"  - **Detalhe do Cálculo**: {detalhe_calculo}"
        )

        return (decadencia_encontrada, relatorio_decadencia)

    @staticmethod
    def check_tempestividade(data_protocolo, prazo_final):
        """
        Tempestividade (CTB ART. 285)
        Se protocolo for posterior a limite -> Intempestivo
        """
        if not data_protocolo or not prazo_final:
            return None # Null indica que o avaliador não preencheu/sistema não encontrou
            
        if isinstance(data_protocolo, str):
            data_protocolo = datetime.datetime.strptime(data_protocolo, "%Y-%m-%d").date()
        if isinstance(prazo_final, str):
            prazo_final = datetime.datetime.strptime(prazo_final, "%Y-%m-%d").date()
            
        # Retorna True se é Tempestivo
        return data_protocolo <= prazo_final
