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
from .bis_guides import BIS_GUIDES, get_bis_guide
from .auditor import audit_character
from .coach import generate_coach_summary

__all__ = [
    "audit_character",
    "generate_coach_summary",
    "get_bis_guide",
    "BIS_GUIDES",
    # models
    "AuditReport",
    "AuditSeverity",
    "BisGuide",
    "CharacterData",
    "EnchantAuditIssue",
    "EquippedItem",
    "GemAuditIssue",
    "ItemAuditIssue",
    "StatCapAuditResult",
]
