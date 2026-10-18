"""The Data API's HTTP surface (tech spec §9.2, §9.5).

``create_app()`` builds the FastAPI app: the platform API mounts it under
``/data``; ``src.data_api.main:app`` runs it alone (``DATA_API_TENANT_KEY``
pins one business, as the per-tenant deployment of §9.1 does).

| Method | Path | |
|--------|------|-|
| GET | ``/healthz``, ``/readyz`` | process; database and blueprint |
| GET | ``/v1/schema`` | the active blueprint, objects the caller may read |
| GET | ``/v1/openapi.json`` | generated from the blueprint |
| GET | ``/v1/{object}`` | list: ``filter[f][op]``, ``sort``, ``page[size]``, ``page[after]``, ``fields``, ``include`` |
| GET | ``/v1/{object}/{id}`` | one record, ``ETag: "<row_version>"``; ``include`` |
| POST | ``/v1/{object}`` | create; ``Idempotency-Key`` (24 h) |
| PATCH | ``/v1/{object}/{id}`` | update; ``If-Match`` required, ``412`` when stale |
| DELETE | ``/v1/{object}/{id}`` | archive |
| GET, POST | ``/v1/{object}/{id}/links/{relation}`` | linked records; link or unlink |
| POST | ``/v1/batch`` | up to 100 creates, updates, archives in one transaction |
| POST | ``/v1/reports`` | aggregates |
| POST | ``/v1/schema/changes`` | propose (``dry_run`` previews) |
| GET | ``/v1/schema/changes/{id}`` | status and impact |
| POST | ``/v1/schema/changes/{id}/approve`` / ``reject`` | owners and admins |

Every error is one problem-details shape: ``{type, title, status, detail, code}``.
App keys are rate limited (``DATA_API_KEY_*``, ``DATA_API_EXTERNAL_*``; 429
with ``Retry-After``). Links are ``ref`` fields, one level: a record's link
field, or the records of another object linking to it (an order's shipments).
Later: app end-user auth (§11.6), row policies.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select, text

from src.data_api import records, tokens
from src.data_api.model import model_for
from src.schema_engine import blueprint as bp
from src.schema_engine import engine as schema
from src.schema_engine.planner import PlanError

logger = logging.getLogger(__name__)

MAX_BODY = 1_000_000
MAX_BATCH = 100
IDEMPOTENCY_TTL = 24 * 3600
BIG_TABLE = 100_000


def problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, media_type="application/problem+json", content={
        "type": f"https://docs.hirebuddha.com/errors/{code}", "title": code.replace("_", " "),
        "status": status, "detail": detail, "code": code})


async def _company_for_tenant(tenant_key: str) -> Any:
    from src.common.tenancy.models import TenantDirectoryEntry
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        company_id = (await db.execute(select(TenantDirectoryEntry.company_id).where(
            TenantDirectoryEntry.tenant_key == tenant_key))).scalar()
    if company_id is None:
        raise tokens.Unauthorized("unknown business")
    return company_id


def _pinned() -> Optional[str]:
    from src.common.config import settings

    return getattr(settings, "DATA_API_TENANT_KEY", "") or None


class Context:
    """One request: who calls, the business's database, its blueprint and model."""

    def __init__(self, caller: tokens.Caller, engine: Any, blueprint: Dict[str, Any]) -> None:
        self.caller, self.engine, self.blueprint = caller, engine, blueprint
        self.model = model_for(caller.company_id, blueprint)

    def require(self, object_name: str, operation: str) -> str:
        try:
            name, _ = bp.resolve_object(self.blueprint, object_name)
        except bp.BlueprintError:
            raise records.RecordError(404, "unknown_object", f"no object {object_name!r}") from None
        if not self.caller.may(name, operation):
            raise records.RecordError(403, "forbidden", f"not allowed to {operation} {name}")
        return name


async def context(request: Request) -> Context:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise tokens.Unauthorized("send Authorization: Bearer <token or app key>")
    credential = header[7:].strip()
    pinned = _pinned()
    if credential.startswith("hbk_"):
        tenant_key = tokens.tenant_of_key(credential)
        if not tenant_key or (pinned and tenant_key != pinned):
            raise tokens.Unauthorized("the key is for another business")
        company_id = await _company_for_tenant(tenant_key)
        engine, _ = await schema.business_engine(company_id)
        async with schema.session(engine) as db:
            caller = await tokens.caller_for_key(db, credential, tenant_key, company_id)
    else:
        caller = tokens.decode(credential, tenant_key=pinned)
        engine, location = await schema.business_engine(caller.company_id)
        if location.key != caller.tenant_key:
            raise tokens.Unauthorized("the token is for another business")
    if caller.kind == "key":
        await _rate_limit(caller)
    return Context(caller, engine, await schema.active_blueprint(engine, caller.company_id))


class RateLimited(Exception):
    """A key over its rate (429, ``Retry-After``)."""


async def _rate_limit(caller: tokens.Caller) -> None:
    """Per key (§9.5): at most the burst in one second and the rate on average over ten.
    Without Redis the request goes through (logged): the limit protects, it never blocks the API."""
    import time

    from src.common.config import settings

    rate = settings.DATA_API_EXTERNAL_RATE if caller.external else settings.DATA_API_KEY_RATE
    burst = settings.DATA_API_EXTERNAL_BURST if caller.external else settings.DATA_API_KEY_BURST
    now = int(time.time())
    second, ten = f"dapi:rl:{caller.actor}:1:{now}", f"dapi:rl:{caller.actor}:10:{now // 10}"
    try:
        from src.common.redis_client import shared_redis

        pipe = shared_redis().pipeline()
        pipe.incr(second)
        pipe.expire(second, 2)
        pipe.incr(ten)
        pipe.expire(ten, 20)
        in_second, _, in_ten, _ = await pipe.execute()
    except Exception as error:  # noqa: BLE001
        logger.warning("Data API rate limit not checked: %s", error)
        return
    if in_second > burst or in_ten > rate * 10:
        raise RateLimited(f"over {rate} requests a second (burst {burst}) for this key")


def _etag(version: int) -> str:
    return f'"{version}"'


def _if_match(request: Request) -> Optional[int]:
    raw = request.headers.get("if-match")
    if raw is None:
        return None
    match = re.match(r'^(?:W/)?"?(\d+)"?$', raw.strip())
    if not match:
        raise records.RecordError(400, "invalid_if_match", "If-Match is the record's ETag")
    return int(match.group(1))


async def _body(request: Request) -> Any:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise records.RecordError(413, "too_large", "the body is at most 1 MB")
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        raise records.RecordError(400, "invalid_json", "the body is not JSON") from None


async def _nudge(company_id: Any, event_id: Any) -> None:
    if event_id is None:
        return
    from src.automation import store

    await store.nudge(company_id, event_id)


async def _check_filters(ctx: Context, name: str, conditions: Any) -> None:
    """A filter on an unindexed field of a big table is refused without the reports scope."""
    if not conditions or ctx.caller.reports:
        return
    obj = ctx.blueprint["objects"][name]
    indexed = {"id"} | {cols[0] for cols in obj.get("indexes", []) + obj.get("unique", [])} \
        | {n for n, s in bp.fields(obj).items() if s["type"] == "ref"}
    unindexed = [f for f, _, _ in conditions if f not in indexed]
    if not unindexed:
        return
    async with ctx.engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT c.reltuples::bigint FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :s AND c.relname = :t"),
            {"s": obj["storage"]["schema"], "t": obj["storage"]["table"]})).scalar() or 0
    if rows > BIG_TABLE:
        raise records.RecordError(422, "unindexed_filter",
                                  f"{', '.join(unindexed)} is not indexed on a table this size; add an index "
                                  "or use a key with the reports scope")


def _includes(ctx: Context, name: str, raw: Optional[str]) -> list:
    """``include=account,owner``: link fields whose objects the caller may read."""
    wanted = [r for r in (raw or "").split(",") if r]
    for relation in wanted:
        kind, _, field = records.relation_of(ctx.model, name, relation)
        if kind == "forward":
            ctx.require(ctx.blueprint["objects"][name]["fields"][field]["to"], "read")
    return wanted


BATCH_OPERATIONS = {"create": "create", "update": "update", "archive": "delete"}


async def _batch_one(db: Any, ctx: Context, op: Any) -> Tuple[Dict[str, Any], Any]:
    if not isinstance(op, dict) or op.get("op") not in BATCH_OPERATIONS:
        raise records.RecordError(422, "invalid_batch", f"op is one of {', '.join(BATCH_OPERATIONS)}")
    name = ctx.require(str(op.get("object") or ""), BATCH_OPERATIONS[op["op"]])
    company, actor = ctx.caller.company_id, ctx.caller.actor
    if op["op"] == "create":
        return await records.create_record(db, ctx.model, company, name, op.get("values") or {}, actor=actor)
    if not op.get("id"):
        raise records.RecordError(422, "invalid_batch", f"{op['op']} needs the record's id")
    if op["op"] == "archive":
        return await records.archive_record(db, ctx.model, company, name, op["id"], actor=actor)
    version = op.get("row_version")
    if version is None:
        raise records.RecordError(428, "if_match_required", "an update in a batch names the row_version it read")
    return await records.update_record(db, ctx.model, company, name, op["id"], op.get("values") or {},
                                       actor=actor, if_match=int(version))


def _openapi(ctx: Context) -> Dict[str, Any]:
    types = {"integer": "integer", "decimal": "string", "money": "string", "boolean": "boolean"}
    paths: Dict[str, Any] = {}
    components: Dict[str, Any] = {}
    for name in ctx.caller.readable(bp.objects(ctx.blueprint)):
        obj = ctx.blueprint["objects"][name]
        properties = {c: {"type": "string"} for c in bp.SYSTEM_COLUMNS}
        properties["row_version"] = {"type": "integer"}
        for field_name, spec in bp.fields(obj).items():
            prop: Dict[str, Any] = {"type": types.get(spec["type"], "string")}
            if spec["type"] == "enum":
                prop["enum"] = spec["values"]
            if spec["type"] in ("date", "datetime"):
                prop["format"] = "date" if spec["type"] == "date" else "date-time"
            properties[field_name] = prop
        components[name] = {"type": "object", "properties": properties,
                            "required": [n for n, s in bp.fields(obj).items() if s.get("required")]}
        ref = {"$ref": f"#/components/schemas/{name}"}
        paths[f"/v1/{name}"] = {"get": {"summary": f"List {obj['plural']}"},
                                "post": {"summary": f"Create a {obj['label']}",
                                         "requestBody": {"content": {"application/json": {"schema": ref}}}}}
        paths[f"/v1/{name}/{{id}}"] = {"get": {"summary": f"One {obj['label']}"},
                                       "patch": {"summary": f"Update a {obj['label']} (If-Match)"},
                                       "delete": {"summary": f"Archive a {obj['label']}"}}
    return {"openapi": "3.1.0", "info": {"title": "HireBuddha Data API", "version": str(ctx.blueprint["version"])},
            "paths": paths, "components": {"schemas": components}}


def create_app() -> FastAPI:
    app = FastAPI(title="HireBuddha Data API", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(records.RecordError)
    async def _record_error(request: Request, error: records.RecordError) -> JSONResponse:
        return problem(error.status, error.code, error.detail)

    @app.exception_handler(tokens.Unauthorized)
    async def _unauthorized(request: Request, error: tokens.Unauthorized) -> JSONResponse:
        return problem(401, "unauthorized", str(error))

    @app.exception_handler(schema.RecordsUnavailable)
    async def _unavailable(request: Request, error: schema.RecordsUnavailable) -> JSONResponse:
        return problem(409, "records_unavailable", str(error))

    @app.exception_handler(PlanError)
    async def _plan_error(request: Request, error: PlanError) -> JSONResponse:
        return problem(422, "invalid_change", str(error))

    @app.exception_handler(schema.ApplyError)
    async def _apply_error(request: Request, error: schema.ApplyError) -> JSONResponse:
        return problem(409, "change_not_applied", str(error))

    @app.exception_handler(RateLimited)
    async def _rate_limited(request: Request, error: RateLimited) -> JSONResponse:
        response = problem(429, "rate_limited", str(error))
        response.headers["Retry-After"] = "1"
        return response

    @app.get("/healthz")
    async def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> Any:
        pinned = _pinned()
        if not pinned:
            return {"status": "ok", "tenant": None}
        try:
            company_id = await _company_for_tenant(pinned)
            engine, _ = await schema.business_engine(company_id)
            version = (await schema.active_blueprint(engine, company_id))["version"]
        except Exception as error:  # noqa: BLE001
            return problem(503, "not_ready", str(error))
        return {"status": "ok", "tenant": pinned, "blueprint_version": version}

    @app.get("/v1/schema")
    async def get_schema(ctx: Context = Depends(context)) -> Dict[str, Any]:
        visible = ctx.caller.readable(bp.objects(ctx.blueprint))
        return {"version": ctx.blueprint["version"], "base_pack": ctx.blueprint.get("base_pack"),
                "objects": {n: {**ctx.blueprint["objects"][n], "fields": bp.fields(ctx.blueprint["objects"][n])}
                            for n in visible}}

    @app.get("/v1/openapi.json")
    async def openapi(ctx: Context = Depends(context)) -> Dict[str, Any]:
        return _openapi(ctx)

    @app.post("/v1/reports")
    async def reports(request: Request, ctx: Context = Depends(context)) -> Dict[str, Any]:
        if not ctx.caller.reports:
            raise records.RecordError(403, "forbidden", "reports need the reports scope")
        spec = await _body(request)
        ctx.require(str((spec or {}).get("object") or ""), "read")
        async with ctx.engine.connect() as conn:
            await conn.execute(text("SET LOCAL statement_timeout = '30s'"))
            return await records.report(conn, ctx.model, spec)

    @app.post("/v1/schema/changes", status_code=201)
    async def propose_change(request: Request, ctx: Context = Depends(context)) -> Dict[str, Any]:
        if ctx.caller.schema not in ("propose", "apply"):
            raise records.RecordError(403, "forbidden", "not allowed to change the schema")
        body = await _body(request)
        kind = "agent" if ctx.caller.kind == "run" else ("user" if ctx.caller.schema == "apply" else "key")
        return await schema.propose(ctx.engine, ctx.caller.company_id, body.get("operations"),
                                    actor_kind=kind, actor_id=ctx.caller.actor, reason=body.get("reason"),
                                    run_id=ctx.caller.actor[4:] if ctx.caller.kind == "run" else None,
                                    dry_run=bool(body.get("dry_run")))

    @app.get("/v1/schema/changes/{change_id}")
    async def get_change(change_id: str, ctx: Context = Depends(context)) -> Dict[str, Any]:
        try:
            return await schema.change_view(ctx.engine, ctx.caller.company_id, change_id)
        except (LookupError, ValueError):
            raise records.RecordError(404, "not_found", "no such change") from None

    async def _decide(change_id: str, ctx: Context, approve: bool) -> Dict[str, Any]:
        if ctx.caller.schema != "apply":
            raise records.RecordError(403, "forbidden", "owners and admins decide schema changes")
        try:
            return await schema.decide(ctx.engine, ctx.caller.company_id, change_id, approve=approve,
                                       decided_by=ctx.caller.actor)
        except (LookupError, ValueError):
            raise records.RecordError(404, "not_found", "no such change") from None

    @app.post("/v1/schema/changes/{change_id}/approve")
    async def approve_change(change_id: str, ctx: Context = Depends(context)) -> Dict[str, Any]:
        return await _decide(change_id, ctx, True)

    @app.post("/v1/schema/changes/{change_id}/reject")
    async def reject_change(change_id: str, ctx: Context = Depends(context)) -> Dict[str, Any]:
        return await _decide(change_id, ctx, False)

    @app.get("/v1/{object_name}")
    async def list_records(object_name: str, request: Request, ctx: Context = Depends(context)) -> Dict[str, Any]:
        name = ctx.require(object_name, "read")
        params = request.query_params
        conditions = records.filters_from_query(list(params.multi_items()))
        await _check_filters(ctx, name, conditions)
        fields = [f for f in (params.get("fields") or "").split(",") if f] or None
        includes = _includes(ctx, name, params.get("include"))
        async with ctx.engine.connect() as conn:
            await conn.execute(text("SET LOCAL statement_timeout = '5s'"))
            page = await records.list_records(
                conn, ctx.model, name, conditions=conditions, sort=params.get("sort"),
                size=int(params.get("page[size]") or records.DEFAULT_PAGE), after=params.get("page[after]"),
                fields=fields, include_archived=params.get("archived") == "true")
            if includes:
                await records.include(conn, ctx.model, name, page["items"], includes)
            return page

    @app.get("/v1/{object_name}/{record_id}")
    async def get_record(object_name: str, record_id: str, request: Request,
                         ctx: Context = Depends(context)) -> Response:
        name = ctx.require(object_name, "read")
        includes = _includes(ctx, name, request.query_params.get("include"))
        async with ctx.engine.connect() as conn:
            record, version = await records.get_record(conn, ctx.model, name, record_id)
            if includes:
                await records.include(conn, ctx.model, name, [record], includes)
        return JSONResponse(record, headers={"ETag": _etag(version)})

    @app.get("/v1/{object_name}/{record_id}/links/{relation}")
    async def linked(object_name: str, record_id: str, relation: str, request: Request,
                     ctx: Context = Depends(context)) -> Dict[str, Any]:
        """The record a link field points to, or the records of another object linking to this one."""
        name = ctx.require(object_name, "read")
        kind, other, field = records.relation_of(ctx.model, name, relation)
        params = request.query_params
        async with ctx.engine.connect() as conn:
            await conn.execute(text("SET LOCAL statement_timeout = '5s'"))
            record, _ = await records.get_record(conn, ctx.model, name, record_id)
            if kind == "forward":
                target = ctx.blueprint["objects"][name]["fields"][field]["to"]
                ctx.require(target, "read")
                if not record.get(field):
                    return {"object": target, "items": [], "next": None}
                found, _ = await records.get_record(conn, ctx.model, target, record[field])
                return {"object": target, "items": [found], "next": None}
            ctx.require(other, "read")
            return await records.list_records(
                conn, ctx.model, other, conditions=[(field, "eq", record["id"])], sort=params.get("sort"),
                size=int(params.get("page[size]") or records.DEFAULT_PAGE), after=params.get("page[after]"))

    @app.post("/v1/{object_name}/{record_id}/links/{relation}")
    async def link(object_name: str, record_id: str, relation: str, request: Request,
                   ctx: Context = Depends(context)) -> Dict[str, Any]:
        """Link records: ``{"id": …}`` (or null) for a link field of this record;
        ``{"ids": [...], "unlink": [...]}`` for the records of another object linking to it."""
        name = ctx.require(object_name, "read")
        kind, other, field = records.relation_of(ctx.model, name, relation)
        body = await _body(request)
        changed, events = [], []
        async with schema.session(ctx.engine) as db:
            if kind == "forward":
                ctx.require(name, "update")
                version = await records.current_version(db, ctx.model, name, record_id)
                record, event_id = await records.update_record(
                    db, ctx.model, ctx.caller.company_id, name, record_id, {field: (body or {}).get("id")},
                    actor=ctx.caller.actor, if_match=version)
                changed.append(record)
                events.append(event_id)
            else:
                ctx.require(other, "update")
                this, _ = await records.get_record(db, ctx.model, name, record_id)  # it exists; its id as stored
                link_ids, unlink_ids = list((body or {}).get("ids") or []), list((body or {}).get("unlink") or [])
                if len(link_ids) + len(unlink_ids) > records.MAX_LINKS:
                    raise records.RecordError(422, "too_many_links", f"at most {records.MAX_LINKS} records at once")
                for other_id, value in [(i, this["id"]) for i in link_ids] + [(i, None) for i in unlink_ids]:
                    current, version = await records.get_record(db, ctx.model, other, other_id)
                    if value is None and current.get(field) != this["id"]:
                        continue  # linked to another record, or to none: unlinking it from this one changes nothing
                    record, event_id = await records.update_record(
                        db, ctx.model, ctx.caller.company_id, other, other_id, {field: value},
                        actor=ctx.caller.actor, if_match=version)
                    changed.append(record)
                    events.append(event_id)
            await db.commit()
        for event_id in events:
            await _nudge(ctx.caller.company_id, event_id)
        return {"object": name if kind == "forward" else other, "changed": changed}

    @app.post("/v1/batch")
    async def batch(request: Request, ctx: Context = Depends(context)) -> Dict[str, Any]:
        """Up to 100 creates, updates and archives in one transaction: all happen, or none.
        ``{"operations": [{"op": "create", "object": "order", "values": {…}},
        {"op": "update", "object": "order", "id": …, "row_version": 3, "values": {…}},
        {"op": "archive", "object": "order", "id": …}]}``"""
        body = await _body(request)
        operations = (body or {}).get("operations")
        if not isinstance(operations, list) or not operations:
            raise records.RecordError(422, "invalid_batch", "operations is a non-empty list")
        if len(operations) > MAX_BATCH:
            raise records.RecordError(422, "invalid_batch", f"at most {MAX_BATCH} operations in one batch")
        results, events = [], []
        async with schema.session(ctx.engine) as db:
            for index, op in enumerate(operations):
                try:
                    record, event_id = await _batch_one(db, ctx, op)
                except records.RecordError as error:
                    raise records.RecordError(error.status, error.code,
                                              f"operation {index}: {error.detail}; nothing was changed") from None
                results.append(record)
                events.append(event_id)
            await db.commit()
        for event_id in events:
            await _nudge(ctx.caller.company_id, event_id)
        return {"results": results}

    @app.post("/v1/{object_name}", status_code=201)
    async def create_record(object_name: str, request: Request, ctx: Context = Depends(context)) -> Response:
        name = ctx.require(object_name, "create")
        idem = request.headers.get("idempotency-key")
        redis_key = f"dapi:idem:{ctx.caller.company_id}:{ctx.caller.actor}:{idem}" if idem else None
        if redis_key:
            from src.common.redis_client import shared_redis

            earlier = await shared_redis().get(redis_key)
            if earlier:
                return JSONResponse(json.loads(earlier), status_code=201, headers={"Idempotent-Replayed": "true"})
        body = await _body(request)
        async with schema.session(ctx.engine) as db:
            record, event_id = await records.create_record(db, ctx.model, ctx.caller.company_id, name, body,
                                                           actor=ctx.caller.actor)
            await db.commit()
        await _nudge(ctx.caller.company_id, event_id)
        if redis_key:
            from src.common.redis_client import shared_redis

            await shared_redis().set(redis_key, json.dumps(record), ex=IDEMPOTENCY_TTL)
        return JSONResponse(record, status_code=201, headers={"ETag": _etag(record["row_version"])})

    @app.patch("/v1/{object_name}/{record_id}")
    async def update_record(object_name: str, record_id: str, request: Request,
                            ctx: Context = Depends(context)) -> Response:
        name = ctx.require(object_name, "update")
        body = await _body(request)
        async with schema.session(ctx.engine) as db:
            record, event_id = await records.update_record(db, ctx.model, ctx.caller.company_id, name, record_id,
                                                           body, actor=ctx.caller.actor, if_match=_if_match(request))
            await db.commit()
        await _nudge(ctx.caller.company_id, event_id)
        return JSONResponse(record, headers={"ETag": _etag(record["row_version"])})

    @app.delete("/v1/{object_name}/{record_id}")
    async def archive_record(object_name: str, record_id: str, ctx: Context = Depends(context)) -> Response:
        name = ctx.require(object_name, "delete")
        async with schema.session(ctx.engine) as db:
            record, event_id = await records.archive_record(db, ctx.model, ctx.caller.company_id, name, record_id,
                                                            actor=ctx.caller.actor)
            await db.commit()
        await _nudge(ctx.caller.company_id, event_id)
        return JSONResponse(record, headers={"ETag": _etag(record["row_version"])})

    return app
