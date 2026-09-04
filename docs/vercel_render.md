# Vercel frontend / Render backend

Deployment source: https://github.com/UnpaidInterns67/drishti, branch `main`.

## Vercel

- Use the Hobby plan where eligible. Import the existing repository; do not create a clone.
- Root directory: `web`. Framework preset: Other.
- `vercel.ts` builds only the three public frontend files and proxies `/api/*` and `/health` to Render.
- Set `BACKEND_ORIGIN` to the actual Render HTTPS origin, without a path. Configuration intentionally fails until this is supplied.
- Never put the officer password or other backend secrets in Vercel.
- The same-origin proxy preserves the application's host-only, Secure, SameSite=Strict cookies and CSRF flow. Verify login and logout through the deployed frontend.

## Render

- Public Git repository: the URL above. Docker runtime, root directory blank, branch `main`.
- Free compute only, no disk or paid add-ons. Container port 8000, one worker, health path `/health`.
- Supply `BOOTSTRAP_OFFICER_USERNAME` and a unique `BOOTSTRAP_OFFICER_PASSWORD` as backend secrets.
- Configure exact `ALLOWED_HOSTS`, HTTPS `CORS_ORIGINS`, `AUTH_COOKIE_SECURE=true`, and `REQUIRE_HTTPS=true`.
- Production startup also requires verified encrypted storage. Do not set `DATA_VOLUME_ENCRYPTED=true` without confirming that it covers the actual runtime filesystem. Free ephemeral storage is not a persistent disk.
- Do not bypass the production startup checks just to obtain a green deployment.

## Free-tier limitations and release checks

Free Render compute has limited memory and CPU, sleeps when idle, and loses SQLite data, uploads, and downloaded model caches on restart/redeploy. This is a synthetic-data demonstration target, not an operational identity screening deployment.

Before claiming success, verify health, authenticated login, CSRF-protected upload, OCR inference, camera permission and face processing, logout, and memory usage under the free limit. Keep a local presentation backup. A successful homepage alone does not establish a working AI backend.
