# AI integration contract

The backend can call the AI layer without invoking its command-line scripts.

## Document screening

```python
from ai.document_analysis.analyzer import build_document_record

result = build_document_record(
    ocr_items,
    image_path="path/to/uploaded-document.jpg",
)
```

Each OCR item must contain `text` and may contain a four-point `bbox`. Supplying
`image_path` enables ELA, noise, metadata, and capture-quality analysis. The
result contains `classification`, `documents`, per-check validation evidence,
cross-validation, forensics, and document risk.

## Face verification

```python
from ai.face_verification import IdentityVerifier

verifier = IdentityVerifier()
start = verifier.start_session(document_image)
frame_result = verifier.process_frame(frame)
verifier.close_session()
```

Create one verifier per active capture session and always close it.

## Duplicate-identity screening

```python
from ai.face_verification import find_duplicate_identities

duplicate_result = find_duplicate_identities(
    query_embedding,
    enrolled_records,
    document_number=current_document_number,
    full_name=current_name,
    date_of_birth=current_date_of_birth,
)
```

The backend owns embedding storage. Each enrolled row should expose `embedding`,
`identity_id`, `document_number`, `full_name`, and `date_of_birth` to this
function. Different document numbers are expected when one person holds Aadhaar,
a passport, and other credentials. The check raises a duplicate only for a
biometric match with conflicting identity attributes; matching biographics or a
masked Aadhaar suffix are classified as the same identity. The SQLite implementation
stores float32 vectors as BLOBs and never exposes them through the API. Production
deployments must provide encryption at rest and restrict database access because
face embeddings are sensitive biometric data.

## Final decision

```python
from ai.verification_engine import combine_verification

decision = combine_verification(
    document_result,
    face_result,
    watchlist_result={
        "blacklisted": False,
        "duplicate_identity": duplicate_result["duplicate_identity"],
    },
)
```

Stable response fields are `verified`, `decision`, `manual_review`, `retry_required`,
`risk_score`, `risk_level`, `checks`, `reasons`, and `evidence`. Possible
decisions are `APPROVE`, `RETRY`, and `REJECT`. `RETRY` is an automated
recapture path and does not create an operator review queue.
