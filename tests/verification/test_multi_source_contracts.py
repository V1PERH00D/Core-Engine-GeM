"""Multi-source provider contract tests.

These tests prove that the Compliance Engine can support multiple
government verification sources (GST, Udyam, PAN, MCA) through the
same :class:`VerificationProvider` contract, with no source-specific
branching inside the engine.

The tests are organised by concern:

1. Per-source contract tests (status mapping, normalized data, raw
   response preservation, audit fields, immutability, fresh object).
2. Engine substitutability tests (any ``VerificationProvider`` for a
   capability can be swapped in without engine changes).
3. Cross-source contract invariants (every provider returns a valid
   ``Verification``; provider failures are distinct from verified
   negatives; verification_refs point to verification_id; raw
   response is preserved separately).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
    PANValidationRule,
    UdyamRegistrationRule,
)
from compliance_engine.verification import (
    GSTNAdapter,
    InProcessTransport,
    McaAdapter,
    McaQuery,
    MockGSTProvider,
    MockPANProvider,
    MockUdyamProvider,
    NormalizedGstData,
    NormalizedMcaData,
    NormalizedPanData,
    NormalizedUdyamData,
    PanAdapter,
    PanQuery,
    SourceResponseEnvelope,
    StaticTransport,
    TransportError,
    UdyamAdapter,
    UdyamQuery,
    VerificationProvider,
)

from tests.engine._builders import (
    gst_evidence,
    gst_requirement,
    pan_evidence,
    pan_requirement,
    udyam_evidence,
    udyam_requirement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env(
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


# Per-source transport factories. The Udyam/PAN/MCA adapters do not
# (and should not) have a hardcoded ``gstin`` key; the tests inject
# the correct ``query_key`` so a single ``StaticTransport`` shape can
# be reused across sources.

def _udyam_transport(responses: dict[str, SourceResponseEnvelope]) -> StaticTransport:
    return StaticTransport(
        responses=responses, query_key=lambda q: q.udyam_registration_number
    )


def _pan_transport(responses: dict[str, SourceResponseEnvelope]) -> StaticTransport:
    return StaticTransport(responses=responses, query_key=lambda q: q.pan)


def _mca_transport(responses: dict[str, SourceResponseEnvelope]) -> StaticTransport:
    return StaticTransport(responses=responses, query_key=lambda q: q.cin)


# Common identifier constants per source
_GSTIN = "27AAACI1234F1Z5"
_UDYAM = "UDYAM-MH-12-0019842"
_PAN = "AAACI1234F"
_CIN = "L17110MH1973PLC012012"


# ===========================================================================
# GSTN adapter contract
# ===========================================================================


def test_gstn_adapter_verified_status() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    }))
    v = adapter.verify("bidder-1", _GSTIN)
    assert v.status is VerificationStatus.VERIFIED
    assert v.source == "GSTN"
    assert v.capability == Capability.GST


def test_gstn_adapter_not_found() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        "27AAAAA0000A1Z5": _env(status_code=404, raw=None),
    }))
    v = adapter.verify("bidder-1", "27AAAAA0000A1Z5")
    assert v.status is VerificationStatus.NOT_FOUND


def test_gstn_adapter_inactive() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        "27AAACI9999F1Z5": _env(status_code=410, raw={"registration_status": "INACTIVE", "legal_name": "ACME CO"}),
    }))
    v = adapter.verify("bidder-1", "27AAACI9999F1Z5")
    assert v.status is VerificationStatus.INACTIVE


def test_gstn_adapter_invalid() -> None:
    """A 4xx with a payload that has no recognizable domain field
    is treated as ``INVALID`` (the source rejected the identifier)."""
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        "27XXXXX9999X1Z5": _env(
            status_code=400,
            raw={"error": "malformed identifier"},
        ),
    }))
    v = adapter.verify("bidder-1", "27XXXXX9999X1Z5")
    assert v.status is VerificationStatus.INVALID


def test_gstn_adapter_unavailable() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(status_code=503, raw=None),
    }))
    v = adapter.verify("bidder-1", _GSTIN)
    assert v.status is VerificationStatus.UNAVAILABLE


def test_gstn_adapter_error() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(status_code=999, raw=None),
    }))
    v = adapter.verify("bidder-1", _GSTIN)
    assert v.status is VerificationStatus.ERROR


def test_gstn_adapter_normalized_data_shape() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    }))
    v = adapter.verify("bidder-1", _GSTIN)
    assert set(v.data.keys()) == {"registration_status", "legal_name"}
    # Pydantic-validated model
    NormalizedGstData(**v.data)


def test_gstn_adapter_raw_response_preserved() -> None:
    raw = {"registration_status": "ACTIVE", "legal_name": "ACME CO", "extra": "ignored_by_data"}
    adapter = GSTNAdapter(transport=StaticTransport(responses={_GSTIN: _env(status_code=200, raw=raw)}))
    v = adapter.verify("bidder-1", _GSTIN)
    assert v.raw_response == raw
    assert "extra" not in v.data


def test_gstn_adapter_audit_fields_populated() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
                     latency_ms=42, correlation_id="trace-1"),
    }))
    v = adapter.verify("bidder-1", _GSTIN)
    assert v.query is not None
    assert v.query["bidder_id"] == "bidder-1"
    assert v.query["gstin"] == _GSTIN
    assert v.query["call_id"]
    assert v.latency_ms == 42
    assert v.correlation_id == "trace-1"
    assert v.transport_status_code == 200


def test_gstn_adapter_fresh_object_per_call() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    }))
    v1 = adapter.verify("bidder-1", _GSTIN)
    v2 = adapter.verify("bidder-1", _GSTIN)
    assert v1 is not v2


def test_gstn_adapter_does_not_mutate_inputs() -> None:
    transport = StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    })
    adapter = GSTNAdapter(transport=transport)
    gstin = _GSTIN
    before = id(gstin)
    adapter.verify("bidder-1", gstin)
    after = id(gstin)
    assert before == after


def test_gstn_adapter_transport_exception_is_unavailable() -> None:
    class _Exploding:
        def send_query(self, query: Any) -> SourceResponseEnvelope:
            raise TransportError("boom")
    v = GSTNAdapter(transport=_Exploding()).verify("bidder-1", _GSTIN)  # type: ignore[arg-type]
    assert v.status is VerificationStatus.UNAVAILABLE


def test_gstn_adapter_default_transport_is_unavailable() -> None:
    """No injected transport -> no network -> UNAVAILABLE safely."""
    v = GSTNAdapter().verify("bidder-1", _GSTIN)
    assert v.status is VerificationStatus.UNAVAILABLE
    assert v.source == "GSTN"
    assert v.capability == Capability.GST


# ===========================================================================
# Udyam adapter contract
# ===========================================================================


def test_udyam_adapter_verified_status() -> None:
    adapter = UdyamAdapter(transport=_udyam_transport({
        _UDYAM: _env(status_code=200, raw={
            "registration_status": "ACTIVE", "enterprise_name": "ACME", "enterprise_category": "Medium",
        }),
    }))
    v = adapter.verify("bidder-1", _UDYAM)
    assert v.status is VerificationStatus.VERIFIED
    assert v.source == "UDYAM"
    assert v.capability == Capability.UDYAM


def test_udyam_adapter_not_found() -> None:
    adapter = UdyamAdapter(transport=_udyam_transport({
        "UDYAM-MH-12-9999999": _env(status_code=404, raw=None),
    }))
    v = adapter.verify("bidder-1", "UDYAM-MH-12-9999999")
    assert v.status is VerificationStatus.NOT_FOUND


def test_udyam_adapter_inactive() -> None:
    adapter = UdyamAdapter(transport=_udyam_transport({
        "UDYAM-MH-12-0019843": _env(status_code=410, raw={
            "registration_status": "INACTIVE", "enterprise_name": "ACME", "enterprise_category": "Medium",
        }),
    }))
    v = adapter.verify("bidder-1", "UDYAM-MH-12-0019843")
    assert v.status is VerificationStatus.INACTIVE


def test_udyam_adapter_invalid() -> None:
    """4xx + payload without a recognizable domain field -> INVALID."""
    adapter = UdyamAdapter(transport=_udyam_transport({
        "UDYAM-INVALID-123": _env(status_code=400, raw={"error": "malformed"}),
    }))
    v = adapter.verify("bidder-1", "UDYAM-INVALID-123")
    assert v.status is VerificationStatus.INVALID


def test_udyam_adapter_unavailable_and_error() -> None:
    a = UdyamAdapter(transport=_udyam_transport({_UDYAM: _env(status_code=503, raw=None)}))
    assert a.verify("bidder-1", _UDYAM).status is VerificationStatus.UNAVAILABLE
    # Use a non-standard code (outside 2xx/4xx/5xx) for ERROR.
    b = UdyamAdapter(transport=_udyam_transport({_UDYAM: _env(status_code=999, raw=None)}))
    assert b.verify("bidder-1", _UDYAM).status is VerificationStatus.ERROR


def test_udyam_adapter_normalized_data_shape() -> None:
    adapter = UdyamAdapter(transport=_udyam_transport({
        _UDYAM: _env(status_code=200, raw={
            "registration_status": "ACTIVE", "enterprise_name": "ACME", "enterprise_category": "Medium",
        }),
    }))
    v = adapter.verify("bidder-1", _UDYAM)
    assert set(v.data.keys()) == {"registration_status", "enterprise_name", "enterprise_category"}
    NormalizedUdyamData(**v.data)


def test_udyam_adapter_raw_response_preserved() -> None:
    raw = {"registration_status": "ACTIVE", "enterprise_name": "ACME", "extra": "ignored_by_data"}
    adapter = UdyamAdapter(transport=_udyam_transport({_UDYAM: _env(status_code=200, raw=raw)}))
    v = adapter.verify("bidder-1", _UDYAM)
    assert v.raw_response == raw
    assert "extra" not in v.data


def test_udyam_adapter_query_field_name() -> None:
    """Udyam queries use ``udyam_registration_number`` not ``gstin``."""
    transport = _udyam_transport({
        _UDYAM: _env(status_code=200, raw={
            "registration_status": "ACTIVE", "enterprise_name": "ACME", "enterprise_category": "Medium",
        }),
    })
    adapter = UdyamAdapter(transport=transport)
    adapter.verify("bidder-42", _UDYAM)
    assert len(transport.queries) == 1
    q = transport.queries[0]
    assert isinstance(q, UdyamQuery)
    assert q.bidder_id == "bidder-42"
    assert q.udyam_registration_number == _UDYAM


def test_udyam_adapter_fresh_object_per_call() -> None:
    transport = _udyam_transport({
        _UDYAM: _env(status_code=200, raw={
            "registration_status": "ACTIVE", "enterprise_name": "ACME", "enterprise_category": "Medium",
        }),
    })
    adapter = UdyamAdapter(transport=transport)
    v1 = adapter.verify("bidder-1", _UDYAM)
    v2 = adapter.verify("bidder-1", _UDYAM)
    assert v1 is not v2


def test_udyam_adapter_default_transport_is_unavailable() -> None:
    v = UdyamAdapter().verify("bidder-1", _UDYAM)
    assert v.status is VerificationStatus.UNAVAILABLE
    assert v.source == "UDYAM"
    assert v.capability == Capability.UDYAM


# ===========================================================================
# PAN adapter contract
# ===========================================================================


def test_pan_adapter_verified_status() -> None:
    adapter = PanAdapter(transport=_pan_transport({
        _PAN: _env(status_code=200, raw={"pan_status": "ACTIVE", "name_on_pan": "ACME CO"}),
    }))
    v = adapter.verify("bidder-1", _PAN)
    assert v.status is VerificationStatus.VERIFIED
    assert v.source == "PAN"
    assert v.capability == Capability.PAN_INCOME_TAX


def test_pan_adapter_not_found() -> None:
    adapter = PanAdapter(transport=_pan_transport({
        "AAABBB0000C": _env(status_code=404, raw=None),
    }))
    v = adapter.verify("bidder-1", "AAABBB0000C")
    assert v.status is VerificationStatus.NOT_FOUND


def test_pan_adapter_inactive() -> None:
    adapter = PanAdapter(transport=_pan_transport({
        "AAACI9999F": _env(status_code=410, raw={"pan_status": "INACTIVE", "name_on_pan": "ACME CO"}),
    }))
    v = adapter.verify("bidder-1", "AAACI9999F")
    assert v.status is VerificationStatus.INACTIVE


def test_pan_adapter_invalid() -> None:
    """4xx + payload without a recognizable domain field -> INVALID."""
    adapter = PanAdapter(transport=_pan_transport({
        "ABCDE1234F": _env(status_code=400, raw={"error": "malformed"}),
    }))
    v = adapter.verify("bidder-1", "ABCDE1234F")
    assert v.status is VerificationStatus.INVALID


def test_pan_adapter_unavailable_and_error() -> None:
    a = PanAdapter(transport=_pan_transport({_PAN: _env(status_code=503, raw=None)}))
    assert a.verify("bidder-1", _PAN).status is VerificationStatus.UNAVAILABLE
    b = PanAdapter(transport=_pan_transport({_PAN: _env(status_code=999, raw=None)}))
    assert b.verify("bidder-1", _PAN).status is VerificationStatus.ERROR


def test_pan_adapter_normalized_data_shape() -> None:
    adapter = PanAdapter(transport=_pan_transport({
        _PAN: _env(status_code=200, raw={"pan_status": "ACTIVE", "name_on_pan": "ACME CO"}),
    }))
    v = adapter.verify("bidder-1", _PAN)
    assert set(v.data.keys()) == {"pan_status", "name_on_pan"}
    NormalizedPanData(**v.data)


def test_pan_adapter_raw_response_preserved() -> None:
    raw = {"pan_status": "ACTIVE", "name_on_pan": "ACME CO", "extra": "ignored_by_data"}
    adapter = PanAdapter(transport=_pan_transport({_PAN: _env(status_code=200, raw=raw)}))
    v = adapter.verify("bidder-1", _PAN)
    assert v.raw_response == raw
    assert "extra" not in v.data


def test_pan_adapter_query_field_name() -> None:
    """PAN queries use ``pan`` not ``gstin``."""
    transport = _pan_transport({_PAN: _env(status_code=200, raw={"pan_status": "ACTIVE", "name_on_pan": "ACME CO"})})
    adapter = PanAdapter(transport=transport)
    adapter.verify("bidder-42", _PAN)
    assert len(transport.queries) == 1
    q = transport.queries[0]
    assert isinstance(q, PanQuery)
    assert q.bidder_id == "bidder-42"
    assert q.pan == _PAN


def test_pan_adapter_fresh_object_per_call() -> None:
    transport = _pan_transport({_PAN: _env(status_code=200, raw={"pan_status": "ACTIVE", "name_on_pan": "ACME CO"})})
    adapter = PanAdapter(transport=transport)
    v1 = adapter.verify("bidder-1", _PAN)
    v2 = adapter.verify("bidder-1", _PAN)
    assert v1 is not v2


def test_pan_adapter_default_transport_is_unavailable() -> None:
    v = PanAdapter().verify("bidder-1", _PAN)
    assert v.status is VerificationStatus.UNAVAILABLE
    assert v.source == "PAN"
    assert v.capability == Capability.PAN_INCOME_TAX


# ===========================================================================
# MCA adapter contract (no current rule; provider seam only)
# ===========================================================================


def test_mca_adapter_verified_status() -> None:
    adapter = McaAdapter(transport=_mca_transport({
        _CIN: _env(status_code=200, raw={"company_status": "ACTIVE", "company_name": "ACME LTD"}),
    }))
    v = adapter.verify("bidder-1", _CIN)
    assert v.status is VerificationStatus.VERIFIED
    assert v.source == "MCA21"
    # MCA capability is a free-form string (matches the identity alias).
    assert v.capability == "MCA21"


def test_mca_adapter_not_found() -> None:
    adapter = McaAdapter(transport=_mca_transport({
        "U99999MH9999PLC999999": _env(status_code=404, raw=None),
    }))
    v = adapter.verify("bidder-1", "U99999MH9999PLC999999")
    assert v.status is VerificationStatus.NOT_FOUND


def test_mca_adapter_inactive() -> None:
    adapter = McaAdapter(transport=_mca_transport({
        _CIN: _env(status_code=410, raw={"company_status": "INACTIVE", "company_name": "ACME LTD"}),
    }))
    v = adapter.verify("bidder-1", _CIN)
    assert v.status is VerificationStatus.INACTIVE


def test_mca_adapter_invalid() -> None:
    """4xx + payload without a recognizable domain field -> INVALID."""
    adapter = McaAdapter(transport=_mca_transport({
        "INVALID-CIN": _env(status_code=400, raw={"error": "malformed"}),
    }))
    v = adapter.verify("bidder-1", "INVALID-CIN")
    assert v.status is VerificationStatus.INVALID


def test_mca_adapter_unavailable_and_error() -> None:
    a = McaAdapter(transport=_mca_transport({_CIN: _env(status_code=503, raw=None)}))
    assert a.verify("bidder-1", _CIN).status is VerificationStatus.UNAVAILABLE
    b = McaAdapter(transport=_mca_transport({_CIN: _env(status_code=999, raw=None)}))
    assert b.verify("bidder-1", _CIN).status is VerificationStatus.ERROR


def test_mca_adapter_normalized_data_shape() -> None:
    adapter = McaAdapter(transport=_mca_transport({
        _CIN: _env(status_code=200, raw={"company_status": "ACTIVE", "company_name": "ACME LTD"}),
    }))
    v = adapter.verify("bidder-1", _CIN)
    assert set(v.data.keys()) == {"company_status", "company_name"}
    NormalizedMcaData(**v.data)


def test_mca_adapter_raw_response_preserved() -> None:
    raw = {"company_status": "ACTIVE", "company_name": "ACME LTD", "extra": "ignored_by_data"}
    adapter = McaAdapter(transport=_mca_transport({_CIN: _env(status_code=200, raw=raw)}))
    v = adapter.verify("bidder-1", _CIN)
    assert v.raw_response == raw
    assert "extra" not in v.data


def test_mca_adapter_query_field_name() -> None:
    """MCA queries use ``cin`` not ``gstin``."""
    transport = _mca_transport({_CIN: _env(status_code=200, raw={"company_status": "ACTIVE", "company_name": "ACME LTD"})})
    adapter = McaAdapter(transport=transport)
    adapter.verify("bidder-42", _CIN)
    assert len(transport.queries) == 1
    q = transport.queries[0]
    assert isinstance(q, McaQuery)
    assert q.bidder_id == "bidder-42"
    assert q.cin == _CIN


def test_mca_adapter_fresh_object_per_call() -> None:
    transport = _mca_transport({_CIN: _env(status_code=200, raw={"company_status": "ACTIVE", "company_name": "ACME LTD"})})
    adapter = McaAdapter(transport=transport)
    v1 = adapter.verify("bidder-1", _CIN)
    v2 = adapter.verify("bidder-1", _CIN)
    assert v1 is not v2


def test_mca_adapter_default_transport_is_unavailable() -> None:
    v = McaAdapter().verify("bidder-1", _CIN)
    assert v.status is VerificationStatus.UNAVAILABLE
    assert v.source == "MCA21"
    assert v.capability == "MCA21"


# ===========================================================================
# Engine substitutability
# ===========================================================================


def test_engine_accepts_gstn_adapter_substituting_for_mock_gst() -> None:
    """GSTNAdapter can be substituted for MockGSTProvider without engine
    changes; the GST rule still produces a PASS."""

    transport = StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    })
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )
    result = engine.run(evidence=[gst_evidence()], requirements=[gst_requirement()])

    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.actual["status"] is VerificationStatus.VERIFIED


def test_engine_accepts_udyam_adapter_substituting_for_mock() -> None:
    transport = _udyam_transport({
        _UDYAM: _env(status_code=200, raw={
            "registration_status": "ACTIVE", "enterprise_name": "ACME", "enterprise_category": "Medium",
        }),
    })
    engine = ComplianceEngine(
        rules={"UDYAM_REGISTRATION_001": UdyamRegistrationRule()},
        providers={Capability.UDYAM: UdyamAdapter(transport=transport)},
    )
    result = engine.run(evidence=[udyam_evidence()], requirements=[udyam_requirement()])

    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.actual["status"] is VerificationStatus.VERIFIED


def test_engine_accepts_pan_adapter_substituting_for_mock() -> None:
    transport = _pan_transport({
        _PAN: _env(status_code=200, raw={"pan_status": "ACTIVE", "name_on_pan": "ACME CO"}),
    })
    engine = ComplianceEngine(
        rules={"PAN_VALIDATION_001": PANValidationRule()},
        providers={Capability.PAN_INCOME_TAX: PanAdapter(transport=transport)},
    )
    result = engine.run(evidence=[pan_evidence()], requirements=[pan_requirement()])

    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.actual["status"] is VerificationStatus.VERIFIED


def test_engine_uses_mock_gst_provider_unchanged() -> None:
    """The existing MockGSTProvider still works with the engine after
    the GSTNAdapter was added; this guards against accidental removal
    of the mock."""

    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: MockGSTProvider()},
    )
    result = engine.run(evidence=[gst_evidence()], requirements=[gst_requirement()])
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS


def test_engine_uses_mock_pan_and_udyam_unchanged() -> None:
    engine = ComplianceEngine(
        rules={
            "PAN_VALIDATION_001": PANValidationRule(),
            "UDYAM_REGISTRATION_001": UdyamRegistrationRule(),
        },
        providers={
            Capability.PAN_INCOME_TAX: MockPANProvider(),
            Capability.UDYAM: MockUdyamProvider(),
        },
    )
    result = engine.run(
        evidence=[pan_evidence(), udyam_evidence()],
        requirements=[pan_requirement(), udyam_requirement()],
    )
    by_id = {cr.requirement_id: cr for cr in result.compliance_results}
    assert by_id["req-pan-001"].status is ComplianceStatus.PASS
    assert by_id["req-udyam-001"].status is ComplianceStatus.PASS


# ===========================================================================
# Cross-source invariants
# ===========================================================================


def test_all_adapters_return_verification_instances() -> None:
    """Every adapter must return a fully-populated Verification, with
    the same field set, regardless of source."""

    gstn = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    })).verify("bidder-1", _GSTIN)
    udyam = UdyamAdapter(transport=_udyam_transport({
        _UDYAM: _env(status_code=200, raw={"registration_status": "ACTIVE", "enterprise_name": "ACME", "enterprise_category": "Medium"}),
    })).verify("bidder-1", _UDYAM)
    pan = PanAdapter(transport=_pan_transport({
        _PAN: _env(status_code=200, raw={"pan_status": "ACTIVE", "name_on_pan": "ACME CO"}),
    })).verify("bidder-1", _PAN)
    mca = McaAdapter(transport=_mca_transport({
        _CIN: _env(status_code=200, raw={"company_status": "ACTIVE", "company_name": "ACME LTD"}),
    })).verify("bidder-1", _CIN)

    for v in (gstn, udyam, pan, mca):
        assert isinstance(v, Verification)
        assert v.status is VerificationStatus.VERIFIED
        # Common audit fields populated for every source
        assert v.verification_id
        assert v.bidder_id == "bidder-1"
        assert v.queried_identifier
        assert v.source
        assert v.capability
        assert v.retrieved_at.tzinfo is not None
        # Raw response / audit fields available when envelope provided them
        assert v.raw_response is not None
        assert v.latency_ms is not None
        assert v.correlation_id is not None
        assert v.query is not None


def test_all_adapters_have_distinct_sources() -> None:
    """The four providers must keep distinct source identifiers so the
    audit trail can tell which source produced which record."""

    sources = {
        GSTNAdapter.SOURCE,
        UdyamAdapter.SOURCE,
        PanAdapter.SOURCE,
        McaAdapter.SOURCE,
    }
    assert sources == {"GSTN", "UDYAM", "PAN", "MCA21"}


def test_provider_failures_are_distinct_from_verified_negatives() -> None:
    """A UNAVAILABLE or ERROR response must never look like a verified
    negative result."""

    # Verified negative (inactive) via GSTN
    transport = StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "INACTIVE", "legal_name": "ACME CO"}),
    })
    assert GSTNAdapter(transport=transport).verify("b", _GSTIN).status is VerificationStatus.INACTIVE
    # Provider failure (503)
    transport2 = StaticTransport(responses={_GSTIN: _env(status_code=503, raw=None)})
    assert GSTNAdapter(transport=transport2).verify("b", _GSTIN).status is VerificationStatus.UNAVAILABLE
    # Provider failure (non-standard code)
    transport3 = StaticTransport(responses={_GSTIN: _env(status_code=999, raw=None)})
    assert GSTNAdapter(transport=transport3).verify("b", _GSTIN).status is VerificationStatus.ERROR


def test_engine_captures_each_provider_verification_in_records() -> None:
    """The engine must capture the Verification from each provider
    into EngineResult.verification_records, including the production
    adapters."""

    transport = StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    })
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )
    result = engine.run(evidence=[gst_evidence()], requirements=[gst_requirement()])
    assert len(result.verification_records) == 1
    v = result.verification_records[0]
    assert v.source == "GSTN"
    assert v.query is not None
    assert v.query["bidder_id"] == "bidder_1"
    assert v.query["gstin"] == _GSTIN
    assert v.query["call_id"]


def test_compliance_result_verification_refs_matches_engine_record() -> None:
    """ComplianceResult.verification_refs must contain the same id as
    the engine-captured verification record."""

    transport = StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    })
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )
    result = engine.run(evidence=[gst_evidence()], requirements=[gst_requirement()])
    cr = result.compliance_results[0]
    assert cr.verification_refs == [v.verification_id for v in result.verification_records]


def test_engine_does_not_branch_on_provider_class() -> None:
    """The engine must accept any VerificationProvider for a capability
    without isinstance checks. A user-defined provider works."""

    class _UserDefinedProvider(VerificationProvider):
        def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
            return Verification(
                verification_id=f"USER:{identifier}",
                bidder_id=bidder_id,
                capability=Capability.GST,
                source="USER",
                queried_identifier=identifier,
                status=VerificationStatus.VERIFIED,
                data={"registration_status": "ACTIVE", "legal_name": "USER CO"},
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: _UserDefinedProvider()},
    )
    result = engine.run(evidence=[gst_evidence()], requirements=[gst_requirement()])
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.verification_refs[0].startswith("USER:")


def test_unavailable_provider_does_not_pass_in_engine() -> None:
    """A provider that returns UNAVAILABLE must not yield PASS through
    any of the four adapters."""

    for adapter, key in [
        (GSTNAdapter(), _GSTIN),
        (UdyamAdapter(), _UDYAM),
        (PanAdapter(), _PAN),
        (McaAdapter(), _CIN),
    ]:
        v = adapter.verify("bidder-1", key)
        assert v.status is VerificationStatus.UNAVAILABLE
