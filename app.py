from flask import Flask, render_template, request, jsonify, send_file, flash, redirect, url_for
import os
import subprocess
import json
from werkzeug.utils import secure_filename
import threading
import time
# import moviepy.editor as mp  # Temporariamente desabilitado
from PIL import Image, ImageDraw, ImageFont
import io
import base64
import random
import gzip
from functools import lru_cache
import concurrent.futures
import hashlib
from werkzeug.middleware.profiler import ProfilerMiddleware

app = Flask(__name__)
app.secret_key = 'transcricao_audio_key_2024'

# Performance profiling in development
if os.environ.get('FLASK_ENV') == 'development':
    app.wsgi_app = ProfilerMiddleware(app.wsgi_app)

# Production configuration with optimizations
def setup_production():
    """Configure production settings"""
    if not app.debug:
        # Setup logging
        import logging
        logging.basicConfig(level=logging.INFO)
        
        # Warm up models in background for faster first request
        if os.environ.get('WARMUP_MODELS', 'false').lower() == 'true':
            executor.submit(warmup_models)

def warmup_models():
    """Warm up models for faster first transcription"""
    try:
        from transcriptor import get_whisper_model, get_alignment_model
        print("[INFO] Warming up models...")
        get_whisper_model()
        get_alignment_model()
        print("[INFO] Models warmed up successfully")
    except Exception as e:
        print(f"[WARNING] Model warmup failed: {e}")

# Add response compression
@app.after_request
def after_request(response):
    """Add performance headers and compression"""
    # Cache static assets
    if request.endpoint and 'static' in request.endpoint:
        response.cache_control.max_age = 31536000  # 1 year
        response.cache_control.public = True
    
    # Add security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    return response

# Add memory monitoring endpoint
@app.route('/health')
def health_check():
    """Health check endpoint with system stats"""
    try:
        import psutil
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent()
        
        return jsonify({
            'status': 'healthy',
            'memory_usage': f"{memory.percent}%",
            'cpu_usage': f"{cpu}%",
            'cache_size': len(os.listdir(CACHE_FOLDER)),
            'active_jobs': len(processing_status)
        })
    except ImportError:
        return jsonify({'status': 'healthy', 'monitoring': 'unavailable'})

# Configurações
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
TEMP_FOLDER = 'temp'
CACHE_FOLDER = 'cache'
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'mp4', 'm4a', 'flac', 'ogg'}
ALLOWED_TRANSCRIPTION = {'json'}

# Criar pastas se não existirem
for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, TEMP_FOLDER, CACHE_FOLDER]:
    os.makedirs(folder, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['TEMP_FOLDER'] = TEMP_FOLDER
app.config['CACHE_FOLDER'] = CACHE_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max

# Status dos processamentos com TTL para limpeza automática
processing_status = {}
STATUS_TTL = 3600  # 1 hora

# Cache global para fontes
_font_cache = {}

# Thread pool para processamento assíncrono
executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

def cleanup_old_status():
    """Remove status antigos para evitar vazamento de memória"""
    current_time = time.time()
    expired_jobs = [
        job_id for job_id, status in processing_status.items()
        if current_time - status.get('created_at', 0) > STATUS_TTL
    ]
    for job_id in expired_jobs:
        del processing_status[job_id]

@lru_cache(maxsize=32)
def get_cached_font(font_path, size):
    """Cache otimizado para fontes"""
    try:
        return ImageFont.truetype(font_path, size)
    except:
        return ImageFont.load_default()

def get_font(font_type='regular', size=42):
    """Obter fonte com cache otimizado"""
    cache_key = f"{font_type}_{size}"
    
    if cache_key not in _font_cache:
        if font_type == 'bold':
            try:
                _font_cache[cache_key] = get_cached_font("/usr/share/fonts/truetype/open-sans/OpenSans-Bold.ttf", size)
            except:
                try:
                    _font_cache[cache_key] = get_cached_font("/usr/share/fonts/liberation/LiberationSans-Bold.ttf", size)
                except:
                    _font_cache[cache_key] = ImageFont.load_default()
        else:
            try:
                _font_cache[cache_key] = get_cached_font("/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf", size)
            except:
                try:
                    _font_cache[cache_key] = get_cached_font("/usr/share/fonts/liberation/LiberationSans-Regular.ttf", size)
                except:
                    _font_cache[cache_key] = ImageFont.load_default()
    
    return _font_cache[cache_key]

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

@lru_cache(maxsize=100)
def calculate_text_layout(text, width, height, max_lines=2):
    """Cache de layout de texto para evitar recálculos"""
    words = text.split()
    lines = []
    current_line = []
    max_width = width * 0.8
    
    font_regular = get_font('regular', 42)
    
    # Usar uma imagem temporária para cálculos
    temp_img = Image.new('RGB', (100, 100), 'white')
    temp_draw = ImageDraw.Draw(temp_img)
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = temp_draw.textbbox((0, 0), test_line, font=font_regular)
        line_width = bbox[2] - bbox[0]
        
        if line_width <= max_width:
            current_line.append(word)
        else:
            if len(lines) < max_lines:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                break
    
    if current_line and len(lines) < max_lines:
        lines.append(' '.join(current_line))
    
    return tuple(lines)  # Tuple para hashable cache

def create_slide_image(text, width=1920, height=1080):
    """
    Cria uma imagem com o texto do slide com otimizações de performance
    """
    # Cache baseado no hash do texto
    text_hash = hashlib.md5(text.encode()).hexdigest()
    cache_path = os.path.join(CACHE_FOLDER, f"slide_{text_hash}.png")
    
    # Verificar cache primeiro
    if os.path.exists(cache_path):
        return Image.open(cache_path)
    
    # Criar imagem com fundo branco
    img = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(img)
    
    # Usar fontes em cache
    font_regular = get_font('regular', 42)
    font_bold = get_font('bold', 42)

    # Usar layout em cache
    lines = calculate_text_layout(text, width, height)
    
    # Calcular altura total do texto
    total_height = 0
    line_spacing = 20
    
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_regular)
        total_height += (bbox[3] - bbox[1]) + line_spacing
    
    # Posição inicial Y (centralizado verticalmente)
    current_y = (height - total_height) / 2
    
    # Desenhar cada linha otimizado
    for line in lines:
        # Calcular largura da linha para centralizar
        bbox = draw.textbbox((0, 0), line, font=font_regular)
        line_width = bbox[2] - bbox[0]
        current_x = (width - line_width) / 2
        
        # Renderizar texto simples (otimizado)
        draw.text((current_x, current_y), line, font=font_regular, fill='black')
        current_y += bbox[3] - bbox[1] + line_spacing
    
    # Adicionar "..." no final de 90% dos slides
    if random.random() < 0.9:
        draw.text(
            (width - 60, height - 60),
            "...",
            font=font_regular,
            fill='black',
            anchor="rb"
        )
    
    # Salvar no cache
    img.save(cache_path, optimize=True, quality=85)
    
    return img

@app.route('/export_video', methods=['POST'])
def export_video():
    """Exporta os slides como vídeo - temporariamente desabilitado"""
    try:
        return jsonify({
            'error': 'Funcionalidade de exportação de vídeo temporariamente desabilitada. Use apenas transcrição por enquanto.',
            'status': 'disabled'
        }), 503
        
    except Exception as e:
        print(f"Erro na exportação de vídeo: {str(e)}")
        return jsonify({'error': f'Erro interno: {str(e)}'}), 500

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
    """Executa a transcrição em background com otimizações"""
    try:
        print(f"[{job_id}] Iniciando transcrição para {audio_path}")
        processing_status[job_id]['status'] = 'processing'
        processing_status[job_id]['message'] = 'Iniciando transcrição...'

        # Executar transcriptor de forma otimizada
        env = os.environ.copy()
        env['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:128'  # Otimizar uso de GPU
        
        result = subprocess.run(
            ['python', 'transcriptor.py', audio_path],
            capture_output=True,
            text=True,
            cwd='.',
            env=env,
            timeout=1800  # Timeout de 30 minutos
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
                
                # Otimizar JSON antes de salvar
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # Comprimir JSON se for muito grande
                    if os.path.getsize(json_file) > 100 * 1024:  # > 100KB
                        compressed_path = output_path + '.gz'
                        with gzip.open(compressed_path, 'wt', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
                        
                        # Remover arquivo original não comprimido
                        os.remove(json_file)
                        print(f"[{job_id}] JSON comprimido salvo em: {compressed_path}")
                        processing_status[job_id]['output_file'] = os.path.basename(compressed_path)
                    else:
                        # Mover arquivo sem compressão se for pequeno
                        os.rename(json_file, output_path)
                        print(f"[{job_id}] JSON salvo em: {output_path}")
                        processing_status[job_id]['output_file'] = json_file
                        
                except Exception as json_error:
                    print(f"[{job_id}] Erro ao processar JSON: {json_error}")
                    # Fallback para mover arquivo original
                    os.rename(json_file, output_path)
                    processing_status[job_id]['output_file'] = json_file

                processing_status[job_id]['status'] = 'completed'
                processing_status[job_id]['message'] = 'Transcrição concluída com sucesso!'
            else:
                processing_status[job_id]['status'] = 'error'
                processing_status[job_id]['message'] = 'Arquivo JSON não foi gerado'
                print(f"[{job_id}] ERRO: JSON não encontrado: {json_file}")
        else:
            processing_status[job_id]['status'] = 'error'
            processing_status[job_id]['message'] = f'Erro na transcrição: {result.stderr}'
            print(f"[{job_id}] ERRO na execução do script")

    except subprocess.TimeoutExpired:
        processing_status[job_id]['status'] = 'error'
        processing_status[job_id]['message'] = 'Timeout na transcrição (máximo 30 minutos)'
        print(f"[{job_id}] TIMEOUT: Transcrição excedeu 30 minutos")
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
    """Upload com otimizações e processamento assíncrono"""
    try:
        # Limpeza periódica de status antigos
        cleanup_old_status()
        
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
            
            # Salvar arquivo com verificação de espaço
            try:
                file.save(filepath)
                file_size = os.path.getsize(filepath)
                
                # Verificar se o arquivo não está corrompido
                if file_size < 1024:  # Menor que 1KB provavelmente está corrompido
                    os.remove(filepath)
                    flash('Arquivo muito pequeno ou corrompido')
                    return redirect(request.url)
                
            except Exception as save_error:
                flash(f'Erro ao salvar arquivo: {str(save_error)}')
                return redirect(request.url)
            
            # Gerar ID único para o job
            job_id = str(int(time.time() * 1000))
            
            # Adicionar status inicial
            processing_status[job_id] = {
                'status': 'queued',
                'message': 'Aguardando processamento...',
                'filename': filename,
                'created_at': time.time(),
                'file_size': file_size
            }
            
            # Submeter para processamento assíncrono usando thread pool
            future = executor.submit(run_transcription, filepath, job_id)
            processing_status[job_id]['future'] = future
            
            # Retornar URL de status para polling
            if request.headers.get('Content-Type') == 'application/json':
                return jsonify({
                    'success': True, 
                    'job_id': job_id,
                    'status_url': f'/status/{job_id}'
                })
            else:
                flash(f'Upload realizado! ID do processamento: {job_id}')
                return redirect(url_for('check_status', job_id=job_id))
        else:
            flash('Formato de arquivo não suportado')
            return redirect(request.url)
            
    except Exception as e:
        flash(f'Erro no upload: {str(e)}')
        return redirect(request.url)

@app.route('/status/<job_id>')
def check_status(job_id):
    if job_id in processing_status:
        # Atualizar TTL para manter o status
        processing_status[job_id]['created_at'] = time.time()
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
    """Retorna o conteúdo de uma transcrição com suporte a compressão"""
    try:
        # Tentar arquivo comprimido primeiro
        compressed_path = os.path.join(OUTPUT_FOLDER, filename + '.gz')
        regular_path = os.path.join(OUTPUT_FOLDER, filename)
        
        if os.path.exists(compressed_path):
            with gzip.open(compressed_path, 'rt', encoding='utf-8') as f:
                return jsonify(json.load(f))
        elif os.path.exists(regular_path):
            with open(regular_path, 'r', encoding='utf-8') as f:
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
    # Configuração para Hugging Face Spaces
    import os
    
    # Configurar produção
    setup_production()
    
    # Porta padrão do Hugging Face Spaces
    port = int(os.environ.get('PORT', 7860))
    
    # Configuração otimizada para produção
    print(f"[INFO] Starting VSL Transcription App on port {port}")
    print(f"[INFO] Debug mode: {os.environ.get('FLASK_ENV') == 'development'}")
    
    # Executar aplicação
    app.run(
        host='0.0.0.0', 
        port=port, 
        debug=False,  # Sempre False em produção
        threaded=True
    )

# Cleanup de recursos ao sair da aplicação
import atexit

def cleanup_resources():
    """Limpeza de recursos ao encerrar aplicação"""
    try:
        executor.shutdown(wait=False)
        
        # Limpar cache muito antigo (mais de 1 dia)
        import time
        current_time = time.time()
        for filename in os.listdir(CACHE_FOLDER):
            file_path = os.path.join(CACHE_FOLDER, filename)
            if os.path.isfile(file_path):
                file_age = current_time - os.path.getmtime(file_path)
                if file_age > 86400:  # 24 horas
                    try:
                        os.remove(file_path)
                    except:
                        pass
    except:
        pass

atexit.register(cleanup_resources)
