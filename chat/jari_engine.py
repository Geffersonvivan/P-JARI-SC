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
                return prefix + "7. Por favor, faça o upload dos arquivos **'Autuação' e 'Consolidado'** *(Para simular o upload, digite apenas 'ok')*:"
            
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
        elif fase == 4:
            return "**Fase 4: Pesquisa e Validação**\n\nPor favor, descreva em poucas palavras a **tese principal** de defesa do recorrente:"
        elif fase == 5:
            return "Gerando Parecer Técnico Final... (Aguarde...)"
        elif fase == 6:
            return "Realizando Auditoria de Blindagem... (Aguarde...)"
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
                res += f"🛡️ **Nota de Blindagem:** {self.parecer.nota_blindagem}\n"
            else:
                res += "*(Sem parecer técnico gerado para este processo)*"
            return res
        else:
            return "Processo finalizado ou estado inválido."

    def process_message(self, message: str):
        """Processa a mensagem do usuário e avança a fase se apropriado."""
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
            
        elif fase == 4:
            self.parecer.tese = message.strip()
            self.parecer.save()
            return self.run_llm_phases()

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
        """Executa cálculos da Fase 3 e avança o estado."""
        # Calcula tempestividade e prescrição
        tempestivo = JariMath.check_tempestividade(self.parecer.data_protocolo, self.parecer.prazo_final)
        presc_intercorrente = JariMath.check_prescription_intercorrente(self.parecer.data_protocolo, self.parecer.data_sessao)

        resultado = "**Fase 3: Admissibilidade e Prazos**\n\n"
        if tempestivo:
            resultado += "✅ Tempestivo\n"
        else:
            resultado += "❌ Intempestivo\n"
            
        if presc_intercorrente:
            resultado += "❌ Prescrição Intercorrente Detectada (> 1095 dias)\n"
        else:
            resultado += "✅ Sem Prescrição Intercorrente\n"

        if not tempestivo or presc_intercorrente:
            self.parecer.status_fase = 5 # Pula pra Fase 5 de resultado prejudicado
            self.parecer.tese = "INTEMPESTIVO / PRESCRITO - SEM NECESSIDADE DE ANÁLISE DE MÉRITO."
            self.parecer.save()
            resultado += "\n⚠️ Mérito Prejudicado pela Admissibilidade. Digite **'avançar'** para gerar o Parecer de Indeferimento Imediato."
        else:
            self.parecer.status_fase = 4 # Vai pra busca de teses
            self.parecer.save()
            resultado += "\n✅ Tudo Certo! Avançando.\n\n" + self.get_current_prompt()

        return resultado

    def run_llm_phases(self):
        """Executa as Fases 4, 5 e 6 interagindo com Vertex AI, Perplexity e Gemini."""
        from chat.integrations import PerplexityClient, GeminiClient, VertexAIClient
        
        perplexity = PerplexityClient()
        gemini = GeminiClient()
        vertex = VertexAIClient()
        
        tese = self.parecer.tese or "Intempestividade / Prescrição."
        
        # Fase 4: Busca Externa (Perplexity) e Busca Interna (Vertex)
        perplexity_result = "Não aplicável por ausência de mérito (intempestivo)."
        vertex_result = "Não aplicável por intempestividade."
        if self.parecer.status_fase == 4 or "INTEMPESTIVO" not in tese:
            perplexity_result = perplexity.search_tese(tese)
            vertex_result = vertex.search_documents(tese)
            
        # Fase 5: Geração de Parecer Textual (Gemini)
        parecer_text = gemini.validate_and_generate_parecer(self.parecer, tese, perplexity_result, vertex_result)
        self.parecer.parecer_final = parecer_text
        
        # Fase 6: Auditoria de Blindagem (Gemini)
        blindagem_text = gemini.calculate_blindagem(parecer_text)
        self.parecer.nota_blindagem = blindagem_text
        
        # Avança para Fase 7 de salvar em pasta
        self.parecer.status_fase = 7
        self.parecer.save()
        
        final_response = (
            f"**Fase 5: Parecer Técnico Gerado com Sucesso**\n\n"
            f"{parecer_text}\n\n"
            f"---\n\n"
            f"**Fase 6: Auditoria Externa / Blindagem**\n\n"
            f"🛡️ {blindagem_text}\n\n"
            f"---\n\n"
        )
        
        # Concatena com a pergunta da próxima fase (onde pede a pasta)
        final_response += self.get_current_prompt()
        
        return final_response
