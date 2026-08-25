from enum import Enum

class ComplianceStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    MISSING = "MISSING"

class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

CHECK_IDS = {
    "GST": "CHK-GST-01",
    "PAN": "CHK-PAN-01",
    "UDYAM": "CHK-UDYAM-01",
    "EPFO": "CHK-EPFO-01",
    "OEM": "CHK-OEM-01",
    "MCA21": "CHK-MCA-01",
    "MAKE_IN_INDIA": "CHK-MII-01",
    "BLACKLIST": "CHK-BLK-01"
}

ENGINE_METADATA = {
    "module_2_rules_version": "v1.0.0-deterministic",
    "module_3_ai_model_version": "v1.0.0-llama3-groq",
    "schema_version": "2026-08.1"
}