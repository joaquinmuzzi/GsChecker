from src.functions.embeds import _extract_icc_boss_kills

# Estadísticas reales de Dapko/Lordaeron en el armory (2026-09-27).
DAPKO_ROWS = [
    ["Gunship Battle victories (Icecrown 10 player)", "39"],
    ["Gunship Battle victories (Heroic Icecrown 10 player)", "38"],
    ["Gunship Battle victories (Icecrown 25 player)", "121"],
    ["Gunship Battle victories (Heroic Icecrown 25 player)", "121"],
    ["Deathbringer kills (Icecrown 10 player)", "32"],
    ["Deathbringer kills (Heroic Icecrown 10 player)", "120"],
    ["Deathbringer kills (Icecrown 25 player)", "5"],
    ["Deathbringer kills (Heroic Icecrown 25 player)", "91"],
]


def test_saurfang_heroic10_and_normal25_are_swapped_back():
    icc_10, icc_25 = _extract_icc_boss_kills(DAPKO_ROWS)

    assert icc_10["Saurfang"] == {"nm": 32, "hc": 5}
    assert icc_25["Saurfang"] == {"nm": 120, "hc": 91}
    # Nunca más Saurfangs que Gunships (mismo ala, Gunship va antes).
    for icc in (icc_10, icc_25):
        for mode in ("nm", "hc"):
            assert icc["Saurfang"][mode] <= icc["Gunship"][mode]


def test_other_bosses_are_not_swapped():
    rows = [
        ["Festergut kills (Heroic Icecrown 10 player)", "7"],
        ["Festergut kills (Icecrown 25 player)", "3"],
    ]
    icc_10, icc_25 = _extract_icc_boss_kills(rows)
    assert icc_10["Festergut"]["hc"] == 7
    assert icc_25["Festergut"]["nm"] == 3
