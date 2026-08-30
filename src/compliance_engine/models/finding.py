"""Formalized cross-document findings from anomaly detection."""

from typing import Any

from pydantic import BaseModel, field_validator

from compliance_engine.flags import get_flag_definition


class IdentityFinding(BaseModel):
    """A formally structured cross-document identity mismatch finding.
    
    Represents the result of deterministic cross-document identity comparison.
    Not a compliance result—purely an anomaly detection output.
    """

    flag_id: str
    capability: str
    message: str
    evidence_refs: list[str]
    compared_values: list[Any]
    normalized_values: list[str]
    left_document_id: str
    right_document_id: str

    @field_validator("flag_id")
    @classmethod
    def validate_flag_id(cls, v: str) -> str:
        """Ensure flag_id corresponds to a registered flag."""
        definition = get_flag_definition(v)
        return definition.flag_id

    @field_validator("normalized_values")
    @classmethod
    def validate_normalized_values(cls, v: list[str], info) -> list[str]:
        """Ensure normalized_values correspond to compared_values in order."""
        if "compared_values" in info.data:
            compared = info.data["compared_values"]
            if len(v) != len(compared):
                raise ValueError(
                    f"normalized_values length {len(v)} must match compared_values length {len(compared)}"
                )
        return v
