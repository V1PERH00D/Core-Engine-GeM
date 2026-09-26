from pydantic import BaseModel, Field
from typing import Optional

class CAUDINExtraction(BaseModel):
    ca_udin: Optional[str] = Field(None, description="18-digit ICAI Unique Document Identification Number")
    ca_member_number: Optional[str] = Field(None, description="6-digit ICAI membership number")
    certified_figure_inr_cr: Optional[float] = Field(None, description="Financial turnover figure certified")