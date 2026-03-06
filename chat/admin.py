from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import ConfiguracaoParecer, ParecerFinal, Parecer, Pasta, UserProfile, PjariCacheConfig, PjariCacheEntry, AiRequestLog

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Perfil de Créditos e Assinatura'
    fields = ('credits', 'is_pro', 'subscription_status', 'mp_customer_id', 'can_view_global_stats')
    
@admin.register(AiRequestLog)
class AiRequestLogAdmin(admin.ModelAdmin):
    list_display = ('provider', 'fase', 'user', 'input_tokens', 'output_tokens', 'data_requisicao')
    list_filter = ('provider', 'fase')
    search_fields = ('user__username', 'parecer_referencia__nome_processo')


class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)

# Re-registrar o UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

@admin.register(PjariCacheConfig)
class PjariCacheConfigAdmin(admin.ModelAdmin):
    list_display = ('is_active', 'total_requests', 'total_hits', 'hit_rate')
    readonly_fields = ('total_requests', 'total_hits', 'hit_rate')

@admin.register(PjariCacheEntry)
class PjariCacheEntryAdmin(admin.ModelAdmin):
    list_display = ('cache_key', 'hit_count', 'created_at')
    search_fields = ('cache_key',)
    readonly_fields = ('created_at', 'hit_count')

admin.site.register(ConfiguracaoParecer)
admin.site.register(ParecerFinal)
admin.site.register(Parecer)
admin.site.register(Pasta)
