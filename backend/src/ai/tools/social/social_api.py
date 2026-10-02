"""``social_api`` — one primitive for every connected social platform (R2, P6.2).

There were 52 per-verb social tools (``twitter_create_post``,
``google_ads_report``, …): each a function declaration in every prompt that
granted it, and 20 of them for platforms no connection could be made for.
They are now the internal **operations** of one tool. The model first asks a
platform what it can do (``operation="describe"`` — its operations and their
parameters), then calls one with a ``payload``. Platform knowledge — how to
post, report, answer comments — belongs in SKILLs, not in tool schemas.

The platforms are one list (decision D17): those a connection can be created
for **and** refreshed — ``social_connection_service.PLATFORM_REFRESH_CONFIG``.
"""
from __future__ import annotations

import inspect
import json
from typing import Any, Dict, Optional

from pydantic import Field, field_validator

from src.ai.social_connection_service import PLATFORM_REFRESH_CONFIG
from src.ai.tools.base import Tool, ToolOutput, ToolParams, ToolStatus
from src.ai.tools.social import facebook, google_ads, instagram, linkedin, reddit, tiktok, twitter, youtube
from src.ai.tools.social.base import SocialMediaTool

__all__ = ["SOCIAL_PLATFORMS", "SocialAPITool", "operations"]

SOCIAL_PLATFORMS: tuple[str, ...] = tuple(sorted(PLATFORM_REFRESH_CONFIG))
DESCRIBE = "describe"

# Operations that change something on the platform: never re-run by the
# resilience layer, and keyed for idempotency.
_WRITE_VERBS = ("create", "publish", "upload", "send", "save", "manage")


def _load_operations() -> Dict[str, Dict[str, SocialMediaTool]]:
    ops: Dict[str, Dict[str, SocialMediaTool]] = {}
    for module in (facebook, google_ads, instagram, linkedin, reddit, tiktok, twitter, youtube):
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, SocialMediaTool) and cls is not SocialMediaTool and cls.__module__ == module.__name__:
                op = cls()
                verb = op.name[len(op.platform) + 1:] if op.name.startswith(op.platform + "_") else op.name
                ops.setdefault(op.platform, {})[verb] = op
    return ops


_OPERATIONS = _load_operations()


def operations() -> Dict[str, Dict[str, SocialMediaTool]]:
    """``{platform: {operation: implementation}}``."""
    return _OPERATIONS


def writes(operation: str) -> bool:
    return operation.split("_", 1)[0] in _WRITE_VERBS


class SocialAPIParams(ToolParams):
    platform: str = Field(..., json_schema_extra={"enum": list(SOCIAL_PLATFORMS)},
                          description="The platform: " + ", ".join(SOCIAL_PLATFORMS))
    operation: str = Field(..., description=(
        "'describe' lists the platform's operations and their parameters — call it first; "
        "otherwise the operation to run"))
    payload: Dict[str, Any] = Field(default_factory=dict, description=(
        "The operation's parameters, as 'describe' lists them"))

    @field_validator("platform")
    @classmethod
    def _a_connected_platform(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in SOCIAL_PLATFORMS:
            raise ValueError(f"'{v}' is not a platform this tool reaches; one of {list(SOCIAL_PLATFORMS)}")
        return v


class SocialAPITool(Tool):
    name = "social_api"
    category = "social"
    description = (
        "Act on a connected social or ads platform (LinkedIn, X, Facebook, Instagram, "
        "Google Ads, YouTube, TikTok, Reddit). Call it with operation 'describe' to list a "
        "platform's operations and their parameters, then call the operation with its "
        "payload. Credentials come from the company's connection."
    )
    # Unfinished integrations behind one opt-in: ``tools.experimental.social_api``.
    status = ToolStatus.EXPERIMENTAL
    Params = SocialAPIParams

    async def execute(self, params: SocialAPIParams, ctx: Dict[str, Any]) -> ToolOutput:
        platform_ops = _OPERATIONS.get(params.platform, {})
        if params.operation == DESCRIBE:
            return ToolOutput(output=json.dumps({
                "platform": params.platform,
                "operations": [
                    {"operation": verb, "description": op.description, "writes": writes(verb),
                     "parameters": op.get_function_schema()["parameters"]}
                    for verb, op in sorted(platform_ops.items())
                ],
            }))
        op = platform_ops.get(params.operation)
        if op is None:
            return ToolOutput.failed(
                f"{params.platform} has no operation '{params.operation}'; one of {sorted(platform_ops)} "
                f"(or '{DESCRIBE}')", code="unknown_operation")
        problem = _payload_problem(op, params.payload)
        if problem:
            return ToolOutput.failed(f"{params.platform}.{params.operation}: {problem}",
                                     code="invalid_arguments")
        out = await op.run_with_context(json.dumps(params.payload), ctx)
        meta = {"platform": params.platform, "operation": params.operation, "writes": writes(params.operation)}
        error = _error_of(out)
        if error:
            return ToolOutput(success=False, output=out, error=error, error_code="platform_error", metadata=meta)
        return ToolOutput(output=out, metadata=meta)


def _payload_problem(op: SocialMediaTool, payload: Dict[str, Any]) -> Optional[str]:
    """What is wrong with ``payload`` against the operation's schema, if anything."""
    schema = op.get_function_schema()["parameters"]
    properties = schema.get("properties", {})
    missing = [k for k in schema.get("required", []) if payload.get(k) in (None, "")]
    unknown = sorted(set(payload) - set(properties))
    parts = []
    if missing:
        parts.append(f"missing {missing}")
    if unknown:
        parts.append(f"unknown {unknown}")
    return f"{'; '.join(parts)} — the operation takes {sorted(properties)}" if parts else None


def _error_of(out: str) -> Optional[str]:
    try:
        parsed = json.loads(out)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict) and parsed.get("error"):
        return str(parsed["error"])
    return None
