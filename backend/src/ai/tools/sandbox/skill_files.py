"""Skill files — a run's version assets, written into the tenant workspace (R2 §7).

A run sees the assets of its own pinned version and of its ancestor runs'
versions (D14), so a SKILL's scripts reach the ACTIONs it delegates to. Each
version's files land in ``<tenant workspace>/.skills/<slug>/<version>/``,
which the sandbox tools run in (host mode) or bind-mount at the same path
(container mode). A ``.content-hash`` marker makes a repeat a no-op without
reading a single body; only a missing or stale tree is (re)written, into a
temporary directory first so a parallel step never sees half a tree.

Runs in the worker. The API process stores bodies and never writes or runs
them (the ``SandboxedSynthesizedTool`` invariant).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from sqlalchemy import select

from src.ai.tools.sandbox.workspace import tenant_workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

__all__ = [
    "SKILLS_DIR", "SKILL_FILES_TOKEN", "SkillFiles", "fill_skill_files", "materialise",
    "render_skill_files", "run_skill_files", "slug",
]

SKILLS_DIR = ".skills"
# In a prompt, the nearest version's files folder (the first one listed).
SKILL_FILES_TOKEN = "$SKILL_FILES"
MARKER = ".content-hash"
_MAX_ANCESTORS = 16
_LISTED_PER_VERSION = 40
_RUNNABLE = (".py", ".js", ".mjs", ".ts", ".sh")


@dataclass
class SkillFiles:
    """One version's files as the step prompt names them."""
    entity_name: str
    version_number: int
    root: str                                   # relative to the workspace, POSIX
    paths: list[str] = field(default_factory=list)


def slug(name: str) -> str:
    """A directory name for an entity: lower-case letters, digits and ``-``."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:60] or "skill"


def _read_marker(root: str) -> Optional[str]:
    try:
        with open(os.path.join(root, MARKER), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def materialise(company_id: Any, root_rel: str, digest: str, files: dict[str, str]) -> str:
    """Write ``files`` under ``<workspace>/<root_rel>``; a no-op when its marker is ``digest``."""
    workspace = tenant_workspace(company_id)
    root = os.path.join(workspace, *root_rel.split("/"))
    if _read_marker(root) == digest:
        return root
    from src.ai.governance.entity_assets import valid_asset_path

    tmp = f"{root}.tmp-{uuid.uuid4().hex[:8]}"
    for path, body in files.items():
        # Checked again here: a row written by a seed or a script never met put_asset.
        target = os.path.join(tmp, *valid_asset_path(path).split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(body)
    with open(os.path.join(tmp, MARKER), "w", encoding="utf-8") as f:
        f.write(digest)
    os.makedirs(os.path.dirname(root), exist_ok=True)
    try:
        if os.path.isdir(root):
            if _read_marker(root) == digest:    # another step finished first
                shutil.rmtree(tmp, ignore_errors=True)
                return root
            shutil.rmtree(root)                 # a draft whose files changed
        os.rename(tmp, root)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        if _read_marker(root) != digest:
            raise
    return root


async def _version_chain(db: "AsyncSession", run: Any) -> list[UUID]:
    """The run's pinned version, then each ancestor run's, nearest first, distinct."""
    from src.ai.orm.execution import ExecutionRun

    chain: list[UUID] = []
    version_id, parent_id = getattr(run, "entity_version_id", None), getattr(run, "parent_run_id", None)
    for _ in range(_MAX_ANCESTORS):
        if version_id and version_id not in chain:
            chain.append(version_id)
        if not parent_id:
            break
        row = (await db.execute(
            select(ExecutionRun.entity_version_id, ExecutionRun.parent_run_id).where(ExecutionRun.id == parent_id)
        )).first()
        if row is None:
            break
        version_id, parent_id = row
    return chain


async def run_skill_files(db: "AsyncSession", run: Any) -> list[SkillFiles]:
    """Materialise the run's skill files (own version and ancestors') and name them.

    Best-effort per version: a version that cannot be written is logged and
    left out of the list rather than failing the step.
    """
    from src.ai.orm.versions import EntityAsset, EntityVersion

    found: list[SkillFiles] = []
    for version_id in await _version_chain(db, run):
        paths = list((await db.execute(
            select(EntityAsset.path).where(EntityAsset.entity_version_id == version_id).order_by(EntityAsset.path)
        )).scalars())
        if not paths:
            continue
        version = (await db.execute(select(
            EntityVersion.version_number, EntityVersion.content_hash, EntityVersion.snapshot,
        ).where(EntityVersion.id == version_id))).one()
        name = str((version.snapshot or {}).get("name") or "skill")
        root_rel = f"{SKILLS_DIR}/{slug(name)}/{version.version_number}"
        try:
            root = os.path.join(tenant_workspace(run.company_id), *root_rel.split("/"))
            if _read_marker(root) != version.content_hash:
                bodies = dict((await db.execute(
                    select(EntityAsset.path, EntityAsset.body).where(EntityAsset.entity_version_id == version_id)
                )).tuples().all())
                materialise(run.company_id, root_rel, version.content_hash, bodies)
        except Exception:                                                   # noqa: BLE001
            logger.warning("skill files of version %s could not be written", version_id, exc_info=True)
            continue
        found.append(SkillFiles(entity_name=name, version_number=version.version_number,
                                root=root_rel, paths=paths))
    return found


def fill_skill_files(text: str, skills: list[SkillFiles]) -> str:
    """``$SKILL_FILES`` in a prompt → the nearest version's files folder.

    A seed or author names a script exactly (``$SKILL_FILES/office/validate.py``)
    without knowing the version number. Unchanged when the run has no files.
    """
    return text.replace(SKILL_FILES_TOKEN, skills[0].root) if skills else text


def render_skill_files(skills: list[SkillFiles]) -> Optional[str]:
    """The step prompt's section naming the files (scripts first, a capped list)."""
    if not skills:
        return None
    lines = [
        "These files are already in your workspace — the working directory of `sandbox_code` "
        "and `terminal`. Run or read them by these paths; do not retype them.",
    ]
    for s in skills:
        ordered = sorted(s.paths, key=lambda p: (not p.endswith(_RUNNABLE), p))
        lines.append(f"- {s.entity_name} v{s.version_number}: `{s.root}/`")
        lines.extend(f"  - `{s.root}/{p}`" for p in ordered[:_LISTED_PER_VERSION])
        if len(ordered) > _LISTED_PER_VERSION:
            lines.append(f"  - … and {len(ordered) - _LISTED_PER_VERSION} more (`ls -R {s.root}`)")
    return "\n".join(lines)
