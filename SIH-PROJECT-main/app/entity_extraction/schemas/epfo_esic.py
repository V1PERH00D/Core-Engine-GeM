from pydantic import BaseModel, Field
from typing import Optional

class EPFOESICExtraction(BaseModel):
    epfo_establishment_code: Optional[str] = Field(None, description="EPFO establishment code")
    esic_code: Optional[str] = Field(None, description="17-digit ESIC registration code")
    covered_employee_count: Optional[int] = Field(None, description="Contributing employee count")