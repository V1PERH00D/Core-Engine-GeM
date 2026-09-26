from pydantic import BaseModel, Field
from typing import Optional

class GSTCertExtraction(BaseModel):
    gstin: Optional[str] = Field(None, description="15-character GST Identification Number")
    legal_name: Optional[str] = Field(None, description="Legal business name on GST record")
    trade_name: Optional[str] = Field(None, description="Trade name")
    taxpayer_type: Optional[str] = Field(None, description="Regular / Composition")
    constitution_of_business: Optional[str] = Field(None, description="E.g., Private Limited, Partnership")
    registration_date: Optional[str] = Field(None, description="Date of GST registration")