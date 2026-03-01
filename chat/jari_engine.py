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
                f"**Fase 2: Diretriz de Integridade**\n\n"
                f"Confirme se os dados abaixo coincidem **EXATAMENTE** com os documentos originais:\n"
                f"- Data da Sessão: {self.parecer.data_sessao.strftime('%d/%m/%Y') if self.parecer.data_sessao else ''}\n"
                f"- PA: {self.parecer.pa}\n"
                f"- SGPE: {self.parecer.sgpe}\n"
                f"- Prazo Final: {self.parecer.prazo_final.strftime('%d/%m/%Y') if self.parecer.prazo_final else ''}\n"
                f"- Data do Protocolo: {self.parecer.data_protocolo.strftime('%d/%m/%Y') if self.parecer.data_protocolo else ''}\n"
                f"- Páginas da Defesa: {self.parecer.paginas_defesa}\n\n"
                f"Responda apenas com **'ok'** para aprovar, ou **'corrigir'** para voltar à Fase 1."
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
                
            if not self.parecer.data_sessao:
                try:
                    import datetime
                    self.parecer.data_sessao = datetime.datetime.strptime(val, "%d/%m/%Y").date()
                except Exception:
                    return f"❌ Erro ao ler a data. O formato deve ser DD/MM/AAAA. Ex: 15/05/2024. Tente novamente."
            elif not self.parecer.pa:
                self.parecer.pa = val
            elif not self.parecer.sgpe:
                self.parecer.sgpe = val
            elif not self.parecer.prazo_final:
                try:
                    import datetime
                    self.parecer.prazo_final = datetime.datetime.strptime(val, "%d/%m/%Y").date()
                except Exception:
                    return f"❌ Erro ao ler a data. O formato deve ser DD/MM/AAAA. Ex: 15/05/2024. Tente novamente."
            elif not self.parecer.data_protocolo:
                try:
                    import datetime
                    self.parecer.data_protocolo = datetime.datetime.strptime(val, "%d/%m/%Y").date()
                except Exception:
                    return f"❌ Erro ao ler a data. O formato deve ser DD/MM/AAAA. Ex: 15/05/2024. Tente novamente."
            elif not self.parecer.paginas_defesa:
                self.parecer.paginas_defesa = val
            elif not self.parecer.autuacao_pdf_path:
                if uploaded_files and len(uploaded_files) > 0:
                    # Tenta identificar qual é qual pelo nome do arquivo contendo 'consolidado' ou 'autuacao'
                    file_autuacao = uploaded_files[0]
                    file_consolidado = uploaded_files[0]
                    
                    if len(uploaded_files) > 1:
                        f1, f2 = uploaded_files[0], uploaded_files[1]
                        f1_lower = f1.lower()
                        f2_lower = f2.lower()
                        
                        # 1. Tenta identificar pelo nome do consolidado/peticao
                        if any(term in f1_lower for term in ["consolidado", "cons", "defesa", "recurso"]):
                            file_consolidado = f1
                            file_autuacao = f2
                        elif any(term in f2_lower for term in ["consolidado", "cons", "defesa", "recurso"]):
                            file_consolidado = f2
                            file_autuacao = f1
                        # 2. Tenta identificar pelo nome da autuacao/AIT
                        elif any(term in f1_lower for term in ["autua", "ait", "termo"]):
                            file_autuacao = f1
                            file_consolidado = f2
                        elif any(term in f2_lower for term in ["autua", "ait", "termo"]):
                            file_autuacao = f2
                            file_consolidado = f1
                        else:
                            # 3. Fallback inteligente: O Consolidado (Processo inteiro) é sempre muito maior que a Autuação (1 pág).
                            import os
                            size1 = os.path.getsize(f1) if os.path.exists(f1) else 0
                            size2 = os.path.getsize(f2) if os.path.exists(f2) else 0
                            if size1 > size2:
                                file_consolidado = f1
                                file_autuacao = f2
                            else:
                                file_consolidado = f2
                                file_autuacao = f1
                            
                    self.parecer.autuacao_pdf_path = file_autuacao
                    self.parecer.consolidado_pdf_path = file_consolidado
                    
                    self.parecer.status_fase = 2
                    self.parecer.save()
                    return self.get_current_prompt()
                else:
                    # Fallback simulado se não mandou arquivo
                    self.parecer.autuacao_pdf_path = "upload_simulado.pdf"
                    self.parecer.consolidado_pdf_path = "upload_simulado.pdf"
                    self.parecer.status_fase = 2
                    self.parecer.save()
                    return self.get_current_prompt()
            
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
                texto_adm = self.parecer.admissibilidade_texto or ""
                texto_adm_lower = texto_adm.lower()
                
                import re
                # Busca padronizada pelas conclusões negativas geradas pelo LLM ou termos definitivos
                is_prejudicado = bool(re.search(r'conclusão\s*:\s*(intempestivo|prescrito|decadência|decadente)', texto_adm_lower))
                
                # Fallback: outras expressões definitivas que o LLM pode usar
                if not is_prejudicado:
                    for term in ["ocorrência de prescrição", "reconhece-se a prescrição", "ocorrência de decadência", "recurso intempestivo"]:
                        if term in texto_adm_lower and "não " + term not in texto_adm_lower:
                            is_prejudicado = True
                            break

                if is_prejudicado:
                    self.parecer.status_fase = 5 # Pula pra Fase 5 de resultado prejudicado, não analisa mérito
                    self.parecer.tese = "MÉRITO PREJUDICADO (INTEMPESTIVIDADE, PRESCRIÇÃO OU DECADÊNCIA)."
                    self.parecer.save()
                    return "\n⚠️ Mérito Prejudicado. A inteligência constatou Intempestividade, Prescrição ou Decadência. O Parecer Final será gerado agora sem análise das teses de defesa.\n" + self.run_llm_phases()
                else:
                    return self.run_phase_4_extraction()
            else:
                return "Responda 'ok' para prosseguir. Em caso de divergência real, recomece ou modifique manualmente depois."

        elif fase == 4:
            if message.lower().strip() != 'ok':
                return self.run_phase_4_refinement(message.strip())
            return self.analise_tese_fase_4()
            
        elif fase == 41:
            if message.lower().strip() == 'ok':
                self.parecer.status_fase = 5
                self.parecer.save()
                return self.run_llm_phases()
            else:
                return "Responda 'ok' para prosseguir."

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

    def run_phase_3(self):
        """Executa cálculos manuais extras se necessário, mas hoje delega pro LLM montar a Tabela P1."""
        from chat.integrations import GeminiClient
        gemini = GeminiClient()
        
        texto_admissibilidade = gemini.generate_admissibility_report(self.parecer)
        
        self.parecer.admissibilidade_texto = texto_admissibilidade
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
        
        perplexity = PerplexityClient()
        gemini = GeminiClient()
        vertex = VertexAIClient()
        
        tese = self.parecer.tese or ""
        
        vertex_result = vertex.search_documents(tese)
        perplexity_result = perplexity.search_tese(tese)
        
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
        
        # Pode reaproveitar a busca ou rodar de novo (por simplicidade do LLM, deixamos simular ou repetir)
        if "PREJUDICADO" in tese:
            vertex_result = "Não aplicável."
            perplexity_result = "Não aplicável por ausência de mérito."
        else:
            vertex_result = self.parecer.vertex_result or vertex.search_documents(tese)
            perplexity_result = self.parecer.perplexity_result or perplexity.search_tese(tese)
            
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
        # Após a conclusão da geração do Parecer, os arquivos não são mais necessários
        import os
        
        # Deleta Autuacao se existir e nao for simulada
        if self.parecer.autuacao_pdf_path and "upload_simulado" not in self.parecer.autuacao_pdf_path:
            if os.path.exists(self.parecer.autuacao_pdf_path):
                try:
                    os.remove(self.parecer.autuacao_pdf_path)
                except Exception as e:
                    print(f"Erro ao deletar autuação PDF: {e}")
            self.parecer.autuacao_pdf_path = None
            
        # Deleta Consolidado se existir, nao for repetido, e nao for simulada
        if self.parecer.consolidado_pdf_path and "upload_simulado" not in self.parecer.consolidado_pdf_path:
            if os.path.exists(self.parecer.consolidado_pdf_path):
                try:
                    os.remove(self.parecer.consolidado_pdf_path)
                except Exception as e:
                    print(f"Erro ao deletar consolidado PDF: {e}")
            self.parecer.consolidado_pdf_path = None

        # Avança para Fase 7 de salvar em pasta
        self.parecer.status_fase = 7
        self.parecer.save()
        
        final_response = (
            f"**Fase 5: Parecer Técnico Gerado com Sucesso!**\n\n"
            f"{parecer_text}\n\n"
            f"---\n\n"
        )
        
        # Concatena com a pergunta da próxima fase (onde pede a pasta)
        final_response += self.get_current_prompt()
        
        return final_response

