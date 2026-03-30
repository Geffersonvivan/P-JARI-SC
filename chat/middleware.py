from django.shortcuts import redirect
from django.urls import reverse
from django.core.cache import cache
from legal.models import DocumentoLegal, AceiteDocumentoLegal

class RequireTermsAcceptanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            allowed_urls = [
                reverse('aceitar_termos'),
                reverse('termos'),
                '/admin/',
                '/static/',
                '/media/'
            ]

            is_allowed = any(request.path.startswith(url) for url in allowed_urls)

            if not is_allowed:
                # Cache Redis por usuário: evita 4 queries DB a cada request autenticado.
                # TTL de 6h — invalidado explicitamente quando o usuário aceita os termos.
                _cache_key = f"termos_ok_{request.user.pk}"
                termos_verificados = cache.get(_cache_key)
                if not termos_verificados:
                    precisa_aceitar = False

                    # Busca os documentos atualmente ativos (buscamos Apenas ID para não baixar Textos Gigantes na RAM bloqueando o IO)
                    termo_ativo = DocumentoLegal.objects.filter(tipo='TERMO_USO', is_active=True).only('id').first()
                    politica_ativa = DocumentoLegal.objects.filter(tipo='POLITICA_PRIVACIDADE', is_active=True).only('id').first()

                    # Verifica se o usuário logado aceitou a versão EXATA de ambos os documentos
                    if termo_ativo:
                        aceitou_termo = AceiteDocumentoLegal.objects.filter(user=request.user, documento=termo_ativo).exists()
                        if not aceitou_termo:
                            precisa_aceitar = True

                    if politica_ativa:
                        aceitou_politica = AceiteDocumentoLegal.objects.filter(user=request.user, documento=politica_ativa).exists()
                        if not aceitou_politica:
                            precisa_aceitar = True

                    if precisa_aceitar:
                        return redirect('aceitar_termos')
                    else:
                        cache.set(_cache_key, True, timeout=21600)  # 6h

        return self.get_response(request)
