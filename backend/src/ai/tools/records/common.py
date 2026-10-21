"""What the record tools share (Phase 14 WS4 4.8): the records an agent may
reach — its ``capabilities.records`` over the business's active blueprint —
and a Data API client with the run's token.

The tools never touch the business's database: every call goes through the
Data API (``src.data_api.sdk``) with a run token, so an agent meets the same
checks, audit and ``record.*`` events as every other caller.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, FrozenSet, List, Optional, Tuple

from src.ai.tools.automation.common import Caller, caller_of
from src.ai.tools.base import ToolOutput

logger = logging.getLogger(__name__)

MAX_FIELDS_SHOWN = 40


@dataclass(frozen=True)
class RecordsView:
    """The objects an agent may use, and how, at one blueprint version."""
    version: int
    objects: Dict[str, Dict[str, Any]]          # name → {label, plural, description, fields}
    operations: Dict[str, FrozenSet[str]]       # name → operations
    reports: bool
    schema_changes: bool

    def names(self, operation: str) -> List[str]:
        return [n for n in self.objects if operation in self.operations.get(n, frozenset())]


async def records_view(company_id: Any, entity: Any, shared: Dict[str, Any]) -> Optional[RecordsView]:
    """The agent's view, read once per tool load (``shared``); ``None`` when the
    business has no records of its own yet."""
    if "records" not in shared:
        shared["records"] = await _load_view(company_id, entity)
    return shared["records"]


async def _load_view(company_id: Any, entity: Any) -> Optional[RecordsView]:
    from src.data_api import tokens
    from src.schema_engine import blueprint as bp
    from src.schema_engine import engine as schema

    caps = tokens.records_capability(entity)
    try:
        engine, _ = await schema.business_engine(company_id)
    except schema.RecordsUnavailable:
        return None
    blueprint = await schema.active_blueprint(engine, company_id)
    granted = tokens.permissions(caps.get("objects") or {})
    objects, operations = {}, {}
    for name, obj in bp.objects(blueprint).items():
        allowed = granted.get(name) or granted.get("*") or frozenset()
        if not allowed:
            continue
        objects[name] = {"label": obj.get("label"), "plural": obj.get("plural"),
                         "description": obj.get("description"), "fields": bp.fields(obj)}
        operations[name] = allowed
    return RecordsView(version=blueprint["version"], objects=objects, operations=operations,
                       reports=bool(caps.get("reports")), schema_changes=caps.get("schema_changes") == "propose")


def field_line(name: str, spec: Dict[str, Any]) -> str:
    kind = spec["type"]
    if kind == "enum":
        what = "one of " + "|".join(spec["values"])
    elif kind == "ref":
        what = f"id of a {spec['to']}"
    elif kind == "money":
        what = f"money (amount; currency in {name}_currency)"
    elif kind == "text" and spec.get("max_length"):
        what = f"text ≤{spec['max_length']}"
    else:
        what = kind.replace("_", " ")
    flags = [f for f, on in (("required", spec.get("required")), ("unique", spec.get("unique")),
                             ("personal", spec.get("sensitivity") in ("pii", "secret"))) if on]
    if spec.get("default") is not None:
        flags.append(f"default {spec['default']}")
    return f"{name} ({what}{'; ' + ', '.join(flags) if flags else ''})"


def describe_objects(view: RecordsView, names: List[str]) -> str:
    """One line per object with its fields, for a tool's description."""
    lines = []
    for name in names:
        fields = list(view.objects[name]["fields"].items())
        shown = ", ".join(field_line(n, s) for n, s in fields[:MAX_FIELDS_SHOWN])
        more = f", … {len(fields) - MAX_FIELDS_SHOWN} more (describe_schema)" if len(fields) > MAX_FIELDS_SHOWN else ""
        lines.append(f"- {name}: {shown}{more}")
    return "\n".join(lines)


@dataclass(frozen=True)
class RunRecords:
    """One call's Data API client (as the run), the run and its agent."""
    client: Any
    caller: Caller
    entity: Any


@asynccontextmanager
async def run_client(ctx: Dict[str, Any]) -> AsyncIterator[Tuple[Optional[RunRecords], Optional[ToolOutput]]]:
    """``(records, None)``: the Data API as this run; ``(None, refusal)``: why not."""
    from src.ai.orm import HierarchicalEntity
    from src.common.tenancy.session import tenant_session
    from src.data_api import sdk, tokens
    from src.schema_engine import engine as schema

    caller, refused = caller_of(ctx)
    if refused:
        yield None, refused
        return
    try:
        _, location = await schema.business_engine(caller.company_id)
    except schema.RecordsUnavailable as error:
        yield None, ToolOutput.failed(str(error), code="records_unavailable")
        return
    async with tenant_session(caller.company_id) as db:
        entity = await db.get(HierarchicalEntity, caller.entity_id)
    if entity is None or entity.company_id != caller.company_id:
        yield None, ToolOutput.failed("the agent of this run was not found", code="no_run")
        return
    token = await tokens.mint_run_token(caller.run_id, entity, caller.company_id, location.key)
    async with sdk.DataApi(token) as client:
        yield RunRecords(client, caller, entity), None


def failed(error: Any) -> ToolOutput:
    """A Data API refusal as the tool's failure (the model reads the reason)."""
    from src.data_api.sdk import DataApiError

    if isinstance(error, DataApiError):
        return ToolOutput.failed(f"{error.code}: {error.detail}", code=error.code, status=error.status)
    return ToolOutput.failed(str(error), code="tool_error")
