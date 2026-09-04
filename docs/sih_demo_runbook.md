# SIH 2026 demo runbook

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
