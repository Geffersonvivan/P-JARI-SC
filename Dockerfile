# Usa Python 3.12 slim, que é leve e rápido
FROM python:3.12-slim

# Variáveis de ambiente
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Instala dependências do sistema + Node.js (para compilar Tailwind CSS)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        python3-dev \
        libgl1 \
        libglib2.0-0 \
        curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copia APENAS o requirements.txt (Segredo do Cache)
# Se o requirements.txt não for modificado no push, o Docker salta a instalação pesada!
COPY requirements.txt /app/

# Instala as dependências Python
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Compila o Tailwind CSS durante o build da imagem (não no startup)
# Camada separada: só reconstrói se package*.json ou input.css mudar
COPY package.json package-lock.json tailwind.config.js /app/
RUN npm ci

# Somente DEPOIS de instalar as bibliotecas, nós copiamos o código local (views, html, etc)
COPY . /app/

# Gera o tailwind.css com todas as classes usadas pelos templates
RUN npm run build:css

# Dá permissão de execução para o script de inicialização
RUN chmod +x start.sh

# Executa o Gunicorn e as migrações usando o start.sh que já escrevemos
CMD ["bash", "start.sh"]
