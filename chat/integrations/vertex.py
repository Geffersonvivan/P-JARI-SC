import os
from google.cloud import discoveryengine_v1 as discoveryengine


class VertexAIClient:
    def __init__(self):
        self.project_id = os.environ.get('VERTEX_PROJECT_ID')
        self.location = os.environ.get('VERTEX_LOCATION', 'global')
        self.data_store_id = os.environ.get('VERTEX_DATA_STORE_ID')

    def search_documents(self, parecer_obj, query, top_k=5):
        if not self.project_id or not self.data_store_id:
            return "Sistema RAG Offline. O Agente deve responder à pergunta utilizando seu amplo conhecimento prévio do Código de Trânsito Brasileiro (CTB) e resoluções do CONTRAN, informando as bases legais federais aplicáveis."

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
                content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                    snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                        return_snippet=True
                    )
                )
            )

            response = client.search(request, timeout=60)

            resultados = []
            for result in response.results:
                document_data = result.document.derived_struct_data
                content = ""

                trechos = document_data.get("extractive_answers", [])
                if trechos:
                     content = trechos[0].get("content", "")

                if not content:
                    snippets = document_data.get("snippets", [])
                    if snippets:
                        content = snippets[0].get("snippet", "")

                if content:
                    resultados.append(content)

            is_miss = False
            if not resultados:
                is_miss = True

            try:
                if parecer_obj:
                    from chat.models import AiRequestLog
                    AiRequestLog.objects.create(
                        parecer_referencia=parecer_obj,
                        user=parecer_obj.user,
                        provider='Vertex AI (Search)',
                        fase='Pesquisa Base (RAG)',
                        input_tokens=0,
                        output_tokens=1,
                        query_text=query,
                        is_miss=is_miss
                    )
            except Exception:
                pass

            if is_miss:
                try:
                    from django.core.mail import send_mail
                    from django.conf import settings
                    import logging
                    logger = logging.getLogger(__name__)

                    subject = f"🚨 JARI ALERTA (RAG MISS): Termo Não Encontrado"
                    message = (
                        f"O sistema realizou uma busca no Vertex AI RAG que retornou VAZIA.\n\n"
                        f"Termo Pesquisado:\n{query}\n\n"
                        f"Por favor, verifique se algum documento normativo está faltando na base de dados (Ex: resoluções novas)."
                    )
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        ['geffersonvivan@gmail.com'],
                        fail_silently=True,
                    )
                except Exception as e:
                    pass
                return "Nenhum documento interno encontrado para esta busca."

            return "\n\n---\n\n".join(resultados)
        except Exception as e:
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                subject = f"🚨 JARI ALERTA INOPERÂNCIA: Erro Vertex AI"
                message = f"O banco de dados privado do JARI (Vertex) caiu ou retornou erro.\n\nErro: {str(e)}"
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    ['geffersonvivan@gmail.com'],
                    fail_silently=True,
                )
            except Exception:
                pass
            return f"Erro ao buscar no Vertex AI: {str(e)}"
