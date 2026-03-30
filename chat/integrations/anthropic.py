import os
import base64
import logging

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

_log = logging.getLogger(__name__)

# Limites de tamanho dos campos de texto antes de montar o prompt.
# Evita estouro silencioso de contexto da API e garante truncamento previsível.
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


class AnthropicClient:
    def __init__(self):
        self.api_key = os.environ.get('ANTHROPIC_API_KEY')
        self.client = Anthropic(api_key=self.api_key) if self.api_key else None

    def _log_tokens(self, parecer_obj, input_tokens, output_tokens, fase_nome, model_name=None, start_time=None):
        if not parecer_obj: return
        try:
            from chat.models import AiRequestLog
            import time
            latency_ms = 0
            if start_time:
                latency_ms = int((time.time() - start_time) * 1000)

            AiRequestLog.objects.create(
                parecer_referencia=parecer_obj,
                user=parecer_obj.user,
                provider='Anthropic',
                fase=fase_nome,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                model_name=model_name
            )
        except Exception as e:
            print(f"Erro ao logar tokens Anthropic: {e}")

    def get_pdf_content(self, file_path):
        if not file_path: return None
        from django.core.files.storage import default_storage
        try:
            with default_storage.open(file_path, 'rb') as f:
                pdf_data = base64.b64encode(f.read()).decode("utf-8")
                return {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_data
                    }
                }
        except Exception as e:
            print(f"Anthropic PDF encoding error: {e}")
            return None

    def validate_and_generate_parecer(self, parecer_obj, tese, perplexity_result, vertex_result="", task_id=None):
        relator_name = "NÃO INFORMADO"
        if parecer_obj.user:
            relator_name = f"{parecer_obj.user.first_name} {parecer_obj.user.last_name}".strip()
            if not relator_name:
                relator_name = parecer_obj.user.username
        relator_name = relator_name.upper()

        if not self.client:
            import logging
            _log = logging.getLogger(__name__)
            _log.warning("ANTHROPIC_API_KEY não configurada — fallback para GeminiClient.")
            try:
                from chat.integrations.gemini import GeminiClient
                return GeminiClient().generate_parecer_gemini(
                    parecer_obj, tese, perplexity_result, vertex_result, task_id
                )
            except Exception as _fe:
                _log.error(f"Fallback Gemini também falhou: {_fe}")
                return (
                    "⚠️ **ERRO DE CONFIGURAÇÃO: Parecer não gerado.**\n\n"
                    "Nem Anthropic (chave ausente) nem Gemini (fallback) conseguiram gerar o parecer. "
                    "Configure ANTHROPIC_API_KEY ou verifique GOOGLE_API_KEY."
                )

        # Prompt versionado — editar em chat/prompts/phase_5.py
        from chat.prompts.phase_5 import build_system_instruction
        system_instruction = build_system_instruction(relator_name)

        # ── Flags JariMath explícitas (soberanas) ────────────────────────────
        def _flag_val(julgador, automatico):
            return julgador if julgador is not None else automatico

        _f_punit  = _flag_val(parecer_obj.julgador_prescricao_punitiva,      parecer_obj.has_prescricao_punitiva)
        _f_inter  = _flag_val(parecer_obj.julgador_prescricao_intercorrente,  parecer_obj.has_prescricao_intercorrente)
        _f_decad  = _flag_val(parecer_obj.julgador_decadencia,                parecer_obj.has_decadencia)
        _f_temp   = _flag_val(parecer_obj.julgador_tempestivo,                parecer_obj.is_tempestivo)
        _prejudica = _f_punit or _f_inter or _f_decad
        # BUG-A-FIX: ROTA D — tese acolhida na F4 também exige DEFERIDO
        _rota_d_deferido = "RESULTADO EXIGIDO NESTE PARECER: DEFERIDO" in (parecer_obj.analise_tese_texto or "")
        _resultado_obrigatorio = "DEFERIDO" if (_prejudica or _rota_d_deferido) else "INDEFERIDO"

        _flags_block = (
            "🔒 FLAGS JARIMATH — SOBERANAS, INVIOLÁVEIS, NÃO RECALCULE:\n"
            f"• Tempestividade: {'TEMPESTIVO — dentro do prazo' if _f_temp else 'INTEMPESTIVO — fora do prazo'}\n"
            f"• Prescrição Punitiva: {'SIM — CONFIGURADA' if _f_punit else 'NÃO configurada'}\n"
            f"• Prescrição Intercorrente: {'SIM — CONFIGURADA' if _f_inter else 'NÃO configurada'}\n"
            f"• Decadência: {'SIM — CONFIGURADA' if _f_decad else 'NÃO configurada'}\n\n"
            f"🔒 RESULTADO OBRIGATÓRIO DESTE PARECER: {_resultado_obrigatorio}\n"
            f"Escrever qualquer resultado diferente de {_resultado_obrigatorio} é INVÁLIDO e será rejeitado.\n"
        )
        # ─────────────────────────────────────────────────────────────────────

        _adm   = _trunc(parecer_obj.admissibilidade_texto or '',                   'admissibilidade', _LIMITES['admissibilidade'])
        _tab   = _trunc(getattr(parecer_obj, 'tabela_datas_sensiveis', '') or '', 'tabela_datas',    _LIMITES['tabela_datas'])
        _anal  = _trunc(parecer_obj.analise_tese_texto or '',                     'analise_tese',    _LIMITES['analise_tese'])
        _tese  = _trunc(tese or '',                                               'tese',            _LIMITES['tese'])
        _vrtx  = _trunc(vertex_result or '',                                      'vertex',          _LIMITES['vertex'])
        _pplx  = _trunc(perplexity_result or '',                                  'perplexity',      _LIMITES['perplexity'])

        # M2-FIX: Detecta divergências entre flags do julgador e resultados automáticos.
        # Quando o julgador inverteu um resultado, o admissibilidade_texto pode conter o resultado
        # automático antigo — avisamos explicitamente o LLM para ignorá-lo.
        _divs = []
        if parecer_obj.julgador_prescricao_punitiva is not None and parecer_obj.julgador_prescricao_punitiva != parecer_obj.has_prescricao_punitiva:
            _divs.append(f"  • Prescrição Punitiva: automático={'SIM' if parecer_obj.has_prescricao_punitiva else 'NÃO'} → julgador={'SIM' if parecer_obj.julgador_prescricao_punitiva else 'NÃO'}")
        if parecer_obj.julgador_prescricao_intercorrente is not None and parecer_obj.julgador_prescricao_intercorrente != parecer_obj.has_prescricao_intercorrente:
            _divs.append(f"  • Prescrição Intercorrente: automático={'SIM' if parecer_obj.has_prescricao_intercorrente else 'NÃO'} → julgador={'SIM' if parecer_obj.julgador_prescricao_intercorrente else 'NÃO'}")
        if parecer_obj.julgador_decadencia is not None and parecer_obj.julgador_decadencia != parecer_obj.has_decadencia:
            _divs.append(f"  • Decadência: automático={'SIM' if parecer_obj.has_decadencia else 'NÃO/NÃO SE APLICA'} → julgador={'SIM' if parecer_obj.julgador_decadencia else 'NÃO'}")
        if parecer_obj.julgador_tempestivo is not None and parecer_obj.julgador_tempestivo != parecer_obj.is_tempestivo:
            _divs.append(f"  • Tempestividade: automático={'TEMPESTIVO' if parecer_obj.is_tempestivo else 'INTEMPESTIVO'} → julgador={'TEMPESTIVO' if parecer_obj.julgador_tempestivo else 'INTEMPESTIVO'}")
        _aviso_diverg = ""
        if _divs:
            _aviso_diverg = (
                "⚠️ DIVERGÊNCIA JULGADOR × AUTOMÁTICO — ATENÇÃO OBRIGATÓRIA:\n"
                "O julgador INVERTEU o resultado automático nos itens abaixo. "
                "As FLAGS JARIMATH soberanas já refletem a decisão final. "
                "O texto de Admissibilidade abaixo pode conter os resultados AUTOMÁTICOS originais — "
                "NÃO os use: use EXCLUSIVAMENTE as FLAGS soberanas acima.\n"
                + "\n".join(_divs) + "\n\n"
            )

        prompt = (
            f"{_flags_block}\n"
            f"---- DADOS PARA PREENCHER O CABEÇALHO (Obrigatório) ----\n"
            f"PROCESSO (PA): {parecer_obj.pa}\n"
            f"SGPE: {parecer_obj.sgpe}\n"
            f"RECORRENTE (Interessado): {parecer_obj.recorrente}\n"
            f"DATA SESSÃO: {parecer_obj.data_sessao.strftime('%d/%m/%Y') if parecer_obj.data_sessao else ''}\n\n"
            f"---- PACOTE DE ADMISSIBILIDADE E FUNDAMENTAÇÃO (Para Capítulos 3.1 a 3.3) ----\n"
            f"{_aviso_diverg}"
            f"A T E N Ç Ã O: Use para redigir a fundamentação, mas as FLAGS acima prevalecem sempre.\n"
            f"{_adm}\n\n"
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

        content = [{"type": "text", "text": prompt}]

        import time
        try:
            start_time = time.time()
            model_to_use = "claude-sonnet-4-6"

            redis_client = None
            if task_id:
                import redis
                import json
                try:
                    from django.conf import settings
                    redis_client = redis.from_url(getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0'))
                except Exception as e:
                    print(f"Erro de conexão com Redis: {e}")

            full_text = []

            with self.client.messages.stream(
                model=model_to_use,
                max_tokens=4096,
                system=system_instruction,
                messages=[{"role": "user", "content": content}]
            ) as stream:
                for text_chunk in stream.text_stream:
                    if text_chunk:
                        full_text.append(text_chunk)
                        if redis_client:
                            import json
                            redis_client.publish(f"stream_{task_id}", json.dumps({
                                'status': 'CHUNK',
                                'text': text_chunk
                            }))

            message = stream.get_final_message()
            final_text = "".join(full_text)

            # Log usage
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            self._log_tokens(parecer_obj, input_tokens, output_tokens, 'Fase 5 (Parecer)', model_name=model_to_use, start_time=start_time)

            return final_text
        except Exception as e:
            err_str = str(e)
            import logging
            _log = logging.getLogger(__name__)
            _log.error(f"Anthropic Fase 5 falhou ({err_str}) — tentando fallback Gemini.")
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                send_mail(
                    subject='🚨 JARI ALERTA (FALHA CLAUDE 3.5)',
                    message=f'A API da Anthropic retornou erro na Fase 5: {err_str}',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=['geffersonvivan@gmail.com'],
                    fail_silently=True
                )
            except Exception:
                pass
            try:
                from chat.integrations.gemini import GeminiClient
                _log.warning("Fase 5: fallback para GeminiClient após falha Anthropic.")
                return GeminiClient().generate_parecer_gemini(
                    parecer_obj, tese, perplexity_result, vertex_result, task_id
                )
            except Exception as _fe:
                _log.error(f"Fase 5 fallback Gemini também falhou: {_fe}")
                return f"Erro ao acessar Claude: {err_str}\nFallback Gemini: {str(_fe)}"
