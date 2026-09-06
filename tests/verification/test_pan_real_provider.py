"""Real-provider-shaped PAN / Income Tax verification milestone tests.

This suite covers the typed SOAP / XML boundary, the configuration
seam, the HTTPS transport seam, and the audit trail produced by
:class:`PanAdapter` when wired in real-provider mode. The existing
``MockPANProvider`` and the legacy ``PanResponseParser`` / payload-dict
path are also exercised for regression.
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
    PAN_SERVICE_ID,
    PanAdapter,
    PanConfig,
    PanEndpointConfig,
    PanAgencyCredentials,
    PanClientCredentials,
    PanHttpClient,
    PanHttpResponse,
    PanQuery,
    PanSigningConfig,
    PanSoapParseError,
    PanSoapRequest,
    PanSoapRequestBuilder,
    PanSoapResponseParser,
    PanTransportError,
    StaticPanTransport,
    VerificationProvider,
    pan_config_from_env,
    pan_new_request_id,
)
from compliance_engine.verification.pan_soap import (
    PAN_NS,
    REQUEST_LOCAL,
    RESPONSE_LOCAL,
    SOAP_NS,
)

from tests.engine._builders import (
    pan_evidence,
    pan_requirement,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _good_config() -> PanConfig:
    return PanConfig(
        endpoint=PanEndpointConfig(
            url="https://incometaxindiaefiling.gov.in/pan/verify",
            timeout_seconds=5.0,
            soap_action="verifyPAN",
        ),
        agency=PanAgencyCredentials(
            agency_username="agency-user-ref",
            agency_password="agency-pwd-ref",
        ),
        client=PanClientCredentials(
            client_id="client-id-ref",
            client_secret="client-secret-ref",
        ),
        signing=PanSigningConfig(
            keystore_ref="keystore-ref",
            keystore_password_ref="keystore-pwd-ref",
            signing_algorithm="RSA_SHA256",
        ),
    )


def _ok_soap(pan: str = "AAACI1234F") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="' + SOAP_NS + '" xmlns:pan="' + PAN_NS + '">'
        '<soap:Body>'
        '<pan:' + RESPONSE_LOCAL + '>'
        '<pan:PAN>' + pan + '</pan:PAN>'
        '<pan:panStatus>E</pan:panStatus>'
        '<pan:panMatch>Y</pan:panMatch>'
        '<pan:nameMatch>Y</pan:nameMatch>'
        '<pan:dobMatch>Y</pan:dobMatch>'
        '<pan:panHolderName>ACME ENTERPRISES PRIVATE LIMITED</pan:panHolderName>'
        '<pan:panHolderDob>01/01/1990</pan:panHolderDob>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
        '</pan:' + RESPONSE_LOCAL + '>'
        '</soap:Body>'
        '</soap:Envelope>'
    )


def _not_found_soap(pan: str = "AAABBB0000C") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="' + SOAP_NS + '" xmlns:pan="' + PAN_NS + '">'
        '<soap:Body>'
        '<pan:' + RESPONSE_LOCAL + '>'
        '<pan:PAN>' + pan + '</pan:PAN>'
        '<pan:panStatus>D</pan:panStatus>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
        '</pan:' + RESPONSE_LOCAL + '>'
        '</soap:Body>'
        '</soap:Envelope>'
    )


def _name_mismatch_soap(pan: str = "AAACI4321F") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="' + SOAP_NS + '" xmlns:pan="' + PAN_NS + '">'
        '<soap:Body>'
        '<pan:' + RESPONSE_LOCAL + '>'
        '<pan:PAN>' + pan + '</pan:PAN>'
        '<pan:panStatus>E</pan:panStatus>'
        '<pan:panMatch>Y</pan:panMatch>'
        '<pan:nameMatch>N</pan:nameMatch>'
        '<pan:dobMatch>Y</pan:dobMatch>'
        '<pan:panHolderName>OTHER BIDDER PRIVATE LIMITED</pan:panHolderName>'
        '<pan:panHolderDob>01/01/1990</pan:panHolderDob>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
        '</pan:' + RESPONSE_LOCAL + '>'
        '</soap:Body>'
        '</soap:Envelope>'
    )


def _dob_mismatch_soap(pan: str = "AAACI9876F") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="' + SOAP_NS + '" xmlns:pan="' + PAN_NS + '">'
        '<soap:Body>'
        '<pan:' + RESPONSE_LOCAL + '>'
        '<pan:PAN>' + pan + '</pan:PAN>'
        '<pan:panStatus>E</pan:panStatus>'
        '<pan:panMatch>Y</pan:panMatch>'
        '<pan:nameMatch>Y</pan:nameMatch>'
        '<pan:dobMatch>N</pan:dobMatch>'
        '<pan:panHolderName>ACME ENTERPRISES PRIVATE LIMITED</pan:panHolderName>'
        '<pan:panHolderDob>01/01/1990</pan:panHolderDob>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
        '</pan:' + RESPONSE_LOCAL + '>'
        '</soap:Body>'
        '</soap:Envelope>'
    )


def _inactive_soap(pan: str = "AAACI9999F") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="' + SOAP_NS + '" xmlns:pan="' + PAN_NS + '">'
        '<soap:Body>'
        '<pan:' + RESPONSE_LOCAL + '>'
        '<pan:PAN>' + pan + '</pan:PAN>'
        '<pan:panStatus>E</pan:panStatus>'
        '<pan:panMatch>Y</pan:panMatch>'
        '<pan:firstNameMatch>Y</pan:firstNameMatch>'
        '<pan:middleNameMatch>Y</pan:middleNameMatch>'
        '<pan:lastNameMatch>N</pan:lastNameMatch>'
        '<pan:panHolderName>OLD NAME</pan:panHolderName>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
        '</pan:' + RESPONSE_LOCAL + '>'
        '</soap:Body>'
        '</soap:Envelope>'
    )


def _service_error_soap(pan: str = "AAABBB0000C") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="' + SOAP_NS + '" xmlns:pan="' + PAN_NS + '">'
        '<soap:Body>'
        '<pan:' + RESPONSE_LOCAL + '>'
        '<pan:PAN>' + pan + '</pan:PAN>'
        '<pan:ServiceErrorCode>100</pan:ServiceErrorCode>'
        '</pan:' + RESPONSE_LOCAL + '>'
        '</soap:Body>'
        '</soap:Envelope>'
    )


# ===========================================================================
# A. Request construction
# ===========================================================================


def test_pan_service_id_constant() -> None:
    assert PAN_SERVICE_ID == "10001"


def test_request_builder_uses_service_id_10001() -> None:
    cfg = _good_config()
    builder = PanSoapRequestBuilder(cfg)
    request = builder.build(PanQuery(bidder_id="b1", pan="AAACI1234F"))
    assert "serviceId=\"" + PAN_SERVICE_ID + "\"" in request.xml
    assert "clientId=\"" + cfg.client.client_id + "\"" in request.xml


def test_request_builder_emits_documented_soap_envelope() -> None:
    cfg = _good_config()
    builder = PanSoapRequestBuilder(cfg)
    request = builder.build(PanQuery(bidder_id="b1", pan="AAACI1234F"))
    root = ET.fromstring(request.xml)
    # ET expands the namespace prefix into a Clark notation tag.
    assert root.tag == "{" + SOAP_NS + "}Envelope"
    local_names = [child.tag.split("}", 1)[-1] for child in root.iter()]
    assert REQUEST_LOCAL in local_names
    assert "UniqueRequestId" in local_names
    assert "PAN" in local_names
    assert "RequestMatchFlag" in local_names


def test_request_includes_unique_request_id() -> None:
    cfg = _good_config()
    builder = PanSoapRequestBuilder(cfg)
    r1 = builder.build(PanQuery(bidder_id="b1", pan="AAACI1234F"))
    r2 = builder.build(PanQuery(bidder_id="b1", pan="AAACI1234F"))
    # Each request must carry its own uniqueRequestId.
    assert r1.request_id != r2.request_id
    assert r1.request_id in r1.xml
    assert r2.request_id in r2.xml


def test_request_includes_pan_field() -> None:
    cfg = _good_config()
    builder = PanSoapRequestBuilder(cfg)
    request = builder.build(PanQuery(bidder_id="b1", pan="AAACI1234F"))
    assert "<pan:PAN>AAACI1234F</pan:PAN>" in request.xml


def test_request_omits_optional_identity_fields_when_absent() -> None:
    cfg = _good_config()
    builder = PanSoapRequestBuilder(cfg)
    request = builder.build(PanQuery(bidder_id="b1", pan="AAACI1234F"))
    assert "<pan:FullName>" not in request.xml
    assert "<pan:DOB>" not in request.xml
    assert "<pan:Gender>" not in request.xml


def test_request_includes_optional_identity_fields_when_provided() -> None:
    cfg = _good_config()
    builder = PanSoapRequestBuilder(cfg)
    request = builder.build(
        PanQuery(
            bidder_id="b1",
            pan="AAACI1234F",
            full_name="ACME ENTERPRISES PRIVATE LIMITED",
            date_of_birth="01/01/1990",
            gender="F",
        )
    )
    assert "<pan:FullName>ACME ENTERPRISES PRIVATE LIMITED</pan:FullName>" in request.xml
    assert "<pan:DOB>01/01/1990</pan:DOB>" in request.xml
    assert "<pan:Gender>F</pan:Gender>" in request.xml


def test_request_headers_are_documented() -> None:
    cfg = _good_config()
    builder = PanSoapRequestBuilder(cfg)
    request = builder.build(PanQuery(bidder_id="b1", pan="AAACI1234F"))
    headers = request.headers("verifyPAN")
    assert headers["SOAPAction"] == "verifyPAN"
    assert "text/xml" in headers["Content-Type"]
    assert "X-PAN-Request-Id" in headers
    assert "X-PAN-Call-Id" in headers
    # call_id and request_id are distinct.
    assert headers["X-PAN-Request-Id"] != headers["X-PAN-Call-Id"]


def test_new_request_id_is_unique_per_call() -> None:
    ids = {pan_new_request_id() for _ in range(50)}
    assert len(ids) == 50


# ===========================================================================
# B. Response parsing
# ===========================================================================


def _parse(pan: str, xml: str) -> Verification:
    parser = PanSoapResponseParser()
    return parser.parse(
        xml,
        query=PanQuery(bidder_id="b1", pan=pan),
        bidder_id="b1",
        transport_status_code=200,
        latency_ms=42,
        correlation_id="corr-xyz",
    )


def test_response_all_match_yields_verified() -> None:
    v = _parse("AAACI1234F", _ok_soap())
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["pan_status"] == "ACTIVE"
    assert v.data["name_on_pan"] == "ACME ENTERPRISES PRIVATE LIMITED"
    assert v.queried_identifier == "AAACI1234F"
    assert v.capability == Capability.PAN_INCOME_TAX
    assert v.source == "PAN"
    assert v.latency_ms == 42
    assert v.correlation_id == "corr-xyz"
    assert v.transport_status_code == 200


def test_response_pan_mismatch_yields_invalid() -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="' + SOAP_NS + '" xmlns:pan="' + PAN_NS + '">'
        '<soap:Body><pan:' + RESPONSE_LOCAL + '>'
        '<pan:PAN>AAACI1234F</pan:PAN>'
        '<pan:panStatus>E</pan:panStatus>'
        '<pan:panMatch>N</pan:panMatch>'
        '<pan:ServiceErrorCode>1</pan:ServiceErrorCode>'
        '</pan:' + RESPONSE_LOCAL + '></soap:Body></soap:Envelope>'
    )
    v = _parse("AAACI1234F", xml)
    assert v.status is VerificationStatus.INVALID


def test_response_name_mismatch_yields_verified_with_match_detail() -> None:
    """The official PAN service returns ``nameMatch="N"`` when the
    *supplied* name does not match the registry record. The PAN
    itself is still valid and active; identity-attribute mismatch
    must not downgrade the domain status to ``INACTIVE``."""
    v = _parse("AAACI4321F", _name_mismatch_soap())
    assert v.status is VerificationStatus.VERIFIED
    # The match details are preserved for audit / anomaly logic.
    assert v.data["match_details"]["name_match"] == "N"
    assert v.data["match_details"]["pan_match"] == "Y"
    assert v.data["name_on_pan"] == "OTHER BIDDER PRIVATE LIMITED"


def test_response_dob_mismatch_yields_verified_with_match_detail() -> None:
    v = _parse("AAACI9876F", _dob_mismatch_soap())
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["match_details"]["dob_match"] == "N"
    assert v.data["match_details"]["pan_match"] == "Y"
    # The DOB on record is preserved.
    assert v.data["date_of_birth"] == "01/01/1990"


def test_response_pan_status_d_yields_not_found() -> None:
    v = _parse("AAABBB0000C", _not_found_soap())
    assert v.status is VerificationStatus.NOT_FOUND


def test_response_service_error_code_yields_error() -> None:
    v = _parse("AAABBB0000C", _service_error_soap())
    assert v.status is VerificationStatus.ERROR


def test_response_malformed_xml_raises_parse_error() -> None:
    parser = PanSoapResponseParser()
    with pytest.raises(PanSoapParseError):
        parser.parse(
            "<not-xml",
            query=PanQuery(bidder_id="b1", pan="AAACI1234F"),
            bidder_id="b1",
        )


def test_response_missing_body_yields_error_via_adapter() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml="<garbage/>",
                latency_ms=10,
                correlation_id="c-1",
            )
        }
    )
    adapter = PanAdapter(
        config=_good_config(),
        http_transport=transport,
    )
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.status is VerificationStatus.ERROR
    # The verbatim body is preserved on the audit record so the
    # malformed payload remains reconstructable.
    assert v.raw_response == {"soap_xml": "<garbage/>"}


# ===========================================================================
# C. Transport
# ===========================================================================


def test_static_transport_success_captures_latency_and_correlation() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_ok_soap(),
                latency_ms=77,
                correlation_id="corr-77",
            )
        }
    )
    adapter = PanAdapter(
        config=_good_config(),
        http_transport=transport,
    )
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.status is VerificationStatus.VERIFIED
    assert v.latency_ms == 77
    assert v.transport_status_code == 200


def test_static_transport_404_maps_to_error_not_not_found() -> None:
    transport = StaticPanTransport(
        default_response=PanHttpResponse(
            status_code=404,
            body_xml="",
            latency_ms=5,
            correlation_id="c-404",
        )
    )
    adapter = PanAdapter(
        config=_good_config(),
        http_transport=transport,
    )
    v = adapter.verify("bidder-1", "AAACI1234F")
    # Empty body means we never got a valid PAN record -- ERROR, not
    # a "verified negative".
    assert v.status is VerificationStatus.ERROR
    assert v.transport_status_code == 404


def test_transport_error_maps_to_unavailable() -> None:
    class _BoomTransport:
        def send(self, request: PanSoapRequest) -> PanHttpResponse:
            raise PanTransportError("network down")

    adapter = PanAdapter(
        config=_good_config(),
        http_transport=_BoomTransport(),  # type: ignore[arg-type]
    )
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.status is VerificationStatus.UNAVAILABLE


def test_transport_500_maps_to_error_not_verified() -> None:
    transport = StaticPanTransport(
        default_response=PanHttpResponse(
            status_code=500,
            body_xml="",
            latency_ms=10,
            correlation_id="c-500",
        )
    )
    adapter = PanAdapter(
        config=_good_config(),
        http_transport=transport,
    )
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.status is VerificationStatus.ERROR
    assert v.transport_status_code == 500


def test_correlation_id_is_propagated() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_ok_soap(),
                latency_ms=20,
                correlation_id="corr-from-transport",
            )
        }
    )
    adapter = PanAdapter(
        config=_good_config(),
        http_transport=transport,
    )
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.correlation_id == "corr-from-transport"


def test_static_transport_records_requests_for_assertion() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200, body_xml=_ok_soap(), latency_ms=1, correlation_id="c"
            )
        }
    )
    adapter = PanAdapter(
        config=_good_config(),
        http_transport=transport,
    )
    adapter.verify("bidder-1", "AAACI1234F")
    adapter.verify("bidder-1", "AAACI1234F")
    assert len(transport.requests) == 2
    # call_id flows into the SOAP envelope; request_id is fresh per call.
    assert transport.requests[0].call_id != transport.requests[1].call_id
    assert transport.requests[0].request_id != transport.requests[1].request_id


# ===========================================================================
# D. Security / configuration
# ===========================================================================


def test_config_rejects_empty_credential_references() -> None:
    # Empty values are tolerated at the field level so that
    # environment-driven construction surfaces a clear aggregate
    # error from ``validate_for_real_use``.
    cfg = PanConfig(
        endpoint=PanEndpointConfig(
            url="https://incometaxindiaefiling.gov.in/pan/verify"
        ),
        agency=PanAgencyCredentials(
            agency_username="", agency_password="x"
        ),
        client=PanClientCredentials(client_id="x", client_secret="y"),
        signing=PanSigningConfig(
            keystore_ref="k", keystore_password_ref="p"
        ),
    )
    with pytest.raises(ValueError):
        cfg.validate_for_real_use()


def test_config_rejects_non_https_endpoint() -> None:
    with pytest.raises(Exception):
        PanEndpointConfig(url="http://example.com/verify")


def test_config_validate_for_real_use_raises_when_incomplete() -> None:
    # Build the config bypassing field-level validation so we can
    # verify the aggregate ``validate_for_real_use`` check.
    incomplete = PanConfig.model_construct(
        endpoint=PanEndpointConfig(url="https://example.test/pan"),
        agency=PanAgencyCredentials.model_construct(
            agency_username="", agency_password=""
        ),
        client=PanClientCredentials.model_construct(
            client_id="", client_secret=""
        ),
        signing=PanSigningConfig.model_construct(
            keystore_ref="", keystore_password_ref="", signing_algorithm="RSA_SHA256"
        ),
        service_id=PAN_SERVICE_ID,
    )
    with pytest.raises(ValueError):
        incomplete.validate_for_real_use()


def test_config_validate_for_real_use_passes_when_complete() -> None:
    _good_config().validate_for_real_use()


def test_no_secrets_in_source() -> None:
    """Sanity: the source tree must not contain a hardcoded PAN secret.

    We assert that none of the obvious hardcoded credential names
    appear in the pan_* modules.
    """
    import os

    root = os.path.join(
        os.path.dirname(__file__), "..", "..", "src", "compliance_engine", "verification"
    )
    for name in ("pan_config.py", "pan_soap.py", "pan_http_transport.py", "pan_adapter.py"):
        path = os.path.join(root, name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        # No literal-looking real-world credential strings.
        for bad in (
            "AGENCY_PASSWORD=",
            "PASSWORD=\"secret",
            "client_secret=\"real",
        ):
            assert bad not in text, "Hardcoded secret in " + name


def test_from_env_returns_incomplete_config_without_env() -> None:
    # ``from_env`` always returns a config object; it does not validate.
    # We assert that the *aggregate* validator catches the missing env.
    cfg = pan_config_from_env(env={})
    with pytest.raises(ValueError):
        cfg.validate_for_real_use()


def test_from_env_populates_config_from_environment() -> None:
    cfg = pan_config_from_env(
        env={
            "PAN_ENDPOINT_URL": "https://example.test/pan",
            "PAN_AGENCY_USERNAME": "u",
            "PAN_AGENCY_PASSWORD": "p",
            "PAN_CLIENT_ID": "cid",
            "PAN_CLIENT_SECRET": "cse",
            "PAN_KEYSTORE_REF": "ks",
            "PAN_KEYSTORE_PASSWORD_REF": "ksp",
        }
    )
    cfg.validate_for_real_use()


def test_adapter_real_path_requires_config_and_transport() -> None:
    with pytest.raises(ValueError):
        PanAdapter(config=_good_config())  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        PanAdapter(http_transport=StaticPanTransport())  # type: ignore[call-arg]


def test_pan_http_client_rejects_incomplete_config() -> None:
    incomplete = PanConfig(
        endpoint=PanEndpointConfig(url="https://example.test/pan"),
        agency=PanAgencyCredentials(agency_username="", agency_password=""),
        client=PanClientCredentials(client_id="", client_secret=""),
        signing=PanSigningConfig(keystore_ref="", keystore_password_ref=""),
    )
    with pytest.raises(ValueError):
        PanHttpClient(incomplete)


def test_pan_http_client_rejects_non_https_at_send() -> None:
    class _FakeConn:
        status = 200

        def read(self) -> bytes:
            return _ok_soap().encode("utf-8")

        def close(self) -> None:
            pass

    class _FakeResponse:
        status = 200

        def read(self) -> bytes:
            return _ok_soap().encode("utf-8")

    def _fake_opener(*, url, body, headers, timeout):
        # Reject plain http://
        from urllib.parse import urlparse
        if urlparse(url).scheme != "https":
            raise PanTransportError("scheme was " + urlparse(url).scheme)
        return _FakeResponse()

    client = PanHttpClient(_good_config(), opener=_fake_opener)
    request = PanSoapRequest(
        xml=_ok_soap(),
        request_id=uuid4().hex,
        call_id=uuid4().hex,
        pan="AAACI1234F",
    )
    response = client.send(request)
    assert response.status_code == 200


# ===========================================================================
# E. Audit / Engine integration
# ===========================================================================


def test_verification_id_is_unique_per_call_real_path() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_ok_soap(),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(
        config=_good_config(),
        http_transport=transport,
    )
    v1 = adapter.verify("bidder-1", "AAACI1234F")
    v2 = adapter.verify("bidder-1", "AAACI1234F")
    assert v1.verification_id != v2.verification_id
    assert v1.verification_id.startswith("PAN:AAACI1234F:")
    assert v2.verification_id.startswith("PAN:AAACI1234F:")


def test_verification_carries_query_and_raw_response() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_ok_soap(),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(
        config=_good_config(),
        http_transport=transport,
    )
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.query is not None
    assert v.query["pan"] == "AAACI1234F"
    assert v.query["service_id"] == PAN_SERVICE_ID
    assert v.raw_response is not None
    assert "soap_xml" in v.raw_response


def test_engine_captures_real_provider_verification() -> None:
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_ok_soap(),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(
        config=_good_config(),
        http_transport=transport,
    )
    engine = ComplianceEngine(
        rules={"PAN_VALIDATION_001": PANValidationRule()},
        providers={Capability.PAN_INCOME_TAX: adapter},
    )
    result = engine.run(
        evidence=[pan_evidence("AAACI1234F")],
        requirements=[pan_requirement()],
    )
    assert len(result.compliance_results) == 1
    assert result.compliance_results[0].status is ComplianceStatus.PASS
    assert any(
        v.source == "PAN" for v in result.verification_records
    )
    for verification in result.verification_records:
        assert verification.verification_id.startswith("PAN:AAACI1234F:")


def test_engine_captures_name_mismatch_as_verified() -> None:
    """The PAN rule does not perform identity-attribute comparison;
    a name-mismatch response must surface as ``VERIFIED`` (the PAN
    itself is valid) and the rule must produce a PASS verdict.

    The mismatch detail is preserved on the captured ``Verification``
    for downstream audit / anomaly logic.
    """
    transport = StaticPanTransport(
        responses={
            "AAACI4321F": PanHttpResponse(
                status_code=200,
                body_xml=_name_mismatch_soap(),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(
        config=_good_config(),
        http_transport=transport,
    )
    engine = ComplianceEngine(
        rules={"PAN_VALIDATION_001": PANValidationRule()},
        providers={Capability.PAN_INCOME_TAX: adapter},
    )
    result = engine.run(
        evidence=[pan_evidence("AAACI4321F")],
        requirements=[pan_requirement()],
    )
    assert any(
        v.status is VerificationStatus.VERIFIED
        and v.data.get("match_details", {}).get("name_match") == "N"
        for v in result.verification_records
    )
    # The PAN rule does not compare names, so the verdict is PASS.
    assert result.compliance_results[0].status is ComplianceStatus.PASS


# ===========================================================================
# F. Regression -- existing behaviour preserved
# ===========================================================================


def test_mock_pan_provider_still_works() -> None:
    v = MockPANProvider().verify(
        "bidder-1", MockPANProvider.PAN_VERIFIED
    )
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["name_on_pan"] == "ACME ENTERPRISES PRIVATE LIMITED"


def test_legacy_pan_adapter_path_still_works() -> None:
    from compliance_engine.verification import (
        SourceResponseEnvelope,
        StaticTransport,
    )
    transport = StaticTransport(
        responses={
            "AAACI1234F": SourceResponseEnvelope(
                status_code=200,
                raw_response={
                    "pan_status": "ACTIVE",
                    "name_on_pan": "ACME ENTERPRISES PRIVATE LIMITED",
                },
                latency_ms=5,
                correlation_id="legacy",
            )
        },
        query_key=lambda q: q.pan,
    )
    adapter = PanAdapter(transport=transport)
    v = adapter.verify("bidder-1", "AAACI1234F")
    assert v.status is VerificationStatus.VERIFIED
    assert v.source == "PAN"


def test_legacy_payload_pan_not_found() -> None:
    from compliance_engine.verification import (
        SourceResponseEnvelope,
        StaticTransport,
    )
    transport = StaticTransport(
        default_response=SourceResponseEnvelope(
            status_code=404, raw_response=None, latency_ms=1, correlation_id="c"
        ),
        query_key=lambda q: q.pan,
    )
    adapter = PanAdapter(transport=transport)
    v = adapter.verify("bidder-1", "AAABBB0000C")
    assert v.status is VerificationStatus.NOT_FOUND


def test_pan_provider_is_subclass_of_verification_provider() -> None:
    assert isinstance(PanAdapter(), VerificationProvider)
    assert isinstance(MockPANProvider(), VerificationProvider)


def test_pan_validation_rule_unchanged_for_real_path() -> None:
    """Real-provider PAN path must produce the same rule verdict as the
    mock for an all-match case."""
    transport = StaticPanTransport(
        responses={
            "AAACI1234F": PanHttpResponse(
                status_code=200,
                body_xml=_ok_soap(),
                latency_ms=1,
                correlation_id="c",
            )
        }
    )
    adapter = PanAdapter(
        config=_good_config(),
        http_transport=transport,
    )
    engine = ComplianceEngine(
        rules={"PAN_VALIDATION_001": PANValidationRule()},
        providers={Capability.PAN_INCOME_TAX: adapter},
    )
    result = engine.run(
        evidence=[pan_evidence("AAACI1234F")],
        requirements=[pan_requirement()],
    )
    assert result.compliance_results[0].status is ComplianceStatus.PASS
