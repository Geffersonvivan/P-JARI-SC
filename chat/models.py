from django.db import models
from django.contrib.auth.models import User
from django.utils.functional import cached_property

class Pasta(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pastas', null=True, blank=True, db_index=True)
    session_key = models.CharField(max_length=40, null=True, blank=True, db_index=True)
    nome_pasta = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    posicao = models.IntegerField(default=0)

    def __str__(self):
        nome_usuario = self.user.username if self.user else "Anon"
        return f'{self.nome_pasta} - {nome_usuario}'

class Parecer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pareceres', null=True, blank=True, db_index=True)
    session_key = models.CharField(max_length=40, null=True, blank=True, db_index=True)
    pasta = models.ForeignKey(Pasta, on_delete=models.CASCADE, related_name='projetos', null=True, blank=True)
    nome_processo = models.CharField(max_length=255)
    is_saved = models.BooleanField(default=True, db_index=True)
    
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
    status_fase = models.IntegerField(default=1, db_index=True)
    pa = models.CharField(max_length=100, blank=True, null=True)
    sgpe = models.CharField(max_length=100, blank=True, null=True)
    recorrente = models.CharField(max_length=255, blank=True, null=True)
    data_sessao = models.DateField(blank=True, null=True)
    data_protocolo = models.DateField(blank=True, null=True)
    prazo_final = models.DateField(blank=True, null=True)
    paginas_defesa = models.CharField(max_length=100, blank=True, null=True)
    
    # Arquivos — armazenados via default_storage (GCS em produção, local em dev)
    autuacao_pdf_path = models.FileField(upload_to='uploads/', max_length=500, blank=True, null=True)
    consolidado_pdf_path = models.FileField(upload_to='uploads/', max_length=500, blank=True, null=True)
    ata_pdf_path = models.FileField(upload_to='uploads/', max_length=500, blank=True, null=True)
    
    # Flags Booleanas Calculadas (Regras de Ouro - Fase 3 do Motor)
    is_tempestivo = models.BooleanField(null=True, blank=True)
    has_prescricao_punitiva = models.BooleanField(null=True, blank=True)
    has_prescricao_intercorrente = models.BooleanField(null=True, blank=True)
    has_decadencia = models.BooleanField(null=True, blank=True)

    # Fase 1 — Extração automática via Gemini (JSON com campos + confiança)
    fase1_extracao_json = models.JSONField(blank=True, null=True)

    # Tipo de penalidade da autuação — determina regras de decadência FILTRO 2/3
    # Valores: 'multa', 'advertencia', 'suspensao', 'cassacao'
    tipo_penalidade = models.CharField(max_length=20, blank=True, null=True)
    # Data de conclusão do processo de multa que deu causa à suspensão/cassação (FILTRO 3)
    data_conclusao_multa = models.DateField(blank=True, null=True)
    # True = autuação em flagrante (marco = data_infracao); False = sem flagrante (marco = data_conhecimento_infracao)
    # None = não determinado (fallback conservador: usa data_infracao)
    tem_flagrante = models.BooleanField(blank=True, null=True)
    # Data do conhecimento da infração pelo órgão — marco FILTRO 3 para multas SEM flagrante (art. 282 §6º-A CTB)
    data_conhecimento_infracao = models.DateField(blank=True, null=True)
    # Data da infração extraída dos documentos na Fase 3 — usada para blindagem Filtro 1 na F31
    data_infracao = models.DateField(blank=True, null=True)
    # True = data_infracao veio do fallback min() — exige confirmação explícita do julgador na F31
    data_infracao_fallback = models.BooleanField(default=False)
    # Suspensão por acúmulo de pontos: marco inicial da prescrição punitiva = dia seguinte à totalização
    # logica_jari.md §221 — quando preenchido, substitui data_infracao no check_prescription_punitiva
    data_totalizacao_pontos = models.DateField(blank=True, null=True)

    # Escolhas do julgador (Fase 31 — A/B) — substituem as flags automáticas em todas as fases seguintes
    julgador_tempestivo = models.BooleanField(null=True, blank=True)
    julgador_prescricao_punitiva = models.BooleanField(null=True, blank=True)
    julgador_prescricao_intercorrente = models.BooleanField(null=True, blank=True)
    julgador_decadencia = models.BooleanField(null=True, blank=True)
    
    # Textos gerados pelas IAs nas Fases 3 a 6, ou extraidos do documento de origem (Fase 7)
    infracao_documento = models.CharField(max_length=255, blank=True, null=True)
    admissibilidade_texto = models.TextField(blank=True, null=True)
    tese = models.TextField(blank=True, null=True)
    vertex_result = models.TextField(blank=True, null=True)
    perplexity_result = models.TextField(blank=True, null=True)
    analise_tese_texto = models.TextField(blank=True, null=True)
    parecer_final = models.TextField(blank=True, null=True)
    # Coluna denormalizada: evita icontains em parecer_final (seq scan em TextField grande)
    # Populada automaticamente via save() a partir do conteúdo de parecer_final
    resultado_final = models.CharField(
        max_length=15, blank=True, null=True, db_index=True,
        help_text="DEFERIDO ou INDEFERIDO — derivado de parecer_final no save()"
    )
    dossie_fontes = models.TextField(blank=True, null=True)
    nota_blindagem = models.TextField(blank=True, null=True)
    tabela_datas_sensiveis = models.TextField(blank=True, null=True)
    
    # Fase 5 — Provider que gerou o parecer (usado na Fase 6 para auditor cruzado)
    fase5_provider = models.CharField(max_length=10, blank=True, null=True)

    # Fase 6 - Auditoria e Blindagem
    blindagem_score = models.IntegerField(null=True, blank=True)
    blindagem_detalhes = models.TextField(blank=True, null=True)
    checklist_auditoria_json = models.JSONField(blank=True, null=True)
    tempo_julgamento_segundos = models.IntegerField(null=True, blank=True)
    
    # Fase 8 - Feedback Contínuo do Usuário
    feedback_score = models.IntegerField(null=True, blank=True, help_text="Nota de 0 a 100 dada pelo usuário sobre o parecer gerado")
    feedback_tags = models.CharField(max_length=500, blank=True, null=True, help_text="Tags de erro pontuadas (ex: erro-de-data, erro-jurisprudencia)")
    feedback_notes = models.TextField(blank=True, null=True, help_text="Comentário livre do usuário sobre o que faltou na IA")

    # Meta dados
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Deriva resultado_final a partir do parecer_final para evitar icontains em TextField
        update_fields = kwargs.get('update_fields')
        if update_fields is None or 'parecer_final' in update_fields:
            if self.parecer_final:
                self.resultado_final = 'INDEFERIDO' if 'INDEFERID' in self.parecer_final.upper() else 'DEFERIDO'
            else:
                self.resultado_final = None
            if update_fields and 'resultado_final' not in update_fields:
                kwargs['update_fields'] = list(update_fields) + ['resultado_final']
        super().save(*args, **kwargs)

    def __str__(self):
        nome_usuario = self.user.username if self.user else "Anon"
        return f'{self.nome_processo} - {nome_usuario}'

    @cached_property
    def conteudo_final(self) -> str:
        """
        Retorna o conteúdo canônico do parecer:
        - Se o julgador editou e salvou no TinyMCE → ParecerFinal.conteudo_html (HTML)
        - Caso contrário → parecer_final gerado pela IA (markdown)

        Centraliza a regra de leitura para evitar dual-lookup nas views.
        Nota: parecer_final (markdown bruto) é sempre preservado como fonte primária da IA.
        """
        ultimo = self.pareceres_finais.order_by('-data_criacao').first()
        return ultimo.conteudo_html if ultimo else (self.parecer_final or "")

    @classmethod
    def score_stats(cls, user=None, days=90):
        """
        Retorna distribuição estatística do blindagem_score para baseline comparativo.

        Útil para contextualizar se um score individual é bom ou ruim em relação
        ao conjunto de pareceres de um julgador ou de toda a JARI no período.

        Args:
            user: filtra por User específico (None = todos os usuários)
            days: filtra pelos últimos N dias (None = sem filtro de período)

        Returns:
            dict com count, avg, min, max, p25, p50, p75
            ou None se não houver pareceres com score no período.

        Exemplo:
            stats = Parecer.score_stats(user=request.user, days=90)
            # {'count': 42, 'avg': 87.3, 'min': 50, 'max': 100, 'p25': 80, 'p50': 90, 'p75': 100}
        """
        from django.db.models import Avg, Min, Max, Count
        import datetime as _dt

        qs = cls.objects.filter(blindagem_score__isnull=False)
        if user is not None:
            qs = qs.filter(user=user)
        if days is not None:
            cutoff = _dt.datetime.now() - _dt.timedelta(days=days)
            qs = qs.filter(created_at__gte=cutoff)

        agg = qs.aggregate(
            count=Count('id'),
            avg=Avg('blindagem_score'),
            min=Min('blindagem_score'),
            max=Max('blindagem_score'),
        )
        if not agg['count']:
            return None

        scores = list(
            qs.order_by('blindagem_score').values_list('blindagem_score', flat=True)
        )
        n = len(scores)

        def _pct(p):
            return scores[max(0, min(int(n * p / 100), n - 1))]

        return {
            'count': agg['count'],
            'avg': round(agg['avg'], 1) if agg['avg'] is not None else None,
            'min': agg['min'],
            'max': agg['max'],
            'p25': _pct(25),
            'p50': _pct(50),
            'p75': _pct(75),
        }

    class Meta:
        ordering = ['-created_at']

class ConfiguracaoParecer(models.Model):
    # Cabeçalho (Imagem Única / Banner)
    cabecalho_imagem = models.ImageField(upload_to='assets/logos/', help_text="Faça o upload do banner completo em arquivo de imagem PNG ou JPG. Recomendado conter o texto e logos nas extremidades com proporção wide (painel).", null=True, blank=True)
    
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

class ChatMessage(models.Model):
    parecer = models.ForeignKey(Parecer, on_delete=models.CASCADE, related_name='chat_history')
    role = models.CharField(max_length=20, choices=[('user', 'User'), ('assistant', 'Assistant')])
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.role} - {self.created_at.strftime('%d/%m %H:%M')}"

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
        rate = (self.total_hits / self.total_requests) * 100
        return f"{rate:.2f}%"

    @property
    def total_economia(self):
        # Cada hit no cache economiza 1 request Vertex + 1 request Perplexity. Media de $0.05 por hit total.
        economia_dolar = self.total_hits * 0.05
        return f"${economia_dolar:.2f}"
        

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


class AuditEvent(models.Model):
    """Audit trail de eventos de negócio do wizard — complementa AiRequestLog (LLM/RAG)."""

    EVENTOS = [
        ('fase_concluida',        'Fase Concluída'),
        ('fase_erro',             'Erro de Fase'),
        ('parecer_finalizado',    'Parecer Finalizado'),
        ('filtro_bloqueado',      'Filtro Bloqueado (Admissibilidade)'),
        ('admissibilidade_decisao', 'Decisão de Admissibilidade'),
        ('blindagem_score',       'Score de Blindagem Registrado'),
        ('credito_consumido',     'Crédito Consumido'),
        ('upload_documentos',     'Upload de Documentos'),
    ]

    timestamp  = models.DateTimeField(auto_now_add=True, db_index=True)
    evento     = models.CharField(max_length=60, choices=EVENTOS, db_index=True)
    user       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_events')
    parecer    = models.ForeignKey('Parecer', on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_events')
    fase       = models.IntegerField(null=True, blank=True)
    dados      = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['evento', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.evento} | fase={self.fase} | {self.timestamp:%d/%m/%Y %H:%M}"


def log_audit(evento: str, parecer=None, fase: int = None, dados: dict = None):
    """Helper para registrar eventos de auditoria sem bloquear o fluxo principal."""
    try:
        AuditEvent.objects.create(
            evento=evento,
            user=parecer.user if parecer else None,
            parecer=parecer,
            fase=fase,
            dados=dados or {},
        )
    except Exception:
        pass  # Nunca deve travar o fluxo principal


class AiRequestLog(models.Model):
    parecer_referencia = models.ForeignKey(Parecer, on_delete=models.CASCADE, related_name='ai_logs', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ai_logs')
    provider = models.CharField(max_length=50) # Gemini, Perplexity, Vertex
    fase = models.CharField(max_length=50, blank=True, null=True)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    data_requisicao = models.DateTimeField(auto_now_add=True)
    query_text = models.TextField(blank=True, null=True, help_text="Termo pesquisado, caso aplicável (Ex: Vertex RAG query)")
    is_miss = models.BooleanField(default=False, help_text="Se True, significa que a IA não retornou resultados práticos (Ex: RAG vazio)")
    latency_ms = models.IntegerField(default=0, help_text="Tempo de execução da chamada em milissegundos")
    model_name = models.CharField(max_length=100, blank=True, null=True, help_text="Versão do modelo (ex: sonar-pro, gemini-2.5-flash)")
    is_pdf_defect = models.BooleanField(default=False, help_text="Se True, significa que o OCR do PDF falhou e a IA não conseguiu ler o conteúdo")

    class Meta:
        indexes = [
            models.Index(fields=['-data_requisicao']),
            models.Index(fields=['provider', '-data_requisicao']),
        ]

    def __str__(self):
        nome_usuario = self.user.username if self.user else "Anon"
        return f"{self.provider} - Fase {self.fase} - User: {nome_usuario}"

class Subscription(models.Model):
    PLANO_CHOICES = [
        ('basic', 'Básico'),
        ('pro', 'Profissional'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    plano = models.CharField(max_length=20, choices=PLANO_CHOICES)
    creditos_base = models.IntegerField()
    creditos_bonus = models.IntegerField(default=0)
    data_inicio = models.DateTimeField()
    data_expiracao = models.DateTimeField()
    stripe_session_id = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)

    @property
    def creditos_total(self):
        return self.creditos_base + self.creditos_bonus

    class Meta:
        ordering = ['-data_inicio']
        verbose_name = "Assinatura"
        verbose_name_plural = "Assinaturas"

    def __str__(self):
        return f"{self.user.username} — {self.get_plano_display()} ({self.data_inicio.strftime('%d/%m/%Y')} → {self.data_expiracao.strftime('%d/%m/%Y')})"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    is_pro = models.BooleanField(default=False)
    credits = models.IntegerField(default=5)
    subscription_status = models.CharField(max_length=50, default='inactive')
    subscription_start_at = models.DateTimeField(null=True, blank=True)
    subscription_expires_at = models.DateTimeField(null=True, blank=True)
    viu_boas_vindas = models.BooleanField(default=False)
    has_seen_tour = models.BooleanField(default=False)
    can_view_global_stats = models.BooleanField(default=False, verbose_name="Ver Painel Global")
    ultimo_acesso_forum = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Profile: {self.user.username} - PRO: {self.is_pro}"

from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


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
        admin_email = getattr(settings, 'ADMIN_EMAIL', None)
        if admin_email:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [admin_email],
                fail_silently=True,
            )
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).error("Erro ao enviar email de notificação de signup: %s", e)

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
    imagem = models.ImageField(upload_to='forum_images/', blank=True, null=True)
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

class TermoAceiteLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='termos_aceites')
    data_hora = models.DateTimeField(auto_now_add=True)
    ip_usuario = models.GenericIPAddressField(null=True, blank=True)
    versao_termo = models.CharField(max_length=50, default='1.0')

    class Meta:
        ordering = ['-data_hora']

    def __str__(self):
        return f"Aceite {self.versao_termo} - {self.user.username} em {self.data_hora.strftime('%d/%m/%Y %H:%M')}"

class SystemHealthCheck(models.Model):
    data_execucao = models.DateTimeField(auto_now_add=True)
    status_operacional = models.BooleanField(default=True)
    latencia_media_apis = models.FloatField(default=0.0)
    math_score = models.CharField(max_length=50, default="N/A")
    tempo_total_ciclo = models.FloatField(default=0.0)
    log_detalhado = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-data_execucao']

    def __str__(self):
        status = "OK" if self.status_operacional else "FALHA"
        return f"HealthCheck [{status}] - {self.data_execucao.strftime('%d/%m/%Y %H:%M')}"

class TestRun(models.Model):
    executado_em  = models.DateTimeField(auto_now_add=True)
    total         = models.IntegerField(default=0)
    passou        = models.IntegerField(default=0)
    falhou        = models.IntegerField(default=0)
    duracao_ms    = models.IntegerField(default=0)
    detalhes_json = models.JSONField(default=list)

    class Meta:
        ordering = ['-executado_em']

    def __str__(self):
        return f"TestRun {self.executado_em.strftime('%d/%m/%Y %H:%M')} — {self.passou}/{self.total}"


class PjariVersion(models.Model):
    major = models.IntegerField(default=1, verbose_name="Major (Paradigma)")
    minor = models.IntegerField(default=2, verbose_name="Minor (Raciocínio/Lógica)")
    patch = models.IntegerField(default=0, verbose_name="Patch/Versão Vertex (Base de Leis)")
    logica_hash = models.CharField(max_length=64, blank=True, null=True, verbose_name="Hash do logica_jari.md")
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Controle de Versão (JARI)"
        verbose_name_plural = "Controle de Versão (JARI)"

    def __str__(self):
        return f"v{self.major}.{self.minor}.{self.patch}"

    def save(self, *args, **kwargs):
        # Garante que seja um Singleton (apenas um registro na tabela)
        if not self.pk and PjariVersion.objects.exists():
            raise ValueError("PjariVersion é um singleton — já existe um registro. Use PjariVersion.objects.first() para atualizar.")
        super().save(*args, **kwargs)
