import torch
import whisperx
import json
import sys
import os
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline
import warnings
warnings.filterwarnings("ignore")

def corrigir_palavra(corretor, palavra, contexto=""):
    """Corrige uma única palavra mantendo maiúsculas/minúsculas e contexto"""
    if not palavra.strip():
        return palavra
        
    # Palavras que devem permanecer em maiúsculo
    if palavra.upper() == "CETOX":
        return "CETOX"
        
    try:
        # Preservar maiúsculas/minúsculas originais
        is_upper = palavra.isupper()
        is_title = palavra.istitle()
        
        # Usar contexto para melhor correção
        entrada = f"corrigir gramática no contexto '{contexto}': {palavra}"
        corrigida = corretor(entrada, max_length=100, do_sample=False, num_beams=1)[0]["generated_text"]
        
        # Limpar resultado
        corrigida = corrigida.replace("corrigir gramática no contexto", "").replace("'", "").strip(": .")
        
        # Restaurar maiúsculas/minúsculas
        if is_upper:
            return corrigida.upper()
        elif is_title:
            return corrigida.title()
        return corrigida
        
    except Exception as e:
        print(f"[AVISO] Erro ao corrigir palavra '{palavra}': {e}")
        return palavra

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
    
    # Gerar nome do JSON baseado no áudio
    base_name = os.path.splitext(os.path.basename(AUDIO_PATH))[0]
    OUTPUT_JSON = f"{base_name}_transcricao.json"
    
    # === CONFIGURAÇÕES ===
    LANGUAGE = "pt"
    SCORE_MINIMO = 0.4  # Reduzido para pegar mais palavras
    MODEL_NAME = "unicamp-dl/ptt5-base-portuguese-vocab"

    # === SETUP DISPOSITIVO ===
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    print(f"[INFO] Usando dispositivo: {device.upper()}")

    # === TRANSCRIÇÃO COM WHISPERX ===
    print("[INFO] Carregando modelo WhisperX...")
    model = whisperx.load_model("large-v2", device, compute_type=compute_type, language=LANGUAGE)

    print("[INFO] Carregando áudio e transcrevendo...")
    audio = whisperx.load_audio(AUDIO_PATH)
    result = model.transcribe(audio, batch_size=16)  # Aumentar batch_size para melhor precisão

    print("[INFO] Carregando modelo de alinhamento...")
    align_model, metadata = whisperx.load_align_model(language_code=LANGUAGE, device=device)

    print("[INFO] Alinhando palavras com precisão...")
    aligned = whisperx.align(result["segments"], align_model, metadata, audio, device)

    # === CORREÇÃO GRAMATICAL COM PTT5 ===
    print("[INFO] Carregando corretor gramatical...")
    try:
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model_corr = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
        corretor = pipeline("text2text-generation", model=model_corr, tokenizer=tokenizer, device=0 if device == "cuda" else -1)
        corretor_disponivel = True
    except Exception as e:
        print(f"[AVISO] Correção desativada: {e}")
        corretor_disponivel = False

    # === PROCESSAR RESULTADO FINAL ===
    print("[INFO] Processando palavras...")
    resultado = []
    
    # Primeiro, vamos juntar palavras que foram cortadas incorretamente
    words = aligned["word_segments"]
    i = 0
    while i < len(words):
        word = words[i]
        
        # Pular palavras vazias
        if not word["word"].strip():
            i += 1
            continue
            
        # Verificar se próxima palavra deve ser juntada
        if i + 1 < len(words):
            next_word = words[i + 1]
            # Se o intervalo é muito pequeno e não há pontuação entre elas
            if (next_word["start"] - word["end"]) < 0.15:  # Aumentado para pegar mais palavras juntas
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

    # Agora corrigir a gramática com contexto
    if corretor_disponivel:
        # Criar contexto para cada palavra usando palavras vizinhas
        for i, word in enumerate(resultado):
            # Pegar palavras anteriores e posteriores para contexto
            start_idx = max(0, i - 2)
            end_idx = min(len(resultado), i + 3)
            contexto = " ".join(w["word"] for w in resultado[start_idx:end_idx])
            
            # Corrigir palavra mantendo contexto
            word["word"] = corrigir_palavra(corretor, word["word"].strip(), contexto)

    # === SALVAR EM JSON ===
    output = {
        "metadata": {
            "total_words": len(resultado),
            "arquivo": AUDIO_PATH,
            "modelo": "WhisperX large-v2",
            "correcao_gramatical": corretor_disponivel
        },
        "words": [{
            "word": w["word"],
            "start": round(w["start"], 3),
            "end": round(w["end"], 3),
            "score": round(w["score"], 3)
        } for w in resultado]
    }
    
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[SUCESSO] Transcrição salva em {OUTPUT_JSON} com {len(resultado)} palavras!")
    return OUTPUT_JSON

if __name__ == "__main__":
    main()