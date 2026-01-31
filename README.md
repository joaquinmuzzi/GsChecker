# GsChecker

Bot de Discord para consultar GearScore y logros de raids de personajes en Warmane (Lordaeron).

## Características

- Cálculo local de GearScore con tabla WotLK.
- Progreso de ICC 10/25 en Normal y Heroic (por logros de alas).
- Ruby Sanctum (Halion) en Normal y Heroic.
- Salida en embed limpio y compacto.

> Nota: el progreso de ICC se basa en logros de alas, no en conteo por boss individual.

## Requisitos

- Python 3.10+
- Token de Discord

## Instalación

1) Clonar y entrar al repo
```bash
git clone https://github.com/tuusuario/GsChecker.git
cd GsChecker
```

2) Configurar el token
```bash
cp .env.example .env
```
Editar `.env` y agregar:
```
DISCORD_TOKEN=tu_token_aqui
```

3) Instalar dependencias

**Opción A: Script**
```bash
./run.sh
```

**Opción B: Pip**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

**Opción C: Poetry**
```bash
poetry install
poetry run python main.py
```

## Uso

- `!personaje <nombre>`

El nombre se normaliza automáticamente (primera letra en mayúscula).

## Estructura

```
GsChecker/
├── main.py              # Bot de Discord
├── gearscore.py         # Cálculo de GearScore
├── profile_scraper.py   # Scraper del Armory
├── static/
│   └── GS.json          # Tabla de GearScore
├── requirements.txt     # Dependencias (pip)
├── pyproject.toml       # Dependencias (Poetry)
└── run.sh               # Script de arranque
```

## Reutilización de código

Este proyecto se apoya en la lógica y mapeos de IDs de logros del proyecto **WarmaneProfileParser** (MIT).
No se incluye el repositorio original en este proyecto; solo se reutilizan ideas y datos de mapeo.

Repositorio original: https://github.com/Ridepad/WarmaneProfileParser

Licencia del proyecto original (MIT):

```
MIT License

Copyright (c) 2020 Ridepad

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
