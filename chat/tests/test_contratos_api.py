"""
Camada 3 — Testes de Contrato das APIs (Mocks)

Verifica que as integrações com Anthropic, Gemini, Vertex e Perplexity
se comportam corretamente quando APIs falham, retornam lentidão ou
respostas malformadas.

Todos os testes usam mocks — sem chamadas reais a APIs externas.

Executar:
    python manage.py test chat.tests.test_contratos_api --keepdb
"""
import os
import unittest
from unittest.mock import MagicMock, patch, call


# ── Helper: mock de Parecer sem banco ────────────────────────────────────────

def _parecer(**kwargs):
    import datetime
    p = MagicMock()
    p.id = 1
    p.pa = "100/2024"
    p.sgpe = "SGPE-001"
    p.nome_processo = "Teste"
    p.session_key = "sess-001"
    p.data_sessao = datetime.date(2025, 6, 1)
    p.data_infracao = datetime.date(2024, 1, 1)
    p.data_protocolo = datetime.date(2024, 3, 1)
    p.prazo_final = datetime.date(2024, 3, 15)
    p.admissibilidade_texto = "Texto de admissibilidade"
    p.tabela_datas_sensiveis = ""
    p.analise_tese_texto = ""
    p.tese = "Nulidade de notificação"
    p.is_tempestivo = True
    p.has_prescricao_punitiva = False
    p.has_prescricao_intercorrente = False
    p.has_decadencia = False
    p.julgador_tempestivo = None
    p.julgador_prescricao_punitiva = None
    p.julgador_prescricao_intercorrente = None
    p.julgador_decadencia = None
    p.autuacao_pdf_path = None
    p.consolidado_pdf_path = None
    p.ata_pdf_path = None
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


def _mock_stream(texto="Parecer gerado."):
    """Cria um context manager mock para client.messages.stream."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.text_stream = iter([texto])
    ctx.get_final_message.return_value.usage.input_tokens = 100
    ctx.get_final_message.return_value.usage.output_tokens = 50
    return ctx


# ── Anthropic ────────────────────────────────────────────────────────────────

class TestAnthropicTrunc(unittest.TestCase):
    """Testa a função _trunc diretamente — sem banco, sem API."""

    def _trunc(self):
        from chat.integrations.anthropic import _trunc
        return _trunc

    def test_texto_dentro_do_limite_nao_e_truncado(self):
        _trunc = self._trunc()
        texto = "x" * 100
        resultado = _trunc(texto, "admissibilidade", 10_000)
        self.assertEqual(resultado, texto)

    def test_texto_acima_do_limite_e_truncado(self):
        _trunc = self._trunc()
        texto = "A" * 12_000
        resultado = _trunc(texto, "admissibilidade", 10_000)
        self.assertEqual(len(resultado[:10_000]), 10_000)
        self.assertIn("[truncado:", resultado)
        self.assertIn("2000 chars omitidos", resultado)

    def test_truncamento_loga_warning(self):
        _trunc = self._trunc()
        with self.assertLogs("chat.integrations.anthropic", level="WARNING") as cm:
            _trunc("B" * 11_000, "admissibilidade", 10_000)
        self.assertTrue(any("TRUNC" in line for line in cm.output))

    def test_texto_vazio_retorna_vazio(self):
        _trunc = self._trunc()
        self.assertEqual(_trunc("", "qualquer", 100), "")
        self.assertEqual(_trunc(None, "qualquer", 100), "")


class TestAnthropicFallback(unittest.TestCase):
    """Testa o fallback Gemini quando Anthropic não está disponível."""

    def _client(self):
        from chat.integrations.anthropic import AnthropicClient
        c = AnthropicClient()
        c.client = None  # Simula API key ausente
        return c

    def test_api_key_ausente_chama_gemini(self):
        """Sem client Anthropic → GeminiClient.generate_parecer_gemini é chamado."""
        cliente = self._client()
        mock_gemini_inst = MagicMock()
        mock_gemini_inst.generate_parecer_gemini.return_value = "Parecer Gemini"

        with patch('chat.integrations.gemini.GeminiClient', return_value=mock_gemini_inst):
            result = cliente.validate_and_generate_parecer(_parecer(), tese="tese", perplexity_result="")

        mock_gemini_inst.generate_parecer_gemini.assert_called_once()
        self.assertEqual(result, "Parecer Gemini")

    def test_api_key_ausente_gemini_falha_retorna_erro_configuracao(self):
        """Sem client + Gemini falha → retorna mensagem de erro de configuração."""
        cliente = self._client()
        mock_gemini_inst = MagicMock()
        mock_gemini_inst.generate_parecer_gemini.side_effect = Exception("Gemini down")

        with patch('chat.integrations.gemini.GeminiClient', return_value=mock_gemini_inst):
            result = cliente.validate_and_generate_parecer(_parecer(), tese="tese", perplexity_result="")

        self.assertIn("ERRO DE CONFIGURAÇÃO", result)

    def test_excecao_anthropic_faz_fallback_gemini(self):
        """Anthropic lança exceção → fallback Gemini + e-mail de alerta enviado."""
        from chat.integrations.anthropic import AnthropicClient
        cliente = AnthropicClient()
        cliente.client = MagicMock()
        cliente.client.messages.stream.side_effect = Exception("API down")

        mock_gemini_inst = MagicMock()
        mock_gemini_inst.generate_parecer_gemini.return_value = "Fallback Gemini OK"

        with patch('chat.integrations.gemini.GeminiClient', return_value=mock_gemini_inst), \
             patch('chat.prompts.phase_5.build_system_instruction', return_value="sys"), \
             patch('django.core.mail.send_mail'), \
             patch('chat.models.AiRequestLog.objects.create'):
            result = cliente.validate_and_generate_parecer(_parecer(), tese="tese", perplexity_result="")

        mock_gemini_inst.generate_parecer_gemini.assert_called_once()
        self.assertEqual(result, "Fallback Gemini OK")

    def test_excecao_anthropic_ambas_falham_retorna_string_erro(self):
        """Anthropic falha e Gemini também falha → retorna string com ambos os erros."""
        from chat.integrations.anthropic import AnthropicClient
        cliente = AnthropicClient()
        cliente.client = MagicMock()
        cliente.client.messages.stream.side_effect = Exception("Anthropic down")

        mock_gemini_inst = MagicMock()
        mock_gemini_inst.generate_parecer_gemini.side_effect = Exception("Gemini down")

        with patch('chat.integrations.gemini.GeminiClient', return_value=mock_gemini_inst), \
             patch('chat.prompts.phase_5.build_system_instruction', return_value="sys"), \
             patch('django.core.mail.send_mail'), \
             patch('chat.models.AiRequestLog.objects.create'):
            result = cliente.validate_and_generate_parecer(_parecer(), tese="tese", perplexity_result="")

        self.assertIn("Anthropic down", result)
        self.assertIn("Gemini down", result)


class TestAnthropicFlagsBlock(unittest.TestCase):
    """Verifica que _flags_block está presente no conteúdo enviado ao modelo."""

    def _call_e_capturar_prompt(self, **parecer_kwargs):
        from chat.integrations.anthropic import AnthropicClient
        cliente = AnthropicClient()
        cliente.client = MagicMock()
        mock_ctx = _mock_stream("INDEFERIDO.")
        cliente.client.messages.stream.return_value = mock_ctx

        with patch('chat.prompts.phase_5.build_system_instruction', return_value="sys"), \
             patch('chat.models.AiRequestLog.objects.create'):
            cliente.validate_and_generate_parecer(
                _parecer(**parecer_kwargs), tese="tese teste", perplexity_result=""
            )

        call_kwargs = cliente.client.messages.stream.call_args
        messages = call_kwargs.kwargs.get('messages') or call_kwargs[1].get('messages') or call_kwargs[0][0]
        content = messages[0]['content']
        return str(content)

    def test_flags_block_presente_no_prompt(self):
        """O bloco de FLAGS está sempre no início do conteúdo enviado."""
        content = self._call_e_capturar_prompt()
        self.assertIn("FLAGS MATEMÁTICAS", content)
        self.assertIn("SOBERANAS", content)
        self.assertIn("RESULTADO OBRIGATÓRIO", content)

    def test_resultado_obrigatorio_deferido_quando_prescricao_punitiva(self):
        """has_prescricao_punitiva=True → RESULTADO OBRIGATÓRIO: DEFERIDO."""
        content = self._call_e_capturar_prompt(has_prescricao_punitiva=True)
        self.assertIn("RESULTADO OBRIGATÓRIO DESTE PARECER: DEFERIDO", content)

    def test_resultado_obrigatorio_indeferido_sem_prejudicialidade(self):
        """Sem nenhuma flag de prejudicialidade → RESULTADO OBRIGATÓRIO: INDEFERIDO."""
        content = self._call_e_capturar_prompt(
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
        )
        self.assertIn("RESULTADO OBRIGATÓRIO DESTE PARECER: INDEFERIDO", content)

    def test_rota_d_analise_tese_forca_deferido(self):
        """analise_tese_texto com 'RESULTADO EXIGIDO NESTE PARECER: DEFERIDO' → DEFERIDO."""
        content = self._call_e_capturar_prompt(
            analise_tese_texto="RESULTADO EXIGIDO NESTE PARECER: DEFERIDO",
            has_prescricao_punitiva=False,
        )
        self.assertIn("RESULTADO OBRIGATÓRIO DESTE PARECER: DEFERIDO", content)

    def test_julgador_prevalece_sobre_automatico(self):
        """julgador_prescricao_punitiva=True sobrepõe has_prescricao_punitiva=False."""
        content = self._call_e_capturar_prompt(
            has_prescricao_punitiva=False,
            julgador_prescricao_punitiva=True,
        )
        self.assertIn("RESULTADO OBRIGATÓRIO DESTE PARECER: DEFERIDO", content)


# ── Vertex AI ────────────────────────────────────────────────────────────────

class TestVertexCache(unittest.TestCase):
    """Cache Redis para Vertex: hit evita chamada à API; miss chama e cacheia."""

    def _client(self):
        from chat.integrations.vertex import VertexAIClient
        return VertexAIClient()

    def _env_vertex(self):
        return patch.dict(os.environ, {
            'VERTEX_PROJECT_ID': 'proj-test',
            'VERTEX_DATA_STORE_ID': 'store-test',
            'VERTEX_LOCATION': 'global',
        })

    def test_cache_hit_nao_chama_api_vertex(self):
        """Cache hit → SearchServiceClient nunca é instanciado."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = "resultado em cache"

        with self._env_vertex(), \
             patch('chat.integrations.vertex._get_redis', return_value=mock_redis), \
             patch('chat.integrations.vertex.discoveryengine.SearchServiceClient') as mock_api:
            result = self._client().search_documents(_parecer(), "prescrição punitiva CTB")

        mock_api.assert_not_called()
        self.assertEqual(result, "resultado em cache")

    def test_cache_miss_chama_api_e_armazena_com_ttl_86400(self):
        """Cache miss → API chamada → resultado armazenado com TTL de 86.400s."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None  # cache miss

        mock_doc = MagicMock()
        mock_doc.document.derived_struct_data.get.side_effect = lambda k, d=None: (
            [{"content": "Base legal encontrada"}] if k == "extractive_answers" else d
        )

        mock_response = MagicMock()
        mock_response.results = [mock_doc]

        mock_search_client = MagicMock()
        mock_search_client.search.return_value = mock_response
        mock_search_client.serving_config_path.return_value = "serving/config/path"

        with self._env_vertex(), \
             patch('chat.integrations.vertex._get_redis', return_value=mock_redis), \
             patch('chat.integrations.vertex.discoveryengine.SearchServiceClient',
                   return_value=mock_search_client), \
             patch('chat.models.AiRequestLog.objects.create'):
            result = self._client().search_documents(_parecer(), "prescrição punitiva CTB")

        mock_search_client.search.assert_called_once()
        mock_redis.setex.assert_called_once()
        _ttl_usado = mock_redis.setex.call_args[0][1]
        self.assertEqual(_ttl_usado, 86_400)
        self.assertIn("Base legal encontrada", result)

    def test_excecao_vertex_retorna_string_sem_estourar(self):
        """Timeout/exceção na API → retorna string de erro sem propagar exceção."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with self._env_vertex(), \
             patch('chat.integrations.vertex._get_redis', return_value=mock_redis), \
             patch('chat.integrations.vertex.discoveryengine.SearchServiceClient',
                   side_effect=Exception("Connection timeout")), \
             patch('django.core.mail.send_mail'):
            result = self._client().search_documents(_parecer(), "prazo decadencial")

        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_sem_project_id_retorna_offline_sem_chamar_api(self):
        """Sem VERTEX_PROJECT_ID → retorna mensagem 'RAG Offline' sem chamar API."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop('VERTEX_PROJECT_ID', None)
            os.environ.pop('VERTEX_DATA_STORE_ID', None)
            with patch('chat.integrations.vertex.discoveryengine.SearchServiceClient') as mock_api:
                result = self._client().search_documents(_parecer(), "qualquer")
        mock_api.assert_not_called()
        self.assertIn("Offline", result)


# ── Perplexity ───────────────────────────────────────────────────────────────

class TestPerplexityCache(unittest.TestCase):
    """Cache Redis para Perplexity: hit evita chamada HTTP; miss chama e cacheia."""

    def _client(self, api_key="pplx-test-key"):
        from chat.integrations.perplexity import PerplexityClient
        c = PerplexityClient()
        c.api_key = api_key
        return c

    def test_sem_api_key_retorna_simulacao(self):
        """Sem PERPLEXITY_API_KEY → retorna texto de simulação, sem chamada HTTP."""
        with patch('requests.post') as mock_post:
            result = self._client(api_key=None).search_tese(_parecer(), "tese")
        mock_post.assert_not_called()
        self.assertIn("Simulação", result)

    def test_cache_hit_nao_chama_api_http(self):
        """Cache hit → requests.post nunca é chamado."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = "jurisprudência em cache"

        with patch('chat.integrations.perplexity._get_redis', return_value=mock_redis), \
             patch('requests.post') as mock_post:
            result = self._client().search_tese(_parecer(), "nulidade de notificação")

        mock_post.assert_not_called()
        self.assertEqual(result, "jurisprudência em cache")

    def test_cache_miss_chama_api_e_armazena_com_ttl_86400(self):
        """Cache miss → requests.post chamado → resultado armazenado com TTL 86.400s."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "REsp 123.456 favorável"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 100},
        }
        mock_response.raise_for_status = MagicMock()

        with patch('chat.integrations.perplexity._get_redis', return_value=mock_redis), \
             patch('requests.post', return_value=mock_response), \
             patch('chat.models.AiRequestLog.objects.create'):
            result = self._client().search_tese(_parecer(), "nulidade de notificação")

        mock_redis.setex.assert_called_once()
        _ttl_usado = mock_redis.setex.call_args[0][1]
        self.assertEqual(_ttl_usado, 86_400)
        self.assertEqual(result, "REsp 123.456 favorável")

    def test_api_retorna_excecao_truncagem_segura(self):
        """requests.post lança exceção → retorna string sem propagar exceção."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with patch('chat.integrations.perplexity._get_redis', return_value=mock_redis), \
             patch('requests.post', side_effect=Exception("Connection refused")):
            result = self._client().search_tese(_parecer(), "tese qualquer")

        self.assertIsInstance(result, str)
        self.assertIn("Erro ao acessar Perplexity", result)

    def test_api_retorna_html_ou_status_erro_nao_quebra(self):
        """Resposta HTTP com raise_for_status() → exceção capturada, retorna fallback."""
        import requests as req_lib
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = req_lib.exceptions.HTTPError("500 Server Error")

        with patch('chat.integrations.perplexity._get_redis', return_value=mock_redis), \
             patch('requests.post', return_value=mock_response):
            result = self._client().search_tese(_parecer(), "tese qualquer")

        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


# ── Celery queues ────────────────────────────────────────────────────────────

class TestCeleryQueues(unittest.TestCase):
    """Verifica que as tasks estão registradas nas filas corretas."""

    def test_processar_fase1_task_fila_fast(self):
        from chat.tasks import processar_fase1_task
        self.assertEqual(processar_fase1_task.queue, 'fast')

    def test_processar_fase2_task_fila_fast(self):
        from chat.tasks import processar_fase2_task
        self.assertEqual(processar_fase2_task.queue, 'fast')

    def test_gerar_parecer_task_fila_heavy(self):
        from chat.tasks import gerar_parecer_task
        self.assertEqual(gerar_parecer_task.queue, 'heavy')

    def test_gerar_parecer_task_max_retries_2(self):
        from chat.tasks import gerar_parecer_task
        self.assertEqual(gerar_parecer_task.max_retries, 2)
