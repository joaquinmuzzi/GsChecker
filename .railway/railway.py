"""Infraestructura del proyecto en Railway (reemplaza al railway.toml, que
Railway deja de leer el 2026-12-01).

Railway NO lee este archivo en cada deploy: se aplica a mano con
    railway config plan    # ver diferencias
    railway config apply   # aplicarlas

Los servicios se siguen construyendo con Nixpacks, igual que con el toml.
"""
from railway_sdk import define_railway, github, postgres, preserve, project, service, volume


@define_railway
def main(ctx=None):
    repo = github("joaquinmuzzi/GsChecker", branch="master", checkSuites=False)

    db = postgres("Postgres", region="us-west2")
    db.networking = {"privateNetworkEndpoint": "postgres", "tcpProxies": {"5432": {}}}

    usage_alerts = {"usage": {"100": {}, "80": {}, "95": {}}}
    postgres_volume = volume(
        "postgres-volume-NNcI",
        {"alerts": usage_alerts, "allowOnlineResize": True, "region": "us-west2", "sizeMB": 5000},
    )
    # Volumen huérfano (no está montado en ningún servicio). Se declara para que
    # aplicar este archivo no lo borre; eliminarlo es una decisión aparte.
    mysql_volume = volume(
        "mysql-volume",
        {"alerts": usage_alerts, "allowOnlineResize": True, "region": "us-west2", "sizeMB": 5000},
    )

    cron = service(
        "GsChecker-Cron",
        source=repo,
        start="python -m tools.run_scheduled_preload",
        replicas={"us-west2": 1},
        build={"builder": "NIXPACKS"},
        deploy={"cronSchedule": "0 3 * * *", "restartPolicyType": "NEVER"},
        networking={"privateNetworkEndpoint": "gschecker-cron"},
        env={
            "DATABASE_URL": preserve(),
            "FORCE_FILTER": preserve(),
            "RAILWAY_RUN_COMMAND": preserve(),
            "START_COMMAND": preserve(),
        },
    )

    bot = service(
        "GsChecker",
        source=repo,
        replicas={"us-west2": 1},
        build={"builder": "NIXPACKS"},
        deploy={
            "limitOverride": {"containers": {"cpu": 2, "memoryBytes": 2000000000}},
            "restartPolicyType": "ON_FAILURE",
            "restartPolicyMaxRetries": 10,
        },
        networking={"privateNetworkEndpoint": "gschecker"},
        env={"DATABASE_URL": preserve(), "DISCORD_TOKEN": preserve(), "START_COMMAND": preserve()},
    )

    return project(
        "alluring-integrity",
        resources=[db, cron, bot, postgres_volume, mysql_volume],
    )
