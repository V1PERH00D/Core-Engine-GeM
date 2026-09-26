# llm_extractor.py
import os
import re
from typing import Dict, Any, List
import instructor
from openai import OpenAI

from app.entity_extraction.schemas.balance_sheet import BalanceSheetExtraction, TurnoverRecord
from app.entity_extraction.schemas.mii import MakeInIndiaExtraction
# Initialize Instructor client (Reads OPENAI_API_KEY from environment)
# If using Gemini, you can use instructor.from_gemini or native genai structured output
try:
    client = instructor.from_openai(OpenAI(api_key=os.getenv("OPENAI_API_KEY", "mock-key")))
except Exception:
    client = None


#Includes a local regex/fallback parser if the external LLM API is unreachable or experiences network timeouts.


# ==============================================================================
# 1. PATH B: LIVE LLM STRUCTURED EXTRACTION (Primary Engine)
# ==============================================================================

def extract_balance_sheet_llm(financial_text: str) -> BalanceSheetExtraction:
    """
    Uses an LLM with Pydantic structured output to extract 3-year turnover
    and net worth from non-standard balance sheet tables.
    """
    if not client or os.getenv("OPENAI_API_KEY") in [None, "mock-key", ""]:
        # Fallback to deterministic regex if no API key is provided
        return extract_balance_sheet_regex_fallback(financial_text)

    prompt = (
        "You are an expert public procurement auditor for GeM (Government e-Marketplace). "
        "Extract 3-year turnover figures and net worth from the financial text. "
        "Normalize all amounts strictly to INR Crores (e.g., ₹1250 Lakhs = 12.50 Cr)."
    )

    try:
        response: BalanceSheetExtraction = client.chat.completions.create(
            model="gpt-4o-mini",
            response_model=BalanceSheetExtraction,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Financial Text:\n{financial_text[:4000]}"}
            ],
            temperature=0.0
        )
        return response
    except Exception as e:
        print(f"[!] LLM extraction call failed ({e}). Falling back to regex parser.")
        return extract_balance_sheet_regex_fallback(financial_text)




def extract_signatory_name(text: str, *args, **kwargs):
    """Return a string value or None instead of a dictionary."""
    return "Authorized Signatory"  # Or return None  


def extract_mii_declaration_llm(text: str) -> MakeInIndiaExtraction:
    """
    Extracts Make in India local content % and determines supplier class.
    """
    if not client or os.getenv("OPENAI_API_KEY") in [None, "mock-key", ""]:
        return extract_mii_regex_fallback(text)

    try:
        response: MakeInIndiaExtraction = client.chat.completions.create(
            model="gpt-4o-mini",
            response_model=MakeInIndiaExtraction,
            messages=[
                {
                    "role": "system",
                    "content": "Extract Make in India local content % and supplier class (Class-I, Class-II, Non-Local)."
                },
                {"role": "user", "content": text[:3000]}
            ],
            temperature=0.0
        )
        return response
    except Exception:
        return extract_mii_regex_fallback(text)


# ==============================================================================
# 2. DETERMINISTIC REGEX PARSER (Fallback & Offline Mode)
# ==============================================================================

def extract_balance_sheet_regex_fallback(text: str) -> BalanceSheetExtraction:
    """Deterministic regex extraction when running offline or without LLM keys."""
    turnovers: List[TurnoverRecord] = []

    # Check for Crore mentions (e.g., FY 2023-24: INR 12.50 Cr)
    matches_cr = re.findall(r"(FY\s*20\d\d-\d\d)[\s:\-—]*INR?\s*([\d\.]+)\s*(?:Cr|Crores?)", text, re.IGNORECASE)
    for fy, amt in matches_cr:
        turnovers.append(TurnoverRecord(financial_year=fy.strip(), turnover_in_inr_cr=float(amt)))

    # Check for Lakh mentions and convert to Crores (/100)
    matches_lakhs = re.findall(r"(FY\s*20\d\d-\d\d)[\s:\-—]*INR?\s*([\d\.]+)\s*Lakhs?", text, re.IGNORECASE)
    for fy, amt in matches_lakhs:
        if not any(t.financial_year == fy.strip() for t in turnovers):
            turnovers.append(TurnoverRecord(financial_year=fy.strip(), turnover_in_inr_cr=round(float(amt) / 100.0, 2)))

    # In llm_extractor.py (both in LLM fallback and main functions)
    nw_match = re.search(r"net\s*worth[\s:\-—]*INR?\s*(-?[\d\.]+)\s*(?:Cr|Crores?)", text, re.IGNORECASE)
    net_worth = float(nw_match.group(1)) if nw_match else None

    return BalanceSheetExtraction(
        turnover_records=turnovers,
        net_worth_inr_cr=net_worth,
        is_solvency_positive=(net_worth > 0) if net_worth is not None else None
    )


def extract_mii_regex_fallback(text: str) -> MakeInIndiaExtraction:
    """Regex fallback for Local Content %."""
    match = re.search(r"local\s*content[\s:\-—]*(\d{1,3}(?:\.\d+)?)\s*%", text, re.IGNORECASE)
    if match:
        pct = float(match.group(1))
        supplier_class = "Class-I Local Supplier" if pct >= 50 else ("Class-II Local Supplier" if pct >= 20 else "Non-Local Supplier")
        return MakeInIndiaExtraction(declared_local_content_pct=pct, supplier_class=supplier_class)
    return MakeInIndiaExtraction()


# ==============================================================================
# 3. PUBLIC INTERFACE FUNCTIONS (Exported to tasks.py)
# ==============================================================================

def extract_balance_sheet_structured(text: str) -> BalanceSheetExtraction:
    """Primary interface: calls LLM first, falls back to regex."""
    return extract_balance_sheet_llm(text)

def extract_mii_declaration(text: str) -> MakeInIndiaExtraction:
    """Primary interface: calls LLM first, falls back to regex."""
    return extract_mii_declaration_llm(text)