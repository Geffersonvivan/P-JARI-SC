import datetime
import calendar
import logging

_logger = logging.getLogger(__name__)


class JariMath:
    # Res. CONTRAN 782/2020 — suspensão de prazos COVID-19
    # logica_jari.md §246: "A partir de 20/03/2020... encerramento em 30/11/2020, totalizando 256 dias corridos."
    INICIO_COVID_SUSPENSAO = datetime.date(2020, 3, 20)
    FIM_COVID_SUSPENSAO    = datetime.date(2020, 11, 30)
    # Período inclusivo (20/03 e 30/11 contam): (FIM - INICIO).days + 1 = 256
    # Fonte: logica_jari §246 — "totalizando 256 dias corridos de impedimento legal de agir"
    DIAS_SUSPENSAO_COVID   = (datetime.date(2020, 11, 30) - datetime.date(2020, 3, 20)).days + 1  # 256

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
    def _aniversario_5_anos(data_base):
        """
        Calcula a data exata do aniversário de 5 anos de data_base (mesmo dia/mês).
        Trata 29/02 em anos não-bissextos: usa 28/02 como aniversário (conservador).
        Spec logica_jari.md §119: "somar exatos 5 anos, mantendo mesmo dia/mês".
        """
        ano_aniversario = data_base.year + 5
        dia = data_base.day
        mes = data_base.month
        # 29/02 em ano não-bissexto → 28/02 (conservador: prescrição começa 1 dia antes)
        import calendar
        if mes == 2 and dia == 29 and not calendar.isleap(ano_aniversario):
            dia = 28
        return data_base.replace(year=ano_aniversario, month=mes, day=dia)

    @staticmethod
    def check_prescription_punitiva(data_infracao, data_sessao, marcos_interruptivos=None, desconto_covid_dias=0):
        """
        Prescrição Punitiva (Lei 9.873/99): 5 anos por data aniversário.
        Spec logica_jari.md §108–143:
          - A cada ato interruptivo válido, reinicia a contagem do zero.
          - O prazo expira às 23:59 do dia aniversário de 5 anos do último marco.
          - Se data_sessao > aniversário → SIM (prescrito).
          - Se data_sessao <= aniversário → NÃO.

        desconto_covid_dias: dias de suspensão COVID (256) a adicionar ao aniversário
          prescricional quando o último marco interruptivo ocorreu antes do fim do
          período de suspensão (Res. CONTRAN 782/2020 — até 30/11/2020).
          Isso estende o prazo, evitando declarar prescrição indevida.
        """
        ultimo_marco = data_infracao
        if marcos_interruptivos and len(marcos_interruptivos) > 0:
            ultimo_marco = max(marcos_interruptivos)

        aniversario = JariMath._aniversario_5_anos(ultimo_marco)
        if desconto_covid_dias:
            aniversario = aniversario + datetime.timedelta(days=desconto_covid_dias)
        _prescrito = data_sessao > aniversario if data_sessao else False
        _logger.info(
            "[JARIMATH] punitiva=%s | ultimo_marco=%s | aniversario=%s | sessao=%s | covid_dias=%s",
            _prescrito, ultimo_marco, aniversario, data_sessao, desconto_covid_dias,
        )
        return _prescrito

    @staticmethod
    def check_prescription_intercorrente(data_protocolo, data_sessao):
        """
        Prescrição Intercorrente (Lei 9.873/99).
        Prazo legal: 3 anos. Contagem: Calendário Civil (data a data).
        Datas obrigatórias exclusivas: Protocolo JARI (F1/P5) e Sessão (F1/P1).
        
        Regra de contagem: 
        Deve-se identificar o “aniversário” de 3 anos da data do protocolo do recurso JARI.
        Cálculo objetivo: Some 3 (três) anos civis à data do protocolo.
        A data obtida será denominada “Data de Aniversário de 3 anos do Protocolo”.

        Se a Data da Sessão de Julgamento JARI for anterior ou igual à Data de Aniversário:
        "Prescrição intercorrente não configurada."
        Se a Data da Sessão de Julgamento JARI for posterior à Data de Aniversário:
        "Prescrição intercorrente configurada."
        """
        if not data_protocolo or not data_sessao:
            return False, "Dados insuficientes para calcular a prescrição intercorrente."
            
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
            
        is_prescrito = data_sessao > aniversario
        
        if is_prescrito:
            declaracao = "Prescrição intercorrente configurada."
        else:
            declaracao = "Prescrição intercorrente não configurada."

        _logger.info(
            "[JARIMATH] intercorrente=%s | protocolo=%s | aniversario=%s | sessao=%s",
            is_prescrito, data_protocolo, aniversario, data_sessao,
        )
        return is_prescrito, declaracao

    @staticmethod
    def check_decadencia(data_infracao, data_expedicao_autuacao, data_decisao_final=None,
                         tipo_penalidade=None, data_conclusao_multa=None,
                         tem_flagrante=None, data_conhecimento_infracao=None):
        """
        Decadência CTB (Roteiro Fase 3 - P1):
        Evidencia: Faixa Temporal, Regra Aplicada e Incidência COVID.

        tipo_penalidade: 'multa' | 'advertencia' | 'suspensao' | 'cassacao'
        data_conclusao_multa: date — conclusão do processo de multa que gerou a suspensão/cassação
                              (FILTRO 3, suspensão/cassação — logica_jari.md §218)
        tem_flagrante: True = flagrante (marco = data_infracao)
                       False = sem flagrante (marco = data_conhecimento_infracao, art. 282 §6º-A CTB)
                       None = não determinado (fallback conservador: data_infracao)
        data_conhecimento_infracao: date — data em que o órgão tomou ciência da infração
                                    (FILTRO 3, multa sem flagrante)

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

        dias_infracao_notificacao = JariMath.calculate_days_diff(data_infracao, data_expedicao_autuacao)
        desconto_covid = 0
        incidencia_covid_texto = "Não aplicável."

        if data_infracao <= JariMath.FIM_COVID_SUSPENSAO:
            desconto_covid = JariMath.DIAS_SUSPENSAO_COVID
            dias_infracao_notificacao = max(0, dias_infracao_notificacao - desconto_covid)
            incidencia_covid_texto = "Sim (Res. 782/CONTRAN gerou desconto de -256 dias ao cômputo)."

        faixa_temporal = ""
        regra_aplicada = ""
        decadencia_encontrada = False
        detalhe_calculo = ""

        _penalidade_grave = tipo_penalidade and tipo_penalidade.lower() in ('suspensao', 'cassacao')

        # C) Infrações a partir de 22/10/2021 (inclusive) — FILTRO 3
        if data_infracao >= LIMIAR_2_TRANSICAO:
            faixa_temporal = "Após 22/10/2021"

            # FILTRO 3 — Suspensão/Cassação: marco inicial é a conclusão da multa, não a infração
            # (logica_jari.md §218: "data da conclusão do processo da multa que lhes deu causa")
            if _penalidade_grave:
                # C2-FIX: spec §241 — único prazo para suspensão/cassação é 360 dias da conclusão da multa.
                # Removido o check intermediário de 180 dias que não existe na especificação.
                regra_aplicada = "360 dias Instauração — marco: conclusão da multa (art. 24 §1º Res. 844/2021)"
                if data_conclusao_multa:
                    data_marco_inicio = data_conclusao_multa
                    if isinstance(data_marco_inicio, str):
                        import datetime as _dt
                        data_marco_inicio = _dt.datetime.strptime(data_marco_inicio, "%Y-%m-%d").date()
                    dias_marco_notificacao = max(0, JariMath.calculate_days_diff(data_marco_inicio, data_expedicao_autuacao) - desconto_covid)
                else:
                    # Sem data de conclusão da multa — fallback conservador com aviso
                    data_marco_inicio = data_infracao
                    dias_marco_notificacao = dias_infracao_notificacao
                    regra_aplicada += " [AVISO: data_conclusao_multa não informada — usando data_infracao como fallback]"

                if dias_marco_notificacao > 360:
                    decadencia_encontrada = True
                    detalhe_calculo = (
                        f"Instauração excedeu 360 dias a partir da conclusão da multa "
                        f"({dias_marco_notificacao} dias contabilizados)."
                    )
                else:
                    detalhe_calculo = (
                        f"Dentro do limite de 360 dias a partir da conclusão da multa "
                        f"({dias_marco_notificacao} dias transcorridos)."
                    )
            else:
                # FILTRO 3 — Multa/Advertência: marco e limiar dependem do flagrante
                # Com flagrante    → 180 dias da data_infracao (art. 282 §6º-A CTB / logica_jari §239)
                # Sem flagrante    → 360 dias da data_conhecimento_infracao (art. 282 §6º-A CTB / logica_jari §240)
                # Não determinado → fallback conservador: data_infracao com 180 dias
                if tem_flagrante is False and data_conhecimento_infracao:
                    data_marco_multa = data_conhecimento_infracao
                    if isinstance(data_marco_multa, str):
                        import datetime as _dt
                        data_marco_multa = _dt.datetime.strptime(data_marco_multa, "%Y-%m-%d").date()
                    regra_aplicada = "360 dias — marco: data do conhecimento (sem flagrante, art. 282 §6º-A CTB)"
                    dias_marco_notificacao = max(0, JariMath.calculate_days_diff(data_marco_multa, data_expedicao_autuacao) - desconto_covid)
                    limiar_f3 = 360
                elif tem_flagrante is False and not data_conhecimento_infracao:
                    data_marco_multa = data_infracao
                    regra_aplicada = "180 dias — sem flagrante, marco data_infracao (data_conhecimento não informada)"
                    dias_marco_notificacao = dias_infracao_notificacao
                    limiar_f3 = 180
                else:
                    # Com flagrante ou não determinado → 180 dias da data_infracao
                    data_marco_multa = data_infracao
                    regra_aplicada = "180 dias — marco: data da infração (flagrante, art. 282 §6º-A CTB)"
                    if tem_flagrante is None:
                        regra_aplicada += " [flagrante não determinado — usando data_infracao como fallback]"
                    dias_marco_notificacao = dias_infracao_notificacao
                    limiar_f3 = 180

                if dias_marco_notificacao > limiar_f3:
                    decadencia_encontrada = True
                    detalhe_calculo = f"Prazo excedeu {limiar_f3} dias ({dias_marco_notificacao} dias contabilizados)."
                else:
                    detalhe_calculo = f"Dentro do limite de {limiar_f3} dias ({dias_marco_notificacao} dias transcorridos)."

        # B) Infrações entre 12/04/2021 e 21/10/2021 (inclusive) — FILTRO 2
        elif data_infracao >= LIMIAR_1_ANTIGA and data_infracao < LIMIAR_2_TRANSICAO:
            faixa_temporal = "De 12/04/2021 a 21/10/2021"

            # FILTRO 2 — Suspensão/Cassação NÃO está sujeita a 180/360 dias
            # (Nota CETRAN/SC 02/03/2023: prazo decadencial só vale para multas/advertências)
            if _penalidade_grave:
                faixa_temporal = "De 12/04/2021 a 22/10/2021 — Suspensão/Cassação"
                regra_aplicada = "NÃO SE APLICA — Suspensão/Cassação (Nota CETRAN/SC 02/03/2023)"
                decadencia_encontrada = False
                detalhe_calculo = (
                    "Penalidade de suspensão ou cassação no período FILTRO 2 (12/04/2021–22/10/2021). "
                    "A Nota CETRAN/SC 02/03/2023 restringe a decadência de 180/360 dias "
                    "exclusivamente a multas e advertências neste período. "
                    "Análise encaminhada à Prescrição Punitiva (Lei 9.873/1999)."
                )
            else:
                # C1-FIX: FILTRO 2 multa/advertência — distinguir flagrante de sem flagrante.
                # Com flagrante → 180 dias da data_infracao (logica_jari.md §227)
                # Sem flagrante → 360 dias da data_conhecimento_infracao (logica_jari.md §228)
                if tem_flagrante is False and data_conhecimento_infracao:
                    data_marco_multa_f2 = data_conhecimento_infracao
                    if isinstance(data_marco_multa_f2, str):
                        import datetime as _dt
                        data_marco_multa_f2 = _dt.datetime.strptime(data_marco_multa_f2, "%Y-%m-%d").date()
                    regra_aplicada = "360 dias — marco: data do conhecimento (sem flagrante, art. 282 §6º-A CTB)"
                    dias_marco_f2 = max(0, JariMath.calculate_days_diff(data_marco_multa_f2, data_expedicao_autuacao) - desconto_covid)
                    limiar_f2 = 360
                elif tem_flagrante is False and not data_conhecimento_infracao:
                    data_marco_multa_f2 = data_infracao
                    regra_aplicada = "180 dias — sem flagrante, marco data_infracao (data_conhecimento não informada)"
                    dias_marco_f2 = dias_infracao_notificacao
                    limiar_f2 = 180
                else:
                    # Com flagrante ou não determinado → 180 dias da data_infracao
                    data_marco_multa_f2 = data_infracao
                    regra_aplicada = "180 dias Notificação / 360 dias Decisão Final"
                    if tem_flagrante is None:
                        regra_aplicada += " [flagrante não determinado — usando data_infracao como fallback]"
                    dias_marco_f2 = dias_infracao_notificacao
                    limiar_f2 = 180

                if dias_marco_f2 > limiar_f2:
                    decadencia_encontrada = True
                    detalhe_calculo = f"Prazo excedeu {limiar_f2} dias ({dias_marco_f2} dias contabilizados)."
                else:
                    detalhe_calculo = f"Dentro do limite de {limiar_f2} dias ({dias_marco_f2} dias transcorridos)."
            
        # A) Infrações anteriores a 12/04/2021 — FILTRO 1
        # HARD STOP (Parecer CETRAN/SC 381/2022): decadência de 180/360 dias é PROIBIDA
        # para este período. Resultado sempre "NÃO SE APLICA".
        else:
            faixa_temporal = "Antes 12/04/2021"
            regra_aplicada = "NÃO SE APLICA — Blindagem CETRAN/SC 381/2022"
            decadencia_encontrada = False  # Hard stop: nunca True para FILTRO 1
            detalhe_calculo = (
                "Infração anterior a 12/04/2021 (Filtro 1). "
                "Decadência de 180/360 dias expressamente proibida pelo Parecer CETRAN/SC 381/2022. "
                "Análise encaminhada exclusivamente à Prescrição Punitiva (Lei 9.873/1999)."
            )

        relatorio_decadencia = (
            f"  - **Data da Infração**: {data_infracao.strftime('%d/%m/%Y')}\n"
            f"  - **Faixa Temporal Identificada**: {faixa_temporal}\n"
            f"  - **Regra Aplicada**: {regra_aplicada}\n"
            f"  - **Incidência COVID (Res. 782)**: {incidencia_covid_texto}\n"
            f"  - **Detalhe do Cálculo**: {detalhe_calculo}"
        )

        _logger.info(
            "[JARIMATH] decadencia=%s | filtro=%s | regra=%s | detalhe=%s",
            decadencia_encontrada, faixa_temporal, regra_aplicada,
            detalhe_calculo[:120] if detalhe_calculo else '',
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
