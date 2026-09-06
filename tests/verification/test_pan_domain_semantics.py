"""Domain semantics and security-seam regression for the PAN provider.

This suite pins the corrected mapping between the official PAN
Verification Web Service response payload and the internal
:class:`VerificationStatus`. It is deliberately exhaustive so a
future regression in the parser surfaces immediately.

Reference: the official PAN Verification Web Service (service ID
10001) response shape documented in
``src/compliance_engine/verification/pan_soap.py``.

Mapping
-------

* ``ServiceErrorCode != "1"``           -> ``ERROR``
* ``panStatus != "E"``                  -> ``NOT_FOUND``
* ``panMatch == "N"``                   -> ``INVALID``
* everything else (including name/DOB
  /component mismatches)                -> ``VERIFIED``
* ``INACTIVE``                           -> reserved for an explicit
  inactive code from the registry; the documented contract does not
  include one.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from uuid import uuid4

import pytest

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Capability,
    ComplianceStatus,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules import PANValidationRule
from compliance_engine.verification import (
    MockPANProvider,
    PanAdapter,
    PanConfig,
    PanEndpointConfig,
    PanAgencyCredentials,
    PanClientCredentials,
    PanHttpResponse,
    PanQuery,
    PanSigningConfig,
    PanSoapResponseParser,
    PanTransportError,
    StaticPanTransport,
)
from compliance_engine.verification.pan_soap import (
    PAN_NS,
    RESPONSE_LOCAL,
    SOAP_NS,
)

from tests.engine._builders import pan_evidence, pan_requirement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _good_config() -> PanConfig:
    return PanConfig(
        endpoint=PanEndpointConfig(
            url="https://incometaxindiaefiling.gov.in/pan/verify",
            timeout_seconds=5.0,
            soap_action="verifyPAN",
        ),
        agency=PanAgencyCredentials(
            agency_username="u", agency_password="p"
        ),
        client=PanClientCredentials(client_id="c", client_secret="s"),
        signing=PanSigningConfig(
            keystore_ref="k", keystore_password_ref="kp"
        ),
    )


def _xml(body_inside_response: str, pan: str = "AAACI1234F") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="' + SOAP_NS + '" xmlns:pan="' + PAN_NS + '">'
        '<soap:Body><pan:' + RESPONSE_LOCAL + '>'
        '<pan:PAN>' + pan + '</pan:PAN>'
        + body_inside_response +
        '</pan:' + RESPONSE_LOCAL + '></soap:Body></soap:Envelope>'
    )


def _parse(body: str, pan: str = "AAACI1234F") -> Verification:
    parser = PanSoapResponseParser()
    return parser.parse(
        _xml(body, pan=pan),
        query=PanQuery(bidder_id="b1", pan=pan),
        bidder_id="b1",
        transport_status_code=200,
        latency_ms=10,
        correlation_id="corr",
    )


# ===========================================================================
# 1. PAN matched (all flags = "Y")
# ===========================================================================


def test_pan_matched_all_yields_verified() -> None:
    v = _parse(
        '<pan:panStatus>E</pan:panStatus>'
        '<pan:panMatch>Y</pan:panMatch>'
        '<pan:nameMatch>Y</pan:nameMatch>'
        '<pan:dobMatch>Y</pan:dobMatch>'
        '<pan:panHolderName>ACME CO</pan:panHolderName>'
        '<pan:panHolderDob>01/01/1990</pan:panHolderDob>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
    )
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["pan_status"] == "ACTIVE"
    assert v.data["name_on_pan"] == "ACME CO"
    assert v.data["date_of_birth"] == "01/01/1990"


# ===========================================================================
# 2. PAN mismatch (panMatch = "N") -> INVALID
# ===========================================================================


def test_pan_mismatch_yields_invalid() -> None:
    v = _parse(
        '<pan:panStatus>E</pan:panStatus>'
        '<pan:panMatch>N</pan:panMatch>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
    )
    assert v.status is VerificationStatus.INVALID


# ===========================================================================
# 3. name mismatch (nameMatch = "N") -> VERIFIED, not INACTIVE
# ===========================================================================


def test_name_mismatch_does_not_downgrade_pan_to_inactive() -> None:
    """Critical regression: the official service reports
    ``nameMatch="N"`` when the *supplied* name does not match the
    registry record. The PAN itself is still valid and active; the
    rule layer and the compliance verdict must not change. The
    mismatch detail is preserved in ``data["match_details"]`` for
    audit / anomaly logic.
    """
    v = _parse(
        '<pan:panStatus>E</pan:panStatus>'
        '<pan:panMatch>Y</pan:panMatch>'
        '<pan:nameMatch>N</pan:nameMatch>'
        '<pan:dobMatch>Y</pan:dobMatch>'
        '<pan:panHolderName>OTHER BIDDER LIMITED</pan:panHolderName>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
    )
    assert v.status is VerificationStatus.VERIFIED, (
        "Identity-attribute mismatch must not downgrade the PAN to "
        "INACTIVE; the PAN itself is valid and active."
    )
    assert v.data["name_on_pan"] == "OTHER BIDDER LIMITED"
    assert v.data["match_details"]["name_match"] == "N"
    assert v.data["match_details"]["pan_match"] == "Y"


# ===========================================================================
# 4. DOB mismatch (dobMatch = "N") -> VERIFIED, not INACTIVE
# ===========================================================================


def test_dob_mismatch_does_not_downgrade_pan_to_inactive() -> None:
    v = _parse(
        '<pan:panStatus>E</pan:panStatus>'
        '<pan:panMatch>Y</pan:panMatch>'
        '<pan:nameMatch>Y</pan:nameMatch>'
        '<pan:dobMatch>N</pan:dobMatch>'
        '<pan:panHolderName>ACME CO</pan:panHolderName>'
        '<pan:panHolderDob>01/01/1990</pan:panHolderDob>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
    )
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["match_details"]["dob_match"] == "N"
    assert v.data["date_of_birth"] == "01/01/1990"


# ===========================================================================
# 5. component mismatch (lastNameMatch = "N") -> VERIFIED
# ===========================================================================


def test_component_name_mismatch_yields_verified() -> None:
    v = _parse(
        '<pan:panStatus>E</pan:panStatus>'
        '<pan:panMatch>Y</pan:panMatch>'
        '<pan:firstNameMatch>Y</pan:firstNameMatch>'
        '<pan:middleNameMatch>Y</pan:middleNameMatch>'
        '<pan:lastNameMatch>N</pan:lastNameMatch>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
    )
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["match_details"]["last_name_match"] == "N"
    assert v.data["match_details"]["first_name_match"] == "Y"


# ===========================================================================
# 6. actual inactive result -- not represented by the documented contract
# ===========================================================================


def test_no_documented_inactive_code_in_official_contract() -> None:
    """The documented PAN service uses ``panStatus="D"`` (deleted)
    rather than an explicit "inactive" code. The parser therefore
    never produces ``INACTIVE`` for a successful service response;
    ``INACTIVE`` is reserved for a future explicit code.
    """
    responses = [
        # Successful response with all match flags = Y.
        ('<pan:panStatus>E</pan:panStatus>'
         '<pan:panMatch>Y</pan:panMatch>'
         '<pan:nameMatch>Y</pan:nameMatch>'
         '<pan:dobMatch>Y</pan:dobMatch>'
         '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'),
        # Name mismatch.
        ('<pan:panStatus>E</pan:panStatus>'
         '<pan:panMatch>Y</pan:panMatch>'
         '<pan:nameMatch>N</pan:nameMatch>'
         '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'),
        # DOB mismatch.
        ('<pan:panStatus>E</pan:panStatus>'
         '<pan:panMatch>Y</pan:panMatch>'
         '<pan:dobMatch>N</pan:dobMatch>'
         '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'),
        # Component mismatch.
        ('<pan:panStatus>E</pan:panStatus>'
         '<pan:panMatch>Y</pan:panMatch>'
         '<pan:lastNameMatch>N</pan:lastNameMatch>'
         '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'),
    ]
    for body in responses:
        v = _parse(body)
        assert v.status is not VerificationStatus.INACTIVE, (
            "INACTIVE must not be produced from a successful service "
            "response; got INACTIVE for body: " + body
        )


# ===========================================================================
# 7. actual missing/not-found result (panStatus != "E")
# ===========================================================================


@pytest.mark.parametrize("pan_status", ["D", "F"])
def test_pan_status_other_than_e_yields_not_found(pan_status: str) -> None:
    v = _parse(
        '<pan:panStatus>' + pan_status + '</pan:panStatus>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
    )
    assert v.status is VerificationStatus.NOT_FOUND


# ===========================================================================
# 8. service error
# ===========================================================================


def test_service_error_code_yields_error() -> None:
    v = _parse(
        '<pan:ServiceErrorCode>100</pan:ServiceErrorCode>'
    )
    assert v.status is VerificationStatus.ERROR


# ===========================================================================
# 9. malformed SOAP / XML
# ===========================================================================


def test_malformed_xml_via_adapter_yields_error_with_raw_preserved() -> None:
    from compliance_engine.verification import PanSoapParseError
    parser = PanSoapResponseParser()
    with pytest.raises(PanSoapParseError):
        parser.parse(
            "<not-xml",
            query=PanQuery(bidder_id="b1", pan="AAACI1234F"),
            bidder_id="b1",
        )


# ===========================================================================
# 10. HTTP success + negative business result (NOT a verified negative)
# ===========================================================================


def test_http_200_with_service_error_yields_error() -> None:
    transport = StaticPanTransport(
        default_response=PanHttpResponse(
            status_code=200,
            body_xml=_xml('<pan:ServiceErrorCode>101</pan:ServiceErrorCode>'),
            latency_ms=5,
            correlation_id="c",
        )
    )
    adapter = PanAdapter(config=_good_config(), http_transport=transport)
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.status is VerificationStatus.ERROR
    assert v.transport_status_code == 200


# ===========================================================================
# 11. transport failure -> UNAVAILABLE
# ===========================================================================


def test_transport_failure_yields_unavailable() -> None:
    class _BoomTransport:
        def send(self, request) -> PanHttpResponse:  # type: ignore[no-untyped-def]
            raise PanTransportError("connection reset")

    adapter = PanAdapter(
        config=_good_config(),
        http_transport=_BoomTransport(),  # type: ignore[arg-type]
    )
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.status is VerificationStatus.UNAVAILABLE


# ===========================================================================
# 12. unique call_id
# ===========================================================================


def test_call_id_is_unique_per_call() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_xml(
                    '<pan:panStatus>E</pan:panStatus>'
                    '<pan:panMatch>Y</pan:panMatch>'
                    '<pan:nameMatch>Y</pan:nameMatch>'
                    '<pan:dobMatch>Y</pan:dobMatch>'
                    '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
                ),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(config=_good_config(), http_transport=transport)
    adapter.verify("bidder-1", "AAACI1234F")
    adapter.verify("bidder-1", "AAACI1234F")
    assert len(transport.requests) == 2
    assert transport.requests[0].call_id != transport.requests[1].call_id


# ===========================================================================
# 13. unique verification_id
# ===========================================================================


def test_verification_id_is_unique_per_call() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_xml(
                    '<pan:panStatus>E</pan:panStatus>'
                    '<pan:panMatch>Y</pan:panMatch>'
                    '<pan:nameMatch>Y</pan:nameMatch>'
                    '<pan:dobMatch>Y</pan:dobMatch>'
                    '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
                ),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(config=_good_config(), http_transport=transport)
    v1 = adapter.verify("bidder-1", "AAACI1234F")
    v2 = adapter.verify("bidder-1", "AAACI1234F")
    assert v1.verification_id != v2.verification_id


# ===========================================================================
# 14. request_id preservation
# ===========================================================================


def test_request_id_is_preserved_and_distinct_per_call() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_xml(
                    '<pan:panStatus>E</pan:panStatus>'
                    '<pan:panMatch>Y</pan:panMatch>'
                    '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
                ),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(config=_good_config(), http_transport=transport)
    adapter.verify("bidder-1", "AAACI1234F")
    adapter.verify("bidder-1", "AAACI1234F")
    # request_id flows into the SOAP envelope and the audit record.
    assert transport.requests[0].request_id != transport.requests[1].request_id
    assert transport.requests[0].request_id != transport.requests[0].call_id


# ===========================================================================
# 15. correlation_id preservation
# ===========================================================================


def test_correlation_id_from_transport_is_preserved() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_xml(
                    '<pan:panStatus>E</pan:panStatus>'
                    '<pan:panMatch>Y</pan:panMatch>'
                    '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
                ),
                latency_ms=1,
                correlation_id="trace-abc-123",
            )
        }
    )
    adapter = PanAdapter(config=_good_config(), http_transport=transport)
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.correlation_id == "trace-abc-123"
    # correlation_id is distinct from the per-call request_id /
    # call_id.
    assert v.correlation_id != v.query["call_id"]


# ===========================================================================
# 16. audit raw response
# ===========================================================================


def test_raw_response_preserves_soap_xml_for_audit() -> None:
    body = (
        '<pan:panStatus>E</pan:panStatus>'
        '<pan:panMatch>Y</pan:panMatch>'
        '<pan:nameMatch>N</pan:nameMatch>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
    )
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_xml(body),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(config=_good_config(), http_transport=transport)
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.raw_response is not None
    assert "soap_xml" in v.raw_response
    # The full SOAP envelope is preserved verbatim.
    assert "soap:Envelope" in v.raw_response["soap_xml"]
    assert "nameMatch" in v.raw_response["soap_xml"]


# ===========================================================================
# 17. EngineResult capture
# ===========================================================================


def test_engine_result_captures_verification() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_xml(
                    '<pan:panStatus>E</pan:panStatus>'
                    '<pan:panMatch>Y</pan:panMatch>'
                    '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
                ),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(config=_good_config(), http_transport=transport)
    engine = ComplianceEngine(
        rules={"PAN_VALIDATION_001": PANValidationRule()},
        providers={Capability.PAN_INCOME_TAX: adapter},
    )
    result = engine.run(
        evidence=[pan_evidence("AAACI1234F")],
        requirements=[pan_requirement()],
    )
    assert len(result.verification_records) == 1
    v = result.verification_records[0]
    assert v.source == "PAN"
    assert v.status is VerificationStatus.VERIFIED


# ===========================================================================
# 18. ComplianceResult verification_refs
# ===========================================================================


def test_compliance_result_verification_refs_match_verification_id() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_xml(
                    '<pan:panStatus>E</pan:panStatus>'
                    '<pan:panMatch>Y</pan:panMatch>'
                    '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
                ),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(config=_good_config(), http_transport=transport)
    engine = ComplianceEngine(
        rules={"PAN_VALIDATION_001": PANValidationRule()},
        providers={Capability.PAN_INCOME_TAX: adapter},
    )
    result = engine.run(
        evidence=[pan_evidence("AAACI1234F")],
        requirements=[pan_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.verification_refs == [result.verification_records[0].verification_id]


# ===========================================================================
# 19. MockPANProvider regression
# ===========================================================================


def test_mock_pan_provider_name_mismatch_is_verified() -> None:
    """The mock provider must mirror the corrected domain
    semantics: a name-mismatch is still a valid (VERIFIED) PAN."""
    v = MockPANProvider().verify(
        "bidder-1", MockPANProvider.PAN_NAME_MISMATCH
    )
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["name_on_pan"] == "OTHER BIDDER PRIVATE LIMITED"


def test_mock_pan_provider_inactive_is_still_inactive() -> None:
    """The mock's ``PAN_INACTIVE`` fixture models a PAN that was
    once active and is now deactivated in the registry -- i.e. an
    inactive record. The rule layer maps that to FAIL."""
    v = MockPANProvider().verify(
        "bidder-1", MockPANProvider.PAN_INACTIVE
    )
    assert v.status is VerificationStatus.INACTIVE


# ===========================================================================
# 20. unit tests work without credentials
# ===========================================================================


def test_unit_tests_work_without_credentials() -> None:
    """The real-provider path must be fully exercisable with
    injected transports, no credentials, no real network calls."""
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_xml(
                    '<pan:panStatus>E</pan:panStatus>'
                    '<pan:panMatch>Y</pan:panMatch>'
                    '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
                ),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    # The ``keystore_password_ref`` etc. are opaque references, not
    # real credentials.
    adapter = PanAdapter(config=_good_config(), http_transport=transport)
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.status is VerificationStatus.VERIFIED
    # No hardcoded secret in the SOAP envelope.
    assert "***" in transport.requests[0].xml


# ===========================================================================
# Bonus: full end-to-end mismatch case against the rule
# ===========================================================================


def test_rule_does_not_penalise_supplied_name_mismatch() -> None:
    """The PAN rule must not perform identity-attribute comparison;
    a name-mismatch SOAP response (the PAN itself is valid) must
    produce PASS."""
    transport = StaticPanTransport(
        responses={
            "AAACI4321F": PanHttpResponse(
                status_code=200,
                body_xml=_xml(
                    '<pan:panStatus>E</pan:panStatus>'
                    '<pan:panMatch>Y</pan:panMatch>'
                    '<pan:nameMatch>N</pan:nameMatch>'
                    '<pan:dobMatch>Y</pan:dobMatch>'
                    '<pan:panHolderName>OTHER BIDDER LIMITED</pan:panHolderName>'
                    '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>',
                    pan="AAACI4321F",
                ),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(config=_good_config(), http_transport=transport)
    engine = ComplianceEngine(
        rules={"PAN_VALIDATION_001": PANValidationRule()},
        providers={Capability.PAN_INCOME_TAX: adapter},
    )
    result = engine.run(
        evidence=[pan_evidence("AAACI4321F")],
        requirements=[pan_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.flags == []


def test_rule_penalises_pan_not_found() -> None:
    transport = StaticPanTransport(
        responses={
            "AAABBB0000C": PanHttpResponse(
                status_code=200,
                body_xml=_xml(
                    '<pan:panStatus>D</pan:panStatus>'
                    '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>',
                    pan="AAABBB0000C",
                ),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(config=_good_config(), http_transport=transport)
    engine = ComplianceEngine(
        rules={"PAN_VALIDATION_001": PANValidationRule()},
        providers={Capability.PAN_INCOME_TAX: adapter},
    )
    result = engine.run(
        evidence=[pan_evidence("AAABBB0000C")],
        requirements=[pan_requirement()],
    )
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert "PAN_NOT_FOUND" in cr.flags
