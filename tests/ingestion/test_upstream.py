import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from compliance_engine.ingestion import evidence_id_for, normalize_upstream
from compliance_engine.models import Evidence

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "upstream"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _by_field(records: list[Evidence], field_name: str) -> list[Evidence]:
    return [item for item in records if item.field_name == field_name]


def test_sample_json_produces_evidence_objects() -> None:
    records = normalize_upstream(_load("sample.json"))
    assert records
    assert all(isinstance(item, Evidence) for item in records)


def test_sample_1_json_produces_evidence_objects() -> None:
    records = normalize_upstream(_load("sample_1.json"))
    assert records
    assert all(isinstance(item, Evidence) for item in records)


def test_gstin_becomes_evidence() -> None:
    gstin = _by_field(normalize_upstream(_load("sample.json")), "gstin")
    assert len(gstin) == 1
    assert gstin[0].document_type == "GST"
    assert gstin[0].value == "27AAACI1234F1Z5"
    assert gstin[0].document_id == "doc-uuid-gst-001"


def test_pan_becomes_evidence() -> None:
    pan = _by_field(normalize_upstream(_load("sample.json")), "pan_number")
    assert len(pan) == 1
    assert pan[0].document_type == "PAN"
    assert pan[0].value == "AAACI1234F"


def test_list_valued_fields_are_preserved() -> None:
    records = normalize_upstream(_load("sample.json"))
    turnovers = _by_field(records, "annual_turnovers")[0]
    dins = _by_field(records, "active_director_dins")[0]
    assert turnovers.value == [
        {"financial_year": "2022-23", "turnover": 12.5},
        {"financial_year": "2023-24", "turnover": 15.8},
        {"financial_year": "2024-25", "turnover": 18.2},
    ]
    assert dins.value == ["01234567", "09876543"]


def test_page_bbox_and_confidence_are_preserved() -> None:
    gstin = _by_field(normalize_upstream(_load("sample.json")), "gstin")[0]
    assert gstin.confidence == 0.99
    assert gstin.page == 1
    assert gstin.bbox == [50.0, 100.0, 250.0, 120.0]


def test_missing_null_values_are_preserved() -> None:
    records = normalize_upstream(_load("sample.json"))
    missing = _by_field(records, "return_period")[0]
    assert missing.value is None
    assert missing.confidence == 0.0
    assert missing.page is None
    assert missing.bbox is None


def test_evidence_ids_are_deterministic() -> None:
    payload = _load("sample.json")
    first = normalize_upstream(payload)
    second = normalize_upstream(payload)
    assert [item.evidence_id for item in first] == [item.evidence_id for item in second]
    gstin = _by_field(first, "gstin")[0]
    assert gstin.evidence_id == evidence_id_for(gstin.document_id, "gstin")
    assert gstin.evidence_id == "doc-uuid-gst-001:gstin"


def test_malformed_evidence_fails_clearly() -> None:
    payload = copy.deepcopy(_load("sample.json"))
    payload["documents"][0]["extracted_fields"]["gstin"]["bbox"] = [50.0, 100.0]
    with pytest.raises(ValidationError, match="gstin"):
        normalize_upstream(payload)
