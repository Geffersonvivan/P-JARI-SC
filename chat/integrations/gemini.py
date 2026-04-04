import os
import time
import logging as _logging
from google import genai
from django.core.mail import send_mail
from django.conf import settings

from .perplexity import _p

_log = _logging.getLogger(__name__)

# Limites de tamanho dos campos de texto antes de montar o prompt.
_LIMITES = {
    'admissibilidade': 10_000,
    'tabela_datas':     5_000,
    'analise_tese':    12_000,
    'tese':             3_000,
    'vertex':           6_000,
    'perplexity':       6_000,
}


def _trunc(texto: str, label: str, max_chars: int) -> str:
    """Trunca `texto` a `max_chars` caracteres e loga se houver corte."""
    if not texto:
        return texto or ''
    if len(texto) <= max_chars:
        return texto
    _log.warning("[TRUNC] %s truncado de %d → %d chars", label, len(texto), max_chars)
    return texto[:max_chars] + f'\n… [truncado: {len(texto) - max_chars} chars omitidos]'


class GeminiClient:
    def __init__(self):
        self.api_key = os.environ.get('GEMINI_API_KEY')
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def _call_with_fallback(self, preferred_model, fallback_model, contents, config, fase_label, parecer_obj, start_time):
        """Chama generate_content com fallback automático em caso de 503/429/UNAVAILABLE."""
        import logging as _log_fb
        _log = _log_fb.getLogger(__name__)
        for attempt, model in enumerate([preferred_model, fallback_model]):
            try:
                response = self.client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                if attempt > 0:
                    _log.warning(f"_call_with_fallback [{fase_label}]: fallback para {model} OK")
                self._log_tokens(parecer_obj, response, fase_label, model_name=model, start_time=start_time)
                return response, model
            except Exception as e:
                err_str = str(e)
                _transient = any(x in err_str for x in ('503', '429', 'UNAVAILABLE', 'overloaded', 'Too Many Requests'))
                if _transient and attempt == 0:
                    _log.warning(f"_call_with_fallback [{fase_label}]: {model} indisponível — tentando {fallback_model}")
                    continue
                if "429" in err_str or "Too Many Requests" in err_str:
                    send_mail(
                        subject=f'🚨 JARI ALERTA (COTA GEMINI) — {fase_label}',
                        message=f'A API do Gemini estourou a cota de RPM (Erro 429) na {fase_label}.',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=['geffersonvivan@gmail.com'],
                        fail_silently=True
                    )
                raise

    def _log_tokens(self, parecer_obj, response, fase_nome, model_name=None, start_time=None):
        if not parecer_obj or not response: return
        try:
            from chat.models import AiRequestLog
            usage = getattr(response, 'usage_metadata', None)

            latency_ms = 0
            if start_time:
                latency_ms = int((time.time() - start_time) * 1000)

            is_pdf_defect = False
            if hasattr(response, 'text') and response.text:
                text_lower = response.text.lower()
                if "ilegível" in text_lower or "mal escaneada" in text_lower or "não foi possível ler" in text_lower or "resolução ruim" in text_lower:
                    is_pdf_defect = True

            if usage:
                AiRequestLog.objects.create(
                    parecer_referencia=parecer_obj,
                    user=parecer_obj.user,
                    provider='Gemini',
                    fase=fase_nome,
                    input_tokens=getattr(usage, 'prompt_token_count', 0),
                    output_tokens=getattr(usage, 'candidates_token_count', 0),
                    latency_ms=latency_ms,
                    model_name=model_name,
                    is_pdf_defect=is_pdf_defect
                )
        except Exception as e:
            _log.error("Erro ao logar tokens Gemini: %s", e)

    def upload_file(self, file_path):
        if not self.client or not file_path:
            return None

        import tempfile
        import logging
        from django.core.files.storage import default_storage
        from django.core.cache import cache

        _log = logging.getLogger(__name__)

        # Normaliza FieldFile para string
        path_str = file_path.name if hasattr(file_path, 'name') else str(file_path)

        if not path_str or "upload_simulado" in path_str:
            return None

        # --- FIX 2: Cache Redis do file handle Gemini ---
        # Gemini mantém arquivos por 48h; cache por 23h para margem segura.
        try:
            _file_size = default_storage.size(path_str)
            _cache_key = f"gemini_file:{path_str}:{_file_size}"
            _cached_name = cache.get(_cache_key)
            if _cached_name:
                try:
                    cached_gemini_file = self.client.files.get(name=_cached_name)
                    _state = getattr(getattr(cached_gemini_file, 'state', None), 'name', 'ACTIVE')
                    if _state == 'ACTIVE':
                        _log.info(f"upload_file [CACHE HIT] {path_str} → {_cached_name}")
                        return cached_gemini_file
                    else:
                        cache.delete(_cache_key)
                except Exception:
                    cache.delete(_cache_key)
        except Exception:
            _cache_key = None

        temp_path = None
        compressed_path = None
        _t_start = time.monotonic()
        try:
            # Baixa do Storage (local ou S3/GCS) para um arquivo temporário em disco
            with default_storage.open(path_str, 'rb') as f_in:
                fd, temp_path = tempfile.mkstemp(suffix=".pdf")
                with os.fdopen(fd, 'wb') as f_out:
                    f_out.write(f_in.read())
            _t_download = time.monotonic()
            _log.info(f"upload_file [PERF] download {path_str}: {_t_download - _t_start:.2f}s ({os.path.getsize(temp_path)//1024}KB)")

            # Comprime o PDF antes do upload para reduzir tempo de transferência
            upload_path = temp_path  # default: sem compressão
            _is_repaired = False
            try:
                import fitz  # PyMuPDF
                size_original = os.path.getsize(temp_path)
                fitz.TOOLS.reset_mupdf_warnings()
                doc = fitz.open(temp_path)
                # Captura e registra warnings MuPDF (xref corrompido, etc.) sem poluir stderr
                _mupdf_warns = fitz.TOOLS.mupdf_warnings()
                if _mupdf_warns:
                    _log.warning(f"upload_file: MuPDF warnings em {path_str}: {_mupdf_warns.strip()}")
                # PDF reparado → garbage=4 reconstrói o xref do zero (resolve corrupção)
                # PDF normal    → garbage=3 é suficiente e mais rápido
                _is_repaired = getattr(doc, 'is_repaired', False)
                _garbage = 4 if _is_repaired else 3
                fd2, compressed_path = tempfile.mkstemp(suffix=".pdf")
                os.close(fd2)
                doc.save(compressed_path, deflate=True, deflate_images=True,
                         deflate_fonts=True, garbage=_garbage, clean=True)
                doc.close()
                size_compressed = os.path.getsize(compressed_path)
                reduction = (1 - size_compressed / size_original) * 100
                _t_compress = time.monotonic()
                _log.info(
                    f"upload_file [PERF] compress {path_str} {size_original//1024}KB → "
                    f"{size_compressed//1024}KB ({reduction:.0f}% redução)"
                    f"{' [xref reparado]' if _is_repaired else ''}"
                    f" — {_t_compress - _t_download:.2f}s"
                )
                upload_path = compressed_path

                # --- FIX 1: Persiste PDF reparado de volta ao storage ---
                # Substitui o arquivo corrompido pelo reparado para eliminar o reparo futuro.
                if _is_repaired:
                    try:
                        # Resolve caminho absoluto para storage local
                        from django.conf import settings as _settings
                        _abs_path = None
                        if hasattr(default_storage, 'path'):
                            try:
                                _abs_path = default_storage.path(path_str)
                            except NotImplementedError:
                                pass
                        if _abs_path:
                            import shutil
                            shutil.copy2(compressed_path, _abs_path)
                        else:
                            # GCS ou outro storage remoto: delete + save com mesmo nome
                            from django.core.files.base import File as DjangoFile
                            default_storage.delete(path_str)
                            with open(compressed_path, 'rb') as _f_rep:
                                default_storage.save(path_str, DjangoFile(_f_rep))
                        _log.info(f"upload_file [REPAIR] PDF reparado salvo de volta em {path_str}")
                    except Exception as _e_rep:
                        _log.warning(f"upload_file [REPAIR] falhou ao persistir PDF reparado: {_e_rep}")

            except Exception as e:
                _log.warning(f"upload_file: compressão falhou para {path_str}: {e} — usando original")
                _t_compress = time.monotonic()

            # Faz o upload pro ecossistema do Gemini com MIME type explícito
            gemini_file = self.client.files.upload(
                file=upload_path,
                config={'mime_type': 'application/pdf'},
            )
            _t_upload = time.monotonic()
            _log.info(f"upload_file [PERF] gemini_upload {path_str}: {_t_upload - _t_compress:.2f}s")

            # Aguarda o arquivo ficar ACTIVE (processamento assíncrono do Gemini)
            max_wait = 60  # segundos
            waited = 0
            while getattr(getattr(gemini_file, 'state', None), 'name', 'ACTIVE') == 'PROCESSING':
                if waited >= max_wait:
                    _log.warning(f"upload_file: arquivo {path_str} ainda PROCESSING após {max_wait}s — abortando")
                    return None
                time.sleep(2)
                waited += 2
                gemini_file = self.client.files.get(name=gemini_file.name)

            _t_total = time.monotonic()
            _log.info(f"upload_file [PERF] TOTAL {path_str}: {_t_total - _t_start:.2f}s (active_wait={waited}s) state={getattr(getattr(gemini_file, 'state', None), 'name', '?')}")

            # Armazena no cache Redis para reuso nas próximas fases (TTL 23h)
            if _cache_key and getattr(getattr(gemini_file, 'state', None), 'name', '') == 'ACTIVE':
                try:
                    cache.set(_cache_key, gemini_file.name, timeout=23 * 3600)
                except Exception:
                    pass

            return gemini_file
        except Exception as e:
            _log.warning(f"upload_file falhou para {path_str}: {e}")
            return None
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
            if compressed_path and os.path.exists(compressed_path):
                os.remove(compressed_path)

    def extract_fase1_fields(self, parecer_obj):
        """
        Fase 1 — Auto-preenchimento: extrai campos estruturados dos PDFs via Gemini.
        Retorna dict com campos + nível de confiança ('alta'|'baixa'|'nulo').
        Retorna None se Gemini indisponível ou extração falhar.
        """
        if not self.client:
            return None

        system_instruction = (
            "Você é um extrator de dados jurídicos para o sistema P-JARI/SC.\n"
            "Analise os documentos PDF anexados e extraia EXCLUSIVAMENTE os campos solicitados.\n"
            "REGRAS ABSOLUTAS:\n"
            "1. NUNCA invente ou deduza valores — se não encontrar, use null.\n"
            "2. Datas SEMPRE no formato DD/MM/AAAA. Se encontrar em outro formato, converta.\n"
            "3. Confiança: 'alta' = encontrou explicitamente no documento; "
            "'baixa' = inferido/ambíguo/múltiplos valores; 'nulo' = não encontrado.\n"
            "4. Retorne EXCLUSIVAMENTE um JSON válido, sem texto adicional, sem markdown."
        )

        prompt_text = (
            "Extraia dos documentos em anexo os seguintes campos e retorne um JSON com esta estrutura exata:\n\n"
            "{\n"
            '  "pa": "número do processo administrativo (ex: 2024/00123) ou null",\n'
            '  "pa_conf": "alta|baixa|nulo",\n'
            '  "sgpe": "número SGPE ou null",\n'
            '  "sgpe_conf": "alta|baixa|nulo",\n'
            '  "prazo_final": "data limite para protocolo do recurso JARI em DD/MM/AAAA ou null",\n'
            '  "prazo_final_conf": "alta|baixa|nulo",\n'
            '  "data_protocolo": "data em que o recurso foi protocolado em DD/MM/AAAA ou null",\n'
            '  "data_protocolo_conf": "alta|baixa|nulo",\n'
            '  "paginas_defesa": "intervalo de páginas da defesa recursal (ex: 15-24) ou null",\n'
            '  "paginas_defesa_conf": "alta|baixa|nulo",\n'
            '  "recorrente": "nome completo do condutor ou proprietário recorrente ou null",\n'
            '  "recorrente_conf": "alta|baixa|nulo"\n'
            "}\n\n"
            "Não retorne nada além do JSON."
        )

        import logging as _logging
        _log = _logging.getLogger(__name__)

        contents = [prompt_text]

        # Upload paralelo dos PDFs para reduzir o tempo de espera
        import concurrent.futures as _cf
        paths_para_upload = []
        for path_field in [parecer_obj.autuacao_pdf_path, parecer_obj.consolidado_pdf_path]:
            _path = _p(path_field)
            if _path and "upload_simulado" not in _path:
                paths_para_upload.append(_path)

        uploaded_files = []
        if paths_para_upload:
            with _cf.ThreadPoolExecutor(max_workers=len(paths_para_upload)) as ex:
                futures = {ex.submit(self.upload_file, p): p for p in paths_para_upload}
                for fut in _cf.as_completed(futures):
                    f = fut.result()
                    if f:
                        uploaded_files.append(f)
                    else:
                        _log.warning(f"extract_fase1_fields: upload falhou para {futures[fut]}")

        pdfs_anexados = len(uploaded_files)
        for f in uploaded_files:
            contents.insert(0, f)

        if pdfs_anexados == 0:
            _log.warning(f"extract_fase1_fields: nenhum PDF anexado para parecer={parecer_obj.id} — abortando")
            return None

        _log.info(f"extract_fase1_fields: {pdfs_anexados} PDF(s) anexado(s) para parecer={parecer_obj.id}")

        try:
            import json as _json
            response = self.client.models.generate_content(
                model='gemini-2.0-flash',
                contents=contents,
                config={'system_instruction': system_instruction},
            )
            raw = response.text.strip()
            _log.info(f"extract_fase1_fields: Gemini raw response (100 chars): {raw[:100]}")
            # Remove markdown code fences se o modelo as incluir
            if raw.startswith('```'):
                raw = raw.split('\n', 1)[-1]
                raw = raw.rsplit('```', 1)[0].strip()
            dados = _json.loads(raw)
            # Se todos os campos extraíveis são null, retorna None para não exibir form vazio
            campos_extraiveis = ["pa", "sgpe", "prazo_final", "data_protocolo", "paginas_defesa", "recorrente"]
            if all(dados.get(c) is None for c in campos_extraiveis):
                _log.warning(f"extract_fase1_fields: todos os campos retornaram null para parecer={parecer_obj.id}")
                return None
            return dados
        except Exception as e:
            _log.warning(f"extract_fase1_fields falhou: {e}")
            return None

    def generate_phase2_report(self, parecer_obj, contexto_textual_datas):
        """
        Retorna um dict com campos estruturados + tabela_markdown.
        Usa response_schema para eliminar regex frágil no parsing.
        Em caso de falha total retorna dict com campo 'erro'.
        """
        if not self.client:
            return {'erro': 'Cliente Gemini não configurado.', 'tabela_markdown': 'Simulação: sem cliente.'}

        from google.genai import types as _gtypes

        # ── Schema estruturado ────────────────────────────────────────────────
        _schema = _gtypes.Schema(
            type=_gtypes.Type.OBJECT,
            properties={
                'recorrente': _gtypes.Schema(
                    type=_gtypes.Type.STRING,
                    description='Nome do condutor ou proprietário identificado no PDF. "NÃO LOCALIZADO" se ausente.',
                ),
                'tipo_penalidade': _gtypes.Schema(
                    type=_gtypes.Type.STRING,
                    enum=['multa', 'advertencia', 'suspensao', 'cassacao', 'nao_determinado'],
                    description='Tipo da autuação conforme documento.',
                ),
                'data_conclusao_multa': _gtypes.Schema(
                    type=_gtypes.Type.STRING,
                    description='DD/MM/AAAA ou NAO_SE_APLICA — data de conclusão do processo de multa.',
                ),
                'tem_flagrante': _gtypes.Schema(
                    type=_gtypes.Type.STRING,
                    enum=['SIM', 'NAO', 'NAO_DETERMINADO'],
                    description='A autuação foi lavrada em flagrante?',
                ),
                'data_conhecimento_infracao': _gtypes.Schema(
                    type=_gtypes.Type.STRING,
                    description='DD/MM/AAAA ou NAO_SE_APLICA — data em que o órgão tomou ciência (art. 282 §6º-A CTB).',
                ),
                'data_totalizacao_pontos': _gtypes.Schema(
                    type=_gtypes.Type.STRING,
                    description=(
                        'DD/MM/AAAA ou NAO_SE_APLICA — data de totalização de pontos que gerou a suspensão '
                        '(logica_jari §221). Preencher APENAS se tipo_penalidade=suspensao E o documento indicar '
                        'que a suspensão originou-se de acúmulo de pontos; caso contrário, NAO_SE_APLICA.'
                    ),
                ),
                'data_infracao_extraida': _gtypes.Schema(
                    type=_gtypes.Type.STRING,
                    description='DD/MM/AAAA ou NAO_SE_APLICA — data da infração (tipo INFRACAO) identificada nos documentos.',
                ),
                'data_notificacao_extraida': _gtypes.Schema(
                    type=_gtypes.Type.STRING,
                    description='DD/MM/AAAA ou NAO_SE_APLICA — data da primeira notificação (NA ou NP, a mais antiga) identificada nos documentos.',
                ),
                'tabela_markdown': _gtypes.Schema(
                    type=_gtypes.Type.STRING,
                    description=(
                        'Saída completa em Markdown para exibição ao julgador. '
                        'Deve conter: #### 1. Linha do Tempo Mínima (tabela com colunas Data|Tipo|Descritivo|Origem|Observações), '
                        '#### 2. Tabela de Datas Sensíveis para Prazos (colunas Tipo|Data|Descritivo|Origem|Observações), '
                        'e #### Atenção do Membro Julgador (bullets com divergências/NÃO LOCALIZADOS). '
                        'Rótulos canônicos de Tipo: INFRACAO|NA|NP|INSTAURACAO|PROTOCOLO|SESSAO|PRAZO|CONCLUSAO_MULTA|DECISAO|OUTRO.'
                    ),
                ),
            },
            required=['recorrente', 'tipo_penalidade', 'tem_flagrante', 'tabela_markdown'],
        )

        system_instruction = (
            "SYSTEM P-JARI - FASE 2 (DIR - INTEGRIDADE/REGULARIDADE)\n"
            "Sua função é organizar as datas essenciais do processo, garantindo base objetiva para análise de prazos na Fase 3.\n\n"
            "REGRAS DE CLASSIFICAÇÃO:\n"
            "1. Utilize o Bloco A (Informado pelo Julgador) SEMPRE, ainda que não haja documento equivalente.\n"
            "2. Utilize o Bloco B (Extraído do PDF via Python em anexo).\n"
            "3. Se houver mais de uma data para o mesmo evento, liste TODAS numerando como POSSÍVEL (1), (2), sem escolher 'a verdadeira'.\n"
            "4. Se não encontrar um tipo essencial (Ex: Notificação, Julgamento), escreva 'NÃO LOCALIZADO - [tipo]' na coluna Observações.\n"
            "5. NUNCA declare 'erro', 'nulidade' ou 'conflito'; apenas anote 'Divergente; julgador deve avaliar na Fase 3'.\n"
            "6. Preencha TODOS os campos do JSON. Para datas ausentes use NAO_SE_APLICA. Para recorrente ausente use NÃO LOCALIZADO.\n"
            "7. No campo tabela_markdown, use rótulos canônicos MAIÚSCULOS na coluna Tipo: "
            "INFRACAO|NA|NP|INSTAURACAO|PROTOCOLO|SESSAO|PRAZO|CONCLUSAO_MULTA|DECISAO|TOTALIZACAO_PONTOS|OUTRO — sem variações.\n"
            "8. data_totalizacao_pontos: preencher APENAS quando tipo_penalidade=suspensao E o documento indicar "
            "explicitamente que a suspensão originou-se de acúmulo de pontos (art. 261 CTB). Caso contrário: NAO_SE_APLICA.\n"
            "Escreva de forma fria e neutra."
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
            "Cruze as origens. Dê prioridade a não omitir nada. "
            "Retorne o JSON conforme o schema: campos estruturados + tabela_markdown completa."
        )

        contents = [prompt_text]

        from django.core.files.storage import default_storage
        for path_field, label in [
            (parecer_obj.autuacao_pdf_path, 'autuacao'),
            (parecer_obj.consolidado_pdf_path, 'consolidado'),
            (parecer_obj.ata_pdf_path, 'ata'),
        ]:
            _path = _p(path_field)
            if not _path or "upload_simulado" in _path:
                continue
            if label == 'consolidado' and _p(parecer_obj.autuacao_pdf_path) == _path:
                continue  # mesmo arquivo, evita upload duplicado
            try:
                if default_storage.exists(_path):
                    f = self.upload_file(_path)
                    if f:
                        contents.insert(0, f)
            except Exception:
                pass

        try:
            import json as _json
            start_time = time.time()
            response, _ = self._call_with_fallback(
                'gemini-2.5-pro', 'gemini-2.0-flash',
                contents,
                {
                    'system_instruction': system_instruction,
                    'response_mime_type': 'application/json',
                    'response_schema': _schema,
                },
                'Fase 2 (DIR)', parecer_obj, start_time,
            )
            return _json.loads(response.text)
        except Exception as e:
            return {'erro': str(e), 'tabela_markdown': f"Erro ao acessar Gemini na Fase 2: {e}.\n"}

    def generate_phase3_report(self, parecer_obj, matematica_detalhes):
        if not self.client:
             return "Simulação: Admissibilidade checada. Tempestivo. Prescrições Afastadas."

        # Prompt versionado — editar em chat/prompts/phase_3.py
        from chat.prompts.phase_3 import SYSTEM_INSTRUCTION as system_instruction

        data_sessao_str = parecer_obj.data_sessao.strftime('%d/%m/%Y') if parecer_obj.data_sessao else 'NÃO INFORMADO'
        prazo_final_str = parecer_obj.prazo_final.strftime('%d/%m/%Y') if parecer_obj.prazo_final else 'NÃO INFORMADO'
        data_protocolo_str = parecer_obj.data_protocolo.strftime('%d/%m/%Y') if parecer_obj.data_protocolo else 'NÃO INFORMADO'

        _tab_f3 = _trunc(parecer_obj.tabela_datas_sensiveis or '', 'tabela_datas', _LIMITES['tabela_datas'])
        prompt_text = (
            f"=== Respostas da Fase 1 ===\n"
            f"1. Sessão JARI: {data_sessao_str}\n"
            f"4. Prazo Final Recurso: {prazo_final_str}\n"
            f"5. Protocolo Recurso: {data_protocolo_str}\n\n"
            f"=== Fatos Documentais (Fase 2) ===\n"
            f"{_tab_f3 or 'Não há tabela F2 gerada.'}\n\n"
            f"=== Flags Matemáticas e Intervalos do Python (Fase 3) ===\n"
            f"{matematica_detalhes}\n\n"
            "Aplique estritamente o roteiro obrigatório e devolva os resultados solicitados baseando-se unicamente nas flags matemáticas acima."
        )

        start_time = time.time()
        response, _ = self._call_with_fallback(
            'gemini-2.5-pro', 'gemini-2.0-flash',
            [prompt_text], {'system_instruction': system_instruction},
            'Fase 3 (Avaliação Prazos)', parecer_obj, start_time
        )
        return response.text

    def extract_tese(self, parecer_obj):
        if not self.client:
             return "Simulação: O recorrente alega a não aferição do radar pelo INMETRO."

        # Prompt versionado — editar em chat/prompts/phase_4.py
        from chat.prompts.phase_4 import SYSTEM_INSTRUCTION_EXTRACT as system_instruction

        admissibilidade_julgador = _trunc(
            parecer_obj.admissibilidade_texto or 'Não informada.',
            'admissibilidade', _LIMITES['admissibilidade'],
        )
        prompt_text = (
            f"--- DECISÃO DE ADMISSIBILIDADE E PRAZOS (FASE 3) ---\n"
            f"Os resultados abaixo refletem a escolha SOBERANA do membro julgador. Você NÃO pode contrariá-los:\n"
            f"{admissibilidade_julgador}\n\n"
            f"--- INSTRUÇÃO DE EXTRAÇÃO ---\n"
            f"Verifique o resultado acima. Se a decisão do julgador apontar que o recurso é INTEMPESTIVO (INTEMPESTIVIDADE DO RECURSO: CONFIGURADA), PRESCRITO (Prescrição Punitiva ou Intercorrente: SIM) ou DECADENTE (Decadência: SIM), você DEVE ABORTAR a leitura do recurso e responder APENAS E EXATAMENTE:\n"
            f"'MÉRITO PREJUDICADO. Teses defensivas prejudicadas em razão da extinção da pretensão punitiva ou inadmissibilidade recursal.'\n\n"
            f"Caso contrário (INTEMPESTIVIDADE DO RECURSO: NÃO CONFIGURADA e Prescrições/Decadência: NÃO), localize a defesa nas páginas indicadas: {parecer_obj.paginas_defesa}.\n\n"
            "Liste AS TESES jurídicas apresentadas de forma isolada e em tópicos (bullet points). "
            "Apenas descreva o que foi pedido, detalhando cada ponto separadamente. Reforçando: não gere respostas, julgamentos ou mérito agora, apenas a LISTAGEM e classificação das teses alegadas no Recurso."
        )

        contents = [prompt_text]

        if parecer_obj.autuacao_pdf_path and "upload_simulado" not in _p(parecer_obj.autuacao_pdf_path):
            file_autuacao = self.upload_file(_p(parecer_obj.autuacao_pdf_path))
            if file_autuacao:
                contents.insert(0, file_autuacao)

        if parecer_obj.consolidado_pdf_path and "upload_simulado" not in _p(parecer_obj.consolidado_pdf_path) and _p(parecer_obj.consolidado_pdf_path) != _p(parecer_obj.autuacao_pdf_path):
            file_consolidado = self.upload_file(_p(parecer_obj.consolidado_pdf_path))
            if file_consolidado:
                contents.insert(0, file_consolidado)

        try:
            start_time = time.time()
            model_to_use = 'gemini-2.5-flash'
            response = self.client.models.generate_content(
                model=model_to_use,
                contents=contents,
                config={'system_instruction': system_instruction}
            )
            self._log_tokens(parecer_obj, response, 'Fase 4 (Extração)', model_name=model_to_use, start_time=start_time)
            return response.text.strip()
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "Too Many Requests" in err_str:
                send_mail(
                    subject='🚨 JARI ALERTA (COTA GEMINI)',
                    message='A API do Gemini estourou a cota de RPM (Erro 429).',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=['geffersonvivan@gmail.com'],
                    fail_silently=True
                )
            return f"Erro ao extrair tese via LLM: {str(e)}"

    def refine_tese(self, parecer_obj, user_hint):
        if not self.client:
             return f"Simulação de Refinamento: O recorrente alega que {user_hint}."

        # Prompt versionado — editar em chat/prompts/phase_4.py
        from chat.prompts.phase_4 import SYSTEM_INSTRUCTION_REFINE as system_instruction

        prompt_text = (
            f"Por favor, releia a defesa do recorrente nas páginas: {parecer_obj.paginas_defesa}.\n\n"
            f"O assessor revisor apontou o seguinte: '{user_hint}'.\n\n"
            "Com base nessa instrução, escreva um NOVO resumo claro e direto informando as alegações da defesa."
        )

        contents = [prompt_text]

        if parecer_obj.autuacao_pdf_path and "upload_simulado" not in _p(parecer_obj.autuacao_pdf_path):
            file_autuacao = self.upload_file(_p(parecer_obj.autuacao_pdf_path))
            if file_autuacao:
                contents.insert(0, file_autuacao)

        if parecer_obj.consolidado_pdf_path and "upload_simulado" not in _p(parecer_obj.consolidado_pdf_path) and _p(parecer_obj.consolidado_pdf_path) != _p(parecer_obj.autuacao_pdf_path):
            file_consolidado = self.upload_file(_p(parecer_obj.consolidado_pdf_path))
            if file_consolidado:
                contents.insert(0, file_consolidado)

        try:
            start_time = time.time()
            model_to_use = 'gemini-2.5-flash'
            response = self.client.models.generate_content(
                model=model_to_use,
                contents=contents,
                config={'system_instruction': system_instruction}
            )
            self._log_tokens(parecer_obj, response, 'Fase 4 (Refinamento)', model_name=model_to_use, start_time=start_time)
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
            _log.error("Erro ao gerar cache key: %s", e)
            return "erro_chave"

    def analyze_tese(self, parecer_obj, tese, perplexity_result, vertex_result):
        # DIV-06: usar flags do julgador (soberanas); fallback para automáticas se julgador não escolheu
        _punit  = parecer_obj.julgador_prescricao_punitiva      if parecer_obj.julgador_prescricao_punitiva      is not None else parecer_obj.has_prescricao_punitiva
        _inter  = parecer_obj.julgador_prescricao_intercorrente if parecer_obj.julgador_prescricao_intercorrente is not None else parecer_obj.has_prescricao_intercorrente
        _decad  = parecer_obj.julgador_decadencia               if parecer_obj.julgador_decadencia               is not None else parecer_obj.has_decadencia
        _temp   = parecer_obj.julgador_tempestivo               if parecer_obj.julgador_tempestivo               is not None else parecer_obj.is_tempestivo
        # Verifica Prejudicialidade com base nas escolhas efetivas do julgador
        is_prejudicado = (
            _punit or _inter or _decad or (_temp is False)
        )
        if is_prejudicado:
            return "Teses defensivas prejudicadas em razão da extinção da pretensão punitiva ou inadmissibilidade recursal."

        if not self.client:
             return "Simulação: Resultar em: Conclusão: acolhida/não acolhida. (acolhida)"

        # Prompt versionado — editar em chat/prompts/phase_4.py
        from chat.prompts.phase_4 import SYSTEM_INSTRUCTION_ANALYZE as system_instruction

        _vrtx_t = _trunc(vertex_result or '',      'vertex',     _LIMITES['vertex'])
        _pplx_t = _trunc(perplexity_result or '',  'perplexity', _LIMITES['perplexity'])
        _tese_t = _trunc(tese or '',               'tese',       _LIMITES['tese'])

        prompt_text = (
            f"Processo: {parecer_obj.pa} | SGPE: {parecer_obj.sgpe}\n"
            f"Teses Listadas: {_tese_t}\n\n"
            f"Documentos Anexos: Documento 'consolidado' + 'autuação'\n\n"
            f"RAG Inventário Normativo Google (VERTEX): {_vrtx_t}\n"
            f"Pesquisa Auxiliar (PERPLEXITY): {_pplx_t}\n\n"
            "Exponha as alternativas (a) e (b) justificadas para cada tese isoladamente.\n"
            "Ao final, liste as tags [DECISAO_TESE_X] para todas as teses analisadas (uma por linha)."
        )

        contents = [prompt_text]

        # Anexar os PDFs no prompt se existirem
        from django.core.files.storage import default_storage
        if parecer_obj.autuacao_pdf_path and "upload_simulado" not in _p(parecer_obj.autuacao_pdf_path):
            if default_storage.exists(_p(parecer_obj.autuacao_pdf_path)):
                file_autuacao = self.upload_file(_p(parecer_obj.autuacao_pdf_path))
                if file_autuacao:
                    contents.insert(0, file_autuacao)

        if parecer_obj.consolidado_pdf_path and "upload_simulado" not in _p(parecer_obj.consolidado_pdf_path):
            if default_storage.exists(_p(parecer_obj.consolidado_pdf_path)):
                file_consolidado = self.upload_file(_p(parecer_obj.consolidado_pdf_path))
                if file_consolidado:
                    contents.insert(0, file_consolidado)

        try:
            start_time = time.time()
            response, _ = self._call_with_fallback(
                'gemini-2.5-pro', 'gemini-2.0-flash',
                contents, {'system_instruction': system_instruction},
                'Fase 4 (Análise Mérito)', parecer_obj, start_time
            )
            return response.text
        except Exception as e:
            return f"Erro ao acessar Gemini na Fase 4: {str(e)}.\n"

    def generate_parecer_gemini(self, parecer_obj, tese, perplexity_result, vertex_result="", task_id=None):
        """Gerador alternativo via Gemini 2.5-flash. Fluxo principal usa AnthropicClient."""
        relator_name = "NÃO INFORMADO"
        if parecer_obj.user:
            relator_name = f"{parecer_obj.user.first_name} {parecer_obj.user.last_name}".strip()
            if not relator_name:
                relator_name = parecer_obj.user.username
        relator_name = relator_name.upper()

        status_deferimento = "DEFERIDO" if "PREJUDICADO" in tese else "INDEFERIDO/DEFERIDO"
        if not self.client:
            return f"**RESULTADO SIMULADO:** {status_deferimento}"

        # Prompt versionado — editar em chat/prompts/phase_5.py
        from chat.prompts.phase_5 import build_system_instruction
        system_instruction = build_system_instruction(relator_name)

        _adm  = _trunc(parecer_obj.admissibilidade_texto or '',                    'admissibilidade', _LIMITES['admissibilidade'])
        _tab  = _trunc(getattr(parecer_obj, 'tabela_datas_sensiveis', '') or '',  'tabela_datas',    _LIMITES['tabela_datas'])
        _anal = _trunc(parecer_obj.analise_tese_texto or '',                      'analise_tese',    _LIMITES['analise_tese'])
        _tese = _trunc(tese or '',                                                'tese',            _LIMITES['tese'])
        _vrtx = _trunc(vertex_result or '',                                       'vertex',          _LIMITES['vertex'])
        _pplx = _trunc(perplexity_result or '',                                   'perplexity',      _LIMITES['perplexity'])

        # M2-FIX: Detecta divergências entre flags do julgador e resultados automáticos.
        _divs_g = []
        if parecer_obj.julgador_prescricao_punitiva is not None and parecer_obj.julgador_prescricao_punitiva != parecer_obj.has_prescricao_punitiva:
            _divs_g.append(f"  • Prescrição Punitiva: automático={'SIM' if parecer_obj.has_prescricao_punitiva else 'NÃO'} → julgador={'SIM' if parecer_obj.julgador_prescricao_punitiva else 'NÃO'}")
        if parecer_obj.julgador_prescricao_intercorrente is not None and parecer_obj.julgador_prescricao_intercorrente != parecer_obj.has_prescricao_intercorrente:
            _divs_g.append(f"  • Prescrição Intercorrente: automático={'SIM' if parecer_obj.has_prescricao_intercorrente else 'NÃO'} → julgador={'SIM' if parecer_obj.julgador_prescricao_intercorrente else 'NÃO'}")
        if parecer_obj.julgador_decadencia is not None and parecer_obj.julgador_decadencia != parecer_obj.has_decadencia:
            _divs_g.append(f"  • Decadência: automático={'SIM' if parecer_obj.has_decadencia else 'NÃO/NÃO SE APLICA'} → julgador={'SIM' if parecer_obj.julgador_decadencia else 'NÃO'}")
        if parecer_obj.julgador_tempestivo is not None and parecer_obj.julgador_tempestivo != parecer_obj.is_tempestivo:
            _divs_g.append(f"  • Tempestividade: automático={'TEMPESTIVO' if parecer_obj.is_tempestivo else 'INTEMPESTIVO'} → julgador={'TEMPESTIVO' if parecer_obj.julgador_tempestivo else 'INTEMPESTIVO'}")
        _aviso_diverg_g = ""
        if _divs_g:
            _aviso_diverg_g = (
                "⚠️ DIVERGÊNCIA JULGADOR × AUTOMÁTICO — ATENÇÃO OBRIGATÓRIA:\n"
                "O julgador INVERTEU o resultado automático nos itens abaixo. "
                "As FLAGS JARIMATH soberanas já refletem a decisão final. "
                "O texto de Admissibilidade abaixo pode conter os resultados AUTOMÁTICOS originais — "
                "NÃO os use: use EXCLUSIVAMENTE as FLAGS soberanas acima.\n"
                + "\n".join(_divs_g) + "\n\n"
            )

        # S5-FIX (Gemini fallback): quando há inversão pelo julgador, sinaliza explicitamente
        # que o admissibilidade_texto contém resultado automático superado.
        if _divs_g:
            _adm_g_prompt = (
                "🚫 RESULTADO DO TEXTO ABAIXO ESTÁ SUPERADO PELA DECISÃO DO JULGADOR 🚫\n"
                "Use APENAS os dados de datas e prazos para fundamentação. "
                "A conclusão correta está nas FLAGS/RESULTADO OBRIGATÓRIO acima.\n\n"
                f"{_adm}"
            )
        else:
            _adm_g_prompt = _adm

        prompt = (
            f"---- DADOS PARA PREENCHER O CABEÇALHO (Obrigatório) ----\n"
            f"PROCESSO (PA): {parecer_obj.pa}\n"
            f"SGPE: {parecer_obj.sgpe}\n"
            f"RECORRENTE (Interessado): {parecer_obj.recorrente}\n"
            f"DATA SESSÃO: {parecer_obj.data_sessao.strftime('%d/%m/%Y') if parecer_obj.data_sessao else ''}\n\n"
            f"---- PACOTE DE FLAGS MATEMÁTICAS E ADMISSIBILIDADE (Soberanas para o Resultado e Capítulos 3.1 a 3.3) ----\n"
            f"{_aviso_diverg_g}"
            f"A T E N Ç Ã O: Os resultados abaixo refletem a escolha exclusiva do MEMBRO JULGADOR. Você está ESTRITAMENTE VINCULADO a usar estas conclusões e NÃO pode contrariá-las em nenhuma hipótese.\n"
            f"{_adm_g_prompt}\n\n"
            f"---- RESUMO FÁTICO (Para o Relatório e Datas da Prescrição) ----\n"
            f"{_tab or 'Vazio.'}\n\n"
            f"---- ANÁLISE DAS TESES E DECISÃO EXIGIDA (Para 'Teses Defensivas') ----\n"
            f"{_anal}\n"
            f"Tese(s) Inicialmente Alegada(s): {_tese}\n\n"
            f"---- BASES NORMATIVAS ----\n"
            f"RAG VERTEX: {_vrtx}\n"
            f"PERPLEXITY: {_pplx}\n\n"
            f"Crie o Parecer englobando as seções listadas no sistema EXACTAMENTE com a formatação exigida."
        )

        contents = [prompt]

        # Anexar os PDFs no prompt se existirem para que a IA possa extrair "Interessado" da Autuação
        from django.core.files.storage import default_storage

        if parecer_obj.autuacao_pdf_path and "upload_simulado" not in _p(parecer_obj.autuacao_pdf_path):
            try:
                if default_storage.exists(_p(parecer_obj.autuacao_pdf_path)):
                    file_autuacao = self.upload_file(_p(parecer_obj.autuacao_pdf_path))
                    if file_autuacao:
                        contents.insert(0, file_autuacao)
            except Exception: pass

        if parecer_obj.consolidado_pdf_path and "upload_simulado" not in _p(parecer_obj.consolidado_pdf_path) and _p(parecer_obj.consolidado_pdf_path) != _p(parecer_obj.autuacao_pdf_path):
            try:
                if default_storage.exists(_p(parecer_obj.consolidado_pdf_path)):
                    file_consolidado = self.upload_file(_p(parecer_obj.consolidado_pdf_path))
                    if file_consolidado:
                        contents.insert(0, file_consolidado)
            except Exception: pass

        try:
            start_time = time.time()
            model_to_use = 'gemini-2.5-flash'

            redis_client = None
            if task_id:
                import redis
                import json
                try:
                    redis_client = redis.from_url(getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0'))
                except Exception as e:
                    _log.error("Erro de conexão com Redis: %s", e)

            # Definir limiares de segurança explícitos para BLOCK_NONE (Gemini V1beta/V1) usando nova SDK google-genai
            from google.genai import types
            safety_settings = [
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE)
            ]

            response_stream = self.client.models.generate_content_stream(
                model=model_to_use,
                contents=contents,
                config={
                    'system_instruction': system_instruction,
                    'safety_settings': safety_settings
                }
            )

            full_text = []
            last_chunk = None
            for chunk in response_stream:
                last_chunk = chunk
                try:
                    # Depending on library version, might throw exception if safety blocked
                    chunk_text = getattr(chunk, 'text', '')
                    if chunk_text:
                        full_text.append(chunk_text)
                        if redis_client:
                            import json
                            redis_client.publish(f"stream_{task_id}", json.dumps({
                                'status': 'CHUNK',
                                'text': chunk_text
                            }))
                except Exception as stream_err:
                    _log.error("Erro no streaming do chunk: %s", stream_err)

            final_text = "".join(full_text)
            self._log_tokens(parecer_obj, last_chunk, 'Fase 5 (Parecer)', model_name=model_to_use, start_time=start_time)
            return final_text
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "Too Many Requests" in err_str:
                send_mail(
                    subject='🚨 JARI ALERTA (COTA GEMINI)',
                    message='A API do Gemini estourou a cota de RPM (Erro 429). Ocorreu na Fase 5 (Parecer).',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=['geffersonvivan@gmail.com'],
                    fail_silently=True
                )
            return f"Erro ao acessar Gemini: {str(e)}.\nFalha ao gerar parecer via LLM."

    def audit_parecer(self, parecer_obj):
        if not self.client:
            return "✅ Simulação: Conformidade integral. (Score calculado pelo JariMath)"

        system_instruction = (
            "Você é o Auditor Corregedor do P-JARI/SC (Fase 6 - AUDITORIA).\n"
            "Sua única função é realizar um checklist sobre o Parecer Final submetido, cruzando a compatibilidade narrativa do Relator com a tabela matemática anterior.\n\n"
            "REGRA DE OURO (SOBERANIA DA MATEMÁTICA OBRIGATÓRIA):\n"
            "Não tente recalcular a tempestividade do recurso subtraindo ou somando dias de notificações citadas no texto. "
            "Apenas valide se a conclusão do Relator (Tempestivo/Intempestivo) bate com o resultado da Matemática Obrigatória fornecida no prompt. Se o resultado for SIM (TEMPESTIVO), e o texto falar tempestivo, a nota é 🟢 Conforme. ATENÇÃO MÁXIMA: Se a Matemática acusar Prescrição ou Decadência como SIM, o fato de ser Intempestivo perde a relevância (matéria de ordem pública prevalece), devendo a tempestividade ser considerada 🟢 Conforme se o texto a apontar como prejudicada.\n\n"
            "A Auditoria final apresentada deve ser FORMATADA EXCLUSIVAMENTE EM MARKDOWN (NÃO USE NENHUMA TAG HTML) DE FORMA CLARA, OBJETIVA, DIRETA E VISUALMENTE ATRATIVA.\n"
            "OBRIGATÓRIO: Pule linha DUPLA (\\n\\n) no final de cada item de validação do checklist, para que eles não fiquem aglomerados em um único parágrafo.\n"
            "Classifique de forma estrita cada um dos blocos abaixo. Use ícones ricos como 🟢, 🔴, ⚠️.\n"
            "Exemplo visual: `**1. Identificação Processual:** 🟢 Conforme - O PA e SGPE coincidem com a base.`\n\n"
            "ITENS OBRIGATÓRIOS DO CHECKLIST:\n"
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

        # DIV-08: usar flags efetivas do julgador (soberanas); fallback para automáticas
        _ef_temp  = parecer_obj.julgador_tempestivo               if parecer_obj.julgador_tempestivo               is not None else parecer_obj.is_tempestivo
        _ef_punit = parecer_obj.julgador_prescricao_punitiva      if parecer_obj.julgador_prescricao_punitiva      is not None else parecer_obj.has_prescricao_punitiva
        _ef_inter = parecer_obj.julgador_prescricao_intercorrente if parecer_obj.julgador_prescricao_intercorrente is not None else parecer_obj.has_prescricao_intercorrente
        _ef_decad = parecer_obj.julgador_decadencia               if parecer_obj.julgador_decadencia               is not None else parecer_obj.has_decadencia

        data_protocolo_str = parecer_obj.data_protocolo.strftime('%d/%m/%Y') if parecer_obj.data_protocolo else "Não informada"
        prazo_final_str = parecer_obj.prazo_final.strftime('%d/%m/%Y') if parecer_obj.prazo_final else "Não informado"

        prompt = (
            f"--- MATEMÁTICA OBRIGATÓRIA (Escolhas Soberanas do Julgador) ---\n"
            f"Data do Protocolo Direto (Informado): {data_protocolo_str}\n"
            f"Prazo Final Máximo (Informado/Calculado): {prazo_final_str}\n"
            f"Tempestividade: {'DENTRO DO PRAZO (TEMPESTIVO)' if _ef_temp else 'FORA DO PRAZO (INTEMPESTIVO)'}\n"
            f"Prescrição Punitiva: {'SIM' if _ef_punit else 'NÃO'}\n"
            f"Intercorrente: {'SIM' if _ef_inter else 'NÃO'}\n"
            f"Decadência: {'SIM' if _ef_decad else 'NÃO'}\n\n"
            f"--- PARECER REDIGIDO PELA FASE 5 (O ALVO DA AUDITORIA) ---\n"
            f"{parecer_obj.parecer_final}\n\n"
            f"Execute o Checklist e devolva APENAS as 10 linhas avaliadas."
        )

        try:
            start_time = time.time()
            model_to_use = 'gemini-2.5-flash'
            response = self.client.models.generate_content(
                model=model_to_use,
                contents=[prompt],
                config={'system_instruction': system_instruction, 'temperature': 0.1}
            )
            self._log_tokens(parecer_obj, response, 'Fase 6 (Auditoria)', model_name=model_to_use, start_time=start_time)
            return response.text
        except Exception as e:
            return f"⚠️ Auditoria Qualitativa offline. Resultado puramente matemático operando."
