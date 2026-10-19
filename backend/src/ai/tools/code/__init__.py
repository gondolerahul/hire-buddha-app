"""Code lanes for agents (Phase 14 WS6 6.3, 6.5; tech spec §11.2; D35).

* ``save_code`` — keep code the agent wrote as **scratch**: stored, listed for
  the business, deleted after a week unless promoted. Nothing loads it at
  runtime.
* ``propose_code_promotion`` — open the pull request that would make scratch
  code an asset (a branch, a test scaffold, checks). A person merges.
* ``propose_app_change`` — change an app's files: a branch
  ``hb/<run>-<slug>`` and a pull request with checks; once a person merges
  it, the app is built. The agent never merges, publishes or deploys.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from src.ai.tools.automation.common import caller_of
from src.ai.tools.base import Tool, ToolOutput, ToolParams

MAX_FILES = 50


def _files(files: Dict[str, str]) -> Dict[str, bytes]:
    return {path: content.encode() for path, content in files.items()}


class SaveCodeParams(ToolParams):
    name: str = Field(..., description="A short name, e.g. 'invoice_parser'.")
    kind: str = Field("script", description="script | tool | skill_script | app")
    files: Dict[str, str] = Field(..., description="Path → content, e.g. {'parser.py': '...'}.")
    description: Optional[str] = Field(None, description="What it does and how to run it.")


class SaveCodeTool(Tool):
    name = "save_code"
    description = ("Keep code you wrote as scratch for the business to see and, if useful, promote. Scratch is "
                   "deleted after a week unless a person promotes it; it is never loaded at runtime.")
    category = "code"
    Params = SaveCodeParams

    async def execute(self, params: SaveCodeParams, ctx: Dict[str, Any]) -> ToolOutput:
        from src.code_lanes import service

        caller, refused = caller_of(ctx)
        if refused:
            return refused
        if len(params.files) > MAX_FILES:
            return ToolOutput.failed(f"at most {MAX_FILES} files", code="invalid")
        try:
            item = await service.register_scratch(caller.company_id, kind=params.kind, name=params.name,
                                                  files=_files(params.files), description=params.description,
                                                  run_id=caller.run_id)
        except service.CodeProblem as error:
            return ToolOutput.failed(str(error), code="refused")
        return ToolOutput(output={"code_item_id": item["id"], "lane": "scratch",
                                  "kept_until": item["retention_until"]})


class PromoteParams(ToolParams):
    code_item_id: str = Field(..., description="The scratch item save_code returned.")
    repo_id: str = Field(..., description="The repository it should live in (list them with the business).")
    path: Optional[str] = Field(None, description="Folder in the repository; default <kind>s/<name>.")


class ProposeCodePromotionTool(Tool):
    name = "propose_code_promotion"
    description = ("Open a pull request that would make scratch code a reviewed asset of the business: a branch "
                   "with the files and a test scaffold; checks run on it. A person approves and merges it.")
    category = "code"
    Params = PromoteParams

    async def execute(self, params: PromoteParams, ctx: Dict[str, Any]) -> ToolOutput:
        from src.code_lanes import service

        caller, refused = caller_of(ctx)
        if refused:
            return refused
        try:
            review = await service.promote(caller.company_id, params.code_item_id, repo_id=params.repo_id,
                                           run_id=caller.run_id, path=params.path)
        except (service.CodeProblem, ValueError) as error:
            return ToolOutput.failed(str(error), code="refused")
        return ToolOutput(output={"review_id": review["id"], "pull_request": review["number"], "url": review["url"],
                                  "note": "checks are running; a person decides whether to merge"})


class AppChangeParams(ToolParams):
    app_id: str = Field(..., description="The app to change.")
    title: str = Field(..., description="What the change does, as a pull request title.")
    files: Dict[str, str] = Field(..., description="Path (in the app) → new content.")
    delete: List[str] = Field(default_factory=list, description="Paths (in the app) to remove.")
    body: str = Field("", description="Why, for the person who reviews it.")


class ProposeAppChangeTool(Tool):
    name = "propose_app_change"
    description = ("Change an app's code: a branch and a pull request with checks. The app is rebuilt only "
                   "after a person merges it; a preview of the change runs while it is open.")
    category = "code"
    Params = AppChangeParams

    async def execute(self, params: AppChangeParams, ctx: Dict[str, Any]) -> ToolOutput:
        from src.apps.db import app_session
        from src.apps.models import App
        from src.code_lanes import service

        caller, refused = caller_of(ctx)
        if refused:
            return refused
        if len(params.files) + len(params.delete) > MAX_FILES:
            return ToolOutput.failed(f"at most {MAX_FILES} files in one change", code="invalid")
        try:
            async with app_session(caller.company_id) as db:
                app = await db.get(App, service._uuid(params.app_id))  # noqa: SLF001
            if app is None or app.company_id != caller.company_id or app.repo_id is None:
                return ToolOutput.failed("no such app", code="not_found")
            prefix = f"{app.repo_path}/" if app.repo_path else ""
            review = await service.open_change(
                caller.company_id, repo_id=app.repo_id, app_id=app.id, run_id=caller.run_id,
                branch=f"hb/{caller.run_id.hex[:8]}-{service.slug(params.title, length=30)}",
                files={prefix + p: c for p, c in _files(params.files).items()},
                delete_paths=[prefix + p for p in params.delete], title=params.title,
                body=params.body + f"\n\nProposed by run `{caller.run_id}` in HireBuddha.")
        except Exception as error:  # noqa: BLE001 - shown to the agent
            return ToolOutput.failed(str(error), code="refused")
        return ToolOutput(output={"review_id": review["id"], "pull_request": review["number"], "url": review["url"],
                                  "note": "checks and a preview are on their way; a person merges"})


CODE_TOOLS = (SaveCodeTool, ProposeCodePromotionTool, ProposeAppChangeTool)
