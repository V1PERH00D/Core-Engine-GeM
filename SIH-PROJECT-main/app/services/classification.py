DOCUMENT_SIGNATURES = {
    "udyam_certificate": {
        "keywords": ["udyam registration", "udyam registration number", "udyam reg"],
        "display_name": "Udyam Registration Certificate",
    },
    "gst_certificate": {
        "keywords": ["goods and services tax", "gstin", "certificate of registration"],
        "display_name": "GST Registration Certificate",
    },
    "pan_card": {
        "keywords": ["income tax department", "permanent account number", "govt. of india"],
        "display_name": "PAN Card",
    },
    "itr_acknowledgment": {
        "keywords": ["income tax return", "acknowledgement number", "assessment year"],
        "display_name": "ITR Acknowledgment",
    },
    "epfo_certificate": {
        "keywords": ["employees provident fund", "epfo", "establishment code"],
        "display_name": "EPFO Registration Certificate",
    },
    "esic_certificate": {
        "keywords": [
            "employees state insurance", "esic", "esi corporation",
            "insurance number", "employer code", "sub code",
            "esic registration", "e.s.i. act", "insurable employment"
        ],
        "display_name": "ESIC Registration Certificate",
    },

    "startup_india_certificate": {
        "keywords": [
            "startup india", "dpiit", "department for promotion of industry",
            "certificate of recognition", "startup recognition number",
            "recognition certificate", "startup india scheme",
            "innovative", "scalable business model"
        ],
        "display_name": "Startup India Certificate",
    },

    "nsic_certificate": {
        "keywords": [
            "national small industries corporation", "nsic",
            "single point registration", "spr certificate",
            "nsic registration", "monetary limit",
            "tender marketing", "public procurement policy"
        ],
        "display_name": "NSIC Registration Certificate",
    },

    "oem_authorization": {
        "keywords": [
            "original equipment manufacturer", "oem", "authorization letter",
            "authorized dealer", "authorized distributor", "manufacturer authorization",
            "authorized to sell", "authorized to bid", "on behalf of the manufacturer",
            "letter of authorization"
        ],
        "display_name": "OEM Authorization Letter",
    },

    "digilocker_document": {
        "keywords": [
            "digilocker", "digital locker", "issued via digilocker",
            "digitally signed", "e-sign", "meripehchaan",
            "digilocker verified", "government of india digilocker"
        ],
        "display_name": "DigiLocker Verified Document",
    },

    "board_resolution_poa": {
        "keywords": [
            "board resolution", "power of attorney", "poa",
            "authorized signatory", "resolved that", "board of directors",
            "hereby authorize", "in pursuance of section", "notarized",
            "certified true copy of resolution"
        ],
        "display_name": "Board Resolution / Power of Attorney",
    },

    "self_declaration": {
        "keywords": [
            "self declaration", "undertaking", "hereby declare",
            "i/we declare", "solemnly affirm", "declaration form",
            "on affidavit", "non-blacklisting declaration", "no litigation certificate"
        ],
        "display_name": "Self Declaration / Undertaking",
    },

    "financial_statement": {
        "keywords": [
            "balance sheet", "profit and loss", "audited financial statement",
            "annual turnover", "chartered accountant", "auditor's report",
            "net worth certificate", "ca certificate", "financial year ended",
            "statement of accounts"
        ],
        "display_name": "Financial Statement",
    },

    "blacklisting_debarment": {
        "keywords": [
            "blacklisting", "debarment", "not blacklisted", "not debarred",
            "banned list", "holiday listed", "suspension of business dealings",
            "no adverse action", "certificate of non-blacklisting"
        ],
        "display_name": "Non-Blacklisting / Debarment Certificate",
    },

    "make_in_india_local_content": {
        "keywords": [
            "make in india", "local content", "class-i local supplier",
            "class-ii local supplier", "domestic value addition",
            "purchase preference", "local content percentage",
            "self-certification of local content"
        ],
        "display_name": "Make in India / Local Content Certificate",
    },
}

def classify_document(text: str) -> tuple[str, str]:
    if not text:
        return "unclassified", "Unclassified Document"

    text_lower = text.lower()

    best_match = None
    best_score = 0

    for doc_type, signature in DOCUMENT_SIGNATURES.items():
        score = sum(1 for kw in signature["keywords"] if kw in text_lower)
        if score > best_score:
            best_score = score
            best_match = doc_type

    if best_match is None:
        return "unclassified", "Unclassified Document"

    return best_match, DOCUMENT_SIGNATURES[best_match]["display_name"]