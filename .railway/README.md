# Railway (Infrastructure as Code)

`railway.py` describe los servicios del proyecto `alluring-integrity`
(bot, cron, Postgres y volúmenes). Reemplaza al `railway.toml`, que Railway
deja de leer el 2026-12-01.

Railway **no** lee este archivo en cada deploy: los cambios se aplican a mano.

```bash
pip install railway-sdk   # solo en tu máquina, no va en requirements.txt
railway config plan       # ver qué cambiaría
railway config apply      # aplicarlo
```
