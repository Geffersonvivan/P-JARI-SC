import os
import django
from django.db.models import Q

# Configure Django environment for standalone script
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core_jari.settings')
django.setup()

from chat.models import Parecer
from chat.pdf_extractor import PDFExtractor

def backfill_infracoes():
    pareceres_sem_infracao = Parecer.objects.filter(
        Q(infracao_documento__isnull=True) | Q(infracao_documento=''),
        consolidado_pdf_path__isnull=False
    ).exclude(consolidado_pdf_path='').exclude(consolidado_pdf_path__contains='upload_simulado')
    
    total = pareceres_sem_infracao.count()
    print(f"[{total}] Pareceres precisam ser retroativos.")
    
    atualizados = 0
    erros = 0
    
    for i, p in enumerate(pareceres_sem_infracao, 1):
        print(f"Processando {i}/{total}: ID {p.id} - PDF: {p.consolidado_pdf_path}")
        try:
            infracao = PDFExtractor.extract_infracao_from_pdf(p.consolidado_pdf_path)
            if infracao:
                p.infracao_documento = infracao
                p.save(update_fields=['infracao_documento'])
                atualizados += 1
                print(f"  -> SUCESSO! Infracao: '{infracao}'")
            else:
                print(f"  -> NAO ENCONTRADA no PDF.")
        except Exception as e:
            erros += 1
            print(f"  -> ERRO OCORRIDO: {e}")
            
    print(f"=== BACKFILL FINALIZADO ===")
    print(f"Atualizados com sucesso: {atualizados}")
    print(f"Falharam / Não encontrada: {total - atualizados}")
    print(f"Erros crassos: {erros}")

if __name__ == '__main__':
    backfill_infracoes()
