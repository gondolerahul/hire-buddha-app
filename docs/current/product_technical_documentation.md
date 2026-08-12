# HireBuddha — Product Technical Documentation

> **Platform Version:** 2.0.0 (GA)  
> **Author:** Buddha Cognitive Lab  
> **Last Updated:** June 2026  
> **Status:** Architecture & Systems Manual

---

## 1. System Architecture & Topology

The HireBuddha platform uses a multi-process, service-oriented architecture. Traffic routing, reverse proxying, and SSL termination are handled by a front-end Apache HTTP Server.

```
                           Internet (Client Requests)
                                       │
                         ┌─────────────▼─────────────┐
                         │   Apache HTTP (80/443)    │ (mod_ssl, VirtualHosts)
                         └─────────────┬─────────────┘
                                       │ (Reverse Proxy via mod_proxy_wstunnel)
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
┌─────────────────┐           ┌────────────────┐            ┌─────────────────┐
│ React Frontend  │           │  FastAPI App   │            │ Unified Gateway │
│ `localhost:3000`│           │ `localhost:8000`│           │ `localhost:8001`│
└─────────────────┘           └────────┬───────┘            └────────┬────────┘
                                       │ (SQL / Cache)               │ (WebSockets)
                                       ▼                             ▼
                              ┌────────────────┐            ┌─────────────────┐
                              │  PostgreSQL    │            │   Voice Server  │
                              │ `localhost:5433`│            │ `localhost:8002`│
                              └────────────────┘            └─────────────────┘
```

### 1.1 Apache Proxy Configuration
An example virtual host configuration snippet below details how subdomains are proxied to their respective backend services:

```apache
# App Frontend Proxy
<VirtualHost *:443>
    ServerName app.hirebuddha.com
    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/hirebuddha.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/hirebuddha.com/privkey.pem

    ProxyPreserveHost On
    ProxyPass / http://localhost:3000/
    ProxyPassReverse / http://localhost:3000/
</VirtualHost>

# Unified AI Gateway Proxy (supporting HTTP and WebSockets)
<VirtualHost *:443>
    ServerName api.hirebuddha.com
    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/hirebuddha.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/hirebuddha.com/privkey.pem

    ProxyPreserveHost On

    # WebSockets Handshake Routing
    ProxyPass /stream/audio ws://localhost:8001/stream/audio
    ProxyPassReverse /stream/audio ws://localhost:8001/stream/audio

    # REST Requests Routing
    ProxyPass / http://localhost:8001/
    ProxyPassReverse / http://localhost:8001/
</VirtualHost>
```

### 1.2 Core Directory File Index
*   `backend/src/ai/`: Agent Kernel execution logic.
    *   `core/`: Composes the control loops, state engines, step execution drivers, and scheduling queues.
        *   `agent_loop.py`: The control loop orchestrating perception, strategy, action, reflection, and decisions.
        *   `step_engine.py`: Single-step and parallel DAG execution wrapper.
        *   `agent_state.py`: Typed state envelope and JSON snapshot engine.
        *   `budget.py`: Tracks token caps, USD limits, and run latency.
        *   `feature_flags.py`: Feature flag overrides.
        *   `arq_jobs.py`: Worker tasks definition (`run_execution_recursive`, `resume_parent_run`).
    *   `planning/`: Generates plans and houses the Critic Pipeline and Strategic planners.
        *   `critic_pipeline.py`: Plugs in the pre-critic, post-critic, and supervisor pipelines.
        *   `strategist.py`: Selects next execution frames based on the current state.
        *   `planner_service.py`: Generates the step list for Processes.
    *   `memory/`: CORTEX engine, semantic indexers, and episodic memory.
        *   `cortex_service.py`: Tree memory interface.
        *   `cortex_bridge.py`: Bridges the agent loop to CORTEX node operations.
        *   `assembler.py`: Reconciles memories for prompt injection.
    *   `governance/`: Enforces billing checks, limits, and Human-in-the-loop (HITL) gateways.
        *   `governance_service.py`: Checks credit gates and processes final settlements.
        *   `rate_limiter.py`: Limits API calls using Redis.
    *   `orm/`: SQLAlchemy model definitions.
*   `backend/src/gateway/`: Proxy for real-time audio streams, WebRTC, and inbound webhooks.
    *   `dispatcher.py`: Routes inbound webhooks to background tasks.
*   `backend/src/voice/`: Audio processors, session managers, and Gemini Live/Azure Realtime adapters.
    *   `websocket_handler.py`: Bidirectional audio streaming WebSocket handler.
    *   `gemini_live.py`: Real Gemini Live SDK client.
    *   `azure_realtime.py`: Real Azure OpenAI Realtime client.

---

## 2. Database Schema & Core Models

All database models inherit from `src.common.database.Base` and are defined with SQLAlchemy 2.0's strict async `Mapped[]` type annotations.

### 2.1 The Agent Kernel: `hierarchical_entities`

```python
class HierarchicalEntity(Base):
    __tablename__ = "hierarchical_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=True)
    version: Mapped[str] = mapped_column(String, nullable=False, default="1.0.0")
    type: Mapped[str] = mapped_column(String, nullable=False)  # ACTION, SKILL, AGENT, PROCESS
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")
    name: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[Any] = mapped_column(JSON, nullable=True)

    # Configuration properties stored as structured JSON
    identity: Mapped[Any] = mapped_column(JSON, nullable=True)         # Tone, Empathy, Humor values
    hierarchy: Mapped[Any] = mapped_column(JSON, nullable=True)        # Linked child entity ids
    logic_gate: Mapped[Any] = mapped_column(JSON, nullable=True)       # Reasoning configuration
    planning: Mapped[Any] = mapped_column(JSON, nullable=True)         # Custom prompts configurations
    capabilities: Mapped[Any] = mapped_column(JSON, nullable=True)     # Bound tools and rate limit limits
    governance: Mapped[Any] = mapped_column(JSON, nullable=True)       # Max cost, timeout, and HITL checkpoints
    io_contract: Mapped[Any] = mapped_column(JSON, nullable=True)      # Input/Output variables schemas
    observability: Mapped[Any] = mapped_column(JSON, nullable=True)    # Trace logs settings
```

### 2.2 Execution Runs & Tracing: `execution_runs`

```python
class ExecutionRun(Base):
    __tablename__ = "execution_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchical_entities.id"), nullable=False)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_runs.id"), nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    input_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    dynamic_plan: Mapped[Any] = mapped_column(JSON, nullable=True)
    result_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    context_state: Mapped[Any] = mapped_column(JSON, nullable=True)     # Serialized AgentState snapshot
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Costs and Tokens accounting
    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    billed_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

### 2.3 Wallets & Subscriptions: `credit_wallets`

```python
class CreditWallet(Base):
    __tablename__ = "credit_wallets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    account_model: Mapped[str] = mapped_column(String, default="pay_as_you_go") # pay_as_you_go, subscription
    
    # Bucket Credits fields
    daily_credits: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    daily_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    wallet_balance: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    wallet_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    subscription_credits: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    subscription_bonus_credits: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    sub_credits_expire_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

---

## 3. Core AI Orchestration Engine (The AgentLoop)

The `AgentLoop` coordinates state transitions and execution within the platform.

### 3.1 Control Loop Code Workflow
The execution loop runs inside `AgentLoop._drive` and `AgentLoop._loop` via a state-machine workflow:

```
[BOOTSTRAP RUN]
      │
      ▼
┌──────────────┐
│  Perceive    │ ◄── [Re-read Cancel Status]
└──────┬───────┘
       │ (perception variables)
       ▼
┌──────────────┐
│  Strategize  │ ◄── [Retry Queue Check]
└──────┬───────┘
       │ (chosen_executor, move)
       ▼
┌──────────────┐
│  Pre-Critic  │ ───► [BLOCK] ──► [Consecutive Count >= 3?] ──► [ABORT]
└──────┬───────┘
       │ (PASS / REVISE)
       ▼
┌──────────────┐
│     Act      │ ───► [Awaiting Children?] ──► [SUSPEND STATE] ──► [release worker]
└──────┬───────┘
       │ (ActionResult)
       ▼
┌──────────────┐
│   Observe    │
└──────┬───────┘
       │ (novelty_score, outcome)
       ▼
┌──────────────┐
│ Post-Critics │
└──────┬───────┘
       │ (supervise recommendation)
       ▼
┌──────────────┐
│   Reflect    │ ───► [Write Reflection Node to CORTEX]
└──────┬───────┘
       │
       ▼
┌──────────────┐
│    Decide    │ ───► [REPLAN / CONTINUE / DONE / ABORT]
└──────────────┘
```

1.  **Perceive**: `Perceiver.gather` loads local inputs, semantic chunks, and updates the active context block.
2.  **Strategize**: `Strategist.next_move` selects a step or prompts the planner. It also evaluates if there are queued retries.
3.  **Pre-Critic**: `CriticPipeline.pre_action` audits the selected action. Consecutive rejections increment `consecutive_pre_critic_blocks`. If this reaches `_MAX_CONSECUTIVE_PRE_CRITIC_BLOCKS` (3), a circuit-breaker stops the execution.
4.  **Act**: Resolves and calls the step executor.
5.  **Observe**: `Observer.parse` processes step outputs and checks for runtime blocks.
6.  **Post-Critic**: The supervisor checks alignment, logs token usage, and schedules retries.
7.  **Reflect**: `Reflector.produce` writes logical reflections back to CORTEX tree memories.
8.  **Decide**: Checks flags and sets `state.done = True` if complete or aborted.

### 3.2 Async Suspend/Resume Child Dispatch Implementation
When a process triggers a child run, the execution is handled asynchronously to prevent blocking the worker thread:

#### 1. Suspend Event (`ChildEntityExecutor._dispatch_async`)
*   Inserts a new `execution_runs` row with `parent_run_id` set to the parent's run ID.
*   Enqueues the child run via Redis/Arq.
*   Returns an `awaiting_children` list to the loop:
    ```json
    [{"run_id": "child-run-uuid-string", "step_id": "parent-step-id", "status": "PENDING"}]
    ```
*   The parent loop captures the result, serializes the complete `AgentState` object using `state.snapshot()`, stores it in `run.context_state["__agent_state_snapshot__"]`, sets the status to `WAITING_ON_CHILDREN`, and releases the execution worker.

#### 2. Resume Event (`resume_parent_run` worker job)
*   Triggered when the child run reaches a terminal state.
*   Resolves the parent run, checking that its status is `WAITING_ON_CHILDREN`.
*   Deserializes the state snapshot using `AgentState.restore(snapshot)`.
*   Calls `_fold_children` to merge the child's outputs and costs:
    ```python
    # Deduct child cost from parent budget
    state.budget.consume(
        usd=Decimal(str(child_run.total_cost_usd or 0)),
        tokens=int(child_run.total_tokens or 0)
    )
    # Store child output in parent context
    state.context_state[step_id] = child_run.result_data.get("output", "")
    state.mark_step_complete(step_id)
    ```
*   Resumes execution via `AgentLoop._drive`.

---

## 4. Memory System & CORTEX Technical Details

### 4.1 Semantic Query matching (pgvector)
HireBuddha uses `pgvector` for similarity matching:

```sql
SELECT content, 1 - (embedding <=> :query_embedding) AS similarity
FROM document_chunks
WHERE document_id IN (:doc_ids)
  AND 1 - (embedding <=> :query_embedding) > 0.70
ORDER BY similarity DESC
LIMIT 5;
```

### 4.2 CORTEX Context Viewport
CORTEX organizes data into hierarchical trees. A viewport parser limits the size of context injected into the prompt, resolving context window limitations:

```python
def get_viewport_context(tree: CortexTree, cursor_node_id: UUID, max_tokens: int = 8000) -> str:
    # 1. Walk up the parent tree from the cursor node
    path = tree.get_path_to_root(cursor_node_id)
    
    # 2. Add sibling context nodes based on relevance
    nodes = prune_and_rank_by_relevance(path, target_query=None)
    
    # 3. Serialize nodes until the max_tokens limit is reached
    serialized = []
    accumulated_tokens = 0
    for node in nodes:
        node_text = f"[{node.type.upper()}] {node.title}: {node.content}\n"
        tokens = count_tokens_fn(node_text)
        if accumulated_tokens + tokens > max_tokens:
            break
        serialized.append(node_text)
        accumulated_tokens += tokens
        
    return "\n".join(serialized)
```

If the node count exceeds the configured limit, the system summarizes historical nodes and records the output in a `checkpoint` node, freeing up context space.

---

## 5. Voice WebSocket Handler

Real-time voice calls are processed by `websocket_handler.py`.

```
[Twilio Inbound Connection]
            │ (SIP / RTP Stream)
            ▼
[Unified Gateway (mod_proxy_wstunnel)]
            │ (ws://streaming.hirebuddha.com/stream/audio)
            ▼
[FastAPI / voice/websocket_handler.py]
            │ (PCM Chunks / WebSockets)
            ▼
[gemini_live.py / LiveClient]
            │ (LiveConnect Session)
            ▼
[Google Gemini Live API]
```

### 5.1 Inbound Audio Processing Loop
```python
async def receive_from_twilio(websocket: WebSocket, gemini_session: GeminiLiveSession):
    async for message in websocket.iter_text():
        data = json.loads(message)
        if data.get("event") == "media":
            # Twilio streams Mu-law or A-law compressed packets
            payload = base64.b64decode(data["media"]["payload"])
            
            # Decompress Mu-law payload to 16kHz linear PCM
            pcm16_data = audio_processor.ulaw_to_pcm(payload)
            
            # Stream 20ms audio chunks to Gemini Live
            await gemini_session.send_audio(pcm16_data)
```

### 5.2 Outbound Audio Processing Loop
```python
async def send_to_twilio(websocket: WebSocket, gemini_session: GeminiLiveSession):
    async for response in gemini_session.receive():
        if response.server_content and response.server_content.model_turn:
            for part in response.server_content.model_turn.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("audio/"):
                    pcm_chunk = part.inline_data.data
                    
                    # Compress 16kHz PCM down to Twilio's Mu-law standard
                    ulaw_payload = audio_processor.pcm_to_ulaw(pcm_chunk)
                    
                    # Send media event to Twilio
                    await websocket.send_text(json.dumps({
                        "event": "media",
                        "media": {
                            "payload": base64.b64encode(ulaw_payload).decode("utf-8")
                        }
                    }))
```

---

## 6. Billing & Credits Engine

### 6.1 TB Billing Calculation
The system calculates usage costs using the **TB Billing Formula**:

```python
def calculate_tb(
    base_cost: Decimal,
    multiplier_factor: Decimal,
    platform_fee_pct: Decimal,
    sales_partner_fee_pct: Decimal,
    discount_pct: Decimal
) -> dict:
    """
    Calculate final billed amount from base cost.
    Formula:
      billed = (base_cost * multiplier)
             + (base_cost * multiplier * platform_fee)
             + (base_cost * multiplier * partner_fee)
             - (base_cost * multiplier * discount)
    """
    markup = base_cost * multiplier_factor
    platform_charge = markup * (platform_fee_pct / Decimal("100"))
    partner_charge = markup * (sales_partner_fee_pct / Decimal("100"))
    discount_amount = markup * (discount_pct / Decimal("100"))
    
    total_billing = markup + platform_charge + partner_charge - discount_amount
    
    return {
        "markup": markup,
        "platform_charge": platform_charge,
        "partner_charge": partner_charge,
        "discount_amount": discount_amount,
        "total_billing": max(total_billing, Decimal("0"))
    }
```

---

## 7. Security & Encryption

### 7.1 AES-256-GCM Symmetric Cipher Implementation
API keys and social media tokens are encrypted before saving to database columns:

```python
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def encrypt_vault_secret(secret_text: str, key_hex: str) -> str:
    """Encrypt integrations key using the master hex key."""
    key_bytes = bytes.fromhex(key_hex)
    aesgcm = AESGCM(key_bytes)
    nonce = os.urandom(12)  # 12-byte initialization vector
    
    ciphertext = aesgcm.encrypt(nonce, secret_text.encode("utf-8"), None)
    
    # Prepend nonce to cipher bytes before saving as hex
    return (nonce + ciphertext).hex()

def decrypt_vault_secret(encrypted_hex: str, key_hex: str) -> str:
    """Decrypt integrations key using the master hex key."""
    key_bytes = bytes.fromhex(key_hex)
    aesgcm = AESGCM(key_bytes)
    raw_data = bytes.fromhex(encrypted_hex)
    
    nonce = raw_data[:12]
    ciphertext = raw_data[12:]
    
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode("utf-8")
```

### 7.2 Company Suspension ASGI Middleware
The platform blocks suspended companies using an ASGI middleware layer:

```python
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from src.auth.service import CompanyService

class CompanySuspensionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Bypass check for public paths
        if request.url.path in ("/health", "/api/v1/auth/login", "/api/v1/auth/register"):
            return await call_next(request)
            
        # 2. Extract company_id from request state (populated by auth)
        company_id = request.state.company_id if hasattr(request.state, "company_id") else None
        
        if company_id:
            # 3. Check suspension status in database
            is_suspended = await CompanyService.is_company_suspended(company_id)
            if is_suspended:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Access denied: Account is suspended due to unpaid invoice."}
                )
                
        return await call_next(request)
```

---

## 8. Frontend ReactFlow Node Serialization

In the canvas dashboard (`frontend/src/pages/ai/EntityFlow.tsx`), user interactions serialize flows into the entity database schema:

```typescript
interface ReactFlowEdge {
  id: string;
  source: string; // parent step id
  target: string; // child step id
}

interface ReactFlowNode {
  id: string;
  type: string;
  data: {
    label: string;
    stepConfig: {
      type: string;
      target: {
        prompt_template: string;
        tool_id?: string;
      };
    };
  };
}

// Compiles ReactFlow state into the backend hierarchical json schema
function serializeFlow(nodes: ReactFlowNode[], edges: ReactFlowEdge[]): any {
  return nodes.map(node => {
    // 1. Find dependency links pointing to this node
    const inputDependencies = edges
      .filter(edge => edge.target === node.id)
      .map(edge => edge.source);

    // 2. Format structure matching PlanStep schema
    return {
      step_id: node.id,
      name: node.data.label,
      type: node.data.stepConfig.type,
      target: {
        ...node.data.stepConfig.target,
        input_dependencies: inputDependencies,
      }
    };
  });
}
```
