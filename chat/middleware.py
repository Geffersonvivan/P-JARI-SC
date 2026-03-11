from django.shortcuts import redirect
from django.urls import reverse
from legal.models import DocumentoLegal, AceiteDocumentoLegal

class RequireTermsAcceptanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Lista de URLs permitidas sem aceite (evita loop infinito)
            allowed_urls = [
                reverse('aceitar_termos'),
                reverse('account_logout'),
                '/admin/',
                '/static/',
                '/media/'
            ]

            is_allowed = any(request.path.startswith(url) for url in allowed_urls)

            if not is_allowed:
                # Otimização: Se já verificou nesta sessão que ele está ok, não consulta o BD.
                # Nota: Sempre que houver um NOVO documento is_active, teremos que invalidar a sessão.
                termos_verificados = request.session.get('documentos_legais_verificados', False)
                if not termos_verificados:
                    precisa_aceitar = False

                    # Busca os documentos atualmente ativos
                    termo_ativo = DocumentoLegal.objects.filter(tipo='TERMO_USO', is_active=True).first()
                    politica_ativa = DocumentoLegal.objects.filter(tipo='POLITICA_PRIVACIDADE', is_active=True).first()

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
                        request.session['documentos_legais_verificados'] = True

        return self.get_response(request)
