# bbox_mapper.py
from typing import List, Dict, Any, Optional

def map_field_to_bbox(search_term: str, ocr_pages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Finds which document + text snippet an extracted value came from.
    (No true visual bounding box yet — Module 1's OCR doesn't emit
    word-level coordinates. This returns a text-based evidence pointer
    instead: which file, and the surrounding text.)"""
    if not search_term:
        return None

    term_lower = search_term.strip().lower()
    for page in ocr_pages:
        raw_text = page.get("raw_text", "")
        idx = raw_text.lower().find(term_lower)
        if idx != -1:
            start = max(0, idx - 40)
            end = min(len(raw_text), idx + len(term_lower) + 40)
            return {
                "file_name": page.get("file_name"),
                "matched_text": raw_text[idx: idx + len(term_lower)],
                "context_snippet": raw_text[start:end].strip()
            }
    return None