from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST


@login_required
@require_POST
def create_citacao_view(request):
    titulo = request.POST.get('titulo')
    conteudo = request.POST.get('conteudo')
    is_public_str = request.POST.get('is_public', 'true')
    is_public = str(is_public_str).lower() == 'true'

    if not titulo:
        return JsonResponse({'error': 'Título é obrigatório.'}, status=400)

    from ..models import BancoTese
    banco = BancoTese.objects.create(
        user=request.user,
        titulo=titulo,
        conteudo=conteudo or '',
        is_public=is_public
    )

    return JsonResponse({'success': True, 'id': banco.id, 'titulo': titulo, 'is_public': is_public})


@login_required
@require_POST
def editar_citacao_view(request, id):
    from ..models import BancoTese

    titulo = request.POST.get('titulo')
    conteudo = request.POST.get('conteudo')
    is_public_str = request.POST.get('is_public')

    if not titulo or not conteudo:
        return JsonResponse({'error': 'Título e Conteúdo são obrigatórios.'}, status=400)

    try:
        citacao = BancoTese.objects.get(id=id, user=request.user)
        citacao.titulo = titulo
        citacao.conteudo = conteudo
        if is_public_str is not None:
            citacao.is_public = str(is_public_str).lower() == 'true'
        citacao.save()
        return JsonResponse({'success': True, 'id': citacao.id, 'titulo': citacao.titulo, 'is_public': citacao.is_public})
    except BancoTese.DoesNotExist:
        return JsonResponse({'error': 'Citação não encontrada ou permissão negada.'}, status=404)


@login_required
@require_POST
def excluir_citacao_view(request, id):
    from ..models import BancoTese
    try:
        citacao = BancoTese.objects.get(id=id, user=request.user)
        citacao.delete()
        return JsonResponse({'success': True})
    except BancoTese.DoesNotExist:
        return JsonResponse({'error': 'Citação não encontrada ou permissão negada.'}, status=404)


@login_required
@require_POST
def increment_citacao_usage_view(request, id):
    from ..models import BancoTese
    from django.db.models import F, Q
    try:
        # Permite incrementar citações públicas ou citações próprias do usuário
        updated = BancoTese.objects.filter(
            Q(id=id) & (Q(is_public=True) | Q(user=request.user))
        ).update(usage_count=F('usage_count') + 1)
        if not updated:
            return JsonResponse({'error': 'Citação não encontrada.'}, status=404)
        usage_count = BancoTese.objects.values_list('usage_count', flat=True).get(id=id)
        return JsonResponse({'success': True, 'usage_count': usage_count})
    except BancoTese.DoesNotExist:
        return JsonResponse({'error': 'Citação não encontrada.'}, status=404)


@login_required
@require_POST
def import_citacao_comunidade_view(request, id):
    from ..models import BancoTese
    from django.db.models import F
    try:
        citacao_original = BancoTese.objects.get(id=id)

        nova_citacao = BancoTese.objects.create(
            user=request.user,
            titulo=citacao_original.titulo,
            conteudo=citacao_original.conteudo,
            is_public=False,
            usage_count=0
        )

        BancoTese.objects.filter(id=id).update(usage_count=F('usage_count') + 1)

        return JsonResponse({'success': True, 'id': nova_citacao.id, 'titulo': nova_citacao.titulo})
    except BancoTese.DoesNotExist:
        return JsonResponse({'error': 'Citação não encontrada.'}, status=404)
