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
                    "content": "Você é um assessor jurídico especialista no JARI de Santa Catarina. Sua pesquisa deve obrigatoriamente priorizar sites com domínios .gov.br ou .sc.gov.br. Relacione apenas resoluções do CONTRAN, CETRAN-SC, MBFT e CTB aplicáveis ao caso."
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
        if not self.client or not os.path.exists(file_path):
            return None
        try:
            # Upload the file to Gemini
            gemini_file = self.client.files.upload(file=file_path)
            return gemini_file
        except Exception as e:
            print(f"Erro ao subir arquivo pro Gemini: {e}")
            return None

    def generate_admissibility_report(self, parecer_obj):
        if not self.client:
             return "Simulação: Admissibilidade checada. Tempestivo. Prescrições Afastadas."
             
        system_instruction = (
            "Você é o Assessor P-JARI/SC. Analise os dados fornecidos e retorne OBRIGATORIAMENTE "
            "um levantamento estruturado de datas no exato formato visual abaixo:\n\n"
            "🔎 **LEVANTAMENTO COMPLETO DE TODAS AS DATAS (extraídas documentalmente)**\n\n"
            "📍 **FASE INFRAÇÃO / AUTUAÇÃO**\n"
            "**1. Data da Infração:** [Data] às [Hora]\n"
            "📄 [Nome do Documento Oficial]\n"
            "**2. Data Postagem Notificação Autuação:** [Data]\n"
            "📄 [Nome do Documento Oficial]\n"
            "*(...e assim por diante para todas as datas dessa fase)*\n\n"
            "📍 **FASE PROCESSO DE SUSPENSÃO**\n"
            "**8. Portaria Instauração PSDD:** [Data]\n"
            "📄 [Nome do Documento Oficial]\n"
            "*(...continuando a numeração contínua para as demais datas dessa fase)*\n\n"
            "📍 **FASE RECURSAL JARI**\n"
            "**12. Protocolo Recurso JARI:** [Data]\n"
            "📄 [Nome do Documento Oficial]\n"
            "**13. Data Sessão Julgamento JARI:** [Data]\n"
            "📌 Informação Pergunta 1\n\n"
            "REGRAS DE FORMATAÇÃO: Use negrito para o nome do evento. Coloque o ícone 📄 e o nome do arquivo/documento NA LINHA DE BAIXO de cada evento. Mantenha a numeração 1,2,3... contínua entre as fases. Não invente datas ausentes, escreva 'Data não localizada' se não achar. É EXPRESSAMENTE PROIBIDO incluir números de páginas das quais a informação foi retirada."
        )
        
        prompt_text = (
            f"Processo: {parecer_obj.pa} | SGPE: {parecer_obj.sgpe}\n"
            f"Data da Sessão informada pela Pergunta 1: {parecer_obj.data_sessao}\n"
            f"Data de Protocolo JARI informada pela Pergunta 5: {parecer_obj.data_protocolo}\n"
            f"Prazo Final (Tempestividade) informada pela Pergunta 4: {parecer_obj.prazo_final}\n\n"
            "Leia os PDFs anexados, extraia todas as datas cronológicas obrigatórias e devolva "
            "EXATAMENTE o layout Markdown visual solicitado (🔎, 📍, 1., 2., 📄). "
            "Ao final das datas, forneça a conclusão obrigatória e expressa sobre: "
            "Tempestividade, Prescrição Punitiva, Prescrição Intercorrente (calculando a diferença em dias corridos entre o Protocolo JARI da Pergunta 5 e a Data da Sessão da Pergunta 1 > 1095 dias) e Decadência."
        )
        
        contents = [prompt_text]
        
        # Anexar os PDFs no prompt se existirem
        if parecer_obj.autuacao_pdf_path and os.path.exists(parecer_obj.autuacao_pdf_path) and "upload_simulado" not in parecer_obj.autuacao_pdf_path:
            file_autuacao = self.upload_file(parecer_obj.autuacao_pdf_path)
            if file_autuacao:
                contents.insert(0, file_autuacao)
                
        if parecer_obj.consolidado_pdf_path and os.path.exists(parecer_obj.consolidado_pdf_path) and "upload_simulado" not in parecer_obj.consolidado_pdf_path:
            file_consolidado = self.upload_file(parecer_obj.consolidado_pdf_path)
            if file_consolidado:
                contents.insert(0, file_consolidado)

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-pro', # Usando PRO para melhor leitura de documentos complexos
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
            "Você é o Assessor Jurídico P-JARI/SC. Sua tarefa é ler o documento anexo (que pode ser "
            "um Processo Consolidado longo) e encontrar a peça de defesa do recorrente. As páginas "
            "indicadas são apenas um REFERENCIAL para te ajudar a localizar mais rápido onde o recurso começa. "
            "Escaneie o documento a partir dessas páginas e extraia a tese principal alegada para anulação da multa. "
            "Seja direto e conciso, resumindo a alegação central em um parágrafo."
        )
        
        prompt_text = (
            f"Por favor, procure a defesa do recorrente no documento anexo. O assessor informou que "
            f"ela deve estar próxima as seguintes páginas: {parecer_obj.paginas_defesa}.\n\n"
            "Qual é a tese principal alegada para solicitar o cancelamento/nulidade da autuação? Retorne o resumo das alegações."
        )
        
        contents = [prompt_text]
        
        if parecer_obj.autuacao_pdf_path and os.path.exists(parecer_obj.autuacao_pdf_path) and "upload_simulado" not in parecer_obj.autuacao_pdf_path:
            file_autuacao = self.upload_file(parecer_obj.autuacao_pdf_path)
            if file_autuacao:
                contents.insert(0, file_autuacao)
                
        if parecer_obj.consolidado_pdf_path and os.path.exists(parecer_obj.consolidado_pdf_path) and "upload_simulado" not in parecer_obj.consolidado_pdf_path and parecer_obj.consolidado_pdf_path != parecer_obj.autuacao_pdf_path:
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
        
        if parecer_obj.autuacao_pdf_path and os.path.exists(parecer_obj.autuacao_pdf_path) and "upload_simulado" not in parecer_obj.autuacao_pdf_path:
            file_autuacao = self.upload_file(parecer_obj.autuacao_pdf_path)
            if file_autuacao:
                contents.insert(0, file_autuacao)
                
        if parecer_obj.consolidado_pdf_path and os.path.exists(parecer_obj.consolidado_pdf_path) and "upload_simulado" not in parecer_obj.consolidado_pdf_path and parecer_obj.consolidado_pdf_path != parecer_obj.autuacao_pdf_path:
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
            "Você é o Assessor P-JARI/SC. Sua tarefa é ler a tese defensiva, analisar eventuais "
            "arquivos anexados e confrontar com o Inventário Normativo vertx google e a "
            "jurisprudência Perplexity fornecida. Responda de forma clara e termine EXATAMENTE "
            "com a string: 'Resultar em: Conclusão: acolhida' ou 'Resultar em: Conclusão: não acolhida'."
        )
        
        prompt_text = (
            f"Processo: {parecer_obj.pa} | SGPE: {parecer_obj.sgpe}\n"
            f"Data da Sessão (P1): {parecer_obj.data_sessao}\n"
            f"Tese de defesa alegada (Páginas {parecer_obj.paginas_defesa}): {tese}\n\n"
            f"---- HISTÓRICO DE MEMÓRIA DO PROCESSO (Admissibilidade Fase 3) ----\n"
            f"{parecer_obj.admissibilidade_texto}\n"
            f"------------------------------------------------------------------\n\n"
            f"Inventário Normativo (Vertex): {vertex_result}\n\n"
            f"Jurisprudência (Perplexity): {perplexity_result}\n\n"
            "Analise e decida pela acolhida ou não acolhida da tese com base na documentação, normativas e no histórico de admissibilidade já calculado."
        )
        
        contents = [prompt_text]
        
        # Anexar os PDFs no prompt se existirem
        if parecer_obj.autuacao_pdf_path and os.path.exists(parecer_obj.autuacao_pdf_path) and "upload_simulado" not in parecer_obj.autuacao_pdf_path:
            file_autuacao = self.upload_file(parecer_obj.autuacao_pdf_path)
            if file_autuacao:
                contents.insert(0, file_autuacao)
                
        if parecer_obj.consolidado_pdf_path and os.path.exists(parecer_obj.consolidado_pdf_path) and "upload_simulado" not in parecer_obj.consolidado_pdf_path:
            file_consolidado = self.upload_file(parecer_obj.consolidado_pdf_path)
            if file_consolidado:
                contents.insert(0, file_consolidado)

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-pro',
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

        if not self.client:
            return (
                "**PARECER JARI**\n\n"
                "**PROCESSO:** 123\n"
                "**SGPE:** 321\n"
                "**RECORRENTE:** NOME\n"
                f"**RELATOR:** {relator_name}\n"
                "**DATA SESSÃO:** \n\n"
                "**RESULTADO:** DEFERIDO\n\n"
                "**EMENTA**\n"
                "RECURSO TEMPESTIVO. TESE ACOLHIDA.\n\n"
                "**RELATÓRIO**\nTrata-se de recurso administrativo interposto por "
                f"{parecer_obj.recorrente} contra processo punitivo de trânsito.\n\n"
                "**FUNDAMENTAÇÃO JURÍDICA**\n\n"
                "**1. ADMISSIBILIDADE**\nTempestivo.\n"
                "**2. TESES DEFENSIVAS (se tempestivo)**\nAdmitida.\n"
                "**3. PRESCRIÇÃO E DECADÊNCIA**\nSem ocorrência.\n"
                "**4. MATERIALIDADE**\nAuto de Infração válido.\n"
                "**5. GARANTIAS PROCESSUAIS**\nAmpla defesa respeitada."
            )
            
        system_instruction = (
            "Você é o Assessor P-JARI/SC. Sua função é assessorar julgamentos JARI-SC, com legalidade estrita, "
            "rastreabilidade documental e máxima proteção ao recorrente. \n\n"
            "**REGRAS DE OURO (IMUTÁVEIS)**:\n"
            "1. PROIBIDO inventar fatos, datas, normas ou conclusões.\n"
            "2. PROIBIDO responder 'de memória' ou completar lacunas fáticas ou jurídicas.\n"
            "3. Se algo não estiver localizado nos documentos fornecidos, responda OBRIGATORIAMENTE: "
            "'NÃO LOCALIZADO nos documentos anexados (Doc/Pág).'\n"
            "4. FONTE ÚNICA DA VERDADE: O 'Inventário Normativo vertx google'. Norma inferior jamais afasta norma superior.\n"
            "5. LINGUAGEM ESTRITAMENTE FORMAL E JURÍDICA: É EXPRESSAMENTE PROIBIDO o uso de qualquer EMOJI (como ✅, ❌, etc) em toda a redação do Parecer.\n"
            "6. PROIBIDO CITAR TECNOLOGIAS: Jamais mencione na redação do Parecer os nomes das ferramentas de IA ou RAG que o alimentaram (como Perplexity, Gemini, Vertex AI, RAG, Motor JARI, 'nosso sistema', etc). Aja e escreva como o humano Assessor Julgador.\n\n"
            "Você deve compor o parecer estruturado em UM ÚNICO BLOCO no seguinte formato EXATO (INCLUINDO AS TAGS DOSSIE_START e DOSSIE_END literais):\n\n"
            "**PARECER JARI**\n\n"
            "**PROCESSO:** [PA]\n"
            "**SGPE:** [SGPE]\n"
            "**RECORRENTE:** [Documento \"Autuação\" nome linha \"Interessado\" após \":\" em maiúsculo]\n"
            f"**RELATOR:** {relator_name}\n"
            "**DATA SESSÃO:** [DD/MM/AAAA]\n\n"
            "**RESULTADO:** [DEFERIDO/INDEFERIDO]\n\n"
            "**EMENTA**\n"
            "[Resumo: infração, tese(s), prescrição/decadência, resultado]\n"
            "TEXTO EMENTA EM MAIÚSCULO\n\n"
            "**RELATÓRIO**\n"
            "[Síntese: infração, notificações, defesa/recurso, envio à JARI.]\n\n"
            "**FUNDAMENTAÇÃO JURÍDICA**\n\n"
            "**1. ADMISSIBILIDADE**\n"
            "Conclusão: [tempestivo / intempestivo]\n\n"
            "**2. TESES DEFENSIVAS (se tempestivo)**\n"
            "*(Cada tese analisada isoladamente, com base normativa e conclusão)*\n\n"
            "**3. PRESCRIÇÃO E DECADÊNCIA**\n"
            "3.1 Prescrição punitiva: [linha do tempo + conclusão]\n"
            "3.2 Prescrição intercorrente: A data da Sessão de Julgamento é [DD/MM/AAAA]. [conclusão]\n"
            "3.3 Decadência: [regime temporal + conclusão]\n\n"
            "**4. MATERIALIDADE**\n"
            "**5. GARANTIAS PROCESSUAIS**\n\n"
            "***DOSSIE_START***\n"
            "- REGRA DE FERRO 1: É OBRIGATÓRIO incluir as tags literais ***DOSSIE_START*** e ***DOSSIE_END*** no seu output para delimitar esta seção.\n"
            "- REGRA DE FERRO 2: É EXPRESSAMENTE PROIBIDO copiar e colar o texto bruto do histórico.\n"
            "- Liste em bullet points EXCLUSIVAMENTE nomes de Leis, Artigos, Resoluções do CONTRAN, CTB, etc., que embasaram o Parecer.\n"
            "- REGRAS EXTRAORDINÁRIAS DE REDAÇÃO E EXCLUSÃO:\n"
            "  A) VERBOS SEMPRE NO PASSADO: Em toda a redação, conjugue os verbos sempre no passado, narrando os fatos ocorridos (ex: 'ocorreu', 'o recorrente alegou', 'foi expedida', 'restou configurado'). Nunca use o presente (evite 'ocorre', 'alega', 'é expedida').\n"
            "  B) PALAVRAS PROIBIDAS: JAMAIS escreva as palavras 'Vertex', 'Autuação', 'consolidado', 'Perplexity' ou 'Gemini', nem como referência. Aja como um humano.\n"
            "  C) LINKS CLICÁVEIS (MARKDOWN): Use sempre a sintaxe [Nome da Lei](http://link.com) em vez de jogar o texto cru na tela. Caso não tenha, não invente.\n"
            "  D) SEM NÚMERO DE PÁGINAS: É expressamente proibido citar ou fazer referência a números de páginas na redação (ex: JAMAIS escreva 'Página 3', 'Página 9', '(Página 8)', etc). Aponte apenas o nome do documento oficial ou os fatos.\n"
            "***DOSSIE_END***"
        )
        
        prompt = (
            f"Analise o seguinte processo do JARI-SC:\n\n"
            f"Recorrente: {parecer_obj.recorrente}\n"
            f"*(Se Recorrente for 'Não informado' ou vazio, busque no documento 'Autuação' o campo 'Interessado:')*\n"
            f"PA: {parecer_obj.pa}\n"
            f"SGPE: {parecer_obj.sgpe}\n"
            f"Data da Sessão: {parecer_obj.data_sessao}\n"
            f"Tese de defesa alegada e refinada (Fase 4): {tese}\n\n"
            f"---- HISTÓRICO DE MEMÓRIA DO PROCESSO: TABELA DE DATAS E ADMISSIBILIDADE (Fase 3) ----\n"
            f"{parecer_obj.admissibilidade_texto}\n"
            f"-------------------------------------------------------------------------------------\n\n"
            f"---- HISTÓRICO DE MEMÓRIA DO PROCESSO: CONCLUSÃO PRÉVIA DA TESE (Fase 41) ----\n"
            f"{parecer_obj.analise_tese_texto}\n"
            f"----------------------------------------------------------------------------\n\n"
            f"Manuais, Resoluções e Regulamentos Internos aplicáveis (Inventário Normativo vertx google): {vertex_result}\n\n"
            f"Resultado da busca externa (jurisprudência Perplexity): {perplexity_result}\n\n"
            f"Elabore o Parecer Técnico no bloco único estruturado exigido, substituindo os espaços numéricos "
            "com 1., 2., 3., 4., 5. conforme a regra atualizada das fases do relatório e utilizando todo o histórico em memória."
        )

        contents = [prompt]
        
        # Anexar os PDFs no prompt se existirem para que a IA possa extrair "Interessado" da Autuação
        if parecer_obj.autuacao_pdf_path and os.path.exists(parecer_obj.autuacao_pdf_path) and "upload_simulado" not in parecer_obj.autuacao_pdf_path:
            file_autuacao = self.upload_file(parecer_obj.autuacao_pdf_path)
            if file_autuacao:
                contents.insert(0, file_autuacao)
                
        if parecer_obj.consolidado_pdf_path and os.path.exists(parecer_obj.consolidado_pdf_path) and "upload_simulado" not in parecer_obj.consolidado_pdf_path and parecer_obj.consolidado_pdf_path != parecer_obj.autuacao_pdf_path:
            file_consolidado = self.upload_file(parecer_obj.consolidado_pdf_path)
            if file_consolidado:
                contents.insert(0, file_consolidado)

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
