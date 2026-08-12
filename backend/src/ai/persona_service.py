"""
PersonaService — P2.2

Resolves and applies the standardized AgentPersona schema for any HierarchicalEntity.

Handles both the new AgentPersona format and legacy identity formats:
  - New format:  entity.identity = {"name": ..., "voice": {...}, "personality": {...}, ...}
  - Legacy 1:    entity.identity = {"system_prompt": ..., "behavioral_constraints": [...]}
  - Legacy 2:    entity.identity = {"persona": {"system_prompt": ...}}
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.ai.schemas import AgentPersona, VoiceConfig, PersonalityMatrix

if TYPE_CHECKING:
    from src.ai.models import HierarchicalEntity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System Prompt Builder (P2.5)
# ---------------------------------------------------------------------------

def build_system_prompt_from_persona(persona: AgentPersona) -> str:
    """
    Dynamically inject personality dimensions into the system prompt.

    Called by:
      - ai/worker.py → build_sandwich_prompt() when entity has an AgentPersona
      - streaming/agent_loader.py → _build_system_instruction()
    """
    personality = persona.personality
    parts: list[str] = []

    # Core identity block — always include both system_prompt and bio.
    # The bio often contains important behavioral instructions (language switching,
    # conversational style) that complement the system_prompt.
    if persona.system_prompt:
        parts.append(persona.system_prompt)
    else:
        parts.append(f"You are {persona.name}, a {persona.role}.")

    if persona.bio:
        parts.append(f"## Agent Bio & Behavioral Guidelines\n{persona.bio}")

    # Personality dimensions block
    empathy_desc = (
        "Show high empathy — acknowledge emotions before providing information."
        if personality.empathy_level > 0.6
        else "Maintain professional empathy while staying solution-focused."
    )
    humor_desc = (
        "Use light humor when appropriate to build rapport."
        if personality.humor_level > 0.4
        else "Maintain a professional tone without humor."
    )
    verbosity_desc = {
        "concise":  "Keep responses brief and to the point (1-3 sentences).",
        "moderate": "Provide clear, complete responses with enough detail.",
        "verbose":  "Provide thorough, detailed explanations.",
    }.get(personality.verbosity, "Keep responses clear and direct.")

    parts.append(f"""
## Personality Profile
- **Tone**: {personality.tone}
- **Communication Style**: {personality.formality} register; {verbosity_desc}
- **Empathy**: {empathy_desc}
- **Humor**: {humor_desc}
""".strip())

    # Behavioral constraints
    if persona.behavioral_constraints:
        constraints_text = "\n".join(f"- {c}" for c in persona.behavioral_constraints)
        parts.append(f"## Behavioral Constraints\n{constraints_text}")

    # Dynamic hooks
    if persona.greeting_template:
        parts.append(f"## Opening\nUse this greeting: {persona.greeting_template}")
    if persona.escalation_message:
        parts.append(f"## Escalation\nWhen escalating to human: {persona.escalation_message}")
    if persona.closing_message:
        parts.append(f"## Closing\nEnd with: {persona.closing_message}")

    # Few-shot examples
    if persona.few_shot_examples:
        examples_text = "\n".join(
            f"Scenario: {ex.scenario}\nIdeal response: {ex.ideal_response}"
            for ex in persona.few_shot_examples
        )
        parts.append(f"## Examples\n{examples_text}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# PersonaService
# ---------------------------------------------------------------------------

class PersonaService:
    """
    Loads and applies the AgentPersona for a given HierarchicalEntity.

    Handles graceful fallback from AgentPersona → legacy Persona → minimal defaults.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_persona(self, entity_id: UUID) -> Optional[AgentPersona]:
        """
        Load and parse the standardized AgentPersona for an entity.
        Returns None if the entity doesn't exist or has no identity configured.
        """
        from src.ai.models import HierarchicalEntity
        result = await self.db.execute(
            select(HierarchicalEntity).where(HierarchicalEntity.id == entity_id)
        )
        entity = result.scalar_one_or_none()
        if not entity:
            return None
        return self._parse_persona(entity.identity)

    def _parse_persona(self, identity: Optional[dict]) -> Optional[AgentPersona]:
        """
        Parse identity dict into AgentPersona — handles all legacy formats.

        Format detection:
          - New (AgentPersona):  Has "name" key or "personality" key
          - Legacy 1:            Has "system_prompt" key directly
          - Legacy 2:            Has "persona" key wrapping a system_prompt dict
        """
        if not identity:
            return None

        try:
            # ── New AgentPersona format ───────────────────────────────
            if "name" in identity or "personality" in identity or "voice" in identity:
                return AgentPersona(**identity)

            # ── Legacy format 2: {"persona": {"system_prompt": ...}} ─
            if "persona" in identity and isinstance(identity["persona"], dict):
                inner = identity["persona"]
                return AgentPersona(
                    system_prompt=inner.get("system_prompt", ""),
                    behavioral_constraints=inner.get("behavioral_constraints", []),
                    name=inner.get("name", "AI Assistant"),
                    role=inner.get("role", "AI Assistant"),
                )

            # ── Legacy format 1: {"system_prompt": "...", ...} ────────
            if "system_prompt" in identity:
                return AgentPersona(
                    system_prompt=identity.get("system_prompt", ""),
                    behavioral_constraints=identity.get("behavioral_constraints", []),
                    name=identity.get("role", "AI Assistant"),
                    role=identity.get("role", "AI Assistant"),
                )

        except Exception as e:
            logger.warning(f"Could not parse persona from identity: {e}")

        return None

    async def get_voice_config(self, entity_id: UUID) -> VoiceConfig:
        """
        Convenience: returns the VoiceConfig from the persona, or defaults.
        Used by AgentContextLoader to pass voice params to GeminiLiveClient.
        """
        persona = await self.get_persona(entity_id)
        return persona.voice if persona else VoiceConfig()

    async def build_system_prompt(
        self,
        entity_id: UUID,
        context: Optional[dict] = None,
    ) -> str:
        """
        Build a fully-injected system prompt from persona + optional runtime context.

        Falls back to a minimal default prompt if no persona is configured.
        """
        persona = await self.get_persona(entity_id)
        if not persona:
            return "You are a helpful AI assistant."
        prompt = build_system_prompt_from_persona(persona)
        # Runtime context injection (e.g. {customer_name}, {account_id})
        if context:
            for key, value in context.items():
                prompt = prompt.replace(f"{{{key}}}", str(value))
        return prompt

    async def get_persona_from_entity(
        self, entity: "HierarchicalEntity"
    ) -> Optional[AgentPersona]:
        """Parse persona directly from an already-loaded entity object (no extra DB query)."""
        return self._parse_persona(entity.identity)
