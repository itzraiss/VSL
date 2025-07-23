---
title: VSL Transcription & Video Generator
emoji: 🎬
colorFrom: purple
colorTo: gray
sdk: docker
pinned: false
license: mit
app_port: 7860
---

# VSL Transcription & Video Generator 🎬

Uma aplicação completa para transcrição de áudio e geração de vídeos VSL (Video Sales Letter) otimizada para performance.

## 🚀 Funcionalidades

- **Transcrição de Áudio**: Processamento automático com WhisperX large-v2
- **Correção Gramatical**: IA para melhorar qualidade do texto
- **Geração de Slides**: Criação automática de slides visuais
- **Exportação de Vídeo**: Sincronização de áudio com slides
- **Interface Moderna**: UI responsiva e otimizada

## 📊 Formatos Suportados

### Áudio
- MP3, WAV, MP4, M4A, FLAC, OGG
- Até 500MB por arquivo

### Saída
- JSON com timestamps precisos
- Vídeo MP4 com sincronização
- Slides PNG individuais

## 🛠 Como Usar

1. **Carregar Áudio**: Faça upload do arquivo ou cole uma URL
2. **Carregar Transcrição**: Upload do JSON ou use transcrições salvas
3. **Preview**: Visualize os slides gerados
4. **Exportar**: Gere o vídeo final sincronizado

## ⚡ Otimizações de Performance

- Cache inteligente de modelos
- Processamento paralelo
- Compressão automática
- Memória otimizada

## 📈 Monitoramento

Acesse `/health` para métricas do sistema em tempo real.

## 🔧 Tecnologias

- **Backend**: Flask + WhisperX + Transformers
- **Frontend**: HTML5 + CSS3 + JavaScript
- **IA**: PyTorch + Hugging Face
- **Container**: Docker otimizado

---

Desenvolvido com foco em performance e qualidade de transcrição.
