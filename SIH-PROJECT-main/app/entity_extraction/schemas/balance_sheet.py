from pydantic import BaseModel, Field
from typing import List, Optional

class TurnoverRecord(BaseModel):
    financial_year: str = Field(..., description="E.g., FY 2022-23, FY 2023-24, FY 2024-25")
    turnover_in_inr_cr: float = Field(..., description="Turnover converted strictly to INR Crores")

class BalanceSheetExtraction(BaseModel):
    turnover_records: List[TurnoverRecord] = Field(default_factory=list)
    net_worth_inr_cr: Optional[float] = Field(default=None, description="Total net worth in INR Crores")
    is_solvency_positive: Optional[bool] = Field(default=None, description="True if Net Worth > 0")
    net_profit_inr_cr: Optional[float] = Field(default=None, description="Reported Net Profit in INR Crores")
    share_captital_inr_cr: Optional[float] = Field(default=None, description="Total shares in INR")
    reserves_surplus_inr_cr: Optional[float] = Field(default=None, description="Total reserves in INR")
    accumulated_losses_inr_cr: Optional[float] = Field(default=0.0, description="Total lossess accumulated in INR")
