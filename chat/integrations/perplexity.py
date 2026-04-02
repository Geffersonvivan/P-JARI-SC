import os
import time
import hashlib
import logging
import requests
from django.core.mail import send_mail

_log = logging.getLogger(__name__)
from django.conf import settings

# TTL do cache RAG: 24 horas
_RAG_CACHE_TTL = 86_400


def _rag_cache_key(query: str) -> str:
    digest = hashlib.sha256(query.strip().lower().encode()).hexdigest()[:16]
    return f"rag:perplexity:{digest}"


def _get_redis():
    try:
        import redis
        return redis.from_url(getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0'),
                              decode_responses=True)
    except Exception:
        return None


def _p(field):
    """Normaliza FileField/CharField para string de caminho, ou None."""
    if not field:
        return None
    return field.name if hasattr(field, 'name') else (str(field) or None)


class PerplexityClient:
    def __init__(self):
        self.api_key = os.environ.get('PERPLEXITY_API_KEY')
        self.url = "https://api.perplexity.ai/chat/completions"

    def search_tese(self, parecer_obj, tese):
        if not self.api_key:
            return "Simulação (Perplexity): Tese pesquisada. A tese é favorável segundo jurisprudência recente (REsp 123.456)."

        # Cache hit — evita re-consultar Perplexity para a mesma tese
        _cache_key = _rag_cache_key(tese)
        _r = _get_redis()
        if _r:
            try:
                _cached = _r.get(_cache_key)
                if _cached:
                    return _cached
            except Exception:
                pass

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
            start_time = time.time()
            response = requests.post(self.url, json=payload, headers=headers, timeout=60)

            if response.status_code == 402:
                send_mail(
                    subject='🚨 JARI ALERTA (FUNDO PERPLEXITY)',
                    message='O Perplexity AI retornou Erro 402 (Payment Required). O saldo da API esgotou e o sistema está respondendo via fallback.',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=['geffersonvivan@gmail.com'],
                    fail_silently=True
                )

            response.raise_for_status()
            data = response.json()
            latency_ms = int((time.time() - start_time) * 1000)

            try:
                if parecer_obj:
                    from chat.models import AiRequestLog
                    AiRequestLog.objects.create(
                        parecer_referencia=parecer_obj,
                        user=parecer_obj.user,
                        provider='Perplexity',
                        fase='Pesquisa Base (Jurisprudência)',
                        input_tokens=data.get('usage', {}).get('prompt_tokens', 0),
                        output_tokens=data.get('usage', {}).get('completion_tokens', 0),
                        latency_ms=latency_ms,
                        model_name='sonar-pro'
                    )
            except Exception as log_e:
                _log.error("Erro ao logar tokens Perplexity: %s", log_e)

            resultado = data["choices"][0]["message"]["content"]
            if _r:
                try:
                    _r.setex(_cache_key, _RAG_CACHE_TTL, resultado)
                except Exception:
                    pass
            return resultado
        except Exception as e:
            return f"Erro ao acessar Perplexity: {str(e)}.\nSimulação ativada: Jurisprudência encontrada favorável a tese."
