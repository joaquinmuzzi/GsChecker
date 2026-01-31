# GsChecker

Bot de Discord para verificar GearScore y progreso de personajes en Warmane.

## Instalación y Configuración

### 1. Clonar el repositorio
```bash
git clone https://github.com/tuusuario/GsChecker.git
cd GsChecker
```

### 2. Crear archivo de configuración
```bash
cp .env.example .env
```

Edita `.env` y añade tu token de Discord:
```
DISCORD_TOKEN=tu_token_aqui
```

### 3. Instalar dependencias

**Opción A: Script automático (recomendado)**
```bash
./run.sh
```

**Opción B: Manual con pip**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

**Opción C: Con Poetry**
```bash
poetry install
poetry run python main.py
```

### Comandos disponibles:

- `!personaje <nombre>` - Muestra el GearScore y progreso del personaje (servidor Lordaeron por defecto)
- `!personaje <nombre> <servidor>` - Muestra info del personaje en el servidor especificado

## Características

- Cálculo local de GearScore usando la tabla oficial de WotLK
- Scraping ligero del Armory de Warmane
- Muestra progreso en ICC 10/25 normal/heroico
- Detecta logros de Halion HC 10 y 25
- Fallback a la API de Warmane si el scraping falla

## Estructura del proyecto

```
GsChecker/
├── main.py              # Bot de Discord
├── gearscore.py         # Cálculo de GearScore
├── profile_scraper.py   # Scraper del Armory
├── static/
│   └── GS.json         # Tabla de GearScore
├── requirements.txt     # Dependencias (pip)
└── pyproject.toml      # Dependencias (Poetry)
```
