from typing import Dict, Any

def verify_extraction_grounding(extracted_value: Any, raw_text: str) -> float:
    """Verifies whether extracted field exists in source text to detect hallucination."""
    if extracted_value is None:
        return 0.0
    val_str = str(extracted_value).strip().lower()
    if val_str in raw_text.lower():
        return 1.0  # 100% grounded in source document
    return 0.5      # Derived / Normalized value


def calculate_grounding_score(extracted_dict: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    """
    Verifies that extracted statutory tokens have exact string matches in the OCR source.
    Generates a confidence report to prevent LLM hallucinations.
    """
    raw_lower = raw_text.lower()
    field_confidence = {}

    # Check GSTIN
    gst = extracted_dict.get("gst", {}).get("gstin")
    if gst:
        field_confidence["gstin"] = 1.0 if gst.lower() in raw_lower else 0.0

    # Check PAN
    pan = extracted_dict.get("pan_itr", {}).get("pan_number")
    if pan:
        field_confidence["pan"] = 1.0 if pan.lower() in raw_lower else 0.0

    # Check UDIN
    ca_udin = extracted_dict.get("ca_udin", {}).get("ca_udin")
    if ca_udin:
        field_confidence["ca_udin"] = 1.0 if ca_udin.lower() in raw_lower else 0.0

    # Check Udyam
    udyam = extracted_dict.get("udyam", {}).get("udyam_registration_number")
    if udyam:
        field_confidence["udyam"] = 1.0 if udyam.lower() in raw_lower else 0.0

    score_values = list(field_confidence.values())
    avg_score = sum(score_values) / len(score_values) if score_values else 1.0

    return {
        "field_confidence": field_confidence,
        "overall_grounding_score": round(avg_score, 2),
        "is_reliable": avg_score >= 0.8
    }