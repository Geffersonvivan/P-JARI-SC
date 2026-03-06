import os
import requests
from google import genai
from google.cloud import discoveryengine_v1 as discoveryengine

class PerplexityClient:
    def __init__(self):
        self.api_key = os.environ.get('PERPLEXITY_API_KEY')
        self.url = "https://api.perplexity.ai/chat/completions"

    def search_tese(self, tese):
        if not self.api_key:
            return "Simulação (Perplexity): Tese pesquisada. A tese é favorável segundo jurisprudência recente (REsp 123.456)."
            
        payload = {
            "model": "sonar-pro",
            "messages": [
                {
                    "role": "system",
                    "content": "Você é um assessor jurídico especialista no JARI de Santa Catarina. Sua pesquisa deve obrigatoriamente priorizar sites com domínios .gov.br ou .sc.gov.br. Relacione apenas resoluções do CONTRAN, CETRAN-SC, MBFT e CTB aplicáveis ao caso. Para toda lei citada, pesquise o LINK OFICIAL DA WEB dela e devolva no formato Markdown clicável, ex: [Código de Trânsito Brasileiro, Art. 12](http://www.planalto.gov.br/...)"
                },
                {
                    "role": "user",
                    "content": f"Pesquise jurisprudência oficial aplicável e a validade normativa da seguinte tese de defesa: {tese}"
                }
            ]
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(self.url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Erro ao acessar Perplexity: {str(e)}.\nSimulação ativada: Jurisprudência encontrada favorável a tese."

class GeminiClient:
    def __init__(self):
        self.api_key = os.environ.get('GEMINI_API_KEY')
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def upload_file(self, file_path):
        if not self.client or not file_path:
            return None
            
        import tempfile
        from django.core.files.storage import default_storage
        
        # If it's a simulated or local absolute path bypassing Storage
        if isinstance(file_path, str) and "upload_simulado" in file_path:
            return None
            
        try:
            # Baixa do Google Cloud Storage ou do disco local via Django Storage para um arquivo temporário
            with default_storage.open(file_path, 'rb') as f_in:
                # O Gemini precisa de um caminho físico em disco, então criamos um temp local
                fd, temp_path = tempfile.mkstemp(suffix=".pdf")
                with os.fdopen(fd, 'wb') as f_out:
                    f_out.write(f_in.read())
            
            # Faz o upload físico pro ecossistema do Gemini
            gemini_file = self.client.files.upload(file=temp_path)
            
            # Limpa o arquivo temporário local agora que o Gemini já comeu
            os.remove(temp_path)
            
            return gemini_file
        except Exception as e:
            print(f"Erro ao subir arquivo pro Gemini a partir do Storage: {e}")
            return None

    def generate_phase2_report(self, parecer_obj, contexto_textual_datas):
        if not self.client:
             return "Simulação: Admissibilidade checada. Tempestivo. Prescrições Afastadas."
             
        system_instruction = (
            "SYSTEM P-JARI - FASE 2 (DIR - INTEGRIDADE/REGULARIDADE)\n"
            "Sua função é organizar as datas essenciais do processo, garantindo base objetiva para análise de prazos na Fase 3.\n\n"
            "REGRAS DE CLASSIFICAÇÃO:\n"
            "1. Utilize o Bloco A (Informado pelo Julgador) SEMPRE, ainda que não haja documento equivalente.\n"
            "2. Utilize o Bloco B (Extraído do PDF via Python em anexo).\n"
            "3. Se houver mais de uma data para o mesmo evento, liste TODAS numerando como POSSÍVEL (1), (2), sem escolher 'a verdadeira'.\n"
            "4. Se não encontrar um tipo essencial (Ex: Notificação, Julgamento), escreva 'NÃO LOCALIZADO - [tipo]'.\n"
            "5. NUNCA declare 'erro', 'nulidade' ou 'conflito' na Fase 2, apenas anote na observação 'Divergente; julgador deve avaliar na Fase 3'.\n\n"
            "SAÍDA OBRIGATÓRIA (Use estritamente Markdown tables válidas com `|`):\n"
            "A saída deve começar com a frase: 'Varredura confirmada. Nenhuma nova data localizada além das já listadas.'\n\n"
            "#### 1. Linha do Tempo Mínima\n"
            "| Data | Tipo | Descritivo | Origem | Observações |\n"
            "|---|---|---|---|---|\n"
            "| DD/MM/AAAA | [TIPO] | [Descritivo] | [Doc/Pág] ou [Pergunta] | [Ex: Confirmado, POSSÍVEL (1), NÃO LOCALIZADO] |\n\n"
            "#### 2. Tabela de Datas Sensíveis para Prazos\n"
            "| Tipo | Data | Descritivo | Origem | Observações |\n"
            "|---|---|---|---|---|\n"
            "| [TIPO ÚNICO] | DD/MM/AAAA | [Descritivo] | [Doc/Pág] | [Alertas/OK] |\n\n"
            "#### 3. Alertas para a Fase 3\n"
            "Liste em bullets os tipos de datas NÃO LOCALIZADAS, Múltiplas Versões, ou Divergências visíveis.\n\n"
            "Escreva a documentação descritiva de forma fria e neutra."
        )
        
        prompt_text = (
            f"=== BLOCO A (EXTERNO - Informações da Fase 1) ===\n"
            f"1. Sessão JARI: {parecer_obj.data_sessao or 'NÃO INFORMADO'}\n"
            f"2. PA: {parecer_obj.pa}\n"
            f"3. SGPE: {parecer_obj.sgpe}\n"
            f"4. Prazo Final Recurso: {parecer_obj.prazo_final or 'NÃO INFORMADO'}\n"
            f"5. Protocolo Recurso: {parecer_obj.data_protocolo or 'NÃO INFORMADO'}\n\n"
            f"=== BLOCO B (Extração Bruta dos Documentos via Python) ===\n"
            f"{contexto_textual_datas}\n\n"
            "Cruze as origens. Dê prioridade a não omitir nada. Monte a Linha do Tempo, a Tabela de Datas Sensíveis e os Alertas."
        )
        
        contents = [prompt_text]
        
        # Anexar os PDFs no prompt se existirem para referências contextuais mais finas que a regex possa ter perdido
        from django.core.files.storage import default_storage
        
        if parecer_obj.autuacao_pdf_path and "upload_simulado" not in parecer_obj.autuacao_pdf_path:
            try:
                if default_storage.exists(parecer_obj.autuacao_pdf_path):
                    file_autuacao = self.upload_file(parecer_obj.autuacao_pdf_path)
                    if file_autuacao:
                        contents.insert(0, file_autuacao)
            except Exception: pass
                
        if parecer_obj.consolidado_pdf_path and "upload_simulado" not in parecer_obj.consolidado_pdf_path:
            try:
                if default_storage.exists(parecer_obj.consolidado_pdf_path):
                    pass # Já anexamos um ou é o msmo arquivo para poupar token se o extrator pegou. No entanto, o Gemini 1.5 PRO guenta.
                    if parecer_obj.autuacao_pdf_path != parecer_obj.consolidado_pdf_path:
                        file_consolidado = self.upload_file(parecer_obj.consolidado_pdf_path)
                        if file_consolidado:
                            contents.insert(0, file_consolidado)
            except Exception: pass

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-pro',
                contents=contents,
                config={'system_instruction': system_instruction}
            )
            return response.text
        except Exception as e:
            return f"Erro ao acessar Gemini na Fase 2: {str(e)}.\n"

    def extract_tese(self, parecer_obj):
        if not self.client:
             return "Simulação: O recorrente alega a não aferição do radar pelo INMETRO."
             
        system_instruction = (
            "Você é o Assessor Jurídico P-JARI/SC. Sua tarefa é ler EXCLUSIVAMENTE a Defesa "
            "Recursal indicada nas páginas. Siga a regra FASE 4 - EXTRAÇÃO DE TESES:\n"
            "a) Identificar cada tese explicitamente apresentada, sem inferência.\n"
            "b) Listar as teses separadamente (não agrupar).\n"
            "c) Se a tese não tiver fundo jurídico (emoção, 'peço compreensão', etc.), classifique-a expressamente como 'Tese não jurídica' e trate como 'não acolhida por ausência de fundamento normativo'.\n"
            "d) Proibido: Criar tese não alegada, presumir argumento implícito, completar lacuna defensiva."
        )
        
        prompt_text = (
            f"Localize a defesa nas páginas indicadas: {parecer_obj.paginas_defesa}.\n\n"
            "Liste AS TESES jurídicas apresentadas de forma isolada e em tópicos (bullet points). "
            "Apenas descreva o que foi pedido, detalhando cada ponto separadamente. Reforçando: não gere respostas, julgamentos ou mérito agora, apenas a LISTAGEM e classificação das teses alegadas no Recurso."
        )
        
        contents = [prompt_text]
        
        if parecer_obj.autuacao_pdf_path and "upload_simulado" not in parecer_obj.autuacao_pdf_path:
            file_autuacao = self.upload_file(parecer_obj.autuacao_pdf_path)
            if file_autuacao:
                contents.insert(0, file_autuacao)
                
        if parecer_obj.consolidado_pdf_path and "upload_simulado" not in parecer_obj.consolidado_pdf_path and parecer_obj.consolidado_pdf_path != parecer_obj.autuacao_pdf_path:
            file_consolidado = self.upload_file(parecer_obj.consolidado_pdf_path)
            if file_consolidado:
                contents.insert(0, file_consolidado)

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config={'system_instruction': system_instruction}
            )
            return response.text.strip()
        except Exception as e:
            return f"Erro ao extrair tese via LLM: {str(e)}"

    def refine_tese(self, parecer_obj, user_hint):
        if not self.client:
             return f"Simulação de Refinamento: O recorrente alega que {user_hint}."
             
        system_instruction = (
            "Você é o Assessor P-JARI/SC. O usuário forneceu uma dica/diretriz sobre a real "
            "tese de defesa do recorrente. Leia o documento anexo nas páginas indicadas e extraia "
            "um novo resumo da tese guiando-se estritamente pela diretriz do usuário."
        )
        
        prompt_text = (
            f"Por favor, releia a defesa do recorrente nas páginas: {parecer_obj.paginas_defesa}.\n\n"
            f"O assessor revisor apontou o seguinte: '{user_hint}'.\n\n"
            "Com base nessa instrução, escreva um NOVO resumo claro e direto informando as alegações da defesa."
        )
        
        contents = [prompt_text]
        
        if parecer_obj.autuacao_pdf_path and "upload_simulado" not in parecer_obj.autuacao_pdf_path:
            file_autuacao = self.upload_file(parecer_obj.autuacao_pdf_path)
            if file_autuacao:
                contents.insert(0, file_autuacao)
                
        if parecer_obj.consolidado_pdf_path and "upload_simulado" not in parecer_obj.consolidado_pdf_path and parecer_obj.consolidado_pdf_path != parecer_obj.autuacao_pdf_path:
            file_consolidado = self.upload_file(parecer_obj.consolidado_pdf_path)
            if file_consolidado:
                contents.insert(0, file_consolidado)

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config={'system_instruction': system_instruction}
            )
            return response.text.strip()
        except Exception as e:
            return f"Erro ao refinar tese via LLM: {str(e)}"

    def get_cache_key_from_tese(self, tese):
        """Usa o Gemini Flash para extrair o núcleo da tese em até 3 palavras."""
        if not self.client:
            return "simulacao"
            
        system_instruction = (
            "Sua única tarefa é extrair a palavra-chave central ou o 'núcleo' do argumento jurídico abaixo. "
            "Retorne APENAS essa palavra-chave (máximo 3 palavras). Sem pontos, sem explicações. "
            "Exemplos de saída: 'Aferição Inmetro', 'Sinalização R-19', 'Nulidade Citação', 'Mérito Prejudicado'."
        )
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[tese],
                config={'system_instruction': system_instruction, 'temperature': 0.1}
            )
            # Limpa qualquer formatação extra e converte para minúsculo para padronizar a chave
            key = response.text.strip().lower().replace('"', '').replace("'", "")
            return key
        except Exception as e:
            print(f"Erro ao gerar cache key: {e}")
            return "erro_chave"

    def analyze_tese(self, parecer_obj, tese, perplexity_result, vertex_result):
        # Verifica Prejudicialidade Externa (Prescrição, Decadência, Intempestividade)
        is_prejudicado = (
            parecer_obj.has_prescricao_punitiva or
            parecer_obj.has_prescricao_intercorrente or
            parecer_obj.has_decadencia or
            parecer_obj.is_tempestivo is False
        )
        if is_prejudicado:
            return "Teses defensivas prejudicadas em razão da extinção da pretensão punitiva ou inadmissibilidade recursal."
            
        if not self.client:
             return "Simulação: Resultar em: Conclusão: acolhida/não acolhida. (acolhida)"
             
        system_instruction = (
            "Você é o Assessor P-JARI/SC (Fase 4 Avançada). As regras OBRIGATÓRIAS SÃO:\n"
            "1. Para cada tese apresentada, transcreva uma síntese objetiva da alegação.\n"
            "2. PRESUNÇÃO DE LEGITIMIDADE DOS ATOS ADMINISTRATIVOS: Na dúvida, prevalece o relato do agente de trânsito e documentos oficiais (AIT, notificações, portarias). Contudo, SEMPRE VERIFIQUE:\n"
            "   (a) Falhas formais graves visíveis nos autos (AIT em branco, falta de laudos obrigatórios). Ex: acolhimento contra Inmetro depende de prova *robusta* ou erro material grave do agente.\n"
            "   (b) Se a defesa anexou prova documental *concreta e idônea* (fotos evidentes, vídeos, certidões).\n"
            "3. Confronto com as Provas (para cada tese):\n"
            "   - Se não houver prova cabal em contrário nem falha formal: registrar que prevalece o relato do agente (documentação oficial).\n"
            "   - Se houver prova idônea ou falha formal: justificar o acolhimento da tese, sobrepujando a presunção.\n"
            "4. Só classifique 'não acolhida por falta de prova' após constatar que *não há qualquer documento robusto que a sustente* e *os autos não revelam falha formal*.\n"
            "5. FUNDAMENTAÇÃO E RAG: Fundamente o mérito de forma robusta e cite a hierarquia normativa exclusivamente baseada no 'RAG Inventário Normativo', usando Perplexity apenas subsidiariamente. NÃO CRIE NORMAS INEXISTENTES.\n"
            "6. PROIBIÇÕES ABSOLUTAS: Não crie tese não alegada, não presuma argumento, não complete lacuna defensiva, e **não agrupe teses distintas**.\n"
            "7. Ao final de CADA TESE analisada, você deve OBRIGATORIAMENTE escrever e pular de linha:\n"
            "   'Conclusão: Acolhida.'\n"
            "   ou\n"
            "   'Conclusão: Não acolhida.'\n"
        )
        
        prompt_text = (
            f"Processo: {parecer_obj.pa} | SGPE: {parecer_obj.sgpe}\n"
            f"Teses Listadas: {tese}\n\n"
            f"Documentos Anexos: Documento 'consolidado' + 'autuação'\n\n"
            f"RAG Inventário Normativo Google (VERTEX): {vertex_result}\n"
            f"Pesquisa Auxiliar (PERPLEXITY): {perplexity_result}\n\n"
            "Prossiga com a Análise das Teses isoladamente. Aplique a REGRA DA PRESUNÇÃO DE LEGITIMIDADE avaliando se há provas/falhas formais no AIT. Termine obrigatoriamente a fundamentação de cada tese com 'Conclusão: Acolhida.' ou 'Conclusão: Não acolhida.'. Ao final de tudo o julgamento do mérito, pule algumas linhas e escreva a exata string:\n\n"
            "Confirme 'ok' ou indique divergência."
        )
        
        contents = [prompt_text]
        
        # Anexar os PDFs no prompt se existirem
        from django.core.files.storage import default_storage
        if parecer_obj.autuacao_pdf_path and "upload_simulado" not in parecer_obj.autuacao_pdf_path:
            if default_storage.exists(parecer_obj.autuacao_pdf_path):
                file_autuacao = self.upload_file(parecer_obj.autuacao_pdf_path)
                if file_autuacao:
                    contents.insert(0, file_autuacao)
                
        if parecer_obj.consolidado_pdf_path and "upload_simulado" not in parecer_obj.consolidado_pdf_path:
            if default_storage.exists(parecer_obj.consolidado_pdf_path):
                file_consolidado = self.upload_file(parecer_obj.consolidado_pdf_path)
                if file_consolidado:
                    contents.insert(0, file_consolidado)

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-pro', # Modelo 2.5 PRO para máxima análise de mérito (Rigidez absoluta)
                contents=contents,
                config={'system_instruction': system_instruction}
            )
            return response.text
        except Exception as e:
            return f"Erro ao acessar Gemini na Fase 4: {str(e)}.\n"

    def validate_and_generate_parecer(self, parecer_obj, tese, perplexity_result, vertex_result=""):
        relator_name = "NÃO INFORMADO"
        if parecer_obj.user:
            relator_name = f"{parecer_obj.user.first_name} {parecer_obj.user.last_name}".strip()
            if not relator_name:
                relator_name = parecer_obj.user.username
        relator_name = relator_name.upper()

        status_deferimento = "DEFERIDO" if "PREJUDICADO" in tese else "INDEFERIDO/DEFERIDO"
        if not self.client:
            return f"**RESULTADO SIMULADO:** {status_deferimento}"
            
        system_instruction = (
            "Você é o Assessor P-JARI/SC (Fase 5 - PARECER PROTOCOLO DEFINITIVO).\n"
            "REGRAS DE OURO (IMUTÁVEIS):\n"
            "1. NÃO INOVE: Não crie tese, não crie fato, não crie fundamento probatório não comprovado. Seja 100% restrito ao RAG e aos relatórios recebidos.\n"
            "2. CITAÇÃO NORMATIVA: Baseie-se expressamente nas normas fornecidas.\n"
            "3. PROSA FLUIDA: Redija em parágrafos contínuos, com a coesão lapidar de um Juiz. Converta dados numéricos em explicações naturais (Ex: 'O intervalo foi de X dias, não superando o prazo legal'). Evite letreiros engessados e subtópicos em demasia na argumentação.\n"
            "4. SINTAXE PROIBIDA: Texto sem emojis, sem comandos sistêmicos ou que revelem sua natureza de IA.\n"
            "5. COMPATIBILIDADE LEAL: Se a Admissibilidade ditar Prescrição/Decadência, o Resultado Obrigatório deve ser DEFERIDO, "
            "e a seção de Teses Defensivas conter exclusivamente a declaração de prejudicialidade. Se Intempestivo sem extinção, INDEFERIDO.\n\n"
            "GERAR O PARECER SEGUINDO ESTA ESTRUTURA DIRETA:\n\n"
            "PARECER JARI\n"
            "PROCESSO: [PA]\n"
            "SGPE: [SGPE]\n"
            "RECORRENTE: [Nome - Documento Autuação]\n"
            f"RELATOR: {relator_name}\n"
            "DATA SESSÃO: [DD/MM/AAAA]\n"
            "RESULTADO: [DEFERIDO ou INDEFERIDO]\n\n"
            "EMENTA\n"
            "Texto em maiúsculo, objetivo, contendo: infração + tese(s) + admissibilidade + prescrição/decadência + resultado.\n\n"
            "RELATÓRIO\n"
            "Narre a gênese do processo baseando-se no Resumo Geral (fato, local e o ato de interposição recursal). Este é o relatório.\n\n"
            "FUNDAMENTAÇÃO JURÍDICA\n"
            "ADMISSIBILIDADE\n"
            "Tempestividade concluída em texto discursivo com explicação normativa.\n"
            "PRESCRIÇÃO E DECADÊNCIA\n"
            "Justifique com clareza em texto coeso, agrupando os prazos computados pelo motor matemático (punitiva, intercorrente e decadência).\n"
            "TESES DEFENSIVAS\n"
            "Se prejudicadas pela extinção punitiva, declare a prejudicialidade. Se vivas, afaste-as ou acolha-as demonstrando choque normativo de forma direta e incisiva, sem subtítulos excessivos para cada uma.\n"
            "MATERIALIDADE E GARANTIAS PROCESSUAIS\n"
            "Desfecho das garantias de defesa.\n\n"
            "Esta é a fundamentação.\n\n"
            "***DOSSIE_START***\n"
            "[Cite apenas as leis e fundamentos em bullets (Exemplo: * [Constituição Federal](https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm) ) pesquisando sempre que possível o link na WEB para a lei no formato Markdown padrão.]\n"
            "***DOSSIE_END***"
        )
        
        prompt = (
            f"---- RESUMO GERAL DO FATO (FASE 2) ----\n"
            f"{getattr(parecer_obj, 'tabela_datas_sensiveis', '') or 'Vazio.'}\n\n"
            f"---- MATEMÁTICA TEMPORAL E ADMISSIBILIDADE (FASE 3) ----\n"
            f"{parecer_obj.admissibilidade_texto}\n\n"
            f"---- CONCLUSÃO DAS TESES (FASE 4) ----\n"
            f"{parecer_obj.analise_tese_texto}\n"
            f"Tese(s): {tese}\n\n"
            f"DADOS DE CABEÇALHO:\n"
            f"PA: {parecer_obj.pa}\n"
            f"SGPE: {parecer_obj.sgpe}\n"
            f"Recorrente: {parecer_obj.recorrente}\n"
            f"Data Sessão: {parecer_obj.data_sessao}\n\n"
            f"INVENTÁRIO NORMATIVO: {vertex_result}\n\n"
            f"JURISPRUDÊNCIA SUBSIDIÁRIA: {perplexity_result}\n\n"
            f"Crie o Parecer englobando as seções listadas, transformando a carga calculada numa obra narrativa fluida de Magistrado."
        )

        contents = [prompt]
        
        # Anexar os PDFs no prompt se existirem para que a IA possa extrair "Interessado" da Autuação
        from django.core.files.storage import default_storage
        
        if parecer_obj.autuacao_pdf_path and "upload_simulado" not in parecer_obj.autuacao_pdf_path:
            try:
                if default_storage.exists(parecer_obj.autuacao_pdf_path):
                    file_autuacao = self.upload_file(parecer_obj.autuacao_pdf_path)
                    if file_autuacao:
                        contents.insert(0, file_autuacao)
            except Exception: pass
                
        if parecer_obj.consolidado_pdf_path and "upload_simulado" not in parecer_obj.consolidado_pdf_path and parecer_obj.consolidado_pdf_path != parecer_obj.autuacao_pdf_path:
            try:
                if default_storage.exists(parecer_obj.consolidado_pdf_path):
                    file_consolidado = self.upload_file(parecer_obj.consolidado_pdf_path)
                    if file_consolidado:
                        contents.insert(0, file_consolidado)
            except Exception: pass

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config={'system_instruction': system_instruction}
            )
            return response.text
        except Exception as e:
            return f"Erro ao acessar Gemini: {str(e)}.\nFalha ao gerar parecer via LLM."

    def audit_parecer(self, parecer_obj):
        if not self.client:
            return "✅ Simulação: Conformidade integral. (Score calculado pelo JariMath)"
            
        system_instruction = (
            "Você é o Auditor Corregedor do P-JARI/SC (Fase 6 - AUDITORIA).\n"
            "Sua única função é realizar um checklist sobre o Parecer Final submetido, cruzando a compatibilidade narrativa do Relator com a tabela matemática anterior.\n\n"
            "Classifique de forma estrita cada um dos blocos abaixo como '✅ Conforme' ou '❌ Inconsistente' seguido de uma breve linha de justificativa:\n"
            "1. Identificação processual (PA, SGPE, Nome)\n"
            "2. Conformidade das datas (infração, julgamento)\n"
            "3. Tempestividade narrativa\n"
            "4. Prescrição punitiva aplicada\n"
            "5. Prescrição intercorrente\n"
            "6. Decadência\n"
            "7. Análise correta das teses (Se cabível)\n"
            "8. Compatibilidade lógica entre fundamentação e RESULTADO (Criticamente importante)\n"
            "9. Citação normativa presente\n"
            "10. Ausência de inovação (Sem invencionices textuais)\n"
        )
        
        prompt = (
            f"--- MATEMÁTICA OBRIGATÓRIA (Soberania Python) ---\n"
            f"Tempestivo: {'SIM' if parecer_obj.is_tempestivo else 'NÃO'}\n"
            f"Prescrição Punitiva: {'SIM' if parecer_obj.has_prescricao_punitiva else 'NÃO'}\n"
            f"Intercorrente: {'SIM' if parecer_obj.has_prescricao_intercorrente else 'NÃO'}\n"
            f"Decadência: {'SIM' if parecer_obj.has_decadencia else 'NÃO'}\n\n"
            f"--- PARECER REDIGIDO PELA FASE 5 (O ALVO DA AUDITORIA) ---\n"
            f"{parecer_obj.parecer_final}\n\n"
            f"Execute o Checklist e devolva APENAS as 10 linhas avaliadas."
        )

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[prompt],
                config={'system_instruction': system_instruction, 'temperature': 0.1}
            )
            return response.text
        except Exception as e:
            return f"⚠️ Auditoria Qualitativa offline. Resultado puramente matemático operando."

class VertexAIClient:
    def __init__(self):
        self.project_id = os.environ.get('VERTEX_PROJECT_ID')
        self.location = os.environ.get('VERTEX_LOCATION', 'global')
        self.data_store_id = os.environ.get('VERTEX_DATA_STORE_ID')

    def search_documents(self, query, top_k=5):
        if not self.project_id or not self.data_store_id:
            return "Simulação (Vertex AI): Motor de busca interno não configurado. Adicione os IDs no .env."

        try:
            client = discoveryengine.SearchServiceClient()
            serving_config = client.serving_config_path(
                project=self.project_id,
                location=self.location,
                data_store=self.data_store_id,
                serving_config="default_config",
            )
            
            request = discoveryengine.SearchRequest(
                serving_config=serving_config,
                query=query,
                page_size=top_k,
            )
            
            response = client.search(request)
            
            resultados = []
            for result in response.results:
                document_data = result.document.derived_struct_data
                trechos = document_data.get("extractive_answers", [])
                if trechos:
                     resultados.append(trechos[0].get("content", ""))
                     
            if not resultados:
                return "Nenhum documento interno encontrado para esta busca."
                
            return "\n\n---\n\n".join(resultados)
        except Exception as e:
            return f"Erro ao buscar no Vertex AI: {str(e)}"
