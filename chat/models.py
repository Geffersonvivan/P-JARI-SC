from django.db import models
from django.contrib.auth.models import User

class Pasta(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pastas', null=True, blank=True)
    session_key = models.CharField(max_length=40, null=True, blank=True)
    nome_pasta = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        nome_usuario = self.user.username if self.user else "Anon"
        return f'{self.nome_pasta} - {nome_usuario}'

class Parecer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pareceres', null=True, blank=True)
    session_key = models.CharField(max_length=40, null=True, blank=True)
    pasta = models.ForeignKey(Pasta, on_delete=models.CASCADE, related_name='projetos', null=True, blank=True)
    nome_processo = models.CharField(max_length=255)
    is_saved = models.BooleanField(default=True)
    
    # Campos do Assessor JARI
    status_fase = models.IntegerField(default=1) # Fases 1 a 6
    pa = models.CharField(max_length=100, blank=True, null=True)
    sgpe = models.CharField(max_length=100, blank=True, null=True)
    recorrente = models.CharField(max_length=255, blank=True, null=True)
    data_sessao = models.DateField(blank=True, null=True)
    data_protocolo = models.DateField(blank=True, null=True)
    prazo_final = models.DateField(blank=True, null=True)
    paginas_defesa = models.CharField(max_length=100, blank=True, null=True)
    
    # Arquivos (Uso temporário para não quebrar; idealmente devem ir para S3 ou MEDIA_ROOT)
    autuacao_pdf_path = models.CharField(max_length=500, blank=True, null=True)
    consolidado_pdf_path = models.CharField(max_length=500, blank=True, null=True)
    
    # Textos da Fase 4 a 6
    tese = models.TextField(blank=True, null=True)
    parecer_final = models.TextField(blank=True, null=True)
    nota_blindagem = models.CharField(max_length=100, blank=True, null=True)
    
    # Meta dados
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        nome_usuario = self.user.username if self.user else "Anon"
        return f'{self.nome_processo} - {nome_usuario}'

    class Meta:
        ordering = ['-created_at']

class ConfiguracaoParecer(models.Model):
    # Cabeçalho
    logo = models.ImageField(upload_to='assets/logos/', help_text="Logo em PNG")
    titulo_cabecalho = models.TextField(default="ESTADO DE SANTA CATARINA\nDEPARTAMENTO ESTADUAL DE TRÂNSITO")
    subtitulo_cabecalho = models.TextField(blank=True, default="JUNTA ADMINISTRATIVA DE RECURSOS DE INFRAÇÃO –\nJARI REGIONAL DE CHAPECÓ")
    
    # Rodapés Condicionais
    rodape_deferido = models.TextField(help_text="HTML para caso de Deferimento")
    rodape_indeferido = models.TextField(help_text="HTML para caso de Indeferimento")

    def __str__(self):
        return "Configuração Global do Parecer"

    class Meta:
        verbose_name = "Configuração do Parecer"
        verbose_name_plural = "Configurações do Parecer"

class ParecerFinal(models.Model):
    parecer_referencia = models.ForeignKey(Parecer, on_delete=models.CASCADE, related_name='pareceres_finais', null=True, blank=True)
    conteudo_html = models.TextField()
    data_criacao = models.DateTimeField(auto_now_add=True)
    status_resultado = models.CharField(max_length=20) # Deferido ou Indeferido

    def __str__(self):
        nome = self.parecer_referencia.nome_processo if self.parecer_referencia else "Avulso"
        return f"Parecer Final: {nome} - {self.status_resultado}"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    is_pro = models.BooleanField(default=False)
    credits = models.IntegerField(default=2)
    mp_customer_id = models.CharField(max_length=255, blank=True, null=True)
    subscription_status = models.CharField(max_length=50, default='inactive')
    viu_boas_vindas = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Profile: {self.user.username} - PRO: {self.is_pro}"

from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()
