"""schemas/persona.py — Persona / agent identity DTOs.

The standardized persona schema replaces the loosely-typed JSON blob in
HierarchicalEntity.identity.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, field_validator

__all__ = [
    "PersonaExample",
    "VoiceConfig",
    "PersonalityMatrix",
    "AgentPersona",
    "Persona",
]


class PersonaExample(BaseModel):
    scenario: str = ""
    ideal_response: str = ""
    # Legacy fields accepted from frontend (mapped to scenario/ideal_response)
    input: Optional[str] = None
    output: Optional[str] = None

    @field_validator("scenario", mode="before")
    @classmethod
    def _scenario_from_input(cls, v, info):
        """Accept legacy 'input' field as scenario when scenario is empty."""
        if v:
            return v
        data = info.data if hasattr(info, "data") else {}
        return data.get("input") or ""

    @field_validator("ideal_response", mode="before")
    @classmethod
    def _ideal_from_output(cls, v, info):
        """Accept legacy 'output' field as ideal_response when ideal_response is empty."""
        if v:
            return v
        data = info.data if hasattr(info, "data") else {}
        return data.get("output") or ""


class VoiceConfig(BaseModel):
    """Voice identity parameters for Gemini Live API.

    Applied when the agent is used in a real-time voice/streaming session.
    """
    voice_name: str = "Aoede"
    language_code: str = "en-US"   # BCP-47 language tag
    speaking_rate: float = 1.0     # 0.25 – 4.0  (1.0 = normal)
    pitch: float = 0.0             # -20.0 to +20.0 semitones
    custom_voice_id: Optional[str] = None


class PersonalityMatrix(BaseModel):
    """Behavioural fingerprint injected into the system prompt at runtime.

    Each dimension controls a specific tonal / stylistic aspect.
    """
    tone: str = "professional"        # friendly | formal | empathetic | assertive
    verbosity: str = "concise"        # concise | moderate | verbose
    empathy_level: float = 0.7        # 0.0 (robotic) → 1.0 (highly empathetic)
    humor_level: float = 0.2          # 0.0 (none) → 1.0 (frequent humor)
    formality: str = "semi-formal"    # formal | semi-formal | casual
    decision_confidence: float = 0.8  # Confidence threshold before escalating to human


class AgentPersona(BaseModel):
    """Canonical, standardized persona for HierarchicalEntity.identity.

    Replaces the old free-form JSON with a typed, validated structure.
    """
    # Core identity (name removed — use top-level entity.name instead)
    role: str = "AI Assistant"
    bio: Optional[str] = None

    # Visual identity (for UI and future multi-modal interactions)
    profile_image_url: Optional[str] = None
    profile_image_thumbnail_url: Optional[str] = None

    # Behavioral fingerprint
    personality: PersonalityMatrix = PersonalityMatrix()

    # Voice identity (for Gemini Live sessions)
    voice: VoiceConfig = VoiceConfig()

    # Prompt engineering
    system_prompt: str = ""
    behavioral_constraints: List[str] = []
    few_shot_examples: List[PersonaExample] = []

    # Dynamic injection hooks
    greeting_template: Optional[str] = None    # First utterance template
    escalation_message: Optional[str] = None   # What to say when escalating to human
    closing_message: Optional[str] = None      # End-of-call closing statement


class Persona(BaseModel):
    """Legacy persona model — kept for backward compatibility. Prefer AgentPersona."""
    system_prompt: str
    examples: List[PersonaExample] = []
    behavioral_constraints: List[str] = []
    few_shot_examples: List[Dict[str, str]] = []
