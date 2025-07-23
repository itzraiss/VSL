# Multi-stage build para reduzir tamanho da imagem
FROM python:3.9-slim as builder

# Instalar dependências de sistema necessárias para build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    wget \
    pkg-config \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Atualizar pip para versão mais recente
RUN pip install --upgrade pip

# Criar diretório de trabalho
WORKDIR /app

# Copiar requirements e instalar dependências Python
COPY requirements.txt .

# Instalar dependências com resolução de conflitos otimizada
RUN pip install --no-cache-dir --user --no-warn-script-location -r requirements.txt

# Estágio final
FROM python:3.9-slim

# Instalar apenas dependências de runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    fonts-liberation \
    fonts-open-sans \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

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

# Tornar o script de startup executável
RUN chmod +x startup.py

# Mudança para usuário não-root
USER app

# Configurar variáveis de ambiente
ENV PATH=/home/app/.local/bin:$PATH \
    PYTHONPATH=/app \
    MPLCONFIGDIR=/home/app/.config/matplotlib \
    TRANSFORMERS_CACHE=/home/app/.cache/huggingface \
    HF_HOME=/home/app/.cache/huggingface \
    XDG_CACHE_HOME=/home/app/.cache \
    PYTHONUNBUFFERED=1

# Otimizações de performance
ENV OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    TOKENIZERS_PARALLELISM=false

# Expor porta (Hugging Face Spaces usa a porta 7860)
EXPOSE 7860

# Comando para iniciar a aplicação com verificação (compatível com Hugging Face Spaces)
CMD ["python", "startup.py"]
