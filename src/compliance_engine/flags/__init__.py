"""Verification flag registry."""

from compliance_engine.flags.registry import (
    FLAG_REGISTRY,
    GSTIN_MISSING,
    FlagDefinition,
    FlagSeverity,
    UnknownFlagError,
    get_flag_definition,
)

__all__ = [
    "FLAG_REGISTRY",
    "GSTIN_MISSING",
    "FlagDefinition",
    "FlagSeverity",
    "UnknownFlagError",
    "get_flag_definition",
]
