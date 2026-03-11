from django.contrib import admin
from .models import DocumentoLegal, AceiteDocumentoLegal

@admin.register(DocumentoLegal)
class DocumentoLegalAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'versao', 'is_active', 'data_publicacao')
    list_filter = ('tipo', 'is_active')
    search_fields = ('versao', 'conteudo')
    ordering = ('-data_publicacao',)

@admin.register(AceiteDocumentoLegal)
class AceiteDocumentoLegalAdmin(admin.ModelAdmin):
    list_display = ('user', 'get_tipo_documento', 'get_versao_documento', 'data_hora', 'ip_usuario')
    list_filter = ('documento__tipo', 'data_hora')
    search_fields = ('user__username', 'user__email', 'ip_usuario')
    ordering = ('-data_hora',)
    readonly_fields = ('user', 'documento', 'ip_usuario', 'data_hora')

    def get_tipo_documento(self, obj):
        return obj.documento.get_tipo_display()
    get_tipo_documento.short_description = 'Tipo'
    get_tipo_documento.admin_order_field = 'documento__tipo'

    def get_versao_documento(self, obj):
        return obj.documento.versao
    get_versao_documento.short_description = 'Versão'
    get_versao_documento.admin_order_field = 'documento__versao'
