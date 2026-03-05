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
    projetos_salvos = Prefetch('projetos', queryset=Parecer.objects.filter(is_saved=True).order_by('-created_at'))
    
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
            rodape_texto = config.rodape_indeferido if is_indeferido else config.rodape_deferido
            
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
            
            tit = config.titulo_cabecalho.replace('\n', '<br>') if config.titulo_cabecalho else ""
            sub = config.subtitulo_cabecalho.replace('\n', '<br>') if config.subtitulo_cabecalho else ""
            
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
            texto_html = texto_gerado_pela_ia.replace('\n', '<br>')
            texto_html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', texto_html)
            
            # Formatar dossiê se existir na View do Editor para passar pro PDF
            dossie_html = parecer.dossie_fontes or ""
            if dossie_html:
                dossie_html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" class="text-blue-600 hover:text-blue-800 underline break-words font-semibold" rel="noopener noreferrer">\1</a>', dossie_html)
                dossie_html = re.sub(r'(?<!href="|href=\')\b(https?:\/\/[^\s<]+[^<.,:;"\')\]\s])', r'<a href="\1" target="_blank" class="text-blue-500 hover:text-blue-700 underline truncate inline-block max-w-[250px] align-bottom" title="\1" rel="noopener noreferrer">Acessar Link</a>', dossie_html)
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
            parecer_gerado = texto_gerado_pela_ia.replace('\n', '<br>')

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
        # Usuário autenticado: Verifica limite de créditos
        total_usos = Parecer.objects.filter(user=request.user, is_saved=True).count()
        if total_usos >= request.user.profile.credits:
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
        # Se Content-Type for multipart, tratar via POST
        if request.content_type and 'multipart/form-data' in request.content_type:
            message = request.POST.get('message')
            parecer_id = request.POST.get('parecer_id')
            pasta_id = request.POST.get('pasta_id')
            
            # Salva os arquivos e gera a string de caminhos usando o storage backend
            files = []
            from django.core.files.storage import default_storage
            import os
            for key, f in request.FILES.items():
                if f.name.endswith('.pdf'):
                    # O Django Storage cuida de salvar no Local ou no Google Cloud
                    base_name = os.path.basename(f.name)
                    path = default_storage.save(f'uploads/{base_name}', f)
                    # Adiciona a URL do arquivo ou o nome no storage para referência futura
                    files.append(path)
            
            uploaded_files = files
        else:
            data = json.loads(request.body)
            message = data.get('message')
            parecer_id = data.get('parecer_id')
            pasta_id = data.get('pasta_id')
            uploaded_files = []

        if message:
            
            # Novo bloco para buscar resumo da pasta com todos os seus projetos
            if message.strip() == 'RESUMO' and pasta_id:
                pasta = get_object_or_404(Pasta, id=pasta_id, **filter_kwargs)
                projetos = pasta.projetos.filter(is_saved=True).order_by('-created_at')
                if projetos.exists():
                    reply = f"**{pasta.nome_pasta} - Visão Geral:**\n\nEsta pasta contém {projetos.count()} processos mapeados. Clique em um processo na barra lateral para ver o Laudo Técnico e o Parecer completo."
                else:
                    reply = "Esta pasta está vazia. Digite **iniciar** para começar uma nova análise."
                return JsonResponse({'reply': reply})
                
            # Novo bloco para buscar O RESUMO DE APENAS UM ÚNICO PROJETO ESPECÍFICO
            elif message.strip() == 'RESUMO_PROJETO' and parecer_id:
                p = get_object_or_404(Parecer, id=parecer_id, is_saved=True, **filter_kwargs)
                reply = f"**O motor identificou a seleção do projeto {p.nome_processo}. Abaixo constam os resultados:**\n\n"
                reply += f"--- \n"
                
                if p.parecer_final:
                    reply += f"{p.parecer_final}\n\n"
                    if p.dossie_fontes:
                        import re
                        parsed_dossie = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" class="text-blue-600 hover:text-blue-800 underline break-words font-semibold" rel="noopener noreferrer">\1</a>', p.dossie_fontes)
                        # Remove markdown boldings and links from interfering with next regex
                        parsed_dossie = re.sub(r'(?<!href="|href=\')\b(https?:\/\/[^\s<]+[^<.,:;"\')\]\s])', r'<a href="\1" target="_blank" class="text-blue-500 hover:text-blue-700 underline truncate inline-block max-w-[250px] align-bottom" title="\1" rel="noopener noreferrer">Acessar Link</a>', parsed_dossie)
                        reply += f"<details class='mt-4 mb-2 bg-blue-50/50 rounded-xl border border-blue-100/50 overflow-hidden shadow-sm'><summary class='px-4 py-3 bg-white/50 cursor-pointer text-[#444746] font-medium flex items-center gap-2 hover:bg-blue-50/50 transition-colors outline-none'>🔎 FUNDAMENTAÇÃO NORMATIVA - PARECER</summary><div class='p-4 text-sm text-[#444746] leading-relaxed border-t border-blue-100/50 bg-white/30 whitespace-pre-wrap'>{parsed_dossie}</div></details>\n\n"
                    
                    # Injects link for the editor isolated from paragraph tags so marked skips stripping CSS
                    reply += f"\n\n<div style='margin-top: 20px;'><a href='/parecer/{p.id}/editor/' style='display:inline-block; padding:8px 16px; background-color:#2563eb; color:white; border-radius:8px; text-decoration:none; font-weight:600;'>✏️ Abrir Editor de Parecer Final</a></div>\n\n"
                else:
                    reply += "*(Sem parecer gerado)*\n\n"
                return JsonResponse({'reply': reply})
                
            # Se o usuário mandou "iniciar" sem Parecer, cria um Processo Automático temporário (não salvo na sidebar ainda)
            if not parecer_id and message.strip().lower() == 'iniciar':
                if not request.user.is_authenticated:
                    count = Parecer.objects.filter(user__isnull=True, session_key=request.session.session_key).count()
                    if count >= 2:
                        return JsonResponse({'requires_login': True})
                else:
                    # Usuário autenticado: Verifica limite de créditos
                    total_usos = Parecer.objects.filter(user=request.user, is_saved=True).count()
                    if total_usos >= request.user.profile.credits:
                        return JsonResponse({'requires_plan': True})

                from datetime import datetime
                nome_temporario = f"Processo {datetime.now().strftime('%d/%m %H:%M')}"
                # is_saved=False indica que é um rascunho temporário ativo no chat
                if request.user.is_authenticated:
                    parecer = Parecer.objects.create(user=request.user, nome_processo=nome_temporario, is_saved=False)
                else:
                    parecer = Parecer.objects.create(session_key=request.session.session_key, nome_processo=nome_temporario, is_saved=False)
                parecer_id = parecer.id
                
                from .jari_engine import JariEngine
                engine = JariEngine(parecer)
                reply = engine.get_current_prompt()
                
                return JsonResponse({
                    'reply': reply,
                    'status_fase': parecer.status_fase,
                    'active_parecer_id': parecer.id
                })
            
            if parecer_id:
                # Processamento Faseado usando o Jari Engine
                from .jari_engine import JariEngine
                parecer = get_object_or_404(Parecer, id=parecer_id, **filter_kwargs)
                engine = JariEngine(parecer)
                reply = engine.process_message(message, uploaded_files)
                
                return JsonResponse({
                    'reply': reply,
                    'status_fase': parecer.status_fase
                })
            else:
                # Fallback se não mandou "iniciar" e não tem parecer selecionado
                reply = "Digite **iniciar** para começar uma nova análise de processo."
                return JsonResponse({'reply': reply})
                
        return JsonResponse({'error': 'Mensagem inválida'}, status=400)
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        try:
            with open('debug_jari.txt', 'a') as f:
                f.write(f"ERRO CHAT: {str(e)}\n\n{trace}\n\n")
        except:
            pass
        traceback.print_exc()
        return JsonResponse({'error': str(e), 'trace': trace}, status=500)

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
        
        # O PA_UNAUTHORIZED request bloqueia a geração dependendo de quem pede
        # Ao usar o Production Token (APP_USR-) para validar, qualquer dado Payer 
        # que conflitar minimamente com a conta do titular de destino é bloqueada pelo
        # modelo antifraude (PolicyAgent). Para testes locais forçamos um e-mail dummy:
        
        # Pega um email que seja garantidamente DIFERENTE do email do dono da conta Mercado Pago
        payer_email = "test_user_pjari_999@gmail.com"
        if request.user.email and 'gefferson' not in request.user.email.lower() and request.user.email != 'geffersonvivan@gmail.com':
            payer_email = request.user.email

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
                        user = User.objects.get(id=user_id)
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
                        
                        # Disparar Email de notificação da compra para o Admin
                        from django.core.mail import send_mail
                        nome_cliente = user.get_full_name() or user.username
                        email_cliente = user.email or 'N/A'
                        send_mail(
                            subject=f'✅ Nova Venda Confirmada: {nome_cliente}',
                            message=f'Sucesso! Um pagamento de R$ {trans_amount} foi aprovado no Mercado Pago e os créditos foram liberados.\n\nDetalhes do Cliente:\nNome: {nome_cliente}\nEmail: {email_cliente}\nID do Pagamento: {payment_id}',
                            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'validacao@pjarisc.com.br'),
                            recipient_list=['geffersonvivan@gmail.com'],
                            fail_silently=True,
                        )
                        
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
    
    # 3. Taxa de Deferimento (ParecerFinal vinculados aos Pareceres do usuario)
    pareceres_finais = ParecerFinal.objects.filter(
        parecer_referencia__user=request.user,
        parecer_referencia__created_at__year=ano,
        parecer_referencia__created_at__month=mes
    )
    total_finais = pareceres_finais.count()
    
    deferidos = pareceres_finais.filter(status_resultado__icontains='DEFERIDO').exclude(status_resultado__icontains='INDEFERIDO').count()
    indeferidos = pareceres_finais.filter(status_resultado__icontains='INDEFERIDO').count()
    
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
    pareceres_mes = Parecer.objects.filter(
        user=request.user, 
        is_saved=True, 
        created_at__year=ano,
        created_at__month=mes
    ).exclude(tese__isnull=True).exclude(tese__exact='')
    
    import re
    from collections import Counter
    stopwords = {'a', 'o', 'e', 'é', 'do', 'da', 'de', 'para', 'com', 'sem', 'em', 'no', 'na', 
                 'dos', 'das', 'os', 'as', 'um', 'uma', 'uns', 'umas', 'por', 'pelo', 'pela',
                 'que', 'se', 'ao', 'aos', 'ou'}
    todas_palavras = []
    for p in pareceres_mes:
        if p.tese:
            # limpar pontos e formatar
            texto_limpo = re.sub(r'[^\w\s]', '', p.tese.lower())
            palavras = texto_limpo.split()
            palavras_filtradas = [w for w in palavras if len(w) > 3 and w not in stopwords]
            todas_palavras.extend(palavras_filtradas)
    
    contagem_palavras = Counter(todas_palavras)
    # Pegar as 50 palavras mais comuns
    top_palavras = contagem_palavras.most_common(50)
    # Formato pro JS: [['palavra', frequencia], ...]
    nuvem_dados = [[item[0], item[1]] for item in top_palavras]
    
    # Replicar as pastas do menu lateral para manter a interface
    projetos_salvos = Prefetch('projetos', queryset=Parecer.objects.filter(is_saved=True).order_by('-created_at'))
    
    pasta_outros, _ = Pasta.objects.get_or_create(nome_pasta="Outros", user=request.user)
    pasta_outros = Pasta.objects.filter(id=pasta_outros.id).prefetch_related(projetos_salvos).annotate(
        num_projetos=Count('projetos', filter=Q(projetos__is_saved=True))
    ).first()
    
    pastas = Pasta.objects.filter(user=request.user).exclude(id=pasta_outros.id).prefetch_related(projetos_salvos).annotate(
        num_projetos=Count('projetos', filter=Q(projetos__is_saved=True))
    ).order_by('-created_at')
    
    context = {
        'total_julgados': total_julgados,
        'tempo_poupado_horas': tempo_poupado_horas,
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
