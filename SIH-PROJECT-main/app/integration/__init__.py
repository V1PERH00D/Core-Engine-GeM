"""Integration layer between Module 1/2 (SIH-PROJECT-main) and Module 4
(Core-Engine-GeM).

Module 1/2 owns ingestion, OCR, classification, entity extraction and
application persistence. Core-Engine-GeM owns Evidence normalization,
cross-document consistency rules, canonical flags and explanations.

This package is the single, explicit translation point between the two.
It contains no verification rules of its own: every rule, flag and
explanation is produced by the Core-Engine-GeM engines.
"""
