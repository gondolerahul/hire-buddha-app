import os
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values shipped in code, .env.example or docker-compose that must never guard anything.
PLACEHOLDER_SECRETS = frozenset({
    "change-me-in-production", "changeme", "change-me", "secret", "dev_secret_key_change_in_production",
    "your-default-dev-key-must-be-32-bytes",   # ENCRYPTION_MASTER_KEY's old default (AU-24)
})

# The stored-credential key's minimum length; generate one with
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
MIN_ENCRYPTION_KEY_LENGTH = 32

class Settings(BaseSettings):
    # The control database (Phase 14 WS2, tech spec §5.1, §16): identity,
    # companies, billing, the tenant directory — today, every table.
    # DATABASE_URL is its old name, kept as an alias for one release: set
    # either; both read the same value.
    CONTROL_DATABASE_URL: str = ""
    DATABASE_URL: str = ""
    REDIS_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Encrypts every stored third-party credential (common/security.py). No
    # default: one in the repository encrypted everything a deployment that
    # forgot it stored (AU-24). A placeholder or a short value refuses to load.
    ENCRYPTION_MASTER_KEY: str

    @field_validator("ENCRYPTION_MASTER_KEY")
    @classmethod
    def _real_encryption_key(cls, value: str) -> str:
        if value.strip().lower() in PLACEHOLDER_SECRETS or len(value) < MIN_ENCRYPTION_KEY_LENGTH:
            raise ValueError(
                f"ENCRYPTION_MASTER_KEY must be a random value of at least "
                f"{MIN_ENCRYPTION_KEY_LENGTH} characters, not a placeholder. Generate one with "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
        return value

    # ── Public address telephony reaches this API on ──────────────────────
    # TwiML <Stream> URLs, Tata's wss_url and campaign callbacks are built from
    # these (voice/public_urls.py). The default is this API on a local stack;
    # production sets the public hostname and "wss", and the HTTP callbacks
    # follow the protocol (https for wss). SA-01: the default used to be the
    # retired voice service on :8002.
    STREAMING_HOST: str = "localhost:8000"
    STREAMING_PROTOCOL: str = "ws"

    # ── HTTP edge — one list, one limit (the gateway on :8001 is merged in) ─
    CORS_ORIGINS: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "http://34.100.230.121:3000,"
        "https://dev.hirebuddha.com,"
        "https://app.hirebuddha.com,"
        "https://gateway.hirebuddha.com"
    )
    # Per client IP, on every REST route except the inbound webhook and
    # internal-event endpoints. Counted in Redis; in memory if Redis is down.
    RATE_LIMIT: str = "200/minute"
    # GW-02. Signed deliveries per webhook endpoint (one company, one source);
    # a provider's IPs are shared by every tenant, so not per IP.
    WEBHOOK_RATE_LIMIT: str = "300/minute"
    # Live-socket handshakes (/stream/audio, /stream/video, /mobile/ws) per
    # client IP. Telephony media streams are gated by their call instead.
    WS_HANDSHAKE_RATE_LIMIT: str = "30/minute"
    # Live AI sessions (calls, browser audio, video) a company may hold at once.
    LIVE_SESSIONS_PER_COMPANY: int = 20

    # ── Account emails (AU-06, AU-08) ─────────────────────────────────────
    # Where verification and password-reset links point: the SPA's origin.
    FRONTEND_URL: str = "http://localhost:3000"
    # Local development only: when an account email cannot be sent (no SMTP
    # integration), write its link to the API log instead. Never in production —
    # the links are credentials.
    EMAIL_LINKS_IN_LOG: bool = False

    # ── Webhook / internal-event / media-stream edge ──────────────────────
    # Shared secret for POST /internal/event (X-Internal-Token). Empty or a
    # known placeholder disables the endpoint (503) rather than guarding it
    # with a secret everyone knows (SA-20).
    INTERNAL_TOKEN: str = ""
    VIDEO_STREAMING_ENABLED: bool = True
    # STUN/TURN servers for WebRTC ICE negotiation (comma-separated)
    STUN_SERVERS: str = "stun:stun.l.google.com:19302"
    TURN_SERVER_URL: str = ""
    TURN_USERNAME: str = ""
    TURN_CREDENTIAL: str = ""

    # ── Worker health (SA-I4) ─────────────────────────────────────────────
    # Each arq worker beats this often; one silent for three beats is dead.
    WORKER_HEARTBEAT_SECONDS: int = 10
    # A due job waiting longer than this makes /api/v1/health "degraded".
    WORKER_BACKLOG_ALERT_SECONDS: int = 600
    # Child runs have their own queue and worker (SA-07); this many run at
    # once across all parents, and the rest wait in the queue.
    CHILD_WORKER_MAX_JOBS: int = 10
    # Each worker serves Prometheus /metrics on its own port (IN-20); 0 = off.
    # Loopback by default: a Prometheus that scrapes from a container on Linux
    # needs an address it can reach, and the host's firewall in front (IN-08).
    WORKER_METRICS_PORT: int = 9101
    CHILD_WORKER_METRICS_PORT: int = 9102
    EVENT_WORKER_METRICS_PORT: int = 9103
    PROVISIONER_METRICS_PORT: int = 9105
    SCHEDULER_METRICS_PORT: int = 9104
    WORKER_METRICS_ADDR: str = "127.0.0.1"
    # A parent suspended on its children (AK-03): when every child is done but
    # its resume never arrived, the sweeper re-enqueues the resume after the
    # grace; a parent still waiting after the timeout is failed and settled.
    WAITING_RESUME_GRACE_SECONDS: int = 120
    # Top-level runs a company may start in any 60 seconds (GH-03, HD17);
    # 0 turns the quota off. Refuses when Redis is unreachable.
    RUNS_STARTED_PER_MINUTE: int = 60
    # A busy or unanswered campaign call is dialed again after this many
    # seconds, doubled for each try (VT-10).
    CAMPAIGN_RETRY_BACKOFF_SECONDS: int = 600
    # Every LLM provider call (one per generate, one per ReAct turn) gets this
    # timeout and up to this many attempts on 408/429/5xx/timeouts, with
    # exponential backoff and jitter (LP-03, ai/llm/retry.py).
    LLM_CALL_TIMEOUT_SECONDS: float = 300.0
    LLM_CALL_MAX_ATTEMPTS: int = 3
    LLM_RETRY_BASE_SECONDS: float = 1.0
    LLM_RETRY_MAX_DELAY_SECONDS: float = 30.0
    WAITING_ON_CHILDREN_TIMEOUT_SECONDS: int = 3600

    # Phase 12 `02` S4 — per-tenant container sandbox. ON by default (TL-01,
    # D29): model-written code runs in the company's container, never as the
    # backend's OS user. A host without Docker or the hb-sandbox image refuses
    # sandbox calls with a message naming this setting; a development machine
    # opts out in .env (SANDBOX_CONTAINER_RUNTIME_ENABLED=false).
    SANDBOX_CONTAINER_RUNTIME_ENABLED: bool = True
    SANDBOX_IMAGE: str = "hb-sandbox:local"
    SANDBOX_NETWORK: str = "none"
    SANDBOX_MEMORY: str = "1g"
    SANDBOX_CPUS: str = "1.0"
    SANDBOX_PIDS_LIMIT: int = 256
    SANDBOX_IDLE_PAUSE_SECONDS: int = 900
    SANDBOX_REAP_SECONDS: int = 86400
    # Root of the per-tenant workspaces (<root>/<company_id>). Empty means
    # <system temp>/sandbox — node-local and lost on reboot (TL-16); a durable
    # deployment points it at a mounted volume. One definition, read by every
    # sandbox path (TL-29): src/ai/tools/sandbox/workspace.py.
    SANDBOX_WORKSPACE_ROOT: str = ""
    # S6 cost attribution: sandbox runtime time is metered against this SKU
    # (IntegrationRegistry.service_sku, owned by the APP company; cost_unit
    # "second"). Seed it with scripts/seed_sandbox_sku.py.
    SANDBOX_COST_SKU: str = "sandbox-runtime"
    # The LinkedIn API version every LinkedIn call sends (TL-48). LinkedIn
    # retires a version about a year after release: whoever touches the
    # LinkedIn integration owns this value; review it every six months
    # (next: 2027-04). It was "202401", hardcoded twelve times.
    LINKEDIN_API_VERSION: str = "202509"
    # S5 persistent browser: when enabled, headless_browser uses a persistent
    # Chromium profile under the tenant workspace so cookies/logins survive across
    # calls. OFF by default (ephemeral context = today's behavior).
    SANDBOX_PERSISTENT_BROWSER_ENABLED: bool = False
    # Egress proxy (Phase 12 `02`/`06`, TL-15): a sandbox call whose network
    # policy is ``allowlist`` (a synthesized tool that declares ALLOWLIST) runs
    # in a container on an --internal docker network (no direct internet) whose
    # only route out is a dual-homed tinyproxy enforcing SANDBOX_EGRESS_ALLOWLIST.
    # Every other call runs --network none. The policy is the call's, so there
    # is no master switch (the old SANDBOX_EGRESS_PROXY_ENABLED had no reader).
    SANDBOX_EGRESS_IMAGE: str = "hb-egress-proxy:local"
    SANDBOX_EGRESS_NETWORK: str = "hb-egress-internal"
    SANDBOX_EGRESS_UPLINK_NETWORK: str = "hb-egress-uplink"
    SANDBOX_EGRESS_PROXY_PORT: int = 8888
    # Comma-separated host allow-list the proxy permits (suffix match). Default
    # is the Google API surface the tools already depend on.
    SANDBOX_EGRESS_ALLOWLIST: str = "googleapis.com,google.com"

    # ── Voice call guardrails (Kanakia-Leads-01 fixes) ────────────────────
    # Voicemail detection: disconnect instead of pitching to a mailbox.
    VOICEMAIL_DETECTION_ENABLED: bool = True
    # Outbound call with no lead speech (neither transcript nor audio energy)
    # for this long after the agent's first audio → treated as an answering
    # machine. Must comfortably exceed a polite listen-through of the intro.
    VOICEMAIL_NO_SPEECH_SECONDS: int = 25
    # Voicemail greeting phrases are only scanned during this window from
    # pipeline start; later mentions ("just leave me a message on WhatsApp")
    # are normal conversation.
    VOICEMAIL_PHRASE_WINDOW_SECONDS: int = 30
    # Activity watchdog: no first agent audio within this window of the
    # greeting trigger → pipeline stall, call is torn down as failed.
    VOICE_PIPELINE_STALL_SECONDS: int = 10
    # Both sides idle (no agent audio sent AND no lead speech) for this long
    # → wind-down prompt, then disconnect.
    VOICE_SILENCE_DISCONNECT_SECONDS: int = 15
    # No silence enforcement during the first N seconds of the pipeline
    # (covers setup + greeting latency).
    VOICE_SILENCE_GRACE_SECONDS: int = 20
    # Agent produced no audio for this long after the lead's turn ended →
    # nudge the model; hard-disconnect at 2x only if the flag below is on
    # (tool calls legitimately exceed this window).
    VOICE_AGENT_STALL_SECONDS: int = 10
    VOICE_AGENT_STALL_DISCONNECT: bool = False
    # While Gemini reports the lead mid-utterance (voice_activity START with no
    # END yet) the agent is listening, not stalled: the "lead keeps talking,
    # agent silent" nudge holds off for up to this long. A lead answering at
    # length got told-off nudges ("reply now") mid-sentence; past the cap the
    # nudge fires anyway, for an utterance the model never closes.
    VOICE_LEAD_TURN_MAX_SECONDS: int = 25
    # RMS threshold on 16-bit PCM inbound audio above which the lead counts
    # as speaking (μ-law frames flow continuously even in silence).
    VOICE_VAD_RMS_THRESHOLD: int = 300
    # Echo suppression: while agent audio is playing at the provider, inbound
    # frames quieter than this are NOT forwarded to the model. PSTN echo of
    # the agent's own voice (attenuated, typically rms<600) was triggering
    # Gemini's barge-in and gibberish transcripts; real interjections are
    # much louder. 0 disables the gate.
    VOICE_ECHO_SUPPRESS_RMS: int = 600
    # Noise gate for mobile-dialer calls: inbound frames quieter than this
    # reach the model as true silence. The line's hiss between a lead's words
    # (rms 5-80) kept Gemini's turn detection from seeing the pause, so
    # "hello ... hello ... hello" merged into one turn nobody answered. The
    # gate stays open for VOICE_NOISE_GATE_HANGOVER_FRAMES (20 ms each) after
    # the last loud frame so the tails of words are not clipped. 0 disables.
    VOICE_NOISE_GATE_RMS: int = 40
    VOICE_NOISE_GATE_HANGOVER_FRAMES: int = 10
    # An interruption only flushes the provider's playback buffer when
    # inbound speech at least this loud was heard in the last ~1.5s —
    # otherwise the "interruption" was echo/noise and wiping the buffer cuts
    # the agent off mid-sentence.
    VOICE_BARGE_IN_RMS_THRESHOLD: int = 1000
    # Agent context cache TTL (seconds); 0 disables. Agent edits take up to
    # this long to reach new calls.
    VOICE_AGENT_CACHE_TTL_SECONDS: int = 300
    # Smartflo login-JWT cache TTL for account APIs (e.g. /v1/call/hangup).
    TATA_AUTH_TOKEN_TTL_SECONDS: int = 43200
    # Country code prepended to 10-digit campaign contact numbers that lack
    # one (Tata rejects non-E.164 numbers with HTTP 422 "Invalid details").
    DEFAULT_PHONE_COUNTRY_CODE: str = "91"
    # Key Smartflo's dynamic endpoint expects in our {"<key>": true, "wss_url"}
    # reply. Historically "sucess"; Smartflo docs say "success". Verify, then flip.
    TATA_STREAM_SUCCESS_KEY: str = "sucess"

    # ── Mobile dialer (docs/mobile-dialer-app) ────────────────────────────
    # A call attempt the app registered but whose AI leg never arrived.
    MOBILE_ATTEMPT_TTL_SECONDS: int = 120
    # After the AI-leg stream starts, wait this long for CLI/DTMF binding
    # before starting the agent without lead context.
    MOBILE_IDENT_TIMEOUT_SECONDS: int = 10
    # A CLI-bound session still waits this long for the DTMF token that
    # confirms (or corrects) the binding before loading the agent.
    MOBILE_DTMF_CONFIRM_WAIT_SECONDS: int = 4
    # Max wait for the app's 'merged' signal after the AI is ready.
    MOBILE_MERGE_WAIT_SECONDS: int = 60
    # Accept a lone '#' DTMF as the merged signal when mobile data is poor.
    MOBILE_DTMF_MERGE_FALLBACK: bool = True
    MOBILE_LEASE_SECONDS: int = 300
    MOBILE_VERIFICATION_TTL_SECONDS: int = 300
    MOBILE_VERIFICATION_MAX_CALL_SECONDS: int = 20
    MOBILE_RECONCILE_WINDOW_SECONDS: int = 15
    # Guardrails for reps calling from personal SIMs (TRAI TCCCPR, docs 08 §1.1).
    MOBILE_CALLING_HOURS_START: str = "09:30"   # IST, inclusive
    MOBILE_CALLING_HOURS_END: str = "19:30"     # IST, exclusive
    MOBILE_CALLING_HOURS_ENFORCED: bool = True
    MOBILE_REP_DAILY_ATTEMPT_CAP: int = 150
    # Firebase service-account JSON for FCM fallback pushes; empty disables FCM.
    MOBILE_FCM_SERVICE_ACCOUNT_FILE: str = ""
    # Latest Android build offered for in-app update (private distribution).
    MOBILE_APP_LATEST_VERSION_CODE: int = 1
    MOBILE_APP_LATEST_VERSION_NAME: str = "1.0.0"
    MOBILE_APP_MIN_SUPPORTED_VERSION_CODE: int = 1
    MOBILE_APP_DOWNLOAD_URL: str = ""

    # ── Phase 14: cloud-neutral platform adapters (tech spec §16, §19) ────
    # local | azure | onprem — the default adapter of every capability in
    # src/common/platform; each *_BACKEND setting below overrides one.
    PLATFORM_PROFILE: str = "local"
    # Files (§12.1): local_disk | azure_blob. Empty = the profile's default.
    STORAGE_BACKEND: str = ""
    # local_disk root; empty = backend/artifact.
    STORAGE_LOCAL_ROOT: str = ""
    # azure_blob: the account's blob endpoint, reached with the pod's workload
    # identity (no keys). A connection string is for Azurite and tests only.
    AZURE_STORAGE_ACCOUNT_URL: str = ""
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    # A download link (GET /api/v1/files/{id}) is valid this long.
    STORAGE_SIGNED_URL_TTL_SECONDS: int = 600
    # Runtime secret lookups: env | azure_keyvault. Settings themselves come
    # from the environment (Key Vault CSI driver in AKS, .env locally).
    SECRETS_BACKEND: str = ""
    AZURE_KEYVAULT_URL: str = ""
    # Tokens for Azure services from the workload's identity (no stored keys):
    # azure_workload_identity | none. A laptop can opt in and use `az login`.
    WORKLOAD_IDENTITY_BACKEND: str = ""
    # Tenant key-encryption keys (WS5, §10.4): local | azure_keyvault. local keeps
    # one key file per tenant under LOCAL_KEK_DIR (empty = backend/.local-keys).
    KEK_BACKEND: str = ""
    LOCAL_KEK_DIR: str = ""
    # azure_keyvault: the tenant-keys vault (separate from platform secrets).
    AZURE_TENANT_KEYS_VAULT_URL: str = ""
    TENANT_KEK_HSM: bool = False
    # ── Connections (Phase 14 WS5, tech spec §10) ─────────────────────────
    # Where the provider sends the browser back: https://connect.<domain>
    # (empty = this API's public URL). OAuth state lives 10 minutes in Redis.
    CONNECTIONS_PUBLIC_URL: str = ""
    # The screen the browser lands on after a provider's window (the frontend).
    CONNECTIONS_RETURN_PATH: str = "/connections"
    # Tools fall back to the old social_connections / email_connections rows
    # until WS7's conversion has moved them (then switch off; WS9 removes it).
    CONNECTIONS_LEGACY_FALLBACK: bool = True
    # The registry holds system integrations only (D40, 5.7): /integrations is
    # staff's, for the platform company's rows. On once WS7 has moved every
    # business's own keys into connections (python -m src.connections.migrate).
    REGISTRY_PLATFORM_ONLY: bool = False
    # Refresh a token this long before it expires; warn the owner this many
    # days before an expiry that cannot be refreshed.
    CONNECTION_REFRESH_WINDOW_SECONDS: int = 1800
    CONNECTION_EXPIRY_WARNING_DAYS: int = 7
    # ── Automation (Phase 14 WS3, tech spec §7) ───────────────────────────
    # The business limits (chain depth, rates, agent limits, retention…) are
    # not settings: each business sets them on screen, none by default
    # (decision D47; src/automation/limits.py, table automation_settings).
    # The scheduler's loop, and how late a due time may be before catch-up rules apply.
    SCHEDULER_TICK_SECONDS: int = 5
    SCHEDULER_GRACE_SECONDS: int = 600
    # Inbound webhooks and internal events become events routed by triggers
    # (WS3 3.5/3.9). Off: the old direct path (process_gateway_event), for rollback.
    AUTOMATION_GATEWAY_EVENTS: bool = True
    # Events routed at once by one event worker (queue "events"). Routing is
    # short (it creates runs, it does not run them).
    EVENT_WORKER_MAX_JOBS: int = 20
    # The Data API (WS4, tech spec §9): the key its tokens are signed with
    # (derived from SECRET_KEY when empty), the business one instance serves
    # (empty: any, by the token), and the environment named in app keys.
    # DATA_API_URL is where agents' record tools reach it (…/data/v1); empty:
    # in this process.
    DATA_API_SIGNING_KEY: str = ""
    # Who signs Data API tokens (W4-1): hmac (DATA_API_SIGNING_KEY) or azure_keyvault
    # (RS256 with this key in AZURE_KEYVAULT_URL); empty = PLATFORM_PROFILE's default.
    TOKEN_SIGNER: str = ""
    DATA_API_SIGNING_KEY_NAME: str = "data-api-signing"
    DATA_API_TENANT_KEY: str = ""
    DATA_API_KEY_ENV: str = "dev"
    DATA_API_URL: str = ""
    # Per-key rate limits (tech spec §9.5): requests a second on average and in
    # a burst, for app keys and for outside systems' keys.
    DATA_API_KEY_RATE: int = 20
    DATA_API_KEY_BURST: int = 100
    DATA_API_EXTERNAL_RATE: int = 5
    DATA_API_EXTERNAL_BURST: int = 25
    # App users (WS6 6.10, tech spec §11.6): access tokens live 15 minutes,
    # refresh tokens 30 days, magic links 15 minutes.
    APP_USER_ACCESS_MINUTES: int = 15
    APP_USER_REFRESH_DAYS: int = 30
    APP_USER_MAGIC_LINK_MINUTES: int = 15

    # ── Tenant runtime and apps (Phase 14 WS6, tech spec §11) ─────────────
    # Kubernetes API (sandbox pods, TenantApp objects, edge routes): in a pod
    # the service account's token and CA; elsewhere KUBE_API_URL + KUBE_TOKEN.
    KUBE_API_URL: str = ""
    KUBE_TOKEN: str = ""
    KUBE_CA_FILE: str = ""
    # The sandbox on AKS (§11.1): kubernetes = KubernetesSandboxRuntime when
    # the container switch is on; empty = the Docker container runtime.
    SANDBOX_RUNTIME: str = ""
    SANDBOX_K8S_IMAGE: str = "hb-sandbox:local"
    SANDBOX_K8S_RUNTIME_CLASS: str = "kata-vm-isolation"
    SANDBOX_K8S_NODE_POOL: str = "sandbox"
    SANDBOX_K8S_WORKSPACE_LIMIT: str = "2Gi"
    SANDBOX_AGENT_PORT: int = 7070
    SANDBOX_IDLE_DELETE_SECONDS: int = 900
    SANDBOX_SCRATCH_RETENTION_DAYS: int = 7
    # Files synced between the platform's workspace and a sandbox pod per call.
    SANDBOX_SYNC_MAX_BYTES: int = 50 * 1024 * 1024
    # The cluster egress proxy (§11.1, 6.2): its address, and the secret its
    # per-tenant proxy credentials are derived from.
    EGRESS_PROXY_URL: str = "http://egress-proxy.hb-system.svc.cluster.local:8888"
    EGRESS_PROXY_SECRET: str = ""
    # Code lanes (D35): scratch code is kept this many days unless promoted;
    # a promotion's checks Job runs this image on AKS (backend/docker/checks).
    CODE_SCRATCH_RETENTION_DAYS: int = 7
    CHECKS_IMAGE: str = "hb-checks:local"
    # Built-in Git (D36): local_git (bare repositories under LOCAL_GIT_DIR,
    # empty = backend/.local-git) | gitea (GITEA_URL with GITEA_ADMIN_TOKEN).
    GIT_BACKEND: str = ""
    LOCAL_GIT_DIR: str = ""
    GITEA_URL: str = ""
    GITEA_ADMIN_TOKEN: str = ""
    # Builds (§11.4): docker (local CLI) | acr_tasks (ACR_* below).
    APP_BUILDER: str = ""
    ACR_SUBSCRIPTION_ID: str = ""
    ACR_RESOURCE_GROUP: str = ""
    ACR_REGISTRY_NAME: str = ""
    ACR_LOGIN_SERVER: str = ""
    APP_BUILD_TIMEOUT_SECONDS: int = 1800
    APP_BUILD_COST_PER_SECOND: float = 0.0001
    # Where apps run (§11.5): docker (local containers) | kubernetes (TenantApp
    # objects for the App Controller).
    APP_RUNTIME: str = ""
    # Hostnames: <app>-<slug>.apps.<APPS_DOMAIN>; previews expire after this many days.
    APPS_DOMAIN: str = "apps.localhost"
    APP_PREVIEW_DAYS: int = 7
    # Custom domains: the CNAME target (the edge's name) and, for an apex
    # domain that cannot have a CNAME, the edge's static IP.
    APP_EDGE_TARGET: str = ""
    APP_EDGE_IP: str = ""
    # Where an app reaches the Data API: from browsers (web apps) and from
    # its own pods (backends). Empty: this API's /data (local development).
    APP_DATA_API_PUBLIC_URL: str = ""
    APP_DATA_API_INTERNAL_URL: str = ""
    # Container Insights / managed Prometheus query endpoints (logs, metrics, metering).
    PROMETHEUS_QUERY_URL: str = ""
    LOG_ANALYTICS_WORKSPACE_ID: str = ""

    # Weekly database exports (decision D45, scripts/backup_databases.py): how
    # many weeks are kept, and the pg_dump binary (its major version must be
    # the server's or newer).
    BACKUP_KEEP_WEEKS: int = 5
    PG_DUMP_PATH: str = "pg_dump"
    # How the platform signs in to PostgreSQL: password (in DATABASE_URL) |
    # entra_token (Azure Flexible Server: the URL names the workload's Entra
    # principal, the password is a fresh token). Empty = the profile's default.
    DB_AUTH: str = ""

    # ── Phase 14 WS2: tenant data plane (tech spec §5.3, §16) ─────────────
    # single: one database holds every table (today) and tenant sessions open
    # on it. split: each tenant's tables live in its own database, found
    # through the tenant directory (src/common/tenancy).
    TENANCY_MODE: str = "single"
    # Port of the tenant database servers: 6432 is Flexible Server's built-in
    # PgBouncer; 0 = the control database URL's port (local Docker).
    TENANT_DB_PORT: int = 0
    # Tenant database engines kept open per process (least recently used go).
    TENANT_ENGINE_CACHE_SIZE: int = 200
    # Who owns and changes a tenant database (tech spec §5.2): DDL runs as this
    # group role (`SET ROLE`), so objects have one owner whoever migrates —
    # the provisioner or the migrator. Empty (local): the connection's user.
    TENANT_DB_DDL_ROLE: str = ""
    # The Entra principals a pool server needs (the provisioner makes them on
    # first use): API, workers and Connection Service (hb_runtime), the
    # migrator (hb_migrator). Comma-separated; empty (local): none.
    TENANT_DB_RUNTIME_PRINCIPALS: str = ""
    TENANT_DB_MIGRATOR_PRINCIPAL: str = ""
    # Provisioning jobs' queue: its own worker, signed in as the provisioner
    # identity (Azure). Empty: the default queue (one worker locally).
    PROVISIONING_QUEUE: str = ""
    # Each tenant's own identity (identity_ready, Azure): made in this resource
    # group, federated to `t-<key>/data-api` on the cluster's OIDC issuer.
    AZURE_SUBSCRIPTION_ID: str = ""
    AZURE_LOCATION: str = ""
    TENANT_IDENTITY_RESOURCE_GROUP: str = ""
    TENANT_IDENTITY_NAME_PREFIX: str = ""   # e.g. id-hb-dev-t- (+ the tenant key)
    AKS_OIDC_ISSUER: str = ""
    # in_process: the platform API serves every business's Data API at /data
    # (local, and Azure dev until the per-tenant Deployment, WS4); deployment:
    # each tenant gets its own (data_api_ready). Empty: by profile.
    DATA_API_MODE: str = ""

    @field_validator("TENANCY_MODE")
    @classmethod
    def _known_tenancy_mode(cls, value: str) -> str:
        mode = value.strip().lower()
        if mode not in ("single", "split"):
            raise ValueError(f"TENANCY_MODE must be single or split, not {value!r}")
        return mode

    @model_validator(mode="after")
    def _control_database_alias(self) -> "Settings":
        control, legacy = self.CONTROL_DATABASE_URL.strip(), self.DATABASE_URL.strip()
        if not (control or legacy):
            raise ValueError("CONTROL_DATABASE_URL (or its old name, DATABASE_URL) must be set")
        if control and legacy and control != legacy:
            raise ValueError("CONTROL_DATABASE_URL and DATABASE_URL are both set and differ; "
                             "set only CONTROL_DATABASE_URL")
        self.CONTROL_DATABASE_URL = self.DATABASE_URL = control or legacy
        return self

    # ── Model credentials on Azure (Phase 14 WS1 1.5–1.7, §12.4) ──────────
    # Google (Gemini, Live, Imagen/Veo, embeddings) from AKS without key files:
    # an external_account credential file for workload identity federation.
    # Empty = Application Default Credentials (gcloud login, a VM's account).
    GOOGLE_WIF_CREDENTIAL_FILE: str = ""
    # Where Claude runs when an integration's service_metadata names no
    # provider: vertex | foundry | anthropic. FOUNDRY_ENDPOINT is the Foundry
    # resource's Anthropic endpoint (https://<resource>.services.ai.azure.com/anthropic/)
    # when the integration names neither a resource nor an endpoint.
    ANTHROPIC_PROVIDER: str = "vertex"
    FOUNDRY_ENDPOINT: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def internal_events_enabled(self) -> bool:
        """True when INTERNAL_TOKEN is a real secret, not empty or a placeholder."""
        token = self.INTERNAL_TOKEN.strip()
        return bool(token) and token.lower() not in PLACEHOLDER_SECRETS

    @property
    def stun_servers_list(self) -> list[str]:
        return [s.strip() for s in self.STUN_SERVERS.split(",") if s.strip()]


def _load_settings() -> Settings:
    """The settings, plus any secret files mounted at ``SETTINGS_SECRETS_DIR``.

    In AKS the Key Vault CSI driver mounts each platform secret as a file named
    after its setting (``SECRET_KEY``, ``INTERNAL_TOKEN``, …; the chart's
    SecretProviderClass sets the aliases), so no secret is baked into an image
    or written into a manifest (Phase 14 WS1 1.4). A file fills a setting the
    environment does not set. The directory is named in the process
    environment, not in ``.env``.
    """
    secrets_dir = os.environ.get("SETTINGS_SECRETS_DIR", "").strip()
    if secrets_dir and Path(secrets_dir).is_dir():
        return Settings(_secrets_dir=secrets_dir)
    return Settings()


settings = _load_settings()
