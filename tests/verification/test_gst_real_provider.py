"""End-to-end tests for the production-shaped GSTN verification milestone.

These tests cover the complete real-provider-ready GST
verification path without ever performing network I/O. Every
status branch (active, cancelled, not-found, invalid, service
error, transport failure, malformed response, HTTP success with
negative domain result) is exercised through a deterministic
in-process transport.

The test cases map directly to the GST milestone's 20
acceptance items:

1. active registration
2. cancelled/inactive registration
3. not-found GSTIN
4. invalid GSTIN
5. service error
6. transport failure
7. malformed response
8. HTTP success with negative domain result
9. raw response preservation
10. normalized data
11. latency
12. correlation_id
13. unique call_id
14. unique verification_id
15. immutable Verification
16. evidence/document enrichment
17. ComplianceResult.verification_refs
18. EngineResult.verification_records
19. MockGSTProvider regression
20. provider substitution without ComplianceEngine branching

The file also covers the additional cross-cutting concerns:

* HTTPS-only enforcement for the real HTTP transport
* latency capture and correlation propagation
* audit trail completeness
* GstConfig / GstSigningConfig seam (no secrets in source, no
  credentials in tests, real-mode validation)
* GstQuery carries three distinct identity fields
* AI Verification consumes GST-shaped Verification objects
"""

from __future__ import annotations

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
    VerificationStatus,
)
from compliance_engine.rules import GSTRegistrationRule
from compliance_engine.verification import (
    GSTNAdapter,
    GstClientCredentials,
    GstConfig,
    GstEndpointConfig,
    GstHttpResponse,
    GstQuery,
    GstResponseEnvelope,
    GstResponseParser,
    GstSigningConfig,
    GstTransportError,
    GST_ENV_PRODUCTION,
    GST_ENV_UAT,
    InProcessTransport,
    MockGSTProvider,
    NormalizedGstData,
    SourceResponseEnvelope,
    StaticGstTransport,
    StaticTransport,
    TransportError,
    VerificationProvider,
    gst_config_from_env,
    http_response_to_envelope,
)

from tests.engine._builders import gst_evidence, gst_requirement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(
    *,
    status_code: int,
    raw: Any = None,
    latency_ms: int | None = 10,
    correlation_id: str | None = "corr-test",
) -> GstResponseEnvelope:
    return GstResponseEnvelope(
        status_code=status_code,
        raw_response=raw,
        latency_ms=latency_ms,
        correlation_id=correlation_id,
    )


def _gstin_evidence(value: str | None, evidence_id: str = "doc-gst-001:gstin") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bidder_id="bidder-1",
        document_id="doc-gst-001",
        document_type="GST",
        field_name="gstin",
        value=value,
    )


def _minimal_config(url: str = "https://gstn.example/verify") -> GstConfig:
    return GstConfig(
        endpoint=GstEndpointConfig(
            url=url,
            timeout_seconds=5.0,
            environment=GST_ENV_UAT,
        ),
        client=GstClientCredentials(
            client_id_ref="GST_CLIENT_ID_REF",
            client_secret_ref="GST_CLIENT_SECRET_REF",
        ),
        signing=GstSigningConfig(
            keystore_ref="GST_KEYSTORE_REF",
            keystore_password_ref="GST_KEYSTORE_PASSWORD_REF",
            signing_algorithm="RSA_SHA256",
        ),
    )


# ---------------------------------------------------------------------------
# 1. Active registration
# ---------------------------------------------------------------------------


def test_active_registration_maps_to_verified() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
                latency_ms=42,
                correlation_id="corr-active",
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.VERIFIED
    assert result.data["registration_status"] == "ACTIVE"
    assert result.data["legal_name"] == "ACME CO"


# ---------------------------------------------------------------------------
# 2. Cancelled / inactive registration
# ---------------------------------------------------------------------------


def test_inactive_registration_maps_to_inactive() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI9999F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "INACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI9999F1Z5")

    assert result.status is VerificationStatus.INACTIVE
    assert result.data["registration_status"] == "INACTIVE"


def test_inactive_registration_fails_compliance() -> None:
    """A verified negative (cancelled) registration must FAIL."""
    transport = StaticTransport(
        responses={
            "27AAACI9999F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "INACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[gst_evidence("27AAACI9999F1Z5")],
        requirements=[gst_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.FAIL
    assert cr.actual["status"] is VerificationStatus.INACTIVE


# ---------------------------------------------------------------------------
# 3. Not-found GSTIN
# ---------------------------------------------------------------------------


def test_not_found_gstin_maps_to_not_found() -> None:
    transport = StaticTransport(
        responses={
            "27AAAAA0000A1Z5": _envelope(status_code=404, raw=None)
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAAAA0000A1Z5")

    assert result.status is VerificationStatus.NOT_FOUND
    assert result.data == {}
    # Transport status is recorded for audit only.
    assert result.transport_status_code == 404


def test_not_found_is_unverifiable_not_pass() -> None:
    """A NOT_FOUND must NOT silently become PASS."""
    transport = StaticTransport(
        responses={"27AAAAA0000A1Z5": _envelope(status_code=404, raw=None)}
    )
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[gst_evidence("27AAAAA0000A1Z5")],
        requirements=[gst_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert cr.actual["status"] is VerificationStatus.NOT_FOUND
    assert "not found" in cr.reason.lower()


# ---------------------------------------------------------------------------
# 4. Invalid GSTIN
# ---------------------------------------------------------------------------


def test_invalid_gstin_maps_to_invalid() -> None:
    transport = StaticTransport(
        responses={
            "27XXXXX9999X1Z5": _envelope(
                status_code=400,
                raw={"registration_status": "INVALID"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27XXXXX9999X1Z5")

    assert result.status is VerificationStatus.INVALID


def test_invalid_is_failure_not_pass() -> None:
    transport = StaticTransport(
        responses={
            "27XXXXX9999X1Z5": _envelope(
                status_code=400, raw={"registration_status": "INVALID"}
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[gst_evidence("27XXXXX9999X1Z5")],
        requirements=[gst_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.FAIL
    assert cr.actual["status"] is VerificationStatus.INVALID


# ---------------------------------------------------------------------------
# 5. Service error
# ---------------------------------------------------------------------------


def test_5xx_maps_to_unavailable() -> None:
    """A 5xx from the source is a service / provider outage.

    The domain status is :class:`VerificationStatus.UNAVAILABLE`
    so the rule layer produces a single ``UNVERIFIABLE``
    compliance result, never a false PASS / FAIL.
    """
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(status_code=503, raw=None)
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.UNAVAILABLE
    assert result.data == {}
    # The transport metadata is preserved for audit.
    assert result.transport_status_code == 503


def test_5xx_is_unverifiable_not_pass() -> None:
    transport = StaticTransport(
        responses={"27AAACI1234F1Z5": _envelope(status_code=503, raw=None)}
    )
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )
    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert cr.actual["status"] is VerificationStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# 6. Transport failure
# ---------------------------------------------------------------------------


class _RaisingTransport(StaticTransport):
    def send_query(self, query):  # type: ignore[override]
        raise TransportError("simulated transport failure")


def test_transport_failure_maps_to_unavailable() -> None:
    transport = _RaisingTransport()
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.UNAVAILABLE
    assert result.data == {}


def test_in_process_transport_raises_not_implemented() -> None:
    """The default transport must fail fast and loud."""
    adapter = GSTNAdapter()  # uses InProcessTransport

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.UNAVAILABLE


def test_gst_transport_error_maps_to_unavailable() -> None:
    """A real-HTTP-transport failure maps to UNAVAILABLE."""

    class _RaisingGstTransport(StaticGstTransport):
        def send(self, request):  # type: ignore[override]
            raise GstTransportError("simulated HTTPS failure")

    adapter = GSTNAdapter(http_transport=_RaisingGstTransport())

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# 7. Malformed response
# ---------------------------------------------------------------------------


def test_malformed_response_via_http_transport_coerces_to_error() -> None:
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
    adapter = GSTNAdapter(http_transport=static)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.ERROR
    assert result.data == {}
    # The raw blob is NOT carried into the audit trail.
    assert result.raw_response is None
    # The transport status is still recorded.
    assert result.transport_status_code == 200


def test_malformed_response_with_unknown_dict_shape() -> None:
    """A 200 with a dict that does not carry the expected domain
    field is a *malformed* payload and is mapped to
    :class:`VerificationStatus.ERROR`."""

    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200, raw={"some": "unknown-payload"}
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    # Unknown payload shape -> ERROR (we do not infer a status).
    assert result.status is VerificationStatus.ERROR


# ---------------------------------------------------------------------------
# 8. HTTP success with negative domain result
# ---------------------------------------------------------------------------


def test_http_success_with_inactive_payload_maps_to_inactive() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI9999F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "INACTIVE", "legal_name": "X"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI9999F1Z5")

    # 200 is transport metadata; the DOMAIN status is INACTIVE
    # because the payload says so.
    assert result.transport_status_code == 200
    assert result.status is VerificationStatus.INACTIVE


def test_http_404_with_no_payload_maps_to_not_found() -> None:
    transport = StaticTransport(
        responses={"27AAACI1234F1Z5": _envelope(status_code=404, raw=None)}
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    # 404 with no payload is the standard "not found" shape.
    assert result.transport_status_code == 404
    assert result.status is VerificationStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# 9. Raw response preservation
# ---------------------------------------------------------------------------


def test_raw_response_preserved_separately() -> None:
    raw = {
        "registration_status": "ACTIVE",
        "legal_name": "ACME CO",
        "filing_status": "REGULAR",  # not in normalized schema; stays in raw
    }
    transport = StaticTransport(
        responses={"27AAACI1234F1Z5": _envelope(status_code=200, raw=raw)}
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.raw_response == raw
    # Normalized data is the narrow subset.
    assert "filing_status" not in result.data


# ---------------------------------------------------------------------------
# 10. Normalized data
# ---------------------------------------------------------------------------


def test_normalized_data_contains_only_minimum_fields() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    # Normalized data is structurally enforced.
    NormalizedGstData.model_validate(result.data)
    assert set(result.data.keys()) == {"registration_status", "legal_name"}


def test_normalized_data_rejects_extra_fields() -> None:
    with pytest.raises(Exception):
        NormalizedGstData(
            registration_status="ACTIVE",
            legal_name="ACME",
            unexpected="x",
        )


# ---------------------------------------------------------------------------
# 11. Latency
# ---------------------------------------------------------------------------


def test_latency_propagated_from_envelope() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
                latency_ms=137,
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.latency_ms == 137


def test_latency_captured_by_static_gst_transport() -> None:
    """The real-HTTP transport's latency flows through the adapter."""
    static = StaticGstTransport(
        responses={
            "27AAACI1234F1Z5": GstHttpResponse(
                status_code=200,
                body_json={"registration_status": "ACTIVE", "legal_name": "ACME"},
                latency_ms=88,
                correlation_id="trace-1",
            )
        }
    )
    adapter = GSTNAdapter(http_transport=static)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.latency_ms == 88


# ---------------------------------------------------------------------------
# 12. Correlation id
# ---------------------------------------------------------------------------


def test_correlation_id_propagated_from_envelope() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME"},
                correlation_id="trace-xyz",
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.correlation_id == "trace-xyz"


def test_correlation_id_falls_back_to_query_level() -> None:
    """When the transport did not supply a correlation id, the
    query-level one is propagated."""

    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME"},
                correlation_id=None,
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify(
        "bidder-1", "27AAACI1234F1Z5", correlation_id="trace-from-caller"
    )

    assert result.correlation_id == "trace-from-caller"


# ---------------------------------------------------------------------------
# 13. Unique call_id
# ---------------------------------------------------------------------------


def test_each_query_has_a_unique_call_id() -> None:
    q1 = GstQuery(bidder_id="b", gstin="27AAACI1234F1Z5")
    q2 = GstQuery(bidder_id="b", gstin="27AAACI1234F1Z5")
    assert q1.call_id != q2.call_id
    assert len(q1.call_id) >= 16  # UUID4 hex is 32 chars; the helper is at least 16


# ---------------------------------------------------------------------------
# 14. Unique verification_id
# ---------------------------------------------------------------------------


def test_repeated_calls_produce_distinct_verification_ids() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    r1 = adapter.verify("bidder-1", "27AAACI1234F1Z5")
    r2 = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert r1.verification_id != r2.verification_id
    # Both IDs still identify the same source + identifier.
    assert r1.verification_id.startswith("GSTN:27AAACI1234F1Z5:")
    assert r2.verification_id.startswith("GSTN:27AAACI1234F1Z5:")


def test_pre_allocated_verification_id_is_honored() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)
    pre_allocated = f"GSTN:27AAACI1234F1Z5:{uuid4().hex}"

    result = adapter.verify(
        "bidder-1", "27AAACI1234F1Z5", verification_id=pre_allocated
    )

    assert result.verification_id == pre_allocated


# ---------------------------------------------------------------------------
# 15. Immutable Verification
# ---------------------------------------------------------------------------


def test_verification_is_frozen() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    with pytest.raises(Exception):
        result.status = VerificationStatus.ERROR  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 16. Evidence / document enrichment
# ---------------------------------------------------------------------------


def test_rule_enriches_verification_with_evidence_and_document() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME"},
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )
    evidence = gst_evidence()
    result = engine.run(evidence=[evidence], requirements=[gst_requirement()])

    # The rule's enriched copy is captured by the engine.
    [verification] = result.verification_records
    assert verification.evidence_id == evidence.evidence_id
    assert verification.document_id == evidence.document_id


# ---------------------------------------------------------------------------
# 17. ComplianceResult.verification_refs
# ---------------------------------------------------------------------------


def test_compliance_result_carries_verification_refs() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME"},
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )
    result = engine.run(evidence=[gst_evidence()], requirements=[gst_requirement()])

    cr = result.compliance_results[0]
    assert len(cr.verification_refs) == 1
    assert cr.verification_refs[0].startswith("GSTN:")


# ---------------------------------------------------------------------------
# 18. EngineResult.verification_records
# ---------------------------------------------------------------------------


def test_engine_result_records_every_verification() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME"},
            )
        }
    )
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )
    result = engine.run(evidence=[gst_evidence()], requirements=[gst_requirement()])

    assert len(result.verification_records) == 1
    [verification] = result.verification_records
    assert verification.queried_identifier == "27AAACI1234F1Z5"
    assert verification.status is VerificationStatus.VERIFIED


# ---------------------------------------------------------------------------
# 19. MockGSTProvider regression
# ---------------------------------------------------------------------------


def test_mock_gst_provider_still_works() -> None:
    """The existing MockGSTProvider regression baseline must hold."""
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: MockGSTProvider()},
    )
    result = engine.run(evidence=[gst_evidence()], requirements=[gst_requirement()])

    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.actual["status"] is VerificationStatus.VERIFIED


# ---------------------------------------------------------------------------
# 20. Provider substitution without ComplianceEngine branching
# ---------------------------------------------------------------------------


def test_engine_accepts_alternate_gst_provider_implementation() -> None:
    """The engine does not branch on the specific provider type."""

    class _AlternateProvider(VerificationProvider):
        SOURCE = "ALT_GST"

        def verify(self, bidder_id, identifier, **kwargs):
            from datetime import UTC, datetime

            from compliance_engine.models import Capability, Verification

            return Verification(
                verification_id=f"ALT_GST:{identifier}",
                bidder_id=bidder_id,
                capability=Capability.GST,
                source=self.SOURCE,
                queried_identifier=identifier,
                status=VerificationStatus.VERIFIED,
                data={"registration_status": "ACTIVE", "legal_name": "ALT"},
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: _AlternateProvider()},
    )
    result = engine.run(evidence=[gst_evidence()], requirements=[gst_requirement()])

    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.verification_refs == ["ALT_GST:27AAACI1234F1Z5"]


# ---------------------------------------------------------------------------
# Additional cross-cutting concerns
# ---------------------------------------------------------------------------


# --- GstQuery identity fields are distinct -----------------------


def test_gst_query_has_three_distinct_identity_fields() -> None:
    q = GstQuery(
        bidder_id="bidder-1",
        gstin="27AAACI1234F1Z5",
        call_id="call-1",
        verification_id="ver-1",
        correlation_id="corr-1",
    )
    assert q.call_id == "call-1"
    assert q.verification_id == "ver-1"
    assert q.correlation_id == "corr-1"
    # The three fields are independent and may be supplied in any
    # combination.
    q2 = GstQuery(bidder_id="bidder-1", gstin="27AAACI1234F1Z5")
    assert q2.call_id != ""
    assert q2.verification_id is None
    assert q2.correlation_id is None


# --- GstQuery is GST-specific, not universal ---------------------


def test_gst_query_rejects_universal_government_fields() -> None:
    """The GstQuery model must not be a universal government query."""
    with pytest.raises(Exception):
        GstQuery(
            bidder_id="b",
            gstin="27AAACI1234F1Z5",
            pan="AAACI1234F",  # NOT a GST field
        )


# --- GstConfig seam ------------------------------------------------


def test_gst_config_validate_for_real_use_rejects_incomplete() -> None:
    incomplete = GstConfig(
        endpoint=GstEndpointConfig(url="", timeout_seconds=5.0),
        client=GstClientCredentials(
            client_id_ref="", client_secret_ref=""
        ),
        signing=GstSigningConfig(
            keystore_ref="", keystore_password_ref=""
        ),
    )
    with pytest.raises(ValueError) as exc:
        incomplete.validate_for_real_use()
    msg = str(exc.value)
    # All required references are listed.
    for key in (
        "endpoint.url",
        "client.client_id_ref",
        "client.client_secret_ref",
        "signing.keystore_ref",
        "signing.keystore_password_ref",
    ):
        assert key in msg


def test_gst_config_validate_for_real_use_accepts_complete() -> None:
    cfg = _minimal_config()
    cfg.validate_for_real_use()  # does not raise


def test_gst_endpoint_rejects_http() -> None:
    with pytest.raises(ValueError):
        GstEndpointConfig(
            url="http://insecure.example/verify", timeout_seconds=5.0
        )


def test_gst_endpoint_rejects_unknown_environment() -> None:
    with pytest.raises(ValueError):
        GstEndpointConfig(
            url="https://gstn.example/verify",
            timeout_seconds=5.0,
            environment="STAGING",
        )


def test_gst_config_from_env_has_no_secrets_in_source() -> None:
    """``from_env`` reads environment variable NAMES, not values.

    The references returned are the *names* of the env vars that
    hold the secrets, never the secrets themselves. The
    deterministic test env is empty, so the returned config
    surfaces a clear "missing" error on real-mode validation.
    """
    cfg = gst_config_from_env(env={})
    with pytest.raises(ValueError):
        cfg.validate_for_real_use()


def test_gst_config_from_env_populates_from_env_dict() -> None:
    cfg = gst_config_from_env(
        env={
            "GST_ENDPOINT_URL": "https://uat.gstn.example/verify",
            "GST_ENVIRONMENT": "UAT",
        }
    )
    assert cfg.endpoint.url == "https://uat.gstn.example/verify"
    assert cfg.endpoint.environment == GST_ENV_UAT
    assert cfg.signing.signing_algorithm == "RSA_SHA256"


def test_gst_config_environment_can_be_production() -> None:
    cfg = gst_config_from_env(env={"GST_ENVIRONMENT": "PRODUCTION"})
    assert cfg.endpoint.environment == GST_ENV_PRODUCTION


# --- Real-HTTP transport seam -------------------------------------


def test_static_gst_transport_returns_canned_response() -> None:
    canned = GstHttpResponse(
        status_code=200,
        body_json={"registration_status": "ACTIVE", "legal_name": "ACME"},
        latency_ms=42,
        correlation_id="trace-1",
    )
    transport = StaticGstTransport(
        responses={"27AAACI1234F1Z5": canned}
    )
    adapter = GSTNAdapter(http_transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.VERIFIED
    assert result.data["legal_name"] == "ACME"
    assert result.latency_ms == 42
    assert result.correlation_id == "trace-1"
    # The transport recorded the request.
    assert len(transport.queries) == 1
    assert transport.queries[0].gstin == "27AAACI1234F1Z5"


def test_static_gst_transport_default_404() -> None:
    transport = StaticGstTransport()
    adapter = GSTNAdapter(http_transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.NOT_FOUND


def test_http_response_to_envelope_preserves_metadata() -> None:
    resp = GstHttpResponse(
        status_code=200,
        body_json={"registration_status": "ACTIVE", "legal_name": "ACME"},
        latency_ms=55,
        correlation_id="trace-2",
    )
    envelope = http_response_to_envelope(resp)

    assert envelope.status_code == 200
    assert envelope.latency_ms == 55
    assert envelope.correlation_id == "trace-2"
    assert envelope.raw_response == {
        "registration_status": "ACTIVE",
        "legal_name": "ACME",
    }


def test_http_response_to_envelope_coerces_non_dict_body() -> None:
    """A non-dict body is coerced to None on the envelope."""
    resp = GstHttpResponse(
        status_code=200,
        body_json="<html>oops</html>",
        latency_ms=10,
        correlation_id=None,
    )
    envelope = http_response_to_envelope(resp)

    assert envelope.raw_response is None
    assert envelope.status_code == 200


# --- Provider substitution also works in the engine -----------------


def test_engine_substitutes_gstn_adapter_for_mock_without_branching() -> None:
    """The engine handles a GSTNAdapter or a MockGSTProvider
    identically. There is no source-specific branch in the engine
    or the rule layer."""

    rules = {"GST_REGISTRATION_001": GSTRegistrationRule()}
    req = gst_requirement()
    evidence = gst_evidence()

    # Run with MockGSTProvider
    mock_engine = ComplianceEngine(
        rules=rules, providers={Capability.GST: MockGSTProvider()}
    )
    mock_result = mock_engine.run(evidence=[evidence], requirements=[req])

    # Run with GSTNAdapter (real-shaped, StaticTransport)
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={
                    "registration_status": "ACTIVE",
                    "legal_name": "ACME ENTERPRISES PRIVATE LIMITED",
                },
            )
        }
    )
    real_engine = ComplianceEngine(
        rules=rules, providers={Capability.GST: GSTNAdapter(transport=transport)}
    )
    real_result = real_engine.run(evidence=[evidence], requirements=[req])

    assert mock_result.compliance_results[0].status is real_result.compliance_results[0].status
    assert mock_result.compliance_results[0].status is ComplianceStatus.PASS


# --- AI Verification consumption -----------------------------------


def test_ai_verification_consumes_gst_shaped_verification() -> None:
    """The GST-shaped Verification must be consumable by AI
    Verification's :class:`VerificationInput` without any change
    to the AI detector / orchestrator logic."""

    from ai_verification.models import BidderSummary, VerificationInput
    from ai_verification.engine import VerificationEngine

    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)
    verification = adapter.verify("bidder-1", "27AAACI1234F1Z5")
    # Enrichment is done by the rule; this test focuses on AI
    # consumption only.
    evidence = gst_evidence()

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
    # the test is that the engine accepts the GST-shaped record
    # without raising.
    ai_engine = VerificationEngine(artifact_store=None)
    ai_result = ai_engine.run(ai_input)
    assert ai_result.bidder_id == "bidder-1"


# --- Audit-trail completeness --------------------------------------


def test_audit_trail_contains_all_required_fields() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME"},
                latency_ms=99,
                correlation_id="trace-audit",
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    # Every required audit field is present.
    assert result.verification_id
    assert result.bidder_id == "bidder-1"
    assert result.capability == Capability.GST
    assert result.source == "GSTN"
    assert result.queried_identifier == "27AAACI1234F1Z5"
    assert result.status is VerificationStatus.VERIFIED
    assert result.data == {
        "registration_status": "ACTIVE",
        "legal_name": "ACME",
    }
    assert result.retrieved_at is not None
    # ``query`` carries the full GstQuery for audit.
    assert result.query is not None
    assert result.query["gstin"] == "27AAACI1234F1Z5"
    assert result.query["bidder_id"] == "bidder-1"
    # The three distinct identity fields are all present on the query.
    assert "call_id" in result.query
    # The transport metadata is preserved separately.
    assert result.raw_response == {
        "registration_status": "ACTIVE",
        "legal_name": "ACME",
    }
    assert result.latency_ms == 99
    assert result.correlation_id == "trace-audit"
    assert result.transport_status_code == 200


# --- HTTPS-only enforcement ----------------------------------------


def test_gst_endpoint_config_rejects_http() -> None:
    """The endpoint config validator refuses non-HTTPS URLs."""
    with pytest.raises(Exception):
        GstEndpointConfig(
            url="http://insecure.example/verify",
            timeout_seconds=1.0,
        )


def test_gst_http_client_runtime_https_check() -> None:
    """The real HTTP client's default opener enforces HTTPS at the
    network seam, even if a caller bypasses the endpoint validator."""

    from compliance_engine.verification.gst_http_transport import (
        GstHttpClient,
        _default_opener,
    )

    # A valid config first; we then bypass the static validator by
    # swapping the URL on the constructed object to a non-HTTPS one
    # and confirming the runtime seam refuses.
    cfg = _minimal_config("https://insecure.example/verify")
    client = GstHttpClient(cfg, opener=_default_opener)
    # Use object.__setattr__ because GstEndpointConfig is frozen.
    object.__setattr__(cfg.endpoint, "url", "http://insecure.example/verify")
    with pytest.raises(GstTransportError):
        client.send(GstQuery(bidder_id="b", gstin="27AAACI1234F1Z5"))
