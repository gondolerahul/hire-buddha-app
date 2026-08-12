"""
Live Client Factory — resolves the correct live streaming client based on task defaults.

For speech_to_speech task type:
  - google/gemini provider → GeminiLiveClient (existing)
  - azure_openai provider   → AzureRealtimeClient (new)

Usage in websocket_handler:
    factory = LiveClientFactory(db=db, company_id=company_id)
    live_client, provider = await factory.create_client(system_instruction, voice_config, ...)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SPEECH_TO_SPEECH_TASK = "speech_to_speech"


class LiveClientFactory:
    """
    Resolves and instantiates the correct live streaming client for speech-to-speech.
    Reads the configured integration from ModelTaskDefaults for task_type='speech_to_speech'.
    """

    def __init__(self, db: AsyncSession, company_id: UUID):
        self.db = db
        self.company_id = company_id

    async def create_client(
        self,
        system_instruction: str,
        voice_config: Optional[Any] = None,
        generation_config: Optional[Dict] = None,
        conversation_history: Optional[list] = None,
    ) -> Tuple[Any, str]:
        """
        Resolve and return a live streaming client based on the
        configured speech_to_speech integration.

        Returns:
            (live_client, provider_name)
            live_client: GeminiLiveClient or AzureRealtimeClient (already connected session)
            provider_name: 'gemini' | 'azure_openai' (for caller to branch on)

        Raises:
            RuntimeError: If no speech_to_speech model is configured.
        """
        from src.config.service import ConfigService
        config_svc = ConfigService(self.db)

        integration, api_key = await config_svc.resolve_model_for_task(
            company_id=self.company_id,
            task_type=SPEECH_TO_SPEECH_TASK,
        )

        if not integration:
            raise RuntimeError(
                "No speech_to_speech model configured. "
                "Please set a default in the AI Model Configuration page."
            )
        if not api_key:
            raise RuntimeError(
                f"No API key found for speech_to_speech model "
                f"'{integration.provider_name}/{integration.model_name}'. "
                "Check Service Integrations."
            )

        provider = (integration.provider_name or "").lower()
        model_name = integration.model_name or ""
        meta = integration.service_metadata or {}

        logger.info(
            f"[LiveClientFactory] speech_to_speech → provider={provider}, model={model_name}"
        )

        if provider in ("azure_openai", "azure"):
            return await self._create_azure_client(
                api_key=api_key,
                model_name=model_name,
                meta=meta,
                system_instruction=system_instruction,
                voice_config=voice_config,
            ), "azure_openai"
        else:
            # Default: Gemini Live (Vertex AI or AI Studio)
            return await self._create_gemini_client(
                api_key=api_key,
                model_name=model_name,
                meta=meta,
                system_instruction=system_instruction,
                voice_config=voice_config,
                generation_config=generation_config,
                conversation_history=conversation_history,
            ), "gemini"

    async def _create_gemini_client(
        self,
        api_key: str,
        model_name: str,
        meta: Dict,
        system_instruction: str,
        voice_config: Optional[Any],
        generation_config: Optional[Dict],
        conversation_history: Optional[list],
    ):
        """
        Instantiate the Gemini Live client.

        Reads 'use_ai_studio' from service_metadata to determine the backend:
          - True: AI Studio / Gemini Developer API (uses API key from integration)
          - False (default): Vertex AI (project_id + region from service_metadata)
        """
        from src.voice.gemini_live import GeminiLiveClient

        use_ai_studio = meta.get("use_ai_studio", False)

        if use_ai_studio:
            logger.info(
                f"[LiveClientFactory] Using AI Studio for model={model_name}"
            )

        return GeminiLiveClient(
            service_metadata=meta,
            system_instruction=system_instruction,
            generation_config=generation_config or {},
            conversation_history=conversation_history or [],
            voice_config=voice_config,
            model_name=model_name,
            use_ai_studio=use_ai_studio,
            api_key=api_key,
        )

    async def _create_azure_client(
        self,
        api_key: str,
        model_name: str,
        meta: Dict,
        system_instruction: str,
        voice_config: Optional[Any],
    ):
        """Instantiate the Azure OpenAI Realtime client."""
        from src.voice.azure_realtime import AzureRealtimeClient, AzureRealtimeConfig

        azure_endpoint = meta.get("azure_endpoint", "")
        if not azure_endpoint:
            raise ValueError("azure_endpoint required in service_metadata for azure_openai provider")

        # Map VoiceConfig voice name to Azure Realtime voice (alloy, echo, fable, onyx, nova, shimmer)
        voice = "alloy"
        if voice_config:
            voice_name = (
                voice_config.voice_name if hasattr(voice_config, "voice_name")
                else voice_config.get("voice_name", "alloy")
            )
            # Best-effort mapping: Gemini voices to Azure voices
            voice = _map_voice_to_azure(voice_name)

        config = AzureRealtimeConfig(
            system_prompt=system_instruction,
            voice=voice,
        )

        client = AzureRealtimeClient(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            model=model_name,
            api_version=meta.get("api_version", "2025-04-01-preview"),
            service_metadata=meta,
        )
        return client, config  # Return both so caller can call client.connect(config)


def _map_voice_to_azure(gemini_voice: str) -> str:
    """
    Map Gemini voice names to Azure OpenAI Realtime voice names.
    Azure voices: alloy, echo, fable, onyx, nova, shimmer, ash, coral, verse, ballad
    """
    mapping = {
        "Aoede": "nova",
        "Puck": "alloy",
        "Charon": "echo",
        "Kore": "shimmer",
        "Fenrir": "onyx",
        "Orbit": "fable",
        "Zephyr": "ash",
        "Leda": "coral",
        "Orus": "verse",
        "Rigel": "echo",
        "Schedar": "alloy",
        "Pulcherrima": "nova",
        "Achird": "shimmer",
        "Sulafat": "ballad",
    }
    return mapping.get(gemini_voice, "alloy")
