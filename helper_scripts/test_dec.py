import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.jari_math import JariMath

cenarios = [
    {
        "nome": "Cenário 1: CTB Antigo (Antes de Abr/2021) = Limite 30 dias",
        "infracao": "2019-05-10",
        "notificacao": "2019-06-15", # 36 dias > 30 (Decaiu)
        "decisao": None
    },
    {
        "nome": "Cenário 2: Era COVID (Res 782) = CTB Antigo + 256 dias suspensos",
        "infracao": "2020-04-10",
        "notificacao": "2020-11-20", # 224 dias - 256 dilação = Zero (Não decaiu)
        "decisao": None
    },
    {
        "nome": "Cenário 3: Transição (Abr/2021 a Out/2021) = 180 (Not), 360 (Final)",
        "infracao": "2021-06-10",
        "notificacao": "2021-12-05", # 178 dias
        "decisao": "2022-06-10" # 365 dias > 360 (Decaiu)
    },
    {
        "nome": "Cenário 4: CTB Novo (Após Out/2021)",
        "infracao": "2022-01-10",
        "notificacao": "2022-03-10", # 59 dias (Não decaiu)
        "decisao": "2022-12-25" # 349 dias (Não decaiu)
    }
]

print("========= JARI MOTOR: AUDITORIA DA TRAVA DE DECADÊNCIA =========")
for c in cenarios:
    print(f"\n>> {c['nome']}")
    decaiu, relatorio = JariMath.check_decadencia(c['infracao'], c['notificacao'], c['decisao'])
    print(f"DECADÊNCIA DETECTADA: {'SIM' if decaiu else 'NÃO'}")
    print(relatorio)
print("==================================================================")
