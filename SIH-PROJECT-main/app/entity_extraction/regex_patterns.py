# regex_patterns.py
import re
from typing import Dict, Any, List, Optional

# --- 1. PRE-COMPILED STATUTORY PATTERNS ---
COMPILED_PATTERNS = {
    "PAN": re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z]{1})\b", re.IGNORECASE),
    "GSTIN": re.compile(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})\b", re.IGNORECASE),
    "CIN": re.compile(r"\b([LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6})\b", re.IGNORECASE),
    "UDYAM": re.compile(r"\b(UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7})\b", re.IGNORECASE),
    "UDIN": re.compile(r"\b([0-9]{2}[0-9]{6}[A-Z0-9]{10})\b", re.IGNORECASE),
    "EPFO": re.compile(r"\b([A-Z]{2}[A-Z]{3}[0-9]{7}[0-9]{3})\b", re.IGNORECASE),
    "ESIC": re.compile(r"\b([0-9]{17})\b"),
    "DPIIT": re.compile(r"\b(DIPP[0-9]{4,6}|DPIIT[0-9]{4,6})\b", re.IGNORECASE),
    "DIN": re.compile(r"\b(?:DIN[:\s\-]*|Director Identification Number[:\s\-]*)([0-9]{8})\b", re.IGNORECASE),
    
    # --- 2. COLLUSION & NETWORK SIGNAL PATTERNS ---
    "PINCODE": re.compile(r"\b([1-9][0-9]{5})\b"),
    "EMAIL": re.compile(r"\b([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)\b"),
    "PHONE": re.compile(r"(?:\+91[\-\s]?)?([6-9][0-9]{9})\b")
}


def extract_statutory_tokens(text: str) -> Dict[str, Any]:
    """
    Runs deterministic regex extraction over raw OCR text.
    Returns primary statutory IDs, lists for multi-value entities (DINs),
    and contact footprints for Module 4 cartel analysis.
    """
    if not text:
        return {
            "pan": None,
            "gstin": None,
            "cin": None,
            "udyam": None,
            "udin": None,
            "epfo": None,
            "esic": None,
            "dpiit": None,
            "startup_india_number": None,
            "dins": [],
            "din": [],
            "registered_pincode": None,
            "registered_email": None,
            "registered_phone": None,
        }

    # Extract all pattern matches
    raw_matches = {}
    for key, compiled_regex in COMPILED_PATTERNS.items():
        found = compiled_regex.findall(text)
        # Deduplicate while preserving order
        raw_matches[key.lower()] = list(dict.fromkeys(found))

    # Helper for first matched item
    def first_or_none(key_name: str) -> Optional[str]:
        items = raw_matches.get(key_name, [])
        return items[0].upper() if items else None

    din_list = raw_matches.get("din", [])
    dpiit_val = first_or_none("dpiit")
    email_items = raw_matches.get("email", [])
    phone_items = raw_matches.get("phone", [])
    pincode_items = raw_matches.get("pincode", [])

    return {
        # Core Single Identifiers (Normalized to Uppercase)
        "pan": first_or_none("pan"),
        "gstin": first_or_none("gstin"),
        "cin": first_or_none("cin"),
        "udyam": first_or_none("udyam"),
        "udin": first_or_none("udin"),
        "epfo": first_or_none("epfo"),
        "esic": first_or_none("esic"),
        "dpiit": dpiit_val,
        "startup_india_number": dpiit_val,

        # Multi-value collections
        "dins": din_list,
        "din": din_list,

        # Cartel / Network Footprints
        "registered_email": email_items[0].lower() if email_items else None,
        "registered_phone": phone_items[0] if phone_items else None,
        "registered_pincode": pincode_items[0] if pincode_items else None,
        
        # Raw grouped matches dictionary
        "all_matches": raw_matches
    }