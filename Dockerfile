# Use Python 3.9 como base 
FROM python:3.9-slim

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    wget \
    imagemagick \
    libmagick++-dev \
    fonts-liberation \
    fonts-open-sans \
    && rm -rf /var/lib/apt/lists/*

# Configurar ImageMagick para permitir operações com PDF
RUN sed -i 's/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/' /etc/ImageMagick-6/policy.xml || true

# Definir diretório de trabalho
WORKDIR /app

# Copiar requirements primeiro para cache melhor
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todos os arquivos do projeto
COPY . .

# Criar pastas necessárias e dar permissão total para todo o projeto
RUN mkdir -p uploads outputs templates temp \
    && mkdir -p /app/.cache/huggingface /app/.config/matplotlib \
    && chmod -R 777 /app

# Mover arquivos HTML para templates (se existirem)
RUN mv index.html templates/ 2>/dev/null || true
RUN mv processing.html templates/ 2>/dev/null || true
RUN mv results.html templates/ 2>/dev/null || true
RUN mv vsl.html templates/ 2>/dev/null || true

# =========================
# SOLUÇÃO PARA ERROS DE PERMISSÃO
# =========================
# Definir diretórios de cache e configuração para ferramentas que exigem escrita
ENV MPLCONFIGDIR=/app/.config/matplotlib
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
ENV HF_HOME=/app/.cache/huggingface
ENV XDG_CACHE_HOME=/app/.cache
ENV IMAGEMAGICK_BINARY=/usr/bin/convert

# Expor porta
EXPOSE 7860

# Comando para iniciar a aplicação
CMD ["python", "app.py"]
