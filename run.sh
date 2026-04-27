#!/bin/bash
# Script para ejecutar el bot de Discord

# Asegura rutas relativas correctas aunque se invoque desde otro directorio
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Verificar si existe el entorno virtual
if [ ! -d "venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv venv
    source venv/bin/activate
    echo "Instalando dependencias..."
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Verificar si existe el archivo .env
if [ ! -f ".env" ]; then
    echo "ERROR: No se encontró el archivo .env"
    echo "Crea el archivo .env y añade tu DISCORD_TOKEN"
    exit 1
fi

# Cargar .env al entorno del shell antes de aplicar defaults.
set -a
source .env
set +a

# Config del bridge.
# Respeta variables ya definidas (por .env o entorno) y solo aplica defaults.
export SCRAPER_BRIDGE_URL="${SCRAPER_BRIDGE_URL:-${BRIDGE_URL:-http://127.0.0.1:8000}}"
export API_SECRET="${BRIDGE_SHARED_SECRET:-${API_SECRET:-secreto123}}"
export BRIDGE_VERIFY_SSL="${BRIDGE_VERIFY_SSL:-false}"

# Ejecutar el bot
echo "Iniciando bot..."
python main.py
