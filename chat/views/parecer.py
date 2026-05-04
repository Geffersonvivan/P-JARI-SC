import json
import os
import urllib.parse
import nh3
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse, Http404
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.core.cache import cache
from django_ratelimit.decorators import ratelimit
from django.core.files.storage import default_storage
from django.conf import settings
from ..models import Parecer, Pasta, ConfiguracaoParecer, ParecerFinal
from .home import _get_filter_kwargs, PLANS

# Tags HTML permitidas no parecer (whitelist de segurança contra XSS)
_ALLOWED_TAGS = {
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'span', 'table',
    'thead', 'tbody', 'tr', 'th', 'td', 'a', 'hr', 'blockquote',
    'sup', 'sub', 'pre', 'code', 'img',
}
_ALLOWED_ATTRS = {
    '*': {'class', 'style', 'id'},
    'a': {'href', 'title', 'target'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan'},
    'img': {'src', 'alt', 'width', 'height'},
}


def _sanitize_html(html: str) -> str:
    """Sanitiza HTML para prevenir XSS, permitindo apenas tags seguras."""
    if not html:
        return html
    return nh3.clean(
        html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS,
        link_rel=None, url_schemes={'http', 'https', 'data'},
    )


@login_required
def editar_parecer_view(request, id):
    parecer = get_object_or_404(Parecer, id=id, user=request.user)
    _MISS = object()
    config = cache.get('configuracao_parecer', _MISS)
    if config is _MISS:
        config = ConfiguracaoParecer.objects.first()
        cache.set('configuracao_parecer', config, timeout=3600)

    # ParecerFinal = versão HTML editada no TinyMCE (tem prioridade)
    # parecer_final = saída markdown bruta da IA (fallback)
    parecer_final_db = parecer.pareceres_finais.order_by('-data_criacao').first()

    if parecer_final_db:
        parecer_gerado = parecer_final_db.conteudo_html
    else:
        texto_gerado_pela_ia = parecer.parecer_final or ""

        if config:
            from django.template import Template, Context
            is_indeferido = "INDEFERID" in texto_gerado_pela_ia.upper()
            _rodape_indef = getattr(config, 'rodape_indeferido', '') or ""
            _rodape_def = getattr(config, 'rodape_deferido', '') or ""
            rodape_texto = _rodape_indef if is_indeferido else _rodape_def

            # Limpa Nonetypes e Nulls antes das manipulações massivas
            if not isinstance(rodape_texto, str): rodape_texto = ""

            # Auto-corrigir tags mal formadas deixadas pelo usuário como {{. }} ou vazias
            palavra_resultado = "INDEFERIDO" if is_indeferido else "DEFERIDO"
            rodape_texto = rodape_texto.replace('{{. }}', palavra_resultado).replace('{{.}}', palavra_resultado)
            rodape_texto = rodape_texto.replace('{{ }}', palavra_resultado).replace('{{}}', palavra_resultado)

            nome_usuario = request.user.get_full_name() or request.user.username if request.user.is_authenticated else "Visitante"
            rodape_template = Template(rodape_texto)
            rodape_escolhido = rodape_template.render(Context({
                'nome_membro': nome_usuario,
                'nome_usuario': nome_usuario,
                'deferido': palavra_resultado,
                'indeferido': palavra_resultado,
                'DEFERIDO': palavra_resultado,
                'INDEFERIDO': palavra_resultado,
                'resultado': palavra_resultado
            }))

            import re
            import base64
            from mimetypes import guess_type

            def _img_to_b64(path):
                mime = guess_type(path)[0] or 'image/png'
                with open(path, 'rb') as f:
                    return f'data:{mime};base64,{base64.b64encode(f.read()).decode()}'

            banner_src = None

            if config.cabecalho_imagem and default_storage.exists(config.cabecalho_imagem.name):
                try:
                    with default_storage.open(config.cabecalho_imagem.name, 'rb') as _img_file:
                        _img_bytes = _img_file.read()
                    _mime = guess_type(config.cabecalho_imagem.name)[0] or 'image/jpeg'
                    banner_src = f'data:{_mime};base64,{base64.b64encode(_img_bytes).decode()}'
                except Exception:
                    banner_src = request.build_absolute_uri(config.cabecalho_imagem.url)

            if not banner_src:
                # Fallback: usa o cabeçalho padrão em staticfiles
                _static_cabecalho = os.path.join(
                    settings.BASE_DIR, 'staticfiles', 'Cabecalho', 'Cabeçalho topo.png'
                )
                if os.path.exists(_static_cabecalho):
                    try:
                        banner_src = _img_to_b64(_static_cabecalho)
                    except Exception:
                        pass

            if banner_src:
                cabecalho_html = f"""
                <div style="text-align: center; width: 100%; margin-bottom: 40px; margin-top: 10px;">
                    <img src='{banner_src}' style='width: 100%; max-width: 800px; height: auto;' alt="Cabeçalho">
                </div>
                """
            else:
                cabecalho_html = """
                <div style="text-align: center; width: 100%; margin-bottom: 40px; margin-top: 10px; height: 153px; border: 1px dashed #ccc; display:flex; align-items:center; justify-content:center;">
                    <span style="color: #999; font-family: Arial, sans-serif; font-size: 12px;">[ Banner do Cabeçalho P-JARI não configurado ]</span>
                </div>
                """

            # Converter markdown para HTML
            import markdown
            texto_html = markdown.markdown(texto_gerado_pela_ia, extensions=['nl2br', 'sane_lists', 'tables'])

            # Converter links no texto do parecer
            texto_html = re.sub(r'<a ', r'<a target="_blank" class="text-blue-600 hover:text-blue-800 underline break-words font-semibold" rel="noopener noreferrer" ', texto_html)

            # Formatar dossiê se existir na View do Editor para passar pro PDF
            dossie_html = parecer.dossie_fontes or ""
            if dossie_html:
                dossie_html = markdown.markdown(dossie_html, extensions=['nl2br', 'sane_lists', 'tables'])
                dossie_html = re.sub(r'<a ', r'<a target="_blank" class="text-blue-600 hover:text-blue-800 underline break-words font-semibold" rel="noopener noreferrer" ', dossie_html)
                parecer.dossie_fontes_html = dossie_html

            # Para o TinyMCE, um bloco flex ou div simples com text-align center é totalmente respeitado nativamente
            rodape_centralizado = f"""
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; margin-top: 25px; width: 100%;">
                <div style="text-align: center; width: auto; display: inline-block;">
                    {rodape_escolhido.replace('<p>', '<p style="text-align: center; margin: 0; padding: 0;">').replace('text-align: left;', 'text-align: center;')}
                </div>
            </div>
            """

            parecer_gerado = f"{cabecalho_html}<div class='corpo'>{texto_html}</div>{rodape_centralizado}"
        else:
            import markdown
            parecer_gerado = markdown.markdown(texto_gerado_pela_ia, extensions=['nl2br', 'sane_lists', 'tables'])

    from ..models import BancoTese
    if request.user.is_authenticated:
        banco_teses = BancoTese.objects.filter(user=request.user).order_by('-created_at')
        teses_comunidade = cache.get('teses_comunidade_top20')
        if teses_comunidade is None:
            teses_comunidade = list(BancoTese.objects.filter(is_public=True).order_by('-usage_count')[:20])
            cache.set('teses_comunidade_top20', teses_comunidade, timeout=300)
        teses_comunidade = [t for t in teses_comunidade if t.user_id != request.user.pk]
    else:
        banco_teses = []
        teses_comunidade = []

    # Phase 5: Dynamic Context Chips
    dynamic_chips = []
    if parecer.infracao_documento:
        infracao_lower = parecer.infracao_documento.lower()
        if "165" in infracao_lower or "embriag" in infracao_lower or "bafôm" in infracao_lower or "recusa" in infracao_lower:
            dynamic_chips.append({"label": "⚖️ Tese: Bafômetro", "prompt": "Sugira uma tese de defesa estruturada com base na jurisprudência do CETRAN-SC para a infração do Art. 165 / 165-A (Embriaguez ou Recusa ao Bafômetro)."})
        if "excesso" in infracao_lower or "218" in infracao_lower or "velocidade" in infracao_lower or "radar" in infracao_lower:
            dynamic_chips.append({"label": "⚖️ Tese: Radar/Velocidade", "prompt": "Quais são as principais teses de defesa preliminares e de mérito aceitas pelo CETRAN-SC para multas de excesso de velocidade relacionadas à aferição do radar?"})
        if "suspens" in infracao_lower or "cass" in infracao_lower or "psdd" in infracao_lower:
            dynamic_chips.append({"label": "⚖️ Tese: Suspensão da CNH", "prompt": "Verifique a pertinência da tese de 'bis in idem' ou argumente sobre a notificação no processo de suspensão/cassação da CNH."})

    if not dynamic_chips:
        # Padrões úteis se não conseguirmos capturar o enquadramento exato
        dynamic_chips.append({"label": "🔎 Analisar Prazos e Prescrição", "prompt": "Levando em conta o CTB e as resoluções do CONTRAN aplicáveis, analise as datas sensíveis informadas neste processo e me diga se há possível prescrição (quinquenal ou intercorrente) ou decadência (Art 281)."})
        dynamic_chips.append({"label": "⚖️ Melhores Teses CETRAN", "prompt": "Quais são as teses de defesa ou preliminares processuais com maior índice de provimento no CETRAN-SC para este caso específico?"})

    return render(request, 'editor_parecer.html', {
        'parecer': parecer,
        'parecer_gerado': _sanitize_html(parecer_gerado),
        'config': config,
        'banco_teses': banco_teses,
        'teses_comunidade': teses_comunidade,
        'dynamic_chips': dynamic_chips
    })


@login_required
@require_POST
def salvar_parecer_view(request, id):
    parecer = get_object_or_404(Parecer, id=id, user=request.user)
    conteudo_final = request.POST.get('conteudo_final')

    if conteudo_final:
        status_result = "INDEFERIDO" if "INDEFERID" in conteudo_final.upper() else "DEFERIDO"

        ParecerFinal.objects.create(
            parecer_referencia=parecer,
            conteudo_html=conteudo_final,
            status_resultado=status_result
        )

    return redirect('home')


@ratelimit(key='user_or_ip', rate='20/h', method='POST', block=True)
@require_POST
def create_parecer_view(request):
    if not request.session.session_key:
        request.session.create()

    if not request.user.is_authenticated:
        count = Parecer.objects.filter(user__isnull=True, session_key=request.session.session_key).count()
        if count >= 2:
            return JsonResponse({'requires_login': True})

    try:
        data = json.loads(request.body)
        nome_processo = (data.get('nome_processo') or '').strip()[:200]
        if nome_processo:
            if request.user.is_authenticated:
                pasta = Pasta.objects.create(user=request.user, nome_pasta=nome_processo)
                parecer = Parecer.objects.create(user=request.user, pasta=pasta, nome_processo=nome_processo, is_saved=True)
            else:
                pasta = Pasta.objects.create(session_key=request.session.session_key, nome_pasta=nome_processo)
                parecer = Parecer.objects.create(session_key=request.session.session_key, pasta=pasta, nome_processo=nome_processo, is_saved=True)
            return JsonResponse({'id': pasta.id, 'nome_processo': pasta.nome_pasta, 'parecer_id': parecer.id})
        return JsonResponse({'error': 'Nome do processo inválido'}, status=400)
    except Exception as e:
        import logging; logging.getLogger(__name__).error("create_parecer_view: %s", e, exc_info=True)
        return JsonResponse({'error': 'Erro interno. Tente novamente.'}, status=500)


@require_POST
def delete_parecer_view(request, id):
    if not request.session.session_key:
        request.session.create()
    filter_kwargs = _get_filter_kwargs(request)

    pasta = get_object_or_404(Pasta, id=id, **filter_kwargs)
    pasta.delete()
    return JsonResponse({'success': True})


@require_POST
def delete_projeto_view(request, id):
    if not request.session.session_key:
        request.session.create()
    filter_kwargs = _get_filter_kwargs(request)

    projeto = get_object_or_404(Parecer, id=id, **filter_kwargs)
    projeto.delete()
    return JsonResponse({'success': True})


@require_POST
def mover_parecer_view(request, id):
    if not request.session.session_key:
        request.session.create()
    filter_kwargs = _get_filter_kwargs(request)

    projeto = get_object_or_404(Parecer, id=id, **filter_kwargs)

    try:
        data = json.loads(request.body)
        nova_pasta_id = data.get('nova_pasta_id')

        if not nova_pasta_id:
            return JsonResponse({'error': 'Nova pasta não especificada.'}, status=400)

        nova_pasta = get_object_or_404(Pasta, id=nova_pasta_id, **filter_kwargs)
        projeto.pasta = nova_pasta
        projeto.save()

        return JsonResponse({'success': True})
    except Exception as e:
        import logging; logging.getLogger(__name__).error("mover_projeto_view: %s", e, exc_info=True)
        return JsonResponse({'error': 'Erro interno. Tente novamente.'}, status=500)


@ratelimit(key='user_or_ip', rate='30/m', method='POST', block=True)
@require_POST
def corrigir_campo_parecer_view(request, parecer_id):
    """
    Corrige um campo da tabela F2 via API.
    Só funciona em FASE_DIR (2). Invalida o pré-cálculo F3 se necessário.
    """
    if not request.session.session_key:
        request.session.create()
    filter_kwargs = _get_filter_kwargs(request)
    parecer = get_object_or_404(Parecer, id=parecer_id, **filter_kwargs)

    from chat.engine import FASE_DIR
    if parecer.status_fase != FASE_DIR:
        return JsonResponse({'error': 'Correção de campo só é permitida na Fase 2.'}, status=400)

    try:
        data = json.loads(request.body)
        campo = (data.get('campo') or '').strip().lower()
        valor_str = str(data.get('valor', '') or '').strip()[:500]

        from chat.engine.phase_2 import _CAMPOS_F2, _parse_field
        if campo not in _CAMPOS_F2:
            return JsonResponse({'error': f'Campo "{campo}" não pode ser editado inline.'}, status=400)

        valor_parsed, erro = _parse_field(campo, valor_str)
        if erro:
            return JsonResponse({'error': erro}, status=400)

        old_val = getattr(parecer, campo, None)
        setattr(parecer, campo, valor_parsed)
        update_fields = [campo]
        if parecer.admissibilidade_texto:
            parecer.admissibilidade_texto = None
            update_fields.append('admissibilidade_texto')
        parecer.save(update_fields=update_fields)

        import logging as _log
        _log.getLogger(__name__).info(
            "[F2-API] campo corrigido: %s %s→%s | parecer=%s", campo, old_val, valor_parsed, parecer.id
        )
        return JsonResponse({'success': True, 'campo': campo, 'valor_novo': str(valor_parsed), 'valor_anterior': str(old_val)})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@require_POST
def salvar_feedback_parecer_view(request, parecer_id):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Não autenticado'}, status=403)

    parecer = get_object_or_404(Parecer, id=parecer_id, user=request.user)

    try:
        data = json.loads(request.body)
        score = data.get('score')
        tags = data.get('tags', [])
        notes = data.get('notes', '')

        if score is not None:
            parecer.feedback_score = int(score)

        if tags is not None:
            # M10 FIX: normalizar para JSON string — robusto contra tags com vírgulas
            import json as _json
            if isinstance(tags, list):
                _tags_clean = [str(t).strip()[:50] for t in tags if str(t).strip()]
            else:
                # Aceita string CSV legada ou JSON string
                _raw = str(tags).strip()
                try:
                    _parsed = _json.loads(_raw)
                    _tags_clean = [str(t).strip()[:50] for t in (_parsed if isinstance(_parsed, list) else [_parsed]) if str(t).strip()]
                except (ValueError, TypeError):
                    _tags_clean = [t.strip()[:50] for t in _raw.split(',') if t.strip()]
            _tags_clean = _tags_clean[:20]  # máximo 20 tags
            parecer.feedback_tags = _json.dumps(_tags_clean, ensure_ascii=False)

        if notes:
            parecer.feedback_notes = str(notes)[:2000]

        parecer.save(update_fields=['feedback_score', 'feedback_tags', 'feedback_notes'])

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


def pdf_proxy_view(request, parecer_id, tipo):
    """Serve PDFs do processo via proxy Django para evitar problemas cross-origin no iframe."""
    filter_kwargs = _get_filter_kwargs(request)
    parecer = get_object_or_404(Parecer, id=parecer_id, **filter_kwargs)

    campo_map = {
        'consolidado': parecer.consolidado_pdf_path,
        'autuacao': parecer.autuacao_pdf_path,
        'ata': parecer.ata_pdf_path,
    }
    field = campo_map.get(tipo)
    if not field:
        raise Http404

    path = field.name if hasattr(field, 'name') else str(field)
    if not path or not default_storage.exists(path):
        raise Http404

    filename = urllib.parse.quote(os.path.basename(path))

    def file_iterator(storage_path, chunk_size=65536):
        with default_storage.open(storage_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    response = StreamingHttpResponse(file_iterator(path), content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    response['X-Frame-Options'] = 'SAMEORIGIN'
    return response

