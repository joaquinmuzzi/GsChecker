"""
Pre-defined BiS guides for WoW WotLK 3.3.5a (ICC patch).

Each entry in ``BIS_GUIDES`` corresponds to a spec and contains:
  • slot-by-slot best / acceptable items
  • required enchant IDs per slot
  • stat caps that must be reached
  • gem requirements (Nightmare Tear for meta activation, etc.)

Enchant IDs are the armory *spell* IDs (the ``ench`` field in the armory
payload), not the item IDs of the enchant scroll.

────────────────────────────────────────────────────────────────────────────
Gem item IDs referenced across guides
────────────────────────────────────────────────────────────────────────────
  44342 – Nightmare Tear              (+10 all stats, prismatic)
  40111 – Bold Cardinal Ruby          (+20 Strength, red)
  40117 – Fractured Cardinal Ruby     (+20 Armor Penetration, red)
  40112 – Delicate Cardinal Ruby      (+20 Agility, red)
  40119 – Rigid King's Amber          (+20 Hit Rating, yellow)
  40125 – Potent Ametrine             (+10 Spell Power / +10 Crit, orange)
  40113 – Brilliant King's Amber      (+20 Intellect, yellow)
  40116 – Lustrous Eye of Zul         (+9 mp5, blue)
  41285 – Chaotic Skyflare Diamond    (meta: +21 crit dmg, req 2 red > blue)
  41333 – Relentless Earthsiege Diam  (meta: +21 agi / 3 % shield)
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from .models import (
    BisGuide,
    BisItemOption,
    BisSlot,
    GemRequirement,
    StatCap,
)


# ░░░░░░░░░░░░░░░░░░░░░  WARRIOR – FURY (ArP build)  ░░░░░░░░░░░░░░░░░░░░░░░

_WARRIOR_FURY_ARP: BisGuide = BisGuide(
    spec_name="Warrior Fury",
    char_class="Warrior",
    spec="Fury",
    meta_gem_id="41285",            # Chaotic Skyflare Diamond
    nightmare_tear_required=True,   # one blue socket → Nightmare Tear
    priority_note=(
        "ArP build. With Needle-Encrusted Scorpion equipped you reach 100% ArP "
        "on proc. Prioritise hit (8 %) and expertise (26) before any other stat. "
        "gem Fractured Cardinal Ruby in all red sockets except one blue socket "
        "where Nightmare Tear must go to satisfy the Chaotic Skyflare Diamond "
        "meta requirement."
    ),
    slots={
        "Head": BisSlot(
            slot="Head",
            options=[
                BisItemOption(item_id="51253", item_name="Sanctified Ymirjar Lord's Helmet",      tier_note="ICC 25H T10.277"),
                BisItemOption(item_id="50975", item_name="Ymirjar Lord's Helmet",                 tier_note="ICC 25N T10.251"),
            ],
            required_enchant_ids=["3817"],
            enchant_display_name="Arcanum of Torment",
        ),
        "Neck": BisSlot(
            slot="Neck",
            options=[
                BisItemOption(item_id="50682", item_name="Penumbra Pendant",            tier_note="ICC 25H Lady Deathwhisper"),
                BisItemOption(item_id="50399", item_name="Precious's Putrid Collar",    tier_note="ICC 25H Rotface"),
            ],
        ),
        "Shoulder": BisSlot(
            slot="Shoulder",
            options=[
                BisItemOption(item_id="51257", item_name="Sanctified Ymirjar Lord's Shoulderplates", tier_note="ICC 25H T10.277"),
                BisItemOption(item_id="50976", item_name="Ymirjar Lord's Shoulderplates",            tier_note="ICC 25N T10.251"),
            ],
            required_enchant_ids=["3875"],
            enchant_display_name="Greater Inscription of the Axe",
        ),
        "Back": BisSlot(
            slot="Back",
            options=[
                BisItemOption(item_id="50466", item_name="Shadowvault Slayer's Cloak", tier_note="ICC 25H Marrowgar"),
                BisItemOption(item_id="47215", item_name="Might of the Ocean Serpent",  tier_note="BoE crafted"),
            ],
            required_enchant_ids=["3605", "2938"],
            enchant_display_name="Enchant Cloak – Speed / Major Agility",
        ),
        "Chest": BisSlot(
            slot="Chest",
            options=[
                BisItemOption(item_id="51255", item_name="Sanctified Ymirjar Lord's Battleplate", tier_note="ICC 25H T10.277"),
                BisItemOption(item_id="50977", item_name="Ymirjar Lord's Battleplate",            tier_note="ICC 25N T10.251"),
            ],
            required_enchant_ids=["3832"],
            enchant_display_name="Enchant Chest – Powerful Stats",
        ),
        "Wrist": BisSlot(
            slot="Wrist",
            options=[
                BisItemOption(item_id="50303", item_name="Toskk's Maximized Wristguards",  tier_note="ICC 25H Putricide"),
                BisItemOption(item_id="50698", item_name="Polar Bear Claw Bracers",         tier_note="ICC 25H Saurfang"),
            ],
            required_enchant_ids=["3845"],
            enchant_display_name="Enchant Bracer – Greater Assault",
        ),
        "Hands": BisSlot(
            slot="Hands",
            options=[
                BisItemOption(item_id="51256", item_name="Sanctified Ymirjar Lord's Gauntlets", tier_note="ICC 25H T10.277"),
                BisItemOption(item_id="50978", item_name="Ymirjar Lord's Gauntlets",            tier_note="ICC 25N T10.251"),
            ],
            required_enchant_ids=["3603"],
            enchant_display_name="Enchant Gloves – Crusher",
        ),
        "Waist": BisSlot(
            slot="Waist",
            options=[
                BisItemOption(item_id="50628", item_name="Astrylian's Sutured Cinch",   tier_note="ICC 25H Blood-Queen"),
                BisItemOption(item_id="50618", item_name="Coldwraith Links",             tier_note="ICC 25H Lana'thel"),
            ],
        ),
        "Legs": BisSlot(
            slot="Legs",
            options=[
                BisItemOption(item_id="51258", item_name="Sanctified Ymirjar Lord's Legplates", tier_note="ICC 25H T10.277"),
                BisItemOption(item_id="50979", item_name="Ymirjar Lord's Legplates",            tier_note="ICC 25N T10.251"),
            ],
            required_enchant_ids=["3822"],
            enchant_display_name="Icescale Leg Armor",
        ),
        "Feet": BisSlot(
            slot="Feet",
            options=[
                BisItemOption(item_id="50387", item_name="Apocalypse's Advance",       tier_note="ICC 25H LK"),
                BisItemOption(item_id="50609", item_name="Frostbitten Fur Boots",       tier_note="ICC 25H Sindragosa"),
            ],
            required_enchant_ids=["3826", "2940"],
            enchant_display_name="Enchant Boots – Greater Assault / Cat's Swiftness",
        ),
        "Finger 1": BisSlot(
            slot="Finger 1",
            options=[
                BisItemOption(item_id="50398", item_name="Ashen Band of Endless Might", tier_note="Ashen Verdict exalted"),
                BisItemOption(item_id="50377", item_name="Sovereign's Mark of Dominance", tier_note="ICC 25H Saurfang"),
            ],
        ),
        "Finger 2": BisSlot(
            slot="Finger 2",
            options=[
                BisItemOption(item_id="50377", item_name="Sovereign's Mark of Dominance", tier_note="ICC 25H Saurfang"),
                BisItemOption(item_id="50370", item_name="Band of the Bone Colossus",      tier_note="ICC 25H Marrowgar"),
            ],
        ),
        "Trinket 1": BisSlot(
            slot="Trinket 1",
            options=[
                BisItemOption(item_id="50362", item_name="Deathbringer's Will",         tier_note="ICC 25H Saurfang"),
            ],
        ),
        "Trinket 2": BisSlot(
            slot="Trinket 2",
            options=[
                BisItemOption(item_id="50453", item_name="Needle-Encrusted Scorpion",   tier_note="FoS Heroic (100% ArP proc)"),
                BisItemOption(item_id="50340", item_name="Whispering Fanged Skull",      tier_note="ICC 25H LK"),
            ],
        ),
        "Main Hand": BisSlot(
            slot="Main Hand",
            options=[
                BisItemOption(item_id="49623", item_name="Shadowmourne",                 tier_note="Legendary – ICC"),
                BisItemOption(item_id="50415", item_name="Bryntroll, the Bone Arbiter",  tier_note="ICC 25H LK"),
                BisItemOption(item_id="50185", item_name="Bloodfall",                    tier_note="ICC 25H PP"),
            ],
            required_enchant_ids=["3789"],
            enchant_display_name="Enchant Weapon – Berserking",
        ),
        "Off Hand": BisSlot(
            slot="Off Hand",
            options=[
                BisItemOption(item_id="50415", item_name="Bryntroll, the Bone Arbiter",       tier_note="ICC 25H LK"),
                BisItemOption(item_id="50412", item_name="Cryptmaker",                        tier_note="ICC 25H LK"),
                BisItemOption(item_id="50730", item_name="Glorenzelg, High-Blade of the Silver Hand", tier_note="ICC 25H LK"),
            ],
            required_enchant_ids=["3789"],
            enchant_display_name="Enchant Weapon – Berserking",
        ),
        "Ranged": BisSlot(
            slot="Ranged",
            options=[
                BisItemOption(item_id="50638", item_name="Rowan's Rifle of Silver Bullets", tier_note="ICC 25H Sindragosa"),
                BisItemOption(item_id="50434", item_name="Hellion Glaive",                  tier_note="ICC 25H Halion"),
            ],
            required_enchant_ids=["3607"],
            enchant_display_name="Heartseeker Scope",
        ),
    },
    stat_caps=[
        StatCap(
            stat_key="hit_rating",
            display_name="Hit Rating",
            cap_value=262,
            cap_label="8% hit cap (262)",
            must_reach=True,
        ),
        StatCap(
            stat_key="expertise_rating",
            display_name="Expertise Rating",
            cap_value=214,
            cap_label="Expertise soft cap (26 exp / 214 rating)",
            must_reach=True,
        ),
        StatCap(
            stat_key="armor_penetration_rating",
            display_name="Armor Penetration",
            cap_value=1400,
            cap_label="100% ArP cap on NES proc (1400)",
            must_reach=True,
        ),
    ],
    gem_requirements=[
        GemRequirement(
            gem_item_id="41285",
            gem_name="Chaotic Skyflare Diamond",
            required_count=1,
            description="Mandatory meta gem: +21% critical damage bonus",
        ),
        GemRequirement(
            gem_item_id="44342",
            gem_name="Nightmare Tear",
            required_count=1,
            description=(
                "Prismatic gem placed in one blue socket to satisfy the "
                "Chaotic Skyflare Diamond 2-red-vs-blue requirement without "
                "losing DPS gem slots."
            ),
        ),
        GemRequirement(
            gem_item_id="40117",
            gem_name="Fractured Cardinal Ruby",
            required_count=6,  # minimum — fill every remaining red/prismatic socket
            description="Primary DPS gem for the ArP build (+20 Armor Penetration).",
        ),
    ],
)


# ░░░░░░░░░░░░░░░░░░░░░  DEATH KNIGHT – BLOOD DPS  ░░░░░░░░░░░░░░░░░░░░░░░░░

_DK_BLOOD_DPS: BisGuide = BisGuide(
    spec_name="Death Knight Blood",
    char_class="Death Knight",
    spec="Blood",
    meta_gem_id="41285",
    nightmare_tear_required=True,
    priority_note=(
        "Blood DPS. Prioritise hit (8 %) and expertise (26). "
        "ArP softcap ~722 without a proc trinket. Use Fractured Cardinal Ruby "
        "above that threshold; Bold Cardinal Ruby below it."
    ),
    slots={
        "Head": BisSlot(
            slot="Head",
            options=[
                BisItemOption(item_id="51265", item_name="Sanctified Scourgelord's Plate Helmet",    tier_note="ICC 25H T10.277"),
                BisItemOption(item_id="50982", item_name="Scourgelord's Plate Helmet",               tier_note="ICC 25N T10.251"),
            ],
            required_enchant_ids=["3817"],
            enchant_display_name="Arcanum of Torment",
        ),
        "Shoulder": BisSlot(
            slot="Shoulder",
            options=[
                BisItemOption(item_id="51269", item_name="Sanctified Scourgelord's Shoulderplates", tier_note="ICC 25H T10.277"),
                BisItemOption(item_id="50986", item_name="Scourgelord's Shoulderplates",            tier_note="ICC 25N T10.251"),
            ],
            required_enchant_ids=["3875"],
            enchant_display_name="Greater Inscription of the Axe",
        ),
        "Chest": BisSlot(
            slot="Chest",
            options=[
                BisItemOption(item_id="51267", item_name="Sanctified Scourgelord's Plate Chestpiece", tier_note="ICC 25H T10.277"),
                BisItemOption(item_id="50984", item_name="Scourgelord's Plate Chestpiece",            tier_note="ICC 25N T10.251"),
            ],
            required_enchant_ids=["3832"],
            enchant_display_name="Enchant Chest – Powerful Stats",
        ),
        "Wrist": BisSlot(
            slot="Wrist",
            options=[
                BisItemOption(item_id="50303", item_name="Toskk's Maximized Wristguards",  tier_note="ICC 25H Putricide"),
            ],
            required_enchant_ids=["3845"],
            enchant_display_name="Enchant Bracer – Greater Assault",
        ),
        "Legs": BisSlot(
            slot="Legs",
            options=[
                BisItemOption(item_id="51268", item_name="Sanctified Scourgelord's Legplates", tier_note="ICC 25H T10.277"),
                BisItemOption(item_id="50985", item_name="Scourgelord's Legplates",            tier_note="ICC 25N T10.251"),
            ],
            required_enchant_ids=["3822"],
            enchant_display_name="Icescale Leg Armor",
        ),
        "Main Hand": BisSlot(
            slot="Main Hand",
            options=[
                BisItemOption(item_id="49623", item_name="Shadowmourne",                 tier_note="Legendary"),
                BisItemOption(item_id="50415", item_name="Bryntroll, the Bone Arbiter",  tier_note="ICC 25H LK"),
                BisItemOption(item_id="50730", item_name="Glorenzelg, High-Blade of the Silver Hand", tier_note="ICC 25H LK"),
            ],
            required_enchant_ids=["3789"],
            enchant_display_name="Enchant Weapon – Berserking",
        ),
        "Trinket 1": BisSlot(
            slot="Trinket 1",
            options=[
                BisItemOption(item_id="50362", item_name="Deathbringer's Will",        tier_note="ICC 25H Saurfang"),
            ],
        ),
        "Trinket 2": BisSlot(
            slot="Trinket 2",
            options=[
                BisItemOption(item_id="50453", item_name="Needle-Encrusted Scorpion", tier_note="FoS Heroic"),
                BisItemOption(item_id="50340", item_name="Whispering Fanged Skull",   tier_note="ICC 25H LK"),
            ],
        ),
    },
    stat_caps=[
        StatCap(stat_key="hit_rating",           display_name="Hit Rating",       cap_value=262,  cap_label="8% hit cap"),
        StatCap(stat_key="expertise_rating",     display_name="Expertise Rating", cap_value=214,  cap_label="Expertise soft cap 26"),
        StatCap(stat_key="armor_penetration_rating", display_name="Armor Penetration", cap_value=722, cap_label="ArP softcap ~722 (no proc trinket)"),
    ],
    gem_requirements=[
        GemRequirement(gem_item_id="41285", gem_name="Chaotic Skyflare Diamond", required_count=1,
                       description="Meta – mandatory +21% crit damage"),
        GemRequirement(gem_item_id="44342", gem_name="Nightmare Tear",           required_count=1,
                       description="Prismatic blue socket gem for meta activation"),
        GemRequirement(gem_item_id="40117", gem_name="Fractured Cardinal Ruby",  required_count=5,
                       description="+20 Armor Penetration per gem"),
    ],
)


# ░░░░░░░░░░░░░░░░░░░░░  MAGE – ARCANE  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░

_MAGE_ARCANE: BisGuide = BisGuide(
    spec_name="Mage Arcane",
    char_class="Mage",
    spec="Arcane",
    meta_gem_id="41285",
    nightmare_tear_required=True,
    priority_note=(
        "Arcane Mage – prioritise Hit cap (17 % / 446 rating), then Haste to "
        "the soft-cap, then pure Spell Power stacking. "
        "Gem Runed Cardinal Ruby (+23 SP) in red sockets. "
        "Use Nightmare Tear in the best blue socket to keep meta active."
    ),
    slots={
        "Head": BisSlot(
            slot="Head",
            options=[
                BisItemOption(item_id="51209", item_name="Sanctified Bloodmage Hood",       tier_note="ICC 25H T10.277"),
                BisItemOption(item_id="50736", item_name="Bloodmage Hood",                  tier_note="ICC 25N T10.251"),
            ],
            required_enchant_ids=["3840"],
            enchant_display_name="Arcanum of Burning Mysteries",
        ),
        "Shoulder": BisSlot(
            slot="Shoulder",
            options=[
                BisItemOption(item_id="51213", item_name="Sanctified Bloodmage Shoulderpads", tier_note="ICC 25H T10.277"),
            ],
            required_enchant_ids=["3878"],
            enchant_display_name="Greater Inscription of the Storm",
        ),
        "Back": BisSlot(
            slot="Back",
            options=[
                BisItemOption(item_id="50020", item_name="Greatcloak of the Turned Champion", tier_note="ICC 25H BC"),
            ],
            required_enchant_ids=["3736"],
            enchant_display_name="Enchant Cloak – Greater Speed",
        ),
        "Chest": BisSlot(
            slot="Chest",
            options=[
                BisItemOption(item_id="51211", item_name="Sanctified Bloodmage Robe",        tier_note="ICC 25H T10.277"),
            ],
            required_enchant_ids=["3832"],
            enchant_display_name="Enchant Chest – Powerful Stats",
        ),
        "Wrist": BisSlot(
            slot="Wrist",
            options=[
                BisItemOption(item_id="50733", item_name="Bejeweled Wizard's Bracers",       tier_note="ICC 25H LK"),
            ],
            required_enchant_ids=["2332"],
            enchant_display_name="Enchant Bracer – Superior Spellpower",
        ),
        "Hands": BisSlot(
            slot="Hands",
            options=[
                BisItemOption(item_id="51210", item_name="Sanctified Bloodmage Gloves",      tier_note="ICC 25H T10.277"),
            ],
            required_enchant_ids=["3604"],
            enchant_display_name="Enchant Gloves – Exceptional Spellpower",
        ),
        "Legs": BisSlot(
            slot="Legs",
            options=[
                BisItemOption(item_id="51212", item_name="Sanctified Bloodmage Leggings",    tier_note="ICC 25H T10.277"),
            ],
            required_enchant_ids=["3813"],
            enchant_display_name="Brilliant Spellthread",
        ),
        "Feet": BisSlot(
            slot="Feet",
            options=[
                BisItemOption(item_id="50608", item_name="Returning Footfalls",              tier_note="ICC 25H LK"),
            ],
            required_enchant_ids=["3606"],
            enchant_display_name="Enchant Boots – Tuskarr's Vitality",
        ),
        "Main Hand": BisSlot(
            slot="Main Hand",
            options=[
                BisItemOption(item_id="50733", item_name="Trauma",                          tier_note="ICC 25H Rotface"),
                BisItemOption(item_id="50734", item_name="Mag'hari Chieftain's Staff",       tier_note="BoE"),
            ],
            required_enchant_ids=["3834"],
            enchant_display_name="Enchant Weapon – Mighty Spellpower",
        ),
        "Off Hand": BisSlot(
            slot="Off Hand",
            options=[
                BisItemOption(item_id="50719", item_name="Sundial of the Exiled",           tier_note="Emblem of Heroism"),
                BisItemOption(item_id="50360", item_name="Dislodged Foreign Object",         tier_note="ICC 25H Festergut"),
            ],
        ),
        "Trinket 1": BisSlot(
            slot="Trinket 1",
            options=[
                BisItemOption(item_id="50360", item_name="Dislodged Foreign Object",        tier_note="ICC 25H Festergut"),
            ],
        ),
        "Trinket 2": BisSlot(
            slot="Trinket 2",
            options=[
                BisItemOption(item_id="50357", item_name="Muradin's Spyglass",              tier_note="ICC 25H LK"),
                BisItemOption(item_id="50365", item_name="Phylactery of the Nameless Lich", tier_note="ICC 25H LK"),
            ],
        ),
    },
    stat_caps=[
        StatCap(stat_key="hit_rating",   display_name="Hit Rating",  cap_value=446,  cap_label="17% hit cap vs raid bosses (446)"),
        StatCap(stat_key="haste_rating", display_name="Haste Rating", cap_value=856, cap_label="Haste soft-cap ~856 (1-sec GCD with Arcane Power up)", must_reach=False),
    ],
    gem_requirements=[
        GemRequirement(gem_item_id="41285", gem_name="Chaotic Skyflare Diamond", required_count=1,
                       description="Meta – +21% crit damage bonus"),
        GemRequirement(gem_item_id="44342", gem_name="Nightmare Tear",           required_count=1,
                       description="Blue socket – activates meta gem requirement"),
        GemRequirement(gem_item_id="40113", gem_name="Runed Cardinal Ruby",      required_count=5,
                       description="+23 Spell Power per gem – primary DPS gem"),
    ],
)


# ░░░░░░░░░░░░░░░░░░░  PALADIN – RETRIBUTION  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░

_PALADIN_RET: BisGuide = BisGuide(
    spec_name="Paladin Retribution",
    char_class="Paladin",
    spec="Retribution",
    meta_gem_id="41285",
    nightmare_tear_required=True,
    priority_note=(
        "Retribution Paladin. Capped hit (8 % / 262), expertise (26 / 214), "
        "then Strength stacking. Use Bold Cardinal Ruby in red sockets. "
        "Nightmare Tear for meta activation."
    ),
    slots={
        "Head": BisSlot(
            slot="Head",
            options=[
                BisItemOption(item_id="51230", item_name="Sanctified Lightsworn Helmet",       tier_note="ICC 25H T10.277"),
                BisItemOption(item_id="50997", item_name="Lightsworn Helmet",                  tier_note="ICC 25N T10.251"),
            ],
            required_enchant_ids=["3817"],
            enchant_display_name="Arcanum of Torment",
        ),
        "Shoulder": BisSlot(
            slot="Shoulder",
            options=[
                BisItemOption(item_id="51234", item_name="Sanctified Lightsworn Shoulderguards", tier_note="ICC 25H T10.277"),
            ],
            required_enchant_ids=["3875"],
            enchant_display_name="Greater Inscription of the Axe",
        ),
        "Main Hand": BisSlot(
            slot="Main Hand",
            options=[
                BisItemOption(item_id="49623", item_name="Shadowmourne",                 tier_note="Legendary"),
                BisItemOption(item_id="50730", item_name="Glorenzelg, High-Blade of the Silver Hand", tier_note="ICC 25H LK"),
                BisItemOption(item_id="50415", item_name="Bryntroll, the Bone Arbiter",  tier_note="ICC 25H LK"),
            ],
            required_enchant_ids=["3370"],
            enchant_display_name="Enchant Weapon – Mongoose / Berserking",
        ),
        "Trinket 1": BisSlot(
            slot="Trinket 1",
            options=[
                BisItemOption(item_id="50362", item_name="Deathbringer's Will",          tier_note="ICC 25H Saurfang"),
            ],
        ),
        "Trinket 2": BisSlot(
            slot="Trinket 2",
            options=[
                BisItemOption(item_id="50406", item_name="Sharpened Twilight Scale",     tier_note="ICC 25H Halion"),
                BisItemOption(item_id="50340", item_name="Whispering Fanged Skull",       tier_note="ICC 25H LK"),
            ],
        ),
    },
    stat_caps=[
        StatCap(stat_key="hit_rating",       display_name="Hit Rating",       cap_value=262, cap_label="8% hit cap"),
        StatCap(stat_key="expertise_rating", display_name="Expertise Rating", cap_value=214, cap_label="Expertise soft cap 26"),
    ],
    gem_requirements=[
        GemRequirement(gem_item_id="41285", gem_name="Chaotic Skyflare Diamond", required_count=1,
                       description="Mandatory meta gem"),
        GemRequirement(gem_item_id="44342", gem_name="Nightmare Tear",           required_count=1,
                       description="Blue socket – meta activation"),
        GemRequirement(gem_item_id="40111", gem_name="Bold Cardinal Ruby",       required_count=6,
                       description="+20 Strength – primary DPS gem for Ret"),
    ],
)


# ░░░░░░░░░░░░░░░░░░░░░░  REGISTRY  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░

BIS_GUIDES: dict[str, BisGuide] = {
    guide.spec_name: guide
    for guide in [
        _WARRIOR_FURY_ARP,
        _DK_BLOOD_DPS,
        _MAGE_ARCANE,
        _PALADIN_RET,
    ]
}

# Aliases that match what the armory / bot commands return
_ALIASES: dict[str, str] = {
    # class + spec combinations
    "warrior fury":          "Warrior Fury",
    "warrior arms":          "Warrior Fury",   # fallback
    "death knight blood":    "Death Knight Blood",
    "dk blood":              "Death Knight Blood",
    "mage arcane":           "Mage Arcane",
    "arcane mage":           "Mage Arcane",
    "paladin retribution":   "Paladin Retribution",
    "retribution paladin":   "Paladin Retribution",
    "ret paladin":           "Paladin Retribution",
}


def get_bis_guide(char_class: str, spec: str) -> BisGuide | None:
    """
    Look up a BiS guide by class + spec.

    Returns ``None`` if no guide exists for the combination yet.

    Parameters
    ----------
    char_class:
        Character class as returned by the armory, e.g. ``'Warrior'``.
    spec:
        Active spec, e.g. ``'Fury'``.
    """
    key = f"{char_class.strip()} {spec.strip()}"
    # Direct lookup first
    guide = BIS_GUIDES.get(key)
    if guide:
        return guide
    # Alias lookup (case-insensitive)
    canonical = _ALIASES.get(key.lower())
    if canonical:
        return BIS_GUIDES.get(canonical)
    return None
