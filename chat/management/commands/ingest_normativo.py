"""
Management command para ingerir PDFs normativos no pgvector.

Uso:
    python manage.py ingest_normativo                     # ingere data/normativo/
    python manage.py ingest_normativo --dir Downloads/    # diretório customizado
    python manage.py ingest_normativo --file doc.pdf      # arquivo único
    python manage.py ingest_normativo --force             # re-indexa tudo
"""
import os
import re
import time
from pathlib import Path

import fitz  # PyMuPDF
from django.conf import settings
from django.core.management.base import BaseCommand

from chat.models import DocumentoNormativo


# --- Chunking ---

_ARTICLE_RE = re.compile(r'(?=\bArt(?:igo)?\.?\s+\d+)')
_MIN_CHUNK_CHARS = 200   # ~50 tokens
_MAX_CHUNK_CHARS = 3200  # ~800 tokens
_WINDOW_CHARS = 2800     # ~700 tokens
_OVERLAP_CHARS = 600     # ~150 tokens


def _extract_text_by_page(pdf_path: str) -> list[tuple[int, str]]:
    """Retorna [(page_number, text), ...] usando PyMuPDF."""
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        if text and text.strip():
            pages.append((i + 1, text.strip()))
    doc.close()
    return pages


def _split_by_articles(text: str) -> list[str]:
    """Divide texto em fronteiras de artigos legais."""
    parts = _ARTICLE_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _sliding_window(text: str) -> list[str]:
    """Fallback: sliding window com overlap."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + _WINDOW_CHARS
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += _WINDOW_CHARS - _OVERLAP_CHARS
    return chunks


def chunk_document(pages: list[tuple[int, str]]) -> list[dict]:
    """
    Produz chunks a partir das páginas extraídas.
    Retorna [{'texto': str, 'pagina_inicio': int, 'pagina_fim': int}, ...]
    """
    # Concatena todo o texto com marcadores de página
    full_text = ""
    page_boundaries = []  # [(char_offset, page_number), ...]
    for page_num, text in pages:
        page_boundaries.append((len(full_text), page_num))
        full_text += text + "\n\n"

    def _page_for_offset(offset: int) -> int:
        """Retorna o número da página para um dado offset de caractere."""
        page = 1
        for boundary_offset, boundary_page in page_boundaries:
            if offset >= boundary_offset:
                page = boundary_page
            else:
                break
        return page

    # Tenta split por artigos primeiro
    raw_chunks = _split_by_articles(full_text)

    # Se poucos artigos encontrados, usa sliding window
    if len(raw_chunks) <= 2:
        raw_chunks = _sliding_window(full_text)

    # Pós-processamento: merge chunks pequenos, split chunks grandes
    final_chunks = []
    buffer = ""
    for raw in raw_chunks:
        if len(raw) < _MIN_CHUNK_CHARS:
            buffer += "\n" + raw
            continue

        if buffer:
            raw = buffer + "\n" + raw
            buffer = ""

        if len(raw) > _MAX_CHUNK_CHARS:
            # Sub-divide com sliding window
            for sub in _sliding_window(raw):
                if len(sub) >= _MIN_CHUNK_CHARS:
                    final_chunks.append(sub)
        else:
            final_chunks.append(raw)

    # Flush buffer restante
    if buffer.strip():
        if final_chunks:
            final_chunks[-1] += "\n" + buffer.strip()
        else:
            final_chunks.append(buffer.strip())

    # Atribuir metadados de página
    result = []
    for chunk_text in final_chunks:
        # Encontra offset do chunk no texto completo
        offset = full_text.find(chunk_text[:100])
        if offset == -1:
            offset = 0
        end_offset = offset + len(chunk_text)

        result.append({
            'texto': chunk_text,
            'pagina_inicio': _page_for_offset(offset),
            'pagina_fim': _page_for_offset(end_offset),
        })

    return result


# --- Embedding ---

_BATCH_SIZE = 100


def _embed_in_batches(texts: list[str]) -> list[list[float]]:
    """Gera embeddings em batches usando sentence-transformers (local, sem API)."""
    from chat.integrations.vertex import embed_texts

    all_embeddings = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i:i + _BATCH_SIZE]
        embeddings = embed_texts(batch)
        all_embeddings.extend(embeddings)
    return all_embeddings


# --- Command ---

class Command(BaseCommand):
    help = "Ingere PDFs normativos no pgvector para busca RAG local."

    def add_arguments(self, parser):
        default_dir = getattr(settings, 'NORMATIVO_DIR',
                              str(Path(settings.BASE_DIR) / 'data' / 'normativo'))
        parser.add_argument(
            '--dir', type=str, default=default_dir,
            help='Diretório com os PDFs (default: data/normativo/)',
        )
        parser.add_argument(
            '--file', type=str, default=None,
            help='Arquivo PDF específico para ingerir.',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Re-indexa mesmo se o arquivo já existe no banco.',
        )

    def handle(self, *args, **options):
        directory = options['dir']
        single_file = options['file']
        force = options['force']

        if single_file:
            pdf_files = [Path(single_file)]
        else:
            dir_path = Path(directory)
            if not dir_path.exists():
                self.stderr.write(self.style.ERROR(f"Diretório não encontrado: {directory}"))
                return
            pdf_files = sorted(dir_path.glob("*.pdf"))

        if not pdf_files:
            self.stderr.write(self.style.WARNING("Nenhum PDF encontrado."))
            return

        self.stdout.write(f"Encontrados {len(pdf_files)} PDFs para processar.\n")

        total_chunks = 0
        for pdf_path in pdf_files:
            # Skip arquivos vazios/temporários
            if pdf_path.stat().st_size < 100:
                self.stdout.write(self.style.WARNING(
                    f"  SKIP (arquivo vazio): {pdf_path.name}"))
                continue

            nome = pdf_path.stem  # nome sem extensão

            # Verifica se já indexado
            if not force and DocumentoNormativo.objects.filter(nome_arquivo=nome).exists():
                self.stdout.write(f"  SKIP (já indexado): {nome}")
                continue

            self.stdout.write(f"  Processando: {pdf_path.name} ... ", ending="")

            try:
                # Extrai texto
                pages = _extract_text_by_page(str(pdf_path))
                if not pages:
                    self.stdout.write(self.style.WARNING("sem texto extraível"))
                    continue

                # Chunking
                chunks = chunk_document(pages)
                if not chunks:
                    self.stdout.write(self.style.WARNING("nenhum chunk gerado"))
                    continue

                # Embedding
                texts = [c['texto'] for c in chunks]
                embeddings = _embed_in_batches(texts)

                # Persiste no banco (delete + bulk_create para idempotência)
                DocumentoNormativo.objects.filter(nome_arquivo=nome).delete()

                objs = [
                    DocumentoNormativo(
                        nome_arquivo=nome,
                        titulo=pdf_path.name,
                        chunk_index=i,
                        pagina_inicio=c['pagina_inicio'],
                        pagina_fim=c['pagina_fim'],
                        texto=c['texto'],
                        embedding=embeddings[i],
                    )
                    for i, c in enumerate(chunks)
                ]
                DocumentoNormativo.objects.bulk_create(objs)

                total_chunks += len(objs)
                self.stdout.write(self.style.SUCCESS(
                    f"{len(objs)} chunks"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"ERRO: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"\nConcluído! {total_chunks} chunks indexados no total."))
        self.stdout.write(
            f"Total no banco: {DocumentoNormativo.objects.count()} chunks")
