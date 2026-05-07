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
                _log.error("Pacote 'anthropic' não instalado. Execute: pip install anthropic")
                AnthropicClient._missing_warned = True
        elif not self.api_key:
            self.client = None
            if not AnthropicClient._missing_warned:
                _log.error(
                    "ANTHROPIC_API_KEY ausente — todas as fases LLM ficarão indisponíveis. "
                    "Configure a variável de ambiente ANTHROPIC_API_KEY no Railway."
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

    def extract_unified_fase1_fase2(self, parecer_obj, markdown_texts, contexto_textual_datas, pdf_chars=9999):
        """
        Extração unificada Fases 1+2 via Claude: campos administrativos + tabela de datas
        sensíveis + tipo_penalidade + flagrante numa única chamada.
        Drop-in replacement para GeminiClient.extract_unified_fase1_fase2().
        Retorna dict com todos os campos ou None se falhar.
        """
        if not self.client:
            _log.warning("extract_unified_anthropic: client não configurado — parecer=%s",
                         getattr(parecer_obj, 'id', '?'))
            return None

        import json as _json
        import time

        # Âncora para SGPE na tabela da Ata
        _pa_anchor = parecer_obj.pa or ""
        _rec_anchor = parecer_obj.recorrente or ""
        _ata_disponivel = 'ata' in markdown_texts if markdown_texts else False
        _anchor_hint = ""
        if _ata_disponivel and _pa_anchor:
            _anchor_hint = (
                f"AVISO CRÍTICO PARA O SGPE: A Ata da Sessão contém uma tabela Markdown com vários processos. "
                f"Localize a linha cujo campo PSDD/PA é exatamente '{_pa_anchor}' "
                f"e extraia o SGPE SOMENTE dessa linha. NUNCA use o SGPE de outra linha.\n\n"
            )
        elif _ata_disponivel and _rec_anchor:
            _anchor_hint = (
                f"AVISO CRÍTICO PARA O SGPE: A Ata da Sessão contém uma tabela Markdown com vários processos. "
                f"Localize a linha cujo recorrente é '{_rec_anchor}' "
                f"e extraia o SGPE SOMENTE dessa linha. NUNCA use o SGPE de outra linha.\n\n"
            )

        system_instruction = (
            "Você é um extrator de dados jurídicos de processos de trânsito (JARI).\n"
            "Analise os documentos abaixo e execute DUAS tarefas simultâneas:\n\n"
            "TAREFA 1 — CAMPOS ADMINISTRATIVOS:\n"
            "Extraia: pa, sgpe, recorrente, prazo_final, data_protocolo, paginas_defesa.\n"
            "Para cada campo, indique confiança: 'alta' (explícito), 'baixa' (ambíguo), 'nulo' (não encontrado).\n\n"
            "EXTRAÇÃO AGRESSIVA — CAMPOS CRÍTICOS (não deixe null se houver qualquer indício):\n"
            "• prazo_final: Procure INTENSIVAMENTE por 'PRAZO FINAL', 'DATA LIMITE', 'VENCE EM', 'PRAZO RECURSAL', "
            "'PRAZO PARA RECURSO', ou qualquer data associada a prazo/limite/vencimento. "
            "Se encontrar uma Notificação de Penalidade (NP), o prazo é geralmente 30 dias após a data da NP. "
            "Se encontrar menção a '30 DIAS' após qualquer notificação, calcule a data e retorne com confiança 'baixa'. "
            "Procure também na Ata da Sessão se há coluna 'PRAZO' ou 'DATA LIMITE'.\n"
            "• data_protocolo: Procure INTENSIVAMENTE por 'PROTOCOLADO EM', 'DATA DO PROTOCOLO', 'RECEBIDO EM', "
            "'DATA DE ENTRADA', 'PROTOCOLO Nº...DE', carimbo de protocolo, selo de recebimento. "
            "Verifique a peça de defesa — geralmente há um carimbo/selo com a data de protocolo no topo ou rodapé. "
            "Na Ata, procure coluna 'PROTOCOLO' ou 'DATA PROTOCOLO'. "
            "No Consolidado, procure seção 'RECURSO' ou 'DEFESA' que mencione quando foi protocolado.\n"
            "• paginas_defesa: Identifique onde começa a peça recursal/defesa escrita PELO RECORRENTE (não pelo órgão). "
            "Procure por: 'RECURSO', 'DEFESA PRÉVIA', 'DEFESA DO CONDUTOR', 'RAZÕES RECURSAIS', 'REQUERIMENTO', "
            "'EXCELENTÍSSIMO', 'ILUSTRÍSSIMO', petição manuscrita ou digitada do cidadão. "
            "Retorne o intervalo de páginas (ex: '15-18'). Se só encontrar uma página, retorne '15'. "
            "DICA: a defesa geralmente está APÓS as notificações e ANTES dos documentos do órgão autuador.\n\n"
            "TAREFA 2 — TABELA DE DATAS SENSÍVEIS:\n"
            "Organize TODAS as datas essenciais do processo numa tabela Markdown.\n"
            "Extraia: tipo_penalidade, tem_flagrante, data_conclusao_multa, data_conhecimento_infracao, "
            "data_totalizacao_pontos, data_infracao_extraida, data_notificacao_extraida.\n\n"
            "REGRAS ABSOLUTAS:\n"
            "1. NUNCA invente datas que não existem nos documentos — mas SE uma data aparece em QUALQUER lugar "
            "do documento (carimbo, tabela, texto corrido, cabeçalho, rodapé), você DEVE extraí-la.\n"
            "2. Datas SEMPRE no formato DD/MM/AAAA.\n"
            "3. Se houver mais de uma data para o mesmo evento, liste TODAS na tabela como POSSÍVEL (1), (2).\n"
            "4. NUNCA declare erro, nulidade ou conflito; apenas anote 'Divergente; julgador deve avaliar'.\n"
            "5. No campo tabela_markdown, use rótulos canônicos MAIÚSCULOS na coluna Tipo: "
            "INFRACAO|NA|NP|INSTAURACAO|PROTOCOLO|SESSAO|PRAZO|CONCLUSAO_MULTA|DECISAO|TOTALIZACAO_PONTOS|OUTRO.\n"
            "6. data_totalizacao_pontos: preencher APENAS quando tipo_penalidade=suspensao E o documento indicar "
            "explicitamente suspensão por acúmulo de pontos. Caso contrário: NAO_SE_APLICA.\n"
            "7. As tabelas no Markdown dos documentos estão em formato GFM — use as colunas para identificar campos.\n"
            "Escreva de forma fria e neutra.\n\n"
            "RESPONDA EXCLUSIVAMENTE com um JSON válido (sem markdown fences) contendo estes campos:\n"
            "pa, pa_conf, sgpe, sgpe_conf, recorrente, recorrente_conf, prazo_final, prazo_final_conf, "
            "data_protocolo, data_protocolo_conf, paginas_defesa, paginas_defesa_conf, "
            "tipo_penalidade (multa|advertencia|suspensao|cassacao|nao_determinado), "
            "tem_flagrante (SIM|NAO|NAO_DETERMINADO), "
            "data_conclusao_multa, data_conhecimento_infracao, data_totalizacao_pontos, "
            "data_infracao_extraida, data_notificacao_extraida, "
            "tabela_markdown (string com as tabelas GFM completas)."
        )

        docs_markdown = "\n\n---\n\n".join(markdown_texts.values()) if markdown_texts else ""

        prompt_text = (
            f"=== BLOCO A (Informações já conhecidas) ===\n"
            f"1. Sessão JARI: {parecer_obj.data_sessao or 'NÃO INFORMADO'}\n"
            f"2. PA: {parecer_obj.pa or 'A EXTRAIR'}\n"
            f"3. SGPE: {parecer_obj.sgpe or 'A EXTRAIR'}\n"
            f"4. Prazo Final Recurso: {parecer_obj.prazo_final or 'A EXTRAIR'}\n"
            f"5. Protocolo Recurso: {parecer_obj.data_protocolo or 'A EXTRAIR'}\n\n"
            f"=== BLOCO B (Datas extraídas dos PDFs via Python) ===\n"
            f"{contexto_textual_datas}\n\n"
            + (_anchor_hint if _anchor_hint else "")
            + "=== DICAS DE LOCALIZAÇÃO ===\n"
            "• pa: 'PROCESSO ADMINISTRATIVO', 'PA', 'Nº PROCESSO'.\n"
            "• sgpe: 'SGPe' na tabela da Ata, na linha correspondente ao PA.\n"
            "• prazo_final: 'PRAZO', 'DATA LIMITE', 'DIAS PARA RECURSO', 'VENCE EM'. "
            "Procure na NP, na Ata (coluna PRAZO), ou calcule 30 dias após a NP se explícito.\n"
            "• data_protocolo: 'PROTOCOLO', 'PROTOCOLADO EM', 'RECEBIDO EM', 'DATA DE ENTRADA', "
            "carimbo de protocolo no topo/rodapé da defesa, coluna 'PROTOCOLO' na Ata.\n"
            "• paginas_defesa: onde começa a peça recursal/defesa escrita pelo recorrente. "
            "Procure por petição, requerimento, 'EXMO', 'ILMO', texto manuscrito. "
            "Retorne intervalo (ex: '15-18') ou página única (ex: '15').\n"
            "• recorrente: 'RECORRENTE', 'CONDUTOR', 'AUTUADO', 'INTERESSADO'.\n\n"
            "IMPORTANTE: Vasculhe TODOS os documentos (PDF visual + Markdown) para cada campo. "
            "Não desista de um campo após olhar apenas um documento — cruze Autuação, Consolidado e Ata.\n\n"
            "=== DOCUMENTOS ===\n\n"
            + docs_markdown + "\n\n"
            "Cruze as origens. Retorne o JSON conforme instruções."
        )

        # Montar content blocks: PDFs base64 + texto
        content_blocks = []

        # Anexar PDFs como documentos base64 (Claude suporta PDF nativo)
        from chat.integrations.perplexity import _p
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
                continue
            try:
                if default_storage.exists(_path):
                    pdf_block = self.get_pdf_content(_path)
                    if pdf_block:
                        content_blocks.append(pdf_block)
            except Exception:
                pass

        content_blocks.append({"type": "text", "text": prompt_text})

        _log.info("extract_unified_anthropic parecer=%s docs=%s total_chars=%d",
                  parecer_obj.id, list(markdown_texts.keys()) if markdown_texts else [],
                  len(docs_markdown))

        try:
            start_time = time.time()
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=system_instruction,
                messages=[{"role": "user", "content": content_blocks}],
            )

            raw_text = response.content[0].text.strip()
            # Limpar possíveis fences de markdown
            if raw_text.startswith('```'):
                raw_text = raw_text.split('\n', 1)[1] if '\n' in raw_text else raw_text[3:]
                if raw_text.endswith('```'):
                    raw_text = raw_text[:-3].strip()

            dados = _json.loads(raw_text)

            self._log_tokens(
                parecer_obj,
                response.usage.input_tokens,
                response.usage.output_tokens,
                'Extração Unificada F1+F2',
                model_name='claude-sonnet-4-20250514',
                start_time=start_time,
            )

            _log.info("extract_unified_anthropic: OK parecer=%s campos=%s",
                      parecer_obj.id, [k for k, v in dados.items() if v and '_conf' not in k and k != 'tabela_markdown'])
            return dados
        except Exception as e:
            _log.warning("extract_unified_anthropic falhou parecer=%s: %s: %s",
                         parecer_obj.id, type(e).__name__, e)
            return None

    def generate_phase2_report(self, parecer_obj, contexto_textual_datas, pdf_chars=9999):
        """
        Fase 2 — Tabela de datas sensíveis + campos estruturados.
        Drop-in replacement para GeminiClient.generate_phase2_report().
        Retorna dict com campos estruturados + tabela_markdown, ou dict com 'erro'.
        """
        if not self.client:
            return {'erro': 'Cliente Anthropic não configurado.', 'tabela_markdown': 'Sem cliente configurado.'}

        import json as _json
        import time

        system_instruction = (
            "INTEGRIDADE/REGULARIDADE DOCUMENTAL\n"
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
            "Escreva de forma fria e neutra.\n\n"
            "RESPONDA EXCLUSIVAMENTE com um JSON válido (sem markdown fences) contendo estes campos:\n"
            "recorrente (string), tipo_penalidade (multa|advertencia|suspensao|cassacao|nao_determinado), "
            "data_conclusao_multa (DD/MM/AAAA ou NAO_SE_APLICA), "
            "tem_flagrante (SIM|NAO|NAO_DETERMINADO), "
            "data_conhecimento_infracao (DD/MM/AAAA ou NAO_SE_APLICA), "
            "data_totalizacao_pontos (DD/MM/AAAA ou NAO_SE_APLICA), "
            "data_infracao_extraida (DD/MM/AAAA ou NAO_SE_APLICA), "
            "data_notificacao_extraida (DD/MM/AAAA ou NAO_SE_APLICA), "
            "tabela_markdown (string com tabelas GFM completas: Linha do Tempo + Datas Sensíveis + Atenção do MJ)."
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
            "Retorne o JSON conforme instruções: campos estruturados + tabela_markdown completa."
        )

        # Montar content blocks: PDFs base64 + texto
        content_blocks = []
        from chat.integrations.perplexity import _p
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
                continue
            try:
                if default_storage.exists(_path):
                    pdf_block = self.get_pdf_content(_path)
                    if pdf_block:
                        content_blocks.append(pdf_block)
            except Exception:
                pass

        content_blocks.append({"type": "text", "text": prompt_text})

        try:
            start_time = time.time()
            _model = "claude-sonnet-4-20250514"
            response = self.client.messages.create(
                model=_model,
                max_tokens=4096,
                system=system_instruction,
                messages=[{"role": "user", "content": content_blocks}],
            )
            raw_text = response.content[0].text.strip()
            if raw_text.startswith('```'):
                raw_text = raw_text.split('\n', 1)[1] if '\n' in raw_text else raw_text[3:]
                if raw_text.endswith('```'):
                    raw_text = raw_text[:-3].strip()

            dados = _json.loads(raw_text)
            self._log_tokens(
                parecer_obj, response.usage.input_tokens, response.usage.output_tokens,
                'Fase 2 (DIR)', model_name=_model, start_time=start_time,
            )
            return dados
        except Exception as e:
            _log.warning("generate_phase2_report falhou parecer=%s: %s", getattr(parecer_obj, 'id', '?'), e)
            return {'erro': str(e), 'tabela_markdown': "⚠️ **Não foi possível processar os documentos com a IA.** Por favor, use o botão \"Corrigir\" para tentar novamente."}

    def generate_phase3_report(self, parecer_obj, matematica_detalhes):
        """Fase 3 — Avaliação de admissibilidade (tempestividade/prescrição/decadência)."""
        if not self.client:
            return "Simulação: Admissibilidade checada. Tempestivo. Prescrições Afastadas."

        import time
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
            f"=== Fatos Documentais ===\n"
            f"{_tab_f3 or 'Não há tabela de fatos gerada.'}\n\n"
            f"=== Flags Matemáticas e Intervalos Calculados ===\n"
            f"{matematica_detalhes}\n\n"
            "Aplique estritamente o roteiro obrigatório e devolva os resultados solicitados baseando-se unicamente nas flags matemáticas acima."
        )

        try:
            start_time = time.time()
            _model = "claude-haiku-4-5-20251001"
            response = self.client.messages.create(
                model=_model,
                max_tokens=4096,
                system=system_instruction,
                messages=[{"role": "user", "content": prompt_text}],
            )
            self._log_tokens(
                parecer_obj, response.usage.input_tokens, response.usage.output_tokens,
                'Fase 3 (Avaliação Prazos)', model_name=_model, start_time=start_time,
            )
            return response.content[0].text
        except Exception as e:
            _log.error("generate_phase3_report falhou parecer=%s: %s", getattr(parecer_obj, 'id', '?'), e)
            raise

    def extract_tese(self, parecer_obj):
        """Fase 4 — Extração de teses defensivas do PDF."""
        if not self.client:
            return "Simulação: O recorrente alega a não aferição do radar pelo INMETRO."

        import time
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

        # PDFs base64
        content_blocks = []
        from chat.integrations.perplexity import _p
        from django.core.files.storage import default_storage
        for path_field in [parecer_obj.autuacao_pdf_path, parecer_obj.consolidado_pdf_path]:
            _path = _p(path_field)
            if not _path or "upload_simulado" in _path:
                continue
            try:
                if default_storage.exists(_path):
                    pdf_block = self.get_pdf_content(_path)
                    if pdf_block:
                        content_blocks.append(pdf_block)
            except Exception:
                pass
        content_blocks.append({"type": "text", "text": prompt_text})

        try:
            start_time = time.time()
            _model = "claude-sonnet-4-20250514"
            response = self.client.messages.create(
                model=_model,
                max_tokens=4096,
                system=system_instruction,
                messages=[{"role": "user", "content": content_blocks}],
            )
            self._log_tokens(
                parecer_obj, response.usage.input_tokens, response.usage.output_tokens,
                'Fase 4 (Extração)', model_name=_model, start_time=start_time,
            )
            return response.content[0].text.strip()
        except Exception as e:
            return f"Erro ao extrair tese via LLM: {e}"

    def refine_tese(self, parecer_obj, user_hint):
        """Fase 4 — Refinamento de tese com dica do julgador."""
        if not self.client:
            return f"Simulação de Refinamento: O recorrente alega que {user_hint}."

        import time
        from chat.prompts.phase_4 import SYSTEM_INSTRUCTION_REFINE as system_instruction

        prompt_text = (
            f"Por favor, releia a defesa do recorrente nas páginas: {parecer_obj.paginas_defesa}.\n\n"
            f"O assessor revisor apontou o seguinte: '{user_hint}'.\n\n"
            "Com base nessa instrução, escreva um NOVO resumo claro e direto informando as alegações da defesa."
        )

        # PDFs base64
        content_blocks = []
        from chat.integrations.perplexity import _p
        from django.core.files.storage import default_storage
        for path_field in [parecer_obj.autuacao_pdf_path, parecer_obj.consolidado_pdf_path]:
            _path = _p(path_field)
            if not _path or "upload_simulado" in _path:
                continue
            try:
                if default_storage.exists(_path):
                    pdf_block = self.get_pdf_content(_path)
                    if pdf_block:
                        content_blocks.append(pdf_block)
            except Exception:
                pass
        content_blocks.append({"type": "text", "text": prompt_text})

        try:
            start_time = time.time()
            _model = "claude-haiku-4-5-20251001"
            response = self.client.messages.create(
                model=_model,
                max_tokens=4096,
                system=system_instruction,
                messages=[{"role": "user", "content": content_blocks}],
            )
            self._log_tokens(
                parecer_obj, response.usage.input_tokens, response.usage.output_tokens,
                'Fase 4 (Refinamento)', model_name=_model, start_time=start_time,
            )
            return response.content[0].text.strip()
        except Exception as e:
            return f"Erro ao refinar tese via LLM: {e}"

    def get_cache_key_from_tese(self, tese):
        """Extrai o núcleo da tese em até 3 palavras (para cache key)."""
        if not self.client:
            return "simulacao"

        system_instruction = (
            "Sua única tarefa é extrair a palavra-chave central ou o 'núcleo' do argumento jurídico abaixo. "
            "Retorne APENAS essa palavra-chave (máximo 3 palavras). Sem pontos, sem explicações. "
            "Exemplos de saída: 'Aferição Inmetro', 'Sinalização R-19', 'Nulidade Citação', 'Mérito Prejudicado'."
        )

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=50,
                system=system_instruction,
                messages=[{"role": "user", "content": tese}],
            )
            key = response.content[0].text.strip().lower().replace('"', '').replace("'", "")
            return key
        except Exception as e:
            _log.error("Erro ao gerar cache key: %s", e)
            return "erro_chave"

    def analyze_tese(self, parecer_obj, tese, perplexity_result, vertex_result):
        """Fase 4 — Análise cruzada de teses com RAG (Vertex + Perplexity)."""
        # Short-circuit: prejudicialidade (Python puro, sem LLM)
        _punit = parecer_obj.julgador_prescricao_punitiva if parecer_obj.julgador_prescricao_punitiva is not None else parecer_obj.has_prescricao_punitiva
        _inter = parecer_obj.julgador_prescricao_intercorrente if parecer_obj.julgador_prescricao_intercorrente is not None else parecer_obj.has_prescricao_intercorrente
        _decad = parecer_obj.julgador_decadencia if parecer_obj.julgador_decadencia is not None else parecer_obj.has_decadencia
        _temp = parecer_obj.julgador_tempestivo if parecer_obj.julgador_tempestivo is not None else parecer_obj.is_tempestivo
        if _punit or _inter or _decad or (_temp is False):
            return "Teses defensivas prejudicadas em razão da extinção da pretensão punitiva ou inadmissibilidade recursal."

        if not self.client:
            return "Simulação: Resultar em: Conclusão: acolhida/não acolhida. (acolhida)"

        import time
        from chat.prompts.phase_4 import SYSTEM_INSTRUCTION_ANALYZE as system_instruction

        _vrtx_t = _trunc(vertex_result or '', 'vertex', _LIMITES['vertex'])
        _pplx_t = _trunc(perplexity_result or '', 'perplexity', _LIMITES['perplexity'])
        _tese_t = _trunc(tese or '', 'tese', _LIMITES['tese'])

        prompt_text = (
            f"Processo: {parecer_obj.pa} | SGPE: {parecer_obj.sgpe}\n"
            f"Teses Listadas: {_tese_t}\n\n"
            f"Documentos Anexos: Documento 'consolidado' + 'autuação'\n\n"
            f"RAG Inventário Normativo Google (VERTEX): {_vrtx_t}\n"
            f"Pesquisa Auxiliar (PERPLEXITY): {_pplx_t}\n\n"
            "Exponha as alternativas (a) e (b) justificadas para cada tese isoladamente.\n"
            "Ao final, liste as tags [DECISAO_TESE_X] para todas as teses analisadas (uma por linha)."
        )

        # PDFs base64
        content_blocks = []
        from chat.integrations.perplexity import _p
        from django.core.files.storage import default_storage
        for path_field in [parecer_obj.autuacao_pdf_path, parecer_obj.consolidado_pdf_path]:
            _path = _p(path_field)
            if not _path or "upload_simulado" in _path:
                continue
            try:
                if default_storage.exists(_path):
                    pdf_block = self.get_pdf_content(_path)
                    if pdf_block:
                        content_blocks.append(pdf_block)
            except Exception:
                pass
        content_blocks.append({"type": "text", "text": prompt_text})

        try:
            start_time = time.time()
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8096,
                system=system_instruction,
                messages=[{"role": "user", "content": content_blocks}],
            )
            self._log_tokens(
                parecer_obj, response.usage.input_tokens, response.usage.output_tokens,
                'Fase 4 (Análise Mérito)', model_name='claude-sonnet-4-20250514', start_time=start_time,
            )
            return response.content[0].text
        except Exception as e:
            return f"Erro ao acessar Claude na Fase 4: {e}.\n"

    def digest_cag_package(self, infracao_desc, vertex_result, perplexity_result):
        """Sintetiza Vertex + Perplexity em pacote normativo compacto (CAG cron)."""
        if not self.client:
            return None

        prompt = (
            f"INFRAÇÃO: {infracao_desc}\n\n"
            f"=== CORPUS NORMATIVO (Vertex AI) ===\n{vertex_result[:6000]}\n\n"
            f"=== JURISPRUDÊNCIA (Perplexity) ===\n{perplexity_result[:6000]}\n\n"
            "Sintetize o material acima em um PACOTE NORMATIVO COMPACTO contendo:\n"
            "1. Artigos do CTB aplicáveis (com redação resumida)\n"
            "2. Resoluções CONTRAN/CETRAN-SC relevantes (número + ementa)\n"
            "3. Top 5 jurisprudências mais citadas (tribunal + número + tese)\n"
            "4. Teses de defesa mais comuns para esta infração\n"
            "5. Pontos de atenção para o relator\n\n"
            "REGRAS:\n"
            "- Máximo 2000 tokens\n"
            "- Sem opinião — apenas fatos normativos\n"
            "- Formato: texto corrido com subtítulos em negrito\n"
            "- Cite artigos e resoluções com números exatos"
        )

        try:
            import time
            start_time = time.time()
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            result = response.content[0].text.strip()
            _log.info("[CAG] Anthropic digest: %d chars, %d in/%d out tokens",
                      len(result), response.usage.input_tokens, response.usage.output_tokens)
            if len(result) < 100:
                return None
            return result
        except Exception as e:
            _log.error("[CAG] Anthropic digest falhou: %s", e)
            return None

    def validate_and_generate_parecer(self, parecer_obj, tese, perplexity_result, vertex_result="", task_id=None):
        relator_name = "NÃO INFORMADO"
        if parecer_obj.user:
            relator_name = f"{parecer_obj.user.first_name} {parecer_obj.user.last_name}".strip()
            if not relator_name:
                relator_name = parecer_obj.user.username
        relator_name = relator_name.upper()

        if not self.client:
            _log.error("ANTHROPIC_API_KEY não configurada — impossível gerar parecer.")
            return (
                "⚠️ **ERRO DE CONFIGURAÇÃO: Parecer não gerado.**\n\n"
                "ANTHROPIC_API_KEY ausente. Configure a variável de ambiente no Railway."
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
            _log.error("Anthropic Fase 5 falhou: %s", err_str)
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                send_mail(
                    subject='🚨 JARI ALERTA (FALHA CLAUDE)',
                    message=f'A API da Anthropic retornou erro na Fase 5: {err_str}',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=['geffersonvivan@gmail.com'],
                    fail_silently=True
                )
            except Exception:
                pass
            return f"⚠️ Erro ao acessar Claude: {err_str}\nTente novamente em alguns instantes."

    def audit_parecer(self, parecer_obj):
        """
        Fase 6 — Auditoria de conformidade via Claude.
        Checklist de 10 itens sobre o Parecer Final.
        """
        if not self.client:
            return "⚠️ Auditoria indisponível: ANTHROPIC_API_KEY não configurada."

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
            _log.warning("[FASE6] Claude audit_parecer falhou: %s", e)
            return f"⚠️ Auditoria Qualitativa offline ({e}). Resultado puramente matemático operando."
