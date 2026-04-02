import json
import requests
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.conf import settings
from ..models import UserProfile, Pasta
from .home import _get_filter_kwargs


@login_required
@require_POST
def dismiss_onboarding_view(request):
    try:
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        profile.viu_boas_vindas = True
        profile.save(update_fields=['viu_boas_vindas'])
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
@require_POST
def reorder_folders_view(request):
    try:
        data = json.loads(request.body)
        order_list = data.get('order', [])

        from django.db.models import Case, When, IntegerField
        cases = {
            int(item['id']): int(item['posicao'])
            for item in order_list
            if int(item.get('id', 0)) > 0
        }
        if cases:
            Pasta.objects.filter(id__in=cases.keys(), user=request.user).update(
                posicao=Case(
                    *[When(id=pk, then=pos) for pk, pos in cases.items()],
                    output_field=IntegerField()
                )
            )

        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


_PROXY_ALLOWED_DOMAINS = {
    'img.clerk.com',
    'images.clerk.dev',
    'lh3.googleusercontent.com',
    'avatars.githubusercontent.com',
    'pbs.twimg.com',
    'storage.googleapis.com',
}

@login_required
def proxy_image_view(request):
    from urllib.parse import urlparse
    url = request.GET.get('url')
    if not url:
        return HttpResponse(status=400)

    # Aceita URLs absolutas HTTP/HTTPS da lista permitida e do próprio host
    parsed = urlparse(url)
    host = request.get_host().split(':')[0]
    
    if parsed.scheme not in ['http', 'https']:
        return HttpResponse(status=403)
        
    is_allowed = parsed.netloc in _PROXY_ALLOWED_DOMAINS or parsed.netloc == host
    if not is_allowed:
        return HttpResponse(status=403)

    try:
        r = requests.get(url, timeout=10, verify=True)
        response = HttpResponse(r.content, content_type=r.headers.get('Content-Type', 'image/jpeg'))
        response['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Erro no proxy de imagem: {e}")
        return HttpResponse(status=502)


@login_required
def aceitar_termos_view(request):
    from legal.models import DocumentoLegal, AceiteDocumentoLegal

    termo_ativo = DocumentoLegal.objects.filter(tipo='TERMO_USO', is_active=True).first()
    politica_ativa = DocumentoLegal.objects.filter(tipo='POLITICA_PRIVACIDADE', is_active=True).first()

    precisa_termo = False
    precisa_politica = False

    if termo_ativo:
        precisa_termo = not AceiteDocumentoLegal.objects.filter(user=request.user, documento=termo_ativo).exists()

    if politica_ativa:
        precisa_politica = not AceiteDocumentoLegal.objects.filter(user=request.user, documento=politica_ativa).exists()

    if not precisa_termo and not precisa_politica:
        from django.core.cache import cache
        cache.set(f"termos_ok_{request.user.pk}", True, timeout=21600)
        return redirect('home')

    if request.method == 'POST':
        ip = request.META.get('HTTP_X_FORWARDED_FOR')
        if ip:
            ip = ip.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')

        # Valida que todos os documentos pendentes foram explicitamente aceitos
        termo_aceito = (not precisa_termo) or (request.POST.get('aceite_termo') == 'on')
        politica_aceita = (not precisa_politica) or (request.POST.get('aceite_politica') == 'on')

        if not termo_aceito or not politica_aceita:
            context = {
                'termo': termo_ativo if precisa_termo else None,
                'politica': politica_ativa if precisa_politica else None,
                'erro': 'Você precisa marcar todas as caixas para continuar.',
            }
            return render(request, 'termos.html', context)

        if precisa_termo:
            AceiteDocumentoLegal.objects.get_or_create(user=request.user, documento=termo_ativo, defaults={'ip_usuario': ip})

        if precisa_politica:
            AceiteDocumentoLegal.objects.get_or_create(user=request.user, documento=politica_ativa, defaults={'ip_usuario': ip})

        from django.core.cache import cache
        cache.set(f"termos_ok_{request.user.pk}", True, timeout=21600)
        return redirect('home')

    context = {
        'termo': termo_ativo if precisa_termo else None,
        'politica': politica_ativa if precisa_politica else None,
    }

    return render(request, 'termos.html', context)


def visualizar_termos_view(request):
    """View pública para visualizar os termos de uso e políticas de privacidade atuais."""
    from legal.models import DocumentoLegal

    termo_ativo = DocumentoLegal.objects.filter(tipo='TERMO_USO', is_active=True).first()
    politica_ativa = DocumentoLegal.objects.filter(tipo='POLITICA_PRIVACIDADE', is_active=True).first()

    context = {
        'termo': termo_ativo,
        'politica': politica_ativa,
        'somente_visualizacao': True # Flag para o template esconder o form de aceite
    }
    return render(request, 'termos.html', context)


def auth_sync_view(request):
    """
    Página interceptora leve: recebe o redirecionamento logo após o Clerk finalizar o login OAuth.
    Seu único papel é renderizar um spinner, o Clerk JS pegar o Token atualizado,
    gravar no Cookie __session de primeira-pessoa (pjarisc.com.br) e mandar direto para o /app/.
    """
    return render(request, 'auth_sync.html', {
        'CLERK_PUBLISHABLE_KEY': getattr(settings, 'CLERK_PUBLISHABLE_KEY', '')
    })
