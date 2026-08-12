from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ENCRYPTION_MASTER_KEY: str = "your-default-dev-key-must-be-32-bytes" # Overridden by env
    STREAMING_HOST: str = "localhost:8002"
    STREAMING_PROTOCOL: str = "ws"

    # Phase 12 `02` S4 — per-tenant container sandbox. OFF by default;
    # SubprocessRuntime stays the dev/CI default and the production rollback.
    SANDBOX_CONTAINER_RUNTIME_ENABLED: bool = False
    SANDBOX_IMAGE: str = "hb-sandbox:local"
    SANDBOX_NETWORK: str = "none"
    SANDBOX_MEMORY: str = "1g"
    SANDBOX_CPUS: str = "1.0"
    SANDBOX_PIDS_LIMIT: int = 256
    SANDBOX_IDLE_PAUSE_SECONDS: int = 900
    SANDBOX_REAP_SECONDS: int = 86400
    # S6 cost attribution: sandbox runtime time is metered against this SKU
    # (IntegrationRegistry.service_sku, owned by the APP company; cost_unit
    # "second"). Seed it with scripts/seed_sandbox_sku.py.
    SANDBOX_COST_SKU: str = "sandbox-runtime"
    # S5 persistent browser: when enabled, headless_browser uses a persistent
    # Chromium profile under the tenant workspace so cookies/logins survive across
    # calls. OFF by default (ephemeral context = today's behavior).
    SANDBOX_PERSISTENT_BROWSER_ENABLED: bool = False
    # S7 egress proxy (Phase 12 `02`/`06`): the network gate for synthesized /
    # network-using tools. When ALLOWLIST is in force the sandbox container joins
    # an --internal docker network (no direct internet) whose only route out is a
    # dual-homed tinyproxy enforcing SANDBOX_EGRESS_ALLOWLIST. OFF by default
    # (NetworkPolicy.NONE → --network none stays today's behavior).
    SANDBOX_EGRESS_PROXY_ENABLED: bool = False
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
    # RMS threshold on 16-bit PCM inbound audio above which the lead counts
    # as speaking (μ-law frames flow continuously even in silence).
    VOICE_VAD_RMS_THRESHOLD: int = 300
    # Echo suppression: while agent audio is playing at the provider, inbound
    # frames quieter than this are NOT forwarded to the model. PSTN echo of
    # the agent's own voice (attenuated, typically rms<600) was triggering
    # Gemini's barge-in and gibberish transcripts; real interjections are
    # much louder. 0 disables the gate.
    VOICE_ECHO_SUPPRESS_RMS: int = 600
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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
