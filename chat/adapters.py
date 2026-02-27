from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
from allauth.account.models import EmailAddress

User = get_user_model()

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        # Ignora se já está vinculado
        if sociallogin.is_existing:
            return

        # Busca o email recebido pela conta social (Google)
        email = sociallogin.account.extra_data.get('email')
        if not email:
            return

        # Verifica se a provedora do serviço social garante a verificação do e-mail
        # Para o Google, o payload contém "email_verified": True
        is_verified = sociallogin.account.extra_data.get('email_verified', False)
        
        # Se for do Google e estiver verificado, garante que não mande e-mail extra de confirmação
        if sociallogin.account.provider == 'google' and is_verified:
            try:
                user = User.objects.get(email=email)
                sociallogin.connect(request, user)
                
                # Marca o endereço de e-mail local do usuário como confirmado
                EmailAddress.objects.get_or_create(
                    user=user, 
                    email=email, 
                    defaults={'verified': True, 'primary': True}
                )
            except User.DoesNotExist:
                pass
