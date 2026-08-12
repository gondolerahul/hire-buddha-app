# HireBuddha — Architecture Diagrams

> **Platform Version:** 2.0.0 (GA)  
> **Author:** Buddha Cognitive Lab  
> **Last Updated:** July 2026  
> **Status:** Architecture Reference — Visual Atlas

---

## Table of Contents

1. [High-Level System Topology](#1-high-level-system-topology)
2. [Agent Hierarchy — The Four Organizational Tiers](#2-agent-hierarchy--the-four-organizational-tiers)
3. [The Agentic Loop — Core Control Flow](#3-the-agentic-loop--core-control-flow)
4. [CORTEX Memory Architecture](#4-cortex-memory-architecture)
5. [Four-Domain Memory System](#5-four-domain-memory-system)
6. [Dreaming & Learning Pipeline](#6-dreaming--learning-pipeline)
7. [Meta Agent — Architecture Board](#7-meta-agent--architecture-board)
8. [Critic Pipeline — Four-Stage Quality Gates](#8-critic-pipeline--four-stage-quality-gates)
9. [Governance & Billing Engine](#9-governance--billing-engine)
10. [Async Suspend/Resume — Child Dispatch](#10-async-suspendresume--child-dispatch)
11. [Voice Subsystem — Real-Time Audio Pipeline](#11-voice-subsystem--real-time-audio-pipeline)
12. [Execution Reasoning Strategies](#12-execution-reasoning-strategies)
13. [Multi-Tenant Security Architecture](#13-multi-tenant-security-architecture)
14. [Intelligence Rule Lifecycle](#14-intelligence-rule-lifecycle)
15. [Meta Intelligence Tree — Platform Knowledge Graph](#15-meta-intelligence-tree--platform-knowledge-graph)

---

## 1. High-Level System Topology

The platform uses a multi-process, service-oriented architecture with Apache HTTP as the edge reverse proxy, SSL terminator, and WebSocket upgrader.

```mermaid
graph TB
    subgraph Internet
        CLIENT["🌐 Client Browsers & Mobile Apps"]
        TWILIO["📞 Twilio / Smartflo / Exotel"]
    end

    subgraph Edge["Edge Layer — Apache HTTP (ports 80/443)"]
        APACHE["Apache HTTP Server<br/>mod_ssl · mod_proxy · mod_proxy_wstunnel"]
    end

    subgraph Application["Application Layer"]
        REACT["⚛️ React Frontend<br/>localhost:3000<br/>app.hirebuddha.com"]
        FASTAPI["⚡ FastAPI Backend<br/>localhost:8000<br/>Internal API"]
        GATEWAY["🔌 Unified AI Gateway<br/>localhost:8001<br/>api.hirebuddha.com"]
        VOICE["🎙️ Voice Server<br/>localhost:8002<br/>Audio Processing"]
    end

    subgraph Data["Data & Queue Layer"]
        PG["🐘 PostgreSQL<br/>localhost:5433<br/>+ pgvector"]
        REDIS["🔴 Redis<br/>Cache · Queues · SSE Pub/Sub"]
        ARQ["⚙️ Arq Workers<br/>Background Task Execution"]
    end

    subgraph External["External AI Providers"]
        GEMINI["Google Gemini API<br/>LLM + Embeddings + Live Voice"]
        OPENAI["Azure OpenAI<br/>GPT-4o Realtime"]
        TOOLS["External Tool APIs<br/>Search · Scrape · Social"]
    end

    CLIENT --> APACHE
    TWILIO --> APACHE
    APACHE -->|"ProxyPass /"| REACT
    APACHE -->|"ProxyPass /api"| FASTAPI
    APACHE -->|"ProxyPass ws://"| GATEWAY
    GATEWAY --> VOICE
    FASTAPI --> PG
    FASTAPI --> REDIS
    REDIS --> ARQ
    ARQ --> PG
    VOICE --> GEMINI
    VOICE --> OPENAI
    ARQ --> GEMINI
    ARQ --> TOOLS

    style APACHE fill:#1a1a2e,stroke:#e94560,color:#fff
    style REACT fill:#0f3460,stroke:#16213e,color:#fff
    style FASTAPI fill:#0f3460,stroke:#16213e,color:#fff
    style GATEWAY fill:#0f3460,stroke:#16213e,color:#fff
    style VOICE fill:#0f3460,stroke:#16213e,color:#fff
    style PG fill:#1a1a2e,stroke:#533483,color:#fff
    style REDIS fill:#1a1a2e,stroke:#e94560,color:#fff
    style ARQ fill:#1a1a2e,stroke:#533483,color:#fff
    style GEMINI fill:#2d4059,stroke:#ea5455,color:#fff
    style OPENAI fill:#2d4059,stroke:#ea5455,color:#fff
    style TOOLS fill:#2d4059,stroke:#ea5455,color:#fff
```

---

## 2. Agent Hierarchy — The Four Organizational Tiers

HireBuddha structures autonomous agents into an organizational hierarchy inspired by corporate structure. Each tier maps to a `HierarchicalEntity` type with distinct execution semantics.

```mermaid
graph TB
    subgraph Hierarchy["🏢 HierarchicalEntity Hierarchy"]
        PROCESS["🏛️ PROCESS<br/><i>C-Suite Orchestrator</i><br/>────────────────<br/>Executor: DAG / Parallel / Debate<br/>Example: 'Quarterly Lead Nurture Campaign'<br/>Coordinates multiple Agents"]
        AGENT["🧑‍💼 AGENT<br/><i>Manager / Department Head</i><br/>────────────────<br/>Executor: Dialog / SingleStep / Recursive<br/>Example: 'Sarah — Lead Qualification Rep'<br/>Manages channel & domain context"]
        SKILL["⚡ SKILL<br/><i>Specialist / Task Executor</i><br/>────────────────<br/>Executor: ToolBurst / SingleStep<br/>Example: 'Contract Generation & E-Sign'<br/>Single focused technical task"]
        ACTION["🔧 ACTION<br/><i>Individual Worker</i><br/>────────────────<br/>Executor: Built-in Tool Call<br/>Example: 'Query Salesforce for Company ID'<br/>Atomic tool-assisted execution"]
    end

    PROCESS -->|"spawns & coordinates"| AGENT
    AGENT -->|"delegates specialized work"| SKILL
    SKILL -->|"invokes atomic tools"| ACTION

    subgraph Execution["Execution Relationship"]
        direction LR
        P_RUN["Process Run<br/>parent_run_id = NULL"]
        A_RUN["Agent Run<br/>parent_run_id = Process"]
        S_RUN["Skill Run<br/>parent_run_id = Agent"]
        AC_RUN["Action Run<br/>parent_run_id = Skill"]
    end

    P_RUN -->|"child dispatch"| A_RUN
    A_RUN -->|"child dispatch"| S_RUN
    S_RUN -->|"child dispatch"| AC_RUN

    style PROCESS fill:#6c3483,stroke:#8e44ad,color:#fff
    style AGENT fill:#2874a6,stroke:#2e86c1,color:#fff
    style SKILL fill:#1e8449,stroke:#27ae60,color:#fff
    style ACTION fill:#b9770e,stroke:#d4ac0d,color:#fff
```

### Entity Configuration Schema

```mermaid
graph LR
    subgraph Entity["HierarchicalEntity JSON Columns"]
        IDENTITY["🎭 identity<br/>Tone · Empathy · Humor · Formality"]
        HIERARCHY["🔗 hierarchy<br/>Linked child entity IDs"]
        LOGIC["🧠 logic_gate<br/>Reasoning configuration<br/>ReAct · CoT · TreeOfThoughts"]
        PLANNING["📋 planning<br/>Custom prompt configurations"]
        CAPS["🛠️ capabilities<br/>Bound tools · Rate limits"]
        GOV["🛡️ governance<br/>Max cost · Timeout · HITL checkpoints"]
        IO["📊 io_contract<br/>Input/Output variable schemas"]
        OBS["👁️ observability<br/>Trace log settings"]
    end

    style IDENTITY fill:#2c3e50,stroke:#e74c3c,color:#fff
    style HIERARCHY fill:#2c3e50,stroke:#e74c3c,color:#fff
    style LOGIC fill:#2c3e50,stroke:#e74c3c,color:#fff
    style PLANNING fill:#2c3e50,stroke:#e74c3c,color:#fff
    style CAPS fill:#2c3e50,stroke:#e74c3c,color:#fff
    style GOV fill:#2c3e50,stroke:#e74c3c,color:#fff
    style IO fill:#2c3e50,stroke:#e74c3c,color:#fff
    style OBS fill:#2c3e50,stroke:#e74c3c,color:#fff
```

---

## 3. The Agentic Loop — Core Control Flow

The `AgentLoop` is the unified execution kernel for every entity type. It implements a **perceive → strategize → pre-critic → act → observe → post-critic → alignment → supervisor → reflect → decide** state machine.

```mermaid
flowchart TB
    START(["🚀 AgentLoop.run(run_id)"]) --> BOOTSTRAP["BOOTSTRAP RUN<br/>Load entity · Deserialize AgentState<br/>Initialize Budget · Compose services"]

    BOOTSTRAP --> PERCEIVE

    subgraph LOOP["🔄 _loop() — Per-Iteration State Machine"]
        PERCEIVE["👁️ PERCEIVE<br/>────────────────<br/>Perceiver.gather()<br/>• CORTEX viewport text<br/>• Intelligence rules<br/>• Recent reflections<br/>• Similar past runs<br/>• Budget pressure<br/>• Pending HITL<br/>• Open subgoals"]

        PERCEIVE --> STRATEGIZE["🎯 STRATEGIZE<br/>────────────────<br/>Strategist.next_move()<br/>• Select executor type<br/>• Choose plan step<br/>• Check retry queue<br/>• Consult PlanStyleBandit"]

        STRATEGIZE --> PRE_CRITIC["🔍 PRE-CRITIC<br/>────────────────<br/>CriticPipeline.pre_action()<br/>• Audit selected action<br/>• PASS / REVISE / BLOCK"]

        PRE_CRITIC -->|"BLOCK"| BLOCK_CHECK{"Consecutive<br/>blocks ≥ 3?"}
        BLOCK_CHECK -->|"Yes"| ABORT_PC["⛔ ABORT<br/>Circuit breaker triggered"]
        BLOCK_CHECK -->|"No"| PERCEIVE

        PRE_CRITIC -->|"PASS / REVISE"| ACT["⚡ ACT<br/>────────────────<br/>Execute via chosen executor<br/>• DAG · Recursive · SingleStep<br/>• ChildEntity · Dialog · Debate<br/>• ToolBurst · Skill"]

        ACT -->|"awaiting_children"| SUSPEND["⏸️ SUSPEND<br/>Serialize AgentState snapshot<br/>Set status: WAITING_ON_CHILDREN<br/>Release worker thread"]

        ACT -->|"ActionResult"| OBSERVE["📊 OBSERVE<br/>────────────────<br/>Observer.parse()<br/>• novelty_score<br/>• outcome: success/fail/partial/blocked<br/>• runtime blockers"]

        OBSERVE --> POST_CRITIC["📝 POST-CRITIC<br/>────────────────<br/>CriticPipeline.post_action()<br/>• Evaluate output quality<br/>• Tag failures (FailureTag enum)<br/>• Log token usage"]

        POST_CRITIC --> ALIGNMENT["⚖️ ALIGNMENT CHECK<br/>────────────────<br/>goal_alignment verifier<br/>• Compare output vs entity goal<br/>• Detect drift"]

        ALIGNMENT --> SUPERVISOR["👨‍⚖️ SUPERVISOR<br/>────────────────<br/>SupervisorCritic.assess()<br/>• Budget-pressure short-circuit<br/>• 3-clean-step fast path<br/>• Propose subgoals on REPLAN"]

        SUPERVISOR --> REFLECT["💭 REFLECT<br/>────────────────<br/>Reflector.produce()<br/>• what_worked / what_didnt<br/>• proposed_change<br/>• scope escalation: run → entity<br/>• Write candidate to IntelligenceTree"]

        REFLECT --> DECIDE["🤔 DECIDE<br/>────────────────<br/>Check flags & budget<br/>• CONTINUE → next iteration<br/>• REPLAN → regenerate plan<br/>• DONE → finalize success<br/>• ABORT → finalize failure"]

        DECIDE -->|"CONTINUE"| PERCEIVE
        DECIDE -->|"REPLAN"| REPLAN["📋 REPLAN<br/>PlanGenerator.generate()<br/>Multi-candidate · Invariant filter"]
        REPLAN --> PERCEIVE
    end

    DECIDE -->|"DONE"| FINALIZE["✅ FINALIZE<br/>Record costs · Settle billing<br/>Trigger dreaming_outcome<br/>Resume parent if child"]
    DECIDE -->|"ABORT"| FINALIZE_ERR["❌ FINALIZE ERROR<br/>Record error · Settle billing<br/>Resume parent with failure"]
    ABORT_PC --> FINALIZE_ERR

    style START fill:#e74c3c,stroke:#c0392b,color:#fff
    style PERCEIVE fill:#8e44ad,stroke:#9b59b6,color:#fff
    style STRATEGIZE fill:#2980b9,stroke:#3498db,color:#fff
    style PRE_CRITIC fill:#d35400,stroke:#e67e22,color:#fff
    style ACT fill:#27ae60,stroke:#2ecc71,color:#fff
    style OBSERVE fill:#2c3e50,stroke:#34495e,color:#fff
    style POST_CRITIC fill:#d35400,stroke:#e67e22,color:#fff
    style ALIGNMENT fill:#c0392b,stroke:#e74c3c,color:#fff
    style SUPERVISOR fill:#8e44ad,stroke:#9b59b6,color:#fff
    style REFLECT fill:#16a085,stroke:#1abc9c,color:#fff
    style DECIDE fill:#2c3e50,stroke:#7f8c8d,color:#fff
    style SUSPEND fill:#7f8c8d,stroke:#95a5a6,color:#fff
    style FINALIZE fill:#27ae60,stroke:#2ecc71,color:#fff
```

### Budget Tracking Per Iteration

```mermaid
graph LR
    BUDGET["📊 Budget Object<br/>────────────────<br/>tokens_max · tokens_used<br/>usd_max · usd_used<br/>wall_max · wall_elapsed<br/>iters_max · iters_used"]

    BUDGET -->|"pressure()"| PRESSURE["Pressure Score<br/>0.0 = fresh<br/>1.0 = exhausted"]
    BUDGET -->|"consume(usd, tokens)"| DEDUCT["Deduct per step"]
    BUDGET -->|"exhausted()"| EXHAUST{"Budget<br/>exhausted?"}
    EXHAUST -->|"Yes"| ABORT["ABORT run"]
    EXHAUST -->|"No"| CONTINUE["Continue iteration"]

    style BUDGET fill:#1a1a2e,stroke:#e94560,color:#fff
```

---

## 4. CORTEX Memory Architecture

CORTEX is a hierarchical tree memory structure that organizes all durable knowledge into typed nodes. Agents never get raw context — they receive a **viewport** over the tree.

```mermaid
graph TB
    subgraph CortexTree["🌳 CORTEX Tree (Per Entity)"]
        ROOT["🏠 ROOT<br/>Entity-scoped tree root"]

        ROOT --> KNOW["📚 KNOWLEDGE<br/>Uploaded docs · Web findings<br/>Semantic vector chunks"]
        ROOT --> TASK["📋 TASK<br/>Current execution task<br/>Input summary"]
        ROOT --> FIND["🔍 FINDING<br/>Step results · Tool outputs<br/>Intermediate discoveries"]
        ROOT --> OUTPUT["📤 OUTPUT<br/>Final deliverables<br/>Generated artifacts"]
        ROOT --> CHECKPOINT["📌 CHECKPOINT<br/>Auto-summary when context<br/>exceeds 8000 tokens"]

        KNOW --> K1["chunk: 'Company pricing policy...'"]
        KNOW --> K2["chunk: 'Product FAQ section 3...'"]

        TASK --> T1["task: 'Qualify lead John Doe'"]

        FIND --> F1["finding: 'John is VP at Acme Corp'"]
        FIND --> F2["finding: 'Acme revenue $50M ARR'"]

        OUTPUT --> O1["output: 'Qualification report PDF'"]

        CHECKPOINT --> CP1["checkpoint: Summary of steps 1-15<br/>Frees context window"]
    end

    subgraph Viewport["👁️ Viewport Assembly"]
        VP_WALK["1. Walk up parent path<br/>from cursor node"]
        VP_SIBLING["2. Add sibling nodes<br/>ranked by relevance"]
        VP_SERIALIZE["3. Serialize until<br/>max_tokens reached (8000)"]
        VP_OUTPUT["4. Inject into<br/>LLM prompt"]
    end

    VP_WALK --> VP_SIBLING --> VP_SERIALIZE --> VP_OUTPUT

    ROOT -.->|"viewport cursor"| VP_WALK

    subgraph Operations["🔧 CORTEX 7 Operations"]
        OP1["NAVIGATE — Move cursor to a node"]
        OP2["READ — Read node content"]
        OP3["WRITE — Create/update node (Provenance-aware)"]
        OP4["RECURSE — Walk subtree"]
        OP5["AWAIT_CHILDREN — Wait for child runs"]
        OP6["CHECKPOINT — Auto-summarize & compress"]
        OP7["SCOPE POLICY — Enforce read/write boundaries"]
    end

    style ROOT fill:#6c3483,stroke:#8e44ad,color:#fff
    style KNOW fill:#2874a6,stroke:#2e86c1,color:#fff
    style TASK fill:#1e8449,stroke:#27ae60,color:#fff
    style FIND fill:#b9770e,stroke:#d4ac0d,color:#fff
    style OUTPUT fill:#c0392b,stroke:#e74c3c,color:#fff
    style CHECKPOINT fill:#7f8c8d,stroke:#95a5a6,color:#fff
```

### Scope Policy Enforcement

```mermaid
graph LR
    WRITE_REQ["Write Request"] --> SCOPE{"ScopePolicy<br/>Check"}
    SCOPE -->|"Within scoped_subtree_root"| ALLOW["✅ Write Allowed<br/>Provenance stamped"]
    SCOPE -->|"Outside boundary"| DENY["❌ ScopeViolation<br/>Write rejected"]

    subgraph Provenance["📜 Provenance Tracking"]
        PROV["source_type: tool_output | llm | user_upload<br/>trust_score: 0.0 — 1.0<br/>tool_id: web_search<br/>url: source URL"]
    end

    ALLOW --> PROV

    style SCOPE fill:#8e44ad,stroke:#9b59b6,color:#fff
    style ALLOW fill:#27ae60,stroke:#2ecc71,color:#fff
    style DENY fill:#e74c3c,stroke:#c0392b,color:#fff
```

---

## 5. Four-Domain Memory System

Memory is organized into four typed domains, each with distinct retrieval weights. The `MemoryAssemblyService` orchestrates retrieval across all domains and injects the assembled result into the agent's context.

```mermaid
graph TB
    subgraph MemoryDomains["🧠 Four Memory Domains over CORTEX"]
        KNOWLEDGE["📚 KnowledgeTree<br/>────────────────<br/>Uploaded documents<br/>Web search results<br/>External data<br/><br/>Weights:<br/>semantic: 0.6<br/>recency: 0.1<br/>user_match: 0.1<br/>success: 0.2"]

        EPISODIC["📝 EpisodicTree<br/>────────────────<br/>Conversation history<br/>Per-user interactions<br/>Dialog turns<br/><br/>Weights:<br/>semantic: 0.3<br/>recency: 0.4<br/>user_match: 0.2<br/>success: 0.1"]

        EXPERIENCE["🏆 ExperienceTree<br/>────────────────<br/>Past run outcomes<br/>Tool call patterns<br/>Success/failure signals<br/><br/>Weights:<br/>semantic: 0.4<br/>recency: 0.2<br/>user_match: 0.1<br/>success: 0.3"]

        INTELLIGENCE["💡 IntelligenceTree<br/>────────────────<br/>Learned rules<br/>Strategy patterns<br/>Candidate → Confirmed → Retired<br/><br/>Weights:<br/>semantic: 0.5<br/>recency: 0.15<br/>user_match: 0.05<br/>success: 0.3"]
    end

    subgraph Assembly["🔧 Memory Assembly Pipeline"]
        ASSEMBLER["assemble_memory()"]
        MAS["MemoryAssemblyService<br/>v2 4-domain retrieval"]
        LEGACY["LegacyEpisodicReader<br/>Flat-table top-up for<br/>freshly migrated entities"]
    end

    ASSEMBLER -->|"v2 canonical path"| MAS
    MAS --> KNOWLEDGE
    MAS --> EPISODIC
    MAS --> EXPERIENCE
    MAS --> INTELLIGENCE
    ASSEMBLER -->|"first-run fallback"| LEGACY

    subgraph Scopes["Memory Scopes"]
        FULL["FULL — All 4 domains"]
        RUN["RUN_SCOPED — All 4 domains"]
        INTEL["INTELLIGENCE_ONLY"]
        KNOW_S["KNOWLEDGE_ONLY + Intelligence"]
        NONE_S["NONE — Skip memory"]
    end

    subgraph Output["📤 Assembled Output"]
        MEM_PROMPT["__memory__<br/>Formatted prompt text"]
        INTEL_RULES["__intelligence_rules__<br/>Active learned rules"]
        EPIS_CTX["__episodic_memory__<br/>Conversation context"]
    end

    MAS --> MEM_PROMPT
    MAS --> INTEL_RULES
    MAS --> EPIS_CTX

    style KNOWLEDGE fill:#2874a6,stroke:#2e86c1,color:#fff
    style EPISODIC fill:#8e44ad,stroke:#9b59b6,color:#fff
    style EXPERIENCE fill:#27ae60,stroke:#2ecc71,color:#fff
    style INTELLIGENCE fill:#d4ac0d,stroke:#f1c40f,color:#000
    style ASSEMBLER fill:#1a1a2e,stroke:#e94560,color:#fff
```

---

## 6. Dreaming & Learning Pipeline

The Dreaming Engine is the platform's **offline learning system**. It runs as a background pipeline triggered by run outcomes and scheduled crons, distilling raw execution experience into confirmed intelligence rules that improve future agent behavior.

```mermaid
flowchart TB
    subgraph Triggers["🔔 Dreaming Triggers"]
        OUTCOME["Run Outcome Trigger<br/>AgentLoop._finalize() →<br/>dreaming_outcome_trigger"]
        CRON["Scheduled Cron Job<br/>Periodic consolidation"]
    end

    subgraph Phase1["Phase 1: Observation Collection"]
        COLLECT["📥 Collect Observations<br/>────────────────<br/>• Step health records<br/>• Critic verdicts & tags<br/>• Post-critic failure tags<br/>• Reflector outputs<br/>• Budget consumption data<br/>• Tool success/failure rates"]
    end

    subgraph Phase2["Phase 2: Pattern Detection"]
        PATTERNS["🔍 Pattern Detection<br/>────────────────<br/>• Recurring failure modes<br/>• Successful tool chains<br/>• Strategy effectiveness<br/>• Cross-run correlations"]

        EMBEDDING["🧮 Embedding Analysis<br/>────────────────<br/>• Semantic similarity matching<br/>• Cluster similar observations<br/>• NN task classification"]
    end

    subgraph Phase3["Phase 3: Rule Distillation"]
        DISTILL["🧪 Distillation<br/>────────────────<br/>LLM-based pattern synthesis<br/>Generate candidate rules<br/>from observed patterns"]

        CANDIDATE["📝 Candidate Rule<br/>lifecycle: CANDIDATE<br/>Written to IntelligenceTree"]
    end

    subgraph Phase4["Phase 4: Validation & Promotion"]
        VALIDATE["✅ Validation Loop<br/>────────────────<br/>Compare candidate against<br/>subsequent run outcomes"]

        PROMOTE{"Net validations<br/>≥ 3?"}
        CONFIRMED["🏆 CONFIRMED Rule<br/>Active in planner/critic prompts"]
        STILL_CAND["⏳ Still CANDIDATE<br/>Keep observing"]

        RETIRE{"Net contradictions<br/>≥ 3?"}
        RETIRED["🗄️ RETIRED Rule<br/>Excluded from prompts"]
    end

    subgraph TrustLearning["🔐 Trust Score Learning"]
        TRUST["TrustLearner<br/>────────────────<br/>Bayesian Beta-posterior<br/>per knowledge source<br/><br/>(prior·k + successes)<br/>/ (k + observations)<br/><br/>Converges to observed<br/>success rate"]
    end

    OUTCOME --> COLLECT
    CRON --> COLLECT
    COLLECT --> PATTERNS
    PATTERNS --> EMBEDDING
    EMBEDDING --> DISTILL
    DISTILL --> CANDIDATE
    CANDIDATE --> VALIDATE
    VALIDATE --> PROMOTE
    PROMOTE -->|"Yes"| CONFIRMED
    PROMOTE -->|"No"| STILL_CAND
    CONFIRMED --> RETIRE
    RETIRE -->|"Yes"| RETIRED
    RETIRE -->|"No"| CONFIRMED

    COLLECT --> TRUST

    CONFIRMED -.->|"injected into"| PERCEIVER["Perceiver.gather()<br/>intelligence_rules[]"]
    CONFIRMED -.->|"consumed by"| CRITIC["CriticPipeline<br/>Pre/Post judgment"]
    CONFIRMED -.->|"consumed by"| STRATEGIST["Strategist<br/>next_move()"]

    style OUTCOME fill:#e74c3c,stroke:#c0392b,color:#fff
    style CRON fill:#e74c3c,stroke:#c0392b,color:#fff
    style DISTILL fill:#8e44ad,stroke:#9b59b6,color:#fff
    style CANDIDATE fill:#d4ac0d,stroke:#f1c40f,color:#000
    style CONFIRMED fill:#27ae60,stroke:#2ecc71,color:#fff
    style RETIRED fill:#7f8c8d,stroke:#95a5a6,color:#fff
    style TRUST fill:#2874a6,stroke:#2e86c1,color:#fff
```

### Skill Library — Emergent Skill Detection

```mermaid
flowchart LR
    RUNS["Recent 50 Runs<br/>per entity"] --> EXTRACT["Extract consecutive<br/>successful tool chains"]
    EXTRACT --> TALLY["Tally chain frequency<br/>across runs"]
    TALLY --> THRESHOLD{"Same chain seen<br/>≥ 5 times?"}
    THRESHOLD -->|"Yes"| SKILL_CAND["📋 skill_candidate<br/>Written to MetaIntelligenceTree<br/>Under '🎯 Spec Patterns'"]
    THRESHOLD -->|"No"| SKIP["Skip — not enough evidence"]
    SKILL_CAND --> HITL["🙋 HITL Approval<br/>Human must explicitly promote"]
    HITL --> SKILL_ENTITY["⚡ New SKILL Entity<br/>Auto-composed from chain"]

    style SKILL_CAND fill:#d4ac0d,stroke:#f1c40f,color:#000
    style HITL fill:#e74c3c,stroke:#c0392b,color:#fff
    style SKILL_ENTITY fill:#27ae60,stroke:#2ecc71,color:#fff
```

---

## 7. Meta Agent — Architecture Board

The Meta Agent is a special agent that **designs, validates, tests, and promotes other agents**. It runs through the same `AgentLoop` but has an internal multi-role **Architecture Board** that turns user requests into production-ready `HierarchicalEntity` definitions.

```mermaid
flowchart TB
    USER_REQ["👤 User Request<br/>'I need a Sales SDR Agent'"] --> META_LOOP["🔄 Meta Agent<br/>runs through standard AgentLoop"]

    META_LOOP --> BOARD

    subgraph BOARD["🏛️ Architecture Board — 7 Roles (Sequential Pipeline)"]
        direction TB

        REQ_CHAT["1️⃣ RequirementChat<br/>────────────────<br/>Normalize raw request<br/>→ typed Spec<br/>Extract: name, goal, tools,<br/>constraints, io_contract"]

        REQ_CHAT --> CURATOR["2️⃣ Curator<br/>────────────────<br/>Decision: REUSE / ADAPT /<br/>COMPOSE / CREATE<br/>• Search RegistrySearch<br/>• Check AntiSprawl guard<br/>• Audit MetaIntelligenceTree"]

        CURATOR --> ARCHITECT["3️⃣ Architect<br/>────────────────<br/>Build / revise the<br/>draft entity payload<br/>• HierarchicalEntity JSON<br/>• Tool bindings<br/>• Governance config"]

        ARCHITECT --> CRITIC_B["4️⃣ BoardCritic<br/>────────────────<br/>Run meta_spec_critic tool<br/>Max 2 revision loops<br/>• PASS / REVISE / BLOCK<br/>• Log anti-patterns"]

        CRITIC_B --> VALIDATOR["5️⃣ Validator<br/>────────────────<br/>8 deterministic checks:<br/>• Schema validity<br/>• Tool capability match<br/>• IO contract completeness<br/>• Goal alignment"]

        VALIDATOR --> TEST_DRIVER["6️⃣ TestDriver<br/>────────────────<br/>Test suite under shared budget:<br/>• Smoke tests<br/>• Regression tests<br/>• Boundary cases<br/>• Hostile inputs<br/>• Comparative runs"]

        TEST_DRIVER --> PROMOTER["7️⃣ Promoter<br/>────────────────<br/>6 promotion gates:<br/>• All tests pass<br/>• Cost within bounds<br/>• No critical anti-patterns<br/>• Validator clean<br/>• Critic approved<br/>• Optional HITL gate<br/><br/>DRAFT → ACTIVE"]
    end

    PROMOTER -->|"✅ Promoted"| ACTIVE["🟢 ACTIVE Entity<br/>Ready for production use"]
    PROMOTER -->|"❌ Blocked"| REVISE_LOOP["🔄 Revision Loop<br/>Back to Architect"]
    REVISE_LOOP --> ARCHITECT

    subgraph AntiSprawl["🛡️ Anti-Sprawl Guard"]
        AS_DUP["Block near-duplicates<br/>Similarity > threshold"]
        AS_CAP["Block over-cap counts<br/>Per-company entity limits"]
        AS_MERGE["Propose consolidation<br/>Merge near-duplicate cluster"]
    end

    CURATOR --> AntiSprawl

    style REQ_CHAT fill:#2874a6,stroke:#2e86c1,color:#fff
    style CURATOR fill:#8e44ad,stroke:#9b59b6,color:#fff
    style ARCHITECT fill:#27ae60,stroke:#2ecc71,color:#fff
    style CRITIC_B fill:#d35400,stroke:#e67e22,color:#fff
    style VALIDATOR fill:#c0392b,stroke:#e74c3c,color:#fff
    style TEST_DRIVER fill:#1a5276,stroke:#2980b9,color:#fff
    style PROMOTER fill:#1e8449,stroke:#27ae60,color:#fff
    style ACTIVE fill:#27ae60,stroke:#2ecc71,color:#fff
```

### Meta Agent Self-Improvement — Prompt Evolution

```mermaid
flowchart LR
    CRON_PE["⏰ Weekly Cron<br/>meta_agent_prompt_evolution"] --> SAMPLE["Sample recent<br/>board runs"]
    SAMPLE --> CRITIC_OF_CRITIC["🧠 PromptEvolutionCritic<br/>────────────────<br/>Critic-of-critic LLM review<br/>• What went wrong in the<br/>  Meta-Agent's OWN process<br/>• Systemic pattern detection<br/>• Premature CREATE over REUSE?<br/>• Weak specs passing Critic?"]
    CRITIC_OF_CRITIC --> PROPOSAL["📝 PromptUpdateProposal<br/>prompt_diff + rationale + confidence"]
    PROPOSAL --> HITL_APPROVE["🙋 HITL Approval Required<br/>Agent cannot self-modify<br/>without human confirmation"]
    HITL_APPROVE -->|"Approved"| BUMP["✅ Prompt Template Updated"]
    HITL_APPROVE -->|"Rejected"| DISCARD["🗑️ Discarded"]

    style CRITIC_OF_CRITIC fill:#8e44ad,stroke:#9b59b6,color:#fff
    style HITL_APPROVE fill:#e74c3c,stroke:#c0392b,color:#fff
    style BUMP fill:#27ae60,stroke:#2ecc71,color:#fff
```

---

## 8. Critic Pipeline — Four-Stage Quality Gates

The `RealCriticPipeline` enforces quality at four checkpoints during each loop iteration.

```mermaid
flowchart LR
    subgraph Pipeline["🛡️ Four-Stage Critic Pipeline"]
        direction TB
        PRE["🔍 Pre-Critic<br/>────────────────<br/>Before action execution<br/>• Audit chosen action<br/>• Check safety constraints<br/>• Verdict: PASS / REVISE / BLOCK<br/>• Circuit breaker at 3 blocks"]

        POST["📝 Post-Critic<br/>────────────────<br/>After action execution<br/>• Evaluate output quality<br/>• Tag failures (FailureTag enum)<br/>• Schedule retries<br/>• Record StepHealthRecord"]

        ALIGN["⚖️ Alignment<br/>────────────────<br/>Goal-vs-output check<br/>• LLM alignment verifier<br/>• Detect goal drift<br/>• Low-cost quick check"]

        SUPER["👨‍⚖️ Supervisor<br/>────────────────<br/>Strategic oversight<br/>• Budget-pressure short-circuit<br/>• 3-clean-step fast path<br/>• Propose subgoals on REPLAN<br/>• Bandit-aware plan selection"]
    end

    ACTION_IN["⚡ Chosen Action"] --> PRE
    PRE -->|"PASS"| EXECUTE["Execute Action"]
    EXECUTE --> POST
    POST --> ALIGN
    ALIGN --> SUPER
    SUPER --> DECISION["📊 Combined Verdicts<br/>→ Reflect → Decide"]

    subgraph Calibration["📐 Weekly Calibration"]
        CAL_JOB["critic_calibration cron<br/>────────────────<br/>Scan StepHealthRecords<br/>vs ExecutionRun outcomes<br/>• Compute false-pass rate<br/>• Compute false-fail rate<br/>• Write to IntelligenceTree"]
    end

    POST -.->|"health records"| Calibration

    style PRE fill:#d35400,stroke:#e67e22,color:#fff
    style POST fill:#d35400,stroke:#e67e22,color:#fff
    style ALIGN fill:#c0392b,stroke:#e74c3c,color:#fff
    style SUPER fill:#8e44ad,stroke:#9b59b6,color:#fff
```

### Retry Strategy Selection

```mermaid
flowchart LR
    FAILURE["Step Failure<br/>with FailureTag"] --> PICK["pick_retry(record, state)"]
    PICK --> STRATEGY{"RetryStrategy"}
    STRATEGY -->|"SAME_MODEL"| S1["Retry with same model<br/>+ adjusted prompt"]
    STRATEGY -->|"FALLBACK_MODEL"| S2["Retry with fallback model<br/>e.g., GPT-4o → Gemini"]
    STRATEGY -->|"ALTERNATIVE_TOOL"| S3["Try different tool<br/>for same objective"]
    STRATEGY -->|"SKIP"| S4["Mark step as skipped<br/>Continue plan"]
    STRATEGY -->|"ABORT"| S5["Abort entire run"]

    style FAILURE fill:#e74c3c,stroke:#c0392b,color:#fff
    style PICK fill:#2874a6,stroke:#2e86c1,color:#fff
```

---

## 9. Governance & Billing Engine

The governance layer enforces cost controls, rate limits, and human-in-the-loop gates at every execution step.

```mermaid
flowchart TB
    subgraph PreFlight["✈️ Pre-Flight Checks"]
        CREDIT_CHECK["💳 Credit Gate<br/>────────────────<br/>Minimum wallet balance:<br/>• Process: $0.50<br/>• Agent: $0.05<br/>• Skill: $0.02<br/>• Action: $0.01"]

        RATE_LIMIT["⏱️ Rate Limiter<br/>────────────────<br/>Per-company / per-tool<br/>Redis-based enforcement"]

        SUSPEND_MW["🚫 Suspension Middleware<br/>────────────────<br/>ASGI middleware blocks<br/>suspended companies"]
    end

    subgraph PerStep["📊 Per-Step Cost Tracking"]
        TOOL_COST["ToolCostResolver<br/>────────────────<br/>TOOL_SKU_MAP lookup<br/>TOOL_FIXED_COST tables"]

        LEDGER["CostLedger<br/>────────────────<br/>attribution: tool | llm | voice<br/>Per-run accumulation"]

        TB_BILLING["TB Billing Formula<br/>────────────────<br/>billed = base × multiplier<br/>+ platform_fee<br/>+ partner_fee<br/>- discount"]
    end

    subgraph Wallets["💰 3-Tier Wallet System"]
        DAILY["☀️ Daily Credits<br/>$5.00 free / day<br/>Expires at midnight"]
        PAYG["💵 PAYG Wallet<br/>Razorpay top-up<br/>365-day validity"]
        SUB["📦 Subscription Credits<br/>Monthly recurring<br/>Up to 40% bonus"]
    end

    subgraph HITL_Gates["🙋 Human-in-the-Loop"]
        HITL_CHECK["HITL Checkpoint<br/>────────────────<br/>Pause at designated points<br/>• High-value email sends<br/>• Tool executions<br/>• Entity promotions"]
    end

    CREDIT_CHECK --> TOOL_COST
    RATE_LIMIT --> TOOL_COST
    TOOL_COST --> LEDGER
    LEDGER --> TB_BILLING
    TB_BILLING --> DAILY
    DAILY -->|"exhausted"| PAYG
    PAYG -->|"exhausted"| SUB
    SUB -->|"exhausted"| BLOCK["⛔ InsufficientCreditsError"]

    style CREDIT_CHECK fill:#27ae60,stroke:#2ecc71,color:#fff
    style RATE_LIMIT fill:#d35400,stroke:#e67e22,color:#fff
    style TB_BILLING fill:#2874a6,stroke:#2e86c1,color:#fff
    style DAILY fill:#f1c40f,stroke:#f39c12,color:#000
    style PAYG fill:#27ae60,stroke:#2ecc71,color:#fff
    style SUB fill:#8e44ad,stroke:#9b59b6,color:#fff
    style BLOCK fill:#e74c3c,stroke:#c0392b,color:#fff
```

---

## 10. Async Suspend/Resume — Child Dispatch

When a parent entity dispatches a child execution, the system uses an async suspend/resume pattern to avoid blocking worker threads.

```mermaid
sequenceDiagram
    participant Parent as 🏛️ Parent AgentLoop
    participant DB as 🐘 PostgreSQL
    participant Redis as 🔴 Redis / Arq
    participant Worker as ⚙️ Arq Worker
    participant Child as 🧑‍💼 Child AgentLoop

    Note over Parent: ACT phase triggers child dispatch

    Parent->>DB: INSERT execution_runs<br/>(parent_run_id = parent.id)
    Parent->>Redis: Enqueue child run via Arq
    Parent->>DB: Serialize AgentState → context_state<br/>Set status = WAITING_ON_CHILDREN
    Note over Parent: ⏸️ Worker thread released

    Redis->>Worker: Dequeue child run
    Worker->>Child: AgentLoop.run(child_run_id)
    Note over Child: Full loop execution

    Child->>DB: Finalize: result_data, total_cost_usd

    Child->>Redis: Trigger resume_parent_run

    Redis->>Worker: Dequeue resume job
    Worker->>DB: Load parent run (WAITING_ON_CHILDREN)
    Worker->>DB: Deserialize AgentState.restore(snapshot)

    Note over Worker: _fold_children:<br/>• Merge child outputs into parent context<br/>• Deduct child cost from parent budget<br/>• Mark step complete

    Worker->>Parent: AgentLoop._drive() resumes
    Note over Parent: ▶️ Continue from next iteration
```

---

## 11. Voice Subsystem — Real-Time Audio Pipeline

The voice system enables bidirectional speech-to-speech communication through telephony providers, streaming PCM audio to AI voice engines.

```mermaid
flowchart LR
    subgraph Telephony["📞 Telephony"]
        CALLER["📱 Caller<br/>(Phone / SIP)"]
        TWILIO_SRV["Twilio / Smartflo<br/>Exotel"]
    end

    subgraph Platform["🔌 HireBuddha Platform"]
        GATEWAY_WS["Unified Gateway<br/>WebSocket Upgrade<br/>ws://api.hirebuddha.com<br/>/stream/audio"]
        WS_HANDLER["websocket_handler.py<br/>Bidirectional async handler"]
        AUDIO_PROC["Audio Processor<br/>μ-law ↔ PCM16<br/>Codec Conversion"]
    end

    subgraph AI_Voice["🧠 AI Voice Engines"]
        GEMINI_LIVE["Google Gemini Live<br/>LiveConnect Session<br/>18 voice presets"]
        AZURE_RT["Azure OpenAI Realtime<br/>GPT-4o Voice"]
    end

    CALLER <-->|"SIP / RTP"| TWILIO_SRV
    TWILIO_SRV <-->|"WebSocket<br/>μ-law encoded"| GATEWAY_WS
    GATEWAY_WS <--> WS_HANDLER

    WS_HANDLER -->|"Inbound: μ-law → PCM16<br/>20ms chunks"| AUDIO_PROC
    AUDIO_PROC -->|"PCM16 stream"| GEMINI_LIVE
    AUDIO_PROC -->|"PCM16 stream"| AZURE_RT

    GEMINI_LIVE -->|"PCM16 response"| AUDIO_PROC
    AZURE_RT -->|"PCM16 response"| AUDIO_PROC
    AUDIO_PROC -->|"Outbound: PCM16 → μ-law"| WS_HANDLER

    subgraph VAD["🎤 Voice Activity Detection"]
        VAD_START["Start-of-Speech: HIGH<br/>Fast barge-in detection"]
        VAD_END["End-of-Speech: LOW<br/>Prevents premature cutoff"]
        VAD_SILENCE["Silence Duration: 1000ms<br/>Response trigger threshold"]
    end

    style CALLER fill:#2874a6,stroke:#2e86c1,color:#fff
    style GATEWAY_WS fill:#1a1a2e,stroke:#e94560,color:#fff
    style GEMINI_LIVE fill:#27ae60,stroke:#2ecc71,color:#fff
    style AZURE_RT fill:#2874a6,stroke:#2e86c1,color:#fff
    style AUDIO_PROC fill:#d35400,stroke:#e67e22,color:#fff
```

---

## 12. Execution Reasoning Strategies

The agent loop supports pluggable reasoning strategies matched to step complexity.

```mermaid
graph TB
    subgraph Strategies["🧠 Reasoning Strategy Registry"]
        REACT["⚡ ReAct<br/>────────────────<br/>Reason → Act → Observe → Loop<br/><br/>Best for:<br/>• Linear tool tasks<br/>• Database operations<br/>• API integrations"]

        COT["💭 Chain-of-Thought<br/>────────────────<br/>Think step-by-step → Generate<br/><br/>Best for:<br/>• Document drafting<br/>• Legal review<br/>• Complex analysis"]

        REFLECT_S["🪞 Reflection<br/>────────────────<br/>Generate → Self-critique → Revise<br/><br/>Best for:<br/>• Quality-critical outputs<br/>• Self-correction"]

        TOT["🌳 Tree-of-Thoughts<br/>────────────────<br/>Branch → Evaluate → Prune → Select<br/><br/>Best for:<br/>• Multi-path exploration<br/>• Strategy selection"]
    end

    subgraph Executors["⚙️ Executor Registry"]
        DAG_EX["DAG Executor<br/>Dependency graph walking"]
        RECURSIVE["Recursive Executor<br/>Nested execution"]
        SINGLE["SingleStep Executor<br/>One-shot tool call"]
        CHILD_ENT["ChildEntity Executor<br/>Async child dispatch"]
        DIALOG["Dialog Executor<br/>Conversational turns"]
        DEBATE["Debate Executor<br/>Multi-perspective synthesis"]
        TOOL_BURST["ToolBurst Executor<br/>Parallel tool calls"]
        SKILL_EX["Skill Executor<br/>Specialized task block"]
    end

    REACT --> SINGLE
    REACT --> DAG_EX
    COT --> SINGLE
    COT --> RECURSIVE
    REFLECT_S --> SINGLE
    TOT --> DEBATE

    style REACT fill:#27ae60,stroke:#2ecc71,color:#fff
    style COT fill:#2874a6,stroke:#2e86c1,color:#fff
    style REFLECT_S fill:#8e44ad,stroke:#9b59b6,color:#fff
    style TOT fill:#d35400,stroke:#e67e22,color:#fff
```

---

## 13. Multi-Tenant Security Architecture

```mermaid
graph TB
    subgraph TenantHierarchy["🔒 4-Level Tenant Isolation"]
        ADMIN["🔑 App Admin<br/>Buddha Cognitive Lab<br/>────────────────<br/>• Platform dashboards<br/>• Global tool registry<br/>• SKU cost management<br/>• Partner commissions"]

        PARTNER["🤝 Partner<br/>────────────────<br/>• Manage tenant portfolios<br/>• Configure pricing multipliers<br/>• Track earnings"]

        TENANT["🏢 Tenant<br/>────────────────<br/>• Manage workspace & users<br/>• AI employee CRUD<br/>• Integrations & wallets<br/>• Data fully isolated"]

        USER_T["👤 User<br/>────────────────<br/>• Access AI features<br/>• View execution histories<br/>• Interact with workspace"]
    end

    ADMIN --> PARTNER --> TENANT --> USER_T

    subgraph Security["🛡️ Security Gates"]
        JWT["🎫 JWT Auth<br/>Short-lived: 15min<br/>HTTP-only refresh: 7 days"]
        VAULT["🔐 Key Vault<br/>AES-256-GCM encryption<br/>12-byte nonce + master key"]
        SUSP["🚫 Suspension MW<br/>ASGI middleware<br/>Instant API block"]
        HITL_SEC["🙋 HITL Checkpoints<br/>Pause before high-risk<br/>operations"]
        CIRCUIT["⚡ Credit Circuit Breaker<br/>Per-step balance check<br/>Immediate stop on zero"]
    end

    style ADMIN fill:#6c3483,stroke:#8e44ad,color:#fff
    style PARTNER fill:#2874a6,stroke:#2e86c1,color:#fff
    style TENANT fill:#27ae60,stroke:#2ecc71,color:#fff
    style USER_T fill:#d4ac0d,stroke:#f1c40f,color:#000
    style JWT fill:#1a1a2e,stroke:#e94560,color:#fff
    style VAULT fill:#1a1a2e,stroke:#e94560,color:#fff
```

---

## 14. Intelligence Rule Lifecycle

Rules learned by the Dreaming Engine follow a strict lifecycle with evidence-based transitions.

```mermaid
stateDiagram-v2
    [*] --> CANDIDATE: Dreaming Engine<br/>distills observation

    CANDIDATE --> CANDIDATE: validation (net < 3)
    CANDIDATE --> CONFIRMED: net validations ≥ 3<br/>(PROMOTE_AFTER = 3)

    CONFIRMED --> CONFIRMED: continues predicting
    CONFIRMED --> RETIRED: net contradictions ≥ 3<br/>(RETIRE_AFTER = 3)

    RETIRED --> [*]: Permanently excluded

    state CANDIDATE {
        [*] --> Observing
        Observing --> Validating: subsequent run matches
        Validating --> Contradicting: subsequent run contradicts
        Contradicting --> Observing: reset cycle
    }

    note right of CANDIDATE
        Not injected into prompts
        when confirmed_only gate is ON
    end note

    note right of CONFIRMED
        Active in:
        • Planner prompts
        • Critic evaluation
        • Strategist decisions
    end note

    note right of RETIRED
        Permanently excluded
        from all prompt injection
    end note
```

---

## 15. Meta Intelligence Tree — Platform Knowledge Graph

The `MetaIntelligenceTree` is a platform-scoped knowledge structure owned by the Meta Agent, tracking cross-entity patterns and learnings at the tenant level.

```mermaid
graph TB
    subgraph MIT["🧠 MetaIntelligenceTree (Per Company, scope=TENANT)"]
        ROOT_MIT["Meta-Agent Role Root"]

        ROOT_MIT --> AP["📏 Architecture Anti-Patterns<br/>────────────────<br/>Written by: BoardCritic<br/>Content: Detected design flaws<br/>LRU-pruned at 200 rows"]

        ROOT_MIT --> SP["🎯 Spec Patterns<br/>────────────────<br/>Written by: Curator + Promoter<br/>Content: Successful entity patterns<br/>+ Skill candidates"]

        ROOT_MIT --> TF["🚨 Test Failure Tags<br/>────────────────<br/>Written by: TestDriver<br/>Content: Categorized test failures<br/>across board runs"]

        ROOT_MIT --> CD["🧠 Curator Decisions<br/>────────────────<br/>Written by: Curator<br/>Content: REUSE/ADAPT/CREATE audit trail"]

        ROOT_MIT --> TR["🔧 Tool Reliability<br/>────────────────<br/>Written by: post-Promoter monitor<br/>Content: Tool success/failure rates"]

        ROOT_MIT --> PC["📝 Prompt-Update Candidates<br/>────────────────<br/>Written by: prompt-evo cron<br/>Content: HITL-gated prompt diffs"]

        ROOT_MIT --> CG["🔗 Composition Graph<br/>────────────────<br/>Entity dependency tracking<br/>Cross-entity relationships"]
    end

    subgraph Consumers["📤 Consumed By"]
        CURATOR_C["Curator — reads anti-patterns<br/>before REUSE/CREATE decision"]
        CRITIC_C["BoardCritic — reads patterns<br/>to validate new specs"]
        TEST_C["TestDriver — reads failure tags<br/>to design test suites"]
        PROMOTER_C["Promoter — reads reliability<br/>data for gate checks"]
    end

    AP --> CURATOR_C
    SP --> CRITIC_C
    TF --> TEST_C
    TR --> PROMOTER_C

    style ROOT_MIT fill:#6c3483,stroke:#8e44ad,color:#fff
    style AP fill:#e74c3c,stroke:#c0392b,color:#fff
    style SP fill:#27ae60,stroke:#2ecc71,color:#fff
    style TF fill:#d35400,stroke:#e67e22,color:#fff
    style CD fill:#2874a6,stroke:#2e86c1,color:#fff
    style TR fill:#7f8c8d,stroke:#95a5a6,color:#fff
    style PC fill:#d4ac0d,stroke:#f1c40f,color:#000
```

---

## Cross-Reference: Source File Mapping

| Diagram Section | Key Source Files |
|---|---|
| System Topology | [main.py](file:///home/rahul/workspace/hb-proto-3/backend/src/main.py), [start_services.sh](file:///home/rahul/workspace/hb-proto-3/start_services.sh) |
| Agent Hierarchy | [models.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/orm/execution.py), [service.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/service.py) |
| Agentic Loop | [agent_loop.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/core/agent_loop.py), [agent_state.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/core/agent_state.py) |
| CORTEX Memory | [cortex_service.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory/cortex_service.py), [cortex_bridge.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory/cortex_bridge.py) |
| Four Domains | [assembler.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory/assembler.py), [domains/](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory/domains/__init__.py) |
| Dreaming/Learning | [dreaming_engine.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory/dreaming_engine.py), [trust_learning.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory/trust_learning.py), [rule_lifecycle.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory/rule_lifecycle.py) |
| Meta Agent | [meta_agent_template.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/meta_agent_template.py), [board/](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/board/__init__.py) |
| Critic Pipeline | [critic_pipeline.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planning/critic_pipeline.py), [supervisor_critic.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/planning/supervisor_critic.py) |
| Governance | [governance_service.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/governance/governance_service.py), [tool_cost_resolver.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/governance/tool_cost_resolver.py) |
| Suspend/Resume | [arq_jobs.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/core/arq_jobs.py), [child_entity.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/core/executors/child_entity.py) |
| Voice | [websocket_handler.py](file:///home/rahul/workspace/hb-proto-3/backend/src/voice), [gemini_live.py](file:///home/rahul/workspace/hb-proto-3/backend/src/voice) |
| Reasoning | [reasoning/](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/core/reasoning/__init__.py), [executors/](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/core/executors/__init__.py) |
| Intelligence Rules | [rule_lifecycle.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory/rule_lifecycle.py), [intelligence_tree_service.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/memory/intelligence_tree_service.py) |
| Meta Intelligence | [meta_intelligence_tree.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/meta_intelligence_tree.py), [skill_library.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/skill_library.py), [prompt_evolution.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/meta/prompt_evolution.py) |
