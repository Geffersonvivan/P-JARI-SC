import os
import json
import jwt
import requests
from django.contrib.auth.models import User
from django.core.cache import cache

class ClerkAuthenticationMiddleware:
    """
    Inspeciona o header 'Authorization: Bearer <token>' enviado pelo Frontend 
    do Clerk, valida a assinatura JWT contra o endpoint JWKS do Clerk e loga o usuário no request.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.clerk_secret_key = os.getenv("CLERK_SECRET_KEY")
        # O Publishable Key identifica esta instância Clerk — usado para validar o claim 'azp'
        self.clerk_publishable_key = os.getenv("CLERK_PUBLISHABLE_KEY", "")

    def __call__(self, request):
        auth_header = request.headers.get("Authorization")
        token = None
        
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        elif "__session" in request.COOKIES:
            token = request.COOKIES.get("__session")
            
        if token:
            try:
                # Buscar chaves JWKS em cache para evitar requisicao a cada hit
                jwks = cache.get("clerk_jwks")
                if not jwks:
                    # Para pegar JWKS, precisa chamar a API do Clerk usando a SECRET_KEY
                    jwks_url = "https://api.clerk.com/v1/jwks"
                    headers = {"Authorization": f"Bearer {self.clerk_secret_key}"}
                    try:
                        response = requests.get(jwks_url, headers=headers, timeout=2)
                        response.raise_for_status()
                        jwks = response.json()
                        cache.set("clerk_jwks", jwks, timeout=3600)  # cache por 1h
                    except requests.exceptions.Timeout:
                        import logging
                        logging.getLogger(__name__).warning("Clerk JWKS fetch timeout — skipping auth this request")
                        jwks = None
                
                if not jwks:
                    response = self.get_response(request)
                    return response

                # Encontrar a chave pública que corresponde ao 'kid' do token
                unverified_header = jwt.get_unverified_header(token)
                rsa_key = {}
                for key in jwks.get("keys", []):
                    if key.get("kid") == unverified_header.get("kid"):
                        rsa_key = {
                            "kty": key.get("kty"),
                            "kid": key.get("kid"),
                            "use": key.get("use"),
                            "n": key.get("n"),
                            "e": key.get("e")
                        }
                        break

                if rsa_key:
                    # PyJWT 2.0+ requer formato de chave PEM adequado se fornecemos apenas n e e
                    # Para simplificar, PyJWT possui jwt.algorithms.RSAAlgorithm.from_jwk()
                    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(rsa_key))
                    
                    # Valida o token e extrai payload
                    payload = jwt.decode(
                        token,
                        public_key,
                        algorithms=["RS256"],
                        options={"verify_aud": False}  # Clerk não garante 'aud'; validamos 'azp' abaixo
                    )

                    # Valida 'azp' (authorized party) para garantir que o token é desta instância Clerk.
                    # No ambiente de desenvolvimento, o Clerk às vezes preenche 'azp' com a URL de origem.
                    azp = payload.get("azp", "")
                    allowed_azps = [self.clerk_publishable_key, "http://127.0.0.1:8000", "http://localhost:8000", "https://pjarisc.com.br", "https://www.pjarisc.com.br"]
                    if self.clerk_publishable_key and azp and azp not in allowed_azps:
                        import logging
                        logging.getLogger(__name__).warning(f"JWT rejeitado: azp '{azp}' não corresponde à instância")
                        response = self.get_response(request)
                        return response

                    clerk_user_id = payload.get("sub")
                    if clerk_user_id:
                        user = User.objects.filter(username=clerk_user_id).first()
                        
                        # Fallback Just-In-Time (JIT): Se o usuário não existe no Django (webhook falhou ou é legado)
                        # Self-healing: Se o usuário existe mas está sem nome (ex: Google SSO sync issue)
                        _sync_cache_key = f"clerk_user_synced_{clerk_user_id}"
                        _already_synced = cache.get(_sync_cache_key)
                        if not _already_synced and (not user or not user.first_name):
                            # Busca os dados do Clerk (máx 1x a cada 5 min por usuário)
                            cache.set(_sync_cache_key, True, timeout=300)
                            user_url = f"https://api.clerk.com/v1/users/{clerk_user_id}"
                            headers = {"Authorization": f"Bearer {self.clerk_secret_key}"}
                            try:
                                response = requests.get(user_url, headers=headers, timeout=2)
                            except requests.exceptions.Timeout:
                                import logging
                                logging.getLogger(__name__).warning(f"Clerk JIT user sync timeout for {clerk_user_id}")
                                response = None
                            if response and response.status_code == 200:
                                clerk_data = response.json()
                                email_addresses = clerk_data.get("email_addresses", [])
                                email = email_addresses[0].get("email_address") if email_addresses else ""
                                first_name = clerk_data.get("first_name") or ""
                                last_name = clerk_data.get("last_name") or ""
                                
                                # Verifica se já existe um usuário com esse email (Legado do django-allauth)
                                if not user:
                                    old_user = User.objects.filter(email=email).first() if email else None
                                    if old_user and old_user.username != clerk_user_id:
                                        # Migra o usuário antigo mudando apenas o username para o ID do Clerk
                                        old_user.username = clerk_user_id
                                        old_user.first_name = first_name[:30] if first_name else old_user.first_name
                                        old_user.last_name = last_name[:30] if last_name else old_user.last_name
                                        old_user.save()
                                        user = old_user
                                    else:
                                        # Cria um usuário local totalmente novo atrelado ao Clerk
                                        user = User.objects.create(
                                            username=clerk_user_id, 
                                            email=email, 
                                            first_name=first_name[:30], 
                                            last_name=last_name[:30]
                                        )
                                        user.set_unusable_password()
                                        user.save()
                                elif user and not user.first_name:
                                    # Self-healing: User already exists but has no name
                                    user.first_name = first_name[:30]
                                    user.last_name = last_name[:30]
                                    user.save(update_fields=['first_name', 'last_name'])
                                    # Sync concluído com sucesso — estende cache para 1h
                                    cache.set(_sync_cache_key, True, timeout=3600)

                        if user:
                            request.user = user  # Injeta no ciclo do Django

            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error("Erro ao validar token do Clerk: %s", e)
                
                # Em vez de travar o app com erro 401, redireciona o usuário para a Home.
                # A tela Home possui o ClerkJS injetado, que cuidará de renovar o cookie silenciosamente
                if request.path.startswith('/app/'):
                    from django.shortcuts import redirect
                    return redirect('/')
                
                # Falha: se não for admin, força usuário anônimo
                if not request.path.startswith('/admin/'):
                    from django.contrib.auth.models import AnonymousUser
                    request.user = AnonymousUser()
        else:
            logger.debug("Token NÃO encontrado nos headers nem nos cookies.")
            # Sem token presente: ignora qualquer sessão legado se não for painel admin
            if not request.path.startswith('/admin/'):
                from django.contrib.auth.models import AnonymousUser
                request.user = AnonymousUser()

        response = self.get_response(request)
        return response
