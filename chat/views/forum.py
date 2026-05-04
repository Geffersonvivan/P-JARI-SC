import json
import nh3
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

_FORUM_ALLOWED_TAGS = {'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'a', 'code', 'pre'}
_FORUM_ALLOWED_ATTRS = {'a': {'href', 'title'}}
_FORUM_MAX_LEN = 5000
_IMAGE_MAX_SIZE = 5 * 1024 * 1024  # 5 MB
_IMAGE_ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}


def _sanitize_forum(text: str) -> str:
    """Sanitiza texto do fórum, limitando tamanho e removendo tags perigosas."""
    return nh3.clean(text[:_FORUM_MAX_LEN], tags=_FORUM_ALLOWED_TAGS, attributes=_FORUM_ALLOWED_ATTRS)


def _validate_forum_image(imagem):
    """Valida tamanho e content_type de upload de imagem do fórum."""
    if imagem.size > _IMAGE_MAX_SIZE:
        return 'Imagem muito grande (máximo 5 MB).'
    if imagem.content_type not in _IMAGE_ALLOWED_TYPES:
        return 'Tipo de arquivo não permitido. Use JPEG, PNG, GIF ou WebP.'
    return None


@ratelimit(key='user', rate='10/m', method='POST', block=True)
@login_required
@require_POST
def criar_post_forum_view(request):
    from ..models import PostForum
    try:
        conteudo = _sanitize_forum(request.POST.get('conteudo', '').strip())
        imagem = request.FILES.get('imagem')

        if not conteudo:
            return JsonResponse({'status': 'error', 'message': 'Conteúdo não pode estar vazio.'}, status=400)

        if imagem:
            erro_img = _validate_forum_image(imagem)
            if erro_img:
                return JsonResponse({'status': 'error', 'message': erro_img}, status=400)

        post = PostForum.objects.create(
            autor=request.user,
            conteudo=conteudo,
            imagem=imagem
        )
        return JsonResponse({
            'status': 'success',
            'post_id': post.id,
            'autor': post.autor.first_name or post.autor.username,
            'conteudo': post.conteudo,
            'imagem_url': post.imagem.url if post.imagem else None,
            'data_criacao': post.data_criacao.strftime('%d/%m/%Y %H:%M')
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@ratelimit(key='user', rate='20/m', method='POST', block=True)
@login_required
@require_POST
def comentar_post_forum_view(request, post_id):
    from ..models import PostForum, ComentarioForum
    try:
        data = json.loads(request.body)
        conteudo = _sanitize_forum(data.get('conteudo', '').strip())
        if not conteudo:
            return JsonResponse({'status': 'error', 'message': 'Conteúdo não pode estar vazio.'}, status=400)

        post = PostForum.objects.get(id=post_id)
        comentario = ComentarioForum.objects.create(
            post=post,
            autor=request.user,
            conteudo=conteudo
        )
        from django.core.cache import cache as _cache
        _cache.delete(f'forum_comentarios_{post_id}')
        return JsonResponse({
            'status': 'success',
            'comentario_id': comentario.id,
            'autor': comentario.autor.first_name or comentario.autor.username,
            'conteudo': comentario.conteudo,
            'data_criacao': comentario.data_criacao.strftime('%d/%m/%Y %H:%M')
        })
    except PostForum.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Post não encontrado.'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@ratelimit(key='user', rate='30/m', method='POST', block=True)
@login_required
@require_POST
def curtir_post_forum_view(request, post_id):
    from ..models import PostForum
    try:
        post = PostForum.objects.get(id=post_id)
        if post.curtidas.filter(id=request.user.id).exists():
            post.curtidas.remove(request.user)
            curtiu = False
        else:
            post.curtidas.add(request.user)
            curtiu = True

        return JsonResponse({
            'status': 'success',
            'curtiu': curtiu,
            'numero_curtidas': post.numero_curtidas
        })
    except PostForum.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Post não encontrado.'}, status=404)


@login_required
def get_comentarios_forum_view(request, post_id):
    from django.core.cache import cache as _cache
    _ck = f'forum_comentarios_{post_id}'
    cached = _cache.get(_ck)
    if cached is not None:
        return JsonResponse(cached)

    from ..models import PostForum
    try:
        post = PostForum.objects.get(id=post_id)
        comentarios = post.comentarios.select_related('autor').all()
        dados = [{
            'id': c.id,
            'autor': c.autor.first_name or c.autor.username,
            'conteudo': c.conteudo,
            'data_criacao': c.data_criacao.strftime('%d/%m/%Y %H:%M')
        } for c in comentarios]

        result = {'status': 'success', 'comentarios': dados}
        _cache.set(_ck, result, timeout=60)
        return JsonResponse(result)
    except PostForum.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Post não encontrado.'}, status=404)


@login_required
@require_POST
def update_forum_access_view(request):
    try:
        from django.utils import timezone
        profile = request.user.profile
        profile.ultimo_acesso_forum = timezone.now()
        profile.save(update_fields=['ultimo_acesso_forum'])
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
