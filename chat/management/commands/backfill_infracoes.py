from django.core.management.base import BaseCommand
from django.db.models import Q
from chat.models import Parecer
from chat.pdf_extractor import PDFExtractor

class Command(BaseCommand):
    help = 'Preenche os pareceres antigos extraindo a infração diretamente do PDF Consolidado.'

    def handle(self, *args, **options):
        pareceres_sem_infracao = Parecer.objects.filter(
            Q(infracao_documento__isnull=True) | Q(infracao_documento=''),
            consolidado_pdf_path__isnull=False
        ).exclude(consolidado_pdf_path='').exclude(consolidado_pdf_path__contains='upload_simulado')
        
        total = pareceres_sem_infracao.count()
        self.stdout.write(self.style.WARNING(f"[{total}] Pareceres precisam ser retroativos (extraindo infracao do PDF)."))
        
        atualizados = 0
        erros = 0
        
        for i, p in enumerate(pareceres_sem_infracao, 1):
            self.stdout.write(f"Processando {i}/{total}: ID {p.id} - PDF: {p.consolidado_pdf_path}")
            try:
                infracao = PDFExtractor.extract_infracao_from_pdf(p.consolidado_pdf_path)
                if infracao:
                    p.infracao_documento = infracao
                    p.save(update_fields=['infracao_documento'])
                    atualizados += 1
                    self.stdout.write(self.style.SUCCESS(f"  -> SUCESSO! Infracao: '{infracao}'"))
                else:
                    self.stdout.write(self.style.NOTICE(f"  -> NAO ENCONTRADA no PDF (talvez nao seja um Consolidado ou esta em outro padrao)."))
            except Exception as e:
                erros += 1
                self.stdout.write(self.style.ERROR(f"  -> ERRO OCORRIDO: {e}"))
                
        self.stdout.write(self.style.SUCCESS(f"=== BACKFILL FINALIZADO ==="))
        self.stdout.write(self.style.SUCCESS(f"Atualizados com sucesso: {atualizados}"))
        self.stdout.write(self.style.WARNING(f"Falharam / Não encontrada: {total - atualizados}"))
        self.stdout.write(self.style.ERROR(f"Erros crassos: {erros}"))
