import unicodedata

import discord


def _display_width(text: str) -> int:
    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
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

            def special_cell(mode, _special=special):
                value = _special.get(mode)
                if value in {"✅", "❌"}:
                    return value
                if value is None:
                    return "?"
                return "?"

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
):
    embed = discord.Embed(title=nombre_char, color=0x2B2D31)
    embed.add_field(name="Spec | GS", value=spec_gs_value or str(gs), inline=True)
    embed.add_field(
        name="Level | Race | Class",
        value=f"{nivel} {raza} {clase}",
        inline=True,
    )
    guild_value = guild_display
    clean_rank = str(guild_rank or "").strip()
    if clean_rank:
        guild_value = f"{guild_display}\n{clean_rank}"
    embed.add_field(name="Guild", value=guild_value, inline=True)
    embed.add_field(
        name="Armory",
        value=f"https://armory.warmane.com/character/{nombre_char}/Lordaeron/profile",
        inline=False,
    )
    embed.add_field(
        name="Uwulogs",
        value=f"https://uwu-logs.xyz/character?name={nombre_char}&server=Lordaeron",
        inline=False,
    )

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
