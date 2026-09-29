import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, DateTime, Integer, Float, Boolean , JSON

# Environment-configurable; defaults keep the existing docker-compose setup.
_DATABASE_URL = os.getenv("DATABASE_URL")
if not _DATABASE_URL:
    _base = "gem_user:gem_pass@localhost:5432/gem_verification"
    try:  # psycopg 3 ships with the integrated Core-Engine-GeM dependencies
        import psycopg  # noqa: F401

        _DATABASE_URL = f"postgresql+psycopg://{_base}"
    except ImportError:
        _DATABASE_URL = f"postgresql://{_base}"  # psycopg2 driver

DATABASE_URL = _DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
import uuid, datetime

class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_zip_name = Column(String)
    status = Column(String, default="uploaded")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    entities_payload = Column(JSON, nullable=True)

class BidderFolder(Base):
    __tablename__ = "bidder_folders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id = Column(UUID(as_uuid=True))
    raw_folder_name = Column(String)
    document_count = Column(Integer, default=0)

class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bidder_folder_id = Column(UUID(as_uuid=True))
    original_relative_path = Column(String)
    stored_path = Column(String)
    extension = Column(String)
    extracted_text = Column(String)
    # Module 2 document-level extracted fields (Module 2 field names).
    # Produced ONCE by Module 2 during entity extraction so downstream
    # modules map — never re-extract — the values. {"gstin": "...", ...}
    extracted_fields = Column(JSON, nullable=True)
    classification_status = Column(String, default="pending")
    classified_type = Column(String)
    display_name = Column(String)
    pdf_producer = Column(String, nullable=True)
    has_digital_signature = Column(Boolean, default=False)
    font_anomaly_detected = Column(Boolean, default=False)

class DocumentEvidence(Base):
    """Document-level Core Evidence persisted for Module 4 provenance.

    One row per extracted field per document. ``evidence_id`` follows
    Core's canonical scheme ``<document_id>:<field_name>`` so every Module
    4 finding can be traced back to the source document and field.
    """

    __tablename__ = "document_evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id = Column(UUID(as_uuid=True))
    bidder_folder_id = Column(UUID(as_uuid=True))
    evidence_id = Column(String)
    document_id = Column(String)
    document_type = Column(String)
    field_name = Column(String)
    value = Column(JSON, nullable=True)          # {"value": ...}; never fabricated
    confidence = Column(Float, nullable=True)     # stays NULL when unknown
    page = Column(Integer, nullable=True)         # stays NULL when unknown
    bbox = Column(JSON, nullable=True)            # stays NULL when unknown
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class BidderComplianceResultRecord(Base):
    """Module 3 (ComplianceEngine) output persisted for one bidder.

    One row per requirement evaluated by the REAL compliance engine.
    ``status`` is the engine's ComplianceStatus (PASS / FAIL / MISSING /
    UNVERIFIABLE / NOT_CHECKED / NOT_APPLICABLE) — never fabricated; a
    provider outage stays UNVERIFIABLE with its honest reason.
    """

    __tablename__ = "bidder_compliance_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id = Column(UUID(as_uuid=True))
    bidder_folder_id = Column(UUID(as_uuid=True))
    bidder_id = Column(String)
    requirement_id = Column(String)
    capability = Column(String)
    status = Column(String)
    reason = Column(String, nullable=True)
    rule_id = Column(String, nullable=True)
    expected = Column(JSON, nullable=True)
    actual = Column(JSON, nullable=True)
    evidence_refs = Column(JSON, default=list)
    verification_refs = Column(JSON, default=list)
    flags = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class BidderVerificationRecord(Base):
    """Authoritative Module 3 provider Verification records (audit trail).

    One row per provider.verify() call made by the real compliance
    engine. All fields are faithful copies of the frozen ``Verification``
    model — statuses (VERIFIED / NOT_FOUND / INVALID / INACTIVE /
    UNAVAILABLE / ERROR) and payloads are never altered or invented.
    """

    __tablename__ = "bidder_verification_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id = Column(UUID(as_uuid=True))
    bidder_folder_id = Column(UUID(as_uuid=True))
    bidder_id = Column(String)
    verification_id = Column(String)
    capability = Column(String)
    source = Column(String)
    queried_identifier = Column(String, nullable=True)
    status = Column(String)
    data = Column(JSON, nullable=True)
    evidence_id = Column(String, nullable=True)
    document_id = Column(String, nullable=True)
    transport_status_code = Column(Integer, nullable=True)
    retrieved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class BidderVerificationResult(Base):
    """Module 4 output for one bidder: findings, canonical flags and the
    grounded explanations of those findings.

    Flags are produced ONLY by the deterministic Core engines; the
    explanations annotation is grounded, explanation-only output.
    """

    __tablename__ = "bidder_verification_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id = Column(UUID(as_uuid=True))
    bidder_folder_id = Column(UUID(as_uuid=True))
    status = Column(String)
    findings = Column(JSON, default=list)
    flags = Column(JSON, default=list)
    explanations = Column(JSON, default=list)
    error = Column(String, nullable=True)
    generated_at = Column(DateTime, default=datetime.datetime.utcnow)

class BidderDocumentScoreRecord(Base):
    """DocumentScoringEngine output persisted for one bidder.

    The score is produced AFTER Module 4 findings/flags exist, by the
    EXISTING Core ``ai_verification.document_scoring.DocumentScoringEngine``
    over the same document-level Evidence Module 4 consumed. This row is a
    faithful persistence of the engine's ``BidderDocumentScore`` — no
    scoring semantics are re-implemented or altered here.

    ``document_scores`` keeps per-document provenance: document_id,
    document_type, evidence_count, finding flag ids, reason codes and the
    per-document score, so the overall bidder score is auditable against
    the persisted document evidence and findings.
    """

    __tablename__ = "bidder_document_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id = Column(UUID(as_uuid=True))
    bidder_folder_id = Column(UUID(as_uuid=True))
    bidder_id = Column(String)
    submission_id = Column(String, nullable=True)
    status = Column(String)
    overall_score = Column(Float)
    category = Column(String)              # RED / YELLOW / GREEN
    reason_codes = Column(JSON, default=list)
    document_scores = Column(JSON, default=list)
    summary = Column(String)
    generated_at = Column(DateTime, default=datetime.datetime.utcnow)