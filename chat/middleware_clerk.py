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
                    response = requests.get(jwks_url, headers=headers, timeout=5)
                    response.raise_for_status()
                    jwks = response.json()
                    cache.set("clerk_jwks", jwks, timeout=3600)  # cache por 1h
                
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
                        options={"verify_aud": False} # A aplicação web às vezes não manda AUD
                    )
                    
                    clerk_user_id = payload.get("sub")
                    if clerk_user_id:
                        user = User.objects.filter(username=clerk_user_id).first()
                        if user:
                            request.user = user  # Injeta no ciclo do Django

            except Exception as e:
                # Falha silenciosamente, o usuário continuará como AnonymousUser
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Erro ao validar token do Clerk: {e}")

        response = self.get_response(request)
        return response
