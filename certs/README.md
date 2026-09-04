# UIDAI trust certificates

`uidai_12_06_18_cer.cer` and `uidai_prod_cdup.cer` are the legacy Secure QR
verification certificates that UIDAI still publishes in the Secure QR section
of its current Data and Downloads page. Their certificate-validity dates have
elapsed, but they remain pinned trust material for signatures created with
those keys; the application does not use them for TLS or new signatures.

- Direct downloads:
  - https://backend.uidai.gov.in/get/files/media/document/2026-07/uidai_12_06_18_cer.cer
  - https://backend.uidai.gov.in/get/files/media/document/2026-07/uidai_prod_cdup.cer
- Certificate SHA-256 fingerprints:
  - `49E298532243CE28E2633A7E4F403D9CA78CBFDA8B3BBDE70324837273BA4D31`
  - `FCF31A3F89211615EBD5D449AC33D8D381F654D2E2D15037D5CC8D4AEB72F836`
- Downloaded-file SHA-256 hashes:
  - `3E6A1503F302A7C33B182DD20E0A6853EEF77BBB24ACC98C91CF16F678D8A977`
  - `D69BC1630B3DD70C262AD293EEA5ECFBFF99F3D757C98DAA2A53B81925A695FE`

`uidai_secure_qr_ds_05.pem` validates the newer `V3` Secure QR payloads. UIDAI's
public certificate page still omits this rotation, so the key is pinned from
version 4.4 (version code 57) of UIDAI's official Google Play package
`in.net.uidai.qrcodescanner`. The package was fetched directly from Google Play;
UIDAI describes that package as its approved QR verifier and the release notes
identify a certificate update.

- Certificate subject: `CN=DS UNIQUE IDENTIFICATION AUTHORITY OF INDIA 05`
- Certificate SHA-256 fingerprint: `E0F0F869D32EFC7E80FAE2223717A56DCF8B616F820B542A49E5BD5ABF1C0F7D`
- Source package SHA-256: `FA9214612F08A156F72AA39D6EE0ED500C54A15A489D6AF46D2F7BB48F1997F1`
- Google Play listing: https://play.google.com/store/apps/details?id=in.net.uidai.qrcodescanner

The certificate-validity window is historical. It remains pinned solely for
checking QR signatures made with that key; it is never used for TLS or for
creating new signatures. Certificate rotation must be tested against UIDAI's
current scanner before deployment.

Certificate rotation is an operational security task. Download replacements
only from UIDAI, verify their subject, validity, and published fingerprint, then
place the required current/legacy certificates in this directory. Uploaded XML
certificates are never trusted.
