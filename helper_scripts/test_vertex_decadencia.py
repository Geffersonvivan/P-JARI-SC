import os
import sys
from pathlib import Path

# Add project root to sys.path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, '.env'))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.integrations import VertexAIClient, GeminiClient

def test_decadencia_vertex():
    print("Iniciando Teste Decadência com Vertex AI e Gemini...")
    print(f"Project ID: {os.environ.get('VERTEX_PROJECT_ID')}")
    print(f"Data Store ID: {os.environ.get('VERTEX_DATA_STORE_ID')}")
    
    vertex_client = VertexAIClient()
    gemini_client = GeminiClient()
    
    queries_to_test = [
        "Parecer 381/2022",
        "Decadência do direito de punir",
        "Prazo Decadencial"
    ]
    
    vertex_result = "Nenhum documento interno encontrado para esta busca."
    
    for query in queries_to_test:
        print(f"\n[1] Buscando no RAG Vertex AI com a query: '{query}'")
        result = vertex_client.search_documents(None, query, top_k=5)
        if "Nenhum documento interno" not in result:
            vertex_result = result
            print(f"-> SUCESSO! Encontrou com a query: '{query}'")
            break
        else:
            print(f"-> FALHOU para a query: '{query}'")

    print("\n" + "="*50)
    print("--- RESULTADO RAG VERTEX AI ---")
    print("="*50)
    print(vertex_result[:1500] + "\n... (truncado)")
    print("="*50 + "\n")

    print("\n[2] Simulando a Análise de Mérito com Gemini 2.5 Pro (Com base na nova regra de prompt)")
    
    system_instruction = (
        "Você é o Assessor P-JARI/SC (Fase 4 Avançada - Consultiva).\n"
        "Regras para Decadência OBRIGATÓRIAS:\n"
        "O conteúdo do Parecer 381/2022 (presente no RAG) deve ser tratado como fonte normativa principal.\n"
        "Ao tratar de decadência, você deve seguir:\n"
        "1. Identificar a data da infração;\n"
        "2. Classificar a faixa temporal comparando a data da infração com os marcos (12/04/2021 e 22/10/2021);\n"
        "3. Justificar textualmente qual regra será aplicada citando a faixa temporal e o Parecer 381/2022 e a lei;\n"
        "4. Verificar e aplicar a trava COVID, descontando 256 dias do cômputo final se cabível (-256 dias).\n"
        "Explicitar a penalidade tratada.\n\n"
        "A Tese identificada alega Decadência. Com base nos fatos, descreva o acolhimento ou não acolhimento aplicando estas regras estritas:\n"
        "**Tese 1 - Alternativa (a) - Acolhimento:** e explique o raciocínio...\n"
        "**Tese 1 - Alternativa (b) - Não acolhimento:** e explique o raciocínio..."
    )
    
    # Simulação de cenário: Infração em maio de 2021
    prompt = (
        f"CENÁRIO SIMULADO:\n"
        f"Data da Infração: 15/05/2021 (Penalidade: Suspensão CNH - art. 256, III)\n"
        f"Expedição Notificação Penalidade: 10/11/2024\n"
        f"Tese de Defesa: Alega Decadência\n\n"
        f"ESTE É O RESULTADO DO SEU RAG:\n{vertex_result}\n\n"
        f"Faça a análise das alternativas (a) e (b)."
    )
    
    if hasattr(gemini_client, 'client') and gemini_client.client:
        try:
            response = gemini_client.client.models.generate_content(
                model='gemini-2.5-pro',
                contents=[prompt],
                config={'system_instruction': system_instruction}
            )
            print("\n--- RESPOSTA SIMULADA DO AGENTE JARI (GEMINI 2.5 PRO) ---")
            print(response.text)
        except Exception as e:
            print(f"Erro no Gemini: {e}")

if __name__ == '__main__':
    test_decadencia_vertex()
