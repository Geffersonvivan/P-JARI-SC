import os
import re
import hashlib
import logging
import math
import threading

_log = logging.getLogger(__name__)

# TTL do cache RAG: 24 horas (base normativa não muda com frequência)
_RAG_CACHE_TTL = 86_400

# Singleton do modelo de embedding — carregado sob demanda
_embed_model = None
_embed_lock = threading.Lock()

_MODEL_NAME = os.environ.get('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')


def _rag_cache_key(prefix: str, query: str) -> str:
    """Gera chave Redis determinística para o resultado de uma query RAG."""
    normalized = re.sub(r'[.\s]+', ' ', query.strip().lower())
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return f"rag:{prefix}:{digest}"


def _get_embed_model():
    """Retorna modelo SentenceTransformer singleton (lazy load). Requer sentence-transformers."""
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    with _embed_lock:
        if _embed_model is not None:
            return _embed_model
        try:
            from sentence_transformers import SentenceTransformer
            _embed_model = SentenceTransformer(_MODEL_NAME)
            _log.info(f"Modelo de embedding carregado: {_MODEL_NAME}")
        except ImportError:
            raise RuntimeError(
                "sentence-transformers não instalado. "
                "Instale localmente para gerar embeddings: pip install sentence-transformers"
            )
        return _embed_model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Gera embeddings usando sentence-transformers (requer o pacote instalado)."""
    model = _get_embed_model()
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return [e.tolist() for e in embeddings]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Similaridade cosseno entre dois vetores."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# --- Cache em memória dos embeddings (carregados 1x do banco) ---
_embeddings_cache = None
_embeddings_cache_lock = threading.Lock()
_EMBEDDINGS_CACHE_TTL = 3600  # Recarrega do banco a cada 1h


def _load_embeddings_cache():
    """Carrega todos os embeddings do banco em memória."""
    global _embeddings_cache
    import time
    from chat.models import DocumentoNormativo

    chunks = list(
        DocumentoNormativo.objects
        .values_list('id', 'nome_arquivo', 'pagina_inicio', 'texto', 'embedding')
    )
    _embeddings_cache = {
        'data': chunks,
        'loaded_at': time.time(),
    }
    _log.info(f"Cache de embeddings carregado: {len(chunks)} chunks")
    return chunks


def _get_embeddings():
    """Retorna embeddings cacheados em memória (recarrega a cada 1h)."""
    import time
    with _embeddings_cache_lock:
        if (_embeddings_cache is None or
                time.time() - _embeddings_cache['loaded_at'] > _EMBEDDINGS_CACHE_TTL):
            _load_embeddings_cache()
        return _embeddings_cache['data']


class VertexAIClient:
    def __init__(self):
        pass

    def search_documents(self, parecer_obj, query, top_k=5):
        from chat.models import DocumentoNormativo

        if not DocumentoNormativo.objects.exists():
            return ("Base normativa não indexada. "
                    "Execute: python manage.py ingest_normativo")

        # Cache hit — evita re-computar para a mesma query
        from django.core.cache import cache
        _cache_key = _rag_cache_key("vertex", query)
        _cached = cache.get(_cache_key)
        if _cached:
            return _cached

        try:
            # Tenta embed da query com sentence-transformers
            try:
                query_vector = embed_texts([query])[0]
            except RuntimeError:
                return self._fallback_text_search(parecer_obj, query, top_k)

            # Busca sobre embeddings em memória (cacheados do banco)
            chunks = _get_embeddings()

            # Se embeddings vazios no banco, usa fallback textual
            if chunks and not chunks[0][4]:  # embedding vazio
                return self._fallback_text_search(parecer_obj, query, top_k)

            scored = []
            for chunk_id, nome, pagina, texto, emb in chunks:
                sim = _cosine_similarity(query_vector, emb)
                scored.append((sim, nome, pagina, texto))

            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[:top_k]

            resultados = []
            for sim, nome, pagina, texto in top:
                header = f"[{nome} | p.{pagina} | sim={sim:.3f}]"
                resultados.append(f"{header}\n{texto}")

            is_miss = not resultados

            try:
                if parecer_obj:
                    from chat.models import AiRequestLog
                    AiRequestLog.objects.create(
                        parecer_referencia=parecer_obj,
                        user=parecer_obj.user,
                        provider='Local RAG (sentence-transformers)',
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
                    send_mail(
                        "🚨 JARI ALERTA (RAG MISS): Termo Não Encontrado",
                        (f"O sistema realizou uma busca RAG que retornou VAZIA.\n\n"
                         f"Termo Pesquisado:\n{query}\n\n"
                         f"Verifique se algum documento normativo está faltando na base."),
                        settings.DEFAULT_FROM_EMAIL,
                        ['geffersonvivan@gmail.com'],
                        fail_silently=True,
                    )
                except Exception:
                    pass
                return "Nenhum documento interno encontrado para esta busca."

            resultado_final = "\n\n---\n\n".join(resultados)
            cache.set(_cache_key, resultado_final, timeout=_RAG_CACHE_TTL)
            return resultado_final

        except Exception as e:
            _log.exception("Erro na busca RAG")
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                send_mail(
                    "🚨 JARI ALERTA INOPERÂNCIA: Erro RAG",
                    f"O sistema RAG retornou erro.\n\nErro: {str(e)}",
                    settings.DEFAULT_FROM_EMAIL,
                    ['geffersonvivan@gmail.com'],
                    fail_silently=True,
                )
            except Exception:
                pass
            return f"Erro ao buscar no RAG: {str(e)}"

    def _fallback_text_search(self, parecer_obj, query, top_k=5):
        """Busca textual simples (icontains) quando sentence-transformers não está disponível."""
        from chat.models import DocumentoNormativo

        # Tokeniza a query em palavras-chave
        palavras = [p for p in query.lower().split() if len(p) > 3]

        from django.db.models import Q
        q_filter = Q()
        for palavra in palavras[:5]:  # Limita a 5 termos
            q_filter |= Q(texto__icontains=palavra)

        chunks = DocumentoNormativo.objects.filter(q_filter)[:top_k]

        if not chunks:
            return "Nenhum documento interno encontrado para esta busca."

        resultados = []
        for chunk in chunks:
            header = f"[{chunk.nome_arquivo} | p.{chunk.pagina_inicio}]"
            resultados.append(f"{header}\n{chunk.texto}")

        resultado_final = "\n\n---\n\n".join(resultados)

        # Cache e log
        from django.core.cache import cache
        _cache_key = _rag_cache_key("vertex", query)
        cache.set(_cache_key, resultado_final, timeout=_RAG_CACHE_TTL)

        try:
            if parecer_obj:
                from chat.models import AiRequestLog
                AiRequestLog.objects.create(
                    parecer_referencia=parecer_obj,
                    user=parecer_obj.user,
                    provider='Local RAG (text-search fallback)',
                    fase='Pesquisa Base (RAG)',
                    input_tokens=0,
                    output_tokens=1,
                    query_text=query,
                    is_miss=False,
                )
        except Exception:
            pass

        return resultado_final
