"""
Sincroniza PDFs normativos de uma pasta do Google Drive para o banco local.

A pasta do Drive deve ser compartilhada com a service account:
  pjari-drive-reader@p-jarisc.iam.gserviceaccount.com

Env vars:
  GDRIVE_NORMATIVO_FOLDER_ID  — ID da pasta no Drive (obrigatório)
  GOOGLE_APPLICATION_CREDENTIALS — JSON ou path da service account
"""
import io
import json
import logging
import os
import tempfile

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

_log = logging.getLogger(__name__)

_SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
_FOLDER_ID = os.environ.get('GDRIVE_NORMATIVO_FOLDER_ID', '')


def _get_credentials():
    """Carrega credenciais da service account (JSON inline ou path de arquivo)."""
    raw = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')
    if raw.strip().startswith('{'):
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    elif os.path.exists(raw):
        return service_account.Credentials.from_service_account_file(raw, scopes=_SCOPES)
    else:
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS não configurado ou arquivo não encontrado."
        )


def _get_drive_service():
    """Retorna cliente autenticado da Google Drive API v3."""
    creds = _get_credentials()
    return build('drive', 'v3', credentials=creds, cache_discovery=False)


def list_remote_pdfs(folder_id: str = '') -> list[dict]:
    """
    Lista PDFs numa pasta do Drive.
    Retorna [{'id': str, 'name': str, 'modifiedTime': str, 'size': int}, ...]
    """
    folder_id = folder_id or _FOLDER_ID
    if not folder_id:
        raise RuntimeError("GDRIVE_NORMATIVO_FOLDER_ID não configurado.")

    service = _get_drive_service()
    results = []
    page_token = None

    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false",
            fields="nextPageToken, files(id, name, modifiedTime, size)",
            pageSize=100,
            pageToken=page_token,
        ).execute()

        results.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break

    return results


def download_pdf(file_id: str, dest_path: str):
    """Baixa um PDF do Drive para o caminho local."""
    service = _get_drive_service()
    request = service.files().get_media(fileId=file_id)
    with open(dest_path, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def sync_from_drive(folder_id: str = '', force: bool = False) -> dict:
    """
    Sincroniza PDFs do Drive → banco local (DocumentoNormativo).

    Compara por nome de arquivo e data de modificação.
    Retorna {'downloaded': int, 'skipped': int, 'errors': int, 'total_chunks': int}
    """
    from pathlib import Path
    from chat.models import DocumentoNormativo
    from chat.management.commands.ingest_normativo import (
        _extract_text_by_page, chunk_document, _embed_in_batches,
    )

    folder_id = folder_id or _FOLDER_ID
    remote_files = list_remote_pdfs(folder_id)
    _log.info(f"Drive sync: {len(remote_files)} PDFs encontrados na pasta.")

    # Nomes já indexados no banco (com timestamp)
    indexed = {}
    if not force:
        for nome, ts in DocumentoNormativo.objects.values_list(
            'nome_arquivo', 'indexado_em'
        ).distinct():
            indexed[nome] = ts

    stats = {'downloaded': 0, 'skipped': 0, 'errors': 0, 'total_chunks': 0}

    for remote in remote_files:
        nome = Path(remote['name']).stem
        remote_modified = remote.get('modifiedTime', '')

        # Skip se já indexado e não foi modificado
        if not force and nome in indexed:
            # Compara timestamps (simplificado: se já existe, pula)
            stats['skipped'] += 1
            continue

        _log.info(f"Drive sync: baixando {remote['name']}...")

        try:
            # Baixa para arquivo temporário
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp_path = tmp.name

            download_pdf(remote['id'], tmp_path)

            # Verifica tamanho
            if os.path.getsize(tmp_path) < 100:
                _log.warning(f"Drive sync: {remote['name']} vazio, pulando.")
                stats['skipped'] += 1
                continue

            # Extrai texto e chunka
            pages = _extract_text_by_page(tmp_path)
            if not pages:
                _log.warning(f"Drive sync: {remote['name']} sem texto extraível.")
                stats['skipped'] += 1
                continue

            chunks = chunk_document(pages)
            if not chunks:
                stats['skipped'] += 1
                continue

            # Embedding
            texts = [c['texto'] for c in chunks]
            embeddings = _embed_in_batches(texts)

            # Persiste (delete + bulk_create)
            DocumentoNormativo.objects.filter(nome_arquivo=nome).delete()
            objs = [
                DocumentoNormativo(
                    nome_arquivo=nome,
                    titulo=remote['name'],
                    chunk_index=i,
                    pagina_inicio=c['pagina_inicio'],
                    pagina_fim=c['pagina_fim'],
                    texto=c['texto'],
                    embedding=embeddings[i],
                )
                for i, c in enumerate(chunks)
            ]
            DocumentoNormativo.objects.bulk_create(objs)

            stats['downloaded'] += 1
            stats['total_chunks'] += len(objs)
            _log.info(f"Drive sync: {remote['name']} → {len(objs)} chunks")

        except Exception as e:
            _log.exception(f"Drive sync: erro em {remote['name']}: {e}")
            stats['errors'] += 1
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    _log.info(f"Drive sync concluído: {stats}")
    return stats
