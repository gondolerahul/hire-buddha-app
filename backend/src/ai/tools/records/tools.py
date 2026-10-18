"""The record tools (Phase 14 WS4 4.8; tech spec §7.11): read the data
structure; find, read, create, update, link and archive the business's
records; run reports; propose schema changes — each through the Data API as
the run.

A run's tools are declared for its business: the ``object`` argument lists
only the objects the agent's ``capabilities.records`` lets it use with that
tool, and the description lists their fields from the active blueprint, so an
object added and approved shows up in the next run without a restart. A tool
the agent could do nothing with here is not offered.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field

from src.ai.tools.base import Tool, ToolOutput, ToolParams
from src.ai.tools.records.common import (RecordsView, describe_objects, failed, field_line, records_view,
                                         run_client)

OPERATORS = Literal["eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "contains", "starts_with", "is_null"]
FILTER_HELP = ("Values are text: numbers as 12.5, true/false, lists for in/nin comma-separated, dates ISO-8601 "
               "or relative (now, now-7d, today+1w; UTC); is_null takes true or false.")


class RecordFilter(ToolParams):
    field: str = Field(..., description="A field of the object, or created_at / updated_at / created_by.")
    op: OPERATORS = Field("eq", description="How the field compares to value.")
    value: Optional[str] = Field(None, description=FILTER_HELP)


class RecordTool(Tool):
    """A tool over the business's records; ``operation`` is what it needs on an object."""
    category = "records"
    operation: str = "read"

    async def tailoring(self, company_id: Any, entity: Any, shared: Dict[str, Any]) -> Any:
        return await records_view(company_id, entity, shared)

    def objects_for(self, view: RecordsView) -> List[str]:
        return view.names(self.operation)

    def function_schema_for(self, tailoring: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(tailoring, RecordsView):
            return None
        names = self.objects_for(tailoring)
        if not names:
            return None
        schema = copy.deepcopy(self.get_function_schema())
        props = schema["parameters"]["properties"]
        if "object" in props:
            props["object"]["enum"] = names
        schema["description"] = f"{self.description}\n\nObjects (blueprint v{tailoring.version}):\n" \
                                f"{describe_objects(tailoring, names)}"
        return schema


def _filters(items: Optional[List[RecordFilter]]) -> List[tuple]:
    return [(f.field, f.op, f.value) for f in items or []]


# ── Read ───────────────────────────────────────────────────────────────────

class FindRecordsParams(ToolParams):
    object: str = Field(..., description="The object to search, e.g. contact.")
    filters: List[RecordFilter] = Field(default_factory=list, description="All must hold.")
    sort: Optional[str] = Field(None, description="Field names, comma-separated; '-' first for descending, "
                                                  "e.g. -created_at.")
    fields: List[str] = Field(default_factory=list, description="Only these fields (id and row_version always).")
    limit: int = Field(20, ge=1, le=100, description="At most this many records.")
    after: Optional[str] = Field(None, description="The 'next' cursor of a previous call, for the next page.")


class FindRecordsTool(RecordTool):
    name = "find_records"
    description = ("Find the business's records of one object with filters, sorted, a page at a time. "
                   "Returns the records (with id and row_version) and a 'next' cursor when there are more.")
    Params = FindRecordsParams

    async def execute(self, params: FindRecordsParams, ctx: Dict[str, Any]) -> ToolOutput:
        async with run_client(ctx) as (records, refused):
            if refused:
                return refused
            try:
                page = await records.client.list(params.object, filters=_filters(params.filters), sort=params.sort,
                                                 fields=params.fields or None, size=params.limit, after=params.after)
            except Exception as error:  # noqa: BLE001 - a refusal is the model's to read
                return failed(error)
        return ToolOutput(output=page)


class GetRecordParams(ToolParams):
    object: str = Field(..., description="The record's object.")
    id: str = Field(..., description="The record's id.")


class GetRecordTool(RecordTool):
    name = "get_record"
    description = "Read one record by id, with its row_version (needed to update it)."
    Params = GetRecordParams

    async def execute(self, params: GetRecordParams, ctx: Dict[str, Any]) -> ToolOutput:
        async with run_client(ctx) as (records, refused):
            if refused:
                return refused
            try:
                return ToolOutput(output=await records.client.get(params.object, params.id))
            except Exception as error:  # noqa: BLE001
                return failed(error)


class DescribeSchemaParams(ToolParams):
    object: Optional[str] = Field(None, description="One object; default: every object you may use.")


class DescribeSchemaTool(RecordTool):
    name = "describe_schema"
    description = ("The business's objects you may use, with every field (type, choices, links, required) "
                   "and what you may do with each.")
    Params = DescribeSchemaParams

    def objects_for(self, view: RecordsView) -> List[str]:
        return list(view.objects)

    async def execute(self, params: DescribeSchemaParams, ctx: Dict[str, Any]) -> ToolOutput:
        async with run_client(ctx) as (records, refused):
            if refused:
                return refused
            view = await records_view(records.caller.company_id, records.entity, {})
        if view is None:
            return ToolOutput.failed("the business has no records yet", code="records_unavailable")
        names = [params.object] if params.object else list(view.objects)
        unknown = [n for n in names if n not in view.objects]
        if unknown:
            return ToolOutput.failed(f"no object {unknown[0]!r} you may use; yours: {', '.join(view.objects)}",
                                     code="unknown_object")
        return ToolOutput(output={"blueprint_version": view.version, "reports": view.reports,
                                  "schema_changes": "propose" if view.schema_changes else "none",
                                  "objects": {n: {"label": view.objects[n]["label"],
                                                  "description": view.objects[n]["description"],
                                                  "you_may": sorted(view.operations[n]),
                                                  "fields": [field_line(f, s) for f, s in
                                                             view.objects[n]["fields"].items()]}
                                              for n in names}})


# ── Write ──────────────────────────────────────────────────────────────────

class CreateRecordParams(ToolParams):
    object: str = Field(..., description="The object to create a record of.")
    values: Dict[str, Any] = Field(..., description="Field → value; a link is the linked record's id; money "
                                                    "fields take <field>_currency too.")


class CreateRecordTool(RecordTool):
    name = "create_record"
    description = ("Create a record. The same create repeated in one run makes one record. Returns the record "
                   "with its id and row_version.")
    operation = "create"
    Params = CreateRecordParams

    async def execute(self, params: CreateRecordParams, ctx: Dict[str, Any]) -> ToolOutput:
        async with run_client(ctx) as (records, refused):
            if refused:
                return refused
            same = json.dumps([params.object, params.values], sort_keys=True, default=str)
            key = f"run:{records.caller.run_id}:{hashlib.sha256(same.encode()).hexdigest()[:32]}"
            try:
                return ToolOutput(output=await records.client.create(params.object, params.values,
                                                                     idempotency_key=key))
            except Exception as error:  # noqa: BLE001
                return failed(error)


class UpdateRecordParams(ToolParams):
    object: str = Field(..., description="The record's object.")
    id: str = Field(..., description="The record's id.")
    values: Dict[str, Any] = Field(..., description="Only the fields to change.")
    row_version: Optional[int] = Field(None, description=(
        "The row_version you read; the update is refused (stale) if the record changed since — read it "
        "again and decide. Omit to update the record as it is now."))


class UpdateRecordTool(RecordTool):
    name = "update_record"
    description = "Change fields of a record. Returns the record with its new row_version."
    operation = "update"
    Params = UpdateRecordParams

    async def execute(self, params: UpdateRecordParams, ctx: Dict[str, Any]) -> ToolOutput:
        async with run_client(ctx) as (records, refused):
            if refused:
                return refused
            try:
                version = params.row_version
                if version is None:
                    version = (await records.client.get(params.object, params.id))["row_version"]
                return ToolOutput(output=await records.client.update(params.object, params.id, params.values,
                                                                     row_version=version))
            except Exception as error:  # noqa: BLE001
                return failed(error)


class ArchiveRecordParams(ToolParams):
    object: str = Field(..., description="The record's object.")
    id: str = Field(..., description="The record's id.")


class ArchiveRecordTool(RecordTool):
    name = "archive_record"
    description = ("Archive a record: it is hidden at once and kept (nothing is deleted). Use it when a record "
                   "is wrong or no longer wanted.")
    operation = "delete"
    Params = ArchiveRecordParams

    async def execute(self, params: ArchiveRecordParams, ctx: Dict[str, Any]) -> ToolOutput:
        async with run_client(ctx) as (records, refused):
            if refused:
                return refused
            try:
                return ToolOutput(output=await records.client.archive(params.object, params.id))
            except Exception as error:  # noqa: BLE001
                return failed(error)


class LinkRecordsParams(ToolParams):
    object: str = Field(..., description="The record's object, e.g. order.")
    id: str = Field(..., description="The record's id.")
    relation: str = Field(..., description=(
        "A link field of the object (e.g. account: set it with 'to'), or another object whose records link to "
        "this one (e.g. shipment: link them with 'ids'; name the field as shipment.order if there are two)."))
    to: Optional[str] = Field(None, description="For a link field: the linked record's id; omit to clear it.")
    ids: List[str] = Field(default_factory=list, description="For another object: its records to link to this one.")
    unlink: List[str] = Field(default_factory=list, description="For another object: its records to unlink.")
    read: bool = Field(False, description="Only read what is linked now (changes nothing).")


class LinkRecordsTool(RecordTool):
    name = "link_records"
    description = ("Read or change links between records: an order's account, or an order's shipments. "
                   "Returns the linked records, or the records changed.")
    Params = LinkRecordsParams

    def objects_for(self, view: RecordsView) -> List[str]:
        return view.names("read") if view.names("update") else []

    async def execute(self, params: LinkRecordsParams, ctx: Dict[str, Any]) -> ToolOutput:
        async with run_client(ctx) as (records, refused):
            if refused:
                return refused
            try:
                if params.read:
                    return ToolOutput(output=await records.client.linked(params.object, params.id, params.relation))
                return ToolOutput(output=await records.client.link(params.object, params.id, params.relation,
                                                                   to=params.to, ids=params.ids,
                                                                   unlink=params.unlink))
            except Exception as error:  # noqa: BLE001
                return failed(error)


# ── Reports and schema ─────────────────────────────────────────────────────

class Measure(ToolParams):
    fn: Literal["count", "sum", "avg", "min", "max"] = "count"
    field: Optional[str] = Field(None, description="The number field (not for count).")


class Bucket(ToolParams):
    field: str = Field("created_at", description="A date or date-time field.")
    unit: Literal["hour", "day", "week", "month", "quarter", "year"] = "day"


class RunReportParams(ToolParams):
    object: str = Field(..., description="The object to report on.")
    group_by: List[str] = Field(default_factory=list, description="Fields to group by.")
    measures: List[Measure] = Field(default_factory=list, description="Default: count.")
    filters: List[RecordFilter] = Field(default_factory=list, description="Only records where all hold.")
    bucket: Optional[Bucket] = Field(None, description="Group by time too.")


class RunReportTool(RecordTool):
    name = "run_report"
    description = ("Count, sum, average, min or max records of an object, grouped by fields and/or time. Use it "
                   "for numbers (how many leads this week) instead of reading every record.")
    Params = RunReportParams

    def objects_for(self, view: RecordsView) -> List[str]:
        return view.names("read") if view.reports else []

    async def execute(self, params: RunReportParams, ctx: Dict[str, Any]) -> ToolOutput:
        async with run_client(ctx) as (records, refused):
            if refused:
                return refused
            try:
                return ToolOutput(output=await records.client.report(
                    params.object, group_by=params.group_by,
                    measures=[m.model_dump(exclude_none=True) for m in params.measures],
                    filters=_filters(params.filters), bucket=params.bucket.model_dump() if params.bucket else None))
            except Exception as error:  # noqa: BLE001
                return failed(error)


class ProposeSchemaChangeParams(ToolParams):
    reason: str = Field(..., description="Why the business needs it, in a sentence the owner reads.")
    operations: List[Dict[str, Any]] = Field(..., description=(
        "The changes, e.g. {\"op\": \"add_object\", \"object\": \"shipment\", \"definition\": {\"label\": "
        "\"Shipment\", \"fields\": {\"carrier\": {\"type\": \"text\"}, \"order\": {\"type\": \"ref\", \"to\": "
        "\"order\"}}}}; {\"op\": \"add_field\", \"object\": \"contact\", \"field\": \"x_tier\", \"definition\": "
        "{\"type\": \"enum\", \"values\": [\"gold\", \"silver\"]}}. A field added to a standard object (account, "
        "contact, activity, consent) starts with x_. Also add_index, add_unique, widen, make_required, rename, "
        "archive. Field types: text, long_text, integer, decimal, money, boolean, date, datetime, enum, email, "
        "phone, url, ref, file."))
    dry_run: bool = Field(False, description="Only check it and show what it would affect.")


class ProposeSchemaChangeTool(RecordTool):
    name = "propose_schema_change"
    description = ("Propose a change to the business's data structure: a new object or field, an index. A "
                   "person approves it (unless the owner lets simple additions through); once applied, the "
                   "next runs see it. Returns the change with its status, checks and impact.")
    Params = ProposeSchemaChangeParams

    def function_schema_for(self, tailoring: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(tailoring, RecordsView) or not tailoring.schema_changes:
            return None
        schema = copy.deepcopy(self.get_function_schema())
        if tailoring.objects:
            schema["description"] = (f"{self.description}\n\nObjects you use now (blueprint "
                                     f"v{tailoring.version}):\n{describe_objects(tailoring, list(tailoring.objects))}")
        return schema

    async def execute(self, params: ProposeSchemaChangeParams, ctx: Dict[str, Any]) -> ToolOutput:
        async with run_client(ctx) as (records, refused):
            if refused:
                return refused
            try:
                return ToolOutput(output=await records.client.propose_change(
                    params.operations, reason=params.reason, dry_run=params.dry_run))
            except Exception as error:  # noqa: BLE001
                return failed(error)


RECORD_TOOLS = (DescribeSchemaTool, FindRecordsTool, GetRecordTool, CreateRecordTool, UpdateRecordTool,
                LinkRecordsTool, ArchiveRecordTool, RunReportTool, ProposeSchemaChangeTool)
