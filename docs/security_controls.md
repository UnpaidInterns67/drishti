# Drishti security controls

This is a technical baseline for a demonstration system handling sensitive
identity data. It is not a certification and must not be described as
government-production-ready without an independent security assessment,
penetration test, privacy review, threat model, and authorization from the data
owner.

## Checklist coverage

| Check | Drishti control |
|---|---|
| Hide API keys | No paid/external API key is required. Runtime secrets belong in `.env`, which is ignored. CI rejects committed environment files and high-confidence key formats. |
| Check environment variables | Production startup fails closed when HTTPS, secure cookies, trusted hosts, HTTPS CORS origins, encrypted-volume attestation, or password rules are unsafe. |
| Check keys in Git | `scripts/security_check.py` runs in the security CI workflow. Rotate any secret that was ever committed; deleting it from the latest revision is insufficient. |
| Protect admin routes | Historical screenings, crossing records, audit trails, watchlist management, deletion, and security-event access require the `ADMIN` role. |
| Authentication | Passwords are salted and hashed with scrypt. Server-side sessions store only token hashes and are revoked when a new session is issued. |
| User permissions | Roles are checked server-side. Officers can perform live screening and change their active post; administrators additionally control persisted records and security functions. |
| Input validation | Pydantic forbids unexpected fields, constrains identifiers, rejects control characters, and limits text and metadata sizes. |
| XSS protection | Dynamic UI values are escaped or assigned with `textContent`; CSP blocks inline scripts, plugins, framing, and unapproved network origins. |
| SQL injection | SQLite values are parameterized. The few dynamic query fragments are generated only from server-owned placeholders. |
| Database rules | Foreign keys, uniqueness, role/movement checks, active-state checks, indexes, transactions, and query bounds are enforced. |
| Rate limiting | Login and API sliding-window limits return `429` with `Retry-After`. The production gateway should also apply distributed limits. |
| Spend cap | Not applicable: the application does not call a metered AI/API service. Configure budget alarms before adding one. |
| Secure uploads | Exact MIME allowlist, format-signature verification, per-file byte limit, decoded pixel limit, malformed-image rejection, and server-generated filenames. SVG and active formats are rejected. |
| CSRF | Every authenticated state-changing API call requires a session-bound CSRF token. Cookies use `SameSite=Strict`. |
| CORS | Explicit origin allowlist with credentials; production permits HTTPS origins only and rejects wildcard hosts. |
| HTTPS | Production refuses to start unless HTTPS is required. Caddy terminates TLS, and the app redirects insecure requests. |
| Security headers | CSP, HSTS, frame denial, no-sniff, restrictive permissions policy, referrer policy, cross-origin isolation policy, and no-store on sensitive responses. |
| Secure cookies | Production session cookie uses the `__Host-` prefix plus Secure, HttpOnly, SameSite=Strict, root path, and a bounded lifetime. |
| Debug disabled | Debug is always disabled. OpenAPI, Swagger, and ReDoc endpoints are removed in production. Client errors do not expose exception strings. |
| Production settings | Non-root/read-only container, dropped Linux capabilities, PID limit, internal backend network, persistent runtime volume, health check, single worker, TLS proxy, and startup validation. |

## Government-data deployment requirements

Before a pilot, the system owner must additionally provide controls that cannot
be truthfully implemented inside this repository alone:

- Encrypt the host disk or managed volume and set `DATA_VOLUME_ENCRYPTED=true`
  only after verifying it. Encrypt backups separately and test restoration.
- Replace the bootstrap account with the approved government identity provider,
  MFA, account lifecycle management, and centralized revocation.
- Put Caddy behind the approved government gateway/WAF, restrict the origin
  firewall, centralize rate limiting, and send security events to an immutable
  SIEM with alerting.
- Define data minimization, consent/legal basis, purpose limitation, retention,
  deletion, incident response, breach notification, and biometric-access rules.
- Run SAST, dependency and container scanning, DAST, penetration testing, and an
  architecture/threat-model review before real documents are processed.
- Never use the demo `admin` password outside a local demonstration. Rotate it
  immediately if the database or password has been shared.

## Production configuration

At minimum, configure:

```dotenv
APP_ENV=production
AUTH_COOKIE_SECURE=true
REQUIRE_HTTPS=true
DATA_VOLUME_ENCRYPTED=true
ALLOWED_HOSTS=drishti.example.gov.in
CORS_ORIGINS=https://drishti.example.gov.in
BOOTSTRAP_OFFICER_USERNAME=admin
BOOTSTRAP_OFFICER_PASSWORD=<unique random secret of 14+ characters>
```

Do not set the encrypted-volume flag merely to pass validation. It is an
operator attestation because application code cannot verify cloud or host disk
encryption.
