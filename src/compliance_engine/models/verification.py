"""Authoritative verification records from government or other sources."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class VerificationStatus(StrEnum):
    """Outcome of querying an authoritative source. Not a compliance conclusion."""

    VERIFIED = "VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    INVALID = "INVALID"
    INACTIVE = "INACTIVE"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class Verification(BaseModel):
    """Payload returned by a government or other source adapter."""

    verification_id: str
    bidder_id: str
    capability: str
    source: str
    queried_identifier: str | None = None
    status: VerificationStatus
    data: dict[str, Any]
    retrieved_at: datetime
