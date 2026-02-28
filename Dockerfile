# Usa Python 3.12 slim, que é leve e rápido
FROM python:3.12-slim

# Variáveis de ambiente
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Instala dependências do sistema operacionais necessárias (como drivers de PostgreSQL e imagem para PDFs)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        python3-dev \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copia APENAS o requirements.txt (Segredo do Cache)
# Se o requirements.txt não for modificado no push, o Docker salta a instalação pesada!
COPY requirements.txt /app/

# Instala as dependências Python
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Somente DEPOIS de instalar as bibliotecas, nós copiamos o código local (views, html, etc)
COPY . /app/

# Dá permissão de execução para o script de inicialização
RUN chmod +x start.sh

# Executa o Gunicorn e as migrações usando o start.sh que já escrevemos
CMD ["bash", "start.sh"]
