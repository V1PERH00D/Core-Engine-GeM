"""SOAP / XML boundary for the Income Tax PAN Verification Web Service.

This module encapsulates the documented SOAP request / response shape
for the official PAN Verification Web Service (service ID 10001). It
provides:

* :class:`PanSoapRequestBuilder` -- builds a deterministic SOAP/XML
  request envelope from a :class:`PanQuery` plus a
  :class:`PanConfig`.
* :class:`PanSoapResponseParser` -- parses a SOAP/XML response into
  a :class:`Verification` with the domain
  :class:`VerificationStatus` derived from the response payload
  semantics, never from the transport status code.

Architectural intent
--------------------

The Compliance Engine must never touch XML. Adapters, rules, and the
engine consume only typed pydantic models. This module is the only
place that knows about ``<soap:Envelope>``, ``<PANVerificationRequest>``,
``<PANVerificationResponse>``, and the documented per-field match
flags.

The XML is built / parsed using the Python standard library
(``xml.etree.ElementTree``) so we do not require a SOAP client
dependency. The output is well-formed and matches the field names that
the official service publishes; the transport is responsible for any
WS-Security signature / encryption headers.

What the official service publishes in the response
---------------------------------------------------

* ``pan``               -- echoed PAN
* ``panStatus``         -- e.g. "E" (valid/exists), "D" (deleted), "F" (fake)
* ``panHolderName``     -- name on the PAN card
* ``panHolderDob``      -- date of birth on record
* match flags:
  - ``panMatch``         -- "Y" / "N". Authoritative judgement of
    whether the supplied PAN matches the registry. "N" => the PAN
    is invalid.
  - ``nameMatch``        -- "Y" / "N". Whether the supplied full name
    matches the PAN holder's name on record.
  - ``dobMatch``         -- "Y" / "N". Whether the supplied DOB
    matches the DOB on record.
  - ``firstNameMatch`` / ``middleNameMatch`` / ``lastNameMatch`` --
    "Y" / "N" for the per-component name comparison.
* a service-level error code / message when the call itself fails
  (e.g. ``"1"`` for success, ``"100"`` for invalid PAN format, etc.).

The mapping from those flags to :class:`VerificationStatus` is the
single source of truth in this module:

* ``ServiceErrorCode != "1"``  -> ``ERROR`` (service-declared error)
* ``panStatus != "E"``         -> ``NOT_FOUND`` (PAN not in active
  registry; the service uses panStatus "D" for deleted/inactive
  records and "F" for fake PANs)
* ``panMatch == "N"``          -> ``INVALID`` (the supplied PAN is
  invalid)
* otherwise                    -> ``VERIFIED`` (the PAN is valid and
  active; name / DOB / component mismatch details are preserved in
  ``Verification.data["match_details"]`` for audit but do NOT
  downgrade the PAN status to ``INACTIVE`` because the official
  service does not declare identity-attribute mismatches as
  "inactive PAN".)

``INACTIVE`` is reserved for an explicit "inactive" status code
returned by the registry, which the documented contract does not
include.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:  # pragma: no cover - import-only types
    from compliance_engine.verification.pan_adapter import (
        NormalizedPanData,
        PanQuery,
    )

from compliance_engine.models import (
    Capability,
    Verification,
    VerificationStatus,
)
from compliance_engine.verification.pan_config import (
    PAN_SERVICE_ID,
    PanConfig,
    new_request_id,
)


# SOAP namespace bindings used by the official service.
SOAP_NS: Final[str] = "http://schemas.xmlsoap.org/soap/envelope/"
PAN_NS: Final[str] = (
    "http://incometaxindiaefiling.gov.in/pan/verification"
)

#: Root local name of the request envelope.
REQUEST_LOCAL: Final[str] = "PANVerificationRequest"
#: Root local name of the response envelope.
RESPONSE_LOCAL: Final[str] = "PANVerificationResponse"


# ---------------------------------------------------------------------------
# Request builder
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PanSoapRequest:
    """A deterministic, fully built SOAP request envelope.

    The transport layer is responsible for the WS-Security headers and
    the network call; this object is the verbatim XML body to ship.
    """

    xml: str
    request_id: str
    call_id: str
    pan: str

    def headers(self, soap_action: str) -> dict[str, str]:
        """HTTP headers for the official endpoint.

        Kept as a separate method so the transport can add WS-Security
        headers / signing without re-parsing the XML.
        """

        return {
            "Content-Type": (
                'text/xml; charset="utf-8"; '
                'action="' + soap_action + '"'
            ),
            "SOAPAction": soap_action,
            "X-PAN-Request-Id": self.request_id,
            "X-PAN-Call-Id": self.call_id,
        }


class PanSoapRequestBuilder:
    """Build a :class:`PanSoapRequest` from a typed query + config.

    The builder is stateless and deterministic given its inputs; this
    makes the request shape unit-testable without any network access.
    """

    def __init__(self, config: PanConfig) -> None:
        self._config = config

    def build(self, query: "PanQuery") -> PanSoapRequest:
        cfg = self._config
        # Per-request unique ids. The official service requires a
        # uniqueRequestId for every request; we keep it separate from
        # the per-call ``call_id`` so the two audit ids never collide.
        request_id = new_request_id()

        envelope = ET.Element(
            "soap:Envelope",
            attrib={
                "xmlns:soap": SOAP_NS,
                "xmlns:pan": PAN_NS,
            },
        )
        header = ET.SubElement(envelope, "soap:Header")
        # Per the published contract the serviceId + clientId +
        # clientSecret travel in the SOAP header.
        ET.SubElement(
            header,
            "pan:ServiceContext",
            attrib={
                "serviceId": cfg.service_id,
                "clientId": cfg.client.client_id,
            },
        )
        # The client secret is sent inside an EncryptedData element in
        # a real signed/encrypted envelope. For this milestone we
        # preserve the field as an element with the placeholder text
        # "***" and a clear comment attribute; the transport's signing
        # layer is responsible for replacing it with the actual
        # encrypted value before transmission. **No real secret is
        # ever held in this object.**
        secret_el = ET.SubElement(
            header,
            "pan:ClientSecret",
            attrib={"ref": "encrypted"},
        )
        secret_el.text = "***"

        body = ET.SubElement(envelope, "soap:Body")
        req = ET.SubElement(body, "pan:" + REQUEST_LOCAL)
        ET.SubElement(req, "pan:UniqueRequestId").text = request_id
        ET.SubElement(req, "pan:PAN").text = query.pan
        # Name / DOB / gender are optional but the schema documents
        # them; the Compliance Engine never sets them today because
        # the rules are PAN-only. They are accepted in the model but
        # omitted from the request body when absent so we do not
        # generate empty fields.
        if query.full_name is not None:
            ET.SubElement(req, "pan:FullName").text = query.full_name
        if query.first_name is not None:
            ET.SubElement(req, "pan:FirstName").text = query.first_name
        if query.middle_name is not None:
            ET.SubElement(req, "pan:MiddleName").text = query.middle_name
        if query.last_name is not None:
            ET.SubElement(req, "pan:LastName").text = query.last_name
        if query.date_of_birth is not None:
            ET.SubElement(req, "pan:DOB").text = query.date_of_birth
        if query.gender is not None:
            ET.SubElement(req, "pan:Gender").text = query.gender
        # The requested match flag is always "Y" in this milestone.
        ET.SubElement(req, "pan:RequestMatchFlag").text = "Y"

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(envelope, encoding="unicode")
        )
        return PanSoapRequest(
            xml=xml,
            request_id=request_id,
            call_id=query.call_id,
            pan=query.pan,
        )


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


class PanSoapParseError(ValueError):
    """Raised when the SOAP/XML response cannot be interpreted."""


def _text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


class PanSoapResponseParser:
    """Map a SOAP/XML PAN response to a :class:`Verification`.

    The parser is the single place that decides the domain
    :class:`VerificationStatus`. The transport status code (HTTP 200
    vs 500) is recorded on the :class:`Verification` for audit but is
    **never** the sole determinant of the domain status.
    """

    def parse(
        self,
        xml: str,
        *,
        query: "PanQuery",
        bidder_id: str,
        transport_status_code: int | None = None,
        latency_ms: int | None = None,
        correlation_id: str | None = None,
    ) -> Verification:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise PanSoapParseError(
                "Malformed SOAP response: " + str(exc)
            ) from exc

        body = self._find_body(root)
        response_node = self._find_response(body)
        if response_node is None:
            raise PanSoapParseError(
                "SOAP response is missing the " + RESPONSE_LOCAL + " element."
            )

        domain_status, data = self._derive_domain_status(response_node)
        raw_fields = self._serialise_node(response_node)
        # Preserve the full, verbatim SOAP envelope on the audit
        # record so the raw response is reconstructable for audit /
        # anomaly logic, and additionally expose the parsed fields
        # for consumers that prefer a structured view.
        raw_response: dict[str, Any] = {
            "soap_xml": xml,
            "fields": raw_fields,
        }

        return Verification(
            verification_id=Verification.allocate_id(
                source="PAN",
                identifier=query.pan,
                call_id=query.call_id,
            ),
            bidder_id=bidder_id,
            capability=Capability.PAN_INCOME_TAX,
            source="PAN",
            queried_identifier=query.pan,
            status=domain_status,
            data=data,
            retrieved_at=datetime.now(UTC),
            query={
                "pan": query.pan,
                "call_id": query.call_id,
                "service_id": PAN_SERVICE_ID,
            },
            raw_response=raw_response,
            latency_ms=latency_ms,
            correlation_id=correlation_id,
            transport_status_code=transport_status_code,
        )

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _find_body(root: ET.Element) -> ET.Element | None:
        for child in root.iter():
            if child.tag.endswith("}Body") or child.tag == "Body":
                return child
        return None

    @staticmethod
    def _find_response(body: ET.Element | None) -> ET.Element | None:
        if body is None:
            return None
        for child in body.iter():
            local = child.tag.split("}", 1)[-1]
            if local == RESPONSE_LOCAL:
                return child
        return None

    @staticmethod
    def _serialise_node(node: ET.Element) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for child in node:
            local = child.tag.split("}", 1)[-1]
            value = child.text
            if value is not None and value.strip().startswith("<"):
                # Avoid stuffing nested XML into the audit blob.
                out[local] = value.strip()[:512]
            else:
                out[local] = (value or "").strip() or None
        return out

    @staticmethod
    def _derive_domain_status(
        response: ET.Element,
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        from compliance_engine.verification.pan_adapter import NormalizedPanData

        # Service-level error codes come first. The published codes
        # include "1" for success and a small set of numeric error
        # codes; we treat anything that is not "1" (or absent) as a
        # service-level error / malformed response.
        code = _text(_find_child(response, "ServiceErrorCode"))
        if code is not None and code != "1":
            return VerificationStatus.ERROR, {}

        pan_status = _text(_find_child(response, "panStatus"))
        pan_match = _text(_find_child(response, "panMatch"))
        name_match = _text(_find_child(response, "nameMatch"))
        dob_match = _text(_find_child(response, "dobMatch"))
        first_name_match = _text(_find_child(response, "firstNameMatch"))
        middle_name_match = _text(_find_child(response, "middleNameMatch"))
        last_name_match = _text(_find_child(response, "lastNameMatch"))

        # The PAN Verification Web Service publishes these match flags:
        #
        #   * panStatus  -- "E" (existing/active), "D" (deleted), "F"
        #                   (fake), etc. Only "E" indicates the PAN is
        #                   genuinely registered.
        #   * panMatch   -- "Y" / "N". The authoritative judgement of
        #                   whether the supplied PAN matches the
        #                   registry. "N" => the PAN is invalid.
        #   * nameMatch / dobMatch / firstNameMatch / middleNameMatch /
        #     lastNameMatch -- "Y" / "N". These reflect whether the
        #     *supplied* identity attributes (name / DOB) match the
        #     registry record. They are not a statement about the
        #     PAN's existence or status -- a "N" here means the
        #     bidder-supplied name/DOB does not match the PAN
        #     holder's name/DOB, not that the PAN itself is inactive.
        #
        # The domain ``VerificationStatus`` is therefore:
        #
        #   panStatus != "E"  => NOT_FOUND  (PAN not in active registry)
        #   panMatch  == "N"  => INVALID    (the supplied PAN is invalid)
        #   else              => VERIFIED   (the PAN itself is valid and
        #                                    active; the match details
        #                                    are preserved in ``data``
        #                                    for audit/anomaly logic but
        #                                    do NOT downgrade the PAN
        #                                    status to INACTIVE).
        #
        # ``INACTIVE`` is reserved for the case where the registry
        # explicitly returns an "inactive" status code. The documented
        # contract does not include such a code (the registry uses
        # panStatus "D" for deleted/inactive records, which is mapped to
        # NOT_FOUND above). If a future contract revision adds an
        # explicit inactive code it can be mapped here without
        # changing the rule layer.

        if pan_status is not None and pan_status != "E":
            return VerificationStatus.NOT_FOUND, {}

        if pan_match is None and name_match is None and dob_match is None:
            # No match flags at all means the response is missing the
            # documented semantics.
            return VerificationStatus.ERROR, {}

        if pan_match == "N":
            return VerificationStatus.INVALID, {}

        # Build a normalized data record from the documented registry
        # fields. The PAN itself is verified; mismatch details are
        # preserved so the rule / audit / anomaly layers can decide
        # what to do with them.
        name = _text(_find_child(response, "panHolderName"))
        dob = _text(_find_child(response, "panHolderDob"))
        match_details: dict[str, str] = {}
        for label, value in (
            ("pan_match", pan_match),
            ("name_match", name_match),
            ("dob_match", dob_match),
            ("first_name_match", first_name_match),
            ("middle_name_match", middle_name_match),
            ("last_name_match", last_name_match),
        ):
            if value is not None:
                match_details[label] = value
        if name is None and dob is not None:
            # Defensive: dob is in the document but the holder name
            # was redacted.
            name = None
        data: dict[str, Any] = {}
        try:
            data = NormalizedPanData(
                pan_status="ACTIVE",
                name_on_pan=name,
            ).model_dump()
        except Exception:
            data = {}
        if match_details:
            data["match_details"] = match_details
        if dob is not None:
            data["date_of_birth"] = dob

        return VerificationStatus.VERIFIED, data


def _find_child(node: ET.Element, local_name: str) -> ET.Element | None:
    for child in node:
        if child.tag.split("}", 1)[-1] == local_name:
            return child
    return None


__all__ = [
    "PanSoapParseError",
    "PanSoapRequest",
    "PanSoapRequestBuilder",
    "PanSoapResponseParser",
    "PAN_NS",
    "REQUEST_LOCAL",
    "RESPONSE_LOCAL",
    "SOAP_NS",
]
