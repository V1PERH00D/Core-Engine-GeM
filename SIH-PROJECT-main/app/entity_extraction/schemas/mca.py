from pydantic import BaseModel, Field
from typing import List, Optional

class MCA21Extraction(BaseModel):
    cin: Optional[str] = Field(None, description="21-character Corporate Identification Number")
    company_name: Optional[str] = Field(None, description="Registered legal company name")
    paid_up_capital_inr: Optional[float] = Field(None, description="Paid up capital in INR")
    active_director_dins: List[str] = Field(default_factory=list, description="List of 8-digit DINs")