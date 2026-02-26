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
    ).order_by('-created_at')
    
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
            rodape_texto = config.rodape_indeferido if "INDEFERID" in texto_gerado_pela_ia.upper() else config.rodape_deferido
            
            nome_usuario = request.user.get_full_name() or request.user.username if request.user.is_authenticated else "Visitante"
            rodape_template = Template(rodape_texto)
            rodape_escolhido = rodape_template.render(Context({'nome_membro': nome_usuario}))
            
            import re
            
            # Use explicit image attributes and wrap it
            logo_html = f"<img src='{config.logo.url}' width='110' style='width: 110px; max-width: 110px; height: auto;'>" if config.logo else ""
            
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
def chat_message_view(request):
    if not request.session.session_key:
        request.session.create()
    filter_kwargs = {'user': request.user} if request.user.is_authenticated else {'user__isnull': True, 'session_key': request.session.session_key}
    try:
        data = json.loads(request.body)
        message = data.get('message')
        parecer_id = data.get('parecer_id')
        pasta_id = data.get('pasta_id')

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
                    reply += f"🛡️ **Nota de Blindagem:** {p.nota_blindagem}\n\n"
                    # Injects link for the editor
                    reply += f"<a href='/parecer/{p.id}/editor/' class='inline-block my-4 px-4 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition shadow-sm' style='text-decoration:none;'>✏️ Abrir Editor de Parecer Final</a>\n\n"
                else:
                    reply += "*(Sem parecer gerado)*\n\n"
                return JsonResponse({'reply': reply})
                
            # Se o usuário mandou "iniciar" sem Parecer, cria um Processo Automático temporário (não salvo na sidebar ainda)
            if not parecer_id and message.strip().lower() == 'iniciar':
                if not request.user.is_authenticated:
                    count = Parecer.objects.filter(user__isnull=True, session_key=request.session.session_key).count()
                    if count >= 2:
                        return JsonResponse({'requires_login': True})

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
                reply = engine.process_message(message)
                
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
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

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
        else:
            item_title = "P-JARI/SC Profissional (80 Pareceres)"
            item_price = 1440.00

        # Inicializar o SDK do Mercado Pago
        sdk = mercadopago.SDK(getattr(settings, 'MERCADOPAGO_ACCESS_TOKEN', 'APP_USR-TEST-000000'))
        
        # Criar preferência de pagamento
        preference_data = {
            "items": [
                {
                    "title": item_title,
                    "quantity": 1,
                    "currency_id": "BRL",
                    "unit_price": item_price
                }
            ],
            "payer": {
                "name": request.user.first_name or request.user.username,
                "email": "test_buyer_12@testuser.com"
            },
            "back_urls": {
                "success": request.build_absolute_uri("/planos/?success=1"),
                "failure": request.build_absolute_uri("/planos/?failure=1"),
                "pending": request.build_absolute_uri("/planos/?pending=1")
            },
            # "auto_return": "approved", # Removido temporariamente pois exige HTTPS no back_url.
            "external_reference": str(request.user.id), # Passa o ID do usuário para identificar no webhook
        }
        
        preference_response = sdk.preference().create(preference_data)
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
                sdk = mercadopago.SDK(getattr(settings, 'MERCADOPAGO_ACCESS_TOKEN', 'APP_USR-TEST-000000'))
                payment_info = sdk.payment().get(payment_id)
                payment = payment_info.get("response", {})
                
                # Se o pagamento foi aprovado
                if payment.get("status") == "approved":
                    user_id = payment.get("external_reference")
                    if user_id:
                        user = User.objects.get(id=user_id)
                        # Atualiza o perfil "PRO" garantindo acesso ilimitado
                        user.profile.is_pro = True
                        user.profile.credits += 40
                        user.profile.subscription_status = "active"
                        user.profile.save()
                        print(f"Usuário {user.username} promovido a PRO com sucesso!")
                        
            return HttpResponse(status=200)
        except Exception as e:
            print("Webhook Error:", e)
            return HttpResponse(status=400)
    return HttpResponse(status=405)
