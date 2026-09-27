"""Arma BiS por reino a partir de lo que realmente equipan los mejores jugadores
de cada spec en Warmane (Lordaeron tiene los jefes reforzados, Icecrown es
blizzlike, así que el BiS puede diferir entre reinos).

Dos fases, re-ejecutables:

    python -m tools.build_bis_from_armory collect --realm Lordaeron
    python -m tools.build_bis_from_armory aggregate

`collect` toma candidatos de los rankings de uwu-logs (ICC 25H) por clase/spec,
lee del armory el equipo (ítems, encantamientos, gemas), la spec activa y los
stats de cada uno, y guarda todo en data/bis_raw/<realm>.json. Guarda después
de cada personaje: si se corta, al volver a correrlo retoma donde quedó.

`aggregate` elige los jugadores con más GS de cada spec/rol y guarda en
static/bis/<realm>.json, por slot, los ítems/encantamientos más usados y los
nombres de los ítems (tooltips de Wowhead WotLK: Warmane usa los IDs originales).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import gearscore  # noqa: E402
from profile_scraper import (  # noqa: E402
    _extract_slot_name,
    _parse_character_stats_html,
    parse_slot,
)
from src.audit.auditor import _is_meta_enchant_id, _resolve_gem_item_id  # noqa: E402
from src.audit.bis_guides import HEALER_SPECS, detect_role, is_caster  # noqa: E402
from src.functions.warmane import _parse_specs_from_html  # noqa: E402

logger = logging.getLogger("gschecker.build_bis")

RAW_DIR = PROJECT_ROOT / "data" / "bis_raw"
OUT_DIR = PROJECT_ROOT / "static" / "bis"
REALMS = ("Lordaeron", "Icecrown")

# uwu-logs: class_i en orden alfabético, spec_i = orden de los árboles de talentos.
CLASSES = {
    0: ("Death Knight", ["Blood", "Frost", "Unholy"]),
    1: ("Druid", ["Balance", "Feral Combat", "Restoration"]),
    2: ("Hunter", ["Beast Mastery", "Marksmanship", "Survival"]),
    3: ("Mage", ["Arcane", "Fire", "Frost"]),
    4: ("Paladin", ["Holy", "Protection", "Retribution"]),
    5: ("Priest", ["Discipline", "Holy", "Shadow"]),
    6: ("Rogue", ["Assassination", "Combat", "Subtlety"]),
    7: ("Shaman", ["Elemental", "Enhancement", "Restoration"]),
    8: ("Warlock", ["Affliction", "Demonology", "Destruction"]),
    9: ("Warrior", ["Arms", "Fury", "Protection"]),
}
CANDIDATE_BOSSES = ("Lord Marrowgar", "Professor Putricide", "The Lich King")
# --boost: para las specs con poca muestra (tanques/healers con doble spec suelen
# estar en la otra al momento de leer el armory) se buscan más candidatos.
BOOST_BOSSES = (
    "Lord Marrowgar", "Lady Deathwhisper", "Deathbringer Saurfang", "Festergut",
    "Rotface", "Professor Putricide", "Blood Prince Council", "Blood-Queen Lana'thel",
    "Valithria Dreamwalker", "Sindragosa", "The Lich King",
)
BOOST_BELOW = 8
BOOST_MAX_FETCH = 80
MAX_REPORT_AGE_DAYS = 365
MAX_FETCH_PER_SPEC = 30
TARGET_PER_SPEC = 20
ARMORY_DELAY_S = 3.0
TOP_PLAYERS = 12  # jugadores con más GS que definen el BiS de cada spec/rol

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SESSION = requests.Session()


def _report_date(report_id: str):
    try:
        return datetime.strptime(report_id[:8], "%y-%m-%d")
    except ValueError:
        return None


def uwu_candidates(realm: str, class_i: int, spec_i: int, boost: bool = False) -> list[str]:
    """Jugadores de esa clase/spec en los rankings de ICC 25H (y 25N con
    --boost), del mejor DPS para abajo, con algún log en el último año."""
    cutoff = datetime.now() - timedelta(days=MAX_REPORT_AGE_DAYS)
    seen: dict[str, float] = {}
    bosses = BOOST_BOSSES if boost else CANDIDATE_BOSSES
    modes = ("25H", "25N") if boost else ("25H",)
    for boss, mode in ((b, m) for b in bosses for m in modes):
        payload = {
            "server": realm, "boss": boss, "mode": mode, "class_i": class_i,
            "spec_i": spec_i, "sort_by": "head-useful-dps", "limit": "100",
            "best_only": True, "externals": True,
        }
        try:
            rows = SESSION.post("https://uwu-logs.xyz/top", json=payload, timeout=30).json()
        except Exception as exc:
            logger.warning("uwu top falló %s %s: %s", realm, boss, exc)
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            date = _report_date(str(row[0]))
            name = str(row[3]).strip()
            if not name or (date and date < cutoff):
                continue
            seen[name] = max(seen.get(name, 0.0), float(row[1] or 0))
        time.sleep(1.0)
    return [n for n, _ in sorted(seen.items(), key=lambda kv: -kv[1])]


def _stat(text: str, label: str):
    m = re.search(label + r":\s*([0-9]+)", text)
    return int(m.group(1)) if m else None


def fetch_character(realm: str, name: str) -> dict | None:
    url = f"https://armory.warmane.com/character/{name}/{realm}/summary"
    resp = SESSION.get(url, headers=_HEADERS, timeout=20)
    if resp.status_code != 200:
        logger.warning("armory %s para %s/%s", resp.status_code, name, realm)
        return None
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    model = soup.find(class_="item-model")
    if model is None or not re.search(r"Level\s+80\b", soup.get_text(" ")):
        return None

    gear = []
    for i, a in enumerate(model.find_all("a")):
        item = parse_slot(a)
        item["slot"] = _extract_slot_name(a, i)
        gear.append({k: item.get(k) for k in ("slot", "item", "ench", "gems")})
    gear_ids = [g["item"] if g["item"] and str(g["item"]).isdigit() else "" for g in gear]

    stats_div = soup.find(class_="character-stats")
    stats_text = stats_div.get_text(" ", strip=True) if stats_div else ""
    specs = _parse_specs_from_html(html)
    active = next((s["name"] for s in specs if s.get("active")), None)
    stats = _parse_character_stats_html(html)
    return {
        "name": name,
        "active_spec": active,
        "gs": sum(gearscore.main(gear_ids)) if any(gear_ids) else 0,
        "dodge_pct": stats.get("dodge_pct"),
        "parry_pct": stats.get("parry_pct"),
        "hit_rating": stats.get("hit_rating"),
        "spell_hit_rating": stats.get("spell_hit_rating"),
        "expertise_rating": stats.get("expertise_rating"),
        "stamina": _stat(stats_text, "Stamina"),
        "armor": _stat(stats_text, "Armor"),
        "gear": gear,
    }


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def collect(realm: str, only_class: str | None = None, boost: bool = False) -> None:
    path = RAW_DIR / f"{realm.lower()}.json"
    raw = _load(path)
    max_fetch = BOOST_MAX_FETCH if boost else MAX_FETCH_PER_SPEC
    for class_i, (class_name, specs) in CLASSES.items():
        if only_class and class_name.lower() != only_class.lower():
            continue
        for spec_i, spec_name in enumerate(specs, start=1):
            key = f"{class_name}|{spec_name}"
            entry = raw.setdefault(key, {"tried": [], "characters": []})
            if boost and len(entry["characters"]) >= BOOST_BELOW:
                continue
            if len(entry["characters"]) >= TARGET_PER_SPEC or len(entry["tried"]) >= max_fetch:
                continue
            candidates = uwu_candidates(realm, class_i, spec_i, boost)
            logger.info("%s %s: %d candidatos en uwu-logs", realm, key, len(candidates))
            for name in candidates:
                if len(entry["characters"]) >= TARGET_PER_SPEC or len(entry["tried"]) >= max_fetch:
                    break
                if name in entry["tried"]:
                    continue
                entry["tried"].append(name)
                try:
                    char = fetch_character(realm, name)
                except Exception as exc:
                    logger.warning("fallo %s/%s: %s", name, realm, exc)
                    char = None
                if char and char["active_spec"] == spec_name:
                    entry["characters"].append(char)
                    logger.info("  [%d] %s gs=%s dodge=%s", len(entry["characters"]), name, char["gs"], char["dodge_pct"])
                _save(path, raw)
                time.sleep(ARMORY_DELAY_S)


_POOLED_SLOTS = {"Finger 1": "Finger", "Finger 2": "Finger", "Trinket 1": "Trinket", "Trinket 2": "Trinket"}
TOOLTIP_CACHE = RAW_DIR / "item_tooltips.json"
_tooltips: dict[str, dict] = {}


def item_tooltip(item_id: str) -> dict:
    """{"name", "text"} del tooltip de Wowhead WotLK, cacheado en disco."""
    if not _tooltips and TOOLTIP_CACHE.exists():
        _tooltips.update(_load(TOOLTIP_CACHE))
    if item_id not in _tooltips:
        entry = {"name": item_id, "text": ""}
        try:
            data = SESSION.get(f"https://nether.wowhead.com/wotlk/tooltip/item/{item_id}", timeout=15).json()
            entry = {"name": data.get("name") or item_id,
                     "text": re.sub(r"<[^>]+>", " ", data.get("tooltip", ""))}
        except Exception:
            pass
        _tooltips[item_id] = entry
        if len(_tooltips) % 50 == 0:
            _save(TOOLTIP_CACHE, _tooltips)
        time.sleep(0.3)
    return _tooltips[item_id]


def item_name(item_id: str) -> str:
    return item_tooltip(item_id)["name"]


_MELEE = re.compile(r"Strength|Agility|attack power|armor penetration|expertise|melee attacks", re.I)
_SPELL = re.compile(r"Intellect|spell power|mana per 5", re.I)
MISMATCH_LIMIT = 4


def wears_other_spec_gear(class_name: str, spec: str, char: dict) -> bool:
    """El armory muestra el equipo puesto, que a veces es el de la otra spec
    (ej. un paladín con Holy activo pero con el equipo de Retribution)."""
    int_spec = is_caster(class_name, spec) or (class_name, spec) in HEALER_SPECS
    wrong = 0
    for g in char["gear"]:
        if not g.get("item") or g["slot"] in ("Shirt", "Tabard"):
            continue
        text = item_tooltip(g["item"])["text"]
        melee, spell = bool(_MELEE.search(text)), bool(_SPELL.search(text))
        if int_spec and melee and not spell:
            wrong += 1
        elif not int_spec and spell and not melee:
            wrong += 1
    return wrong >= MISMATCH_LIMIT


NIGHTMARE_TEAR_ID = "49110"
_ench_labels: dict[str, str] = {}


def enchant_label(item_id: str, ench_id: str) -> str:
    """Efecto del encantamiento, leído del tooltip de Wowhead del ítem con ese
    encantamiento aplicado (Wowhead no resuelve IDs de encantamiento sueltos)."""
    if ench_id not in _ench_labels:
        label = ""
        try:
            def lines(url):
                html = SESSION.get(url, timeout=15).json().get("tooltip", "")
                return [t.strip() for t in re.sub(r"<[^>]+>", "|", html).split("|") if t.strip()]
            base = set(lines(f"https://nether.wowhead.com/wotlk/tooltip/item/{item_id}"))
            extra = [t for t in lines(f"https://nether.wowhead.com/wotlk/tooltip/item/{item_id}?ench={ench_id}") if t not in base]
            label = extra[0] if extra else ""
        except Exception:
            pass
        _ench_labels[ench_id] = label or f"encantamiento {ench_id}"
        time.sleep(0.3)
    return _ench_labels[ench_id]


def _percentile(values: list[float], pct: float) -> float:
    values = sorted(values)
    return values[int(pct * (len(values) - 1))]


def stat_caps(class_name: str, spec: str, role: str, top: list[dict]) -> list[dict]:
    """El hit/expertise que alcanzan 3 de cada 4 top del reino. Sale de los
    datos, así refleja lo que se usa en este server (buffs de raid incluidos)."""
    if role == "Tank" or (class_name, spec) in HEALER_SPECS:
        return []
    if is_caster(class_name, spec):
        wanted = [("spell_hit_rating", "hit_rating", "Hit Rating (hechizos)")]
    elif class_name == "Hunter":
        wanted = [("hit_rating", "hit_rating", "Hit Rating")]
    else:
        wanted = [("hit_rating", "hit_rating", "Hit Rating"),
                  ("expertise_rating", "expertise_rating", "Expertise Rating")]
    caps = []
    for source_key, stat_key, display in wanted:
        values = [c[source_key] for c in top if isinstance(c.get(source_key), (int, float)) and c[source_key] > 0]
        if len(values) < 5:
            continue
        value = round(_percentile(values, 0.25))
        caps.append({
            "stat_key": stat_key,
            "display_name": display,
            "cap_value": value,
            "cap_label": f"lo que tienen 3 de cada 4 top (mediana {round(_percentile(values, 0.5))})",
        })
    return caps


def build_guide(class_name: str, spec: str, role: str, chars: list[dict]) -> dict:
    top = sorted(chars, key=lambda c: -(c.get("gs") or 0))[:TOP_PLAYERS]
    items: dict[str, Counter] = {}
    enchants: dict[str, Counter] = {}
    enchant_item: dict[str, str] = {}
    metas: Counter = Counter()
    with_tear = 0
    for char in top:
        has_tear = False
        for g in char["gear"]:
            if not g.get("item") or g["slot"] in ("Shirt", "Tabard"):
                continue
            pooled = _POOLED_SLOTS.get(g["slot"], g["slot"])
            items.setdefault(pooled, Counter())[g["item"]] += 1
            if g.get("ench"):
                enchants.setdefault(pooled, Counter())[g["ench"]] += 1
                enchant_item.setdefault(g["ench"], g["item"])
            for gem in g.get("gems") or []:
                if not gem or gem == "0":
                    continue
                gem_item = _resolve_gem_item_id(gem)
                if _is_meta_enchant_id(gem) and gem_item:
                    metas[gem_item] += 1
                if gem_item == NIGHTMARE_TEAR_ID:
                    has_tear = True
        with_tear += has_tear

    n = len(top)
    slots = {}
    for pooled, counter in items.items():
        # Anillos y trinkets: dos por personaje, se aceptan los 4 más usados.
        keep = 4 if pooled in ("Finger", "Trinket") else 3
        # Los ítems de PvP (Gladiator's) no son BiS de raid aunque algún top
        # los tenga puestos.
        options = [
            {"item_id": iid, "item_name": item_name(iid), "used_by": cnt}
            for iid, cnt in counter.most_common()
            if "Gladiator's" not in item_name(iid)
        ][:keep]
        ench = enchants.get(pooled, Counter())
        # Se exige encantamiento sólo si la mayoría de los top encanta ese slot;
        # se aceptan los que usa al menos 1 de cada 4.
        common = [eid for eid, cnt in ench.most_common() if cnt >= max(2, n // 4)]
        required = common if sum(ench.values()) >= n / 2 else []
        slots[pooled] = {
            "options": options,
            "enchant_ids": required,
            "enchant_label": " / ".join(enchant_label(enchant_item[e], e) for e in required[:2]),
        }

    meta = None
    if metas:
        meta_id, meta_cnt = metas.most_common(1)[0]
        if meta_cnt >= n / 2:
            meta = {"item_id": meta_id, "name": item_name(meta_id), "used_by": meta_cnt}
    return {
        "sample_size": n,
        "gs_range": [top[-1]["gs"], top[0]["gs"]] if top else [0, 0],
        "players": [c["name"] for c in top],
        "slots": slots,
        "meta_gem": meta,
        "nightmare_tear_share": round(with_tear / n, 2) if n else 0,
        "stat_caps": stat_caps(class_name, spec, role, top),
        "equipped_items": sorted({g["item"] for c in top for g in c["gear"] if g.get("item")}),
    }


def aggregate() -> None:
    for realm in REALMS:
        raw = _load(RAW_DIR / f"{realm.lower()}.json")
        guides = {}
        for key, entry in raw.items():
            class_name, spec = key.split("|")
            by_role: dict[str, list] = {}
            for char in entry["characters"]:
                if wears_other_spec_gear(class_name, spec, char):
                    logger.info("%s %s: %s tiene puesto equipo de otra spec, se descarta", realm, key, char["name"])
                    continue
                by_role.setdefault(detect_role(class_name, spec, char), []).append(char)
            for role, chars in by_role.items():
                if len(chars) < 5:
                    logger.info("%s %s %s: sólo %d personajes, se omite", realm, key, role, len(chars))
                    continue
                label = f"{class_name}|{spec}|{role}"
                guides[label] = build_guide(class_name, spec, role, chars)
                logger.info("%s %s: %d jugadores", realm, label, guides[label]["sample_size"])
        # Nombres de todo lo que equipan los top: /ia muestra el ítem actual del
        # jugador por nombre (el HTML del armory sólo trae IDs).
        seen = sorted({i for g in guides.values() for i in g.pop("equipped_items")})
        item_names = {i: item_name(i) for i in seen}
        _save(TOOLTIP_CACHE, _tooltips)
        _save(OUT_DIR / f"{realm.lower()}.json", {
            "realm": realm,
            "generated": datetime.now().strftime("%Y-%m-%d"),
            "source": "armory.warmane.com + rankings ICC 25H de uwu-logs.xyz",
            "guides": guides,
            "item_names": item_names,
        })


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--realm", choices=REALMS, required=True)
    c.add_argument("--class", dest="only_class")
    c.add_argument("--boost", action="store_true",
                   help=f"sólo specs con menos de {BOOST_BELOW} jugadores, con más candidatos")
    sub.add_parser("aggregate")
    args = parser.parse_args()
    if args.cmd == "collect":
        collect(args.realm, args.only_class, args.boost)
    else:
        aggregate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
