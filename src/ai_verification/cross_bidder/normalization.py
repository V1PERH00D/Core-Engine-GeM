from __future__ import annotations

import re
import unicodedata

#: Normalization version for reproducibility and caching.
NORMALIZATION_VERSION = "v1"

# Punctuation and separator characters removed during normalization.
# This set covers the most common OCR noise and non-alphanumeric separators.
_PUNCT_RE = r"[!" + r'"' + r'#$%&\'()*+,-./:;<=>?@[\]^_`{|}~•\n\r\t]+'


def _remove_punctuation(text: str) -> str:
    """Remove punctuation and separator characters."""
    return re.sub(_PUNCT_RE, " ", text)


def normalize_text(text: str) -> str:
    """Normalize text for cross-bidder comparison.

    Steps:
    1. Unicode NFKC normalization
    2. Lowercase
    3. Strip surrounding whitespace
    4. Collapse repeated internal whitespace to single space
    5. Remove punctuation / separators
    6. Normalize obvious OCR confusables (digit zero / letter O, etc.)

    Deterministic; no linguistic rewriting.
    """
    if not text:
        return ""

    # 1. Unicode NFKC normalization
    normalized = unicodedata.normalize("NFKC", text)

    # 2. Lowercase
    normalized = normalized.lower()

    # 3. Strip surrounding whitespace
    normalized = normalized.strip()

    # 4. Collapse repeated internal whitespace to single space
    normalized = re.sub(r"\s+", " ", normalized)

    # 5. Remove punctuation / separators (replace with space, then collapse again)
    normalized = _remove_punctuation(normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # 6. Normalize obvious OCR confusables
    # Map common OCR error patterns: 0 -> o, 1 -> l, 5 -> s, etc.
    confusables = {
        "0": "o",
        "1": "l",
        "5": "s",
    }
    # Build translation table for single-pass replacement
    trans_table = str.maketrans(confusables)
    normalized = normalized.translate(trans_table)

    return normalized


def normalized_text_hash(text: str) -> str:
    """Calculate SHA-256 hash of normalized text.

    Uses the same normalization pipeline as ``normalize_text`` so that
    two texts with identical semantic content but different original
    formatting (e.g. OCR artifacts, formatting) will produce the same hash.

    Returns hex digest string.
    """
    from hashlib import sha256

    normalized = normalize_text(text)
    return sha256(normalized.encode("utf-8")).hexdigest()
