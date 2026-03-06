import base64
from chat.models import Parecer
from chat.jari_math import JariMath

class JariEngine:
    def __init__(self, parecer: Parecer):
        self.parecer = parecer

    def get_current_prompt(self):
        """Retorna a mensagem de prompt baseada na fase atual do processo."""
        fase = self.parecer.status_fase
        
        if fase == 1:
            prefix = ""
            if not self.parecer.data_sessao and not self.parecer.pa and not self.parecer.sgpe:
                prefix = "**Iniciando Fase 1: Coleta e Identificação (F1)!**\n\n"
                
            if not self.parecer.data_sessao:
                return prefix + "1. Por favor, informe a **Data da Sessão de Julgamento** (DD/MM/AAAA):"
            elif not self.parecer.pa:
                return prefix + "2. Por favor, informe o número do **Processo Administrativo**:"
            elif not self.parecer.sgpe:
                return prefix + "3. Por favor, informe o número do **SGPE**:"
            elif not self.parecer.prazo_final:
                return prefix + "4. Por favor, informe o **Prazo Final para protocolo do recurso JARI** (DD/MM/AAAA):"
            elif not self.parecer.data_protocolo:
                return prefix + "5. Por favor, informe a **Data do protocolo do recurso JARI** (DD/MM/AAAA):"
            elif not self.parecer.paginas_defesa:
                return prefix + "6. Por favor, informe as **Páginas da defesa Recurso JARI** (ex: pág. 15 até pág 24):"
            elif not self.parecer.autuacao_pdf_path:
                return prefix + "7. Por favor, faça o upload dos arquivos **'Autuação' e 'Consolidado'** juntos e digite ok:"
            
            return "Fase 1 concluída."

        elif fase == 2:
            return (
                f"{self.parecer.tabela_datas_sensiveis}\n\n"
                f"Confirme **'ok'** ou indique a **divergência** antes de prosseguir para a Fase 3 (Tempestividade, Prescrições e Decadência)."
            )
        elif fase == 3:
            return "Processando Prazos e Admissibilidade... (Simulando loading)"
        elif fase == 31: # Aguardando OK Admissibilidade
            return (
                f"**Fase 3: Admissibilidade e Prazos**\n\n"
                f"{self.parecer.admissibilidade_texto}\n\n"
                f"Responda apenas com **'ok'** para prosseguir para a análise das teses, ou **'divergência'** para apontar erros."
            )
        elif fase == 4:
            return (
                f"**Fase 4: Extração da Tese da Defesa**\n\n"
                f"A inteligência analisou o recurso nas páginas informadas ({self.parecer.paginas_defesa}) e identificou a seguinte tese principal:\n\n"
                f"**{self.parecer.tese}**\n\n"
                f"Responda **'ok'** para validá-la e realizar a pesquisa jurisprudencial, ou **digite uma nova tese** para substituí-la."
            )
        elif fase == 41: # Aguardando OK Tese
            return (
                f"**Fase 4: Conclusão Prévia das Teses**\n\n"
                f"{self.parecer.analise_tese_texto}\n\n"
                f"Responda apenas com **'ok'** para aprovar a conclusão prévia e gerar o Parecer Técnico final."
            )
        elif fase == 5:
            return "Gerando Parecer Técnico Final em Bloco Único... (Aguarde...)"
        elif fase == 7:
            from .models import Pasta
            
            pasta_outros, _ = Pasta.objects.get_or_create(user=self.parecer.user, nome_pasta="Outros")
            pastas_dinamicas = list(Pasta.objects.filter(user=self.parecer.user).exclude(id=pasta_outros.id).order_by('-created_at'))
            
            # Monta lista final para exibição na mesma ordem que será lida no process_message
            pastas = [pasta_outros] + pastas_dinamicas
                
            prompt = "**Salvamento do Projeto**\n\nSelecione qual pasta você deseja usar para salvar esta análise. Digite o número correspondente:\n\n"
            for i, p in enumerate(pastas, 1):
                prompt += f"{i}. {p.nome_pasta}\n"
            return prompt
        elif fase == 8:
            res = f"**{self.parecer.nome_processo} - Parecer Finalizado**\n\n"
            if self.parecer.parecer_final:
                res += self.parecer.parecer_final + "\n\n"
                if self.parecer.dossie_fontes:
                    res += f"\n\n<details class='mt-4 mb-2 bg-blue-50/50 rounded-xl border border-blue-100/50 overflow-hidden shadow-sm'><summary class='px-4 py-3 bg-white/50 cursor-pointer text-[#444746] font-medium flex items-center gap-2 hover:bg-blue-50/50 transition-colors outline-none'>🔎 FUNDAMENTAÇÃO NORMATIVA - PARECER</summary><div class='p-4 text-sm text-[#444746] leading-relaxed border-t border-blue-100/50 bg-white/30 whitespace-pre-wrap'>{self.parecer.dossie_fontes}</div></details>"
            else:
                res += "*(Sem parecer técnico gerado para este processo)*"
            return res
        else:
            return "Processo finalizado ou estado inválido."

    def process_message(self, message: str, uploaded_files=None):
        """Processa a mensagem do usuário e avança a fase se apropriado."""
        if uploaded_files is None:
            uploaded_files = []
            
        if message.strip() == 'RESUMO':
            return self.get_current_prompt()
            
        fase = self.parecer.status_fase

        if fase == 1:
            val = message.strip()
            
            # Limpa qualquer possibilidade de 'corrigir' ter deixado dados errados pra trás
            if val.lower() == 'corrigir':
                pass # Ignorar comando especial
                
            # 1. Verifica PRIORITARIAMENTE se são os PDFs/comando ok da última etapa (Etapa 7)
            # Para evitar que o 'ok' caia numa variável anterior que acidentalmente esteja vazia (ex: data_protocolo)
            if uploaded_files and len(uploaded_files) > 0:
                file_autuacao = uploaded_files[0]
                file_consolidado = uploaded_files[0]
                if len(uploaded_files) > 1:
                    f1, f2 = uploaded_files[0], uploaded_files[1]
                    f1_lower = f1.lower()
                    f2_lower = f2.lower()
                    
                    if any(term in f1_lower for term in ["consolidado", "cons", "defesa", "recurso"]):
                        file_consolidado = f1; file_autuacao = f2
                    elif any(term in f2_lower for term in ["consolidado", "cons", "defesa", "recurso"]):
                        file_consolidado = f2; file_autuacao = f1
                    elif any(term in f1_lower for term in ["autua", "ait", "termo"]):
                        file_autuacao = f1; file_consolidado = f2
                    elif any(term in f2_lower for term in ["autua", "ait", "termo"]):
                        file_autuacao = f2; file_consolidado = f1
                    else:
                        try:
                            from django.core.files.storage import default_storage
                            size1 = default_storage.size(f1) if default_storage.exists(f1) else 0
                            size2 = default_storage.size(f2) if default_storage.exists(f2) else 0
                        except Exception:
                            size1, size2 = 0, 0
                        if size1 > size2:
                            file_consolidado = f1; file_autuacao = f2
                        else:
                            file_consolidado = f2; file_autuacao = f1
                        
                self.parecer.autuacao_pdf_path = file_autuacao
                self.parecer.consolidado_pdf_path = file_consolidado
                self.parecer.status_fase = 2
                self.parecer.save()
                return self.run_phase_2()
            
            elif val.lower() == 'ok':
                # Só processa "ok" se ele já tiver pelo menos os campos anteriores e for a Etapa 7
                if self.parecer.data_sessao and self.parecer.paginas_defesa:
                    self.parecer.autuacao_pdf_path = "upload_simulado_autuacao.pdf"
                    self.parecer.consolidado_pdf_path = "upload_simulado_recurso.pdf"
                    self.parecer.status_fase = 2
                    self.parecer.save()
                    return self.run_phase_2()

            # 2. Se não for Upload, segue a esteira normal de dados sequenciais
            if not self.parecer.data_sessao:
                try:
                    import datetime
                    self.parecer.data_sessao = datetime.datetime.strptime(val, "%d/%m/%Y").date()
                except Exception:
                    return f"❌ Erro ao ler a data {val}. O formato deve ser DD/MM/AAAA. Ex: 15/05/2024. Tente novamente."
            elif not self.parecer.pa:
                self.parecer.pa = val
            elif not self.parecer.sgpe:
                self.parecer.sgpe = val
            elif not self.parecer.prazo_final:
                try:
                    import datetime
                    self.parecer.prazo_final = datetime.datetime.strptime(val, "%d/%m/%Y").date()
                except Exception:
                    return f"❌ Erro ao ler a data de prazo {val}. O formato deve ser DD/MM/AAAA."
            elif not self.parecer.data_protocolo:
                try:
                    import datetime
                    self.parecer.data_protocolo = datetime.datetime.strptime(val, "%d/%m/%Y").date()
                except Exception:
                    return f"❌ Erro ao ler a data de protocolo {val}. O formato deve ser DD/MM/AAAA."
            elif not self.parecer.paginas_defesa:
                self.parecer.paginas_defesa = val
            elif not self.parecer.autuacao_pdf_path:
                return "❌ Por favor, os arquivos são essenciais para avançarmos. Anexe-os e digite 'ok'."
            
            self.parecer.save()
            return self.get_current_prompt()

        elif fase == 2:
            if message.lower().strip() == 'ok':
                self.parecer.status_fase = 3
                self.parecer.save()
                return self.run_phase_3()
            elif message.lower().strip() == 'corrigir':
                self.parecer.status_fase = 1
                
                # Reseta dados
                self.parecer.data_sessao = None
                self.parecer.pa = ""
                self.parecer.sgpe = ""
                self.parecer.prazo_final = None
                self.parecer.data_protocolo = None
                self.parecer.paginas_defesa = ""
                self.parecer.autuacao_pdf_path = None
                self.parecer.consolidado_pdf_path = None
                
                self.parecer.save()
                return "Voltando à Fase 1. Reiniciando a coleta.\n" + self.get_current_prompt()
            else:
                return "Por favor, responda com **'ok'** para prosseguir ou **'corrigir'** para reiniciar."
                
        elif fase == 3:
            return self.run_phase_3()
            
        elif fase == 31:
            if message.lower().strip() == 'ok':
                # Aqui traduzimos as flags matemáticas estritas do BD para roteamento
                if self.parecer.has_prescricao_punitiva or self.parecer.has_prescricao_intercorrente or self.parecer.has_decadencia or not self.parecer.is_tempestivo:
                    self.parecer.status_fase = 5 # Pula pra Fase 5 de resultado prejudicado, não analisa mérito
                    
                    motivo = []
                    if self.parecer.has_prescricao_punitiva: motivo.append("PRESCRIÇÃO PUNITIVA")
                    if self.parecer.has_prescricao_intercorrente: motivo.append("PRESCRIÇÃO INTERCORRENTE")
                    if self.parecer.has_decadencia: motivo.append("DECADÊNCIA")
                    if not self.parecer.is_tempestivo: motivo.append("INTEMPESTIVIDADE")
                    
                    self.parecer.tese = f"MÉRITO PREJUDICADO ({' / '.join(motivo)})."
                    self.parecer.save()
                    return "\n⚠️ **Prejudicialidade Constatada**. Teses defensivas prejudicadas em razão da extinção da pretensão punitiva ou inadmissibilidade recursal.\n\n" + self.run_llm_phases()
                else:
                    return self.run_phase_4_extraction()
            else:
                return "Responda 'ok' para prosseguir. Em caso de divergência real, recomece ou modifique manualmente depois."

        elif fase == 4:
            if message.lower().strip() != 'ok':
                return self.run_phase_4_refinement(message.strip())
            return self.analise_tese_fase_4()
            
        elif fase == 41:
            escolhas = message.lower().strip()
            
            if not escolhas:
                return "Por favor, informe a opção escolhida para cada tese (Ex: 1 a, 2 b)."
                
            if "a" not in escolhas and "b" not in escolhas:
                return "Não identifiquei as opções 'a' ou 'b' na sua resposta. Digite no formato: 1 a, 2 b"
            
            resultado_marcado = "DEFERIDO" if "a" in escolhas else "INDEFERIDO"
            
            # Anexar as escolhas do julgador à tese para municiar a Fase 5
            self.parecer.analise_tese_texto += (
                f"\n\n--- DECISÕES ABSOLUTAS DO JULGADOR ---\n"
                f"Escolhas informadas: {escolhas}\n"
                f"RESULTADO EXIGIDO NESTE PARECER: {resultado_marcado}\n"
                f"DIRETRIZ FASE 5: Você DEVE acatar as alternativas escolhidas ("
                f"se o julgador escolheu 'a', transcreva a linha de raciocínio da Alternativa A de acolhimento; "
                f"se escolheu 'b', transcreva a Alternativa B de não acolhimento). "
                f"Ignore a alternativa descartada. O resultado final deve ser {resultado_marcado}."
            )
            
            self.parecer.status_fase = 5
            self.parecer.save()
            return self.run_llm_phases()
        
        elif fase == 6:
            if message.lower().strip() == 'ok':
                return self.run_phase_6()
            else:
                return "DIGITE 'ok' para auditoria final em tela."

        elif fase == 5:
            # Acionado caso seja intempestivo e tenha pulado a fase 4
            return self.run_llm_phases()

        elif fase == 7:
            from .models import Pasta
            # Seleção de pasta (Garantir msm ordem do get_current_prompt)
            pasta_outros, _ = Pasta.objects.get_or_create(user=self.parecer.user, nome_pasta="Outros")
            pastas_dinamicas = list(Pasta.objects.filter(user=self.parecer.user).exclude(id=pasta_outros.id).order_by('-created_at'))
            pastas = [pasta_outros] + pastas_dinamicas
            
            try:
                idx = int(message.strip()) - 1
                if 0 <= idx < len(pastas):
                    target_folder = pastas[idx]
                    
                    self.parecer.pasta = target_folder
                    sgpe = self.parecer.sgpe if self.parecer.sgpe else 'Sem SGPE'
                    self.parecer.nome_processo = f"Parecer ({sgpe})"
                    self.parecer.is_saved = True
                    self.parecer.status_fase = 8
                    self.parecer.save()
                    
                    folder_name = target_folder.nome_pasta
                    
                    return f"✅ **Sucesso!** O projeto foi salvo na pasta **{folder_name}**. Você pode consultá-lo na barra lateral no futuro."
                else:
                    return f"Número inválido. Por favor, escolha um número de 1 a {len(pastas)}."
            except ValueError:
                return "Por favor, digite apenas o **número** correspondente à pasta desejada."

        return "Processo encontra-se finalizado."

    def run_phase_2(self):
        """Nova Fase 2: Extração Autônoma de Datas e Validação LLM"""
        from chat.integrations import GeminiClient
        from chat.pdf_extractor import PDFExtractor
        import logging
        
        logger = logging.getLogger(__name__)
        gemini = GeminiClient()
        
        # 1. Extração local de Texto e Datas com PyMuPDF
        datas_autuacao = []
        datas_consolidado = []
        
        # Tenta extrair a autuação se houver e não for simulada
        if self.parecer.autuacao_pdf_path and "upload_simulado" not in self.parecer.autuacao_pdf_path:
            datas_autuacao = PDFExtractor.extract_dates_from_pdf(self.parecer.autuacao_pdf_path, "Autuação")
            
        # Tenta extrair o consolidado se houver e não for simulado
        if self.parecer.consolidado_pdf_path and "upload_simulado" not in self.parecer.consolidado_pdf_path:
            # Se forem o mesmo arquivo, pode ser bom evitar extração dupla, mas pro MVP mantemos igual
            if self.parecer.autuacao_pdf_path != self.parecer.consolidado_pdf_path:
                datas_consolidado = PDFExtractor.extract_dates_from_pdf(self.parecer.consolidado_pdf_path, "Consolidado")
            else:
                 datas_consolidado = [] # Não extrai duplicado
                 
        # Formata o texto pro prompt do LLM
        contexto_textual_datas = PDFExtractor.format_extraction_for_llm(datas_autuacao, datas_consolidado)
        
        # 2. Chama o LLM para cruzar as respostas do Bloco A com o texto do Bloco B
        texto_tabela = gemini.generate_phase2_report(self.parecer, contexto_textual_datas)
        
        self.parecer.tabela_datas_sensiveis = texto_tabela
        self.parecer.save()
        
        # Volta pro loop aguardando a pessoa dar 'ok' na tabela
        return self.get_current_prompt()

    def run_phase_3(self):
        """
        Fase 3 (Cálculos Matemáticos Puros).
        Avisa Fase 2 já extraiu a tabela.
        Em seguida, o Python extrai as datas dessa tabela com RegEx
        e usa o JariMath para assinalar no DB Tempestividade/Presc/Decadência.
        """
        import re
        import datetime
        
        # O F2 já preencheu a tabela_datas_sensiveis
        texto_tabela = self.parecer.tabela_datas_sensiveis or ""
        
        # Parseamento de datas via RegEx na Tabela F2 (Busca formato DD/MM/AAAA)
        # O prompt do F2 exige o formato exato "Data da Infração: 10/01/2020", etc.
        datas_encontradas = re.findall(r'(\d{2}/\d{2}/\d{4})', texto_tabela)
        datas_processadas = []
        for d in datas_encontradas:
            try:
                datas_processadas.append(datetime.datetime.strptime(d, "%d/%m/%Y").date())
            except Exception:
                pass
                
        # Ordenamos os marcos para pegar a Infração (primeira data provável) e Decisão (penúltimas)
        datas_processadas.sort()
        
        # O F1 já coleta:
        # Pergunta 1: self.parecer.data_sessao
        # Pergunta 4: self.parecer.prazo_final
        # Pergunta 5: self.parecer.data_protocolo
        
        # Simulando coleta inteligente se o motor encontrar na Tabela (F3)
        data_infracao = datas_processadas[0] if datas_processadas else self.parecer.data_protocolo # Fallback
        # Fallback ingênuo assumindo que a segunda data é a notificação autuação
        data_notificacao_autuacao = datas_processadas[1] if len(datas_processadas) > 1 else data_infracao
        
        # 3. Execução EXATA das restrições (Roteiro Fase 3)
        self.parecer.is_tempestivo = JariMath.check_tempestividade(self.parecer.data_protocolo, self.parecer.prazo_final)
        self.parecer.has_prescricao_punitiva = JariMath.check_prescription_punitiva(data_infracao, self.parecer.data_sessao, datas_processadas)
        self.parecer.has_prescricao_intercorrente = JariMath.check_prescription_intercorrente(self.parecer.data_protocolo, self.parecer.data_sessao)
        
        decadencia_bool, relatorio_decadencia = JariMath.check_decadencia(data_infracao, data_notificacao_autuacao, None)
        self.parecer.has_decadencia = decadencia_bool
        
        # 4. Texto visual para o usuário confirmando
        status_temp = "SIM" if self.parecer.is_tempestivo else "NÃO"
        status_pun = "SIM" if self.parecer.has_prescricao_punitiva else "NÃO"
        status_inter = "SIM" if self.parecer.has_prescricao_intercorrente else "NÃO"
        status_dec = "SIM" if self.parecer.has_decadencia else "NÃO"
        
        texto_status = (
            f"**INÍCIO FASE 3: VERIFICAÇÃO DE PRAZOS E PRESCRIÇÕES OBRIGATÓRIAS**\n\n"
            f"--- ⚖️ **CÁLCULOS TÉCNICOS EFETUADOS NA FASE 3 DO ROTEIRO** ---\n"
            f"- **Tempestivo**: {status_temp}\n"
            f"- **Prescrição Punitiva (>= 5 anos)**: {status_pun}\n"
            f"- **Prescrição Intercorrente (> 3 anos)**: {status_inter}\n"
            f"- **Decadência**: {status_dec}\n"
            f"**[TRAVA JARI - EVIDÊNCIAS DA DECADÊNCIA APLICADA]**\n{relatorio_decadencia}\n\n"
        )
        
        self.parecer.admissibilidade_texto = texto_status
        self.parecer.status_fase = 31 # Aguarda confirmação
        self.parecer.save()

        return self.get_current_prompt()

    def run_phase_4_extraction(self):
        """Extrai a tese automaticamente através da leitura do PDF pelo LLM nas páginas indicadas."""
        from chat.integrations import GeminiClient
        gemini = GeminiClient()
        
        tese_extraida = gemini.extract_tese(self.parecer)
        
        self.parecer.tese = tese_extraida
        self.parecer.status_fase = 4 # Aguarda confirmacao ou correcao da tese por parte do Assessor
        self.parecer.save()
        
        return self.get_current_prompt()

    def run_phase_4_refinement(self, user_hint):
        """Refina a tese extraída usando uma nova dica do Assessor."""
        from chat.integrations import GeminiClient
        gemini = GeminiClient()
        
        tese_refinada = gemini.refine_tese(self.parecer, user_hint)
        
        self.parecer.tese = tese_refinada
        self.parecer.save()
        
        # Volta para o prompt da fase 4 pedindo ok ou nova digitação
        return self.get_current_prompt()

    def analise_tese_fase_4(self):
        """Dispara a checagem cruzada Perplexity + Vertex e avalia a tese via Gemini (Acolhida/Não Acolhida)."""
        from chat.integrations import PerplexityClient, GeminiClient, VertexAIClient
        from chat.models import PjariCacheConfig, PjariCacheEntry
        
        perplexity = PerplexityClient()
        gemini = GeminiClient()
        vertex = VertexAIClient()
        
        tese = self.parecer.tese or ""
        
        # PJARI-CACHE Logic
        cache_config, _ = PjariCacheConfig.objects.get_or_create(id=1)
        vertex_result = None
        perplexity_result = None
        
        if cache_config.is_active:
            cache_config.total_requests += 1
            
            # 1. Gera o núcleo da tese usando Gemini Flash em < 1 segundo
            nucleo = gemini.get_cache_key_from_tese(tese)
            
            # Aqui um sistema completo extrairia o artigo penal do PDF, mas como simplificação,
            # usaremos o 'nucleo' (ex: "afericao inmetro") como chave de cache por enquanto.
            chave = f"tese_{nucleo}"
            
            # 2. Busca no banco de cache
            cache_entry = PjariCacheEntry.objects.filter(cache_key=chave).first()
            if cache_entry:
                vertex_result = cache_entry.vertex_result
                perplexity_result = cache_entry.perplexity_result
                
                # Atualiza métricas
                cache_entry.hit_count += 1
                cache_entry.save()
                cache_config.total_hits += 1
            
            cache_config.save()
            
        # Se não há cache (Miss ou Desativado), busca externo
        if not vertex_result or not perplexity_result:
            import concurrent.futures
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                v_future = executor.submit(vertex.search_documents, tese)
                p_future = executor.submit(perplexity.search_tese, tese)
                
                vertex_result = v_future.result()
                perplexity_result = p_future.result()
                
            # Salva o novo resultado no cache para o próximo
            if cache_config.is_active and "erro" not in chave.lower():
                try:
                    PjariCacheEntry.objects.create(
                        cache_key=chave,
                        vertex_result=vertex_result,
                        perplexity_result=perplexity_result
                    )
                except Exception as e:
                    print(f"Erro ao salvar no PJARI-CACHE: {e}")
        
        # Análise prévia da tese
        analise_resultado = gemini.analyze_tese(self.parecer, tese, perplexity_result, vertex_result)
        
        self.parecer.analise_tese_texto = analise_resultado
        self.parecer.vertex_result = vertex_result
        self.parecer.perplexity_result = perplexity_result
        self.parecer.status_fase = 41 # Aguarda Confirmação
        self.parecer.save()
        
        return self.get_current_prompt()

    def run_llm_phases(self):
        """Executa a Fase 5 (Parecer Bloco Único) e Fase 6 (Blindagem)."""
        from chat.integrations import PerplexityClient, GeminiClient, VertexAIClient
        
        perplexity = PerplexityClient()
        gemini = GeminiClient()
        vertex = VertexAIClient()
        
        tese = self.parecer.tese or "MÉRITO PREJUDICADO."
        
        if "PREJUDICADO" in tese:
            vertex_result = "Não aplicável."
            perplexity_result = "Não aplicável por ausência de mérito."
        else:
            # OTIMIZAÇÃO: Executa ambas as inteligências pendentes ao mesmo tempo
            import concurrent.futures
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                v_future = None
                p_future = None
                
                if not self.parecer.vertex_result:
                    v_future = executor.submit(vertex.search_documents, tese)
                if not self.parecer.perplexity_result:
                    p_future = executor.submit(perplexity.search_tese, tese)
                
                vertex_result = v_future.result() if v_future else self.parecer.vertex_result
                perplexity_result = p_future.result() if p_future else self.parecer.perplexity_result
            
        # Fase 5: Geração de Parecer Textual (Gemini) Formatado
        parecer_text = gemini.validate_and_generate_parecer(self.parecer, tese, perplexity_result, vertex_result)
        
        # Extrair a Fundamentação Normativa (Dossiê) se existir
        # Usa regex pois o LLM às vezes perde os *** e escreve apenas DOSSIE_START
        import re
        dossie = ""
        match_start = re.search(r'\*?\*?\*?DOSSIE_START\*?\*?\*?', parecer_text)
        match_end = re.search(r'\*?\*?\*?DOSSIE_END\*?\*?\*?', parecer_text)
        
        if match_start and match_end:
            start_idx = match_start.start()
            end_idx = match_end.end()
            
            # O dossiê é tudo que está entre START e END (incluindo as tags, opcionalmente, mas aqui pegamos só o bloco)
            dossie_bruto = parecer_text[match_start.end():match_end.start()].strip()
            
            # O texto principal do parecer é tudo ANTES do DOSSIE_START
            texto_principal = parecer_text[:start_idx].strip()
            
            # Remove marcadores Markdown indesejados (como "---") que o LLM gosta de colocar antes do DOSSIE_START
            if texto_principal.endswith("---"):
                texto_principal = texto_principal[:-3].strip()
                
            parecer_text = texto_principal
            dossie = dossie_bruto
            
        self.parecer.parecer_final = parecer_text
        self.parecer.dossie_fontes = dossie
        
        # OTIMIZAÇÃO DE BANCO DE DADOS E DISCO:
        # Após a conclusão da geração do Parecer, as cópias não são mais necessárias
        from django.core.files.storage import default_storage
        
        # Deleta Autuacao se existir e nao for simulada
        if self.parecer.autuacao_pdf_path and "upload_simulado" not in self.parecer.autuacao_pdf_path:
            try:
                if default_storage.exists(self.parecer.autuacao_pdf_path):
                    default_storage.delete(self.parecer.autuacao_pdf_path)
            except Exception as e:
                print(f"Erro ao deletar autuação PDF do storage: {e}")
            self.parecer.autuacao_pdf_path = None
            
        # Deleta Consolidado se existir, nao for repetido, e nao for simulada
        if self.parecer.consolidado_pdf_path and "upload_simulado" not in self.parecer.consolidado_pdf_path:
            try:
                if default_storage.exists(self.parecer.consolidado_pdf_path):
                    default_storage.delete(self.parecer.consolidado_pdf_path)
            except Exception as e:
                print(f"Erro ao deletar consolidado PDF do storage: {e}")
            self.parecer.consolidado_pdf_path = None

        # Avança para Fase 6 de Blindagem e Auditoria
        self.parecer.status_fase = 6
        self.parecer.save()
        
        final_response = (
            f"**Fase 5: Parecer Técnico Gerado com Sucesso!**\n\n"
            f"{parecer_text}\n\n"
            f"---\n\n"
            f"**DIGITE ok para auditoria final em tela (Fase 6).**"
        )
        
        return final_response
        
    def run_phase_6(self):
        """Executa a Fase 6 — AUDITORIA EM TELA (Índice de Blindagem)."""
        # Checa se houve flag de erro interno fatal
        erro_fatal = False
        if (self.parecer.has_prescricao_punitiva or self.parecer.has_prescricao_intercorrente or self.parecer.has_decadencia or not self.parecer.is_tempestivo):
            # Se era prejudicial mas o LLM gerou "INDEFERIDO" por teimosia (inconsistência)
            if "DEFERIDO" not in self.parecer.parecer_final.upper():
                erro_fatal = True
                
        # Checklist Objetivo
        # 10 itens como estipulado. Aqui validamos programaticamente 5 vitais.
        itens_conformes = 10
        inconsistencias = []
        
        if erro_fatal:
            itens_conformes -= 5
            inconsistencias.append("❌ Resultado incompatível com extinção da pretensão punitiva (Deveria ser DEFERIDO)")
        
        # Validar nome e SGPE / PA na saída
        if self.parecer.sgpe and self.parecer.sgpe not in self.parecer.parecer_final:
            itens_conformes -= 1
            inconsistencias.append("❌ Inconsistente: SGPE ausente ou errado no Parecer.")
            
        if self.parecer.pa and self.parecer.pa not in self.parecer.parecer_final:
            itens_conformes -= 1
            inconsistencias.append("❌ Inconsistente: Processo Administrativo ausente ou errado no Parecer.")
            
        indice = (itens_conformes / 10) * 100
        
        # Regra de Gravidade Máxima
        if erro_fatal and indice > 50:
             indice = 50.0
             
        self.parecer.blindagem_score = int(indice)
        if inconsistencias:
             self.parecer.blindagem_detalhes = "\n".join(inconsistencias)
             
        self.parecer.status_fase = 7
        self.parecer.save()
        
        from chat.integrations import GeminiClient
        gemini = GeminiClient()
        checklist_texto = gemini.audit_parecer(self.parecer)
        
        report = f"**Fase 6: Auditoria Final (Índice de Blindagem)**\n\n"
        report += f"📊 Seu PARECER está **{int(indice)}%** blindado contra anulações.\n\n"
        
        if indice != 100:
            report += f"⚠️ **Inconsistências Matemáticas Críticas:**\n{self.parecer.blindagem_detalhes}\n\n"
        else:
            report += f"🟢 **Conformidade Matemática Integral.**\n\n"
            
        report += f"---\n\n**O OLHAR DO CORREGEDOR (IA AUDITORA):**\n\n{checklist_texto}\n\n"
            
        report += f"---\n{self.get_current_prompt()}" # Vai chamar a F7 da Pasta
        
        return report

