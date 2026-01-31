#!/bin/bash
# Script para ejecutar el bot de Discord

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
    echo "Copia .env.example a .env y añade tu DISCORD_TOKEN"
    exit 1
fi

# Ejecutar el bot
echo "Iniciando bot..."
python main.py
