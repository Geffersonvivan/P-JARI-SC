import re
import logging
import fitz  # PyMuPDF
from django.core.files.storage import default_storage
import os
import tempfile

logger = logging.getLogger(__name__)

class PDFExtractor:
    """Extrai informações brutas de PDFs (como datas) mantendo o contexto."""
    
    @staticmethod
    def extract_dates_from_pdf(file_path, doc_type="Desconhecido"):
        """
        Lê o PDF e retorna uma lista de dicionários contendo a data encontrada,
        página e linha de contexto.
        
        Args:
            file_path (str): Caminho do arquivo no Django Storage.
            doc_type (str): "Autuação" ou "Consolidado" para identificar a origem.
            
        Returns:
            list: Lista de dicts com chaves 'data_bruta', 'contexto', 'documento', 'pagina'.
        """
        if not file_path or "upload_simulado" in file_path:
            return []
            
        resultados = []
        total_chars = 0
        temp_path = None

        try:
            # Baixa o arquivo do Storage para um temporário local para o PyMuPDF ler
            with default_storage.open(file_path, 'rb') as f_in:
                fd, temp_path = tempfile.mkstemp(suffix=".pdf")
                with os.fdopen(fd, 'wb') as f_out:
                    if hasattr(f_in, 'chunks'):
                        for chunk in f_in.chunks():
                            f_out.write(chunk)
                    else:
                        f_out.write(f_in.read())

            # Padrões Regex (Cobrindo diversos formatos de data solicitados)
            # - DD/MM/AAAA ou DD/MM/AA
            # - DD-MM-AAAA ou DD-MM-AA
            # - AAAA-MM-DD
            # - AAAA.MM.DD ou DD.MM.AAAA
            paterns = [
                r'\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b', # BR normal ou com hifen
                r'\b(\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})\b', # ISO
                r'\b(\d{1,2}\.\d{1,2}\.\d{2,4})\b', # Com pontos
            ]
            regex_combined = re.compile('|'.join(paterns))

            # Abre o PDF e lê página por página (captura warnings de xref para não poluir stderr)
            fitz.TOOLS.reset_mupdf_warnings()
            with fitz.open(temp_path) as doc:
                _w = fitz.TOOLS.mupdf_warnings()
                if _w:
                    import logging as _logging
                    _logging.getLogger(__name__).warning(f"PDFExtractor MuPDF ({doc_type}): {_w.strip()}")
                    # PDF com xref corrompido: page.get_text() trava em C-level ignorando time_limit
                    if "xref" in _w.lower() or "format error" in _w.lower():
                        return [], 0

                # ── 1ª passagem: extração de texto nativo ───────────────────
                page_texts = []
                for page_num in range(len(doc)):
                    text = doc[page_num].get_text("text")
                    total_chars += len(text)
                    page_texts.append(text)

                # ── OCR fallback: PDF escaneado ou texto limitado ────────────
                # Threshold elevado de 500→2000: PDFs entre 500-2000 chars têm extração
                # de datas comprometida (scan parcial). OCR via Tesseract recupera o texto.
                OCR_THRESHOLD = 2000
                if total_chars < OCR_THRESHOLD:
                    logger.info("PDFExtractor (%s): texto nativo=%d chars < %d — tentando OCR",
                                doc_type, total_chars, OCR_THRESHOLD)
                    ocr_available = True
                    ocr_total = 0
                    ocr_texts = []
                    for page_num in range(len(doc)):
                        try:
                            tp = doc[page_num].get_textpage_ocr(
                                flags=0, language='por', dpi=300, full=True
                            )
                            ocr_text = doc[page_num].get_text(textpage=tp)
                            ocr_total += len(ocr_text)
                            ocr_texts.append(ocr_text)
                        except Exception as ocr_err:
                            logger.warning("PDFExtractor OCR indisponível (%s): %s — instale tesseract-ocr", doc_type, ocr_err)
                            ocr_available = False
                            break
                    if ocr_available and ocr_total > total_chars:
                        logger.info("PDFExtractor OCR (%s): obteve %d chars", doc_type, ocr_total)
                        page_texts = ocr_texts
                        total_chars = ocr_total

                # ── 2ª passagem: extração de datas do texto final ────────────
                for page_num, text in enumerate(page_texts):
                    lines = text.split('\n')
                    for line in lines:
                        line_clean = line.strip()
                        if not line_clean:
                            continue

                        matches = regex_combined.findall(line_clean)
                        for match_group in matches:
                            # findall com multiplos padroes retorna tuplas marcando o grupo que deu hit
                            data_encontrada = next((m for m in match_group if m), None)
                            if data_encontrada:
                                 resultados.append({
                                     "data_bruta": data_encontrada,
                                     "contexto": line_clean[:150], # Limita o tamanho do contexto
                                     "documento": doc_type,
                                     "pagina": page_num + 1 # 1-indexed
                                 })

        except Exception as e:
            logger.error("Erro na extração de texto do %s: %s", doc_type, e)

        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass

        # Retorna tupla (resultados, total_chars) para detecção de legibilidade
        return resultados, total_chars
    
    @staticmethod
    def extract_infracao_from_pdf(file_path):
        """
        Extrai a descrição literal da infração do documento (normalmente o Consolidado do DETRAN).
        Procura o termo 'DESCRIÇÃO DA INFRAÇÃO' e captura as linhas seguintes que compõe o texto.
        
        Args:
            file_path (str): Caminho do arquivo no Django Storage.
            
        Returns:
            str: O texto da infração, ou None se não encontrado.
        """
        if not file_path or "upload_simulado" in file_path:
            return None
            
        temp_path = None
        infracao_encontrada = None
        
        try:
            with default_storage.open(file_path, 'rb') as f_in:
                fd, temp_path = tempfile.mkstemp(suffix=".pdf")
                with os.fdopen(fd, 'wb') as f_out:
                    if hasattr(f_in, 'chunks'):
                        for chunk in f_in.chunks():
                            f_out.write(chunk)
                    else:
                        f_out.write(f_in.read())
            
            fitz.TOOLS.reset_mupdf_warnings()
            with fitz.open(temp_path) as doc:
                _w = fitz.TOOLS.mupdf_warnings()
                if _w:
                    import logging as _logging
                    _logging.getLogger(__name__).warning(f"PDFExtractor MuPDF (infracao): {_w.strip()}")
                    if "xref" in _w.lower() or "format error" in _w.lower():
                        return None
                # Lê até as 5 primeiras páginas (geralmente o AIT tá no topo)
                pages_to_read = min(5, len(doc))
                text = ""
                for page_num in range(pages_to_read):
                    text += doc[page_num].get_text("text") + "\n"

                # OCR fallback para PDFs escaneados
                if len(text.strip()) < 500:
                    ocr_text = ""
                    for page_num in range(pages_to_read):
                        try:
                            tp = doc[page_num].get_textpage_ocr(flags=0, language='por', dpi=300, full=True)
                            ocr_text += doc[page_num].get_text(textpage=tp) + "\n"
                        except Exception:
                            break
                    if len(ocr_text.strip()) > len(text.strip()):
                        text = ocr_text
                    
                lines = text.split('\n')
                
                base_legal_encontrada = None
                
                # Procura primeiro pela Base Legal
                for i, line in enumerate(lines):
                    line_clean = line.strip()
                    if "BASE LEGAL" in line_clean.upper():
                        # A base legal costuma estar 1 linha abaixo (Ex: '165' ou '230 * XI')
                        if i + 1 < len(lines):
                            candidato = lines[i+1].strip()
                            if candidato and len(candidato) < 20 and "CÓDIGO" not in candidato.upper():
                                base_legal_encontrada = candidato
                        break

                for i, line in enumerate(lines):
                    line_clean = line.strip()
                    if "DESCRIÇÃO DA INFRAÇÃO" in line_clean.upper() or "DESCRICAO DA INFRACAO" in line_clean.upper():
                        # A descrição costuma estar na linha imediatamente abaixo ou nas 2 seguintes
                        for j in range(1, 4):
                            if i + j < len(lines):
                                proxima_linha = lines[i+j].strip()
                                # Ignora se for vazia ou for algum cabeçalho espúrio de quebra de página
                                if proxima_linha and len(proxima_linha) > 5 and "CÓDIGO" not in proxima_linha.upper() and "MUNICÍPIO" not in proxima_linha.upper() and "Consolidado gerado" not in proxima_linha:
                                     # Capturou a descrição
                                     infracao_encontrada = proxima_linha
                                     break
                        if infracao_encontrada:
                            if base_legal_encontrada:
                                infracao_encontrada = f"{base_legal_encontrada} ||| {infracao_encontrada}"
                            break
                            
        except Exception as e:
            logger.error("Erro ao extrair infracao do documento: %s", e)
            
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
                    
        return infracao_encontrada

    @staticmethod
    def format_extraction_for_llm(datas_autuacao, datas_consolidado):
        """Formata a lista bruta de dicionários em texto simples para anexar ao prompt."""
        todas_ocorrencias = datas_autuacao + datas_consolidado
        if not todas_ocorrencias:
            return "Nenhuma data localizada nos PDFs via varredura do sistema."
            
        texto = "=== DATAS EXTRAÍDAS DO DOSSIÊ (VIA PYTHON) ===\n"
        texto += "O sistema varreu os documentos e localizou as seguintes ocorrências temporais:\n\n"
        
        # Filtramos muito leve para nao estourar o limite de tokens se for absurdo
        # Limita a 200 datas max
        todas_ocorrencias = todas_ocorrencias[:200]
        
        for index, item in enumerate(todas_ocorrencias, 1):
            texto += (
                f"ID: {index} | Data: {item['data_bruta']} | "
                f"Local: ({item['documento']}/Pág {item['pagina']}) | "
                f"Frase/Contexto: '{item['contexto']}'\n"
            )
            
        return texto
