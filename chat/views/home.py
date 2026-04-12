from django.shortcuts import render, redirect
from django.db.models import Prefetch, Count, Q
from django.conf import settings
from ..models import Parecer, Pasta


def _get_filter_kwargs(request):
    if request.user.is_authenticated:
        return {'user': request.user}
    return {'user': None, 'session_key': request.session.session_key}


PLANS = {
    'extra': {
        'title': 'P-JARI/SC 1 Crédito Extra',
        'price': 20.00,
        'credits_base': 1, 'credits_bonus': 0, 'credits': 1,
        'is_pro': False, 'is_subscription': False,
    },
    'basic': {
        'title': 'P-JARI/SC Básico (40 Pareceres)',
        'price': 720.00,
        'credits_base': 36, 'credits_bonus': 4, 'credits': 40,
        'is_pro': True, 'is_subscription': True,
    },
    'pro': {
        'title': 'P-JARI/SC Profissional (80 Pareceres)',
        'price': 1440.00,
        'credits_base': 72, 'credits_bonus': 8, 'credits': 80,
        'is_pro': True, 'is_subscription': True,
    },
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

    filter_kwargs = _get_filter_kwargs(request)

    # Otimização extrema de Queries (Redução de 6 queries de Banco para apenas 2):
    # Em vez de fazer múltiplos Count() e Prefetches isolados usando o DB, nós pedimos tudo e separamos no Python.
    projetos_salvos = Prefetch('projetos', queryset=Parecer.objects.filter(is_saved=True).only('id', 'pasta_id', 'nome_processo', 'created_at', 'is_saved', 'recorrente', 'sgpe', 'pa', 'status_fase').order_by('-created_at'))

    todas_pastas = list(Pasta.objects.filter(**filter_kwargs).prefetch_related(projetos_salvos).annotate(
        num_projetos=Count('projetos', filter=Q(projetos__is_saved=True))
    ).order_by('posicao', '-created_at'))

    pasta_outros = next((p for p in todas_pastas if p.nome_pasta == "Outros"), None)
    if pasta_outros:
        todas_pastas.remove(pasta_outros)

    pastas = todas_pastas

    # Calcula o total de julgados somando as contagens que já estão na memória (Economiza 1 query extra)
    total_julgados = sum(p.num_projetos for p in pastas)
    if pasta_outros:
        total_julgados += pasta_outros.num_projetos

    from ..models import BancoTese, PostForum, ComentarioForum
    if request.user.is_authenticated:
        banco_teses = BancoTese.objects.filter(user=request.user).order_by('-created_at')
        teses_comunidade = BancoTese.objects.filter(is_public=True).exclude(user=request.user).order_by('-usage_count')[:20]

        # Correção severa de performance: Consulta otimizada apenas pelo timestamp para notificar novos posts.
        ultimo_post = PostForum.objects.only('data_criacao').order_by('-data_criacao').first()
        
        try:
            ultimo_acesso = request.user.profile.ultimo_acesso_forum
        except Exception:
            from ..models import UserProfile
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            ultimo_acesso = profile.ultimo_acesso_forum
            
        tem_novidade_forum = bool(
            ultimo_post and (not ultimo_acesso or ultimo_post.data_criacao > ultimo_acesso)
        )
        posts_forum = PostForum.objects.select_related('autor').prefetch_related('curtidas', 'comentarios__autor').order_by('-data_criacao')[:50]
    else:
        banco_teses = []
        teses_comunidade = []
        posts_forum = []
        tem_novidade_forum = False

    user_credits = 0
    user_is_pro = False
    user_avatar_url = ''
    if request.user.is_authenticated:
        try:
            user_credits = request.user.profile.credits
            user_is_pro = request.user.profile.is_pro
        except Exception:
            pass
        try:
            from allauth.socialaccount.models import SocialAccount
            social = SocialAccount.objects.filter(user=request.user, provider='google').first()
            if social:
                user_avatar_url = social.extra_data.get('picture', '')
        except Exception:
            pass

    return render(request, 'home.html', {
        'CLERK_PUBLISHABLE_KEY': getattr(settings, 'CLERK_PUBLISHABLE_KEY', ''),
        'user_avatar_url': user_avatar_url,
        'pasta_outros': pasta_outros,
        'pastas': pastas,
        'total_julgados': total_julgados,
        'banco_teses': banco_teses,
        'teses_comunidade': teses_comunidade,
        'posts_forum': posts_forum,
        'tem_novidade_forum': tem_novidade_forum,
        'pjari_version': getattr(settings, 'PJARI_VERSION', '1.2'),
        'online_users_count': total_julgados or 0,
        'user_credits': user_credits,
        'user_is_pro': user_is_pro,
    })
