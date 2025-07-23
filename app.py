from flask import Flask, render_template, request, jsonify, send_file, flash, redirect, url_for
import os
import subprocess
import json
from werkzeug.utils import secure_filename
import threading
import time
import moviepy.editor as mp
from PIL import Image, ImageDraw, ImageFont
import io
import base64
import random

app = Flask(__name__)
app.secret_key = 'transcricao_audio_key_2024'

# Configurações
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
TEMP_FOLDER = 'temp'
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'mp4', 'm4a', 'flac', 'ogg'}
ALLOWED_TRANSCRIPTION = {'json'}

# Criar pastas se não existirem
for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, TEMP_FOLDER]:
    os.makedirs(folder, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['TEMP_FOLDER'] = TEMP_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max

# Status dos processamentos
processing_status = {}

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def create_slide_image(text, width=1920, height=1080):
    """
    Cria uma imagem com o texto do slide seguindo regras VSL:
    - Fonte Open Sans 42
    - Máximo 2 linhas em 90% dos slides
    - Palavras importantes em negrito preto ou vermelho
    - Texto centralizado
    - Fundo branco
    """
    # Criar imagem com fundo branco
    img = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(img)
    
    try:
        # Tentar carregar Open Sans do sistema
        font_regular = ImageFont.truetype("/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf", 42)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/open-sans/OpenSans-Bold.ttf", 42)
    except:
        # Fallback para fonte do sistema
        try:
            font_regular = ImageFont.truetype("/usr/share/fonts/liberation/LiberationSans-Regular.ttf", 42)
            font_bold = ImageFont.truetype("/usr/share/fonts/liberation/LiberationSans-Bold.ttf", 42)
        except:
            print("Aviso: Usando fonte padrão")
            font_regular = ImageFont.load_default()
            font_bold = font_regular

    # Processar texto para identificar palavras em negrito
    words = []
    current_pos = 0
    text_without_tags = ""
    
    # Identificar tags de negrito/vermelho
    while current_pos < len(text):
        if text[current_pos:].startswith('<span class=\'bold-red\'>'):
            end_pos = text.find('</span>', current_pos)
            if end_pos != -1:
                word = text[current_pos+23:end_pos]
                words.append(('red-bold', word))
                text_without_tags += word + " "
                current_pos = end_pos + 7
                continue
        elif text[current_pos:].startswith('<span class=\'bold-black\'>'):
            end_pos = text.find('</span>', current_pos)
            if end_pos != -1:
                word = text[current_pos+25:end_pos]
                words.append(('black-bold', word))
                text_without_tags += word + " "
                current_pos = end_pos + 7
                continue
        
        if text[current_pos] == '<':
            end_pos = text.find('>', current_pos)
            if end_pos != -1:
                current_pos = end_pos + 1
                continue
                
        text_without_tags += text[current_pos]
        current_pos += 1
    
    # Quebrar texto em linhas (máximo 2)
    words_clean = text_without_tags.split()
    lines = []
    current_line = []
    max_width = width * 0.8  # 80% da largura para margens
    
    for word in words_clean:
        test_line = ' '.join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font_regular)
        line_width = bbox[2] - bbox[0]
        
        if line_width <= max_width:
            current_line.append(word)
        else:
            if len(lines) < 2:  # Máximo 2 linhas
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                break
    
    if current_line and len(lines) < 2:
        lines.append(' '.join(current_line))
    
    # Calcular altura total do texto
    total_height = 0
    line_spacing = 20  # Espaçamento entre linhas
    
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_regular)
        total_height += (bbox[3] - bbox[1]) + line_spacing
    
    # Posição inicial Y (centralizado verticalmente)
    current_y = (height - total_height) / 2
    
    # Desenhar cada linha
    for line in lines:
        # Calcular largura da linha para centralizar
        bbox = draw.textbbox((0, 0), line, font=font_regular)
        line_width = bbox[2] - bbox[0]
        current_x = (width - line_width) / 2
        
        # Desenhar palavras com formatação apropriada
        for style, word in words:
            if word in line:
                if style == 'red-bold':
                    draw.text((current_x, current_y), word, font=font_bold, fill='#dc2626')
                elif style == 'black-bold':
                    draw.text((current_x, current_y), word, font=font_bold, fill='black')
                else:
                    draw.text((current_x, current_y), word, font=font_regular, fill='black')
                
                # Mover posição X
                bbox = draw.textbbox((0, 0), word + ' ', font=font_regular)
                current_x += bbox[2] - bbox[0]
        
        current_y += bbox[3] - bbox[1] + line_spacing
    
    # Adicionar "..." no final de 90% dos slides
    if random.random() < 0.9:  # 90% de chance
        draw.text(
            (width - 60, height - 60),
            "...",
            font=font_regular,
            fill='black',
            anchor="rb"
        )
    
    return img

@app.route('/export_video', methods=['POST'])
def export_video():
    """Exporta os slides como vídeo com sincronização precisa"""
    try:
        data = request.json
        slides = data.get('slides', [])
        audio_data = data.get('audio', '')
        
        if not slides:
            return jsonify({'error': 'Nenhum slide fornecido'}), 400
            
        # Criar diretório temporário único
        temp_dir = os.path.join(app.config['TEMP_FOLDER'], str(int(time.time())))
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            # Gerar imagens dos slides
            slide_paths = []
            for i, slide in enumerate(slides):
                img = create_slide_image(slide['text'])
                path = os.path.join(temp_dir, f'slide_{i:03d}.png')
                img.save(path)
                slide_paths.append(path)
            
            # Criar vídeo dos slides com timing preciso
            clips = []
            for i, (path, slide) in enumerate(zip(slide_paths, slides)):
                # Calcular duração exata baseada nos timestamps do JSON
                if i < len(slides) - 1:
                    duration = slides[i + 1]['start'] - slide['start']
                else:
                    # Para o último slide, usar o tempo final do áudio ou um valor fixo
                    duration = 3.0  # valor padrão se não houver próximo slide
                
                # Criar clip com duração exata
                clip = mp.ImageClip(path, duration=duration)
                # Definir tempo de início exato
                clip = clip.set_start(slide['start'])
                clips.append(clip)
            
            # Concatenar clips mantendo os tempos exatos
            video = mp.CompositeVideoClip(clips)
            
            # Adicionar áudio mantendo sincronização
            if audio_data:
                # Decodificar áudio base64
                audio_bytes = base64.b64decode(audio_data.split(',')[1])
                audio_path = os.path.join(temp_dir, 'audio.mp3')
                with open(audio_path, 'wb') as f:
                    f.write(audio_bytes)
                
                # Carregar áudio e sincronizar
                audio = mp.AudioFileClip(audio_path)
                # Garantir que o vídeo tenha a mesma duração do áudio
                video = video.set_duration(audio.duration)
                video = video.set_audio(audio)
            
            # Exportar vídeo mantendo qualidade
            output_path = os.path.join(temp_dir, 'output.mp4')
            video.write_videofile(
                output_path,
                fps=30,  # Aumentar FPS para transições mais suaves
                codec='libx264',
                audio_codec='aac',
                audio_bitrate='192k',  # Melhor qualidade de áudio
                bitrate='8000k',  # Melhor qualidade de vídeo
                preset='slow'  # Melhor compressão
            )
            
            return send_file(output_path, as_attachment=True, download_name='vsl_video.mp4')
            
        finally:
            # Limpar arquivos temporários
            for path in slide_paths:
                try:
                    os.remove(path)
                except:
                    pass
            if 'audio_path' in locals():
                try:
                    os.remove(audio_path)
                except:
                    pass
            try:
                os.remove(output_path)
            except:
                pass
            try:
                os.rmdir(temp_dir)
            except:
                pass
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload_transcription', methods=['POST'])
def upload_transcription():
    """Upload de arquivo de transcrição"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Nenhum arquivo enviado'})
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Nenhum arquivo selecionado'})
        
    if file and allowed_file(file.filename, ALLOWED_TRANSCRIPTION):
        filename = secure_filename(file.filename)
        if not filename.endswith('_transcricao.json'):
            filename = filename.rsplit('.', 1)[0] + '_transcricao.json'
            
        filepath = os.path.join(app.config['OUTPUT_FOLDER'], filename)
        file.save(filepath)
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'error': 'Formato de arquivo não suportado'})

@app.route('/delete_transcription/<filename>')
def delete_transcription(filename):
    """Deleta uma transcrição"""
    try:
        filepath = os.path.join(app.config['OUTPUT_FOLDER'], filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Arquivo não encontrado'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def run_transcription(audio_path, job_id):
    """Executa a transcrição em background"""
    try:
        print(f"[{job_id}] Iniciando transcrição para {audio_path}")
        processing_status[job_id]['status'] = 'processing'
        processing_status[job_id]['message'] = 'Iniciando transcrição...'

        result = subprocess.run(
            ['python', 'transcriptor.py', audio_path],
            capture_output=True,
            text=True,
            cwd='.'
        )

        print(f"[{job_id}] Transcrição finalizada com código {result.returncode}")
        if result.stdout:
            print(f"[{job_id}] STDOUT: {result.stdout}")
        if result.stderr:
            print(f"[{job_id}] STDERR: {result.stderr}")

        base_name = os.path.splitext(os.path.basename(audio_path))[0]
        json_file = f"{base_name}_transcricao.json"

        if result.returncode == 0:
            if os.path.exists(json_file):
                output_path = os.path.join(OUTPUT_FOLDER, json_file)
                os.rename(json_file, output_path)

                processing_status[job_id]['status'] = 'completed'
                processing_status[job_id]['message'] = 'Transcrição concluída com sucesso!'
                processing_status[job_id]['output_file'] = json_file
                print(f"[{job_id}] JSON salvo em: {output_path}")
            else:
                processing_status[job_id]['status'] = 'error'
                processing_status[job_id]['message'] = 'Arquivo JSON não foi gerado'
                print(f"[{job_id}] ERRO: JSON não encontrado: {json_file}")
        else:
            processing_status[job_id]['status'] = 'error'
            processing_status[job_id]['message'] = f'Erro na transcrição: {result.stderr}'
            print(f"[{job_id}] ERRO na execução do script")

    except Exception as e:
        processing_status[job_id]['status'] = 'error'
        processing_status[job_id]['message'] = f'Erro interno: {str(e)}'
        print(f"[{job_id}] EXCEPTION: {str(e)}")

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/transcricao')
def transcricao():
    return render_template('index.html')

@app.route('/vsl')
def vsl():
    return render_template('vsl.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('Nenhum arquivo selecionado')
        return redirect(request.url)

    file = request.files['file']
    if file.filename == '':
        flash('Nenhum arquivo selecionado')
        return redirect(request.url)

    if file and allowed_file(file.filename, ALLOWED_EXTENSIONS):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Criar job ID único
        job_id = f"{int(time.time())}_{filename}"
        processing_status[job_id] = {
            'status': 'queued',
            'message': 'Aguardando processamento...',
            'filename': filename
        }

        # Iniciar transcrição em background
        thread = threading.Thread(target=run_transcription, args=(filepath, job_id))
        thread.daemon = True
        thread.start()

        return render_template('processing.html', job_id=job_id, filename=filename)

    else:
        flash('Formato de arquivo não suportado. Use: MP3, WAV, MP4, M4A, FLAC, OGG')
        return redirect(url_for('index'))

@app.route('/status/<job_id>')
def check_status(job_id):
    if job_id in processing_status:
        return jsonify(processing_status[job_id])
    else:
        return jsonify({'status': 'not_found', 'message': 'Job não encontrado'})

@app.route('/download/<filename>')
def download_file(filename):
    try:
        file_path = os.path.join(OUTPUT_FOLDER, filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            flash('Arquivo não encontrado')
            return redirect(url_for('index'))
    except Exception as e:
        flash(f'Erro ao baixar arquivo: {str(e)}')
        return redirect(url_for('index'))

@app.route('/results')
def results():
    output_files = []
    if os.path.exists(OUTPUT_FOLDER):
        for filename in os.listdir(OUTPUT_FOLDER):
            if filename.endswith('.json'):
                filepath = os.path.join(OUTPUT_FOLDER, filename)
                file_stats = os.stat(filepath)
                output_files.append({
                    'name': filename,
                    'size': round(file_stats.st_size / 1024, 2),
                    'modified': time.ctime(file_stats.st_mtime)
                })

    return render_template('results.html', files=output_files)

@app.route('/list_transcriptions')
def list_transcriptions():
    """Lista todas as transcrições disponíveis no servidor"""
    files = []
    if os.path.exists(OUTPUT_FOLDER):
        for filename in os.listdir(OUTPUT_FOLDER):
            if filename.endswith('.json'):
                file_path = os.path.join(OUTPUT_FOLDER, filename)
                stats = os.stat(file_path)
                files.append({
                    'name': filename,
                    'path': file_path,
                    'modified': stats.st_mtime * 1000 # Converter para milissegundos para JavaScript
                })
    return jsonify(files)

@app.route('/get_transcription/<filename>')
def get_transcription(filename):
    """Retorna o conteúdo de uma transcrição específica"""
    try:
        file_path = os.path.join(OUTPUT_FOLDER, filename)
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        else:
            return jsonify({'error': 'Arquivo não encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/save_transcription', methods=['POST'])
def save_transcription():
    """Salva uma transcrição editada"""
    try:
        data = request.json
        if not data or 'metadata' not in data or 'words' not in data:
            return jsonify({'success': False, 'error': 'Formato de transcrição inválido'})
            
        # Gerar nome do arquivo baseado no arquivo original
        base_name = os.path.splitext(os.path.basename(data['metadata']['arquivo']))[0]
        output_file = f"{base_name}_transcricao.json"
        output_path = os.path.join(OUTPUT_FOLDER, output_file)
        
        # Salvar arquivo
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860, debug=False)
