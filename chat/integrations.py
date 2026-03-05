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

    def generate_admissibility_report(self, parecer_obj):
        if not self.client:
             return "Simulação: Admissibilidade checada. Tempestivo. Prescrições Afastadas."
             
        system_instruction = (
            "Você é o Assessor P-JARI/SC. Analise os documentos fornecidos ('Autuação' e 'Consolidado') "
            "e retorne OBRIGATORIAMENTE um Resumo Geral documentado com base nestas REGRAS DE OURO:\n"
            "1. Liste TODAS as datas identificáveis nos formatos usuais (DD/MM/AAAA, etc) em Ordem Cronológica.\n"
            "2. NÃO invente datas ausentes e NÃO complete lacunas.\n"
            "3. Se falhar em achar uma fase essencial (Notificação, Julgamento), escreva na linha: 'NÃO LOCALIZADO - [nome da fase]'.\n"
            "4. Se houver mais de uma data para um evento, crie múltiplas linhas de tabela alertando 'POSSÍVEL Data (1)', 'POSSÍVEL Data (2)'.\n"
            "5. A sua resposta DEVE conter DUAS partes principais formatadas ESTRITAMENTE como TABELAS (com barras verticais e separadores `|---|---|`):\n\n"
            "--- RESUMO GERAL DO PROCESSO ---\n"
            "| Data | Evento Histórico e Localização |\n"
            "|---|---|\n"
            "| [Data] | [Descritivo Cronológico] ([Doc/Pág]) |\n\n"
            "--- TABELA DE DATAS SENSÍVEIS ---\n"
            "| Data | Tipo de Data e Informação |\n"
            "|---|---|\n"
            "| [Data] | [Tipo de data] - [Descritivo] ([Doc/Pág]) |\n"
            "NOTA: As duas listagens acima DEVEM nascer como Tabelas Markdowns válidas. Não produza listas em texto puro."
        )
        
        prompt_text = (
            f"Fase 1 Input:\n"
            f"1. Sessão: {parecer_obj.data_sessao}\n"
            f"2. PA: {parecer_obj.pa}\n"
            f"3. SGPE: {parecer_obj.sgpe}\n"
            f"4. Prazo Final: {parecer_obj.prazo_final}\n"
            f"5. Protocolo: {parecer_obj.data_protocolo}\n\n"
            "Leia os PDFs em anexo com urgência. Escreva EXATAMENTE 'Varredura confirmada. Nenhuma nova data localizada além das já listadas.' "
            "Exiba a Linha do Tempo cronológica e a Tabela de Datas Sensíveis. "
            "Não aplique sentenças jurídicas de prescrição, apenas EXTRAIA as datas brutas exatas dos documentos."
        )
        
        contents = [prompt_text]
        
        # Anexar os PDFs no prompt se existirem
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
                    file_consolidado = self.upload_file(parecer_obj.consolidado_pdf_path)
                    if file_consolidado:
                        contents.insert(0, file_consolidado)
            except Exception: pass

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash', # Mudado de PRO para FLASH para otimização radical de tempo na web
                contents=contents,
                config={'system_instruction': system_instruction}
            )
            return response.text
        except Exception as e:
            return f"Erro ao acessar Gemini na Fase 3: {str(e)}.\n"

    def extract_tese(self, parecer_obj):
        if not self.client:
             return "Simulação: O recorrente alega a não aferição do radar pelo INMETRO."
             
        system_instruction = (
            "Você é o Assessor Jurídico P-JARI/SC. Sua tarefa é ler EXCLUSIVAMENTE a Defesa "
            "Recursal indicada nas páginas. Siga a regra FASE 4 - TESES:\n"
            "1. Identifique cada tese explicitamente apresentada sem inferência.\n"
            "2. Liste as teses separadamente (não agrupe).\n"
            "3. Proibido: Criar tese não alegada, presumir argumento implícito, completar lacuna.\n"
            "4. Se a tese não tiver fundo jurídico (emoção, apelo pessoal), classifique-a expressamente como 'Tese não jurídica'."
        )
        
        prompt_text = (
            f"Localize a defesa nas páginas indicadas: {parecer_obj.paginas_defesa}.\n\n"
            "Liste AS TESES jurídicas apresentadas de forma isolada e em tópicos (bullet points). "
            "Apenas descreva o que foi pedido. Reforçando: não gere respostas, julgamentos ou mérito agora, apenas a LISTAGEM e classificação das teses alegadas no Recurso."
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
        if not self.client:
             return "Simulação: Resultar em: Conclusão: acolhida/não acolhida. (acolhida)"
             
        system_instruction = (
            "Você é o Assessor P-JARI/SC (Fase 4 Avançada). As regras OBRIGATÓRIAS SÃO:\n"
            "1. Para cada tese extraída, você transcreverá uma síntese.\n"
            "2. Confrontará a alegação com a prova nos autos (Auto de Infração e Documentos PDF).\n"
            "3. Fundamentará com a norma (Inventário Normativo/Jurisprudência).\n"
            "4. Se a tese for 'não jurídica' (ex: apelo emocional), retorne 'Não acolhida por ausência de fundamento normativo'.\n"
            "5. Ao final de cada tese, decrete OBRIGATORIAMENTE uma das duas literais strings: 'Conclusão: Acolhida.' ou 'Conclusão: Não acolhida.'\n"
            "Jamais use outras palavras como 'negada', 'procedente', etc."
        )
        
        prompt_text = (
            f"Processo: {parecer_obj.pa} | SGPE: {parecer_obj.sgpe}\n"
            f"Teses Listadas: {tese}\n\n"
            f"Inventário Normativo RAG (VERTEX): {vertex_result}\n"
            f"Jurisprudência (PERPLEXITY): {perplexity_result}\n\n"
            "Prossiga com a Análise das Teses confrontando a documentação, usando EXCLUSIVAMENTE o "
            "inventário normativo ou perplexity. Para cada tese julgada, inclua 'Conclusão: Acolhida.' "
            "ou 'Conclusão: Não acolhida.' ao final."
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
                model='gemini-2.5-flash', # Mudado de PRO para FLASH para agilidade na análise das provas
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
            "1. NÃO INOVE: Não crie tese, não crie fato, não crie fundamento (Seja 100% restrito ao RAG e PDFs).\n"
            "2. DEVERÁ citar expressamente e hierarquizada a norma (CF, CTB, Lei, CONTRAN, Parecer CETRAN).\n"
            "3. SINTAXE PROIBIDA: Texto sem emojis, sem referência a comandos sistêmicos ou IAs.\n"
            "4. COMPATIBILIDADE: Se Fase 3 detectou Prescrição/Decadência, o Resultado Obrigatório deve ser DEFERIDO, "
            "e a seção Teses Defensivas deve conter exclusivamente 'Teses defensivas prejudicadas em razão da extinção da pretensão punitiva'.\n"
            "5. Se Intempestivo sem prescrição: 'INDEFERIDO'.\n\n"
            "GERAR O PARECER BRUTO E INTEGRAL EXATAMENTE NESTE MODELO:\n\n"
            "PARECER JARI\n"
            "PROCESSO: [PA]\n"
            "SGPE: [SGPE]\n"
            "RECORRENTE: [Nome - Documento Autuação]\n"
            f"RELATOR: {relator_name}\n"
            "DATA SESSÃO: [DD/MM/AAAA]\n"
            "RESULTADO: [DEFERIDO ou INDEFERIDO]\n\n"
            "EMENTA\n"
            "[SÍNTESE MAIÚSCULA - infração + tese(s) + admissibilidade + transcrição + resultado]\n\n"
            "RELATÓRIO\n"
            "Este é o relatório.\n\n"
            "FUNDAMENTAÇÃO JURÍDICA\n"
            "ADMISSIBILIDADE\n"
            "Conclusão expressa: [tempestivo/intempestivo] + explicação normativa.\n\n"
            "TESES DEFENSIVAS\n"
            "[Prejudicadas ou Análise Isolada]\n\n"
            "PRESCRIÇÃO E DECADÊNCIA\n"
            "3.1 Prescrição punitiva\n[Linha Tempo + Explicação + Conclusão]\n"
            "3.2 Prescrição intercorrente\n[Intervalo + Explicação + Conclusão]\n"
            "3.3 Decadência\n[Explicação Normativa + Conclusão]\n\n"
            "MATERIALIDADE\n[Explicação Normativa]\n\n"
            "GARANTIAS PROCESSUAIS\n"
            "Verificação de notificações e respeito ao contraditório + explicação normativa (art. 5º, LV, CF/88).\n\n"
            "Esta é a fundamentação.\n\n"
            "***DOSSIE_START***\n"
            "[Cite apenas as leis e fundamentos em bullets (Exemplo: * [Constituição Federal](https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm) ) pesquisando sempre que possível o link na WEB para a lei no formato Markdown padrão.]\n"
            "***DOSSIE_END***"
        )
        
        prompt = (
            f"---- HISTÓRICO MATEMÁTICO GERADO (FASE 3 - SOBERANIA DO CÓDIGO) ----\n"
            f"{parecer_obj.admissibilidade_texto}\n\n"
            f"---- CONCLUSÃO TESE (FASE 4) ----\n"
            f"{parecer_obj.analise_tese_texto}\n"
            f"Tese(s): {tese}\n\n"
            f"DADOS GERAIS:\n"
            f"PA: {parecer_obj.pa}\n"
            f"SGPE: {parecer_obj.sgpe}\n"
            f"Recorrente Manual: {parecer_obj.recorrente}\n"
            f"Data Sessão: {parecer_obj.data_sessao}\n\n"
            f"INVENTÁRIO NORMATIVO: {vertex_result}\n\n"
            f"JURISPRUDÊNCIA: {perplexity_result}\n\n"
            f"Crie o Parecer Final seguindo a formatação e as Regras de Ouro. O resultado de deferido/indeferido MANDA no conteúdo do texto."
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
