from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
import json
from django.db.models import Prefetch, Count, Q
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import mercadopago
from .models import Parecer, Pasta, ConfiguracaoParecer, ParecerFinal

def home_view(request):
    if not request.session.session_key:
        request.session.create()
        
    if request.user.is_authenticated:
        filter_kwargs = {'user': request.user}
    else:
        filter_kwargs = {'user__isnull': True, 'session_key': request.session.session_key}

    # Garante que a pasta fixa 'Outros' exista, e pré-carrega seus projetos
    projetos_salvos = Prefetch('projetos', queryset=Parecer.objects.filter(is_saved=True).only('id', 'pasta_id', 'nome_processo', 'created_at', 'is_saved').order_by('-created_at'))
    
    pasta_outros, _ = Pasta.objects.get_or_create(nome_pasta="Outros", **filter_kwargs)
    # Busca a pasta 'Outros' novamente para aplicar o prefetch e contabilizar os salvamentos
    pasta_outros = Pasta.objects.filter(id=pasta_outros.id).prefetch_related(projetos_salvos).annotate(
        num_projetos=Count('projetos', filter=Q(projetos__is_saved=True))
    ).first()
    
    pastas = Pasta.objects.filter(**filter_kwargs).exclude(id=pasta_outros.id).prefetch_related(projetos_salvos).annotate(
        num_projetos=Count('projetos', filter=Q(projetos__is_saved=True))
    ).order_by('posicao', '-created_at')
    
    # Calcula o total de pareceres finalizados pelo usuário logado
    total_julgados = Parecer.objects.filter(**filter_kwargs, is_saved=True).count()
    
    return render(request, 'home.html', {
        'pasta_outros': pasta_outros,
        'pastas': pastas,
        'total_julgados': total_julgados
    })

def editar_parecer_view(request, id):
    parecer = get_object_or_404(Parecer, id=id)
    config = ConfiguracaoParecer.objects.first()
    
    parecer_final_db = parecer.pareceres_finais.last()
    
    if parecer_final_db:
        parecer_gerado = parecer_final_db.conteudo_html
    else:
        texto_gerado_pela_ia = parecer.parecer_final or ""
        
        if config:
            from django.template import Template, Context
            is_indeferido = "INDEFERID" in texto_gerado_pela_ia.upper()
            _rodape_indef = getattr(config, 'rodape_indeferido', '') or ""
            _rodape_def = getattr(config, 'rodape_deferido', '') or ""
            rodape_texto = _rodape_indef if is_indeferido else _rodape_def
            
            # Limpa Nonetypes e Nulls antes das manipulações massivas
            if not isinstance(rodape_texto, str): rodape_texto = ""
            
            # Auto-corrigir tags mal formadas deixadas pelo usuário como {{. }} ou vazias
            palavra_resultado = "INDEFERIDO" if is_indeferido else "DEFERIDO"
            rodape_texto = rodape_texto.replace('{{. }}', palavra_resultado).replace('{{.}}', palavra_resultado)
            rodape_texto = rodape_texto.replace('{{ }}', palavra_resultado).replace('{{}}', palavra_resultado)
            
            nome_usuario = request.user.get_full_name() or request.user.username if request.user.is_authenticated else "Visitante"
            rodape_template = Template(rodape_texto)
            rodape_escolhido = rodape_template.render(Context({
                'nome_membro': nome_usuario,
                'deferido': palavra_resultado,
                'indeferido': palavra_resultado,
                'DEFERIDO': palavra_resultado,
                'INDEFERIDO': palavra_resultado,
                'resultado': palavra_resultado
            }))
            
            import re
            
            # Use explicit image attributes and wrap it
            from django.core.files.storage import default_storage
            from django.contrib.staticfiles.storage import staticfiles_storage
            
            if config.logo and default_storage.exists(config.logo.name):
                logo_absolute_url = request.build_absolute_uri(config.logo.url)
                logo_html = f"<img src='{logo_absolute_url}' width='110' style='width: 110px; max-width: 110px; height: auto;'>"
            else:
                static_url = staticfiles_storage.url('img/DETRAN.png')
                logo_absolute_url = request.build_absolute_uri(static_url)
                logo_html = f"<img src='{logo_absolute_url}' width='110' style='width: 110px; max-width: 110px; height: auto;'>"
            
            tit_raw = getattr(config, 'titulo_cabecalho', '') or ""
            sub_raw = getattr(config, 'subtitulo_cabecalho', '') or ""
            tit = tit_raw.replace('\n', '<br>') if tit_raw else ""
            sub = sub_raw.replace('\n', '<br>') if sub_raw else ""
            
            cabecalho_html = f"""
                <div style="text-align: center; width: 100%; margin-bottom: 50px;">
                    <table style="border: none; border-collapse: collapse; margin: 0 auto; width: auto;">
                        <tbody>
                            <tr>
                                <td style="border: none; padding: 0 20px 0 0; vertical-align: middle; text-align: right;">
                                    <div style="width: 110px; overflow: hidden; display: inline-block;">
                                        {logo_html}
                                    </div>
                                </td>
                                <td style="border: none; padding: 0; vertical-align: middle; text-align: left; font-family: Arial, sans-serif; font-size: 13px; font-weight: bold; line-height: 1.3;">
                                    {tit}<br>
                                    {sub}
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            """
            
            # Converter markdown para HTML
            import markdown
            texto_html = markdown.markdown(texto_gerado_pela_ia, extensions=['nl2br', 'sane_lists', 'tables'])
            
            # Converter links no texto do parecer
            texto_html = re.sub(r'<a ', r'<a target="_blank" class="text-blue-600 hover:text-blue-800 underline break-words font-semibold" rel="noopener noreferrer" ', texto_html)
            
            # Formatar dossiê se existir na View do Editor para passar pro PDF
            dossie_html = parecer.dossie_fontes or ""
            if dossie_html:
                dossie_html = markdown.markdown(dossie_html, extensions=['nl2br', 'sane_lists', 'tables'])
                dossie_html = re.sub(r'<a ', r'<a target="_blank" class="text-blue-600 hover:text-blue-800 underline break-words font-semibold" rel="noopener noreferrer" ', dossie_html)
                parecer.dossie_fontes_html = dossie_html
            
            # Para o TinyMCE, um bloco flex ou div simples com text-align center é totalmente respeitado nativamente
            rodape_centralizado = f"""
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; margin-top: 50px; width: 100%;">
                <div style="text-align: center; width: auto; display: inline-block;">
                    {rodape_escolhido.replace('<p>', '<p style="text-align: center; margin: 0; padding: 0;">').replace('text-align: left;', 'text-align: center;')}
                </div>
            </div>
            """
            
            parecer_gerado = f"{cabecalho_html}<div class='corpo'>{texto_html}</div>{rodape_centralizado}"
        else:
            import markdown
            parecer_gerado = markdown.markdown(texto_gerado_pela_ia, extensions=['nl2br', 'sane_lists', 'tables'])

    return render(request, 'editor_parecer.html', {
        'parecer': parecer,
        'parecer_gerado': parecer_gerado,
        'config': config
    })

@require_POST
def salvar_parecer_view(request, id):
    parecer = get_object_or_404(Parecer, id=id)
    conteudo_final = request.POST.get('conteudo_final')
    
    if conteudo_final:
        status_result = "INDEFERIDO" if "INDEFERID" in conteudo_final.upper() else "DEFERIDO"
        
        ParecerFinal.objects.create(
            parecer_referencia=parecer,
            conteudo_html=conteudo_final,
            status_resultado=status_result
        )
        
    return redirect('home')

@require_POST
def create_parecer_view(request):
    if not request.session.session_key:
        request.session.create()
        
    if not request.user.is_authenticated:
        count = Parecer.objects.filter(user__isnull=True, session_key=request.session.session_key).count()
        if count >= 2:
            return JsonResponse({'requires_login': True})
    else:
        # Usuário autenticado: Verifica limite de créditos (Ignora se for Vitalício Is Pro)
        total_usos = Parecer.objects.filter(user=request.user, is_saved=True).count()
        if total_usos >= request.user.profile.credits and not request.user.profile.is_pro:
            return JsonResponse({'requires_plan': True})

    try:
        data = json.loads(request.body)
        nome_processo = data.get('nome_processo')
        if nome_processo:
            if request.user.is_authenticated:
                pasta = Pasta.objects.create(user=request.user, nome_pasta=nome_processo)
            else:
                pasta = Pasta.objects.create(session_key=request.session.session_key, nome_pasta=nome_processo)
            return JsonResponse({'id': pasta.id, 'nome_processo': pasta.nome_pasta})
        return JsonResponse({'error': 'Nome do processo inválido'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_POST
def delete_parecer_view(request, id):
    if not request.session.session_key:
        request.session.create()
    filter_kwargs = {'user': request.user} if request.user.is_authenticated else {'user__isnull': True, 'session_key': request.session.session_key}

    pasta = get_object_or_404(Pasta, id=id, **filter_kwargs)
    if pasta.nome_pasta == "Outros":
        return JsonResponse({'error': 'A pasta Outros não pode ser deletada.'}, status=403)
    pasta.delete()
    return JsonResponse({'success': True})

@require_POST
def delete_projeto_view(request, id):
    if not request.session.session_key:
        request.session.create()
    filter_kwargs = {'user': request.user} if request.user.is_authenticated else {'user__isnull': True, 'session_key': request.session.session_key}

    projeto = get_object_or_404(Parecer, id=id, **filter_kwargs)
    projeto.delete()
    return JsonResponse({'success': True})

@require_POST
def mover_parecer_view(request, id):
    if not request.session.session_key:
        request.session.create()
    filter_kwargs = {'user': request.user} if request.user.is_authenticated else {'user__isnull': True, 'session_key': request.session.session_key}

    projeto = get_object_or_404(Parecer, id=id, **filter_kwargs)
    
    try:
        data = json.loads(request.body)
        nova_pasta_id = data.get('nova_pasta_id')
        
        if not nova_pasta_id:
            return JsonResponse({'error': 'Nova pasta não especificada.'}, status=400)
            
        nova_pasta = get_object_or_404(Pasta, id=nova_pasta_id, **filter_kwargs)
        projeto.pasta = nova_pasta
        projeto.save()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_POST
def chat_message_view(request):
    if not request.session.session_key:
        request.session.create()
        
    filter_kwargs = {'user': request.user} if request.user.is_authenticated else {'user__isnull': True, 'session_key': request.session.session_key}
    
    try:
        from .services import ChatService
        import json
        
        if request.content_type and 'multipart/form-data' in request.content_type:
            message = request.POST.get('message', "")
            parecer_id = request.POST.get('parecer_id')
            pasta_id = request.POST.get('pasta_id')
            uploaded_files = ChatService.save_uploaded_files(request.FILES)
        else:
            data = json.loads(request.body)
            message = data.get('message', "")
            parecer_id = data.get('parecer_id')
            pasta_id = data.get('pasta_id')
            uploaded_files = []
            
        if not (message or uploaded_files):
            return JsonResponse({'error': 'Mensagem inválida'}, status=400)
            
        if message.strip() == 'RESUMO' and pasta_id:
            return ChatService.handle_resumo_pasta(pasta_id, filter_kwargs)
            
        elif message.strip() == 'RESUMO_PROJETO' and parecer_id:
            return ChatService.handle_resumo_projeto(parecer_id, filter_kwargs)
            
        elif not parecer_id and message.strip().lower() == 'iniciar':
            return ChatService.handle_iniciar(request, filter_kwargs)
            
        elif parecer_id:
            return ChatService.handle_processamento(parecer_id, message, uploaded_files, filter_kwargs)
            
        return JsonResponse({'reply': "Digite **iniciar** para começar uma nova análise de processo."})
        
        return JsonResponse({'error': 'Mensagem inválida'}, status=400)
    except Exception as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        trace = traceback.format_exc()
        logger.error(f"ERRO CHAT: {str(e)}\n\n{trace}")
        return JsonResponse({'error': str(e), 'trace': trace}, status=500)

def check_task_status_view(request, task_id):
    """View endpoint para o frontend perguntar (poll) a cada x segundos se a tarefa pesada de IA no Celery acabou."""
    from celery.result import AsyncResult
    task = AsyncResult(task_id)
    
    if task.state == 'SUCCESS':
        parecer_id = request.GET.get('parecer_id')
        if parecer_id:
            from .models import Parecer
            try:
                p = Parecer.objects.get(id=parecer_id)
                reply = (
                    f"**Parecer Técnico Gerado com Sucesso!**\n\n"
                    f"{p.parecer_final}\n\n"
                    f"---\n\n"
                    f"Digite **'ok'** para prosseguir."
                )
                return JsonResponse({'status': 'SUCCESS', 'reply': reply, 'status_fase': p.status_fase})
            except Exception as e:
                return JsonResponse({'status': 'FAILURE', 'error': f"Parecer não encontrado. {e}"})
                
        return JsonResponse({'status': 'SUCCESS', 'reply': "Tarefa concluída, mas Parecer ID não fornecido.", 'status_fase': 6})
        
    elif task.state == 'FAILURE':
        return JsonResponse({'status': 'FAILURE', 'error': str(task.info)})
        
    return JsonResponse({'status': 'PROCESSING'})

def planos_view(request):
    if not request.session.session_key:
        request.session.create()
    
    if request.user.is_authenticated:
        total_julgados = Parecer.objects.filter(user=request.user).count()
    else:
        total_julgados = Parecer.objects.filter(user__isnull=True, session_key=request.session.session_key).count()

    context = {
        'total_julgados': total_julgados
    }
    return render(request, 'planos.html', context)

@login_required
def checkout_view(request):
    try:
        # Recupera qual plano foi selecionado
        plan_type = request.GET.get('plan', 'pro')
        
        if plan_type == 'basic':
            item_title = "P-JARI/SC Básico (40 Pareceres)"
            item_price = 720.00
        elif plan_type == 'extra':
            item_title = "P-JARI/SC 1 Crédito Extra"
            item_price = 20.00
        else:
            item_title = "P-JARI/SC Profissional (80 Pareceres)"
            item_price = 1440.00

        # Recupera o token de produção do env
        access_token = getattr(settings, 'MERCADOPAGO_ACCESS_TOKEN', None) or 'APP_USR-TEST-000000'
        
        sdk = mercadopago.SDK(access_token)
        
        # Se estivermos em produção real, usamos o e-mail do usuário.
        # Caso ocorram bloqueios do antifraude do Mercado Pago por testar a compra
        # na mesma máquina/conta do recebedor, recomenda-se usar modo sandbox do SDK.
        payer_email = request.user.email or f"user_{request.user.id}@pjari.com.br"


        preference_data = {
            "items": [
                {
                    "title": item_title,
                    "description": "Créditos de sistema",
                    "quantity": 1,
                    "currency_id": "BRL",
                    "unit_price": float(item_price)
                }
            ],
            "payer": {
                "name": "Cliente",
                "surname": "Teste",
                "email": payer_email,
            },
            "back_urls": {
                "success": request.build_absolute_uri("/planos/?success=1"),
                "failure": request.build_absolute_uri("/planos/?failure=1"),
                "pending": request.build_absolute_uri("/planos/?pending=1")
            },
            "payment_methods": {
                "excluded_payment_types": [
                    {"id": "ticket"},
                    {"id": "atm"}
                ],
                "installments": 12 
            },
            "external_reference": str(request.user.id),
        }
        
        # Em algumas integrações modernas, passar um Header x-integrator-id isenta a UI de block local
        request_options = mercadopago.config.RequestOptions()
        request_options.custom_headers = {
            'x-integrator-id': 'dev_24c65fb163bf11ea96500242ac130004' # ID Padrão Integrador Genérico
        }
        preference_response = sdk.preference().create(preference_data, request_options)
        preference = preference_response["response"]
        
        if "init_point" not in preference:
            import json
            return HttpResponse(f"Erro da API do Mercado Pago: {json.dumps(preference_response)}", status=500)
            
        # Redireciona o usuário para o ambiente seguro do Mercado Pago
        return redirect(preference["init_point"])
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HttpResponse(f"Erro ao gerar checkout: {e}", status=500)

@csrf_exempt
def mercadopago_webhook(request):
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
            action = body.get('action')
            type_ = body.get('type')
            data = body.get('data', {})
            
            # Se for uma notificação de pagamento
            if action == 'payment.created' or type_ == 'payment':
                payment_id = data.get('id')
                access_token = getattr(settings, 'MERCADOPAGO_ACCESS_TOKEN', None) or 'APP_USR-TEST-000000'
                sdk = mercadopago.SDK(access_token)
                payment_info = sdk.payment().get(payment_id)
                payment = payment_info.get("response", {})
                
                # Se o pagamento foi aprovado
                if payment.get("status") == "approved":
                    user_id = payment.get("external_reference")
                    if user_id:
                        from django.db import transaction
                        with transaction.atomic():
                            user = User.objects.select_for_update().get(id=user_id)
                            # Descobrir qual o plano comprado baseado pelo valor na notificação para creditar corretamente
                            trans_amount = payment.get("transaction_amount", 0)
                            
                            if trans_amount == 20.00:
                                user.profile.credits += 1
                            elif trans_amount == 720.00:
                                user.profile.credits += 40
                                user.profile.is_pro = True
                                user.profile.subscription_status = "active"
                            elif trans_amount == 1440.00:
                                user.profile.credits += 80
                                user.profile.is_pro = True
                                user.profile.subscription_status = "active"
                            else:
                                # Caso padrão (se valor for diferente por algum desconto)
                                user.profile.credits += 40
                                user.profile.is_pro = True
                                
                            user.profile.save()
                            print(f"Usuário {user.username} - Pagamento processado: {trans_amount}")
                        
                        # Disparar Email de notificação da compra para o Admin via Celery
                        try:
                            from .tasks import send_payment_notification_task
                            nome_cliente = user.get_full_name() or user.username
                            email_cliente = user.email or 'N/A'
                            send_payment_notification_task.delay(nome_cliente, email_cliente, trans_amount, payment_id)
                        except Exception as em:
                            print(f"Erro disparando webhook email: {em}")
                        
            return HttpResponse(status=200)
        except Exception as e:
            print("Webhook Error:", e)
            return HttpResponse(status=400)
    return HttpResponse(status=405)

@login_required
def estatisticas_view(request):
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models.functions import TruncDate
    import calendar
    from datetime import date
    from django.db.models import Avg, F, ExpressionWrapper, fields, Sum
    
    # Pegar mês e ano da requisição ou usar o atual
    hoje = timezone.localtime(timezone.now()).date()
    try:
        mes = int(request.GET.get('mes', hoje.month))
        ano = int(request.GET.get('ano', hoje.year))
    except (ValueError, TypeError):
        mes = hoje.month
        ano = hoje.year
        
    _, ultimo_dia_mes = calendar.monthrange(ano, mes)
    data_inicio = date(ano, mes, 1)
    data_fim = date(ano, mes, ultimo_dia_mes)
    
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
        tempo_total_julgamento = f"{tt_horas}H {tt_minutos}M"
    else:
        tempo_total_julgamento = f"{tt_minutos}M"
        
    m_minutos = int(media_segundos) // 60
    m_segundos = int(media_segundos) % 60
    media_tempo_julgamento = f"{m_minutos}m {m_segundos}s"
    
    # 3. Taxa de Deferimento e Indeferimento
    pareceres_base = Parecer.objects.filter(
        user=request.user,
        is_saved=True,
        created_at__year=ano,
        created_at__month=mes
    ).exclude(parecer_final__isnull=True).exclude(parecer_final__exact='').prefetch_related('pareceres_finais')
    
    total_finais = pareceres_base.count()
    deferidos = 0
    indeferidos = 0
    
    for p in pareceres_base:
        # Se tem parecer final editado e salvo, usa ele
        final_db = p.pareceres_finais.last()
        texto_analise = final_db.conteudo_html if final_db else p.parecer_final
        
        # O default do JariEngine é escrever "...RESULTADO: INDEFERIDO..." e afins
        if texto_analise and "INDEFERID" in texto_analise.upper():
            indeferidos += 1
        else:
            deferidos += 1
    
    # Adicionando contagem limpa pro grafico Donut
    donut_series = [deferidos, indeferidos]
    
    if total_finais > 0:
        taxa_deferimento = int((deferidos / total_finais) * 100)
        taxa_indeferimento = int((indeferidos / total_finais) * 100)
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
        
    # 5. Nuvem de Palavras (Extraindo de Parecer.tese)
    teses_mes = Parecer.objects.filter(
        user=request.user, 
        is_saved=True, 
        created_at__year=ano,
        created_at__month=mes
    ).exclude(tese__isnull=True).exclude(tese__exact='').values_list('tese', flat=True)
    
    import re
    from collections import Counter
    stopwords = {'a', 'o', 'e', 'é', 'do', 'da', 'de', 'para', 'com', 'sem', 'em', 'no', 'na', 
                 'dos', 'das', 'os', 'as', 'um', 'uma', 'uns', 'umas', 'por', 'pelo', 'pela',
                 'que', 'se', 'ao', 'aos', 'ou'}
    todas_palavras = []
    
    for tese_texto in teses_mes:
        if tese_texto:
            # limpar pontos e formatar
            texto_limpo = re.sub(r'[^\w\s]', '', tese_texto.lower())
            palavras = texto_limpo.split()
            palavras_filtradas = [w for w in palavras if len(w) > 3 and w not in stopwords]
            todas_palavras.extend(palavras_filtradas)
    
    contagem_palavras = Counter(todas_palavras)
    # Pegar as 50 palavras mais comuns
    top_palavras = contagem_palavras.most_common(50)
    # Formato pro JS: [['palavra', frequencia], ...]
    nuvem_dados = [[item[0], item[1]] for item in top_palavras]
    
    # Replicar as pastas do menu lateral para manter a interface
    projetos_salvos = Prefetch('projetos', queryset=Parecer.objects.filter(is_saved=True).only('id', 'pasta_id', 'nome_processo', 'created_at', 'is_saved').order_by('-created_at'))
    
    pasta_outros, _ = Pasta.objects.get_or_create(nome_pasta="Outros", user=request.user)
    pasta_outros = Pasta.objects.filter(id=pasta_outros.id).prefetch_related(projetos_salvos).annotate(
        num_projetos=Count('projetos', filter=Q(projetos__is_saved=True))
    ).first()
    
    pastas = Pasta.objects.filter(user=request.user).exclude(id=pasta_outros.id).prefetch_related(projetos_salvos).annotate(
        num_projetos=Count('projetos', filter=Q(projetos__is_saved=True))
    ).order_by('-created_at')
    
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
        'nuvem_dados': json.dumps(nuvem_dados),
        'grafico_datas': json.dumps(datas),
        'grafico_totais': json.dumps(totais_por_dia),
        'pasta_outros': pasta_outros,
        'pastas': pastas,
        'ano_selecionado': ano,
        'mes_selecionado': mes,
        'total_usos_global': total_usos_global,
        'creditos_usuario': creditos_usuario,
        'is_pro': is_pro,
    }
    
    return render(request, 'dashboard.html', context)

from django.views.decorators.http import require_POST
from django.http import JsonResponse
from .models import UserProfile

@login_required
@require_POST
def dismiss_onboarding_view(request):
    try:
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        profile.viu_boas_vindas = True
        profile.save()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_POST
def reorder_folders_view(request):
    try:
        data = json.loads(request.body)
        order_list = data.get('order', [])
        
        for item in order_list:
            pasta_id = int(item.get('id', 0))
            posicao = int(item.get('posicao', 0))
            
            if pasta_id > 0:
                Pasta.objects.filter(id=pasta_id, user=request.user).update(posicao=posicao)
                
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@login_required
def estatisticas_gerais_view(request):
    if not getattr(request.user.profile, 'can_view_global_stats', False) and not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Acesso Negado. Você não tem permissão para visualizar estatísticas globais.")
        
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models.functions import TruncDate
    import calendar
    from datetime import date
    from .models import Parecer, ParecerFinal, AiRequestLog, UserProfile, PjariCacheConfig
    from django.db.models import Avg, F, ExpressionWrapper, fields, Sum
    
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
        tempo_total_julgamento = f"{tt_horas}H {tt_minutos}M"
    else:
        tempo_total_julgamento = f"{tt_minutos}M"
        
    m_minutos = int(media_segundos) // 60
    m_segundos = int(media_segundos) % 60
    media_tempo_julgamento = f"{m_minutos}m {m_segundos}s"
    
    total_usuarios_ativos = Parecer.objects.filter(is_saved=True, created_at__year=ano, created_at__month=mes).values('user').distinct().count()
    
    # 2. Taxa Deferimento Global
    pareceres_base = Parecer.objects.filter(
        is_saved=True,
        created_at__year=ano,
        created_at__month=mes
    ).exclude(parecer_final__isnull=True).exclude(parecer_final__exact='').prefetch_related('pareceres_finais')
    
    total_finais = pareceres_base.count()
    deferidos = 0
    indeferidos = 0
    
    for p in pareceres_base:
        final_db = p.pareceres_finais.last()
        texto_analise = final_db.conteudo_html if final_db else p.parecer_final
        if texto_analise and "INDEFERID" in texto_analise.upper():
            indeferidos += 1
        else:
            deferidos += 1
            
    donut_series = [deferidos, indeferidos]
    taxa_deferimento = int((deferidos / total_finais) * 100) if total_finais > 0 else 0
    taxa_indeferimento = int((indeferidos / total_finais) * 100) if total_finais > 0 else 0
    
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
    from django.db.models import Sum
    logs = AiRequestLog.objects.filter(data_requisicao__year=ano, data_requisicao__month=mes)
    
    tokens_gemini = logs.filter(provider__icontains='Gemini').aggregate(
        in_t=Sum('input_tokens'), out_t=Sum('output_tokens')
    )
    tokens_perplexity = logs.filter(provider__icontains='Perplexity').aggregate(
        in_t=Sum('input_tokens'), out_t=Sum('output_tokens')
    )
    consultas_vertex = logs.filter(provider__icontains='Vertex').count()
    
    custo_gemini = (tokens_gemini['in_t'] or 0) * (0.075 / 1000000) + (tokens_gemini['out_t'] or 0) * (0.30 / 1000000)
    custo_perplexity = ((tokens_perplexity['in_t'] or 0) + (tokens_perplexity['out_t'] or 0)) * (1.00 / 1000000)
    custo_vertex = consultas_vertex * 0.005
    
    projetos_salvos = Prefetch('projetos', queryset=Parecer.objects.filter(is_saved=True).only('id', 'pasta_id', 'nome_processo', 'created_at', 'is_saved').order_by('-created_at'))
    pasta_outros, _ = Pasta.objects.get_or_create(nome_pasta="Outros", user=request.user)
    pasta_outros = Pasta.objects.filter(id=pasta_outros.id).prefetch_related(projetos_salvos).annotate(
        num_projetos=Count('projetos', filter=Q(projetos__is_saved=True))
    ).first()
    pastas = Pasta.objects.filter(user=request.user).exclude(id=pasta_outros.id).prefetch_related(projetos_salvos).annotate(
        num_projetos=Count('projetos', filter=Q(projetos__is_saved=True))
    ).order_by('-created_at')
    
    # --- NOVAS MÉTRICAS ESTRATÉGIAS ---
    
    # 5. Eficiência do P-JARI Cache (Hit Rate Global)
    cache_config = PjariCacheConfig.objects.first()
    hit_rate = cache_config.hit_rate if cache_config else "0.00%"
    
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
    
    # 8. Distribuição Legal (Top 3 - Termos na tese que remetem a artigos)
    # Reutilizando a lógica do Dashboard local mas sem filtro de user
    teses_globais = Parecer.objects.filter(
        is_saved=True, created_at__year=ano, created_at__month=mes
    ).exclude(tese__isnull=True).exclude(tese__exact='').values_list('tese', flat=True)
    
    texto_total_global = " ".join(teses_globais).lower()
    import re
    # Buscando citações a artigos, ex: "art. 165", "artigo 162"
    artigos = re.findall(r'art[igo\.]*\s*(\d+[a-z]?)', texto_total_global)
    from collections import Counter
    contagem_artigos = Counter(artigos).most_common(3)
    top_artigos = [{"artigo": f"Art. {art}", "qtd": qtd} for art, qtd in contagem_artigos]
    
    # 9. Funil Temporal (Gargalos de Prescrição - Média de dias Protocolo -> Julgamento)
    processos_com_datas = Parecer.objects.filter(
        is_saved=True, created_at__year=ano, created_at__month=mes, 
        data_protocolo__isnull=False, data_sessao__isnull=False
    ).annotate(
        diff_dias=ExpressionWrapper(F('data_sessao') - F('data_protocolo'), output_field=fields.DurationField())
    ).aggregate(avg_diff=Avg('diff_dias'))
    
    avg_dias_funil = 0
    if processos_com_datas['avg_diff']:
        avg_dias_funil = processos_com_datas['avg_diff'].days

    context = {
        'total_julgados': total_julgados_global,
        'tempo_poupado_horas': tempo_poupado_horas,
        'tempo_total_julgamento': tempo_total_julgamento,
        'media_tempo_julgamento': media_tempo_julgamento,
        'taxa_deferimento': taxa_deferimento,
        'taxa_indeferimento': taxa_indeferimento,
        'deferidos_count': deferidos,
        'indeferidos_count': indeferidos,
        'total_usuarios_ativos': total_usuarios_ativos,
        'donut_series': json.dumps(donut_series),
        'grafico_datas': json.dumps(datas),
        'grafico_totais': json.dumps(totais_por_dia),
        'pasta_outros': pasta_outros,
        'pastas': pastas,
        'ano_selecionado': ano,
        'mes_selecionado': mes,
        'tokens_gemini_in': f"{(tokens_gemini['in_t'] or 0):,}".replace(',','.'),
        'tokens_gemini_out': f"{(tokens_gemini['out_t'] or 0):,}".replace(',','.'),
        'tokens_perplexity_in': f"{(tokens_perplexity['in_t'] or 0):,}".replace(',','.'),
        'tokens_perplexity_out': f"{(tokens_perplexity['out_t'] or 0):,}".replace(',','.'),
        'consultas_vertex': consultas_vertex,
        'custo_gemini': f"US$ {custo_gemini:.4f}",
        'custo_perplexity': f"US$ {custo_perplexity:.4f}",
        'custo_vertex': f"US$ {custo_vertex:.4f}",
        
        # Novas métricas context
        'hit_rate': hit_rate,
        'taxa_interceptacao': taxa_interceptacao,
        'ultimas_inconsistencias': ultimas_inconsistencias,
        'taxa_conversao': taxa_conversao,
        'top_artigos': top_artigos,
        'avg_dias_funil': avg_dias_funil,
    }
    return render(request, 'dashboard_global.html', context)

@login_required
@require_POST
def create_citacao_view(request):
    import json
    from .models import BancoTese
    titulo = request.POST.get('titulo')
    conteudo = request.POST.get('conteudo')
    
    if not titulo or not conteudo:
        return JsonResponse({'error': 'Título e Conteúdo são obrigatórios.'}, status=400)
        
    banco = BancoTese.objects.create(
        user=request.user,
        titulo=titulo,
        conteudo=conteudo
    )
    
    return JsonResponse({'success': True, 'id': banco.id, 'titulo': titulo})
