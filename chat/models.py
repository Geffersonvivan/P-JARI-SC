from django.db import models
from django.contrib.auth.models import User

class Pasta(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pastas', null=True, blank=True)
    session_key = models.CharField(max_length=40, null=True, blank=True)
    nome_pasta = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    posicao = models.IntegerField(default=0)

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
    # status_fase mapping:
    # 1 = Coleta
    # 2 = DIR (Double check)
    # 3 = Admissibilidade gerada (Aguardando OK)
    # 31 = Admissibilidade OK (Avança pra 4 ou 5 se intempestivo)
    # 4 = Coletando Tese
    # 41 = Tese analisada (Aguardando OK)
    # 5 = Gerando Parecer
    # 6 = Auditoria Blindagem
    # 7 = Seleção Pasta
    # 8 = Finalizado
    status_fase = models.IntegerField(default=1) 
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
    
    # Flags Booleanas Calculadas (Regras de Ouro - Fase 3 do Motor)
    is_tempestivo = models.BooleanField(null=True, blank=True)
    has_prescricao_punitiva = models.BooleanField(null=True, blank=True)
    has_prescricao_intercorrente = models.BooleanField(null=True, blank=True)
    has_decadencia = models.BooleanField(null=True, blank=True)
    
    # Textos gerados pelas IAs nas Fases 3 a 6
    admissibilidade_texto = models.TextField(blank=True, null=True)
    tese = models.TextField(blank=True, null=True)
    vertex_result = models.TextField(blank=True, null=True)
    perplexity_result = models.TextField(blank=True, null=True)
    analise_tese_texto = models.TextField(blank=True, null=True)
    parecer_final = models.TextField(blank=True, null=True)
    dossie_fontes = models.TextField(blank=True, null=True)
    nota_blindagem = models.TextField(blank=True, null=True)
    tabela_datas_sensiveis = models.TextField(blank=True, null=True)
    
    # Fase 6 - Auditoria e Blindagem
    blindagem_score = models.IntegerField(null=True, blank=True)
    blindagem_detalhes = models.TextField(blank=True, null=True)
    tempo_julgamento_segundos = models.IntegerField(null=True, blank=True)
    
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

class PjariCacheConfig(models.Model):
    is_active = models.BooleanField(default=True, verbose_name="Ativar PJARI-CACHE", help_text="Se desativado, o sistema sempre fará buscas externas na Fase 4 e 5.")
    total_requests = models.IntegerField(default=0, verbose_name="Total de Consultas")
    total_hits = models.IntegerField(default=0, verbose_name="Total de Hits (Acertos no Cache)")

    class Meta:
        verbose_name = "PJARI-CACHE: Configuração e Métricas"
        verbose_name_plural = "PJARI-CACHE: Configurações"

    def __str__(self):
        return f"Status do Cache: {'Ativo' if self.is_active else 'Inativo'}"

    @property
    def hit_rate(self):
        if self.total_requests == 0:
            return "0.00%"
        return f"{(self.total_hits / self.total_requests) * 100:.2f}%"


class PjariCacheEntry(models.Model):
    cache_key = models.CharField(max_length=255, unique=True, verbose_name="Chave de Cache (Artigo + Núcleo)")
    vertex_result = models.TextField(verbose_name="Resultado Vertex (Fundamentação)")
    perplexity_result = models.TextField(verbose_name="Resultado Perplexity (Jurisprudência)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Data de Criação")
    hit_count = models.IntegerField(default=0, verbose_name="Vezes Utilizadas")

    class Meta:
        verbose_name = "PJARI-CACHE: Memória Armazenada"
        verbose_name_plural = "PJARI-CACHE: Memórias Armazenadas"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.cache_key} (Usos: {self.hit_count})"


class AiRequestLog(models.Model):
    parecer_referencia = models.ForeignKey(Parecer, on_delete=models.CASCADE, related_name='ai_logs', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ai_logs')
    provider = models.CharField(max_length=50) # Gemini, Perplexity, Vertex
    fase = models.CharField(max_length=50, blank=True, null=True)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    data_requisicao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        nome_usuario = self.user.username if self.user else "Anon"
        return f"{self.provider} - Fase {self.fase} - User: {nome_usuario}"
        
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    is_pro = models.BooleanField(default=False)
    credits = models.IntegerField(default=5)
    mp_customer_id = models.CharField(max_length=255, blank=True, null=True)
    subscription_status = models.CharField(max_length=50, default='inactive')
    viu_boas_vindas = models.BooleanField(default=False)
    can_view_global_stats = models.BooleanField(default=False, verbose_name="Ver Painel Global")
    
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

from allauth.account.signals import user_signed_up
from django.core.mail import send_mail
from django.conf import settings

@receiver(user_signed_up)
def notify_admin_on_signup(request, user, **kwargs):
    nome_usuario = user.first_name if user.first_name else user.username
    email_usuario = user.email
    
    subject = f"🚀 Novo Cadastro no P-JARI: {nome_usuario}"
    message = (
        f"Olá Gefferson,\n\n"
        f"Alguém acabou de se cadastrar no P-JARI/SC!\n\n"
        f"Nome: {nome_usuario}\n"
        f"E-mail: {email_usuario}\n\n"
        f"Acesse o painel para gerenciar seus créditos."
    )
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            ['geffersonvivan@gmail.com'],
            fail_silently=True,
        )
    except Exception as e:
        print(f"Erro ao enviar email de notificação de signup: {e}")

class BancoTese(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='banco_teses')
    titulo = models.CharField(max_length=255)
    conteudo = models.TextField()
    is_public = models.BooleanField(default=True)
    usage_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.titulo} - {self.user.username}"


class PostForum(models.Model):
    autor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts_forum')
    conteudo = models.TextField()
    data_criacao = models.DateTimeField(auto_now_add=True)
    curtidas = models.ManyToManyField(User, related_name='postagens_curtidas', blank=True)

    class Meta:
        ordering = ['-data_criacao']

    def __str__(self):
        return f"Post de {self.autor.username} em {self.data_criacao.strftime('%d/%m/%Y')}"

    @property
    def numero_curtidas(self):
        return self.curtidas.count()

class ComentarioForum(models.Model):
    post = models.ForeignKey(PostForum, on_delete=models.CASCADE, related_name='comentarios')
    autor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comentarios_forum')
    conteudo = models.TextField()
    data_criacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['data_criacao']

    def __str__(self):
        return f"Comentário de {self.autor.username} no post {self.post.id}"
