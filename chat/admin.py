from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.core.cache import cache
from .models import ConfiguracaoParecer, ParecerFinal, Parecer, Pasta, UserProfile, PjariCacheConfig, PjariCacheEntry, AiRequestLog, Subscription

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Perfil de Créditos e Assinatura'
    fields = ('credits', 'is_pro', 'subscription_status', 'subscription_start_at', 'subscription_expires_at', 'can_view_global_stats')
    readonly_fields = ('subscription_start_at', 'subscription_expires_at')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plano', 'creditos_base', 'creditos_bonus', 'data_inicio', 'data_expiracao', 'is_active', 'stripe_session_id')
    list_filter = ('plano', 'is_active')
    search_fields = ('user__username', 'stripe_session_id')
    readonly_fields = ('stripe_session_id',)
    
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

from .models import ConfiguracaoParecer, ParecerFinal, Parecer, Pasta, UserProfile, PjariCacheConfig, PjariCacheEntry, AiRequestLog, PjariVersion

@admin.register(PjariVersion)
class PjariVersionAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'major', 'minor', 'patch', 'atualizado_em')
    readonly_fields = ('logica_hash', 'atualizado_em')
    fieldsets = (
        ('Versionamento Semântico', {
            'fields': ('major', 'minor', 'patch'),
            'description': 'Atenção: A JARI atualiza automaticamente o "Minor" (2ª casa) quando a Lógica JARI muda. Use o "Patch" (3ª casa) para indicar atualizações de Leis no Vertex AI.'
        }),
        ('Sistema (Apenas Leitura)', {
            'fields': ('logica_hash', 'atualizado_em')
        }),
    )

    def save_model(self, request, obj, form, change):
        # Sincroniza o logica_hash com o estado atual do arquivo para evitar
        # que o context_processor auto-incremente o minor logo após o save manual
        import os, hashlib
        from django.conf import settings as dj_settings
        logica_path = os.path.join(dj_settings.BASE_DIR, 'logica_jari.md')
        if os.path.exists(logica_path):
            with open(logica_path, 'rb') as f:
                h = hashlib.md5()
                while chunk := f.read(8192):
                    h.update(chunk)
            obj.logica_hash = h.hexdigest()
        super().save_model(request, obj, form, change)
        cache.delete('pjari_version_display_text')

    def has_add_permission(self, request):
        # Apenas um registro permitido (Singleton)
        if self.model.objects.count() >= 1:
            return False
        return super().has_add_permission(request)

admin.site.register(ConfiguracaoParecer)

@admin.register(Parecer)
class ParecerAdmin(admin.ModelAdmin):
    list_select_related = ['user', 'pasta']
    list_display = ['__str__', 'status_fase', 'pa', 'sgpe', 'blindagem_score', 'created_at']
    search_fields = ['nome_processo', 'user__username', 'pa', 'sgpe']
    list_filter = ['status_fase']
    readonly_fields = ['score_baseline_90d']

    def score_baseline_90d(self, obj):
        """
        Contextualiza o blindagem_score deste parecer dentro da distribuição
        dos últimos 90 dias — responde "score 70 é bom ou ruim?"
        """
        from .models import Parecer as _P
        stats = _P.score_stats(days=90)
        if not stats:
            return 'Sem dados de baseline (últimos 90 dias).'

        global_str = (
            f"Global 90d — N={stats['count']} | Média={stats['avg']} | "
            f"P25={stats['p25']} | P50 (mediana)={stats['p50']} | P75={stats['p75']}"
        )

        score = obj.blindagem_score
        if score is None:
            return f'Este parecer ainda não foi auditado. {global_str}'

        if score >= stats['p75']:
            nivel = '▲ TOP 25% (acima de P75)'
        elif score >= stats['p50']:
            nivel = '~ Acima da mediana'
        elif score >= stats['p25']:
            nivel = '▼ Abaixo da mediana'
        else:
            nivel = '↓↓ Quartil inferior (abaixo de P25)'

        return f'Score {score} — {nivel} | {global_str}'

    score_baseline_90d.short_description = 'Score vs. Baseline (90 dias)'

@admin.register(Pasta)
class PastaAdmin(admin.ModelAdmin):
    list_select_related = ['user']
    list_display = ['__str__', 'created_at']
    search_fields = ['nome_pasta', 'user__username']

@admin.register(ParecerFinal)
class ParecerFinalAdmin(admin.ModelAdmin):
    list_select_related = ['parecer_referencia']
    list_display = ['__str__', 'status_resultado', 'data_criacao']
    list_filter = ['status_resultado']
