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