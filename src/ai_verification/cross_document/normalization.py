"""Deterministic per-dimension normalization for cross-document consistency."""


import re
import unicodedata
from datetime import date, datetime
from typing import Optional


IDENTIFIER_NORMALIZATION_VERSION = "cross-document-identifier-v1"

IDENTIFIER_NORMALIZATION_RULES: tuple[str, ...] = (
    "1. None / non-string -> None",
    "2. Empty / whitespace-only -> None",
    "3. Unicode NFKC",
    "4. Strip surrounding whitespace",
    "5. Collapse repeated internal whitespace to single space",
    "6. Strip edge punctuation (trailing/leading '.', ',', ';', ':')",
    "7. ASCII uppercase",
)


_MULTI_WS_RE = re.compile(r"\s+")

_EDGE_PUNCT_RE = re.compile(r"^[.,;:\s]+|[.,;:\s]+$")


def normalize_identifier(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if not isinstance(value, str):
        value = str(value)

    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        return None

    text = _MULTI_WS_RE.sub(" ", text)
    text = _EDGE_PUNCT_RE.sub("", text).strip()
    if not text:
        return None

    text = _MULTI_WS_RE.sub(" ", text).strip()
    return text.upper()


ADDRESS_NORMALIZATION_VERSION = "cross-document-address-v1"

ADDRESS_NORMALIZATION_RULES: tuple[str, ...] = (
    "1. None / non-string -> None",
    "2. Empty / whitespace-only -> None",
    "3. Unicode NFKC",
    "4. Strip surrounding whitespace",
    "5. Normalize line breaks",
    "6. Collapse internal whitespace per line",
    "7. Drop empty lines",
    "8. Trim each line",
    "9. Strip harmless edge punctuation",
    "10. Comma spacing normalization",
    "11. Case-fold",
)


_INTERNAL_WS_RE = re.compile(r"[ \t\f\v]+")

_LINE_EDGE_PUNCT_RE = re.compile(r"[,;\s]+|[,;]+$")

_COMMA_SPACE_RE = re.compile(r"\s*,\s*")
_COMMA_RUN_RE = re.compile(r"(?:,\s*){2,}")


def _normalize_address_line(line: str) -> str:
    text = _INTERNAL_WS_RE.sub(" ", line)
    text = _LINE_EDGE_PUNCT_RE.sub("", text).strip()
    text = _INTERNAL_WS_RE.sub(" ", text).strip()
    return text


def normalize_address(value: object) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None

    text = unicodedata.normalize("NFKC", value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip()
    if not text:
        return None

    lines = text.split("\n")
    cleaned: list[str] = []
    for raw in lines:
        line = _normalize_address_line(raw)
        if line:
            cleaned.append(line)
    if not cleaned:
        return None

    joined = "\n".join(cleaned)
    joined = _COMMA_SPACE_RE.sub(", ", joined)
    joined = _COMMA_RUN_RE.sub(", ", joined)
    joined = _INTERNAL_WS_RE.sub(" ", joined).strip()
    return joined.casefold()


DATE_NORMALIZATION_VERSION = "cross-document-date-v1"

DATE_NORMALIZATION_RULES: tuple[str, ...] = (
    "1. None / non-parseable -> None",
    "2. Accept ISO-8601-style strings",
    "3. Accept 'DD-MM-YYYY' and 'DD/MM/YYYY'",
    "4. Accept 'DD-Mon-YYYY'",
    "5. Return canonical 'YYYY-MM-DD'",
)


_ISO_DATE_RE = re.compile(
    r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[T\s]\d{1,2}:\d{2}:\d{2})?\s*$"
)

_DMY_DATE_RE = re.compile(r"^\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$")

_MONTHS: dict[str, int] = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
_DMONY_DATE_RE = re.compile(
    r"^\s*(\d{1,2})[-\s]+([A-Za-z]{3,9})[-\s]+(\d{4})\s*$"
)


def _canonical(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def normalize_date(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None

    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        return None

    match = _ISO_DATE_RE.match(text)
    if match:
        y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return _canonical(y, m, d)

    match = _DMY_DATE_RE.match(text)
    if match:
        d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return _canonical(y, m, d)

    match = _DMONY_DATE_RE.match(text)
    if match:
        d_str = match.group(1)
        mon_str = match.group(2).upper()[:3]
        y_str = match.group(3)
        month = _MONTHS.get(mon_str)
        if month is None:
            return None
        return _canonical(int(y_str), month, int(d_str))

    return None


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


PRODUCT_NORMALIZATION_VERSION = "cross-document-product-v1"

PRODUCT_NORMALIZATION_RULES: tuple[str, ...] = (
    "1. None / non-string -> None",
    "2. Empty / whitespace-only -> None",
    "3. Unicode NFKC",
    "4. Strip surrounding whitespace",
    "5. Collapse repeated internal whitespace to single space",
    "6. Strip harmless edge punctuation",
    "7. Case-fold",
)


def normalize_product(value: object) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None

    text = unicodedata.normalize("NFKC", value)
    text = text.strip()
    if not text:
        return None

    text = _MULTI_WS_RE.sub(" ", text)
    text = _EDGE_PUNCT_RE.sub("", text).strip()
    if not text:
        return None

    return _MULTI_WS_RE.sub(" ", text).strip().casefold()


MANUFACTURER_NORMALIZATION_VERSION = "identity-name-v1"
MANUFACTURER_NORMALIZATION_RULES: tuple[str, ...] = (
    "Manufacturer normalization reuses the cross-source identity "
    "name normalizer (NAME_NORMALIZATION_VERSION).",
)


def normalize_manufacturer(value: object) -> Optional[str]:
    from ai_verification.identity.normalization import normalize_legal_name

    return normalize_legal_name(value)


__all__ = [
    "ADDRESS_NORMALIZATION_RULES",
    "ADDRESS_NORMALIZATION_VERSION",
    "DATE_NORMALIZATION_RULES",
    "DATE_NORMALIZATION_VERSION",
    "IDENTIFIER_NORMALIZATION_RULES",
    "IDENTIFIER_NORMALIZATION_VERSION",
    "MANUFACTURER_NORMALIZATION_RULES",
    "MANUFACTURER_NORMALIZATION_VERSION",
    "PRODUCT_NORMALIZATION_RULES",
    "PRODUCT_NORMALIZATION_VERSION",
    "normalize_address",
    "normalize_date",
    "normalize_identifier",
    "normalize_manufacturer",
    "normalize_product",
    "parse_iso_date",
]
