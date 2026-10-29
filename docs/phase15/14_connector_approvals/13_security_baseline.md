# 13 — Security baseline and the CASA pre-assessment

> **Written:** 29 Oct 2026, with the wave 3 change of [10](10_code_fix_plan.md) (SH-E5, GOOG-E9) · **For:** Gmail's CASA Tier 2 assessment ([02](02_google.md) §4.D, §6); it strengthens every other review
> **Status:** the code and pipeline parts are built (§1); the pre-assessment itself (§2) is run on Azure dev by the owner's team before booking the lab.

## 1. What is in place

| Control (OWASP ASVS area) | Where | Evidence |
|---|---|---|
| HTTPS only; HSTS for a year with subdomains | Envoy Gateway's routes (`infra/k8s/charts/hb-platform/templates/httproutes.yaml`, `gateway.hsts`), the app's nginx (`frontend/nginx/security-headers.conf`) and the API (`src/common/security_headers.py`) | `curl -sI https://app.<domain>/` and `…/api/v1/health` show `Strict-Transport-Security` |
| Content Security Policy | The app: self, Google Fonts, the Google Picker, Razorpay Checkout; nothing inline (V14.4). The API: a JSON answer loads nothing and cannot be framed; its HTML pages use their own styles only. A shared file keeps its sandbox | The same `curl`; `tests/unit/test_wave3_connector_rules.py::test_every_api_answer_carries_the_security_headers` |
| No framing, no sniffing, a referrer policy | `X-Frame-Options: DENY` / `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin` on both | as above |
| Dependency scanning | CI job `security` (`.github/workflows/ci.yml`): Trivy (`aquasecurity/trivy-action`, pinned by commit to v0.36.0, Trivy 0.70.0) over the Python lock, the npm lock and the Dockerfiles. A CRITICAL with a fix fails the build, and so the deploy; HIGH ones are listed in the job's summary. Its first scan (29 Oct) found nine in `backend/poetry.lock`, all upgraded that day: Pillow 10.4.0 → 13.0.0, PyJWT 2.12.1 → 2.15.1, anyio 4.13.0 → 4.15.1, certifi → 2026.10.23, brotli → 1.2.1, brotlicffi → 1.2.1.0 | The run's summary page |
| Container scanning | Every image is scanned after it is pushed (`deploy-azure.yml`, *Scan the image*); HIGH and CRITICAL with a fix are listed per image | The deploy run's summary |
| OAuth `state` and PKCE | One-time `state` in Redis per sign-in; PKCE (S256) for Google, Microsoft and X (`connections/providers/oauth.py`) | `tests/integration/test_connections.py` (the challenge method is checked) |
| Tokens at rest | AES-256-GCM per row under the business's DEK, the DEK wrapped by its KEK in Key Vault (`connections/crypto.py`) | `test_secrets_are_sealed_per_row_rotated_and_shredded` |
| Writes to connected accounts | A person approves each, seeing exactly what goes out (SH-E4) | `test_a_write_to_a_connected_account_waits_for_a_person_and_runs_as_approved` |
| Untrusted content | Prompt-injection screening (Azure AI Content Safety Prompt Shields) and quoting (SH-E3) | the screening tests |
| Least data, least access | Retention by source (SH-E2); staff see connected content only under the business's grant (SH-E6); data-flow note [12](12_data_flow_note.md) | `tests/integration/test_wave3_data_rules.py` |
| Tenant isolation | A database per business; the isolation suite | `tests/isolation` against Azure dev |

**To confirm by the owner:** the tenant-keys vault's key type. Google asks for keys "in an HSM or equivalent": Key Vault *Premium* keys (`RSA-HSM`) meet that; *Standard* software keys may not satisfy every lab. Check with `az keyvault key show --vault-name <tenant-keys vault> --name <a tenant KEK> --query key.kty`.

## 2. The pre-assessment (before booking the lab)

Run against Azure dev, fix, run again; keep each report with the CASA questionnaire.

1. **Dynamic scan.** OWASP ZAP baseline against `https://app.azdev.hirebuddha.com` and `https://gateway.azdev.hirebuddha.com`:
   `docker run --rm -t ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -t https://app.azdev.hirebuddha.com -r app.html`
   Expected now: no missing-header findings. Look at what remains: cookies (the app keeps its token in the browser, not a cookie), information disclosure in error pages.
2. **Dependencies and images.** The CI `security` job's summary and each image's scan: no HIGH or CRITICAL with a fix. Upgrade, rebuild, re-run.
3. **TLS.** `testssl.sh` (or SSL Labs) on both hostnames: TLS 1.2 and 1.3 only, no weak ciphers (Envoy Gateway's defaults, Let's Encrypt certificates).
4. **Secrets.** No secret in an image (`trivy image --scanners secret`), in a log line, or in the repository (`gitleaks detect`).
5. **OAuth.** Redirect URIs registered exactly; a replayed `state` refused; a sign-in without PKCE refused (the integration tests above, and by hand once on dev).
6. **Access control.** The partner and tenancy suites green; the isolation suite green on dev.
7. **The questionnaire.** CASA's self-assessment (ASVS Level 1–2): answer each item with the evidence above; mark anything not met with its fix date.

## 3. Incident response (the note SH-E5 asks for)

* **Report:** `security@hirebuddha.com` (also on `/product/security`); acknowledged within one working day.
* **Triage:** the on-call engineer confirms, scopes (which businesses, which data, which providers' data), contains (rotate the KEK or the provider app's secret, revoke tokens with `service.revoke`, block the route).
* **Tell:** the affected businesses, and the authorities where the law requires (India's CERT-In within 6 hours of noticing a reportable incident; the Data Protection Board under the DPDP Act). For Google user data, Google's `security@google.com` as the Google API Services User Data Policy requires; Meta, LinkedIn, Microsoft and X through their developer portals' security contacts when their data is involved.
* **After:** a written review within 5 working days: cause, data affected, what changed so it cannot recur; kept with the CASA evidence.
