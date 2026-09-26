from pydantic import BaseModel, Field
from typing import Optional

class UdyamExtraction(BaseModel):
    udyam_registration_number: Optional[str] = Field(None, description="Format: UDYAM-XX-00-0000000")
    enterprise_name: Optional[str] = Field(None, description="Name of enterprise")
    enterprise_category: Optional[str] = Field(None, description="Micro, Small, or Medium")
    major_activity: Optional[str] = Field(None, description="Manufacturing or Services")
    nic_2_digit_code: Optional[str] = Field(None, description="2-digit National Industry Classification code")