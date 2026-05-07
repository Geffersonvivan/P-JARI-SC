import re
import json
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.core.cache import cache
from django_ratelimit.decorators import ratelimit
from ..models import Parecer, Pasta


def _get_online_users_count():
    """Conta usuários distintos com parecer, cacheado por 5 min."""
    count = cache.get('pjari_online_users_count')
    if count is None:
        count = Parecer.objects.filter(user__isnull=False).values('user').distinct().count()
        cache.set('pjari_online_users_count', count, timeout=300)
    return count


def _parse_adm_sections(adm_txt: str) -> dict:
    """
    Extrai o texto do 'Cálculo fundamentado' para cada critério de admissibilidade.
    Retorna dict: {TEMPESTIVIDADE: str, PUNITIVA: str, INTERCORRENTE: str, DECADENCIA: str}
    """
    KEYS = ['TEMPESTIVIDADE', 'PUNITIVA', 'INTERCORRENTE', 'DECADENCIA']
    result = {k: '' for k in KEYS}
    if not adm_txt:
        return result

    for key in KEYS:
        marker_re = re.compile(
            r'\[DECISAO_ADMISSIBILIDADE_' + key + r'(?::[A-Z_]+)?\]'
        )
        m = marker_re.search(adm_txt)
        if not m:
            continue
        text_before = adm_txt[:m.start()]

        # Estratégia 1: localiza "**Cálculo fundamentado" imediatamente antes do marcador
        calc_idx = text_before.rfind('**Cálculo fundamentado')
        if calc_idx == -1:
            calc_idx = text_before.lower().rfind('cálculo fundamentado')
        if calc_idx == -1:
            calc_idx = text_before.lower().rfind('calculo fundamentado')

        if calc_idx != -1:
            result[key] = text_before[calc_idx:].strip()
            continue

        # Estratégia 2: texto entre o marcador anterior e este
        all_markers = list(re.finditer(
            r'\[DECISAO_ADMISSIBILIDADE_(\w+)(?::[A-Z_]+)?\]', adm_txt
        ))
        for i, mm in enumerate(all_markers):
            if mm.group(1) != key:
                continue
            start = all_markers[i - 1].end() if i > 0 else 0
            result[key] = adm_txt[start:mm.start()].strip()
            break

    return result


@ratelimit(key='user_or_ip', rate='10/m', method='POST', block=True)
@csrf_exempt
@require_POST
def wizard_avancar_view(request, id):
    """Endpoint dedicado para avançar fases no wizard, sem depender do chat.
    CSRF exempt mas protegido por verificação de header X-Requested-With (não enviável
    cross-origin sem CORS preflight) + autenticação Clerk JWT.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Sessão expirada. Recarregue a página e tente novamente.'}, status=401)
    # Proteção contra CSRF: navegadores não enviam headers custom cross-origin sem preflight CORS
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Requisição inválida.'}, status=403)
    parecer = get_object_or_404(Parecer, id=id, user=request.user)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        data = {}

    message = (data.get('message') or 'ok')[:5000]

    try:
        from ..jari_engine import JariEngine
        engine = JariEngine(parecer)
        reply = engine.process_message(message, [])
    except Exception as e:
        import sentry_sdk, traceback
        sentry_sdk.capture_exception(e)
        import logging
        logging.getLogger(__name__).error(
            "wizard_avancar_view error (parecer=%s fase=%s): %s\n%s",
            id, parecer.status_fase, e, traceback.format_exc()
        )
        # Sanitiza erro: nunca expor detalhes técnicos (429, stack traces) ao usuário
        err_str = str(e)
        _transient = any(m in err_str for m in ('429', 'rate_limit', 'RateLimitError', '502', '503', '504', 'overloaded', 'timeout'))
        if _transient:
            user_msg = 'O servidor está temporariamente sobrecarregado. Aguarde alguns instantes e tente novamente.'
        else:
            user_msg = 'Erro interno ao processar fase. Tente novamente em alguns instantes.'
        return JsonResponse({'error': user_msg}, status=500)

    parecer.refresh_from_db()

    if reply.startswith('{"status": "celery"'):
        try:
            celery_data = json.loads(reply)
        except (json.JSONDecodeError, ValueError):
            celery_data = {}
        return JsonResponse({
            'is_processing': True,
            'task_id': celery_data.get('task_id'),
            'task_type': celery_data.get('type', 'NORMAL'),
            'status_fase': parecer.status_fase,
        })

    # Reply de erro do engine (⚠️, ❌) → retorna como 'error' para o frontend exibir
    if reply and (reply.startswith('⚠️') or reply.startswith('❌') or reply.startswith('⛔')):
        return JsonResponse({'error': reply, 'status_fase': parecer.status_fase})

    _t = parecer.tempo_julgamento_segundos
    return JsonResponse({
        'is_processing': False,
        'reply': reply,
        'status_fase': parecer.status_fase,
        'blindagem_score': parecer.blindagem_score,
        'blindagem_detalhes': parecer.blindagem_detalhes or '',
        'tempo_julgamento_fmt': (
            f"{_t // 60} min {_t % 60} s" if _t and _t >= 60 else (f"{_t} s" if _t else None)
        ),
    })


@ratelimit(key='user_or_ip', rate='60/m', method='ALL', block=True)
@csrf_exempt
def wizard_status_view(request, id):
    """Retorna apenas o status_fase atual do parecer — usado pelo frontend para polling de fallback."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'unauthenticated'}, status=401)
    # Proteção contra CSRF: navegadores não enviam headers custom cross-origin sem preflight CORS
    if request.method == 'POST' and request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Requisição inválida.'}, status=403)
    _status_cache_key = f'wizard_status_{request.user.pk}_{id}'
    _cached_fase = cache.get(_status_cache_key)
    if _cached_fase is not None:
        return JsonResponse({'status_fase': _cached_fase})
    parecer = get_object_or_404(Parecer, id=id, user=request.user)
    cache.set(_status_cache_key, parecer.status_fase, timeout=2)
    return JsonResponse({'status_fase': parecer.status_fase})


@login_required
def wizard_parecer_view(request, id):
    parecer = get_object_or_404(Parecer, id=id, user=request.user)
    pastas = list(Pasta.objects.filter(user=request.user).order_by('nome_pasta'))
    nome_usuario = request.user.get_full_name() or request.user.username

    user_credits = 0
    user_is_pro = False
    try:
        user_credits = request.user.profile.credits
        user_is_pro = request.user.profile.is_pro
    except Exception:
        pass

    # Se houver versão editada pelo editor completo, usa ela (HTML) em vez do markdown bruto
    parecer_final_editado = parecer.pareceres_finais.order_by('-data_criacao').first()
    parecer_final_html = parecer_final_editado.conteudo_html if parecer_final_editado else ''

    _cache_key_fin = f'total_finalizados_{request.user.pk}'
    total_finalizados = cache.get(_cache_key_fin)
    if total_finalizados is None:
        total_finalizados = Parecer.objects.filter(user=request.user, status_fase=8).count()
        cache.set(_cache_key_fin, total_finalizados, timeout=120)

    context = {
        'parecer': parecer,
        'total_finalizados': total_finalizados,
        'csrf_token_value': get_token(request),
        'user_credits': user_credits,
        'user_is_pro': user_is_pro,
        'status_fase': parecer.status_fase,
        'has_consolidado': bool(parecer.consolidado_pdf_path),
        'has_autuacao': bool(parecer.autuacao_pdf_path),
        'has_ata': bool(parecer.ata_pdf_path),
        'admissibilidade_texto': parecer.admissibilidade_texto or '',
        'adm_sections': _parse_adm_sections(parecer.admissibilidade_texto or ''),
        'analise_tese_texto': parecer.analise_tese_texto or '',
        'parecer_final': parecer.parecer_final or '',
        'parecer_final_html': parecer_final_html,
        'tabela_datas_sensiveis': parecer.tabela_datas_sensiveis or '',
        'tese': parecer.tese or '',
        'blindagem_score': parecer.blindagem_score,
        'blindagem_detalhes': parecer.blindagem_detalhes or '',
        'tempo_julgamento_segundos': parecer.tempo_julgamento_segundos,
        'tempo_julgamento_fmt': (
            f"{parecer.tempo_julgamento_segundos // 60} min {parecer.tempo_julgamento_segundos % 60} s"
            if parecer.tempo_julgamento_segundos and parecer.tempo_julgamento_segundos >= 60
            else (f"{parecer.tempo_julgamento_segundos} s" if parecer.tempo_julgamento_segundos else None)
        ),
        'is_tempestivo': parecer.is_tempestivo,
        'has_prescricao_punitiva': parecer.has_prescricao_punitiva,
        'has_prescricao_intercorrente': parecer.has_prescricao_intercorrente,
        'has_decadencia': parecer.has_decadencia,
        'julgador_tempestivo': parecer.julgador_tempestivo,
        'julgador_prescricao_punitiva': parecer.julgador_prescricao_punitiva,
        'julgador_prescricao_intercorrente': parecer.julgador_prescricao_intercorrente,
        'julgador_decadencia': parecer.julgador_decadencia,
        'pastas': pastas,
        'nome_usuario': nome_usuario,
        'CLERK_PUBLISHABLE_KEY': getattr(settings, 'CLERK_PUBLISHABLE_KEY', ''),
        'pjari_version': getattr(settings, 'PJARI_VERSION', '1.2'),
        'online_users_count': _get_online_users_count(),
        'unified_mode': getattr(settings, 'UNIFIED_FASE1_FASE2', False),
    }
    return render(request, 'wizard_parecer.html', context)
