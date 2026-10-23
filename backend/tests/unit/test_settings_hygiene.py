"""Phase 15 T0-7: settings are read through ``Settings``, and a misspelt one is reported.

* ``FRONTEND_URL`` was read twice, with two defaults (``Settings``: :3000, the
  e-mails: :5173); the OAuth client ids and secrets bypassed ``Settings`` (C-3).
* The default CORS list trusted a raw public IP (C-7).
* ``extra="ignore"`` let a misspelt variable change nothing, silently (C-8).
"""
from __future__ import annotations

import ast
from pathlib import Path

from src.common import config
from src.common.config import Settings, unknown_env_keys

SRC = Path(__file__).resolve().parents[2] / "src"


def test_no_raw_ip_is_trusted_by_default():
    default = Settings.model_fields["CORS_ORIGINS"].default
    hosts = [origin.split("//", 1)[1].split(":")[0] for origin in default.split(",")]
    assert not [h for h in hosts if h.replace(".", "").isdigit() and h != "127.0.0.1"]


def test_frontend_url_and_oauth_clients_are_settings_only():
    for name in ("FRONTEND_URL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                 "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"):
        assert name in Settings.model_fields
    readers = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("getenv", "get") and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and first.value in (
                        "FRONTEND_URL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                        "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"):
                    readers.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert readers == []


def test_unknown_keys_are_found(tmp_path):
    env = tmp_path / ".env"
    env.write_text("\n".join([
        "# REDIS_URLL=commented out",
        "REDIS_URL=redis://x",
        "export STREAMING_HOST=h",
        "JWT_SECRET=nothing-reads-me",
        "CORS_ORIGIN=http://a",            # a typo of CORS_ORIGINS
        "AI_FLAG_BANDIT_ENABLED=true",      # read by the flags, not Settings
        "VERTEX_PROJECT_ID=p",              # read by a seed script
        "",
    ]), encoding="utf-8")
    environ = {"PATH": "/bin", "FRONTEND_URLS": "http://x", "SECRET_KEY": "k", "OTEL_SDK_DISABLED": "true"}
    assert unknown_env_keys(str(env), environ) == ["CORS_ORIGIN", "FRONTEND_URLS", "JWT_SECRET"]


def test_each_unknown_key_is_logged_with_a_guess(monkeypatch):
    monkeypatch.setattr(config, "unknown_env_keys", lambda: ["CORS_ORIGIN"])
    said = []

    class Log:
        def warning(self, message, *args):
            said.append(message % args)

    assert config.warn_unknown_env_keys(Log()) == ["CORS_ORIGIN"]
    assert said == ["environment variable CORS_ORIGIN is not a setting and nothing reads it "
                    "(did you mean CORS_ORIGINS?)"]
