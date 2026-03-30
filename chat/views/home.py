from django.shortcuts import render, redirect
from django.db.models import Prefetch, Count, Q
from django.conf import settings
from ..models import Parecer, Pasta


def _get_filter_kwargs(request):
    if request.user.is_authenticated:
        return {'user': request.user}
    return {'user': None, 'session_key': request.session.session_key}


PLANS = {
    'extra':       {'title': 'P-JARI/SC 1 Crédito Extra',          'price': 20.00,   'credits': 1,  'is_pro': False},
    'basic':       {'title': 'P-JARI/SC Básico (40 Pareceres)',     'price': 720.00,  'credits': 40, 'is_pro': True},
    'pro':         {'title': 'P-JARI/SC Profissional (80 Pareceres)','price': 1440.00,'credits': 80, 'is_pro': True},
}


def landing_page_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    return render(request, 'landing.html', {
        'CLERK_PUBLISHABLE_KEY': getattr(settings, 'CLERK_PUBLISHABLE_KEY', '')
    })


def home_view(request):
    if not request.user.is_authenticated:
        return redirect('landing')
        
    if not request.session.session_key:
        request.session.create()

    filter_kwargs = _get_filter_kwargs(request)

    # Otimização extrema de Queries (Redução de 6 queries de Banco para apenas 2):
    # Em vez de fazer múltiplos Count() e Prefetches isolados usando o DB, nós pedimos tudo e separamos no Python.
    projetos_salvos = Prefetch('projetos', queryset=Parecer.objects.filter(is_saved=True).only('id', 'pasta_id', 'nome_processo', 'created_at', 'is_saved', 'recorrente', 'sgpe', 'pa', 'status_fase').order_by('-created_at'))

    todas_pastas = list(Pasta.objects.filter(**filter_kwargs).prefetch_related(projetos_salvos).annotate(
        num_projetos=Count('projetos', filter=Q(projetos__is_saved=True))
    ).order_by('posicao', '-created_at'))

    pasta_outros = next((p for p in todas_pastas if p.nome_pasta == "Outros"), None)

    if not pasta_outros:
        pasta_outros = Pasta.objects.create(nome_pasta="Outros", **filter_kwargs)
        pasta_outros.num_projetos = 0
        # Simula o objeto carregado para evitar que o template acione Lazy Load no BD
        from django.db.models.query import QuerySet
        setattr(pasta_outros, '_prefetched_objects_cache', {'projetos': []})
    else:
        todas_pastas.remove(pasta_outros)

    pastas = todas_pastas

    # Calcula o total de julgados somando as contagens que já estão na memória (Economiza 1 query extra)
    total_julgados = sum(p.num_projetos for p in pastas) + pasta_outros.num_projetos

    from ..models import BancoTese, PostForum, ComentarioForum
    if request.user.is_authenticated:
        banco_teses = BancoTese.objects.filter(user=request.user).order_by('-created_at')
        teses_comunidade = BancoTese.objects.filter(is_public=True).exclude(user=request.user).order_by('-usage_count')[:20]

        # Correção severa de performance: Consulta otimizada apenas pelo timestamp para notificar novos posts.
        ultimo_post = PostForum.objects.only('data_criacao').order_by('-data_criacao').first()
        ultimo_acesso = request.user.profile.ultimo_acesso_forum
        tem_novidade_forum = bool(
            ultimo_post and (not ultimo_acesso or ultimo_post.data_criacao > ultimo_acesso)
        )
        posts_forum = [] # A lista é zerada pois a home não renderiza o forum diretamente
    else:
        banco_teses = []
        teses_comunidade = []
        posts_forum = []
        tem_novidade_forum = False

    return render(request, 'home.html', {
        'CLERK_PUBLISHABLE_KEY': getattr(settings, 'CLERK_PUBLISHABLE_KEY', ''),
        'pasta_outros': pasta_outros,
        'pastas': pastas,
        'total_julgados': total_julgados,
        'banco_teses': banco_teses,
        'teses_comunidade': teses_comunidade,
        'posts_forum': posts_forum,
        'tem_novidade_forum': tem_novidade_forum,
        'pjari_version': getattr(settings, 'PJARI_VERSION', '1.2'),
        'online_users_count': total_julgados or 0,
    })
