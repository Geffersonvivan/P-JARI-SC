import re
import fitz  # PyMuPDF
from django.core.files.storage import default_storage
import os
import tempfile

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
            
            # Abre o PDF e lê página por página
            with fitz.open(temp_path) as doc:
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    # Retira blocos de imagens grandes para economizar RAM do worker gunicorn
                    text = page.get_text("text")
                    # Para ter o contexto exato da linha em que a data aparece
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
            print(f"Erro na extração de texto do {doc_type}: {e}")
            
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
                    
        return resultados
    
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
            
            with fitz.open(temp_path) as doc:
                text = ""
                # Lê até as 5 primeiras páginas (geralmente o AIT tá no topo)
                for page_num in range(min(5, len(doc))):
                    text += doc[page_num].get_text("text") + "\n"
                    
                lines = text.split('\n')
                
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
                            break
                            
        except Exception as e:
            print(f"Erro ao extrair infracao do documento: {e}")
            
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
