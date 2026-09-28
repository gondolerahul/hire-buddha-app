"""
ai.memory.assembler — builds a run's memory context from the four domains.

Retrieval goes through MemoryAssemblyService (knowledge, experience,
intelligence, episodic); the AgentLoop reaches it via
``run_memory.assemble_run_memory``.
"""
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# memory_scope → the domains consulted. RUN_SCOPED carries nothing learned from
# other runs (MemoryConfig: "only the current run's data") — just the entity's
# own reference knowledge.
_SCOPE_DOMAINS: Dict[str, list[str]] = {
    "FULL": ["knowledge", "experience", "intelligence", "episodic"],
    "RUN_SCOPED": ["knowledge"],
    "INTELLIGENCE_ONLY": ["intelligence"],
    "KNOWLEDGE_ONLY": ["knowledge", "intelligence"],
}


async def assemble_memory(
    db: AsyncSession,
    company_id: UUID,
    entity_id: UUID,
    user_id: Optional[UUID] = None,
    task_description: str = "",
    memory_scope: str = "FULL",
    runtime_tree: Any = None,
) -> Dict[str, Any]:
    """Assemble an entity's memory for one run.

    Args:
        memory_scope: "FULL", "RUN_SCOPED" (reference knowledge only),
            "INTELLIGENCE_ONLY", "KNOWLEDGE_ONLY", "NONE".

    Returns:
        The non-empty keys among ``__memory__`` (the rendered prompt block),
        ``__intelligence_rules__`` and ``__episodic_memory__``.
    """
    if memory_scope == "NONE":
        return {}

    from src.ai.memory.memory_assembly_service import MemoryAssemblyService

    assembler = MemoryAssemblyService(db, company_id)
    result = await assembler.assemble_runtime_memory(
        entity_id=entity_id,
        user_id=user_id,
        task_description=task_description,
        runtime_tree=runtime_tree,
        include_domains=_SCOPE_DOMAINS.get(memory_scope, _SCOPE_DOMAINS["FULL"]),
    )

    memory_context: Dict[str, Any] = {}
    if result.formatted_prompt:
        memory_context["__memory__"] = result.formatted_prompt
    if result.intelligence_rules:
        memory_context["__intelligence_rules__"] = result.intelligence_rules
    if result.episodic_context:
        memory_context["__episodic_memory__"] = result.episodic_context

    logger.info(
        f"Memory assembly ({memory_scope}): {len(result.knowledge_refs)} knowledge refs, "
        f"{len(result.experience_suggestions)} experience suggestions, "
        f"{len(result.intelligence_rules)} rules, "
        f"{len(result.episodic_context)} episodes"
    )
    return memory_context
