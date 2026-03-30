import json
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST


@login_required
@require_POST
def criar_post_forum_view(request):
    from ..models import PostForum
    try:
        conteudo = request.POST.get('conteudo', '').strip()
        imagem = request.FILES.get('imagem')

        if not conteudo:
            return JsonResponse({'status': 'error', 'message': 'Conteúdo não pode estar vazio.'}, status=400)

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


@login_required
@require_POST
def comentar_post_forum_view(request, post_id):
    from ..models import PostForum, ComentarioForum
    try:
        data = json.loads(request.body)
        conteudo = data.get('conteudo', '').strip()
        if not conteudo:
            return JsonResponse({'status': 'error', 'message': 'Conteúdo não pode estar vazio.'}, status=400)

        post = PostForum.objects.get(id=post_id)
        comentario = ComentarioForum.objects.create(
            post=post,
            autor=request.user,
            conteudo=conteudo
        )
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

        return JsonResponse({'status': 'success', 'comentarios': dados})
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
