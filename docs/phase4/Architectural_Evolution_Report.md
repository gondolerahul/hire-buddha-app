# AI Agents Platform — Comprehensive Architectural Evolution Report

> **Author**: Senior AI Software Architect & System Designer  
> **Date**: 2026-03-03  
> **Scope**: `backend/src/ai` · `backend/src/streaming`  
> **Classification**: Internal Engineering — Confidential

---

## Table of Contents
1. [Executive Summary](#1-executive-summary)
2. [Codebase Audit & Hygiene](#2-codebase-audit--hygiene)
3. [The Autonomous Loop Evolution](#3-the-autonomous-loop-evolution)
4. [Feature Integration: Multi-Modal Personality & Voice](#4-feature-integration-multi-modal-personality--voice)
5. [External Benchmarking — OpenCode & OpenClaw](#5-external-benchmarking--opencode--openclaw)
6. [Appendix: Key Files Audited](#6-appendix-key-files-audited)

---

## 1. Executive Summary

The HB-Proto-3 AI Agents Platform is a **well-structured, multi-tenant SaaS** with a clear hierarchical agent model (`ACTION → SKILL → AGENT → PROCESS`), a DAG-based parallel execution engine, REACT multi-turn tool loops, a self-critique review mechanism, and a bidirectional real-time voice pipeline powered by Gemini Live. The foundation is solid.

However, several **critical architectural debts** threaten horizontal scalability, long-session robustness, and the platform's ability to autonomously self-correct. This report details those debts and provides a concrete evolution roadmap to move from the current **Linear-Recursive** execution model to a **Recursive Reasoning / Self-Correction** powerhouse suited for a cloud-native, multi-tenant environment.

### Critical Priority Matrix

| Priority | Finding | Module | Risk |
|---|---|---|---|
| 🔴 P0 | `TataStreamHandler` duplicates 100+ lines of `TwilioStreamHandler` | `streaming/websocket_handler.py` | High maintenance burden |
| 🔴 P0 | In-memory audio recording buffers for calls | `streaming/websocket_handler.py` | OOM on long calls (>10 min) |
| 🔴 P0 | API key resolution is 6-strategy waterfall, duplicated in 3 files | `ai/worker.py`, `ai/service.py`, `ai/worker.py:process_document` | Logic drift, N+6 DB queries per LLM call |
| 🔴 P0 | HITL approval notification missing — `TODO` left in `service.py:289` | `ai/service.py` | Approvals silently never unblock workers |
| 🟠 P1 | `ExecutionEngine` shares a single `AsyncSession` across concurrent parallel steps | `ai/worker.py` | SQLAlchemy session race conditions |
| 🟠 P1 | `get_execution` loads 5-level deep SQLAlchemy eager-join chains | `ai/service.py:198` | N+dozens queries, response bloat |
| 🟠 P1 | SessionManager self-describes as "suitable for <50 concurrent calls" | `streaming/session_manager.py` | No Redis caching, DB-bound concurrency ceiling |
| 🟡 P2 | Tool function calling injected via prompt string; native Gemini FC not wired to HITL loop | `ai/worker.py`, `ai/tool_executor.py` | Fragile tool use at scale |
| 🟡 P2 | Two parallel tool execution paths: `execute_tools` (legacy regex) and `execute_from_function_calls` (native FC) | `ai/tool_executor.py` | Dead code risk |
| 🟡 P2 | `process_document` embeds model embedding via raw `httpx` instead of unified `google-genai` SDK | `ai/worker.py:1234` | Inconsistency; bypasses SDK retry / error handling |
| 🟡 P2 | `HierarchicalEntity.identity` has no standardized schema; parsed ambiguously in 3 separate code paths | `ai/models.py`, `ai/worker.py:800`, `streaming/agent_loader.py` | Personality/tone drift between agent types |
| 🟡 P2 | `GeminiLiveSession` wrapper exposes its own `send_text/send_audio/receive` methods but the calling code in `websocket_handler.py` bypasses the wrapper and calls the SDK directly | `streaming/gemini_live.py` | Dead abstraction layer |
| 🟢 P3 | `HierarchicalEntity` has both a new unified structure (`identity`, `logic_gate`, `planning`) and retained legacy fields (`static_plan`, `llm_config`, `toolkit`) | `ai/models.py:42` | Schema sprawl |
| 🟢 P3 | Hardcoded `always_keep` keys in `_maybe_summarize_context` (`"age_group"`, `"style"`, `"topic"`) | `ai/worker.py:1013` | Domain-specific tokens in platform-level code |
| 🟢 P3 | `tool_logs` latency is hardcoded to `latency_ms=0` for REACT tool calls | `ai/worker.py:872` | Incomplete observability data |
| 🟢 P3 | `GeminiLiveClient.generation_config` default stores `response_modalities` at top level; `create_session_config` re-nests correctly but the constructor comment is misleading | `streaming/gemini_live.py:50` | Onboarding confusion |

---

## 2. Codebase Audit & Hygiene

### 2.1 Redundant Code & Logic Duplicates

#### 2.1.1 — TataStreamHandler: The 300-Line Clone
**File**: `streaming/websocket_handler.py` — Lines 639–914

`TataStreamHandler` inherits from `TwilioStreamHandler` but overrides `__init__` with an **identical 40-line copy** of all instance attributes. The `handle_direct` method then re-implements the exact Gemini connection setup (lines 730–791) already present in `TwilioStreamHandler.handle` (lines 114–187), including the greeting trigger, the 5-task creation loop, and the graceful cancellation logic.

**Impact**: Every bug fix or feature addition to Twilio's handler must be manually mirrored. This has already diverged slightly (Tata plays ringback twice — in `handle_direct` line 725 AND potentially in the inherited `_handle_start_event`).

**Fix**: Extract shared state into a `BaseStreamHandler` dataclass + mixin, override only the start-event parsing:
```python
@dataclass
class StreamState:
    session_id: Optional[UUID] = None
    stream_sid: Optional[str] = None
    call_sid: Optional[str] = None
    voice_session: Optional[VoiceSession] = None
    gemini_session: Any = None
    is_running: bool = False
    # ...

class BaseStreamHandler:
    state: StreamState
    async def _setup_gemini_and_run(self, agent_context: AgentContext): ...
    async def _receive_from_provider(self): ...  # abstract

class TwilioStreamHandler(BaseStreamHandler): ...
class TataStreamHandler(BaseStreamHandler):
    async def _receive_from_provider(self): ...  # Tata-specific parsing
```

#### 2.1.2 — API Key Resolution: 6-Waterfall Duplicated in 3 Files
The following files independently implement an identical 4–6 strategy API key lookup:
- `ai/worker.py:925` (`_get_api_key`)
- `ai/service.py:365` (`search_documents`) 
- `ai/worker.py:1212` (`process_document`)

Each makes 2–6 sequential database round-trips per LLM call. With 50 concurrent agents, this is potentially 300 wasted DB queries per second.

**Fix**: Centralize into `ConfigService` as a single `resolve_api_key(company_id, provider, model_name)` method with an in-process TTL cache (e.g., `cachetools.TTLCache` with 60s TTL):
```python
class ConfigService:
    _key_cache: TTLCache = TTLCache(maxsize=512, ttl=60)

    async def resolve_api_key(self, company_id: UUID, provider: str, model_name: str) -> str:
        cache_key = f"{company_id}:{provider}:{model_name}"
        if cache_key in self._key_cache:
            return self._key_cache[cache_key]
        key = await self._waterfall_lookup(company_id, provider, model_name)
        self._key_cache[cache_key] = key
        return key
```

#### 2.1.3 — Dual Tool Execution Paths
`ToolExecutor` exposes two execution methods:
- `execute_tools()` — legacy regex-parsed tool calls (string format `TOOL:name:input`)
- `execute_from_function_calls()` — native Gemini function call dicts

The `parse_tool_calls()` method (regex-based) is still present but the worker exclusively uses native function calling since the google-genai SDK upgrade. The legacy path should be deprecated with a `DeprecationWarning` and removed in the next major version.

### 2.2 Conflicting State Management Flows

#### 2.2.1 — Concurrent Steps Share a Single AsyncSession
In `ExecutionEngine._execute_steps_dag`, parallel steps are launched via `asyncio.gather(*tasks)` but all coroutines share `self.db` (a single `AsyncSession`). SQLAlchemy `AsyncSession` is **not thread-safe** and concurrent coroutines competing on the same session will cause intermittent `PendingRollbackError` and silent transaction aborts. The `_log_conversation_turn` method in `TwilioStreamHandler` already recognized this (line 492: "We MUST NOT reuse self.db here") and spawns a new session per log call. The same pattern must be applied to `ExecutionEngine`.

**Fix**: Each parallel step coroutine should acquire its own session from `AsyncSessionLocal()`, or use a connection pool gateway (e.g., pass `AsyncSessionFactory` to `ExecutionEngine` and let each step open/close its own session).

#### 2.2.2 — HITL Approval Notification: Silent Dead-End
`ai/service.py:289`: `# TODO: Notify worker that approval is received (e.g. via Redis/Event)`

The `respond_to_approval` method updates the DB status but **never signals the waiting worker**. The worker in `run_execution_recursive` has no polling or pub/sub mechanism for approval completions. This means human-approved steps will wait forever until the job times out (30 minutes per `WorkerSettings.job_timeout`).

**Fix**: Publish to Redis channel on approval response:
```python
# In respond_to_approval()
redis = await create_pool(RedisSettings())
await redis.publish(
    f"approval:{approval_id}",
    json.dumps({"status": status, "notes": notes})
)
# In ExecutionEngine, before HITL-gated steps:
async with timeout(approval_timeout_ms / 1000):
    msg = await redis.subscribe(f"approval:{approval_id}")
    # unblock on approved/rejected
```

### 2.3 Architectural Debt: Patterns Hindering Scalability

#### 2.3.1 — Unbounded 5-Level Eager Join in `get_execution`
`ai/service.py:198` builds a 25-option `selectinload` chain for 5 levels of child runs. On deep recursive agents (e.g., a PROCESS calling 3 AGENTs, each calling 3 SKILLs), this degrades into **N×M×P queries** and returns megabytes of JSON to the HTTP client. 

**Fix**: Replace with paginated depth queries + a dedicated "execution tree" endpoint that lazily fetches child levels on demand. For the detail view, consider JSONB aggregation at the DB level using PostgreSQL's `jsonb_agg` recursive CTEs.

#### 2.3.2 — SessionManager: PostgreSQL-Only, <50 Concurrent Calls
`streaming/session_manager.py:6` explicitly documents: "Phase 1: suitable for <50 concurrent calls." As a SaaS platform, this is a hard ceiling. All session hot-path reads/writes hit PostgreSQL with no caching.

**Fix**: Add a Redis caching layer in Phase 2 as already planned. Use Redis hash sets for active session state with TTL-based expiry, falling back to PostgreSQL for persistence.

#### 2.3.3 — In-Memory Audio Recording Buffer (OOM Risk)
`streaming/websocket_handler.py:99`: `self._session_recording_pcm = bytearray()`

A 10-minute call at 8kHz 16-bit mono generates ~9.6 MB of PCM per channel. With mixing, each call accumulates ~19 MB in process memory. At 50 concurrent calls, that's ~950 MB held in RAM per worker process — before Gemini's own buffers.

**Fix**: Stream the recording to a temporary file or object store (Google Cloud Storage) in chunks during the call rather than accumulating in memory:
```python
async def _record_chunk(self, pcm_chunk: bytes):
    async with aiofiles.open(self._temp_recording_path, 'ab') as f:
        await f.write(pcm_chunk)
```

### 2.4 Streaming Bottleneck Analysis

The streaming pipeline has 5 concurrent coroutines per call session:
1. `_receive_from_twilio` — WebSocket I/O bound
2. `_process_incoming_audio` — CPU bound (mulaw → PCM16 conversion via `audioop`)
3. `_receive_from_gemini` — Network I/O bound (Gemini Live WebSocket)
4. `_send_to_twilio` — WebSocket I/O bound
5. `_flush_transcripts` — Timer + DB I/O

**Bottleneck 1**: `audioop.ulaw2lin` is a CPython C extension and fast, but it runs in the event loop thread. At high concurrency, audio conversion could starve other coroutines. Use `asyncio.get_event_loop().run_in_executor(None, audioop.ulaw2lin, chunk, 2)` for large chunks.

**Bottleneck 2**: `_receive_from_twilio` uses `await self.websocket.receive_text()` inside a tight `while self.is_running` loop with no backpressure. If Twilio sends audio faster than Gemini processes it, `incoming_audio_buffer` (a `deque` with no `maxlen`) grows unbounded.

**Fix**: Add `maxlen` to the incoming buffer deque, and implement audio packet drop (prioritize recency over completeness — the human voice is more tolerant of dropped packets than added latency):
```python
self.incoming_audio_buffer = deque(maxlen=200)  # ~1 second of audio at 8kHz/20ms packets
```

**Bottleneck 3**: The 10ms timeout in `_send_to_twilio` (`asyncio.wait_for(..., timeout=0.01)`) means the task busy-loops 100 times/second even when idle. Replace with `asyncio.Queue.get()` (no timeout) and let task cancellation propagate naturally via `is_running`.

---

## 3. The Autonomous Loop Evolution

### 3.1 Current State: Linear-Recursive Execution with Reactive Self-Correction

The current agentic loop in `ExecutionEngine` is:

```
Plan → [Step₁ → Review? → Step₂ → Review? → ... → StepN] → Finalize
```

The REACT loop within each step allows tool use (up to 12 turns), and `_review_step_output` provides a simple self-critique retry mechanism. However:
- **No inter-step feedback loop**: Step N's output cannot trigger re-planning of previous steps
- **No goal decomposition**: The planner generates a flat list of steps (not a tree)
- **No uncertainty handling**: The agent cannot express "I need more information before proceeding"
- **No persistent memory**: State resets on each `ExecutionRun`; conversation context is summarized but not episodically stored

### 3.2 Proposed Evolution: Recursive Reasoning with Self-Correction

#### Phase A: Goal Decomposition Tree (Near-term)

Replace the flat step list with a **goal tree** where each node can spawn child goals dynamically:

```python
class GoalNode:
    goal_id: str
    description: str
    status: Literal["PENDING", "ACTIVE", "BLOCKED", "COMPLETED", "FAILED"]
    children: List[GoalNode] = []
    parent_id: Optional[str] = None
    confidence: float = 0.0  # LLM self-assessed confidence (0-1)
    blockers: List[str] = []  # What's needed to unblock

class RecursiveReasoningEngine(ExecutionEngine):
    async def expand_goal(self, goal: GoalNode, context: dict) -> List[GoalNode]:
        """Ask LLM to decompose a goal into sub-goals if confidence < threshold."""
        if goal.confidence < 0.7:
            return await self._llm_decompose(goal, context)
        return [goal]
    
    async def execute_tree(self, root: GoalNode, context: dict):
        """DFS execution with backtracking on failure."""
        if root.status == "FAILED":
            # Backtrack: re-plan parent goal
            await self.replan_parent(root, context)
        children = await self.expand_goal(root, context)
        await asyncio.gather(*[self.execute_tree(c, context) for c in children])
```

#### Phase B: Uncertainty & Clarification Requests

Add a mechanism for the agent to signal that it needs information before proceeding, without halting the entire run:

```python
class UncertaintySignal(Exception):
    def __init__(self, question: str, confidence: float, alternatives: List[str]):
        self.question = question
        self.confidence = confidence  # Agent's confidence in its current path
        self.alternatives = alternatives  # Possible ways to resolve

# In _execute_thought():
if llm_result.get("needs_clarification"):
    raise UncertaintySignal(
        question=llm_result["clarification_question"],
        confidence=llm_result.get("confidence", 0.5),
        alternatives=llm_result.get("alternatives", [])
    )
```

The `UncertaintySignal` can trigger either:
1. A HITL checkpoint (if `governance.hitl_checkpoints` matches)
2. An autonomous sub-query using a search tool to self-resolve
3. A graceful partial completion with annotated uncertainty

#### Phase C: Long-Running Task State Management

For tasks exceeding the 30-minute job timeout, the current architecture has no checkpointing. Propose:

1. **Checkpoint Snapshots**: Every N steps (configurable), serialize `context_state` + `completed_step_ids` to the `execution_runs` table's `context_state` JSONB column (already present).

2. **Job Resumption**: Add `resume_execution` Arq job that reloads the checkpoint and continues from the last completed step:
```python
async def resume_execution(ctx, run_id_str: str):
    """Resume a checkpointed or interrupted execution run."""
    run_id = UUID(run_id_str)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))
        run = result.scalar_one()
        # Determine which steps are already in context_state
        completed = set(run.context_state.keys()) if run.context_state else set()
        engine = ExecutionEngine(db, redis_pool)
        await engine.execute_run(run_id, skip_completed=completed)
```

3. **Cross-Run Memory**: Introduce an `EpisodicMemoryStore` that persists important facts from completed runs, queryable by `company_id + agent_id + semantic_similarity`:
```python
class EpisodicMemoryStore:
    async def save(self, company_id, agent_id, fact: str, embedding: List[float]): ...
    async def recall(self, company_id, agent_id, query: str, top_k=5) -> List[str]: ...
```
This directly leverages the existing `pgvector` + `DocumentChunk` infrastructure already in `ai/models.py`.

### 3.3 REACT Loop Hardening

The current REACT loop in `_execute_thought` (max 12 turns) has one subtle issue: the "running prompt" accumulation strategy (appending `[Assistant partial response] + tool results`) creates increasingly long prompts across turns. By turn 6, the prompt may exceed the model's context window.

**Fix**: Replace prompt accumulation with Gemini's native multi-turn `contents` list, which the SDK tracks natively and benefits from efficient KV-cache re-use:

```python
# Instead of string appending, build a proper contents list:
contents = [types.Content(role="user", parts=[types.Part.from_text(initial_prompt)])]

for turn in range(max_react_turns):
    response = client.models.generate_content(model=model, contents=contents, config=config)
    
    # Append assistant turn
    contents.append(types.Content(role="model", parts=response.candidates[0].content.parts))
    
    if response.function_calls:
        # Execute tools, then append function results as a user turn
        tool_results = await execute_tools(response.function_calls)
        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_function_response(name=r.name, response=r.result) for r in tool_results]
        ))
    else:
        break  # Final text response
```

---

## 4. Feature Integration: Multi-Modal Personality & Voice

### 4.1 Gemini Live v2.5 Flash Native Audio Integration

The current implementation uses `gemini-2.0-flash-exp` hardcoded as the default model. The upgrade to `gemini-2.5-flash-preview-native-audio-01` (Gemini Live v2.5 Flash Native Audio) requires specific configuration.

#### 4.1.1 Complete `speech_config` & `voice_config` Specification

Based on Google Cloud Vertex AI Gemini Live API documentation, the full `LiveClientSetup` for v2.5 native audio:

```python
def create_v25_native_audio_config(
    voice_name: str = "Aoede",
    language_code: str = "en-US",
    speaking_rate: float = 1.0,
    pitch: float = 0.0,
) -> dict:
    """
    Build LiveClientSetup config for Gemini 2.5 Flash Native Audio.
    
    Supported prebuilt voice names:
      Puck, Charon, Kore, Fenrir, Aoede, Orbit, Zephyr, Leda,
      Orus, Rigel, Schedar, Pulcherrima, Achird, Zubenelgenubi,
      Vindemiatrix, Sadachbia, Sadaltager, Sulafat
    
    Native Audio mode differences vs 2.0-flash:
      - thinking_config NOT supported (causes 60-90s silence)  
      - response_modalities MUST be ["AUDIO"] (TEXT not supported)
      - Automatically higher naturalness and barge-in accuracy
    """
    return {
        # ── generation_config (NESTED) ───────────────────────────────
        "generation_config": {
            "response_modalities": ["AUDIO"],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": voice_name
                    }
                },
                # Multi-speaker config (future): 
                # "multi_speaker_voice_config": {
                #   "speaker_voice_configs": [
                #     {"speaker": "Agent", "voice_config": {"prebuilt_voice_config": {"voice_name": "Aoede"}}},
                #   ]
                # }
            },
            # Language and prosody hints (Native Audio)
            "audio_speech_config": {
                "language_code": language_code,
                "speaking_rate": speaking_rate,  # 0.25 – 4.0
                "pitch": pitch,                  # -20.0 – 20.0 semitones
            }
        },
        # ── top-level LiveClientSetup keys ────────────────────────────
        "system_instruction": None,  # Populated by caller
        "input_audio_transcription": {},   # Enable customer speech-to-text
        "output_audio_transcription": {},  # Enable agent speech-to-text
        "realtime_input_config": {
            "automatic_activity_detection": {
                "disabled": False,
                "start_of_speech_sensitivity": "START_SENSITIVITY_LOW",  # Less aggressive barge-in
                "end_of_speech_sensitivity": "END_SENSITIVITY_HIGH",    # Faster end detection
                "prefix_padding_ms": 100,
                "silence_duration_ms": 800,  # Longer pause = end of speech
            }
        },
        "proactivity": {
            "proactive_audio": True  # Agent can initiate turn (e.g., re-prompt after silence)
        }
    }
```

#### 4.1.2 Update `GeminiLiveClient.create_session_config`

```python
# In streaming/gemini_live.py

MODEL_CONFIGS = {
    "gemini-2.0-flash-exp": {
        "supports_thinking": False,
        "native_audio": False,
    },
    "gemini-2.5-flash-preview-native-audio-01": {
        "supports_thinking": False,  # DO NOT set thinking_config for this model
        "native_audio": True,
    }
}

def create_session_config(self, model: str = "gemini-2.0-flash-exp") -> dict:
    model_caps = MODEL_CONFIGS.get(model, MODEL_CONFIGS["gemini-2.0-flash-exp"])
    
    if model_caps["native_audio"]:
        config = create_v25_native_audio_config(
            voice_name=self.voice_name,  # Sourced from agent persona (see §4.2)
            language_code=self.language_code,
        )
    else:
        config = { ... }  # existing 2.0 config
    
    config["system_instruction"] = self.system_instruction
    return config
```

#### 4.1.3 Model Selection in AgentLoader

Update `agent_loader.py` to read the model from `entity.llm_config` and pass it through:

```python
# In AgentContextLoader.load_agent_for_session()
llm_config = entity.llm_config or {}
live_model = llm_config.get("live_model", "gemini-2.5-flash-preview-native-audio-01")
# Return in AgentContext:
return AgentContext(
    ...,
    live_model=live_model,
    voice_config=identity.get("voice_config", {})  # From persona schema (§4.2)
)
```

### 4.2 Persona Schema — Standardized Agent Identity

The current `identity` field in `HierarchicalEntity` is loosely typed (`Column(JSON)`) and parsed differently in each consumer:
- `ai/worker.py:801` checks `identity.get("system_prompt")` OR `identity.get("persona", {}).get("system_prompt")`
- `streaming/agent_loader.py:75` reads `identity.get("role")`, `identity.get("persona")` (as a string), `identity.get("instructions")`
- `ai/schemas.py:60` defines a `Persona` Pydantic model that is only used in schema validation, not enforced at DB level

**Proposed Standardized Persona Schema**:

```python
# In ai/schemas.py — add PersonaMatrix and VoiceConfig

class VoiceConfig(BaseModel):
    """Voice identity for Gemini Live API."""
    voice_name: str = "Aoede"          # Gemini prebuilt voice name
    language_code: str = "en-US"       # BCP-47 language tag
    speaking_rate: float = 1.0         # 0.25–4.0 (1.0 = normal speed)
    pitch: float = 0.0                 # -20.0 to +20.0 semitones
    # Future: custom voice clone reference
    custom_voice_id: Optional[str] = None  

class PersonalityMatrix(BaseModel):
    """
    Core behavioral fingerprint for the agent.
    These dimensions are injected into the system prompt dynamically.
    """
    tone: str = "professional"         # e.g. friendly, formal, empathetic, assertive
    verbosity: str = "concise"         # concise | moderate | verbose
    empathy_level: float = 0.7         # 0.0 (robotic) to 1.0 (highly empathetic)
    humor_level: float = 0.2           # 0.0 (none) to 1.0 (frequent)
    formality: str = "semi-formal"     # formal | semi-formal | casual
    decision_confidence: float = 0.8   # Confidence threshold before escalating

class AgentPersona(BaseModel):
    """
    Standardized persona schema for HierarchicalEntity.identity.
    Replaces the current loosely-typed JSON blob.
    """
    # Core identity
    name: str                           # Agent's human name (e.g., "Aria")
    role: str                           # Role descriptor (e.g., "EMI Collection Specialist")
    bio: Optional[str] = None          # 1-2 sentence backstory for richer personality
    
    # Visual identity (for UI and future multi-modal interactions)  
    profile_image_url: Optional[str] = None   # Avatar image URL
    profile_image_thumbnail_url: Optional[str] = None
    
    # Behavioral fingerprint
    personality: PersonalityMatrix = PersonalityMatrix()
    
    # Voice identity (for Gemini Live)
    voice: VoiceConfig = VoiceConfig()
    
    # Prompt engineering  
    system_prompt: str = ""            # Core instruction (auto-built from above if empty)
    behavioral_constraints: List[str] = []
    few_shot_examples: List[PersonaExample] = []
    
    # Dynamic injection hooks
    greeting_template: Optional[str] = None  # Template for initial greeting
    escalation_message: Optional[str] = None # What to say when escalating to human
    closing_message: Optional[str] = None    # End-of-call closing statement
```

#### 4.2.1 Dynamic Prompt Injection from Persona

Update `build_sandwich_prompt` in `ai/worker.py` to consume the new `AgentPersona`:

```python
def build_system_prompt_from_persona(persona: AgentPersona) -> str:
    """Inject personality matrix into the system prompt dynamically."""
    personality = persona.personality
    
    prompt_parts = [persona.system_prompt] if persona.system_prompt else []
    
    # Inject personality dimensions
    prompt_parts.append(f"""
## Personality Profile: {persona.name}
- **Role**: {persona.role}
- **Tone**: {personality.tone}
- **Communication Style**: {personality.verbosity} responses, {personality.formality} register
- **Empathy Level**: {"High empathy — acknowledge emotions before providing information" if personality.empathy_level > 0.6 else "Professional empathy — stay solution-focused"}
- **Humor**: {"Use light humor when appropriate" if personality.humor_level > 0.4 else "No humor — maintain professional tone"}

## Behavioral Constraints
{chr(10).join(f"- {c}" for c in persona.behavioral_constraints)}
""")
    
    if persona.greeting_template:
        prompt_parts.append(f"## Opening: Use this greeting template: {persona.greeting_template}")
    
    return "\n\n".join(prompt_parts)
```

#### 4.2.2 Accessing Persona from the `ai` Module

Add a `PersonaService` to the `ai` module for dynamic persona resolution:

```python
# New file: backend/src/ai/persona_service.py

class PersonaService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_persona(self, entity_id: UUID) -> Optional[AgentPersona]:
        """Load and parse the standardized persona for an entity."""
        result = await self.db.execute(
            select(HierarchicalEntity).where(HierarchicalEntity.id == entity_id)
        )
        entity = result.scalar_one_or_none()
        if not entity or not entity.identity:
            return None
        
        try:
            # Handle both old and new identity formats
            identity = entity.identity
            if isinstance(identity, dict) and "persona" in identity:
                identity = identity["persona"]
            return AgentPersona(**identity)
        except Exception:
            return None
    
    async def get_voice_config(self, entity_id: UUID) -> VoiceConfig:
        """Convenience method: returns voice config from persona, or defaults."""
        persona = await self.get_persona(entity_id)
        return persona.voice if persona else VoiceConfig()
    
    async def build_agent_system_prompt(self, entity_id: UUID, context: dict = {}) -> str:
        """Build a fully-injected system prompt from persona + runtime context."""
        persona = await self.get_persona(entity_id)
        if not persona:
            return "You are a helpful AI assistant."
        return build_system_prompt_from_persona(persona)
```

---

## 5. External Benchmarking — OpenCode & OpenClaw

### 5.1 OpenCode (anomalyco/opencode) — Key Architectural Concepts

OpenCode is a CLI-first agentic coding assistant. Key patterns relevant to this platform:

#### 5.1.1 Provider-Agnostic Tool Interface
OpenCode implements tools as self-describing, provider-agnostic interfaces:
```typescript
interface Tool<TInput, TResult> {
  id: string;
  description: string;
  input_schema: JSONSchema;
  execute(input: TInput, context: Context): Promise<TResult>;
  // CRITICAL: tools declare their own permissions
  permissions: ("read_file" | "write_file" | "execute_command" | "network")[];
}
```

**Cloud SaaS Adaptation**: The current `ToolRegistry` in HB-Proto-3 lacks permission declarations. Adding them enables:
- **Sandbox Enforcement**: Reject tool calls that exceed declared permissions per agent
- **Customer Transparency**: Show customers what permissions each tool has
- **Audit Logging**: Log permission-level decisions alongside tool calls

```python
# Enhanced ToolDefinition (update schemas.py)
class ToolDefinition(BaseModel):
    tool_id: str
    permissions: List[Literal["read", "write", "execute", "network", "storage"]] = []
    sandbox_mode: bool = False  # Run in subprocess isolation
    max_execution_seconds: int = 30  # Timeout enforcement
    rate_limit_per_run: Optional[int] = None  # Max calls per ExecutionRun
```

#### 5.1.2 Structured Tool Result Types
OpenCode tools return typed results, not raw strings. The current `ToolExecutor` returns unstructured `Dict[str, Any]`:

**Adaptation**:
```python
class ToolResult(BaseModel):
    success: bool
    output: Any
    content_type: Literal["text", "json", "image", "file", "error"] = "text"
    artifact_path: Optional[str] = None  # For file-producing tools
    cost_usd: Optional[Decimal] = None   # Tool's self-reported cost
    metadata: Dict[str, Any] = {}
```

#### 5.1.3 Session-Scoped Conversation State
OpenCode maintains a **session store** that persists the LLM multi-turn `messages[]` array between tool calls, leveraging the model's own context management rather than re-building prompts.

**Cloud SaaS Adaptation**: HB-Proto-3's `_execute_thought` re-builds `running_prompt` as a string accumulation (known issue in §3.3). Adopting the session-scoped messages list (as proposed in §3.3) is directly inspired by this pattern.

### 5.2 OpenClaw (openclaw/openclaw) — Key Architectural Concepts

OpenClaw focuses on a **sandboxed tool execution** model for safe agentic code execution.

#### 5.2.1 Sandbox Execution via Docker / E2B
OpenClaw executes code tools inside ephemeral containers or [E2B sandboxes](https://e2b.dev/), isolating execution from the host process. The tool result is marshaled via stdout/JSON.

**Cloud SaaS Adaptation**: This is directly applicable to HB-Proto-3's `code_execution` tool type (if/when added). Proposed integration:

```python
# New tool: sandbox_executor.py
class SandboxCodeTool(BaseTool):
    """
    Executes code in an ephemeral E2B sandbox.
    Appropriate for customer-configured code agents.
    """
    async def run(self, code: str, language: str = "python") -> ToolResult:
        sandbox = await E2BSandbox.create(template=language)
        try:
            result = await sandbox.run_code(code, timeout=30)
            return ToolResult(success=True, output=result.stdout, content_type="text")
        finally:
            await sandbox.close()
```

For the cloud SaaS context: offer "standard" (process-isolated via asyncio subprocess) and "secure" (E2B/container) sandbox tiers as part of agent governance configuration.

#### 5.2.2 Memory Architecture: Layered Memory Tiers
OpenClaw implements three memory tiers that map to conversation scope:
- **Working Memory**: Current task context (in-process dict → maps to `context_state`)
- **Episodic Memory**: Past similar tasks (vector store → maps to `DocumentChunk` + pgvector)
- **Semantic Memory**: Stable facts about the world (knowledge base → maps to `Document` RAG)

**Cloud SaaS Adaptation**: The `MemoryConfig` schema in `schemas.py` already defines `SESSION | ENTITY | GLOBAL` scopes. Implementation is the missing piece:

```python
# Proposed MemoryRouter in ai/memory_service.py
class MemoryRouter:
    """Routes memory reads/writes to the appropriate tier."""
    
    async def write_working(self, run_id: UUID, key: str, value: Any): 
        # Update execution_run.context_state JSONB
    
    async def write_episodic(self, agent_id: UUID, content: str, embedding: List[float]):
        # Insert DocumentChunk with special source="episodic_memory"
    
    async def read_episodic(self, agent_id: UUID, query: str, top_k: int = 5) -> List[str]:
        # pgvector cosine similarity search, filtered by source="episodic_memory"
    
    async def write_semantic(self, company_id: UUID, fact: str, embedding: List[float]):
        # Global knowledge base insert (company-scoped)
```

### 5.3 Integration Strategy: Safe Merge of External Concepts

The following table maps external concepts to HB-Proto-3 integration priority, with notes on cloud SaaS adaptations:

| Concept | Source | HB-Proto-3 Integration | Adaptation Note |
|---|---|---|---|
| Provider-agnostic tool interface with permissions | OpenCode | `schemas.py:ToolDefinition` | Add `permissions[]` field; enforce at `ToolExecutor` |
| Typed tool results | OpenCode | `tool_executor.py:ToolResult` | Replaces `Dict[str,Any]` return type |
| Session-scoped messages list | OpenCode | `ai/worker.py:_execute_thought` | Key fix for REACT loop (see §3.3) |
| Sandbox execution (E2B/subprocess) | OpenClaw | New `tools/sandbox_executor.py` | Start with asyncio subprocess; offer E2B as premium tier |
| 3-tier memory (working/episodic/semantic) | OpenClaw | `ai/memory_service.py` | Leverage existing pgvector; add episodic write on run completion |
| Tool rate limiting per run | OpenCode | `schemas.py:ToolDefinition.rate_limit_per_run` | Enforce in `ToolExecutor.execute_from_function_calls` |

**What NOT to import**: Both OpenCode and OpenClaw are **local, single-user** frameworks. Their session management, file system access patterns, and authentication are all process-local. Do not adopt:
- File system-based session storage (replaced by PostgreSQL + Redis)
- Process-local tool registries (replaced by the existing `ToolRegistry` with DB-backed integration)
- Single-user memory scoping (all memory must be `company_id`-scoped for multi-tenancy)

---

## 6. Appendix: Key Files Audited

| File | Lines | Focus Area |
|---|---|---|
| `backend/src/ai/service.py` | 440 | Entity CRUD, execution trigger, RAG search |
| `backend/src/ai/worker.py` | 1,287 | DAG executor, REACT loop, self-critique, billing |
| `backend/src/ai/models.py` | 189 | SQLAlchemy ORM models |
| `backend/src/ai/schemas.py` | 440 | Pydantic schemas, persona, plan step types |
| `backend/src/ai/tool_executor.py` | 223 | Tool dispatch, native FC & legacy regex paths |
| `backend/src/streaming/websocket_handler.py` | 914 | TwilioStreamHandler, TataStreamHandler, audio pipeline |
| `backend/src/streaming/gemini_live.py` | 294 | GeminiLiveClient, session config, voice config |
| `backend/src/streaming/session_manager.py` | 306 | Voice/WhatsApp session lifecycle |
| `backend/src/streaming/agent_loader.py` | 232 | Agent context loading, system prompt building |

---

## Roadmap Summary

```
Q2 2026 — Foundation Hardening (P0 Items)
  ├── [P0] Refactor TataStreamHandler → BaseStreamHandler mixin
  ├── [P0] Centralize API key resolution in ConfigService with TTL cache
  ├── [P0] Fix HITL approval notification (Redis pub/sub)
  └── [P0] Stream audio recording to disk/GCS instead of memory

Q3 2026 — Execution Engine Upgrade
  ├── [P1] Per-step AsyncSession isolation in DAG executor
  ├── [P1] Replace 5-level eager join with lazy execution tree API
  ├── [P1] Add Redis caching layer to SessionManager
  ├── [P2] Deprecate legacy regex tool calling path
  └── [P2] Migrate process_document to google-genai SDK

Q3-Q4 2026 — Autonomous Loop Evolution
  ├── Goal Decomposition Tree (Phase A)
  ├── Uncertainty/Clarification signals (Phase B)
  ├── Multi-turn content list REACT loop (replaces string accumulation)
  └── Episodic memory store (pgvector-backed)

Q4 2026 — Multi-Modal Personality & Voice v2.5
  ├── AgentPersona schema rollout + migration
  ├── PersonaService for dynamic prompt injection  
  ├── Gemini Live v2.5 Flash Native Audio config
  └── VoiceConfig per-agent with voice_name, speaking_rate, pitch

2027 — External Tool Ecosystem
  ├── Typed ToolResult with content_type
  ├── Permission-scoped tool declarations + enforcement
  ├── Sandbox execution (subprocess → E2B premium tier)
  └── 3-tier memory router (working / episodic / semantic)
```

---

*This report reflects the state of the codebase as of 2026-03-03. All line number references correspond to the files as audited on that date.*
