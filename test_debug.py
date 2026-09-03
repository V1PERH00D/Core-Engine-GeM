from ai_verification.cross_bidder.detector import detect_cross_bidder_anomalies, _candidate_blocking, _byte_hash_match, _normalized_hash_match, _lexical_dice, _make_empty_trace
from ai_verification.cross_bidder.document_artifact_store import InMemoryDocumentArtifactStore, DocumentMeta
from datetime import date

raw_text1 = 'the quick brown fox'
raw_text2 = 'the quick brown foxx'
file_hash1 = 'sha256:' + 'b' * 62
file_hash2 = 'sha256:' + 'c' * 62
metadata = {
    'doc1': {
        'document_type': 'PDF',
        'evidence_id': 'ev1',
        'ocr_confidence': 0.95,
        'document_type_confidence': 0.9,
        'issuer': 'Test Issuer',
        'authorization_number': 'AUTH123',
        'issue_date': date(2024, 1, 1),
        'valid_until': date(2025, 1, 1),
        'bidder_name': 'Bidder A',
        'territory': 'Territory X',
    },
    'doc2': {
        'document_type': 'PDF',
        'evidence_id': 'ev2',
        'ocr_confidence': 0.93,
        'document_type_confidence': 0.9,
        'issuer': 'Test Issuer',
        'authorization_number': 'AUTH124',
        'issue_date': date(2024, 1, 2),
        'valid_until': date(2025, 1, 2),
        'bidder_name': 'Bidder B',
        'territory': 'Territory X',
    }
}
artifact_store = InMemoryDocumentArtifactStore(
    raw_texts={'doc1': raw_text1, 'doc2': raw_text2},
    file_hashes={'doc1': file_hash1, 'doc2': file_hash2},
    metadata={k: DocumentMeta(**v) for k, v in metadata.items()},
)

# Debug: check metadata
meta1 = artifact_store.get_metadata('doc1')
meta2 = artifact_store.get_metadata('doc2')
print("Meta doc1:", meta1)
print("Meta doc2:", meta2)

# Directly trace through the function logic
print("--- Debugging detect_cross_bidder_anomalies ---")

# Byte hash comparison
byte_hash_result = _byte_hash_match(meta1, meta2, artifact_store, 'doc1', 'doc2')
print("Byte hash result:", byte_hash_result)

# Normalized hash comparison
norm_hash_result = _normalized_hash_match(meta1, meta2, artifact_store, 'doc1', 'doc2')
print("Normalized hash result:", norm_hash_result)

# Lexical similarity
dice_score = _lexical_dice(meta1, meta2, artifact_store, 'doc1', 'doc2')
print("Dice score:", dice_score)

# Check conditions
print("byte_hash_result == 1.0:", byte_hash_result == 1.0)
print("norm_hash_result == 1.0:", norm_hash_result == 1.0)
print("dice_score is not None and dice_score >= 0.80:", dice_score is not None and dice_score >= 0.80)

# Check what _make_empty_trace returns
empty_trace = _make_empty_trace('doc1', 'doc2', 'bidder-1', 'bidder-2')
print("Empty trace:", empty_trace)

# Now call the actual function
findings, trace = detect_cross_bidder_anomalies('bidder-1', 'bidder-2', 'doc1', 'doc2', artifact_store)
print('Findings:', findings)
print('Trace:', trace)
if findings:
    print('Finding:', findings[0])
    print('Flag:', findings[0].flag_id)
    print('Confidence:', findings[0].confidence)