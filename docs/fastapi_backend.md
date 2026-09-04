# FastAPI backend

Start the development server from the repository root:

```powershell
$env:BOOTSTRAP_OFFICER_USERNAME = "admin"
$env:BOOTSTRAP_OFFICER_PASSWORD = "replace-with-a-random-password-of-12-or-more-characters"
$env:AUTH_COOKIE_SECURE = "false"
.\venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

The browser screening client is available at `http://127.0.0.1:8000/`. It is
served by FastAPI from `web/`, so no separate Node.js development server is
required. Camera access works on localhost or over HTTPS; browsers block it on
an insecure remote origin.

Document analysis supports Aadhaar, passports, visas, national IDs, driving
licences, and permits. The latter three use conservative labelled-field
extraction with per-field provenance and a generic validation profile; unknown
credentials fail closed. Aadhaar validation
does not require an MRZ, nationality field, or expiry date. Full Aadhaar numbers
are checked with the Verhoeff checksum and masked Aadhaar images are accepted
without a checksum claim; the browser displays only the masked form.

A checksum-supported OCR correction is never treated as issuer verification and
forces an automated `RETRY` unless it is independently confirmed. Image forensics
uses ELA, regional noise consistency, file metadata, geometry, exposure, and
contrast as risk
signals. These heuristics can identify some edits but cannot prove authenticity
or guarantee detection of every manipulation. Production Aadhaar verification
should validate issuer-signed Secure QR/offline data rather than relying on the
uploaded pixels alone.

## Cryptographically verified Aadhaar

The primary Aadhaar-card flow requires front and back images. It OCRs the front
while decoding the Secure QR on the back, verifies the QR's UIDAI
`SHA256withRSA` signature, cross-checks printed name/DOB/last-four digits,
compares the visible front photograph with the signed QR portrait, and uses the
signed portrait for live face matching. A changed front photograph produces
`AADHAAR_PHOTO_QR_MISMATCH` even when the live person correctly matches the
original signed portrait. A damaged/unreadable QR
returns a recapture error; an invalid signature is rejected; a front/QR identity
mismatch becomes a critical automated rejection.

API endpoint:

`POST /api/v1/screenings/aadhaar-card` with multipart image fields `front` and
`back`.

## Screening flow

1. `POST /api/v1/screenings` with multipart field `document`.
2. `POST /api/v1/screenings/{session_id}/face/start`.
3. Repeatedly send multipart field `frame` to
   `POST /api/v1/screenings/{session_id}/face/frame`.
4. `POST /api/v1/screenings/{session_id}/finalize`. The backend checks the
   SQLite watchlist automatically and merges any optional supplied signals.
5. Read the result with `GET /api/v1/screenings/{session_id}`.
6. Record the authorized human outcome with
   `POST /api/v1/screenings/{session_id}/disposition`.
7. Delete sensitive temporary data with
   `DELETE /api/v1/screenings/{session_id}`.

The disposition body contains `decision` (`CLEARED`, `REFERRED`, or `DENIED`),
a structured `reason_code`, and optional notes. Clearing a critical automated
reject requires the `ADMIN` supervisor role. Automated triage and human
disposition remain separate audit events.

All `/api/v1` operations require an authenticated officer session except login.
Login creates an HttpOnly, SameSite=Strict session cookie and returns a CSRF
token for state-changing requests. Stored screenings can be listed with
`GET /api/v1/screenings`, and audit events are available from
`GET /api/v1/screenings/{session_id}/audit`.

The active checkpoint is part of the server-side officer session. Change it
through `POST /api/v1/auth/active-checkpoint`; finalization ignores any
client-supplied checkpoint and stamps the crossing with this trusted value.

The frame endpoint accepts `?mirrored=true` when the browser sends an
unmirrored webcam frame but the user is following mirrored on-screen prompts.

Example finalization body:

```json
{
  "watchlist": {
    "blacklisted": false,
    "document_blacklisted": false,
    "duplicate_identity": false,
    "metadata": {}
  }
}
```

## Environment variables

- `CORS_ORIGINS`: comma-separated frontend origins.
- `MAX_UPLOAD_BYTES`: maximum document/frame upload size; default 15 MiB.
- `SESSION_TTL_SECONDS`: in-memory session retention; default 1800 seconds.
- `RUNTIME_DIRECTORY`: temporary encrypted-volume/runtime location.
- `EASYOCR_MODEL_DIRECTORY`: EasyOCR model cache location.
- `DATABASE_PATH`: SQLite database path; defaults to
  `runtime/identity_verification.db`.
- `DUPLICATE_FACE_THRESHOLD`: cosine-similarity threshold for 1:N identity
  search; default `0.50`.
- `BOOTSTRAP_OFFICER_USERNAME` and `BOOTSTRAP_OFFICER_PASSWORD`: initial officer
  login. Set both; the password must contain at least 14 characters.
- `AUTH_SESSION_TTL_SECONDS`: officer session lifetime; default 28800 seconds.
- `AUTH_COOKIE_SECURE`: keep `true` in production HTTPS. Set `false` only for a
  localhost HTTP demo.
- `APP_ENV`: `development`, `test`, or `production`.
- `ALLOWED_HOSTS`: comma-separated accepted HTTP hostnames.
- `REQUIRE_HTTPS`: must be `true` in production.
- `DATA_VOLUME_ENCRYPTED`: operator attestation that runtime data and backups
  use approved encryption at rest; production refuses to start unless true.
- `MAX_IMAGE_PIXELS`: decoded image pixel ceiling; default 25 million.
- `LOGIN_RATE_LIMIT`, `LOGIN_RATE_WINDOW_SECONDS`, `API_RATE_LIMIT`, and
  `API_RATE_WINDOW_SECONDS`: application-level abuse limits.
- `UIDAI_CERTIFICATE_DIRECTORY`: directory containing explicitly trusted UIDAI
  Secure QR certificates; defaults to `certs/`.

When `EASYOCR_MODEL_DIRECTORY` is unset, the backend reuses models already
downloaded into `.venv/easyocr_models` or `venv/easyocr_models`. Otherwise it
uses `runtime/easyocr_models`, where EasyOCR can download models on first use.
For offline deployment, pre-provision the model files and set the variable
explicitly.

RapidOCR with ONNX Runtime is the primary CPU OCR engine; EasyOCR remains a
compatibility fallback. The browser starts model warmup while the user selects a
file, oversized images are reduced to a 1600-pixel working canvas, and OCR runs
concurrently with image forensics. On the repository's dense specimen, the ONNX
engine completed OCR in about 4.7 seconds versus about 10 seconds for warmed
EasyOCR; actual latency varies with image complexity and hardware.

## SQLite persistence and watchlist

The API initializes the SQLite schema automatically on startup. It stores
screening results, final decisions, watchlist entries, and audit events. Raw
uploaded images and active face/liveness objects remain temporary and are not
stored in SQLite. Deleting a screening permanently removes its uploaded
document directory, screening row, audit events, and any face embedding
enrolled by that screening.

- `POST /api/v1/watchlist` adds an active watchlist entry.
- `GET /api/v1/watchlist` lists entries.
- `DELETE /api/v1/watchlist/{entry_id}` deactivates an entry.

Document numbers are normalized before matching. A full name plus date of birth
can also produce a match. Database matches cannot be overridden by values sent
in the finalization request.

## Duplicate-identity screening

Starting face verification extracts the document portrait embedding and compares
it with enrolled SFace embeddings. A similar face associated with a different
document number sets `duplicate_identity=true`, which produces
`POSSIBLE_MULTIPLE_IDENTITIES` in the final decision. Formatting differences in
the same document number do not create a false duplicate.

An embedding is enrolled or refreshed only after an `APPROVE` decision with
successful liveness and face matching. Raw face images are not stored in the
embedding table. Embeddings are sensitive biometric data: use encrypted storage,
strict access control, and an explicit retention policy outside a local demo.

## Cross-border identity continuity

Finalization records the checkpoint, movement (`ENTRY`, `EXIT`, or `TRANSIT`),
lane, document identity, decision, and biometric identity cluster as a border
crossing event. The continuity engine distinguishes two important cases:

- A known face using another document with consistent name and date of birth is
  shown as `CONTINUITY_CONFIRMED`, such as a legitimate passport renewal.
- A known face using another document with conflicting trusted biographics is
  shown as `IDENTITY_CONFLICT` with the conflicting fields, face similarity,
  linked documents, and prior crossing timeline.

Pass movement and lane in `border_context` when finalizing:

```json
{
  "border_context": {
    "movement": "ENTRY",
    "lane": "LANE-01"
  }
}
```

The checkpoint is taken from the authenticated officer session, never trusted
from this JSON body. The final decision contains a `continuity` evidence object.
Administrators can also read `GET /api/v1/border-crossings` or filter it with
`identity_id`.
Deleting a screening also deletes its linked border-crossing event.

The browser officer console renders `continuity.graph` as an interactive
relationship view. It links the live biometric cluster to claimed identity
profiles, presented documents, and checkpoints. Conflicting biometric/profile
links are highlighted separately from legitimate document renewal links, and
the graph rearranges into horizontal layers on desktop and vertical layers on
small screens.

The live image/session store is still in memory, so deploy one worker. Completed
screening records remain readable after restart, but an interrupted liveness
session must be restarted with a new document upload. The application enforces
roles, but approved encrypted infrastructure, centralized identity/MFA, and a
formal retention policy remain deployment responsibilities before real identity
documents are handled.

## Container deployment

Review [security_controls.md](security_controls.md) before using production
mode. The production process intentionally fails closed until HTTPS, trusted
hosts/origins, secure cookies, a non-placeholder password, and encrypted-volume
attestation are configured.

Copy `.env.example` to `.env`, replace the bootstrap password, then run:

```powershell
docker compose up --build -d
```

That local-demo configuration exposes `http://localhost:8000` and persists the
SQLite database and OCR models in the `drishti_runtime` volume. For a host with
a public DNS record, set `DRISHTI_DOMAIN`, keep `AUTH_COOKIE_SECURE=true`, and
run the HTTPS reverse-proxy configuration:

```powershell
docker compose -f compose.yaml -f compose.production.yaml up --build -d
```

HTTPS is required for remote browser camera capture. Back up the named runtime
volume, terminate TLS at Caddy or the government gateway, restrict port 8000 at
the host firewall, and provision trusted UIDAI certificates before a real pilot.
