"""
Agent Context Loader for streaming sessions.

Loads agent configuration and conversation history for each session.
Integrates with existing HierarchicalEntity system.
Supports campaign contact data injection via {{variable}} templates.
"""
import logging
from uuid import UUID
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.ai.models import HierarchicalEntity
from src.voice.models import ConversationHistory
from src.config.models import IntegrationRegistry
from src.common.config import settings
from src.common.security import decrypt_api_key

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent base-context cache. The DB-heavy part of agent loading (persona,
# tools, context-source file extraction, API key) took ~4.5-5s cold and sits
# on the call-setup hot path; every call in a campaign shares one agent, so
# cache it. Per-call parts (conversation history, contact injection) are
# never cached. Agent edits propagate within the TTL.
# ---------------------------------------------------------------------------
try:
    from cachetools import TTLCache
    _AGENT_BASE_CACHE: Optional[TTLCache] = (
        TTLCache(maxsize=128, ttl=settings.VOICE_AGENT_CACHE_TTL_SECONDS)
        if settings.VOICE_AGENT_CACHE_TTL_SECONDS > 0
        else None
    )
except ImportError:
    _AGENT_BASE_CACHE = None


def bust_agent_cache(agent_id: Optional[UUID] = None) -> None:
    """Drop cached agent base contexts (all, or one agent's)."""
    if _AGENT_BASE_CACHE is None:
        return
    if agent_id is None:
        _AGENT_BASE_CACHE.clear()
        return
    for key in [k for k in list(_AGENT_BASE_CACHE.keys()) if k[0] == agent_id]:
        _AGENT_BASE_CACHE.pop(key, None)


class AgentContext:
    """Container for agent configuration and context."""
    
    def __init__(
        self,
        agent_id: UUID,
        system_instruction: str,
        conversation_history: List[Dict[str, Any]],
        llm_config: Dict[str, Any],
        capabilities: Dict[str, Any],
        tools: Optional[List] = None,
        api_key: Optional[str] = None,
        voice_config: Optional[Any] = None,   # VoiceConfig from AgentPersona
        live_model: Optional[str] = None,      # Per-agent Live model override
        max_call_duration_seconds: int = 300,  # Default 5 minutes, configurable per agent
    ):
        self.agent_id = agent_id
        self.system_instruction = system_instruction
        self.conversation_history = conversation_history
        self.llm_config = llm_config
        self.capabilities = capabilities
        self.tools = tools or []
        self.api_key = api_key
        # P2.4 — voice / model overrides from AgentPersona
        self.voice_config = voice_config
        self.task_type = "speech_to_speech"
        self.max_call_duration_seconds = max_call_duration_seconds


class AgentContextLoader:
    """Loads agent configuration for streaming sessions."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def load_agent_for_session(
        self,
        agent_id: UUID,
        customer_id: UUID,
        channel: str = "voice",
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentContext:
        """
        Load agent context for a streaming session.

        The agent-level base (persona, tools, context sources, API key) is
        TTL-cached; conversation history and contact-data injection are
        per-call and applied to a copy.

        Args:
            agent_id: Agent UUID
            customer_id: Customer UUID
            channel: 'voice' or 'whatsapp'
            session_metadata: Optional session metadata containing campaign
                contact_data for template variable injection.
        """
        base = await self._load_agent_base(agent_id, channel)

        # Per-call: conversation history (last 10 interactions)
        history = await self._load_conversation_history(
            customer_id=customer_id,
            agent_id=agent_id,
            channel=channel,
            limit=10
        )

        # Per-call: campaign contact data injection on a copy of the base
        system_instruction = base["system_instruction"]
        contact_data = (session_metadata or {}).get("contact_data", {})
        if contact_data:
            system_instruction = self._inject_contact_data(
                system_instruction, contact_data
            )

        return AgentContext(
            agent_id=agent_id,
            system_instruction=system_instruction,
            conversation_history=history,
            llm_config=base["llm_config"],
            capabilities=base["capabilities"],
            tools=list(base["tools"]),
            api_key=base["api_key"],
            voice_config=base["voice_config"],
            live_model=base["live_model"],
            max_call_duration_seconds=base["max_call_duration_seconds"],
        )

    async def _load_agent_base(self, agent_id: UUID, channel: str) -> Dict[str, Any]:
        """Load (or fetch from cache) the customer-independent agent context."""
        cache_key = (agent_id, channel)
        if _AGENT_BASE_CACHE is not None:
            cached = _AGENT_BASE_CACHE.get(cache_key)
            if cached is not None:
                logger.debug(f"Agent base cache hit for {agent_id} ({channel})")
                return cached

        # 1. Load HierarchicalEntity from database
        result = await self.db.execute(
            select(HierarchicalEntity).where(HierarchicalEntity.id == agent_id)
        )
        entity = result.scalar_one_or_none()
        
        if not entity:
            raise ValueError(f"Agent not found: {agent_id}")
        
        # 2. P2.4 — Resolve AgentPersona for dynamic system prompt + VoiceConfig
        from src.ai.persona_service import PersonaService, build_system_prompt_from_persona
        persona_svc = PersonaService(self.db)
        persona = await persona_svc.get_persona_from_entity(entity)
        
        if persona:
            system_instruction = build_system_prompt_from_persona(persona)
            voice_config = persona.voice
        else:
            # Legacy fallback: build from identity dict fields directly
            identity = entity.identity or {}
            # Try system_prompt first (new format), then instructions (legacy)
            raw_prompt = identity.get("system_prompt") or identity.get("instructions", "")
            if raw_prompt:
                # Use the system_prompt directly — it already contains the full prompt
                system_instruction = raw_prompt
            else:
                system_instruction = self._build_system_instruction(
                    role=identity.get("role", "AI Assistant"),
                    persona=identity.get("persona", ""),
                    instructions="",
                    channel=channel
                )
            voice_config = None
        
        # 2b. Inject entity.goal into system instruction.
        # The goal field contains step-by-step operational instructions
        # (e.g. "confirm email before sending") that are critical for
        # correct agent behavior but were stored separately from identity.
        if entity.goal:
            goal_text = entity.goal if isinstance(entity.goal, str) else str(entity.goal)
            system_instruction += f"\n\n## Goals & Operational Steps\n{goal_text}"
            logger.info(f"Injected goal ({len(goal_text)} chars) into voice system instruction")
        
        # 4. Extract LLM config (from unified JSON structure)
        llm_config = (entity.logic_gate or {}).get("reasoning_config", {})
        
        # 5. Extract capabilities
        capabilities = entity.capabilities or {}
        
        # 5b. Load context sources and inject into system instruction
        context_engineering = capabilities.get("context_engineering", {})
        context_sources = context_engineering.get("context_sources", [])
        if context_sources:
            context_text = await self._load_context_sources(
                context_sources=context_sources,
                company_id=entity.company_id,
            )
            if context_text:
                system_instruction += (
                    "\n\n## Memory Context (Product Knowledge)\n"
                    "Use the following information to answer customer questions accurately.\n"
                    f"{context_text}"
                )
                logger.info(
                    f"Injected {len(context_sources)} context source(s) "
                    f"({len(context_text)} chars) into voice system instruction"
                )
        
        # 6. Load tools if configured (future)
        tools = await self._load_agent_tools(entity)
        
        # 7. Fetch API Key — now via centralized ConfigService.resolve_api_key()
        model_name = llm_config.get("model")
        provider = llm_config.get("model_provider", "google")
        api_key = None
        
        try:
            from src.config.service import ConfigService
            config_svc = ConfigService(self.db)
            api_key = await config_svc.resolve_api_key(
                company_id=entity.company_id,
                provider=provider,
                model_name=model_name,
            )
        except Exception as e:
            logger.error(f"Failed to resolve API key for agent {agent_id}: {e}")
        
        if not api_key:
            logger.warning(f"No API key found for agent {agent_id} (provider={provider}, model={model_name})")
        
        # 8. Resolve Live model name for real-time audio
        #    Check llm_config → capabilities → default
        live_model = (
            llm_config.get("live_model")
            or llm_config.get("model")
            or "gemini-3.1-flash-live-preview"
        )
        
        # 9. Resolve max call duration (configurable at agent level)
        #    Check capabilities → metadata → default (300s = 5 min)
        max_call_duration = (
            capabilities.get("max_call_duration_seconds")
            or (entity.metadata_extensions or {}).get("max_call_duration_seconds") if hasattr(entity, 'metadata_extensions') else None
        )
        if not max_call_duration:
            max_call_duration = 300  # Default: 5 minutes
        else:
            max_call_duration = int(max_call_duration)

        base = {
            "system_instruction": system_instruction,
            "llm_config": llm_config,
            "capabilities": capabilities,
            "tools": tools,
            "api_key": api_key,
            "voice_config": voice_config,
            "live_model": live_model,
            "max_call_duration_seconds": max_call_duration,
        }
        if _AGENT_BASE_CACHE is not None:
            _AGENT_BASE_CACHE[cache_key] = base
        return base
    
    def _build_system_instruction(
        self,
        role: str,
        persona: str,
        instructions: str,
        channel: str
    ) -> str:
        """
        Build system instruction for Gemini from entity identity.
        
        Args:
            role: Agent role (e.g., "EMI Collection Agent")
            persona: Agent persona description
            instructions: Specific instructions
            channel: 'voice' or 'whatsapp'
            
        Returns:
            Formatted system instruction
        """
        instruction = f"""You are {role}.

Persona: {persona}

Instructions:
{instructions}

You are assisting a customer in a real-time {channel} conversation. 
Be concise, helpful, and natural. Listen actively and respond appropriately.
Keep responses brief and conversational - aim for 2-3 sentences maximum.
Avoid repeating yourself or being overly formal."""

        return instruction.strip()
    
    async def _load_conversation_history(
        self,
        customer_id: UUID,
        agent_id: UUID,
        channel: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Load recent conversation history for context.
        
        Args:
            customer_id: Customer UUID
            agent_id: Agent UUID
            channel: 'voice' or 'whatsapp'
            limit: Maximum number of turns to load
            
        Returns:
            List of conversation turns in Gemini format
        """
        result = await self.db.execute(
            select(ConversationHistory)
            .where(
                ConversationHistory.customer_id == customer_id,
                ConversationHistory.agent_id == agent_id,
                ConversationHistory.channel == channel
            )
            .order_by(ConversationHistory.timestamp.desc())
            .limit(limit)
        )
        
        turns = result.scalars().all()
        
        # Convert to Gemini format (reverse order - oldest first)
        history = []
        for turn in reversed(turns):
            role = "user" if turn.speaker == "customer" else "model"
            history.append({
                "role": role,
                "parts": [{"text": turn.content}]
            })
        
        logger.info(f"Loaded {len(history)} conversation turns for customer {customer_id}")
        return history
    
    async def _load_agent_tools(self, entity: HierarchicalEntity) -> List[Dict[str, Any]]:
        """
        Load tool definitions for the voice agent.

        Reads tool_ids from entity.capabilities.tools, resolves their
        function schemas from the ToolRegistry, and returns Gemini-compatible
        function declarations for use in the Live session config.

        Args:
            entity: HierarchicalEntity object

        Returns:
            List of tool function schemas (Gemini function_declarations format)
        """
        capabilities = entity.capabilities or {}

        # Handle both dict and Capabilities model
        if hasattr(capabilities, 'tools'):
            tool_refs = capabilities.tools
        elif isinstance(capabilities, dict):
            tool_refs = capabilities.get("tools", [])
        else:
            tool_refs = []

        # Extract tool_id strings from various formats
        tool_ids = []
        for ref in tool_refs:
            if isinstance(ref, str):
                tool_ids.append(ref)
            elif isinstance(ref, dict):
                tool_ids.append(ref.get("tool_id", ""))
            elif hasattr(ref, 'tool_id'):
                tool_ids.append(ref.tool_id)

        tool_ids = [tid for tid in tool_ids if tid]

        if not tool_ids:
            logger.info("No tools configured for this voice agent")
            return []

        # Resolve function schemas from ToolRegistry
        try:
            from src.ai.tool_executor import ToolExecutor
            schemas = ToolExecutor.get_tool_schemas(tool_ids)
            logger.info(f"Loaded {len(schemas)} tool schema(s) for voice agent: {tool_ids}")
            return schemas
        except Exception as e:
            logger.error(f"Failed to load tool schemas for {tool_ids}: {e}")
            return []

    async def _load_context_sources(
        self,
        context_sources: List[Dict[str, Any]],
        company_id: UUID,
    ) -> str:
        """
        Load text content from context sources (documents, artifacts, etc.)
        for injection into the voice agent's system instruction.

        Supports DOCUMENT and KNOWLEDGE_BASE source types by loading the
        referenced artifact's file content and extracting text.

        Returns:
            Concatenated text from all loadable context sources,
            truncated to ~30000 chars to stay within Gemini's context window.
        """
        loaded_parts: List[str] = []
        MAX_TOTAL_CHARS = 30_000  # Voice sessions need concise context

        for src in context_sources:
            src_type = src.get("source_type", "DOCUMENT")
            ref_id = src.get("reference_id", "")
            desc = src.get("description", "")
            file_name = src.get("file_name", "")

            if not ref_id:
                continue

            try:
                if src_type in ("DOCUMENT", "KNOWLEDGE_BASE"):
                    from src.ai.artifact_service import ArtifactService
                    art_svc = ArtifactService(self.db)
                    artifact = await art_svc.get_artifact(UUID(ref_id), company_id)

                    if not artifact:
                        logger.warning(f"Context source artifact not found: {ref_id}")
                        continue

                    from pathlib import Path
                    fpath = Path(artifact.file_path)
                    mime = artifact.mime_type or ""
                    label = desc or file_name or artifact.file_name

                    # Skip binary media (images, audio, video)
                    if mime.startswith(("image/", "audio/", "video/")):
                        continue

                    if fpath.exists():
                        content = self._extract_text_from_file(fpath, mime)
                        if content:
                            loaded_parts.append(f"### {label}\n{content}")
                        else:
                            logger.warning(f"Could not extract text from {fpath}")
                    else:
                        logger.warning(f"Context source file not found on disk: {fpath}")

            except Exception as e:
                logger.warning(f"Failed to load context source {src_type}:{ref_id}: {e}")

        if not loaded_parts:
            return ""

        combined = "\n\n".join(loaded_parts)
        if len(combined) > MAX_TOTAL_CHARS:
            combined = combined[:MAX_TOTAL_CHARS] + "\n...(truncated)"
        return combined

    @staticmethod
    def _extract_text_from_file(file_path, mime_type: str = "") -> str:
        """
        Extract text from a file (TXT, CSV, DOCX, XLSX, PDF, etc.).
        Returns empty string if extraction fails.
        """
        from pathlib import Path
        ext = Path(file_path).suffix.lower()

        try:
            # Plain text
            if ext in (".txt", ".md", ".csv", ".json", ".xml", ".html"):
                return Path(file_path).read_text(encoding="utf-8", errors="replace")

            # DOCX
            if ext in (".docx", ".doc"):
                try:
                    import docx
                    doc = docx.Document(str(file_path))
                    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
                except ImportError:
                    logger.warning("python-docx not installed; cannot extract DOCX")
                    return ""

            # XLSX / XLS
            if ext in (".xlsx", ".xls"):
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
                    rows = []
                    for ws in wb.worksheets:
                        for row in ws.iter_rows(values_only=True):
                            row_text = "\t".join(str(c) if c is not None else "" for c in row)
                            if row_text.strip():
                                rows.append(row_text)
                    wb.close()
                    return "\n".join(rows)
                except ImportError:
                    logger.warning("openpyxl not installed; cannot extract XLSX")
                    return ""

            # PDF
            if ext == ".pdf":
                try:
                    import PyPDF2
                    reader = PyPDF2.PdfReader(str(file_path))
                    pages = [p.extract_text() or "" for p in reader.pages]
                    return "\n".join(pages)
                except ImportError:
                    logger.warning("PyPDF2 not installed; cannot extract PDF")
                    return ""

            # Fallback: try reading as text
            return Path(file_path).read_text(encoding="utf-8", errors="replace")

        except Exception as e:
            logger.warning(f"Text extraction failed for {file_path}: {e}")
            return ""

    @staticmethod
    def _inject_contact_data(
        system_instruction: str,
        contact_data: Dict[str, Any],
    ) -> str:
        """
        Inject campaign CSV contact data into the agent's system instruction.

        Two mechanisms:
        1. **Template replacement**: Replaces ``{{key}}`` placeholders in the
           prompt with the corresponding value from contact_data.  This lets
           the agent admin write prompts like "Greet the customer by name:
           {{contact}}" and have it filled automatically.
        2. **Context section**: Appends a structured "Call Context" section
           listing all contact fields so the agent is always aware of who
           it is calling, even without explicit {{}} usage.

        Args:
            system_instruction: The current system prompt text.
            contact_data: Dict of CSV column -> value for this lead.

        Returns:
            Updated system instruction with contact data injected.
        """
        import re

        # 1. Replace {{key}} templates (case-insensitive, allows spaces)
        for key, value in contact_data.items():
            if value is None:
                continue
            # Match {{key}} with optional whitespace inside braces
            pattern = r"\{\{\s*" + re.escape(key) + r"\s*\}\}"
            system_instruction = re.sub(
                pattern, str(value), system_instruction, flags=re.IGNORECASE
            )

        # 2. Append structured context section (skip internal fields)
        display_fields = {
            k: v for k, v in contact_data.items()
            if v is not None and k.lower() not in ("phone",)
        }
        if display_fields:
            lines = [f"- **{k}**: {v}" for k, v in display_fields.items()]
            system_instruction += (
                "\n\n## Call Context (Lead Information)\n"
                "Use the following information about the person you are calling:\n"
                + "\n".join(lines)
            )
            logger.info(
                f"Injected {len(display_fields)} contact field(s) into system prompt"
            )

        return system_instruction
