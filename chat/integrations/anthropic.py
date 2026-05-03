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
    'tabela_datas':    15_000,  # aumentado de 5k: processos grandes tinham datas cortadas
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
    _missing_warned = False  # avisa apenas 1x no processo para não poluir logs

    def __init__(self):
        self.api_key = os.environ.get('ANTHROPIC_API_KEY')
        if Anthropic is None:
            self.client = None
            if not AnthropicClient._missing_warned:
                _log.error("Pacote 'anthropic' não instalado — FASE5 usará Gemini. Execute: pip install anthropic")
                AnthropicClient._missing_warned = True
        elif not self.api_key:
            self.client = None
            if not AnthropicClient._missing_warned:
                _log.error(
                    "ANTHROPIC_API_KEY ausente — FASE5 usará Gemini como fallback. "
                    "Configure a variável de ambiente ANTHROPIC_API_KEY no Railway para usar Claude."
                )
                AnthropicClient._missing_warned = True
        else:
            self.client = Anthropic(api_key=self.api_key)

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
            _log.error("Erro ao logar tokens Anthropic: %s", e)

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
            _log.error("Anthropic PDF encoding error: %s", e)
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
            "🔒 FLAGS MATEMÁTICAS — SOBERANAS, INVIOLÁVEIS, NÃO RECALCULE:\n"
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

        # Detecta quais flags o MJ inverteu individualmente
        _temp_invertido  = (parecer_obj.julgador_tempestivo               is not None and parecer_obj.julgador_tempestivo               != parecer_obj.is_tempestivo)
        _punit_invertido = (parecer_obj.julgador_prescricao_punitiva      is not None and parecer_obj.julgador_prescricao_punitiva      != parecer_obj.has_prescricao_punitiva)
        _inter_invertido = (parecer_obj.julgador_prescricao_intercorrente is not None and parecer_obj.julgador_prescricao_intercorrente != parecer_obj.has_prescricao_intercorrente)
        _decad_invertido = (parecer_obj.julgador_decadencia               is not None and parecer_obj.julgador_decadencia               != parecer_obj.has_decadencia)
        _qualquer_invertido = _temp_invertido or _punit_invertido or _inter_invertido or _decad_invertido

        # Constrói instrução cirúrgica por seção — só para as seções efetivamente invertidas
        _section_rules = []
        if _temp_invertido:
            _decisao_temp = "TEMPESTIVO" if parecer_obj.julgador_tempestivo else "INTEMPESTIVO"
            _section_rules.append(
                f"• Seção ADMISSIBILIDADE: o Membro Julgador decidiu que o recurso é {_decisao_temp}. "
                f"Redija nesta seção APENAS a conclusão ({_decisao_temp}) e a base normativa aplicável. "
                f"PROIBIDO mencionar prazo calculado, data divergente ou qualquer resultado diferente."
            )
        if _punit_invertido:
            _decisao_punit = "CONFIGURADA" if parecer_obj.julgador_prescricao_punitiva else "NÃO configurada"
            _section_rules.append(
                f"• Seção 3.1 Prescrição Punitiva: o Membro Julgador decidiu que a prescrição punitiva está {_decisao_punit}. "
                f"Redija nesta seção APENAS a conclusão ({_decisao_punit}) e a base normativa aplicável. "
                f"PROIBIDO mencionar datas calculadas, prazo divergente ou qualquer resultado diferente."
            )
        if _inter_invertido:
            _decisao_inter = "CONFIGURADA" if parecer_obj.julgador_prescricao_intercorrente else "NÃO configurada"
            _section_rules.append(
                f"• Seção 3.2 Prescrição Intercorrente: o Membro Julgador decidiu que a prescrição intercorrente está {_decisao_inter}. "
                f"Redija nesta seção APENAS a conclusão ({_decisao_inter}) e a base normativa aplicável. "
                f"PROIBIDO mencionar datas calculadas, prazo divergente ou qualquer resultado diferente."
            )
        if _decad_invertido:
            _decisao_decad = "CONFIGURADA" if parecer_obj.julgador_decadencia else "NÃO configurada"
            _section_rules.append(
                f"• Seção 3.3 Decadência: o Membro Julgador decidiu que a decadência está {_decisao_decad}. "
                f"Redija nesta seção APENAS a conclusão ({_decisao_decad}) e a base normativa aplicável. "
                f"PROIBIDO mencionar regime temporal calculado, datas divergentes ou qualquer resultado diferente."
            )

        _aviso_diverg = ""
        if _qualquer_invertido:
            _aviso_diverg = (
                "⚠️ DECISÃO DO MEMBRO JULGADOR — RESTRIÇÃO CIRÚRGICA POR SEÇÃO:\n"
                "Nas seções indicadas abaixo, o Membro Julgador exerceu poder discricionário. "
                "A restrição se aplica EXCLUSIVAMENTE a essas seções. O restante do parecer segue normalmente.\n\n"
                + "\n".join(_section_rules) + "\n\n"
                "PROIBIÇÕES ABSOLUTAS para as seções listadas acima:\n"
                "• PROIBIDO citar que houve cálculo automático diferente.\n"
                "• PROIBIDO usar frases como 'deveria ser', 'o cálculo indica', 'tecnicamente', 'o prazo calculado'.\n"
                "• PROIBIDO mencionar contradição, inversão ou divergência com qualquer resultado anterior.\n"
                "• PROIBIDO expor JariMath, flags, motor, fases ou qualquer mecanismo interno.\n\n"
            )

        # Aviso no bloco de admissibilidade para cada item invertido pelo MJ
        _adm_prefix_parts = []
        if _temp_invertido:
            _adm_prefix_parts.append(
                "🚫 CONCLUSÃO DE TEMPESTIVIDADE ABAIXO SUPERADA PELA DECISÃO DO JULGADOR 🚫\n"
                "Use APENAS os dados factuais (datas, identificação do processo) para contextualização. "
                "A conclusão sobre tempestividade obrigatória está na seção ADMISSIBILIDADE acima."
            )
        if _punit_invertido:
            _adm_prefix_parts.append(
                "🚫 CONCLUSÃO DE PRESCRIÇÃO PUNITIVA ABAIXO SUPERADA PELA DECISÃO DO JULGADOR 🚫\n"
                f"Para a seção 3.1, use APENAS a decisão do Membro Julgador: {_decisao_punit}. "
                "IGNORE a conclusão de prescrição punitiva que constar no texto de admissibilidade abaixo."
            )
        if _inter_invertido:
            _adm_prefix_parts.append(
                "🚫 CONCLUSÃO DE PRESCRIÇÃO INTERCORRENTE ABAIXO SUPERADA PELA DECISÃO DO JULGADOR 🚫\n"
                f"Para a seção 3.2, use APENAS a decisão do Membro Julgador: {_decisao_inter}. "
                "IGNORE a conclusão de prescrição intercorrente que constar no texto de admissibilidade abaixo."
            )
        if _decad_invertido:
            _adm_prefix_parts.append(
                "🚫 CONCLUSÃO DE DECADÊNCIA ABAIXO SUPERADA PELA DECISÃO DO JULGADOR 🚫\n"
                f"Para a seção 3.3, use APENAS a decisão do Membro Julgador: {_decisao_decad}. "
                "IGNORE a conclusão de decadência que constar no texto de admissibilidade abaixo."
            )
        if _adm_prefix_parts:
            _adm_prompt = "\n\n".join(_adm_prefix_parts) + f"\n\n{_adm}"
        else:
            _adm_prompt = _adm

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
            f"{_adm_prompt}\n\n"
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
                    _log.error("Erro de conexão com Redis: %s", e)

            full_text = []

            with self.client.messages.stream(
                model=model_to_use,
                max_tokens=8096,
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

            # D2 FIX: validação pós-geração — forçar EMENTA em MAIÚSCULAS
            import re as _re
            _ementa_m = _re.search(r'\*\*EMENTA\*\*\s*\n+([\s\S]+?)(?=\n\*\*|\Z)', final_text)
            if _ementa_m:
                _ementa_orig = _ementa_m.group(1)
                _ementa_upper = _ementa_orig.upper()
                if _ementa_orig != _ementa_upper:
                    final_text = final_text[:_ementa_m.start(1)] + _ementa_upper + final_text[_ementa_m.end(1):]

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

    def audit_parecer(self, parecer_obj):
        """
        Fase 6 — Auditoria cruzada via Claude (quando o parecer foi escrito pelo Gemini).
        Mesmo checklist de 10 itens que o Gemini.audit_parecer, mas por um modelo independente.
        """
        if not self.client:
            return None  # caller fará fallback para Gemini

        import time

        system_instruction = (
            "Você é o Auditor Corregedor responsável pela verificação final do parecer.\n"
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
            model_to_use = "claude-sonnet-4-6"

            message = self.client.messages.create(
                model=model_to_use,
                max_tokens=2048,
                system=system_instruction,
                messages=[{"role": "user", "content": prompt}],
            )

            result = message.content[0].text
            self._log_tokens(
                parecer_obj, message.usage.input_tokens, message.usage.output_tokens,
                'Fase 6 (Auditoria Cruzada)', model_name=model_to_use, start_time=start_time,
            )
            return result
        except Exception as e:
            _log.warning("[FASE6] Claude audit_parecer falhou: %s — caller fará fallback", e)
            return None
