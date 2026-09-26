from pydantic import BaseModel, Field
from typing import Optional

class MakeInIndiaExtraction(BaseModel):
    declared_local_content_pct: Optional[float] = Field(None, description="Percentage of local value addition")
    supplier_class: Optional[str] = Field(None, description="Class-I (>=50%), Class-II (>=20%), Non-Local (<20%)")
    location_of_value_addition: Optional[str] = Field(None, description="Factory / city location declared")