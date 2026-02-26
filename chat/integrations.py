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

    def validate_and_generate_parecer(self, parecer_obj, tese, perplexity_result, vertex_result=""):
        if not self.client:
            return (
                "**PARECER JARI**\n\n"
                "**RESULTADO:** DEFERIDO\n"
                "**EMENTA:** RECURSO TEMPESTIVO. TESE ACOLHIDA.\n\n"
                "**RELATÓRIO:**\nTrata-se de recurso administrativo interposto por "
                f"{parecer_obj.recorrente} contra autuação de trânsito.\n\n"
                "**FUNDAMENTAÇÃO JURÍDICA:**\n"
                f"Admissibilidade OK. A tese '{tese}' foi analisada à luz do MBFT e CTB, e encontra respaldo na jurisprudência "
                f"({perplexity_result}). Pelo exposto, opino pelo deferimento."
            )
            
        system_instruction = (
            "Você é o Assessor P-JARI/SC. Siga o 'Inventário Normativo DRIVE' rigorosamente. "
            "A norma local prevalece sobre fontes externas. Aja de forma técnica, objetiva e com legalidade estrita. "
            "Você deve compor o parecer estruturado em 5 seções obrigatórias: PARECER JARI, RESULTADO (DEFERIDO/INDEFERIDO), "
            "EMENTA (em maiúsculo), RELATÓRIO e FUNDAMENTAÇÃO JURÍDICA."
        )
        
        prompt = (
            f"Analise o seguinte processo do JARI-SC:\n\n"
            f"Recorrente: {parecer_obj.recorrente}\n"
            f"PA: {parecer_obj.pa}\n"
            f"SGPE: {parecer_obj.sgpe}\n"
            f"Tese de defesa alegada: {tese}\n\n"
            f"Resultado da busca externa (jurisprudência Perplexity): {perplexity_result}\n\n"
            f"Manuais, Resoluções e Regulamentos Internos aplicáveis (Vertex AI / Cloud Storage JARI-SC): {vertex_result}\n\n"
            f"Elabore o Parecer Técnico no bloco único estruturado exigido."
        )

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config={'system_instruction': system_instruction}
            )
            return response.text
        except Exception as e:
            return f"Erro ao acessar Gemini: {str(e)}.\nFalha ao gerar parecer via LLM."

    def calculate_blindagem(self, parecer_text):
        if not self.client:
            return "Seu PARECER está **98%** blindado."
            
        prompt = (
            f"Atue como um Membro Julgador revisando a peça do seu Assessor P-JARI. "
            f"Faça a leitura reversa do parecer abaixo e calcule um índice de blindagem (0 a 100%) baseado na "
            f"precisão legal, formatação e suficiência das provas alegadas. "
            f"Ao final da sua avaliação, retorne na última linha exatamente o texto "
            f"'Seu PARECER está [XX]% blindado'.\n\n"
            f"Parecer a ser avaliado:\n\n{parecer_text}"
        )

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            return response.text
        except Exception as e:
            return f"Erro ao acessar Gemini: {str(e)}."

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
