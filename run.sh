#!/bin/bash
cd "$(dirname "$0")"

VENV_DIR="./venv"
REQUIREMENTS="requirements.txt"

# Verifica se Python3 está instalado
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 não encontrado. Instale antes de continuar."
    echo "   Ubuntu/Debian: sudo apt install python3 python3-venv"
    echo "   Arch: sudo pacman -S python"
    exit 1
fi

# Verifica se o venv existe, se não, oferece criar
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Ambiente virtual não encontrado."
    echo "   Será criado um ambiente virtual e instaladas as dependências:"
    echo "   - telethon (API do Telegram)"
    echo "   - python-dotenv"
    echo ""
    read -p "👉 Deseja instalar? (s/n): " resposta
    if [[ "$resposta" != "s" && "$resposta" != "S" ]]; then
        echo "❌ Instalação cancelada."
        exit 1
    fi
    echo ""
    echo "🔧 Criando ambiente virtual..."
    python3 -m venv "$VENV_DIR"
    echo "📥 Instalando dependências..."
    "$VENV_DIR/bin/pip" install --quiet -r "$REQUIREMENTS"
    echo "✅ Tudo instalado!"
    echo ""
fi

# Garante que dependências novas sejam instaladas
"$VENV_DIR/bin/pip" install --quiet -r "$REQUIREMENTS" 2>/dev/null

"$VENV_DIR/bin/python" telegram_downloader.py
