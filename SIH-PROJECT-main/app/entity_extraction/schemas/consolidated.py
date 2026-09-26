from pydantic import BaseModel, Field
from typing import Optional, List
from app.entity_extraction.schemas.gst import GSTCertExtraction
from app.entity_extraction.schemas.pan import PANITRExtraction
from app.entity_extraction.schemas.udyam import UdyamExtraction
from app.entity_extraction.schemas.balance_sheet import BalanceSheetExtraction
from app.entity_extraction.schemas.mca import MCA21Extraction
from app.entity_extraction.schemas.mii import MakeInIndiaExtraction
from app.entity_extraction.schemas.epfo_esic import EPFOESICExtraction
from app.entity_extraction.schemas.ca_udin import CAUDINExtraction

# 1. Forensic metadata model (defined FIRST)
class DocumentForensics(BaseModel):
    pdf_producer: Optional[str] = Field(default=None, description="Producer/Creator metadata from PDF header")
    has_digital_signature: bool = Field(default=False, description="Whether digital signature/DSC was detected")
    font_anomaly_detected: bool = Field(default=False, description="Flag for mismatched font layers or tampering")

# 2. Master consolidated schema
class ConsolidatedBidderExtraction(BaseModel):
    submission_id: str
    gst: GSTCertExtraction = Field(default_factory=GSTCertExtraction)
    pan_itr: PANITRExtraction = Field(default_factory=PANITRExtraction)
    udyam: UdyamExtraction = Field(default_factory=UdyamExtraction)
    balance_sheet: BalanceSheetExtraction = Field(default_factory=BalanceSheetExtraction)
    mca21: MCA21Extraction = Field(default_factory=MCA21Extraction)
    make_in_india: MakeInIndiaExtraction = Field(default_factory=MakeInIndiaExtraction)
    epfo_esic: EPFOESICExtraction = Field(default_factory=EPFOESICExtraction)
    ca_udin: CAUDINExtraction = Field(default_factory=CAUDINExtraction)
    
    # Cartel & Collusion Detection Signals (Optional strings to prevent validation crashes)
    registered_pincode: Optional[str] = Field(default=None, description="PIN code extracted from registered business address")
    registered_email: Optional[str] = Field(default=None, description="Official communication email for collusion checks")
    registered_phone: Optional[str] = Field(default=None, description="Official contact number for collusion checks")
    signatory_name: Optional[str] = Field(default=None, description="Authorized signatory name on self-declarations")
    
    # Document Forensics & Verification Flags
    document_forensics: DocumentForensics = Field(default_factory=DocumentForensics)
    startup_india_number: Optional[str] = None
    nsic_certificate_number: Optional[str] = None
    oem_authorization_found: bool = False
    digilocker_verified: bool = False