# Multi-stage build para reduzir tamanho da imagem
FROM python:3.9-slim as builder

# Instalar dependências de build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Criar diretório de trabalho
WORKDIR /app

# Copiar requirements e instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Estágio final
FROM python:3.9-slim

# Instalar apenas dependências de runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    imagemagick \
    fonts-liberation \
    fonts-open-sans \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Configurar ImageMagick para permitir operações com PDF
RUN sed -i 's/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/' /etc/ImageMagick-6/policy.xml || true

# Criar usuário não-root para segurança
RUN useradd --create-home --shell /bin/bash app

# Definir diretório de trabalho
WORKDIR /app

# Copiar dependências Python do estágio builder
COPY --from=builder /root/.local /home/app/.local

# Copiar arquivos do projeto
COPY --chown=app:app . .

# Criar pastas necessárias com permissões corretas
RUN mkdir -p uploads outputs templates temp cache models \
    && mkdir -p /home/app/.cache/huggingface /home/app/.config/matplotlib \
    && chown -R app:app /app /home/app/.cache /home/app/.config

# Mover arquivos HTML para templates se necessário
RUN if [ -f index.html ]; then mv index.html templates/; fi && \
    if [ -f processing.html ]; then mv processing.html templates/; fi && \
    if [ -f results.html ]; then mv results.html templates/; fi && \
    if [ -f vsl.html ]; then mv vsl.html templates/; fi

# Mudança para usuário não-root
USER app

# Configurar variáveis de ambiente
ENV PATH=/home/app/.local/bin:$PATH \
    PYTHONPATH=/app \
    MPLCONFIGDIR=/home/app/.config/matplotlib \
    TRANSFORMERS_CACHE=/home/app/.cache/huggingface \
    HF_HOME=/home/app/.cache/huggingface \
    XDG_CACHE_HOME=/home/app/.cache \
    IMAGEMAGICK_BINARY=/usr/bin/convert \
    PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:128 \
    PYTHONUNBUFFERED=1

# Otimizações de performance
ENV OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    TOKENIZERS_PARALLELISM=false

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:7860/', timeout=10)" || exit 1

# Expor porta
EXPOSE 7860

# Comando para iniciar a aplicação
CMD ["python", "app.py"]
