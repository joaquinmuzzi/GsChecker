"""
Pydantic models for the GsChecker audit module.

Patch context: WoW WotLK 3.3.5a (ICC patch).
All item / gem / enchant IDs are stored as ``str`` to match the armory payload
and the existing profile_scraper.py / gearscore.py conventions.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────── enums ───────────────────────────────────────────

class AuditSeverity(str, Enum):
    CRITICAL = "critical"  # wrong item / slot completely missing enchant
    WARNING  = "warning"   # non-epic gem, suboptimal enchant, near-cap miss
    INFO     = "info"      # alternative available but current is acceptable


# ─────────────────────────── character input ─────────────────────────────────

class EquippedItem(BaseModel):
    """A single item as returned by the Warmane armory scraper."""

    slot: str
    """Slot label, e.g. 'Head', 'Main Hand', 'Finger 1'."""

    item_id: str
    """Wowhead / armory item ID."""

    enchant_id: str | None = None
    """Enchant ID applied to the item (None / '0' → no enchant)."""

    gem_enchant_ids: list[str] = Field(default_factory=list)
    """
    Enchant IDs that represent socketed gems, as returned by the armory
    ``gems`` field.  These are **enchant IDs**, not item IDs – use the
    ``_GEM_BY_ENCHANT`` reverse-map from ``profile_scraper`` to resolve them.
    """

    @field_validator("enchant_id", mode="before")
    @classmethod
    def _normalise_enchant(cls, v: object) -> str | None:
        s = str(v).strip() if v is not None else ""
        return None if s in ("", "0", "None") else s

    @field_validator("item_id", mode="before")
    @classmethod
    def _normalise_item(cls, v: object) -> str:
        return str(v).strip()

    @field_validator("gem_enchant_ids", mode="before")
    @classmethod
    def _normalise_gems(cls, v: object) -> list[str]:
        if not isinstance(v, (list, tuple)):
            return []
        return [str(g).strip() for g in v if str(g).strip() not in ("", "0")]


class CharacterStats(BaseModel):
    """Relevant secondary stats parsed from the character sheet."""

    hit_rating:      float = 0.0
    expertise_rating: float = 0.0
    armor_penetration_rating: float = 0.0
    haste_rating:    float = 0.0
    crit_rating:     float = 0.0
    spell_power:     float = 0.0
    mp5:             float = 0.0
    defense_rating:  float = 0.0
    dodge_rating:    float = 0.0
    parry_rating:    float = 0.0

    class Config:
        extra = "allow"  # tolerate unknown stats from the armory payload


class CharacterData(BaseModel):
    """Full character snapshot fetched from the armory."""

    name:       str
    server:     str
    char_class: str
    """E.g. 'Warrior', 'Death Knight'."""

    spec: str
    """Active spec label, e.g. 'Fury', 'Blood'."""

    items: list[EquippedItem] = Field(default_factory=list)
    stats: CharacterStats = Field(default_factory=CharacterStats)

    @property
    def items_by_slot(self) -> dict[str, EquippedItem]:
        """O(n) lookup helper; build once per audit call."""
        return {item.slot: item for item in self.items}


# ─────────────────────────── BiS guide input ─────────────────────────────────

class BisItemOption(BaseModel):
    """One item that is acceptable in a given slot (ordered by priority)."""

    item_id:   str
    item_name: str
    tier_note: str = ""
    """E.g. 'ICC 25H', 'crafted', 'badge'."""


class BisSlot(BaseModel):
    """BiS requirements for a single equipment slot."""

    slot: str
    options: list[BisItemOption] = Field(default_factory=list)
    """Ordered best → acceptable. options[0] is the true BiS."""

    required_enchant_ids: list[str] = Field(default_factory=list)
    """Any of these enchant IDs is acceptable (OR logic)."""

    enchant_display_name: str = ""
    """Human-readable enchant label shown in audit messages."""

    @property
    def bis_item(self) -> BisItemOption | None:
        return self.options[0] if self.options else None

    def is_item_acceptable(self, item_id: str) -> bool:
        return any(opt.item_id == item_id for opt in self.options)

    def is_enchant_acceptable(self, enchant_id: str | None) -> bool:
        if not self.required_enchant_ids:
            return True
        if not enchant_id:
            return False
        return enchant_id in self.required_enchant_ids


class StatCap(BaseModel):
    """A stat threshold that must be reached (or not exceeded)."""

    stat_key:     str
    """Must match a field name in ``CharacterStats``."""

    display_name: str
    """E.g. 'Hit Rating', 'Armor Penetration'."""

    cap_value:    float
    """Numeric cap (e.g. 262 for hit to 8 %)."""

    cap_label:    str = ""
    """Friendly label, e.g. '8% hit cap', '100 % ArP'."""

    must_reach:   bool = True
    """True  → reaching the cap is mandatory (hard cap).
    False → going over the cap is wasteful (soft cap check)."""


class GemRequirement(BaseModel):
    """
    A gem that should appear at least ``required_count`` times across all
    non-meta sockets (or exactly once for Nightmare Tear).
    """

    gem_item_id:    str
    """Item ID of the required gem, e.g. '44342' for Nightmare Tear."""

    gem_name:       str
    required_count: int = 1

    description: str = ""
    """Context note, e.g. 'Activates Chaotic Skyflare Diamond meta'."""


class BisGuide(BaseModel):
    """Complete BiS reference for a single spec."""

    spec_name:       str
    """Full label used as a lookup key, e.g. 'Warrior Fury'."""

    char_class:      str
    spec:            str

    slots:           dict[str, BisSlot] = Field(default_factory=dict)
    """Keyed by slot name, e.g. 'Head', 'Main Hand'."""

    stat_caps:       list[StatCap] = Field(default_factory=list)
    gem_requirements: list[GemRequirement] = Field(default_factory=list)

    meta_gem_id: str | None = None
    """Expected meta gem item ID, e.g. '41285' (Chaotic Skyflare Diamond)."""

    priority_note: str = ""
    """Short strategy note shown in the coach summary."""

    nightmare_tear_required: bool = True
    """Whether Nightmare Tear (44342) is mandatory for meta activation."""


# ─────────────────────────── audit result ────────────────────────────────────

class ItemAuditIssue(BaseModel):
    slot: str
    current_item_id: str
    current_item_name: str = "Unknown"
    bis_item_id:     str
    bis_item_name:   str
    severity:        AuditSeverity
    message:         str


class GemAuditIssue(BaseModel):
    slot:       str
    gem_id:     str
    gem_name:   str
    issue:      str
    suggestion: str
    severity:   AuditSeverity


class EnchantAuditIssue(BaseModel):
    slot:                  str
    current_enchant_id:    str | None
    expected_enchant_name: str
    severity:              AuditSeverity
    message:               str


class StatCapAuditResult(BaseModel):
    stat_key:     str
    display_name: str
    current_value: float
    cap_value:    float
    cap_label:    str
    is_capped:    bool
    delta:        float
    """cap_value − current_value.  Negative → overcapped."""

    must_reach: bool = True

    @property
    def is_overcapped(self) -> bool:
        return self.delta < 0

    @property
    def pct_reached(self) -> float:
        if self.cap_value == 0:
            return 100.0
        return min(100.0, self.current_value / self.cap_value * 100)


class AuditReport(BaseModel):
    """Full audit result returned by ``audit_character()``."""

    character_name: str
    spec_name:      str
    server:         str

    item_issues:    list[ItemAuditIssue]    = Field(default_factory=list)
    gem_issues:     list[GemAuditIssue]     = Field(default_factory=list)
    enchant_issues: list[EnchantAuditIssue] = Field(default_factory=list)
    stat_caps:      list[StatCapAuditResult] = Field(default_factory=list)

    overall_score: Annotated[int, Field(ge=0, le=100)] = 100
    """
    0–100 score derived from weighted penalty deductions.
    100 = fully BiS with all caps met, correct gems and enchants.
    """

    coach_summary: str | None = None
    """Narrative paragraph generated by Groq; None if API call was skipped."""

    audit_timestamp: datetime = Field(default_factory=datetime.utcnow)

    # ── convenience helpers ────────────────────────────────────────────────

    @property
    def critical_count(self) -> int:
        counts = (
            sum(1 for i in self.item_issues    if i.severity == AuditSeverity.CRITICAL)
            + sum(1 for i in self.gem_issues   if i.severity == AuditSeverity.CRITICAL)
            + sum(1 for i in self.enchant_issues if i.severity == AuditSeverity.CRITICAL)
        )
        return counts

    @property
    def warning_count(self) -> int:
        return (
            sum(1 for i in self.item_issues    if i.severity == AuditSeverity.WARNING)
            + sum(1 for i in self.gem_issues   if i.severity == AuditSeverity.WARNING)
            + sum(1 for i in self.enchant_issues if i.severity == AuditSeverity.WARNING)
        )

    def to_plain_text(self) -> str:
        """Compact text representation for Discord embeds."""
        lines: list[str] = [
            f"── Audit · {self.character_name} ({self.spec_name}) ──",
            f"Score: {self.overall_score}/100  |  "
            f"{self.critical_count} critical · {self.warning_count} warnings",
        ]
        if self.item_issues:
            lines.append("\n[ITEMS]")
            for i in self.item_issues:
                lines.append(f"  [{i.severity.value.upper()}] {i.message}")
        if self.enchant_issues:
            lines.append("\n[ENCHANTS]")
            for e in self.enchant_issues:
                lines.append(f"  [{e.severity.value.upper()}] {e.message}")
        if self.gem_issues:
            lines.append("\n[GEMS]")
            for g in self.gem_issues:
                lines.append(f"  [{g.severity.value.upper()}] {g.slot}: {g.issue}")
        if self.stat_caps:
            lines.append("\n[STAT CAPS]")
            for s in self.stat_caps:
                status = "✓" if s.is_capped else "✗"
                lines.append(
                    f"  {status} {s.display_name}: {s.current_value:.0f} / {s.cap_value:.0f}"
                    + (f"  (+{s.delta:.0f} needed)" if not s.is_capped and s.must_reach else "")
                )
        if self.coach_summary:
            lines.append(f"\n[COACH]\n{self.coach_summary}")
        return "\n".join(lines)
