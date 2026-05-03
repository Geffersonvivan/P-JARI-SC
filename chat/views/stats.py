import json
import calendar
from datetime import date
from django.shortcuts import render
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db.models import Count, Q, Avg, F, ExpressionWrapper, Sum, Case, When, Value, BooleanField, DurationField
from django.db.models.functions import TruncDate
from django.utils import timezone
from django_ratelimit.decorators import ratelimit
from ..models import Parecer, BancoTese, ParecerFinal


@ratelimit(key='user', rate='30/h', method='GET', block=True)
@login_required
def estatisticas_view(request):

    # Pegar mês e ano da requisição ou usar o atual
    hoje = timezone.localtime(timezone.now()).date()
    try:
        mes = int(request.GET.get('mes', hoje.month))
        ano = int(request.GET.get('ano', hoje.year))
    except (ValueError, TypeError):
        mes = hoje.month
        ano = hoje.year

    _, ultimo_dia_mes = calendar.monthrange(ano, mes)

    # 1. Total Julgado (is_saved=True)
    total_julgados = Parecer.objects.filter(
        user=request.user,
        is_saved=True,
        created_at__year=ano,
        created_at__month=mes
    ).count()

    # 2. Tempo Poupado (cada processo julgado poupa ~40 mins)
    tempo_poupado_minutos = total_julgados * 40
    tempo_poupado_horas = tempo_poupado_minutos // 60

    # NOVAS MÉTRICAS DE TEMPO DE JULGAMENTO (USUÁRIO)
    tempo_julgamento_stats = Parecer.objects.filter(
        user=request.user,
        is_saved=True,
        created_at__year=ano,
        created_at__month=mes,
        tempo_julgamento_segundos__isnull=False
    ).aggregate(
        total_segundos=Sum('tempo_julgamento_segundos'),
        media_segundos=Avg('tempo_julgamento_segundos')
    )

    total_segundos = int(tempo_julgamento_stats['total_segundos'] or 0)
    media_segundos = int(tempo_julgamento_stats['media_segundos'] or 0)

    tt_horas = total_segundos // 3600
    tt_minutos = (total_segundos % 3600) // 60
    if tt_horas > 0:
        tempo_total_julgamento = f"{tt_horas}H {tt_minutos}m"
    else:
        tt_segundos_resto = total_segundos % 60
        tempo_total_julgamento = f"{tt_minutos}m {tt_segundos_resto}s"

    m_minutos = int(media_segundos) // 60
    m_segundos = int(media_segundos) % 60
    media_tempo_julgamento = f"{m_minutos}m {m_segundos}s"

    # 3. Taxa de Deferimento e Indeferimento
    pareceres_base = Parecer.objects.filter(
        user=request.user,
        is_saved=True,
        created_at__year=ano,
        created_at__month=mes
    ).exclude(parecer_final__isnull=True).exclude(parecer_final__exact='')

    # Usa coluna denormalizada resultado_final (índice) em vez de icontains em TextField
    all_pareceres_info = list(pareceres_base.values_list('id', 'resultado_final'))

    total_finais = len(all_pareceres_info)
    ids_indeferidos_base = {pid for pid, res in all_pareceres_info if res == 'INDEFERIDO'}
    ids_base = [pid for pid, _ in all_pareceres_info]

    overrides_info = ParecerFinal.objects.filter(
        parecer_referencia__in=ids_base
    ).annotate(
        is_indef=Case(
            When(conteudo_html__icontains='INDEFERID', then=Value(True)),
            default=Value(False),
            output_field=BooleanField()
        )
    ).order_by('data_criacao').values_list('parecer_referencia_id', 'is_indef')

    final_overrides = {}
    for pid, is_indef in overrides_info:
        final_overrides[pid] = is_indef

    indeferidos = 0
    for pid in ids_base:
        if pid in final_overrides:
            if final_overrides[pid]:
                indeferidos += 1
        elif pid in ids_indeferidos_base:
            indeferidos += 1

    deferidos = total_finais - indeferidos

    # Adicionando contagem limpa pro grafico Donut
    donut_series = [deferidos, indeferidos]

    if total_finais > 0:
        taxa_deferimento = round((deferidos / total_finais) * 100)
        taxa_indeferimento = round((indeferidos / total_finais) * 100)
    else:
        taxa_deferimento = 0
        taxa_indeferimento = 0

    # 4. Gráfico Temporal (Dias do mês selecionado)
    pareceres_por_dia = (
        Parecer.objects.filter(
            user=request.user,
            is_saved=True,
            created_at__year=ano,
            created_at__month=mes
        )
        .annotate(data=TruncDate('created_at'))
        .values('data')
        .annotate(total=Count('id'))
        .order_by('data')
    )

    datas = []
    totais_por_dia = []

    dados_dict = {item['data']: item['total'] for item in pareceres_por_dia}

    for dia in range(1, ultimo_dia_mes + 1):
        data_atual = date(ano, mes, dia)
        datas.append(data_atual.strftime('%d/%m'))
        totais_por_dia.append(dados_dict.get(data_atual, 0))

    # 5. Radar de Infrações (Extraindo da Origem Certa do Consolidado)
    pareceres_radar = Parecer.objects.filter(
        user=request.user,
        is_saved=True,
        created_at__year=ano,
        created_at__month=mes,
        infracao_documento__isnull=False
    ).exclude(infracao_documento__exact='').values('infracao_documento').annotate(
        total=Count('id')
    ).order_by('-total')[:5]

    radar_infracoes = []

    if pareceres_radar:
        max_oco = pareceres_radar[0]['total']
        for item in pareceres_radar:
            nome_bruto = str(item['infracao_documento']).strip().upper()

            base_legal = ""
            nome_limpo = nome_bruto
            if "|||" in nome_bruto:
                partes = nome_bruto.split("|||", 1)
                base_legal = partes[0].strip()
                nome_limpo = partes[1].strip()

            if len(nome_limpo) > 45:
                nome_limpo = nome_limpo[:42] + "..."

            pct = int((item['total'] / max_oco) * 100) if max_oco > 0 else 0
            radar_infracoes.append({
                'base_legal': base_legal,
                'nome': nome_limpo,
                'total': item['total'],
                'pct': pct
            })

    # --- Créditos Variáveis ---
    total_usos_global = Parecer.objects.filter(user=request.user, is_saved=True).count()
    try:
        creditos_usuario = request.user.profile.credits
        is_pro = request.user.profile.is_pro
    except Exception:
        creditos_usuario = 0
        is_pro = False

    context = {
        'total_julgados': total_julgados,
        'tempo_poupado_horas': tempo_poupado_horas,
        'tempo_total_julgamento': tempo_total_julgamento,
        'media_tempo_julgamento': media_tempo_julgamento,
        'taxa_deferimento': taxa_deferimento,
        'taxa_indeferimento': taxa_indeferimento,
        'deferidos_count': deferidos,
        'indeferidos_count': indeferidos,
        'donut_series': json.dumps(donut_series),
        'radar_infracoes': radar_infracoes,
        'grafico_datas': json.dumps(datas),
        'grafico_totais': json.dumps(totais_por_dia),
        'ano_selecionado': ano,
        'mes_selecionado': mes,
        'mes_ano_input': f"{ano}-{mes:02d}",
        'total_usos_global': total_usos_global,
        'creditos_usuario': creditos_usuario,
        'is_pro': is_pro,
        'banco_teses': BancoTese.objects.filter(user=request.user).defer('conteudo').order_by('-created_at'),
    }

    try:
        from allauth.socialaccount.models import SocialAccount
        social = SocialAccount.objects.filter(user=request.user, provider='google').first()
        context['user_avatar_url'] = social.extra_data.get('picture', '') if social else ''
    except Exception:
        context['user_avatar_url'] = ''

    from django.conf import settings as _s
    context['CLERK_PUBLISHABLE_KEY'] = getattr(_s, 'CLERK_PUBLISHABLE_KEY', '')

    return render(request, 'dashboard.html', context)


@ratelimit(key='user', rate='30/h', method='GET', block=True)
@login_required
def estatisticas_gerais_view(request):
    if not getattr(request.user.profile, 'can_view_global_stats', False) and not request.user.is_superuser:
        return HttpResponseForbidden("Acesso Negado. Você não tem permissão para visualizar estatísticas globais.")

    from ..models import AiRequestLog, AuditEvent, UserProfile, PjariCacheConfig, SystemHealthCheck, TestRun

    hoje = timezone.localtime(timezone.now()).date()
    try:
        mes = int(request.GET.get('mes', hoje.month))
        ano = int(request.GET.get('ano', hoje.year))
    except (ValueError, TypeError):
        mes = hoje.month
        ano = hoje.year

    _, ultimo_dia_mes = calendar.monthrange(ano, mes)

    # 1. Total Julgado Global
    total_julgados_global = Parecer.objects.filter(
        is_saved=True,
        created_at__year=ano,
        created_at__month=mes
    ).count()

    tempo_poupado_horas = (total_julgados_global * 40) // 60

    # NOVAS MÉTRICAS DE TEMPO DE JULGAMENTO
    tempo_julgamento_stats = Parecer.objects.filter(
        is_saved=True,
        created_at__year=ano,
        created_at__month=mes,
        tempo_julgamento_segundos__isnull=False
    ).aggregate(
        total_segundos=Sum('tempo_julgamento_segundos'),
        media_segundos=Avg('tempo_julgamento_segundos')
    )

    total_segundos = int(tempo_julgamento_stats['total_segundos'] or 0)
    media_segundos = int(tempo_julgamento_stats['media_segundos'] or 0)

    tt_horas = total_segundos // 3600
    tt_minutos = (total_segundos % 3600) // 60
    if tt_horas > 0:
        tempo_total_julgamento = f"{tt_horas}H {tt_minutos}m"
    else:
        tt_segundos_resto = total_segundos % 60
        tempo_total_julgamento = f"{tt_minutos}m {tt_segundos_resto}s"

    m_minutos = int(media_segundos) // 60
    m_segundos = int(media_segundos) % 60
    media_tempo_julgamento = f"{m_minutos}m {m_segundos}s"

    User = get_user_model()
    total_usuarios_ativos = User.objects.filter(is_superuser=False).count()

    # 2. Taxa Deferimento Global
    pareceres_base = Parecer.objects.filter(
        is_saved=True,
        created_at__year=ano,
        created_at__month=mes
    ).exclude(parecer_final__isnull=True).exclude(parecer_final__exact='')

    # Usa coluna denormalizada resultado_final (índice) em vez de icontains em TextField
    all_pareceres_info = list(pareceres_base.values_list('id', 'resultado_final'))

    total_finais = len(all_pareceres_info)
    ids_indeferidos_base = {pid for pid, res in all_pareceres_info if res == 'INDEFERIDO'}
    ids_base = [pid for pid, _ in all_pareceres_info]

    overrides_info = ParecerFinal.objects.filter(
        parecer_referencia__in=ids_base
    ).annotate(
        is_indef=Case(
            When(conteudo_html__icontains='INDEFERID', then=Value(True)),
            default=Value(False),
            output_field=BooleanField()
        )
    ).order_by('data_criacao').values_list('parecer_referencia_id', 'is_indef')

    final_overrides = {}
    for pid, is_indef in overrides_info:
        final_overrides[pid] = is_indef

    indeferidos = 0
    for pid in ids_base:
        if pid in final_overrides:
            if final_overrides[pid]:
                indeferidos += 1
        elif pid in ids_indeferidos_base:
            indeferidos += 1

    deferidos = total_finais - indeferidos

    donut_series = [deferidos, indeferidos]
    taxa_deferimento = round((deferidos / total_finais) * 100) if total_finais > 0 else 0
    taxa_indeferimento = round((indeferidos / total_finais) * 100) if total_finais > 0 else 0

    # 3. Gráfico Temporal (Linha)
    pareceres_por_dia = (
        Parecer.objects.filter(
            is_saved=True,
            created_at__year=ano,
            created_at__month=mes
        )
        .annotate(data=TruncDate('created_at'))
        .values('data')
        .annotate(total=Count('id'))
        .order_by('data')
    )

    datas = []
    totais_por_dia = []
    dados_dict = {item['data']: item['total'] for item in pareceres_por_dia}
    for dia in range(1, ultimo_dia_mes + 1):
        data_atual = date(ano, mes, dia)
        datas.append(data_atual.strftime('%d/%m'))
        totais_por_dia.append(dados_dict.get(data_atual, 0))

    # 4. Uso de API (Custos e Tokens)
    # Usa range de datas em vez de EXTRACT(year/month) para aproveitar índice B-tree
    from datetime import datetime
    _inicio_mes = datetime(ano, mes, 1)
    _fim_mes = datetime(ano, mes + 1, 1) if mes < 12 else datetime(ano + 1, 1, 1)
    logs = AiRequestLog.objects.filter(data_requisicao__gte=_inicio_mes, data_requisicao__lt=_fim_mes)

    tokens_gemini = logs.filter(provider__icontains='Gemini').aggregate(
        in_t=Sum('input_tokens'), out_t=Sum('output_tokens')
    )
    tokens_perplexity = logs.filter(provider__icontains='Perplexity').aggregate(
        in_t=Sum('input_tokens'), out_t=Sum('output_tokens')
    )
    consultas_vertex = logs.filter(provider__icontains='Vertex').count()

    vertex_misses = list(logs.filter(provider__icontains='Vertex', is_miss=True).select_related('parecer_referencia').order_by('-data_requisicao'))
    taxa_uso_vertex = f"{int((consultas_vertex / total_julgados_global) * 100)}%" if total_julgados_global > 0 else "0%"

    custo_gemini = (tokens_gemini['in_t'] or 0) * (0.075 / 1000000) + (tokens_gemini['out_t'] or 0) * (0.30 / 1000000)
    custo_perplexity = ((tokens_perplexity['in_t'] or 0) + (tokens_perplexity['out_t'] or 0)) * (1.00 / 1000000)
    custo_vertex = consultas_vertex * 0.005

    # NOVAS MÉTRICAS IA (Latência, Dispersão, Fadiga e Defeito)
    perplexity_logs_qs = logs.filter(provider__icontains='Perplexity')
    avg_latency_perplexity_ms = perplexity_logs_qs.aggregate(avg_lat=Avg('latency_ms'))['avg_lat'] or 0
    avg_latency_perplexity_sec = round(avg_latency_perplexity_ms / 1000, 2)

    gemini_logs_qs = logs.filter(provider__icontains='Gemini', model_name__isnull=False).exclude(model_name='')
    gemini_total_requests = gemini_logs_qs.count()
    gemini_pro_count = gemini_logs_qs.filter(model_name__icontains='pro').count()
    gemini_flash_count = gemini_logs_qs.filter(model_name__icontains='flash').count()
    pct_gemini_pro = int((gemini_pro_count / gemini_total_requests) * 100) if gemini_total_requests > 0 else 0
    pct_gemini_flash = int((gemini_flash_count / gemini_total_requests) * 100) if gemini_total_requests > 0 else 0

    top_fatigue_logs = list(logs.filter(provider__icontains='Gemini', input_tokens__gt=0).select_related('parecer_referencia').order_by('-input_tokens')[:5])
    pdf_defects_logs = list(logs.filter(provider__icontains='Gemini', is_pdf_defect=True).select_related('parecer_referencia').order_by('-data_requisicao'))
    pdf_defects_count = len(pdf_defects_logs)

    # --- NOVAS MÉTRICAS ESTRATÉGIAS ---

    # 5. Eficiência do P-JARI Cache (Hit Rate Global)
    cache_config = PjariCacheConfig.objects.first()
    hit_rate = cache_config.hit_rate if cache_config else "0.00%"
    total_economia = cache_config.total_economia if cache_config else "$0.00"

    # 6. Taxa de Interceptação da Auditoria (JariMath vs Humano / 0-99 Score)
    auditorias_com_inconsistencia = Parecer.objects.filter(
        is_saved=True, created_at__year=ano, created_at__month=mes, blindagem_score__lt=100
    )
    total_inconsistencias = auditorias_com_inconsistencia.count()
    taxa_interceptacao = int((total_inconsistencias / total_julgados_global) * 100) if total_julgados_global > 0 else 0

    # 6.1 Log Detalhado de Inconsistências (Painel de Alucinações da IA)
    ultimas_inconsistencias = auditorias_com_inconsistencia.order_by('-created_at')[:15]

    # 7. Conversão de Trial para PRO
    total_users = UserProfile.objects.count()
    pro_users = UserProfile.objects.filter(is_pro=True).count()
    taxa_conversao = int((pro_users / total_users) * 100) if total_users > 0 else 0

    # A nuvem antiga que carregava os textos pro regex foi suprimida.

    # 8. Extrai top 5 Infrações com base na coluna nativa
    pareceres_radar_global = Parecer.objects.filter(
        is_saved=True,
        created_at__year=ano,
        created_at__month=mes,
        infracao_documento__isnull=False
    ).exclude(infracao_documento__exact='').values('infracao_documento').annotate(
        total=Count('id')
    ).order_by('-total')[:5]

    radar_infracoes_global = []

    if pareceres_radar_global:
        max_oco_global = pareceres_radar_global[0]['total']
        for item in pareceres_radar_global:
            nome_bruto_global = str(item['infracao_documento']).strip().upper()

            base_legal_global = ""
            nome_limpo_global = nome_bruto_global
            if "|||" in nome_bruto_global:
                partes = nome_bruto_global.split("|||", 1)
                base_legal_global = partes[0].strip()
                nome_limpo_global = partes[1].strip()

            if len(nome_limpo_global) > 45:
                nome_limpo_global = nome_limpo_global[:42] + "..."

            pct_global = int((item['total'] / max_oco_global) * 100) if max_oco_global > 0 else 0
            radar_infracoes_global.append({
                'base_legal': base_legal_global,
                'nome': nome_limpo_global,
                'total': item['total'],
                'pct': pct_global
            })

    # 9. Funil Temporal (Gargalos de Prescrição - Média de dias Protocolo -> Julgamento)
    processos_com_datas = Parecer.objects.filter(
        is_saved=True, created_at__year=ano, created_at__month=mes,
        data_protocolo__isnull=False, data_sessao__isnull=False
    ).annotate(
        diff_dias=ExpressionWrapper(F('data_sessao') - F('data_protocolo'), output_field=DurationField())
    ).aggregate(avg_diff=Avg('diff_dias'))

    avg_dias_funil = 0
    if processos_com_datas['avg_diff']:
        avg_dias_funil = processos_com_datas['avg_diff'].days

    # 10. Feedback Contínuo da IA (NPS e Tags)
    feedbacks_qs = Parecer.objects.filter(
        is_saved=True, created_at__year=ano, created_at__month=mes, feedback_score__isnull=False
    )

    media_nps_ia = feedbacks_qs.aggregate(avg_score=Avg('feedback_score'))['avg_score']
    nps_ia_fmt = f"{int(media_nps_ia)}%" if media_nps_ia is not None else "N/A"

    # Carrega apenas os campos necessários para evitar textos longos na RAM
    feedbacks_data = list(feedbacks_qs.filter(
        Q(feedback_tags__isnull=False) | Q(feedback_notes__isnull=False)
    ).exclude(feedback_tags='').values('id', 'nome_processo', 'feedback_score', 'feedback_tags', 'feedback_notes', 'created_at'))

    tags_contagem = {}
    feedbacks_com_texto = []

    for fb in feedbacks_data:
        if fb['feedback_tags']:
            # M10 FIX: aceita JSON array (novo formato) e CSV legado
            import json as _json
            _raw_tags = fb['feedback_tags']
            try:
                _tag_list = _json.loads(_raw_tags)
                if not isinstance(_tag_list, list):
                    _tag_list = [str(_tag_list)]
            except (ValueError, TypeError):
                _tag_list = [t.strip() for t in _raw_tags.split(',') if t.strip()]
            for tag in _tag_list:
                tags_contagem[tag] = tags_contagem.get(tag, 0) + 1
        if fb['feedback_notes']:
            feedbacks_com_texto.append({
                'id': fb['id'],
                'processo': fb['nome_processo'],
                'nota': fb['feedback_score'],
                'tags': fb['feedback_tags'],
                'texto': fb['feedback_notes'],
                'data': fb['created_at'].strftime('%d/%m/%Y')
            })

    tags_ranking = sorted(tags_contagem.items(), key=lambda x: x[1], reverse=True)

    # ── Auditoria de Uso ────────────────────────────────────────────────────────
    funil_data = []
    filtros_bloqueados = 0
    erros_fase = 0
    pareceres_finalizados_audit = 0
    creditos_consumidos = 0
    score_medio_blindagem = 0
    adm_counts = {'punitiva': 0, 'intercorrente': 0, 'decadencia': 0, 'intempestivo': 0, 'merito': 0}
    ultimos_erros_fase = []

    try:
        audit_qs = AuditEvent.objects.filter(timestamp__year=ano, timestamp__month=mes)

        # Funil: pareceres por status_fase (snapshot atual — independe do mês)
        # Uma única query agregada em vez de 6 COUNTs separados
        funil_fases = [
            ('Coleta Docs',    [1, 10]),
            ('DIR/Tabela',     [2, 3]),
            ('Admissibilidade',[31]),
            ('Tese',           [4, 41]),
            ('Parecer',        [5, 6]),
            ('Finalizado',     [8]),
        ]
        _all_fases = [f for _, fases in funil_fases for f in fases]
        _fase_counts = {
            row['status_fase']: row['n']
            for row in Parecer.objects.filter(status_fase__in=_all_fases).values('status_fase').annotate(n=Count('id'))
        }
        for label, fases in funil_fases:
            funil_data.append({'label': label, 'count': sum(_fase_counts.get(f, 0) for f in fases)})

        # Eventos de auditoria por tipo
        filtros_bloqueados = audit_qs.filter(evento='filtro_bloqueado').count()
        erros_fase = audit_qs.filter(evento='fase_erro').count()
        pareceres_finalizados_audit = audit_qs.filter(evento='parecer_finalizado').count()
        creditos_consumidos = audit_qs.filter(evento='credito_consumido').count()

        # Score médio de blindagem (do mês)
        score_medio_blindagem = Parecer.objects.filter(
            is_saved=True, created_at__year=ano, created_at__month=mes,
            blindagem_score__isnull=False
        ).aggregate(avg=Avg('blindagem_score'))['avg']
        score_medio_blindagem = round(score_medio_blindagem or 0, 1)

        # Decisões de admissibilidade
        adm_eventos = list(audit_qs.filter(evento='admissibilidade_decisao').values('dados'))
        for ev in adm_eventos:
            d = ev.get('dados') or {}
            if d.get('punitiva'):             adm_counts['punitiva'] += 1
            elif d.get('intercorrente'):      adm_counts['intercorrente'] += 1
            elif d.get('decadencia'):         adm_counts['decadencia'] += 1
            elif d.get('tempestivo') is False: adm_counts['intempestivo'] += 1
            else:                             adm_counts['merito'] += 1

        # Erros por fase (últimos 20)
        ultimos_erros_fase = list(
            audit_qs.filter(evento='fase_erro').order_by('-timestamp').values('timestamp', 'fase', 'dados')[:20]
        )
    except Exception:
        import logging as _log
        _log.getLogger(__name__).exception('[stats] AuditEvent query falhou — migration pendente?')

    context = {
        'total_julgados': total_julgados_global,
        'tempo_poupado_horas': tempo_poupado_horas,
        'tempo_total_julgamento': tempo_total_julgamento,
        'media_tempo_julgamento': media_tempo_julgamento,
        'taxa_deferimento': taxa_deferimento,
        'nps_ia_fmt': nps_ia_fmt,
        'tags_ranking': tags_ranking,
        'feedbacks_com_texto': feedbacks_com_texto,
        'taxa_indeferimento': taxa_indeferimento,
        'deferidos_count': deferidos,
        'indeferidos_count': indeferidos,
        'total_usuarios_ativos': total_usuarios_ativos,
        'donut_series': json.dumps(donut_series),
        'grafico_datas': json.dumps(datas),
        'grafico_totais': json.dumps(totais_por_dia),
        'ano_selecionado': ano,
        'mes_selecionado': mes,
        'mes_ano_input': f"{ano}-{mes:02d}",
        'tokens_gemini_in': f"{(tokens_gemini['in_t'] or 0):,}".replace(',','.'),
        'tokens_gemini_out': f"{(tokens_gemini['out_t'] or 0):,}".replace(',','.'),
        'tokens_perplexity_in': f"{(tokens_perplexity['in_t'] or 0):,}".replace(',','.'),
        'tokens_perplexity_out': f"{(tokens_perplexity['out_t'] or 0):,}".replace(',','.'),
        'consultas_vertex': consultas_vertex,
        'custo_gemini': f"US$ {custo_gemini:.4f}",
        'custo_perplexity': f"US$ {custo_perplexity:.4f}",
        'custo_vertex': f"US$ {custo_vertex:.4f}",
        'vertex_misses': vertex_misses,
        'taxa_uso_vertex': taxa_uso_vertex,
        'avg_latency_perplexity_sec': avg_latency_perplexity_sec,
        'pct_gemini_pro': pct_gemini_pro,
        'pct_gemini_flash': pct_gemini_flash,
        'top_fatigue_logs': top_fatigue_logs,
        'pdf_defects_logs': pdf_defects_logs,
        'pdf_defects_count': pdf_defects_count,

        # Novas métricas context
        'health_check': SystemHealthCheck.objects.first(),
        'ultimo_test_run': TestRun.objects.first(),
        'historico_test_runs': list(
            TestRun.objects.values('executado_em', 'passou', 'falhou', 'total', 'duracao_ms')[:10]
        ),
        'hit_rate': hit_rate,
        'total_economia': total_economia,
        'taxa_interceptacao': taxa_interceptacao,
        'ultimas_inconsistencias': ultimas_inconsistencias,
        'taxa_conversao': taxa_conversao,
        'radar_infracoes': radar_infracoes_global,
        'avg_dias_funil': avg_dias_funil,
        'banco_teses': BancoTese.objects.filter(user=request.user).defer('conteudo').order_by('-created_at'),
        # Auditoria de Uso
        'funil_data': funil_data,
        'filtros_bloqueados': filtros_bloqueados,
        'erros_fase': erros_fase,
        'pareceres_finalizados_audit': pareceres_finalizados_audit,
        'creditos_consumidos': creditos_consumidos,
        'score_medio_blindagem': score_medio_blindagem,
        'adm_counts': adm_counts,
        'ultimos_erros_fase': ultimos_erros_fase,
    }

    try:
        from allauth.socialaccount.models import SocialAccount
        social = SocialAccount.objects.filter(user=request.user, provider='google').first()
        context['user_avatar_url'] = social.extra_data.get('picture', '') if social else ''
    except Exception:
        context['user_avatar_url'] = ''

    from django.conf import settings as _s
    context['CLERK_PUBLISHABLE_KEY'] = getattr(_s, 'CLERK_PUBLISHABLE_KEY', '')

    return render(request, 'dashboard_global.html', context)


@login_required
@require_POST
def resetar_auditoria_view(request):
    """Zera AuditEvent e AiRequestLog. Apenas superuser."""
    if not request.user.is_superuser:
        return JsonResponse({'ok': False, 'erro': 'Acesso negado.'}, status=403)

    from ..models import AuditEvent, AiRequestLog
    import logging
    logger = logging.getLogger(__name__)

    audit_count = AuditEvent.objects.count()
    log_count = AiRequestLog.objects.count()

    AuditEvent.objects.all().delete()
    AiRequestLog.objects.all().delete()

    logger.warning(
        '[RESET] Monitoramento zerado por %s — %d AuditEvents e %d AiRequestLogs removidos.',
        request.user.username, audit_count, log_count,
    )

    return JsonResponse({
        'ok': True,
        'removidos': {'audit_events': audit_count, 'ai_request_logs': log_count},
    })
