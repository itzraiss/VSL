import torch
import whisperx
import json
import sys
import os
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline
import warnings
import gc
from functools import lru_cache
warnings.filterwarnings("ignore")

# Cache global para modelos
_model_cache = {}
_device_cache = None

def get_device():
    """Detectar dispositivo disponível com cache"""
    global _device_cache
    if _device_cache is None:
        if torch.cuda.is_available():
            _device_cache = "cuda"
            print(f"[INFO] Usando GPU: {torch.cuda.get_device_name()}")
        else:
            _device_cache = "cpu"
            print("[INFO] Usando CPU")
    return _device_cache

@lru_cache(maxsize=1)
def get_whisper_model():
    """Carregar modelo WhisperX com cache"""
    if 'whisper' not in _model_cache:
        device = get_device()
        compute_type = "float16" if device == "cuda" else "int8"
        
        print("[INFO] Carregando modelo WhisperX...")
        model = whisperx.load_model(
            "large-v2", 
            device=device, 
            compute_type=compute_type,
            download_root="./models"  # Cache local
        )
        _model_cache['whisper'] = model
        print("[INFO] Modelo WhisperX carregado com sucesso")
    
    return _model_cache['whisper']

@lru_cache(maxsize=1)
def get_alignment_model():
    """Carregar modelo de alinhamento com cache"""
    if 'alignment' not in _model_cache:
        device = get_device()
        print("[INFO] Carregando modelo de alinhamento...")
        model, metadata = whisperx.load_align_model(
            language_code="pt", 
            device=device,
            model_dir="./models"  # Cache local
        )
        _model_cache['alignment'] = (model, metadata)
        print("[INFO] Modelo de alinhamento carregado")
    
    return _model_cache['alignment']

@lru_cache(maxsize=1) 
def get_correction_model():
    """Carregar modelo de correção gramatical com cache"""
    if 'correction' not in _model_cache:
        try:
            device = get_device()
            print("[INFO] Carregando modelo de correção...")
            
            # Usar modelo mais leve para melhor performance
            model_name = "unicamp-dl/ptt5-base-portuguese-vocab"
            
            tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                cache_dir="./models"
            )
            model = AutoModelForSeq2SeqLM.from_pretrained(
                model_name,
                cache_dir="./models",
                torch_dtype=torch.float16 if device == "cuda" else torch.float32
            )
            
            if device == "cuda":
                model = model.to(device)
            
            corretor = pipeline(
                "text2text-generation",
                model=model,
                tokenizer=tokenizer,
                device=0 if device == "cuda" else -1,
                max_length=512,
                batch_size=8  # Processar em lotes para eficiência
            )
            
            _model_cache['correction'] = corretor
            print("[INFO] Modelo de correção carregado")
            return corretor
            
        except Exception as e:
            print(f"[AVISO] Não foi possível carregar modelo de correção: {e}")
            _model_cache['correction'] = None
            return None
    
    return _model_cache['correction']

def corrigir_palavra(corretor, palavra, contexto=""):
    """Corrige uma única palavra mantendo maiúsculas/minúsculas e contexto - otimizado"""
    if not palavra.strip() or not corretor:
        return palavra
        
    # Palavras que devem permanecer inalteradas
    palavras_especiais = {"CETOX", "CEO", "CPF", "CNPJ", "API", "URL", "HTTP", "HTTPS"}
    if palavra.upper() in palavras_especiais:
        return palavra
        
    try:
        # Preservar maiúsculas/minúsculas originais
        is_upper = palavra.isupper()
        is_title = palavra.istitle()
        
        # Usar entrada mais simples para melhor performance
        entrada = f"corrigir: {palavra}"
        
        # Processar com timeout implícito via max_length reduzido
        resultado = corretor(
            entrada, 
            max_length=50,  # Reduzido para palavras
            do_sample=False, 
            num_beams=1,
            early_stopping=True
        )
        
        if resultado and len(resultado) > 0:
            corrigida = resultado[0]["generated_text"]
            # Limpar resultado de forma mais eficiente
            corrigida = corrigida.replace("corrigir:", "").strip(": .")
            
            # Restaurar maiúsculas/minúsculas
            if is_upper and len(corrigida) <= 5:  # Apenas para siglas/palavras curtas
                return corrigida.upper()
            elif is_title:
                return corrigida.title()
            return corrigida
        else:
            return palavra
        
    except Exception as e:
        print(f"[AVISO] Erro ao corrigir palavra '{palavra}': {e}")
        return palavra

def otimizar_memoria():
    """Limpar cache de GPU e memória"""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()

def processar_em_lotes(words, corretor, batch_size=50):
    """Processar correções em lotes para melhor eficiência"""
    if not corretor:
        return words
        
    resultado = []
    
    for i in range(0, len(words), batch_size):
        lote = words[i:i + batch_size]
        
        # Processar lote
        for word in lote:
            if word["word"].strip():
                # Criar contexto mais eficiente
                contexto_inicio = max(0, i - 2)
                contexto_fim = min(len(words), i + 3)
                contexto = " ".join(w["word"] for w in words[contexto_inicio:contexto_fim])
                
                word["word"] = corrigir_palavra(corretor, word["word"].strip(), contexto)
            
            resultado.append(word)
        
        # Limpeza de memória a cada lote
        if i % 200 == 0:  # A cada 4 lotes
            otimizar_memoria()
    
    return resultado

def main():
    # === VERIFICAR ARGUMENTOS ===
    if len(sys.argv) != 2:
        print("Uso: python transcriptor.py <arquivo_audio>")
        sys.exit(1)
    
    AUDIO_PATH = sys.argv[1]
    
    # Verificar se arquivo existe
    if not os.path.exists(AUDIO_PATH):
        print(f"[ERRO] Arquivo não encontrado: {AUDIO_PATH}")
        sys.exit(1)
    
    # Verificar tamanho do arquivo
    file_size = os.path.getsize(AUDIO_PATH)
    print(f"[INFO] Processando arquivo: {AUDIO_PATH} ({file_size / (1024*1024):.1f} MB)")
    
    # Definir arquivo de saída
    base_name = os.path.splitext(os.path.basename(AUDIO_PATH))[0]
    OUTPUT_JSON = f"{base_name}_transcricao.json"
    
    try:
        # === CARREGAR MODELOS ===
        model = get_whisper_model()
        
        # === TRANSCREVER ÁUDIO ===
        print("[INFO] Iniciando transcrição...")
        audio = whisperx.load_audio(AUDIO_PATH)
        result = model.transcribe(audio, batch_size=16)  # Otimizar batch_size
        
        print(f"[INFO] Transcrição inicial concluída. Idioma detectado: {result.get('language', 'pt')}")
        
        # === ALINHAMENTO ===
        print("[INFO] Iniciando alinhamento...")
        align_model, metadata = get_alignment_model()
        result = whisperx.align(
            result["segments"], 
            align_model, 
            metadata, 
            audio, 
            get_device(),
            return_char_alignments=False
        )
        
        print("[INFO] Alinhamento concluído")
        
        # === EXTRAIR PALAVRAS ===
        words = []
        for segment in result["segments"]:
            if "words" in segment:
                words.extend(segment["words"])
        
        print(f"[INFO] {len(words)} palavras extraídas")
        
        # === AGRUPAR PALAVRAS PRÓXIMAS ===
        resultado = []
        i = 0
        while i < len(words):
            word = words[i]
            
            # Pular palavras vazias
            if not word["word"].strip():
                i += 1
                continue
                
            # Verificar se próxima palavra deve ser juntada (otimizado)
            if i + 1 < len(words):
                next_word = words[i + 1]
                # Intervalo mais conservador para melhor qualidade
                if (next_word["start"] - word["end"]) < 0.1:
                    # Juntar palavras
                    merged_word = {
                        "word": f"{word['word']} {next_word['word']}".strip(),
                        "start": word["start"],
                        "end": next_word["end"],
                        "score": (word["score"] + next_word["score"]) / 2
                    }
                    resultado.append(merged_word)
                    i += 2
                    continue
            
            resultado.append(word)
            i += 1

        print(f"[INFO] {len(resultado)} palavras após agrupamento")
        
        # === CORREÇÃO GRAMATICAL ===
        corretor = get_correction_model()
        corretor_disponivel = corretor is not None
        
        if corretor_disponivel:
            print("[INFO] Aplicando correção gramatical...")
            resultado = processar_em_lotes(resultado, corretor)
            print("[INFO] Correção gramatical concluída")
        else:
            print("[AVISO] Correção gramatical não disponível")

        # === SALVAR EM JSON ===
        output = {
            "metadata": {
                "total_words": len(resultado),
                "arquivo": AUDIO_PATH,
                "modelo": "WhisperX large-v2",
                "correcao_gramatical": corretor_disponivel,
                "tamanho_arquivo_mb": round(file_size / (1024*1024), 2)
            },
            "words": [{
                "word": w["word"],
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
                "score": round(w.get("score", 0.0), 3)
            } for w in resultado]
        }
        
        # Salvar com compactação otimizada
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, separators=(',', ': '))

        print(f"[SUCESSO] Transcrição salva em {OUTPUT_JSON} com {len(resultado)} palavras!")
        
        # Limpeza final de memória
        otimizar_memoria()
        
        return OUTPUT_JSON
        
    except Exception as e:
        print(f"[ERRO] Falha na transcrição: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()