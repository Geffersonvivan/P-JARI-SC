from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class DocumentoLegal(models.Model):
    TIPO_CHOICES = (
        ('TERMO_USO', 'Termos de Uso'),
        ('POLITICA_PRIVACIDADE', 'Política de Privacidade'),
    )

    tipo = models.CharField(max_length=50, choices=TIPO_CHOICES)
    versao = models.CharField(max_length=20, help_text="Ex: 1.0, 1.1, 2.0")
    conteudo = models.TextField(help_text="Conteúdo HTML do documento")
    is_active = models.BooleanField(default=False, help_text="Apenas um documento por tipo pode estar ativo")
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_publicacao = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Documento Legal"
        verbose_name_plural = "Documentos Legais"
        unique_together = ('tipo', 'versao')
        ordering = ['-data_publicacao']

    def __str__(self):
        return f"{self.get_tipo_display()} - Versão {self.versao} ({'Ativo' if self.is_active else 'Inativo'})"

    def save(self, *args, **kwargs):
        # Se este documento está sendo ativado, desativa todos os outros do mesmo tipo
        if self.is_active:
            DocumentoLegal.objects.filter(tipo=self.tipo, is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

class AceiteDocumentoLegal(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='aceites_legais')
    documento = models.ForeignKey(DocumentoLegal, on_delete=models.CASCADE, related_name='aceites')
    ip_usuario = models.GenericIPAddressField(null=True, blank=True)
    data_hora = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Aceite de Documento Legal"
        verbose_name_plural = "Aceites de Documentos Legais"
        unique_together = ('user', 'documento')
        ordering = ['-data_hora']

    def __str__(self):
        return f"{self.user.username} aceitou {self.documento.get_tipo_display()} v{self.documento.versao} em {self.data_hora.strftime('%d/%m/%Y %H:%M')}"
