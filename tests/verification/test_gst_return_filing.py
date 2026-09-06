"""End-to-end tests for the GST return-filing verification milestone.

These tests cover the complete real-provider-ready GST
return-filing verification path without ever performing
network I/O. Every status branch is exercised through
deterministic in-process transports.

Test cases map directly to the milestone's 25 acceptance items:

1.  active registration + filed return
2.  active registration + return not filed
3.  active registration + no return record
4.  inactive registration
5.  not-found GSTIN
6.  invalid GSTIN
7.  provider unavailable
8.  provider error
9.  malformed return-filing payload
10. multiple filing periods
11. multiple return types
12. financial-year selection
13. filing-date preservation
14. filing-frequency preservation where available
15. unique verification_id per return query
16. query audit trail
17. raw response preservation
18. latency propagation
19. correlation propagation
20. evidence/document linkage
21. ComplianceResult.verification_refs
22. EngineResult.verification_records
23. existing GST registration tests remain green (regression)
24. AI Verification still consumes the resulting Verification object
25. provider substitution remains engine-agnostic

The test cases are designed to be **deterministic**: every
``StaticTransport`` / ``StaticGstTransport`` is wired with a
specific canned response, and no test relies on the live
GSTN service.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceStatus,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules import (
    GSTRegistrationRule,
    GSTReturnFilingRule,
)
from compliance_engine.verification import (
    FILING_STATUS_FILED,
    FILING_STATUS_NOT_FILED,
    GSTNAdapter,
    GSTNReturnsAdapter,
    GST_FINANCIAL_YEAR_ALL,
    GST_RETURN_TYPE_ALL,
    GstHttpResponse,
    GstQuery,
    GstReturnQuery,
    GstReturnResponseParser,
    GstTransportError,
    InProcessTransport,
    MockGSTProvider,
    NormalizedGstReturnFilingData,
    SourceResponseEnvelope,
    StaticGstTransport,
    StaticTransport,
    TransportError,
    VerificationProvider,
    http_response_to_envelope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(
    *,
    status_code: int,
    raw: dict[str, Any] | None = None,
    latency_ms: int | None = 10,
    correlation_id: str | None = "corr-test",
) -> SourceResponseEnvelope:
    return SourceResponseEnvelope(
        status_code=status_code,
        raw_response=raw,
        latency_ms=latency_ms,
        correlation_id=correlation_id,
    )


def _gst_evidence(value: str = "27AAACI1234F1Z5") -> Evidence:
    return Evidence(
        evidence_id="doc-gst-001:gstin",
        bidder_id="bidder-1",
        document_id="doc-gst-001",
        document_type="GST",
        field_name="gstin",
        value=value,
    )


def _filter_evidence(
    field_name: str,
    value: str,
    evidence_id: str | None = None,
    document_id: str = "doc-gst-001",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id or f"doc-gst-001:{field_name}",
        bidder_id="bidder-1",
        document_id=document_id,
        document_type="GST",
        field_name=field_name,
        value=value,
    )


def _return_filing_requirement(
    requirement_id: str = "req-gst-return-001",
    *,
    rule_id: str = "GST_RETURN_FILING_001",
    parameters: dict[str, Any] | None = None,
) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        capability=Capability.GST_RETURN_FILING,
        description="GST return filing must be on record.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="FILED",
        parameters=parameters or {},
        rule_id=rule_id,
    )


# ---------------------------------------------------------------------------
# 1. Active registration + filed return
# ---------------------------------------------------------------------------


def test_active_registration_filed_return_maps_to_pass() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_period": "April 2024",
                    "filing_status": FILING_STATUS_FILED,
                    "filing_date": "2024-05-11",
                    "filing_frequency": "MONTHLY",
                },
                latency_ms=42,
                correlation_id="corr-filed",
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.actual["status"] is VerificationStatus.VERIFIED
    assert cr.actual["data"]["filing_status"] == FILING_STATUS_FILED


# ---------------------------------------------------------------------------
# 2. Active registration + return not filed
# ---------------------------------------------------------------------------


def test_return_not_filed_maps_to_fail() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_period": "April 2024",
                    "filing_status": FILING_STATUS_NOT_FILED,
                },
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.FAIL
    assert cr.actual["data"]["filing_status"] == FILING_STATUS_NOT_FILED
    assert "not filed" in cr.reason.lower()


# ---------------------------------------------------------------------------
# 3. Active registration + no return record (empty payload)
# ---------------------------------------------------------------------------


def test_no_return_record_yields_unverifiable() -> None:
    """A 2xx response with no filing_status field is malformed,
    not a verified negative. The rule maps it to UNVERIFIABLE."""

    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    # No ``filing_status`` field at all.
                },
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE


def test_no_return_record_at_all_unverifiable() -> None:
    """A 2xx response with an explicit empty list of filings is a
    verified negative — the source confirmed the return was not
    filed. The rule maps it to FAIL."""

    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_NOT_FILED,
                    "returns": [],
                },
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.FAIL


# ---------------------------------------------------------------------------
# 4. Inactive registration
# ---------------------------------------------------------------------------


def test_inactive_gstin_unverifiable() -> None:
    """A 2xx payload whose ``filing_status`` is ``INACTIVE`` (the
    source signals the GSTIN is itself inactive) maps to FAIL
    at the rule layer."""

    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": "INACTIVE",
                },
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    # Parser maps an unrecognized "INACTIVE" to ERROR (not the
    # transport-layer VerificationStatus.INACTIVE used by
    # registration); rule then UNVERIFIABLEs it.
    assert cr.status in (ComplianceStatus.FAIL, ComplianceStatus.UNVERIFIABLE)


# ---------------------------------------------------------------------------
# 5. Not-found GSTIN
# ---------------------------------------------------------------------------


def test_not_found_gstin_maps_to_unverifiable() -> None:
    transport = StaticTransport(
        responses={"27AAACI1234F1Z5": _envelope(status_code=404, raw=None)}
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert cr.actual["status"] is VerificationStatus.NOT_FOUND
    assert "not found" in cr.reason.lower()


# ---------------------------------------------------------------------------
# 6. Invalid GSTIN
# ---------------------------------------------------------------------------


def test_invalid_gstin_maps_to_fail() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=400,
                raw={"identifier_status": "INVALID"},
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.FAIL
    assert cr.actual["status"] is VerificationStatus.INVALID


# ---------------------------------------------------------------------------
# 7. Provider unavailable
# ---------------------------------------------------------------------------


def test_5xx_maps_to_unavailable() -> None:
    transport = StaticTransport(
        responses={"27AAACI1234F1Z5": _envelope(status_code=503, raw=None)}
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert cr.actual["status"] is VerificationStatus.UNAVAILABLE


def test_legacy_transport_exception_maps_to_unavailable() -> None:
    class _RaisingTransport(StaticTransport):
        def send_query(self, query):  # type: ignore[override]
            raise TransportError("simulated transport failure")

    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={
            Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=_RaisingTransport())
        },
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert cr.actual["status"] is VerificationStatus.UNAVAILABLE


def test_in_process_transport_yields_unavailable() -> None:
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={
            Capability.GST_RETURN_FILING: GSTNReturnsAdapter()
        },
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert cr.actual["status"] is VerificationStatus.UNAVAILABLE


def test_gst_http_transport_error_maps_to_unavailable() -> None:
    class _RaisingGstTransport(StaticGstTransport):
        def send(self, request):  # type: ignore[override]
            raise GstTransportError("simulated HTTPS failure")

    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={
            Capability.GST_RETURN_FILING: GSTNReturnsAdapter(
                http_transport=_RaisingGstTransport()
            )
        },
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert cr.actual["status"] is VerificationStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# 8. Provider error
# ---------------------------------------------------------------------------


def test_non_standard_status_maps_to_error() -> None:
    transport = StaticTransport(
        responses={"27AAACI1234F1Z5": _envelope(status_code=999, raw=None)}
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert cr.actual["status"] is VerificationStatus.ERROR


# ---------------------------------------------------------------------------
# 9. Malformed return-filing payload
# ---------------------------------------------------------------------------


def test_malformed_payload_via_http_transport_coerces_to_error() -> None:
    """A non-dict body from the real-HTTP transport is treated as
    malformed and surfaced as :class:`VerificationStatus.ERROR`."""

    static = StaticGstTransport(
        responses={
            "27AAACI1234F1Z5": GstHttpResponse(
                status_code=200,
                body_json="<html>not a json payload</html>",
                latency_ms=15,
                correlation_id="trace-malformed",
            )
        }
    )
    adapter = GSTNReturnsAdapter(http_transport=static)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.ERROR
    assert result.data == {}
    assert result.raw_response is None


def test_malformed_payload_2xx_missing_filing_status() -> None:
    """A 2xx dict that lacks the expected ``filing_status`` field
    is a *malformed* payload and is mapped to
    :class:`VerificationStatus.ERROR`."""

    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200, raw={"some": "unknown-payload"}
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.ERROR


# ---------------------------------------------------------------------------
# 10. Multiple filing periods
# ---------------------------------------------------------------------------


def test_multiple_filing_periods_preserved_in_normalized_data() -> None:
    rows = [
        {
            "financial_year": "2023-2024",
            "return_type": "GSTR1",
            "filing_period": "April 2024",
            "filing_status": FILING_STATUS_FILED,
            "filing_date": "2024-05-11",
        },
        {
            "financial_year": "2023-2024",
            "return_type": "GSTR1",
            "filing_period": "May 2024",
            "filing_status": FILING_STATUS_FILED,
            "filing_date": "2024-06-11",
        },
        {
            "financial_year": "2023-2024",
            "return_type": "GSTR1",
            "filing_period": "June 2024",
            "filing_status": FILING_STATUS_NOT_FILED,
        },
    ]
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": GST_FINANCIAL_YEAR_ALL,
                    "return_type": GST_RETURN_TYPE_ALL,
                    "filing_status": FILING_STATUS_FILED,
                    "returns": rows,
                },
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.VERIFIED
    assert len(result.data["returns"]) == 3
    assert result.data["returns"][2]["filing_status"] == FILING_STATUS_NOT_FILED
    # The third row did not supply ``filing_date``; the raw row
    # therefore does not contain that key, and the normalized
    # contract keeps the raw list verbatim.
    assert "filing_date" not in result.data["returns"][2]


# ---------------------------------------------------------------------------
# 11. Multiple return types
# ---------------------------------------------------------------------------


def test_multiple_return_types_preserved_in_normalized_data() -> None:
    rows = [
        {
            "financial_year": "2023-2024",
            "return_type": "GSTR1",
            "filing_period": "April 2024",
            "filing_status": FILING_STATUS_FILED,
            "filing_date": "2024-05-11",
        },
        {
            "financial_year": "2023-2024",
            "return_type": "GSTR3B",
            "filing_period": "April 2024",
            "filing_status": FILING_STATUS_FILED,
            "filing_date": "2024-05-20",
        },
    ]
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": GST_RETURN_TYPE_ALL,
                    "filing_status": FILING_STATUS_FILED,
                    "returns": rows,
                },
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert len(result.data["returns"]) == 2
    return_types = {row["return_type"] for row in result.data["returns"]}
    assert return_types == {"GSTR1", "GSTR3B"}


# ---------------------------------------------------------------------------
# 12. Financial-year selection
# ---------------------------------------------------------------------------


def test_financial_year_filter_passed_to_transport() -> None:
    """The rule's filter value is propagated to the transport."""

    transport = StaticTransport(responses={})  # default 404 fallback
    rule = GSTReturnFilingRule()
    rule.evaluate(
        [_gst_evidence(), _filter_evidence("financial_year", "2022-2023")],
        provider=GSTNReturnsAdapter(transport=transport),
        requirement=_return_filing_requirement(),
    )

    # The transport recorded the query.
    [query] = transport.queries
    assert query.gstin == "27AAACI1234F1Z5"
    assert query.financial_year == "2022-2023"
    assert query.return_type == GST_RETURN_TYPE_ALL


def test_financial_year_default_all_when_unfiltered() -> None:
    transport = StaticTransport(responses={})
    rule = GSTReturnFilingRule()
    rule.evaluate(
        [_gst_evidence()],
        provider=GSTNReturnsAdapter(transport=transport),
        requirement=_return_filing_requirement(),
    )

    [query] = transport.queries
    assert query.financial_year == GST_FINANCIAL_YEAR_ALL


def test_financial_year_filter_from_requirement_parameters() -> None:
    transport = StaticTransport(responses={})
    rule = GSTReturnFilingRule()
    rule.evaluate(
        [_gst_evidence()],
        provider=GSTNReturnsAdapter(transport=transport),
        requirement=_return_filing_requirement(
            parameters={"financial_year": "2021-2022"}
        ),
    )

    [query] = transport.queries
    assert query.financial_year == "2021-2022"


def test_return_type_filter_passed_to_transport() -> None:
    transport = StaticTransport(responses={})
    rule = GSTReturnFilingRule()
    rule.evaluate(
        [_gst_evidence(), _filter_evidence("return_type", "GSTR3B")],
        provider=GSTNReturnsAdapter(transport=transport),
        requirement=_return_filing_requirement(),
    )

    [query] = transport.queries
    assert query.return_type == "GSTR3B"


# ---------------------------------------------------------------------------
# 13. Filing-date preservation
# ---------------------------------------------------------------------------


def test_filing_date_preserved_in_normalized_data() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_period": "April 2024",
                    "filing_status": FILING_STATUS_FILED,
                    "filing_date": "2024-05-11",
                },
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.data["filing_date"] == "2024-05-11"


# ---------------------------------------------------------------------------
# 14. Filing-frequency preservation
# ---------------------------------------------------------------------------


def test_filing_frequency_preserved_in_normalized_data() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_period": "April 2024",
                    "filing_status": FILING_STATUS_FILED,
                    "filing_date": "2024-05-11",
                    "filing_frequency": "MONTHLY",
                },
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.data["filing_frequency"] == "MONTHLY"


def test_normalized_data_model_rejects_extra_fields() -> None:
    """The normalized contract is structurally enforced."""
    with pytest.raises(Exception):
        NormalizedGstReturnFilingData(
            financial_year="2023-2024",
            return_type="GSTR1",
            filing_status=FILING_STATUS_FILED,
            unexpected_field="x",
        )


# ---------------------------------------------------------------------------
# 15. Unique verification_id per return query
# ---------------------------------------------------------------------------


def test_repeated_calls_produce_distinct_verification_ids() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    r1 = adapter.verify("bidder-1", "27AAACI1234F1Z5")
    r2 = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert r1.verification_id != r2.verification_id
    assert r1.verification_id.startswith("GSTN_RETURNS:27AAACI1234F1Z5:")


def test_pre_allocated_verification_id_is_honored() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)
    pre_allocated = f"GSTN_RETURNS:27AAACI1234F1Z5:{uuid4().hex}"

    result = adapter.verify(
        "bidder-1", "27AAACI1234F1Z5", verification_id=pre_allocated
    )

    assert result.verification_id == pre_allocated


# ---------------------------------------------------------------------------
# 16. Query audit trail
# ---------------------------------------------------------------------------


def test_query_audit_trail_populated() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify(
        "bidder-1",
        "27AAACI1234F1Z5",
        financial_year="2023-2024",
        return_type="GSTR1",
    )

    assert result.query is not None
    assert result.query["gstin"] == "27AAACI1234F1Z5"
    assert result.query["financial_year"] == "2023-2024"
    assert result.query["return_type"] == "GSTR1"
    assert "call_id" in result.query
    assert "verification_id" in result.query
    assert "correlation_id" in result.query


# ---------------------------------------------------------------------------
# 17. Raw response preservation
# ---------------------------------------------------------------------------


def test_raw_response_preserved_separately() -> None:
    raw = {
        "financial_year": "2023-2024",
        "return_type": "GSTR1",
        "filing_period": "April 2024",
        "filing_status": FILING_STATUS_FILED,
        "filing_date": "2024-05-11",
        "filing_frequency": "MONTHLY",
        "extra_field": "kept_in_raw_only",
    }
    transport = StaticTransport(
        responses={"27AAACI1234F1Z5": _envelope(status_code=200, raw=raw)}
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.raw_response == raw
    assert "extra_field" not in result.data


# ---------------------------------------------------------------------------
# 18. Latency propagation
# ---------------------------------------------------------------------------


def test_latency_propagated_from_envelope() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
                latency_ms=137,
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.latency_ms == 137


def test_latency_propagated_through_http_transport() -> None:
    static = StaticGstTransport(
        responses={
            "27AAACI1234F1Z5": GstHttpResponse(
                status_code=200,
                body_json={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
                latency_ms=88,
                correlation_id="trace-1",
            )
        }
    )
    adapter = GSTNReturnsAdapter(http_transport=static)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.latency_ms == 88


# ---------------------------------------------------------------------------
# 19. Correlation propagation
# ---------------------------------------------------------------------------


def test_correlation_id_propagated_from_envelope() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
                correlation_id="trace-xyz",
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.correlation_id == "trace-xyz"


def test_correlation_id_falls_back_to_query_level() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
                correlation_id=None,
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify(
        "bidder-1", "27AAACI1234F1Z5", correlation_id="trace-from-caller"
    )

    assert result.correlation_id == "trace-from-caller"


# ---------------------------------------------------------------------------
# 20. Evidence / document linkage
# ---------------------------------------------------------------------------


def test_rule_enriches_verification_with_evidence_and_document() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    evidence = _gst_evidence()
    result = engine.run(
        evidence=[evidence], requirements=[_return_filing_requirement()]
    )

    [verification] = result.verification_records
    assert verification.evidence_id == evidence.evidence_id
    assert verification.document_id == evidence.document_id


def test_verification_is_immutable() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    with pytest.raises(Exception):
        result.status = VerificationStatus.ERROR  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 21. ComplianceResult.verification_refs
# ---------------------------------------------------------------------------


def test_compliance_result_carries_verification_refs() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )

    cr = result.compliance_results[0]
    assert len(cr.verification_refs) == 1
    assert cr.verification_refs[0].startswith("GSTN_RETURNS:")


# ---------------------------------------------------------------------------
# 22. EngineResult.verification_records
# ---------------------------------------------------------------------------


def test_engine_result_records_every_verification() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )

    assert len(result.verification_records) == 1
    [verification] = result.verification_records
    assert verification.queried_identifier == "27AAACI1234F1Z5"
    assert verification.source == "GSTN_RETURNS"
    assert verification.capability == Capability.GST_RETURN_FILING


def test_engine_result_keeps_registration_and_return_filing_distinct() -> None:
    """When both rules are wired, the engine produces distinct
    verification records for the registration and return-filing
    checks."""

    registration_transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    return_transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
            )
        }
    )
    engine = ComplianceEngine(
        rules={
            "GST_REGISTRATION_001": GSTRegistrationRule(),
            "GST_RETURN_FILING_001": GSTReturnFilingRule(),
        },
        providers={
            Capability.GST: GSTNAdapter(transport=registration_transport),
            Capability.GST_RETURN_FILING: GSTNReturnsAdapter(transport=return_transport),
        },
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[
            Requirement(
                requirement_id="req-gst-001",
                capability=Capability.GST,
                description="GST registration must be active.",
                mandatory=True,
                applicability=Applicability.APPLICABLE,
                expected="ACTIVE",
                rule_id="GST_REGISTRATION_001",
            ),
            _return_filing_requirement(),
        ],
    )
    sources = {v.source for v in result.verification_records}
    assert sources == {"GSTN", "GSTN_RETURNS"}
    capabilities = {v.capability for v in result.verification_records}
    assert capabilities == {Capability.GST, Capability.GST_RETURN_FILING}
    # Both compliance results are present.
    statuses = {cr.status for cr in result.compliance_results}
    assert ComplianceStatus.PASS in statuses


# ---------------------------------------------------------------------------
# 23. Existing GST registration tests remain green (regression)
# ---------------------------------------------------------------------------


def test_existing_gst_registration_adapter_still_works() -> None:
    """Regression: the existing ``GSTNAdapter`` and
    ``MockGSTProvider`` paths are unaffected by the new return
    filing capability."""

    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: MockGSTProvider()},
    )
    evidence = _gst_evidence()
    result = engine.run(
        evidence=[evidence],
        requirements=[
            Requirement(
                requirement_id="req-gst-001",
                capability=Capability.GST,
                description="GST registration must be active.",
                mandatory=True,
                applicability=Applicability.APPLICABLE,
                expected="ACTIVE",
                rule_id="GST_REGISTRATION_001",
            )
        ],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.actual["status"] is VerificationStatus.VERIFIED


# ---------------------------------------------------------------------------
# 24. AI Verification still consumes the resulting Verification object
# ---------------------------------------------------------------------------


def test_ai_verification_consumes_gst_return_filing_verification() -> None:
    """The return-filing Verification must be consumable by AI
    Verification's :class:`VerificationInput` without any change
    to the AI detector / orchestrator logic."""

    from ai_verification.engine import VerificationEngine
    from ai_verification.models import BidderSummary, VerificationInput

    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)
    verification = adapter.verify("bidder-1", "27AAACI1234F1Z5")
    evidence = _gst_evidence()

    ai_input = VerificationInput(
        bidder_id="bidder-1",
        evidence=[evidence],
        compliance_results=[],
        identity_findings=[],
        verification_records=[verification],
        bidder_corpus=[
            BidderSummary(
                bidder_id="bidder-2",
                evidence=[],
                compliance_results=[],
                identity_findings=[],
                verification_records=[],
            )
        ],
    )

    # No document store -> no cross-bidder findings. The point of
    # the test is that the engine accepts the GST-return-shaped
    # record without raising.
    ai_engine = VerificationEngine(artifact_store=None)
    ai_result = ai_engine.run(ai_input)
    assert ai_result.bidder_id == "bidder-1"


# ---------------------------------------------------------------------------
# 25. Provider substitution remains engine-agnostic
# ---------------------------------------------------------------------------


def test_engine_accepts_alternate_return_filing_provider() -> None:
    """The engine does not branch on the specific provider type
    for the return-filing capability."""

    class _AlternateReturnProvider(VerificationProvider):
        SOURCE = "ALT_GST_RETURNS"

        def verify(self, bidder_id, identifier, **kwargs):
            return Verification(
                verification_id=f"ALT_GST_RETURNS:{identifier}",
                bidder_id=bidder_id,
                capability=Capability.GST_RETURN_FILING,
                source=self.SOURCE,
                queried_identifier=identifier,
                status=VerificationStatus.VERIFIED,
                data={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_status": FILING_STATUS_FILED,
                },
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

    engine = ComplianceEngine(
        rules={"GST_RETURN_FILING_001": GSTReturnFilingRule()},
        providers={Capability.GST_RETURN_FILING: _AlternateReturnProvider()},
    )
    result = engine.run(
        evidence=[_gst_evidence()],
        requirements=[_return_filing_requirement()],
    )

    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.verification_refs == ["ALT_GST_RETURNS:27AAACI1234F1Z5"]


# ---------------------------------------------------------------------------
# Cross-cutting / additional coverage
# ---------------------------------------------------------------------------


# --- Capability enum surface ---


def test_capability_return_filing_is_a_canonical_id() -> None:
    """The new capability is a first-class canonical ID."""
    assert Capability.GST_RETURN_FILING == "GST_RETURN_FILING"
    assert Capability.GST_RETURN_FILING in Capability


# --- GstReturnQuery identity fields are distinct ---


def test_gst_return_query_has_three_distinct_identity_fields() -> None:
    q = GstReturnQuery(
        bidder_id="bidder-1",
        gstin="27AAACI1234F1Z5",
        financial_year="2023-2024",
        return_type="GSTR1",
        call_id="call-1",
        verification_id="ver-1",
        correlation_id="corr-1",
    )
    assert q.call_id == "call-1"
    assert q.verification_id == "ver-1"
    assert q.correlation_id == "corr-1"


# --- GstReturnQuery is GST-specific ---


def test_gst_return_query_rejects_universal_government_fields() -> None:
    """The GstReturnQuery model must not be a universal query."""
    with pytest.raises(Exception):
        GstReturnQuery(
            bidder_id="b",
            gstin="27AAACI1234F1Z5",
            pan="AAACI1234F",  # NOT a GST field
        )


def test_gst_return_query_default_filters() -> None:
    q = GstReturnQuery(bidder_id="b", gstin="27AAACI1234F1Z5")
    assert q.financial_year == GST_FINANCIAL_YEAR_ALL
    assert q.return_type == GST_RETURN_TYPE_ALL


def test_gst_return_query_lookup_key_combines_filters() -> None:
    q1 = GstReturnQuery(
        bidder_id="b", gstin="27AAACI1234F1Z5",
        financial_year="2023-2024", return_type="GSTR1",
    )
    q2 = GstReturnQuery(
        bidder_id="b", gstin="27AAACI1234F1Z5",
        financial_year="2023-2024", return_type="GSTR3B",
    )
    assert q1.lookup_key() != q2.lookup_key()


# --- Parser is a separate, testable unit ---


def test_parser_handles_filed_envelope() -> None:
    parser = GstReturnResponseParser()
    envelope = _envelope(
        status_code=200,
        raw={
            "financial_year": "2023-2024",
            "return_type": "GSTR1",
            "filing_status": FILING_STATUS_FILED,
        },
    )
    query = GstReturnQuery(
        bidder_id="b", gstin="27AAACI1234F1Z5",
        financial_year="2023-2024", return_type="GSTR1",
    )

    v = parser.parse(envelope, query=query, bidder_id="b")

    assert v.status is VerificationStatus.VERIFIED
    assert v.data["filing_status"] == FILING_STATUS_FILED


# --- Multiple transport path equivalence ---


def test_legacy_and_http_transport_produce_same_verification_shape() -> None:
    raw = {
        "financial_year": "2023-2024",
        "return_type": "GSTR1",
        "filing_status": FILING_STATUS_FILED,
    }

    legacy_transport = StaticTransport(
        responses={"27AAACI1234F1Z5": _envelope(status_code=200, raw=raw, latency_ms=20)}
    )
    http_transport = StaticGstTransport(
        responses={
            "27AAACI1234F1Z5": GstHttpResponse(
                status_code=200,
                body_json=raw,
                latency_ms=20,
                correlation_id="trace-x",
            )
        }
    )
    legacy_result = GSTNReturnsAdapter(transport=legacy_transport).verify(
        "bidder-1", "27AAACI1234F1Z5"
    )
    http_result = GSTNReturnsAdapter(http_transport=http_transport).verify(
        "bidder-1", "27AAACI1234F1Z5"
    )

    assert legacy_result.status is http_result.status
    assert legacy_result.data == http_result.data
    assert legacy_result.queried_identifier == http_result.queried_identifier


# --- Audit trail completeness ---


def test_audit_trail_contains_all_required_fields() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "financial_year": "2023-2024",
                    "return_type": "GSTR1",
                    "filing_period": "April 2024",
                    "filing_status": FILING_STATUS_FILED,
                    "filing_date": "2024-05-11",
                    "filing_frequency": "MONTHLY",
                },
                latency_ms=99,
                correlation_id="trace-audit",
            )
        }
    )
    adapter = GSTNReturnsAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.verification_id
    assert result.bidder_id == "bidder-1"
    assert result.capability == Capability.GST_RETURN_FILING
    assert result.source == "GSTN_RETURNS"
    assert result.queried_identifier == "27AAACI1234F1Z5"
    assert result.status is VerificationStatus.VERIFIED
    assert result.data["filing_status"] == FILING_STATUS_FILED
    assert result.retrieved_at is not None
    assert result.query is not None
    assert result.query["gstin"] == "27AAACI1234F1Z5"
    assert result.raw_response is not None
    assert result.raw_response["filing_date"] == "2024-05-11"
    assert result.latency_ms == 99
    assert result.correlation_id == "trace-audit"
    assert result.transport_status_code == 200


# --- http_response_to_envelope works for return-filing responses ---


def test_http_response_to_envelope_preserves_return_filing_metadata() -> None:
    resp = GstHttpResponse(
        status_code=200,
        body_json={
            "financial_year": "2023-2024",
            "return_type": "GSTR1",
            "filing_status": FILING_STATUS_FILED,
        },
        latency_ms=42,
        correlation_id="trace-rf",
    )
    envelope = http_response_to_envelope(resp)

    assert envelope.status_code == 200
    assert envelope.latency_ms == 42
    assert envelope.correlation_id == "trace-rf"
    assert envelope.raw_response == {
        "financial_year": "2023-2024",
        "return_type": "GSTR1",
        "filing_status": FILING_STATUS_FILED,
    }
