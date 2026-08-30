"""Normalized bidder-submitted evidence."""

from typing import Annotated, Any

from pydantic import BaseModel, Field

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
PageNumber = Annotated[int, Field(gt=0)]
BoundingBox = Annotated[list[float], Field(min_length=4, max_length=4)]


class Evidence(BaseModel):
    """One normalized field extracted from a bidder-submitted document."""

    evidence_id: str
    bidder_id: str
    document_id: str
    document_type: str
    field_name: str
    value: Any
    confidence: Confidence | None = None
    page: PageNumber | None = None
    bbox: BoundingBox | None = None
