# GsChecker

Bot de Discord para consultar personajes de Warmane (WotLK), con foco en resumen de progreso PvE, calidad de equipo y DPS por boss.

Scrapea directamente `armory.warmane.com` (HTML + API JSON) y `uwu-logs.xyz`.

## Features

- **GearScore** calculado localmente a partir de los ítems equipados (tabla WotLK).
- **Resumen de personaje** (embed) con:
  - clase / raza / nivel,
  - specs activa e inactiva con ícono,
  - guild y rango dentro de la guild,
  - progreso **ICC 10/25** (Normal y Heroic) por boss,
  - **Ruby Sanctum** (Halion) por logros The Twilight Destroyer,
  - profesiones,
  - enchants y gemas faltantes,
  - GearScore por spec (cachea el GS de cada spec en Postgres para mostrarlas todas),
  - links a Armory y UwU Logs.
- **DPS por boss** (máximo y promedio) vía uwu-logs.xyz, con overview rápido y tabla detallada.
- **Trial of the Crusader**: logros 10N / 10H / 25N / 25H.
- **Cache en memoria + Postgres** (`external_api_cache`) para reducir requests al Armory / UwU.
- **Retries con jittered backoff (3–5s)** para rate-limits Cloudflare del Armory (429 / 5xx).

## Comandos

| Comando                     | Descripción                                              | Reino               |
|-----------------------------|----------------------------------------------------------|---------------------|
| `/personaje <nombre> [reino]` | Perfil completo del personaje.                         | Configurable        |
| `/p <nombre> [reino]`        | Alias corto de `/personaje`.                            | Configurable        |
| `/dps <nombre> [spec]`       | DPS por boss desde UwU Logs.                            | Lordaeron           |
| `/ptoc <nombre>`             | Logros ToC (10N/10H/25N/25H) en tabla.                  | Lordaeron           |
| `/ping`                      | Latencia actual del bot.                                | —                   |

Reinos aceptados en `[reino]` (por defecto **Lordaeron**):

- Lordaeron
- Icecrown
- Blackrock
- Onyxia
- Frostmourne

## Instalación

Requiere Python 3.11.

```bash
git clone https://github.com/joaquinmuzzi/GsChecker.git
cd GsChecker
cp .env.example .env   # y editar
```

Variables mínimas en `.env`:

```bash
DISCORD_TOKEN=tu_token
# Opcional — habilita cache externa en Postgres
DATABASE_URL=postgres://...
# Opcional — necesario solo para /ia
GROQ_API_KEY=...
```

### Ejecutar

```bash
# A) Script (crea venv, instala deps y arranca)
./run.sh

# B) venv + pip
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py

# C) Poetry
poetry install
poetry run python main.py
```

## Deploy en Railway

El repo incluye lo necesario para correrlo como **worker**:

- `Procfile` — `worker: bash ./run_railway.sh`
- `railway.toml` — Nixpacks + restart on failure (10 reintentos)
- `run_railway.sh` — carga `.env` y ejecuta `python3 main.py`

Variables recomendadas en Railway:

- `DISCORD_TOKEN` (requerido)
- `DATABASE_URL` (opcional — pero muy recomendado para cache de GS por spec)
- `GROQ_API_KEY` (opcional — solo para `/ia`)

Este servicio es worker: no expone puerto HTTP.

## Cron: precarga de GearScore por spec

El bot depende de armory.warmane.com, que a menudo devuelve 429 (rate limit de Cloudflare). Para que `/personaje` muestre GS incluso cuando el armory está caído, un cron precarga y cachea en Postgres el GS de cada personaje **rastreado**.

### Fuentes de personajes

El cron combina dos fuentes y deduplica:

1. **`data/tracked_characters.txt`** — lista semilla editable manualmente y versionada en git. Un personaje por línea, con reino opcional después de una coma:

   ```text
   Samsara
   Algoritmo, Lordaeron
   Frodo, Icecrown
   ```

2. **Tabla `tracked_characters` en Postgres** — auto-populada por el bot cada vez que se usa un comando de personaje (`/p`, `/personaje`, `/dps`, `/ptoc`, `/ia`). Sobrevive restarts y deploys porque el filesystem de Railway es efímero.

### Setup en Railway (segundo service)

En el mismo proyecto de Railway, creá un **service nuevo** apuntando al mismo repo:

1. **Settings → Service Type**: seleccioná el mismo repo/branch que el bot
2. **Settings → Start Command**:
   ```
   python -m tools.run_scheduled_preload
   ```
3. **Settings → Cron Schedule**: `0 */12 * * *` (cada 12 horas)
4. **Settings → Restart Policy**: `Never` (el cron termina y el container se apaga)
5. **Variables**: compartí `DATABASE_URL` con el service del bot (link al mismo Postgres)

Variables opcionales del cron:

- `PRELOAD_TXT_PATH` — ruta al txt semilla (default: `data/tracked_characters.txt`)
- `PRELOAD_DEFAULT_REALM` — reino asumido cuando el txt no lo especifica (default: `Lordaeron`)
- `PRELOAD_DELAY_SECONDS` — pausa entre personajes para evitar 429 (default: `2.0`)
- `PRELOAD_MAX_CHARACTERS` — corte duro por batch (default: `0` = sin límite)

### Flujo end-to-end

1. Un usuario ejecuta `/p Samsara Lordaeron` → el bot registra `(Samsara, Lordaeron)` en `tracked_characters`.
2. A la próxima corrida del cron, `run_scheduled_preload` toma ese par, calcula GS por spec activa consultando armory, y lo guarda en `external_api_cache` con `source='character_spec_gs'`.
3. Si en el futuro el armory devuelve 429 cuando alguien consulta a Samsara, `/p` cae al cache Postgres y muestra el GS conocido en vez de `?`.

## Logging

Cada invocación de comando emite una línea estructurada en el logger `gschecker.commands`:

```text
command=p user=Frodo(123456789) guild=Durotar(987654321) character='Samsara' realm='Lordaeron'
```

Los logs van a:

- **stdout** — visibles en Railway → *Deploy Logs* (filtrando por `@level:info`).
- **`logs/bot.log`** — rotating file (2 MB × 5 backups) por si corrés local.
- **`logs/bot-errors.log`** — mismo rotating solo para `ERROR`.

Los sub-loggers heredan del logger raíz `gschecker` (configurado en `main.py`):

- `gschecker.commands` — comandos slash.
- `gschecker.warmane` — integración Armory.
- `gschecker.profile_scraper` — parsing de gear.
- `gschecker.postgres` — cache externa.

## Arquitectura

```
main.py                        # arranque, sync slash, lock de proceso, logging global
gearscore.py                   # cálculo local de GS a partir de item IDs (static/GS.json)
profile_scraper.py             # scraping HTML de armory.warmane.com (gear, enchants, gems)

src/
├── controller/
│   └── commands.py            # /personaje /p /dps /ptoc /ia /ping — orquestación
├── functions/
│   ├── warmane.py             # summary/specs/achievements/gear/stats/guild-rank
│   ├── uwu.py                 # integración uwu-logs.xyz (overview + DPS por boss)
│   ├── embeds.py              # armado de embeds y tablas monoespaciadas
│   └── cache.py               # get/set/get_stale in-memory
├── audit/
│   ├── auditor.py             # comparación equipo vs BiS guide
│   ├── bis_guides.py          # guías BiS hardcoded por class+spec
│   ├── coach.py               # resumen narrativo vía Groq
│   ├── integration.py         # bridge scraper → audit
│   └── models.py              # Pydantic models
├── db/
│   └── postgres.py            # cache externa (tabla external_api_cache)
└── schemas/
    └── constants.py           # TTLs, caches in-memory, mapeos de boss/spec

static/
├── GS.json                    # tabla WotLK: item_id → ilvl bucket → GS por slot type
├── gem_data.json              # mapeos gem enchant_id → item info
├── item_sockets_cache.json    # sockets por item_id (evita hits a evowow)
└── raid_items_extra.json      # IDs extra para precarga

tools/
├── preload_character_gs.py    # precarga GS por spec desde UwU Logs
└── preload_item_sockets_cache.py  # precarga sockets de items de raid
```

## Cache

Dos niveles:

- **In-memory** (`src/schemas/constants.py`): dicts `{key: (timestamp, value)}` por dominio (SUMMARY, GEAR, ACHIEVEMENTS, STATS, …) con TTLs entre 120 s y 300 s. Se pierde al reiniciar el proceso.
- **Postgres** (`external_api_cache`): persiste comandos completos y GS por spec (`CHARACTER_SPEC_GS_TTL = 30 días`). Requiere `DATABASE_URL`.

Al escribir cache **nunca** se persiste una respuesta vacía — sólo respuestas completas. Si el Armory falla, se cae a stale cache si existe, y si no, se retorna vacío sin envenenar el TTL.

## Diagnóstico y notas conocidas

- El Armory de Warmane responde con 429 / 5xx bajo carga; hay retry con jittered backoff 3–5 s (`_armory_get` y `_warmane_get_with_scheme_fallback`).
- `/dps` depende 100% de uwu-logs.xyz; si están lentos, el timeout es 45 s.
- El GS por spec se sirve desde Postgres una vez que el bot vio al personaje en esa spec; primera vez muestra `?` en las specs no activas.
- La API JSON del Armory (`/api/character/.../summary`) no devuelve `gearScore` — se calcula siempre localmente desde el equipo scrapeado.

## Ejemplo

![Ejemplo del bot](docs/ejemplo.jpeg)

## Code Reuse

Este proyecto reutiliza ideas y mapeos de IDs / logros inspirados en **WarmaneProfileParser** (MIT):

- <https://github.com/Ridepad/WarmaneProfileParser>

## Licencia

MIT — ver [LICENSE](LICENSE).
