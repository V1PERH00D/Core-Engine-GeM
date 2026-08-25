import uuid
from pydantic import BaseModel, Field

# --- 1. Versioning Constants (Immutable per release) ---
# Workstream A (Rules Engine)
MODULE_2_RULE_VERSION = "v1.0.0-deterministic"

# Workstream B (AI Engine)
MODULE_3_MODEL_VERSION = "llama3-70b-8192-groq" 
MODULE_3_PROMPT_VERSION = "v1.1.0-anomaly-detection"

# --- 2. Prefixed ID Generators ---
def generate_id(prefix: str) -> str:
    """Generates a stable, traceable ID like 'DOC-550e8400-e29b...'"""
    return f"{prefix}-{str(uuid.uuid4())}"

def generate_bidder_id(): return generate_id("BID")
def generate_doc_id(): return generate_id("DOC")
def generate_extraction_id(): return generate_id("EXT")
def generate_check_id(check_type: str): return f"CHK-{check_type}-{str(uuid.uuid4())[:8]}" # e.g. CHK-GST-a1b2c3d4
def generate_evaluation_id(): return generate_id("EVAL")
def generate_flag_id(): return generate_id("FLAG")
def generate_evidence_id(): return generate_id("EVID")
def generate_decision_id(): return generate_id("DEC")

# --- 3. Audit Metadata Schemas ---
class Module2AuditMetadata(BaseModel):
    rule_version: str = Field(default=MODULE_2_RULE_VERSION)
    evaluation_id: str = Field(default_factory=generate_evaluation_id)

class Module3AuditMetadata(BaseModel):
    model_version: str = Field(default=MODULE_3_MODEL_VERSION)
    prompt_version: str = Field(default=MODULE_3_PROMPT_VERSION)
    flag_id: str = Field(default_factory=generate_flag_id)