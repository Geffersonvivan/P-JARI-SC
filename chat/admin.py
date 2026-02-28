from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import ConfiguracaoParecer, ParecerFinal, Parecer, Pasta, UserProfile

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Perfil de Créditos e Assinatura'
    fields = ('credits', 'is_pro', 'subscription_status', 'mp_customer_id')

class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)

# Re-registrar o UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

admin.site.register(ConfiguracaoParecer)
admin.site.register(ParecerFinal)
admin.site.register(Parecer)
admin.site.register(Pasta)
