from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from datetime import datetime
from .models import Parecer, Pasta
from .jari_engine import JariEngine
import json
import re
import os
from django.core.files.storage import default_storage

class ChatService:
    @staticmethod
    def save_uploaded_files(files_dict):
        files = []
        for key, f in files_dict.items():
            if f.name.endswith('.pdf'):
                base_name = os.path.basename(f.name)
                path = default_storage.save(f'uploads/{base_name}', f)
                files.append(path)
        return files

    @staticmethod
    def handle_resumo_pasta(pasta_id, filter_kwargs):
        pasta = get_object_or_404(Pasta, id=pasta_id, **filter_kwargs)
        projetos = pasta.projetos.filter(is_saved=True).order_by('-created_at')
        if projetos.exists():
            reply = f"**{pasta.nome_pasta} - Visão Geral:**\n\nEsta pasta contém {projetos.count()} processos mapeados. Clique em um processo na barra lateral para ver o Laudo Técnico e o Parecer completo."
        else:
            reply = "Esta pasta está vazia. Digite **iniciar** para começar uma nova análise."
        return JsonResponse({'reply': reply})

    @staticmethod
    def handle_resumo_projeto(parecer_id, filter_kwargs):
        p = get_object_or_404(Parecer, id=parecer_id, is_saved=True, **filter_kwargs)
        reply = ""
        if p.parecer_final:
            reply += f"{p.parecer_final}\n\n"
            if p.dossie_fontes:
                parsed_dossie = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" class="text-blue-600 hover:text-blue-800 underline break-words font-semibold" rel="noopener noreferrer">\1</a>', p.dossie_fontes)
                parsed_dossie = re.sub(r'(?<!href="|href=\')\b(https?:\/\/[^\s<]+[^<.,:;"\')\]\s])', r'<a href="\1" target="_blank" class="text-blue-500 hover:text-blue-700 underline truncate inline-block max-w-[250px] align-bottom" title="\1" rel="noopener noreferrer">Acessar Link</a>', parsed_dossie)
            reply += f"\n\n<div style='margin-top: 20px;'><a href='/parecer/{p.id}/editor/' style='display:inline-block; padding:8px 16px; background-color:#2563eb !important; border-radius:8px; text-decoration:none !important; font-weight:600;'><span style='color:#ffffff !important; font-size:14px;'>✏️ Abrir Editor de Parecer Final</span></a></div>\n\n"
        else:
            reply += "*(Sem parecer gerado)*\n\n"
        return JsonResponse({'reply': reply})

    @staticmethod
    def handle_iniciar(request, filter_kwargs):
        if not request.user.is_authenticated:
            count = Parecer.objects.filter(user__isnull=True, session_key=request.session.session_key).count()
            if count >= 2:
                return JsonResponse({'requires_login': True})
        else:
            total_usos = Parecer.objects.filter(user=request.user, is_saved=True).count()
            if total_usos >= request.user.profile.credits and not request.user.profile.is_pro:
                return JsonResponse({'requires_plan': True})

        if request.user.is_authenticated:
            nome_usuario = f"{request.user.first_name} {request.user.last_name}".strip().upper()
            if not nome_usuario:
                nome_usuario = request.user.username.upper()
        else:
            nome_usuario = "VISITANTE"
        nome_temporario = f"Parecer {nome_usuario} {datetime.now().strftime('%d/%m %H:%M')}"
        
        if request.user.is_authenticated:
            parecer = Parecer.objects.create(user=request.user, nome_processo=nome_temporario, is_saved=False)
        else:
            parecer = Parecer.objects.create(session_key=request.session.session_key, nome_processo=nome_temporario, is_saved=False)
        
        engine = JariEngine(parecer)
        reply = engine.get_current_prompt()
        
        return JsonResponse({
            'reply': reply,
            'status_fase': parecer.status_fase,
            'active_parecer_id': parecer.id
        })

    @staticmethod
    def handle_processamento(parecer_id, message, uploaded_files, filter_kwargs):
        parecer = get_object_or_404(Parecer, id=parecer_id, **filter_kwargs)
        engine = JariEngine(parecer)
        reply = engine.process_message(message, uploaded_files)
        
        if reply.startswith('{"status": "celery"'):
            try:
                data_celery = json.loads(reply)
                task_id = data_celery.get("task_id")
                tipo = data_celery.get("type", "NORMAL")
                
                if tipo == "PREJUDICIALIDADE":
                    msg = "\n⚠️ **Prejudicialidade Constatada**. Teses defensivas prejudicadas em razão da extinção da pretensão punitiva ou inadmissibilidade recursal.\n\n⏳ *O processo entrou na Fila de Engenharia de Prompts (Fase 5). Isso levará em média 1 minuto...*"
                else:
                    msg = "⏳ *O processo entrou na Fila de Engenharia de Prompts (Fase 5). Isso levará em média 1 minuto. O P-JARI irá disponibilizar o Parecer logo abaixo quando for concluído...*"
                    
                return JsonResponse({
                    'reply': msg,
                    'status_fase': parecer.status_fase,
                    'task_id': task_id,
                    'is_processing': True
                })
            except Exception:
                pass
        
        return JsonResponse({
            'reply': reply,
            'status_fase': parecer.status_fase
        })
