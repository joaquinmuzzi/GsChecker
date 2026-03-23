import unicodedata

import discord

# Emoji usados en la tabla — forzamos ancho 2 independientemente de lo que
# devuelva unicodedata (varía según versión de Python / UCD).
_EMOJI_W2 = {
    "\u2705",  # ✅
    "\u274c",  # ❌
    "\u26a0",  # ⚠
    "\u23f3",  # ⏳
    "\u231b",  # ⌛
}


def _display_width(text: str) -> int:
    width = 0
    for ch in str(text):
        if ch == "\ufe0f":  # variation selector, no imprime
            continue
        if ch in _EMOJI_W2 or unicodedata.east_asian_width(ch) in {"W", "F"}:
            width += 2
        else:
            width += 1
    return width


def _pad(text: str, width: int) -> str:
    text = str(text)
    dw = _display_width(text)
    if dw > width:
        return text
    return text + " " * (width - dw)


def _cell(v) -> str:
    mark = "✅" if v > 0 else "❌"
    return f"{mark} {v}" if isinstance(v, int) else str(v)


def _calc_widths(rows, headers, header_labels=None) -> dict:
    header_labels = header_labels or {}
    widths = {}
    for key in headers:
        label = header_labels.get(key, key)
        max_cell = max((_display_width(row[key]) for row in rows), default=0)
        widths[key] = max(_display_width(label), max_cell)
    return widths


def _render_table(rows, headers, header_labels=None, widths=None) -> str:
    header_labels = header_labels or {}
    widths = widths or _calc_widths(rows, headers, header_labels)
    header_line = " | ".join(_pad(header_labels.get(h, h), widths[h]) for h in headers)
    total_width = sum(widths[h] for h in headers) + len(headers) * 3
    sep_line = "-" * total_width
    body_lines = [" | ".join(_pad(row[h], widths[h]) for h in headers) for row in rows]
    return "\n".join([header_line, sep_line] + body_lines)


def _format_uwu_dps_table(rows) -> str:
    headers = ["Boss", "Mode", "Raids", "Max DPS", "Avg DPS"]
    widths = _calc_widths(rows, headers)
    header_line = " | ".join(_pad(h, widths[h]) for h in headers)
    total_width = sum(widths[h] for h in headers) + len(headers) * 3
    sep_line = "-" * total_width
    body_lines = []
    for row in rows:
        if row.get("_sep"):
            body_lines.append(sep_line)
            continue
        body_lines.append(" | ".join(_pad(row[h], widths[h]) for h in headers))
    return "\n".join([header_line, sep_line] + body_lines)


def _extract_icc_boss_kills(stats_rows):
    boss_patterns = {
        "Marrowgar": ["Lord Marrowgar"],
        "Deathwhisper": ["Lady Deathwhisper"],
        "Gunship": ["Gunship Battle"],
        "Saurfang": ["Deathbringer"],
        "Festergut": ["Festergut"],
        "Rotface": ["Rotface"],
        "Putricide": ["Professor Putricide"],
        "Blood Prince": ["Blood Prince Council"],
        "Blood Queen": ["Blood Queen Lana'thel"],
        "Valithria": ["Valithria Dreamwalker"],
        "Sindragosa": ["Sindragosa"],
        "Lich King": ["Victories over the Lich King", "Lich King"],
    }

    def parse_value(val: str) -> int:
        if not val or val.strip() in {"- -", "--"}:
            return 0
        try:
            return int(val.replace(",", ""))
        except Exception:
            return 0

    icc_10 = {name: {"nm": 0, "hc": 0} for name in boss_patterns}
    icc_25 = {name: {"nm": 0, "hc": 0} for name in boss_patterns}

    for desc, val in stats_rows:
        if "Icecrown" not in desc:
            continue
        value = parse_value(val)
        if value <= 0:
            continue
        is_10 = "Icecrown 10 player" in desc
        is_25 = "Icecrown 25 player" in desc
        is_hc = "Heroic" in desc
        if not (is_10 or is_25):
            continue
        for boss_name, patterns in boss_patterns.items():
            if any(pat in desc for pat in patterns):
                if is_10:
                    key = "hc" if is_hc else "nm"
                    icc_10[boss_name][key] = max(icc_10[boss_name][key], value)
                if is_25:
                    key = "hc" if is_hc else "nm"
                    icc_25[boss_name][key] = max(icc_25[boss_name][key], value)
                break

    return icc_10, icc_25


def _extract_toc_boss_kills(stats_rows):
    boss_patterns = {
        "Beasts": ["Beasts of Northrend"],
        "Jaraxxus": ["Lord Jaraxxus"],
        "Faction Champs": ["Faction Champions"],
        "Val'kyr Twins": ["Val'kyr Twins", "Valkyr Twins"],
        "Anub'arak": ["Anub'arak", "Anubarak"],
    }

    def parse_value(val: str) -> int:
        if not val or val.strip() in {"- -", "--"}:
            return 0
        try:
            return int(val.replace(",", ""))
        except Exception:
            return 0

    toc_10 = {name: {"nm": 0, "hc": 0} for name in boss_patterns}
    toc_25 = {name: {"nm": 0, "hc": 0} for name in boss_patterns}

    for desc, val in stats_rows:
        if (
            "Trial of the Crusader" not in desc
            and "Trial of the Grand Crusader" not in desc
        ):
            continue
        if "Trial of the Champion" in desc:
            continue
        value = parse_value(val)
        if value <= 0:
            continue
        is_10 = "10 player" in desc
        is_25 = "25 player" in desc
        is_hc = "Trial of the Grand Crusader" in desc
        if not (is_10 or is_25):
            continue
        if (
            "Times completed the Trial of the Crusader" in desc
            or "Times completed the Trial of the Grand Crusader" in desc
        ):
            if is_10:
                key = "hc" if is_hc else "nm"
                toc_10["Anub'arak"][key] = max(toc_10["Anub'arak"][key], value)
            if is_25:
                key = "hc" if is_hc else "nm"
                toc_25["Anub'arak"][key] = max(toc_25["Anub'arak"][key], value)
            continue
        for boss_name, patterns in boss_patterns.items():
            if any(pat in desc for pat in patterns):
                if is_10:
                    key = "hc" if is_hc else "nm"
                    toc_10[boss_name][key] = max(toc_10[boss_name][key], value)
                if is_25:
                    key = "hc" if is_hc else "nm"
                    toc_25[boss_name][key] = max(toc_25[boss_name][key], value)
                break

    return toc_10, toc_25


def _format_boss_rows(
    bosses_10: dict, bosses_25: dict, uwu_icc_kills=None, loading_symbol="?"
):
    rows = []
    uwu_dependent_bosses = {"Marrowgar", "Deathwhisper"}
    if isinstance(uwu_icc_kills, dict):
        uwu_dependent_bosses.update(uwu_icc_kills.keys())

    for name in bosses_10.keys():
        c10 = bosses_10[name]
        c25 = bosses_25.get(name, {"nm": 0, "hc": 0})
        row = {"Boss": name}
        row["10N"] = _cell(c10["nm"])
        if name in uwu_dependent_bosses:
            if uwu_icc_kills is None:
                row["10H"] = loading_symbol
                row["25N"] = loading_symbol
                row["25H"] = loading_symbol
                rows.append(row)
                continue
            special = (uwu_icc_kills or {}).get(name, {})

            def special_cell(mode, _special=special, _loading=loading_symbol):
                value = _special.get(mode)
                if value in {"✅", "❌"}:
                    return f"{value} #"
                if value is None:
                    return _loading
                return _loading

            row["10H"] = special_cell("10H")
            row["25N"] = special_cell("25N")
            row["25H"] = special_cell("25H")
        else:
            row["10H"] = _cell(c10["hc"])
            row["25N"] = _cell(c25["nm"])
            row["25H"] = _cell(c25["hc"])
        rows.append(row)

    def header_status(values):
        if all(values):
            return "✅"
        if any(values):
            return "⚠️"
        return "❌"

    col_status = {
        "10N": header_status([bosses_10[b]["nm"] > 0 for b in bosses_10]),
        "10H": header_status([bosses_10[b]["hc"] > 0 for b in bosses_10]),
        "25N": header_status([bosses_25[b]["nm"] > 0 for b in bosses_25]),
        "25H": header_status([bosses_25[b]["hc"] > 0 for b in bosses_25]),
    }

    headers = ["Boss", "10N", "10H", "25N", "25H"]
    header_labels = {
        "10N": f"{col_status['10N']}10N",
        "10H": f"{col_status['10H']}10H",
        "25N": f"{col_status['25N']}25N",
        "25H": f"{col_status['25H']}25H",
    }
    widths = _calc_widths(rows, headers, header_labels)
    table = _render_table(rows, headers, header_labels, widths)
    return table, widths


_PROF_ABBREV = {
    "alchemy": "Alch.",
    "blacksmithing": "BS.",
    "enchanting": "Ench.",
    "engineering": "Eng.",
    "herbalism": "Herb.",
    "inscription": "Inscr.",
    "jewelcrafting": "JC.",
    "leatherworking": "LW.",
    "mining": "Mining",
    "skinning": "Skin.",
    "tailoring": "Tailor.",
}

_SPEC_ICON_URLS = {
    "arms": "https://cdn.warmane.com/wotlk/icons/medium/ability_warrior_savageblow.jpg",
    "fury": "https://cdn.warmane.com/wotlk/icons/medium/ability_warrior_innerrage.jpg",
    "protection": "https://cdn.warmane.com/wotlk/icons/medium/inv_shield_06.jpg",
    "holy": "https://cdn.warmane.com/wotlk/icons/medium/spell_holy_holybolt.jpg",
    "retribution": "https://cdn.warmane.com/wotlk/icons/medium/spell_holy_auraoflight.jpg",
    "blood": "https://cdn.warmane.com/wotlk/icons/medium/spell_deathknight_bloodpresence.jpg",
    "frost": "https://cdn.warmane.com/wotlk/icons/medium/spell_deathknight_frostpresence.jpg",
    "unholy": "https://cdn.warmane.com/wotlk/icons/medium/spell_deathknight_unholypresence.jpg",
    "balance": "https://cdn.warmane.com/wotlk/icons/medium/spell_nature_starfall.jpg",
    "feral combat": "https://cdn.warmane.com/wotlk/icons/medium/ability_racial_bearform.jpg",
    "restoration": "https://cdn.warmane.com/wotlk/icons/medium/spell_nature_healingtouch.jpg",
    "beast mastery": "https://cdn.warmane.com/wotlk/icons/medium/ability_hunter_bestialdiscipline.jpg",
    "marksmanship": "https://cdn.warmane.com/wotlk/icons/medium/ability_marksmanship.jpg",
    "survival": "https://cdn.warmane.com/wotlk/icons/medium/ability_hunter_camouflage.jpg",
    "arcane": "https://cdn.warmane.com/wotlk/icons/medium/spell_holy_magicalsentry.jpg",
    "fire": "https://cdn.warmane.com/wotlk/icons/medium/spell_fire_firebolt02.jpg",
    "discipline": "https://cdn.warmane.com/wotlk/icons/medium/spell_holy_powerwordshield.jpg",
    "shadow": "https://cdn.warmane.com/wotlk/icons/medium/spell_shadow_shadowwordpain.jpg",
    "assassination": "https://cdn.warmane.com/wotlk/icons/medium/ability_rogue_eviscerate.jpg",
    "combat": "https://cdn.warmane.com/wotlk/icons/medium/ability_backstab.jpg",
    "subtlety": "https://cdn.warmane.com/wotlk/icons/medium/ability_stealth.jpg",
    "elemental": "https://cdn.warmane.com/wotlk/icons/medium/spell_nature_lightning.jpg",
    "enhancement": "https://cdn.warmane.com/wotlk/icons/medium/spell_nature_lightningshield.jpg",
    "affliction": "https://cdn.warmane.com/wotlk/icons/medium/spell_shadow_deathcoil.jpg",
    "demonology": "https://cdn.warmane.com/wotlk/icons/medium/spell_shadow_metamorphosis.jpg",
    "destruction": "https://cdn.warmane.com/wotlk/icons/medium/spell_shadow_rainoffire.jpg",
}

_CLASS_SPEC_ICON_URLS = {
    ("paladin", "protection"): "https://cdn.warmane.com/wotlk/icons/medium/spell_holy_devotionaura.jpg",
    ("warrior", "protection"): "https://cdn.warmane.com/wotlk/icons/medium/inv_shield_06.jpg",
    ("priest", "holy"): "https://cdn.warmane.com/wotlk/icons/medium/spell_holy_guardianspirit.jpg",
    ("paladin", "holy"): "https://cdn.warmane.com/wotlk/icons/medium/spell_holy_holybolt.jpg",
    ("mage", "frost"): "https://cdn.warmane.com/wotlk/icons/medium/spell_frost_frostbolt02.jpg",
    ("death knight", "frost"): "https://cdn.warmane.com/wotlk/icons/medium/spell_deathknight_frostpresence.jpg",
    ("druid", "restoration"): "https://cdn.warmane.com/wotlk/icons/medium/spell_nature_healingtouch.jpg",
    ("shaman", "restoration"): "https://cdn.warmane.com/wotlk/icons/medium/spell_nature_magicimmunity.jpg",
}


def _format_professions_short(professions: list[str]) -> str:
    parts = []
    for prof in professions:
        tokens = prof.split(" ", 1)
        name = tokens[0]
        value = tokens[1] if len(tokens) > 1 else ""
        value = value.split("/")[0].strip()
        abbrev = _PROF_ABBREV.get(name.lower(), name)
        parts.append(f"{abbrev} {value}".strip())
    return " - ".join(parts)


def _spec_icon_url(active_spec_name: str | None, class_name: str | None = None) -> str | None:
    clean_name = str(active_spec_name or "").strip().lower()
    if not clean_name:
        return None
    clean_class_name = str(class_name or "").strip().lower()
    class_specific = _CLASS_SPEC_ICON_URLS.get((clean_class_name, clean_name))
    if class_specific:
        return class_specific
    return _SPEC_ICON_URLS.get(clean_name)


def _build_personaje_embed(
    nombre_char,
    gs,
    nivel,
    raza,
    clase,
    spec_display,
    guild_display,
    halion_10n_achieved,
    halion_10h_achieved,
    halion_25n_achieved,
    halion_25h_achieved,
    icc_10,
    icc_25,
    missing_enchants,
    missing_gems,
    uwu_icc_kills=None,
    loading_symbol="?",
    spec_gs_value: str | None = None,
    guild_rank: str | None = None,
    professions: list[str] | None = None,
    active_spec_name: str | None = None,
):
    embed = discord.Embed(color=0x2B2D31)
    icon_url = _spec_icon_url(active_spec_name, clase)
    if icon_url:
        embed.set_author(name=nombre_char, icon_url=icon_url)
    else:
        embed.title = nombre_char
    embed.add_field(name="Spec", value=spec_gs_value or str(gs), inline=True)
    prof_line = _format_professions_short(professions) if professions else ""
    race_class_value = f"{raza} {clase}"
    if prof_line:
        race_class_value += f"\n{prof_line}"
    embed.add_field(name="Class", value=race_class_value, inline=True)
    guild_value = guild_display
    clean_rank = str(guild_rank or "").strip()
    if clean_rank:
        guild_value = f"{guild_display}\n{clean_rank}"
    embed.add_field(name="Guild", value=guild_value, inline=True)

    icc_table, icc_widths = _format_boss_rows(
        icc_10, icc_25, uwu_icc_kills, loading_symbol
    )
    rs_rows = [
        {
            "Boss": "Halion",
            "10N": "✅" if halion_10n_achieved else "❌",
            "10H": "✅" if halion_10h_achieved else "❌",
            "25N": "✅" if halion_25n_achieved else "❌",
            "25H": "✅" if halion_25h_achieved else "❌",
        }
    ]

    def rs_status(done: bool) -> str:
        return "✅" if done else "❌"

    rs_table = _render_table(
        rs_rows,
        ["Boss", "10N", "10H", "25N", "25H"],
        {
            "10N": f"{rs_status(halion_10n_achieved)}10N",
            "10H": f"{rs_status(halion_10h_achieved)}10H",
            "25N": f"{rs_status(halion_25n_achieved)}25N",
            "25H": f"{rs_status(halion_25h_achieved)}25H",
        },
        icc_widths,
    )

    embed.add_field(
        name="Icecrown Citadel",
        value=f"```\n{icc_table}\n```\n",
        inline=False,
    )
    embed.add_field(
        name="Ruby Sanctum",
        value=f"```\n{rs_table}```",
        inline=False,
    )

    if missing_enchants or missing_gems:
        missing_lines = []
        if missing_enchants:
            missing_lines.append("Enchants Missing:")
            missing_lines.extend(f"- {slot}" for slot in missing_enchants)
        if missing_gems:
            missing_lines.append("Gems Missing:")
            missing_lines.extend(f"- {slot}" for slot in missing_gems)
        embed.add_field(
            name="Enchants / Gems",
            value="```\n" + "\n".join(missing_lines) + "\n```",
            inline=False,
        )

    return embed


def _build_personaje_view(nombre_char: str, server: str = "Lordaeron") -> discord.ui.View:
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label="Armory",
            url=f"https://armory.warmane.com/character/{nombre_char}/{server}/profile",
            style=discord.ButtonStyle.link,
        )
    )
    view.add_item(
        discord.ui.Button(
            label="Uwulogs",
            url=f"https://uwu-logs.xyz/character?name={nombre_char}&server={server}",
            style=discord.ButtonStyle.link,
        )
    )
    return view
