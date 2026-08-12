"""
entity_clone_helpers.py — Shared helpers for entity cloning & remapping.

Extracted from AIService during Phase 6 deduplication to eliminate
the duplicated _clone_fields / _remap_uuid / _remap_entity_refs
logic that existed in both convert_to_template() and clone_template().
"""
import copy
from uuid import UUID

from src.ai.models import HierarchicalEntity


def clone_entity_fields(src: HierarchicalEntity) -> dict:
    """
    Extract clonable fields from a HierarchicalEntity.

    IMPORTANT: JSON/dict fields are deep-copied to prevent shared
    references between template and clone. SQLAlchemy returns the
    same dict object for JSON columns, so without deep-copy, the
    remap step would mutate template data.
    """
    return {
        "name": src.name,
        "display_name": src.display_name,
        "description": src.description,
        "goal": src.goal,
        "type": src.type,
        "version": src.version,
        "status": src.status,
        "tags": copy.deepcopy(src.tags) if src.tags else src.tags,
        "identity": copy.deepcopy(src.identity) if src.identity else src.identity,
        "hierarchy": copy.deepcopy(src.hierarchy) if src.hierarchy else src.hierarchy,
        "logic_gate": copy.deepcopy(src.logic_gate) if src.logic_gate else src.logic_gate,
        "planning": copy.deepcopy(src.planning) if src.planning else src.planning,
        "capabilities": copy.deepcopy(src.capabilities) if src.capabilities else src.capabilities,
        "governance": copy.deepcopy(src.governance) if src.governance else src.governance,
        "io_contract": copy.deepcopy(src.io_contract) if src.io_contract else src.io_contract,
        "observability": copy.deepcopy(src.observability) if src.observability else src.observability,
        "metadata_extensions": copy.deepcopy(src.metadata_extensions) if src.metadata_extensions else src.metadata_extensions,
    }


def remap_entity_refs(
    entity: HierarchicalEntity,
    old_to_new_id: dict[UUID, UUID],
) -> bool:
    """
    Rewrite internal entity_id references in planning steps and
    hierarchy children JSON to point to cloned entity IDs.

    Returns True if any field was modified (caller must persist).
    """
    def _remap_uuid(val: str | None) -> str | None:
        if not val:
            return val
        try:
            old_uuid = UUID(str(val))
        except (ValueError, AttributeError):
            return val
        new_uuid = old_to_new_id.get(old_uuid)
        return str(new_uuid) if new_uuid else val

    modified = False

    # --- planning.static_plan.steps[].target.entity_id ---
    planning = entity.planning
    if planning and isinstance(planning, dict):
        static_plan = planning.get("static_plan")
        if static_plan and isinstance(static_plan, dict):
            for step in static_plan.get("steps", []):
                target = step.get("target") if isinstance(step, dict) else None
                if target and isinstance(target, dict):
                    old_eid = target.get("entity_id")
                    if old_eid:
                        new_eid = _remap_uuid(old_eid)
                        if new_eid != old_eid:
                            target["entity_id"] = new_eid
                            modified = True
            if modified:
                entity.planning = {**planning}

    # --- hierarchy.children[].child_id ---
    hierarchy = entity.hierarchy
    if hierarchy and isinstance(hierarchy, dict):
        hierarchy_modified = False
        for child_ref in hierarchy.get("children", []):
            if isinstance(child_ref, dict):
                old_cid = child_ref.get("child_id")
                if old_cid:
                    new_cid = _remap_uuid(old_cid)
                    if new_cid != old_cid:
                        child_ref["child_id"] = new_cid
                        hierarchy_modified = True
        if hierarchy_modified:
            entity.hierarchy = {**hierarchy}
            modified = True

    return modified
