import re
import json
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from ..models import Parecer, Pasta


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

    message = data.get('message', 'ok')

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
        return JsonResponse({'error': f'Erro interno ao processar fase: {str(e)[:120]}'}, status=500)

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


@csrf_exempt
def wizard_status_view(request, id):
    """Retorna apenas o status_fase atual do parecer — usado pelo frontend para polling de fallback."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'unauthenticated'}, status=401)
    parecer = get_object_or_404(Parecer, id=id, user=request.user)
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

    total_finalizados = Parecer.objects.filter(user=request.user, status_fase=8).count()

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
        'online_users_count': Parecer.objects.filter(user__isnull=False).values('user').distinct().count(),
    }
    return render(request, 'wizard_parecer.html', context)
