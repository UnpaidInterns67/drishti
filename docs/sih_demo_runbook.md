# SIH 2026 demo runbook

## One-click synthetic walkthroughs

Start the normal authenticated local server with `DEMO_ENABLED=true`:

```powershell
$env:DEMO_ENABLED = "true"
$env:AUTH_COOKIE_SECURE = "false" # localhost HTTP only
.\venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Use your configured officer credentials. After signing in, the **SIH synthetic
walkthroughs** panel offers four buttons; each opens the existing evidence,
triage, identity graph and officer-disposition panels in one click.

| Button | Expected walkthrough |
|---|---|
| Clean clearance | APPROVE, low risk, machine consistency only; click Clear traveller and open the temporary synthetic audit. |
| Document inconsistency | RETRY; visible DEMO0002 conflicts with MRZ DEMO0001. Inspect the conflicting-source evidence and refer for examination. |
| Poor capture / recapture | RETRY with IMAGE_RECAPTURE_REQUIRED, without a tampering accusation. Click Simulate improved document recapture to reach APPROVE in the same run. |
| Same-face conflicting identity | REJECT triage, IDENTITY_CONFLICT graph and fictional previous crossing; supervisor action focuses on name and date of birth. Refer to secondary. |

All observations are deterministic fixtures: fabricated OCR text, simulated
capture and liveness, and three-dimensional toy vectors (not real biometric
embeddings). Document parsing, duplicate comparison, continuity, triage and
secondary-inspection policy execute normally. These walkthroughs do not test
camera, OCR-model or face-model accuracy. No genuine identity document, portrait,
issuer signature, chip check or government lookup is supplied or claimed.
`UTO`, `DEMO` identifiers and explicitly fictional names label the specimens.
The synthetic expiry is fixed at 2049-12-31; update fixtures before that date.

Demo API routes live under `/api/v1/demo`: `GET /scenarios`,
`POST /scenarios/{id}`, `POST /runs/{id}/recapture`,
`POST /runs/{id}/disposition`, and `GET /runs/{id}/audit`.
They retain ordinary authentication and CSRF protection. Runs are owner-scoped,
kept only in process memory for 30 minutes, and capped at 100. Use one server
worker for the walkthrough. A restart or eviction removes the rehearsal;
start the scenario again if a run expires. Audit entries are temporary synthetic
events, not the persistent operational audit.

Fixtures never access operational watchlists, enroll a face, or write screenings
or crossings to the database. Each button starts an independent run; scenario
order does not matter. Exit synthetic demo returns to normal intake. Demo mode
is disabled by default and cannot be enabled when `APP_ENV=production`.
Do not enter real personal information in rehearsal notes.

Verification: `python -m pytest tests/test_demo.py tests/test_frontend.py -q`.
The integration tests cover all four results, recapture, disposition, audit,
operational isolation, owner access, CSRF, authentication and production gating.

The manual camera walkthrough below is an optional separate demonstration.

## The one-sentence pitch

Most systems ask whether two faces match. Drishti asks whether an identity
remains trustworthy across the document, live biometric, watchlist, and border
history—and explains the safest next officer action.

## Recommended five-minute flow

### 1. Establish the operational problem (30 seconds)

Explain that a rushed officer must currently interpret document security,
biometrics, databases, and travel history separately. Drishti joins those
signals without removing human authority.

### 2. Clean credential and live traveller (75 seconds)

1. Sign in as the officer and show the authenticated checkpoint.
2. Upload the prepared clean document.
3. Point out extracted fields, capture quality, validation percentage, and the
   displayed authenticity assurance level.
4. Complete the blink and randomized head-turn challenge.
5. Show the explainable low-risk recommendation and record `CLEARED` as the
   human disposition.

### 3. Tampered or inconsistent document (60 seconds)

Use the prepared Aadhaar specimen with a replaced front photograph, or the
passport specimen whose visible document number differs from its MRZ. Show that
Drishti compares the visible photo with the signed QR portrait independently of
the live-person comparison and identifies the exact conflicting source.
Emphasize that the result is an alert for inspection, not a claim of criminal
guilt.

### 4. Same face, conflicting identity (75 seconds)

Run the prepared returning-person scenario with conflicting name or date of
birth. Show the identity relationship graph, previous checkpoint timeline,
duplicate biometric link, and supervisor-routing instruction.

### 5. Close on operational trust (40 seconds)

Open the audit trail and show the officer disposition. Then show the
authenticity limitation: MRZ check digits are not presented as passport issuer
authentication, and NFC/database integrations are explicitly identified as
not performed when unavailable.

## Demo preparation checklist

- Start the server and warm models at least 15 minutes before presenting.
- Use the same laptop, browser, and camera that will be used on stage.
- Keep one clean document, one deliberately inconsistent specimen, and one
  identity-continuity scenario ready locally.
- Verify camera permission and lighting at the venue.
- Keep the browser at 100% zoom and close bandwidth-heavy applications.
- Run `.\venv\Scripts\python.exe -m pytest -q` before freezing the demo build.
- Record a short backup video of the complete workflow.
- Never use a real watchlist claim or real traveller data in the public demo.

## Questions judges are likely to ask

**Does ELA prove a document is fake?** No. It is one explainable forensic risk
signal combined with MRZ, field, issuer, biometric, and history evidence.

**Can it validate an e-passport?** It validates the visible zone and MRZ today.
Chip authentication requires NFC reader hardware and a trusted certificate
gateway; the assurance panel shows when that check was not performed.

**What happens if the photo is poor?** Capture quality is evaluated separately
from tampering. The officer receives recapture guidance rather than a fraud
accusation.

**Does AI make the border decision?** No. Drishti makes an explainable triage
recommendation. An authenticated officer records the statutory disposition,
and supervisor authority is required to clear a critical automated alert.

**How do you handle multiple identities?** Approved biometric embeddings can
link renewed credentials to one identity cluster. A strong face match with
conflicting trusted biographics is escalated and visualized against prior
crossings.

## Do not claim

- Live INTERPOL, immigration, or passport-issuer access without an authorized
  connection.
- Passport-chip verification without compatible NFC hardware.
- That metadata or image forensics alone prove forgery.
- Perfect face, OCR, liveness, or tampering accuracy.
- That an automated `REJECT` label is the final legal border decision.
