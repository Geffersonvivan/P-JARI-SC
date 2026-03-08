import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.models import Parecer
from chat.jari_engine import JariEngine

print("====== INICIANDO TESTE END-TO-END DO MOTOR JARI ======")

import datetime

# 1. Cria um Parecer Mockado na Fase 1
p = Parecer.objects.create(
    nome_processo="TESTE AUTOMATIZADO 2.5-PRO",
    sgpe="0001/2026",
    pa="999/2026",
    data_protocolo=datetime.date(2021, 6, 10),
    data_sessao=datetime.date(2025, 12, 10),
    prazo_final=datetime.date(2021, 6, 20),
    status_fase=1
)
engine = JariEngine(p)

print("\n--- INJETANDO DADOS INICIAIS (SIMULA FASE 1) ---")
payload_fase1 = "10/06/2021\n20/06/2021\n10/12/2025"
resposta = engine.process_message(payload_fase1, [])
print("Status Parecer:", p.status_fase)

print("\n--- FORÇANDO FASE 2 -> FASE 3 (EXTRAÇÃO E MATEMÁTICA) ---")
p.status_fase = 2
p.save()
engine = JariEngine(p)
resposta = engine.process_message("ok", [])
print(resposta) # Mostra o Log da Fase 3
print("Status Parecer:", p.status_fase)

print("\n--- FORÇANDO FASE 3 -> FASE 4 (JULGAMENTO DAS TESES) ---")
p.status_fase = 31
p.save()
engine = JariEngine(p)
# Simulamos que a tese extraída foi uma tese emotiva
p.tese = "A defesa alega que o recorrente precisa do veículo para trabalhar e que o bocal do etilômetro estava violado, pedindo a anulação do auto."
p.save()
resposta = engine.process_message("ok", [])
print(resposta) # Mostra o Log da Fase 4
print("Status Parecer:", p.status_fase)

print("\n--- FORÇANDO FASE 4 -> FASE 5 (GERAÇÃO DO PARECER FINAL) ---")
p.status_fase = 41
p.save()
engine = JariEngine(p)
resposta = engine.process_message("ok", [])
# Na Fase 8 ele concatena tudo em `texto_parecer`
print("\n====== TEXTO DO PARECER JURÍDICO FINAL GERADO ======\n")
print(p.texto_parecer)
print("\n======================================================\n")

# Limpeza
p.delete()
