"""
GsChecker – Audit Module
========================
Compares a character's gear, gems and enchants against a predefined BiS guide
and generates an expert narrative summary via Groq.

Public API
----------
    from src.audit import audit_character, get_bis_guide, AuditReport
    from src.audit.coach import generate_coach_summary
"""

from .auditor import audit_character
from .bis_guides import available_guides, get_bis_guide
from .coach import generate_coach_summary
from .models import (
    AuditReport,
    AuditSeverity,
    BisGuide,
    CharacterData,
    EnchantAuditIssue,
    EquippedItem,
    GemAuditIssue,
    ItemAuditIssue,
    StatCapAuditResult,
)

__all__ = [
    "AuditReport",
    "AuditSeverity",
    "BisGuide",
    "CharacterData",
    "EnchantAuditIssue",
    "EquippedItem",
    "GemAuditIssue",
    "ItemAuditIssue",
    "StatCapAuditResult",
    "audit_character",
    "available_guides",
    "generate_coach_summary",
    "get_bis_guide",
]
