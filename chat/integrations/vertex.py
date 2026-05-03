import os
import re
import hashlib
import logging
from google.cloud import discoveryengine_v1 as discoveryengine

_log = logging.getLogger(__name__)

# TTL do cache RAG: 24 horas (base normativa não muda com frequência)
_RAG_CACHE_TTL = 86_400

# Singleton lazy do SearchServiceClient — evita re-parsear credenciais a cada chamada
_search_client = None
_search_credentials = None


def _rag_cache_key(prefix: str, query: str) -> str:
    """Gera chave Redis determinística para o resultado de uma query RAG."""
    # Normaliza pontuação e espaços para melhorar hit rate
    normalized = re.sub(r'[.\s]+', ' ', query.strip().lower())
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return f"rag:{prefix}:{digest}"


def _get_search_client():
    """Retorna SearchServiceClient singleton (lazy init)."""
    global _search_client, _search_credentials
    if _search_client is not None:
        return _search_client, _search_credentials

    _creds_env = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')
    if _creds_env.strip().startswith('{'):
        import json
        from google.oauth2 import service_account
        _search_credentials = service_account.Credentials.from_service_account_info(
            json.loads(_creds_env)
        )
    else:
        try:
            from django.conf import settings as _dj_settings
            _search_credentials = getattr(_dj_settings, 'GS_CREDENTIALS', None)
        except Exception:
            pass

    _search_client = discoveryengine.SearchServiceClient(credentials=_search_credentials)
    return _search_client, _search_credentials


class VertexAIClient:
    def __init__(self):
        self.project_id = os.environ.get('VERTEX_PROJECT_ID')
        self.location = os.environ.get('VERTEX_LOCATION', 'global')
        self.data_store_id = os.environ.get('VERTEX_DATA_STORE_ID')

    def search_documents(self, parecer_obj, query, top_k=5):
        if not self.project_id or not self.data_store_id:
            return "Sistema RAG Offline. O Agente deve responder à pergunta utilizando seu amplo conhecimento prévio do Código de Trânsito Brasileiro (CTB) e resoluções do CONTRAN, informando as bases legais federais aplicáveis."

        # Cache hit — evita re-consultar Vertex para a mesma query
        from django.core.cache import cache
        _cache_key = _rag_cache_key("vertex", query)
        _cached = cache.get(_cache_key)
        if _cached:
            return _cached

        try:
            client, _credentials = _get_search_client()
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

            resultado_final = "\n\n---\n\n".join(resultados)
            cache.set(_cache_key, resultado_final, timeout=_RAG_CACHE_TTL)
            return resultado_final
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
