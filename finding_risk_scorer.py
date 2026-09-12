"""
finding_risk_scorer.py

Scores a set of verification "findings" (anomalies/flags raised against a
bid or bidder) using the contract schema:

    Finding ID
    Flag / anomaly type
    Severity
    AI confidence score
    Human-readable explanation
    Supporting document/evidence references
    Verification references
    Related bidder IDs (when applicable)
    Similarity/anomaly trace (when applicable)

Produces a single case-level risk score (0-10), classifies it into
RED / YELLOW / GREEN, and persists everything to SQLite.

ALGORITHM ("dominant + decayed" risk aggregation)
--------------------------------------------------
1. Each finding gets a weighted risk = severity_weight * ai_confidence.
   Severity weights (0-10 scale): LOW=2, MEDIUM=4, HIGH=7, CRITICAL=10.
2. Findings are sorted by weighted risk, descending.
3. The single highest-weighted finding becomes the "dominant" risk -
   this sets a floor so one severe, confident finding can't be diluted
   by a pile of minor ones.
4. Every other finding still contributes, but with decay applied by
   rank (0.5^rank) - correlated smaller issues can still push the
   score up, but a long tail of noise can't dominate the result.
5. Hard override: any single CRITICAL-severity finding with AI
   confidence >= 0.85 forces the case to RED, regardless of the
   aggregate math. Certain signals should always escalate.
6. The result is scaled to 0-10 and classified:
       GREEN  : 0   - 3.0   -> auto-clear
       YELLOW : 3.0 - 6.5   -> manual review queue
       RED    : 6.5 - 10, or override -> escalate to officer immediately
"""

import sqlite3
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


class Severity(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_WEIGHTS: Dict[Severity, float] = {
    Severity.LOW: 2.0,
    Severity.MEDIUM: 4.0,
    Severity.HIGH: 7.0,
    Severity.CRITICAL: 10.0,
}

CRITICAL_OVERRIDE_CONFIDENCE = 0.85
DECAY_FACTOR = 0.5


class Category(Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


CATEGORY_ACTION = {
    Category.GREEN: "Auto-clear - no material anomalies detected.",
    Category.YELLOW: "Queue for manual review.",
    Category.RED: "Escalate to officer immediately - high-confidence anomaly.",
}


@dataclass
class VerificationFinding:
    finding_id: str
    flag_type: str
    severity: Severity
    ai_confidence_score: float  # normalized 0.0 - 1.0
    explanation: str
    supporting_references: List[str] = field(default_factory=list)
    verification_references: List[str] = field(default_factory=list)
    related_bidder_ids: List[str] = field(default_factory=list)
    similarity_trace: Optional[Dict] = None

    @staticmethod
    def from_dict(raw: Dict) -> "VerificationFinding":
        """
        Builds a VerificationFinding from a dict shaped like the
        verification contract. Accepts confidence as 0-1 or 0-100.
        """
        severity_raw = str(raw.get("severity", "LOW")).strip().upper()
        try:
            severity = Severity(severity_raw)
        except ValueError:
            severity = Severity.LOW

        confidence = float(raw.get("ai_confidence_score", 0.0))
        if confidence > 1.0:  # tolerate 0-100 scale input
            confidence = confidence / 100.0
        confidence = max(0.0, min(1.0, confidence))

        return VerificationFinding(
            finding_id=raw.get("finding_id", ""),
            flag_type=raw.get("flag_type", "Unspecified"),
            severity=severity,
            ai_confidence_score=confidence,
            explanation=raw.get("explanation", ""),
            supporting_references=raw.get("supporting_references", []) or [],
            verification_references=raw.get("verification_references", []) or [],
            related_bidder_ids=raw.get("related_bidder_ids", []) or [],
            similarity_trace=raw.get("similarity_trace"),
        )

    def weighted_risk(self) -> float:
        return SEVERITY_WEIGHTS[self.severity] * self.ai_confidence_score


@dataclass
class CaseScoringResult:
    case_id: str
    bidder_id: str
    findings: List[VerificationFinding]
    scaled_score: float
    category: Category
    override_triggered: bool
    dominant_finding: Optional[VerificationFinding]
    related_bidder_network: List[str]
    next_action: str

    def summary(self) -> str:
        lines = [
            "=== Finding-Based Risk Scoring Result ===",
            f"Case ID           : {self.case_id}",
            f"Bidder ID         : {self.bidder_id}",
            f"Risk Score        : {self.scaled_score}/10",
            f"Category          : {self.category.value}"
            + (" (override triggered)" if self.override_triggered else ""),
            f"Next Action       : {self.next_action}",
            "",
            "Findings (sorted by weighted risk):",
        ]
        for f in sorted(self.findings, key=lambda x: x.weighted_risk(), reverse=True):
            lines.append(
                f"  [{f.severity.value:8s}] {f.flag_type} "
                f"(conf={f.ai_confidence_score:.2f}, weighted_risk={f.weighted_risk():.2f}) "
                f"- {f.finding_id}"
            )
            lines.append(f"      Reason: {f.explanation}")

        if self.related_bidder_network:
            lines.append("")
            lines.append(f"Related bidder network: {', '.join(self.related_bidder_network)}")

        return "\n".join(lines)


class FindingRiskScorer:
    def __init__(
        self,
        green_ceiling: float = 3.0,
        yellow_ceiling: float = 6.5,
        critical_override_confidence: float = CRITICAL_OVERRIDE_CONFIDENCE,
        decay_factor: float = DECAY_FACTOR,
    ):
        self.green_ceiling = green_ceiling
        self.yellow_ceiling = yellow_ceiling
        self.critical_override_confidence = critical_override_confidence
        self.decay_factor = decay_factor

    def score_case(
        self,
        case_id: str,
        bidder_id: str,
        findings: List[VerificationFinding],
    ) -> CaseScoringResult:
        if not findings:
            # No findings raised at all -> clean case
            return CaseScoringResult(
                case_id=case_id,
                bidder_id=bidder_id,
                findings=[],
                scaled_score=0.0,
                category=Category.GREEN,
                override_triggered=False,
                dominant_finding=None,
                related_bidder_network=[],
                next_action=CATEGORY_ACTION[Category.GREEN],
            )

        ranked = sorted(findings, key=lambda f: f.weighted_risk(), reverse=True)
        dominant = ranked[0]

        raw_risk = dominant.weighted_risk()
        for rank, f in enumerate(ranked[1:], start=1):
            raw_risk += f.weighted_risk() * (self.decay_factor ** rank)

        scaled_score = round(min(10.0, raw_risk), 2)

        override_triggered = any(
            f.severity == Severity.CRITICAL
            and f.ai_confidence_score >= self.critical_override_confidence
            for f in findings
        )

        if override_triggered:
            category = Category.RED
        else:
            category = self._categorize(scaled_score)

        related_bidders = sorted(
            {bid for f in findings for bid in f.related_bidder_ids}
        )

        return CaseScoringResult(
            case_id=case_id,
            bidder_id=bidder_id,
            findings=findings,
            scaled_score=scaled_score,
            category=category,
            override_triggered=override_triggered,
            dominant_finding=dominant,
            related_bidder_network=related_bidders,
            next_action=CATEGORY_ACTION[category],
        )

    def _categorize(self, scaled_score: float) -> Category:
        if scaled_score <= self.green_ceiling:
            return Category.GREEN
        elif scaled_score <= self.yellow_ceiling:
            return Category.YELLOW
        return Category.RED


class FindingRiskDatabase:
    """
    SQLite persistence for case-level risk results and their underlying
    findings, preserving every contract field for audit purposes.
    """

    def __init__(self, db_path: str = "finding_risk_results.db"):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS case_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                bidder_id TEXT NOT NULL,
                scaled_score REAL,
                category TEXT,
                override_triggered INTEGER,
                dominant_finding_id TEXT,
                related_bidder_network TEXT,
                next_action TEXT,
                created_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS finding_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id INTEGER NOT NULL,
                finding_id TEXT,
                bidder_id TEXT,
                flag_type TEXT,
                severity TEXT,
                ai_confidence_score REAL,
                weighted_risk REAL,
                explanation TEXT,
                supporting_references TEXT,
                verification_references TEXT,
                related_bidder_ids TEXT,
                similarity_trace TEXT,
                FOREIGN KEY (result_id) REFERENCES case_results (id)
            )
            """
        )
        conn.commit()
        conn.close()

    def save_result(self, result: CaseScoringResult) -> int:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO case_results
                (case_id, bidder_id, scaled_score, category, override_triggered,
                 dominant_finding_id, related_bidder_network, next_action, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.case_id,
                result.bidder_id,
                result.scaled_score,
                result.category.value,
                int(result.override_triggered),
                result.dominant_finding.finding_id if result.dominant_finding else None,
                json.dumps(result.related_bidder_network),
                result.next_action,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        result_id = cur.lastrowid

        for f in result.findings:
            cur.execute(
                """
                INSERT INTO finding_details
                    (result_id, finding_id, bidder_id, flag_type, severity,
                     ai_confidence_score, weighted_risk, explanation,
                     supporting_references, verification_references,
                     related_bidder_ids, similarity_trace)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    f.finding_id,
                    result.bidder_id,
                    f.flag_type,
                    f.severity.value,
                    f.ai_confidence_score,
                    f.weighted_risk(),
                    f.explanation,
                    json.dumps(f.supporting_references),
                    json.dumps(f.verification_references),
                    json.dumps(f.related_bidder_ids),
                    json.dumps(f.similarity_trace) if f.similarity_trace else None,
                ),
            )

        conn.commit()
        conn.close()
        return result_id

    def get_cases_by_category(self, category: Category) -> List[Dict]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM case_results WHERE category = ? ORDER BY created_at DESC",
            (category.value,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def get_findings_for_bidder(self, bidder_id: str) -> List[Dict]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM finding_details WHERE bidder_id = ?",
            (bidder_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows


if __name__ == "__main__":
    # Example findings as they'd arrive per the verification contract
    raw_findings = [
        {
            "finding_id": "FND-001",
            "flag_type": "GSTIN mismatch",
            "severity": "MEDIUM",
            "ai_confidence_score": 0.72,
            "explanation": "GSTIN on invoice does not match GSTIN on registration certificate.",
            "supporting_references": ["doc://invoice_014.pdf", "doc://gst_cert.pdf"],
            "verification_references": ["ver://gstin-check-88213"],
            "related_bidder_ids": [],
        },
        {
            "finding_id": "FND-002",
            "flag_type": "Duplicate bidder network",
            "severity": "CRITICAL",
            "ai_confidence_score": 0.91,
            "explanation": "Bidder shares bank account details with bidder SELLER-2098, "
                           "suggesting coordinated/cartel bidding.",
            "supporting_references": ["doc://bank_details.pdf"],
            "verification_references": ["ver://cross-ref-4471"],
            "related_bidder_ids": ["SELLER-2098"],
            "similarity_trace": {"match_type": "bank_account", "similarity_score": 0.97},
        },
        {
            "finding_id": "FND-003",
            "flag_type": "OCR low confidence on turnover figure",
            "severity": "LOW",
            "ai_confidence_score": 0.4,
            "explanation": "Turnover figure extracted with low OCR confidence; may need manual re-check.",
            "supporting_references": ["doc://turnover_statement.pdf"],
            "verification_references": [],
            "related_bidder_ids": [],
        },
    ]

    findings = [VerificationFinding.from_dict(f) for f in raw_findings]

    scorer = FindingRiskScorer()
    result = scorer.score_case(
        case_id="CASE-7781",
        bidder_id="SELLER-1042",
        findings=findings,
    )

    print(result.summary())

    db = FindingRiskDatabase(db_path="finding_risk_results.db")
    result_id = db.save_result(result)
    print(f"\nSaved to database with result_id={result_id}")

    print("\nAll RED cases currently in DB:")
    for row in db.get_cases_by_category(Category.RED):
        print(f"  - {row['case_id']} (bidder {row['bidder_id']}): score {row['scaled_score']}")
