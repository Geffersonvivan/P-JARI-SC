import logging
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from datetime import datetime
from .models import Parecer, Pasta
from .jari_engine import JariEngine

logger = logging.getLogger(__name__)
import json
import re
import os
import urllib.parse
from django.core.files.storage import default_storage

def _p(field):
    """Normaliza FileField para string de caminho, ou None."""
    if not field:
        return None
    return field.name if hasattr(field, 'name') else (str(field) or None)

class ChatService:
    MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB por arquivo

    @staticmethod
    def save_uploaded_files(files_dict):
        import logging as _log
        _logger = _log.getLogger(__name__)
        files = []
        for key, f in files_dict.items():
            # Validação 1: extensão
            if not f.name.lower().endswith('.pdf'):
                _logger.warning("upload rejeitado (extensão inválida): %s", f.name)
                continue
            # Validação 2: tamanho máximo (20 MB)
            if f.size > ChatService.MAX_PDF_SIZE_BYTES:
                _logger.warning(
                    "upload rejeitado (tamanho %d bytes > %d): %s",
                    f.size, ChatService.MAX_PDF_SIZE_BYTES, f.name,
                )
                continue
            # Validação 3: magic bytes — confirma que é realmente um PDF
            header = f.read(4)
            f.seek(0)
            if header != b'%PDF':
                _logger.warning("upload rejeitado (magic bytes inválidos): %s", f.name)
                continue
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
            
        autuacao_url = None
        consolidado_url = None
        try:
            _aut = _p(p.autuacao_pdf_path)
            _con = _p(p.consolidado_pdf_path)
            if _aut and default_storage.exists(_aut):
                autuacao_url = f'/chat/pdf/{p.id}/autuacao/'
            if _con and default_storage.exists(_con):
                consolidado_url = f'/chat/pdf/{p.id}/consolidado/'
        except Exception as e:
            logger.error("Erro ao buscar URLs de media PDFs: %s", e)
            
        from .models import ChatMessage
        # Prefixos de comandos internos que não devem aparecer no histórico visível
        _PREFIXOS_INTERNOS = ('FASE1_CONFIRM:', 'ESTE_E_UM_BOTAO_GHOST', 'EDITAR:')
        historico = ChatMessage.objects.filter(parecer=p).order_by('created_at')
        chat_history = [
            {'role': m.role, 'content': m.content}
            for m in historico
            if m.content and not any(m.content.startswith(p_) for p_ in _PREFIXOS_INTERNOS)
        ]
        
        if p.parecer_final or not chat_history:
            chat_history.append({'role': 'assistant', 'content': reply})
            

        return JsonResponse({
            'reply': reply,
            'is_saved': p.is_saved,
            'status_fase': p.status_fase,
            'autuacao_url': autuacao_url,
            'consolidado_url': consolidado_url,
            'chat_history': chat_history
        })

    @staticmethod
    def handle_iniciar(request, filter_kwargs):
        if not request.user.is_authenticated:
            count = Parecer.objects.filter(user__isnull=True, session_key=request.session.session_key).count()
            if count >= 2:
                return JsonResponse({'requires_login': True})
        else:
            # Conta saved + em andamento para evitar race condition onde dois processos
            # simultâneos (is_saved=False) passam pelo check e excedem o limite ao finalizar.
            total_usos = Parecer.objects.filter(user=request.user).count()
            if total_usos >= request.user.profile.credits and not request.user.profile.is_pro and not request.user.is_superuser:
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
        
        from .models import ChatMessage
        ChatMessage.objects.create(parecer=parecer, role='assistant', content=reply)
        
        return JsonResponse({
            'reply': reply,
            'status_fase': parecer.status_fase,
            'active_parecer_id': parecer.id
        })

    @staticmethod
    def handle_processamento(parecer_id, message, uploaded_files, filter_kwargs):
        import time as _time
        import logging as _logging
        _perf = _logging.getLogger('pjari.perf')
        _t0 = _time.monotonic()

        parecer = get_object_or_404(Parecer, id=parecer_id, **filter_kwargs)

        # Guard: parecer finalizado não aceita ações de fase — apenas leitura.
        from .engine import FASE_FINALIZADO
        _msg_strip = (message or '').strip()
        _ACOES_FASE = ('FASE1_CONFIRM:', 'ok', 'corrigir', 'iniciar')
        if parecer.status_fase == FASE_FINALIZADO and any(
            _msg_strip.lower().startswith(a.lower()) for a in _ACOES_FASE
        ):
            return JsonResponse(
                {'error': 'Este parecer está finalizado e não aceita mais ações de fluxo.', 'readonly': True},
                status=409
            )

        from .models import ChatMessage
        # Salva o input do usuario
        if message and str(message).strip() != 'ESTE_E_UM_BOTAO_GHOST':
            ChatMessage.objects.create(parecer=parecer, role='user', content=message)

        engine = JariEngine(parecer)
        _t1 = _time.monotonic()
        reply = engine.process_message(message, uploaded_files)
        _perf.info(f"[PERF] handle_processamento: process_message={_time.monotonic()-_t1:.2f}s total_so_far={_time.monotonic()-_t0:.2f}s parecer={parecer_id} files={len(uploaded_files)}")
        
        if reply.startswith('{"status": "celery"'):
            try:
                data_celery = json.loads(reply)
                task_id = data_celery.get("task_id")
                tipo = data_celery.get("type", "NORMAL")
                
                if tipo == "PREJUDICIALIDADE":
                    msg = "\n⚠️ **Prejudicialidade Constatada**. Teses defensivas prejudicadas em razão da extinção da pretensão punitiva ou inadmissibilidade recursal.\n\n⏳ *O processo entrou na Fila de Engenharia de Prompts (Fase 5). Isso levará em média 1 minuto...*"
                elif tipo == "FASE1":
                    msg = "⏳ *Analisando os documentos com Inteligência Artificial. Aguarde — isso pode levar até 30 segundos...*"
                elif tipo == "FASE2":
                    msg = "⏳ *Extraindo datas sensíveis e montando a tabela de prazos via Inteligência Artificial. Aguarde...*"
                elif tipo == "FASE4":
                    msg = "⏳ *Extraindo teses defensivas via Inteligência Artificial. Aguarde...*"
                else:
                    msg = "⏳ *O processo entrou na Fila de Engenharia de Prompts (Fase 5). Isso levará em média 1 minuto. O P-JARI irá disponibilizar o Parecer logo abaixo quando for concluído...*"
                
                # Monta URLs dos PDFs já salvos para exibir na lateral imediatamente
                autuacao_url = consolidado_url = ata_url = None
                autuacao_name = "Auto de Infração"
                consolidado_name = "Defesa/Recurso"
                ata_name = "Ata"
                try:
                    _aut = _p(parecer.autuacao_pdf_path)
                    _con = _p(parecer.consolidado_pdf_path)
                    _ata = _p(parecer.ata_pdf_path)
                    if _aut and default_storage.exists(_aut):
                        autuacao_url = f'/chat/pdf/{parecer.id}/autuacao/'
                        autuacao_name = urllib.parse.unquote(os.path.basename(_aut))
                    if _con and default_storage.exists(_con):
                        consolidado_url = f'/chat/pdf/{parecer.id}/consolidado/'
                        consolidado_name = urllib.parse.unquote(os.path.basename(_con))
                    if _ata and default_storage.exists(_ata):
                        ata_url = f'/chat/pdf/{parecer.id}/ata/'
                        ata_name = urllib.parse.unquote(os.path.basename(_ata))
                except Exception:
                    pass

                return JsonResponse({
                    'reply': msg,
                    'status_fase': parecer.status_fase,
                    'task_id': task_id,
                    'task_type': tipo,
                    'is_processing': True,
                    'autuacao_url': autuacao_url,
                    'consolidado_url': consolidado_url,
                    'ata_url': ata_url,
                    'autuacao_name': autuacao_name,
                    'consolidado_name': consolidado_name,
                    'ata_name': ata_name,
                })
            except Exception:
                pass
                
        # Salva a resposta do robo
        ChatMessage.objects.create(parecer=parecer, role='assistant', content=reply)
        
        autuacao_url = None
        consolidado_url = None
        ata_url = None
        autuacao_name = "Auto de Infração"
        consolidado_name = "Defesa/Recurso"
        ata_name = "Ata"
        
        try:
            _aut = _p(parecer.autuacao_pdf_path)
            _con = _p(parecer.consolidado_pdf_path)
            _ata = _p(parecer.ata_pdf_path)
            if _aut and default_storage.exists(_aut):
                autuacao_url = f'/chat/pdf/{parecer.id}/autuacao/'
                autuacao_name = urllib.parse.unquote(os.path.basename(_aut))
            if _con and default_storage.exists(_con):
                consolidado_url = f'/chat/pdf/{parecer.id}/consolidado/'
                consolidado_name = urllib.parse.unquote(os.path.basename(_con))
            if _ata and default_storage.exists(_ata):
                ata_url = f'/chat/pdf/{parecer.id}/ata/'
                ata_name = urllib.parse.unquote(os.path.basename(_ata))
        except Exception:
            pass

        response_data = {
            'reply': reply,
            'status_fase': parecer.status_fase,
            'autuacao_url': autuacao_url,
            'consolidado_url': consolidado_url,
            'ata_url': ata_url,
            'autuacao_name': autuacao_name,
            'consolidado_name': consolidado_name,
            'ata_name': ata_name
        }
        # Inclui o texto bruto do parecer na fase 6 para que o frontend
        # pré-preencha o modal de edição sem precisar parsear o HTML renderizado.
        if parecer.status_fase == 6:
            response_data['parecer_final'] = parecer.parecer_final or ''
        return JsonResponse(response_data)
