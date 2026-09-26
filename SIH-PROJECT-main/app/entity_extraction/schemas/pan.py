from pydantic import BaseModel, Field
from typing import Optional

class PANITRExtraction(BaseModel):
    pan_number: Optional[str] = Field(None, description="10-character alphanumeric PAN")
    taxpayer_name: Optional[str] = Field(None, description="Name as per PAN / ITR filing")
    assessment_year: Optional[str] = Field(None, description="E.g., 2024-25")
    itr_form_type: Optional[str] = Field(None, description="ITR-3, ITR-4, ITR-5, ITR-6")
    pan_aadhaar_linked: Optional[bool] = Field(None, description="PAN-Aadhaar linkage verification status")