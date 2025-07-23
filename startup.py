#!/usr/bin/env python3
"""
Script de inicialização para verificar dependências e configurar a aplicação VSL
"""

import sys
import os

def check_dependencies():
    """Verifica se todas as dependências estão instaladas corretamente"""
    print("🔍 Verificando dependências...")
    
    dependencies = [
        ('torch', 'PyTorch'),
        ('torchaudio', 'TorchAudio'),
        ('whisperx', 'WhisperX'),
        ('transformers', 'Transformers'),
        ('flask', 'Flask'),
        ('PIL', 'Pillow'),
        ('librosa', 'Librosa'),
        ('numpy', 'NumPy'),
        ('requests', 'Requests')
    ]
    
    missing = []
    for module, name in dependencies:
        try:
            __import__(module)
            print(f"✅ {name} - OK")
        except ImportError as e:
            print(f"❌ {name} - ERRO: {e}")
            missing.append(name)
    
    if missing:
        print(f"\n❌ Dependências faltando: {', '.join(missing)}")
        return False
    
    print("\n✅ Todas as dependências estão instaladas!")
    return True

def setup_directories():
    """Cria diretórios necessários"""
    print("\n📁 Configurando diretórios...")
    
    directories = [
        'uploads',
        'outputs', 
        'templates',
        'temp',
        'cache',
        'models'
    ]
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"✅ Criado: {directory}/")
        else:
            print(f"✅ Existe: {directory}/")

def check_system_tools():
    """Verifica ferramentas do sistema"""
    print("\n🛠️ Verificando ferramentas do sistema...")
    
    tools = [
        ('ffmpeg', 'FFmpeg para processamento de áudio')
    ]
    
    for tool, description in tools:
        if os.system(f"which {tool} > /dev/null 2>&1") == 0:
            print(f"✅ {tool} - {description}")
        else:
            print(f"⚠️ {tool} - {description} (pode afetar funcionalidades)")

def main():
    """Função principal de inicialização"""
    print("🚀 Iniciando verificação do sistema VSL...")
    print("=" * 50)
    
    # Verificar dependências Python
    if not check_dependencies():
        print("\n❌ Falha na verificação de dependências!")
        sys.exit(1)
    
    # Configurar diretórios
    setup_directories()
    
    # Verificar ferramentas do sistema
    check_system_tools()
    
    print("\n" + "=" * 50)
    print("✅ Sistema verificado com sucesso!")
    print("🎬 Iniciando aplicação VSL...")
    
    # Importar e iniciar a aplicação
    try:
        from app import app, setup_production
        
        # Configurar produção
        setup_production()
        
        # Porta do Hugging Face Spaces
        port = int(os.environ.get('PORT', 7860))
        
        print(f"🌐 Servidor iniciando na porta {port}")
        
        # Executar aplicação
        app.run(
            host='0.0.0.0',
            port=port,
            debug=False,
            threaded=True
        )
        
    except Exception as e:
        print(f"❌ Erro ao iniciar aplicação: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()