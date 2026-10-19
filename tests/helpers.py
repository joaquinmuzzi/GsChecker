"""Datos y utilidades compartidas por los tests de los slash commands."""

from __future__ import annotations

from discord.ext import commands as discord_commands


def _find_command(bot: discord_commands.Bot, name: str):
    for cmd in bot.tree.walk_commands():
        if cmd.name == name:
            return cmd
    raise LookupError(f"slash command '{name}' not found")


def _happy_summary() -> dict:
    return {
        "name": "Samsara",
        "level": 80,
        "race": "Draenei",
        "class": "Death Knight",
        "guild": "Newbie Ink",
        "gearScore": "N/A",
    }


def _happy_gear_data() -> list[dict]:
    slots = [
        "Head",
        "Neck",
        "Shoulder",
        "Back",
        "Chest",
        "Wrist",
        "Hands",
        "Waist",
        "Legs",
        "Feet",
        "Finger 1",
        "Finger 2",
        "Trinket 1",
        "Trinket 2",
        "Ranged",
        "Main Hand",
        "Off Hand",
        "Sigil",
        "Tabard",
    ]
    return [
        {
            "item": str(49986 + i),
            "slot": slot,
            "gems": ["0", "0", "0"],
            "ench": "0",
        }
        for i, slot in enumerate(slots)
    ]


def _happy_achievements() -> dict:
    return {
        "completed_ids": {"4531", "4604"},
        "icc_10n_bosses": 4,
        "icc_25n_bosses": 4,
        "icc_10h_bosses": 0,
        "icc_25h_bosses": 0,
        "halion_10n_achieved": False,
        "halion_10h_achieved": False,
        "halion_25n_achieved": False,
        "halion_25h_achieved": False,
        "storming_10n_achieved": True,
        "storming_10h_achieved": False,
        "storming_25n_achieved": True,
        "storming_25h_achieved": False,
    }
