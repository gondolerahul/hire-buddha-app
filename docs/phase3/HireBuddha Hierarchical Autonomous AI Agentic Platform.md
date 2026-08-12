# **HireBuddha Hierarchical Autonomous AI Agentic Platform**

## **Formal Requirements & Data Structure Specification**

**Document Version:** 1.0.0  
 **Last Updated:** December 25, 2025  
 **Classification:** Technical Specification

---

## **Executive Summary**

This document provides a comprehensive, production-ready data structure specification for the HireBuddha Hierarchical Autonomous AI Agentic Platform. The specification defines a unified, recursive entity model that supports Actions, Skills, Agents, and Processes through a common structural framework while maintaining entity-specific behavioral nuances. The document includes:

1. **Unified Entity Data Structure** with complete field specifications  
2. **Execution Logic Framework** for runtime behavior  
3. **Practical Implementation Example** using a Video Advertising Process  
4. **Database Schema** for persistence  
5. **API Contract Definitions** for inter-entity communication

---

## **1\. Core Design Principles**

### **1.1 Unified Recursive Architecture**

All entities (Action, Skill, Agent, Process) share a common structural interface with specialized behavioral extensions. This enables:

* **Polymorphic execution engine** that treats all entities uniformly  
* **Simplified maintenance** through shared logic patterns  
* **Dynamic composition** allowing runtime entity nesting

### **1.2 Bounded Autonomy**

Static plans provide deterministic guardrails while dynamic planning enables adaptive behavior within defined constraints.

### **1.3 Observability-First Design**

Every decision, tool call, and state transition must be traceable through the hierarchical execution tree.

---

## **2\. Unified Entity Data Structure Specification**

### **2.1 Complete Entity Schema**

json  
{  
  "metadata": {  
    "id": "UUID",  
    "version": "String (SemVer, e.g., '1.2.3')",  
    "type": "Enum: ACTION | SKILL | AGENT | PROCESS",  
    "created\_at": "ISO8601 Timestamp",  
    "updated\_at": "ISO8601 Timestamp",  
    "created\_by": "UUID (User ID)",  
    "tags": \["String"\],  
    "status": "Enum: DRAFT | ACTIVE | DEPRECATED | ARCHIVED"  
  },

  "identity": {  
    "name": "String (Max 100 chars, unique within workspace)",  
    "display\_name": "String (UI-friendly name)",  
    "description": "Text (Max 1000 chars)",  
    "persona": {  
      "system\_prompt": "Text (LLM context defining role, constraints, tone)",  
      "examples": \[  
        {  
          "scenario": "String (Description of situation)",  
          "ideal\_response": "Text (Expected behavior pattern)"  
        }  
      \],  
      "behavioral\_constraints": \[  
        "String (e.g., 'Never contact candidates before 9 AM')"  
      \]  
    },  
    "icon": "String (UI icon identifier)",  
    "color": "String (Hex color for UI representation)"  
  },

  "hierarchy": {  
    "parent\_id": "UUID | null (null for top-level Processes)",  
    "children": \[  
      {  
        "child\_id": "UUID (Reference to another entity)",  
        "child\_type": "Enum: ACTION | SKILL | AGENT | PROCESS",  
        "relationship": "Enum: SEQUENTIAL | PARALLEL | CONDITIONAL",  
        "condition": {  
          "enabled": "Boolean",  
          "expression": "String (JSONLogic or similar)",  
          "description": "String (Human-readable condition)"  
        }  
      }  
    \],  
    "is\_atomic": "Boolean (True only for Actions without sub-entities)",  
    "composition\_depth": "Integer (Calculated: current nesting level)"  
  },

  "logic\_gate": {  
    "reasoning\_config": {  
      "model\_provider": "String (e.g., 'google', 'openai', 'anthropic')",  
      "model\_name": "String (e.g., 'gemini-2.0-flash', 'gpt-4o')",  
      "model\_version": "String | null (Optional specific version)",  
      "temperature": "Float (0.0 \- 2.0, default: 0.7)",  
      "top\_p": "Float (0.0 \- 1.0, default: 1.0)",  
      "max\_tokens": "Integer | null (Max completion tokens)",  
      "reasoning\_mode": "Enum: REACT | CHAIN\_OF\_THOUGHT | REFLECTION | TREE\_OF\_THOUGHTS"  
    },  
    "retry\_policy": {  
      "max\_retries": "Integer (Default: 3)",  
      "backoff\_strategy": "Enum: LINEAR | EXPONENTIAL | NONE",  
      "backoff\_multiplier": "Float (Default: 2.0 for exponential)",  
      "retry\_on": \["Enum: TOOL\_FAILURE | LLM\_ERROR | VALIDATION\_ERROR | TIMEOUT"\]  
    },  
    "review\_mechanism": {  
      "enabled": "Boolean (Enable self-review after execution)",  
      "review\_prompt": "String (Template for reviewing output quality)",  
      "success\_criteria": \[  
        {  
          "criterion": "String (e.g., 'Output contains valid email')",  
          "validation\_type": "Enum: REGEX | SCHEMA | LLM\_JUDGE | FUNCTION",  
          "validator": "String (Regex pattern, schema, or function reference)"  
        }  
      \],  
      "on\_failure": "Enum: RETRY | ESCALATE | ALTERNATIVE\_PATH | ABORT"  
    }  
  },

  "planning": {  
    "static\_plan": {  
      "enabled": "Boolean (Use predefined plan)",  
      "steps": \[  
        {  
          "step\_id": "UUID",  
          "order": "Integer (1-based sequential order)",  
          "name": "String",  
          "description": "String",  
          "type": "Enum: THOUGHT | ACTION | TOOL\_CALL | CHILD\_ENTITY\_INVOCATION",  
          "target": {  
            "entity\_id": "UUID | null (For child invocations)",  
            "tool\_id": "String | null (For tool calls)",  
            "prompt\_template": "String | null (For thought/action steps)"  
          },  
          "required": "Boolean (Can this step be skipped?)",  
          "exit\_conditions": \[  
            {  
              "condition": "String (JSONLogic expression)",  
              "next\_step": "Integer | 'END' | 'ESCALATE'"  
            }  
          \]  
        }  
      \],  
      "fallback\_behavior": "Enum: STRICT | ADAPTIVE | DYNAMIC\_ONLY"  
    },  
    "dynamic\_planning": {  
      "enabled": "Boolean (Allow LLM to generate runtime plans)",  
      "planning\_prompt": "String (Template for plan generation)",  
      "constraints": \[  
        "String (e.g., 'Must include validation step before external API calls')"  
      \],  
      "reconciliation\_strategy": "Enum: STATIC\_PRIORITY | DYNAMIC\_PRIORITY | HYBRID",  
      "allowed\_deviations": {  
        "can\_add\_steps": "Boolean",  
        "can\_skip\_optional\_steps": "Boolean",  
        "can\_reorder\_steps": "Boolean",  
        "can\_change\_tools": "Boolean"  
      }  
    },  
    "loop\_control": {  
      "max\_iterations": "Integer | null (Null \= no limit, dangerous\!)",  
      "convergence\_criteria": \[  
        {  
          "metric": "String (e.g., 'output\_quality\_score')",  
          "threshold": "Float",  
          "operator": "Enum: GT | LT | EQ | GTE | LTE"  
        }  
      \],  
      "iteration\_context\_mode": "Enum: FULL\_HISTORY | SUMMARIZED | LAST\_N",  
      "summary\_every\_n\_iterations": "Integer | null"  
    }  
  },

  "capabilities": {  
    "tools": \[  
      {  
        "tool\_id": "String (Unique identifier)",  
        "name": "String",  
        "description": "String (What the tool does)",  
        "provider": "String (e.g., 'internal', 'google', 'slack')",  
        "authentication": {  
          "type": "Enum: NONE | API\_KEY | OAUTH2 | SERVICE\_ACCOUNT",  
          "credentials\_ref": "String (Reference to secure vault)"  
        },  
        "function\_schema": {  
          "name": "String (Function name for LLM)",  
          "description": "String (Concise function purpose)",  
          "parameters": {  
            "type": "object",  
            "properties": {  
              "param\_name": {  
                "type": "String (JSON Schema type)",  
                "description": "String",  
                "required": "Boolean"  
              }  
            }  
          }  
        },  
        "rate\_limit": {  
          "calls\_per\_minute": "Integer | null",  
          "calls\_per\_hour": "Integer | null"  
        },  
        "permissions": "Enum: READ | WRITE | EXECUTE",  
        "sandbox\_mode": "Boolean (Execute in isolated environment)"  
      }  
    \],  
    "memory": {  
      "enabled": "Boolean",  
      "scope": "Enum: SESSION | ENTITY | GLOBAL",  
      "storage\_backend": "Enum: REDIS | POSTGRES\_JSONB | VECTOR\_DB",  
      "retention\_policy": {  
        "max\_items": "Integer | null",  
        "ttl\_seconds": "Integer | null",  
        "summarization\_threshold": "Integer (Summarize after N items)"  
      },  
      "access\_pattern": "Enum: FULL | SEMANTIC\_SEARCH | RECENT\_N"  
    },  
    "context\_engineering": {  
      "max\_context\_tokens": "Integer (Hard limit for prompt size)",  
      "context\_priority": \[  
        "Enum: SYSTEM\_PROMPT | STATIC\_PLAN | DYNAMIC\_PLAN | MEMORY | TOOL\_RESULTS | USER\_INPUT"  
      \],  
      "artifact\_handling": {  
        "store\_large\_objects": "Boolean (Store \>10KB objects separately)",  
        "artifact\_reference\_mode": "Enum: INLINE | REFERENCE | SUMMARY"  
      }  
    }  
  },

  "governance": {  
    "cost\_controls": {  
      "max\_cost\_usd": "Decimal | null (Per execution)",  
      "cumulative\_cost\_usd": "Decimal | null (Lifetime cost limit)",  
      "alert\_threshold\_usd": "Decimal | null (Warning threshold)"  
    },  
    "execution\_limits": {  
      "timeout\_ms": "Integer (Max execution time)",  
      "max\_recursion\_depth": "Integer (Default: 5)",  
      "max\_tool\_calls": "Integer | null (Per execution)",  
      "max\_llm\_calls": "Integer | null (Per execution)"  
    },  
    "human\_oversight": {  
      "hitl\_checkpoints": \[  
        {  
          "trigger": "Enum: BEFORE\_EXECUTION | AFTER\_PLANNING | BEFORE\_TOOL\_CALL | ON\_FAILURE | CUSTOM\_CONDITION",  
          "condition": "String | null (JSONLogic expression)",  
          "approval\_required": "Boolean",  
          "notification\_channels": \["Enum: EMAIL | SLACK | IN\_APP"\],  
          "timeout\_action": "Enum: PROCEED | ABORT | ESCALATE"  
        }  
      \],  
      "audit\_level": "Enum: MINIMAL | STANDARD | COMPREHENSIVE",  
      "pii\_handling": "Enum: ALLOW | REDACT | ENCRYPT"  
    },  
    "safety\_rails": {  
      "content\_filters": \["Enum: TOXICITY | PII | PROFANITY | BIAS"\],  
      "action\_restrictions": \[  
        {  
          "restricted\_action": "String (e.g., 'delete\_candidate')",  
          "requires\_approval": "Boolean",  
          "blocked\_entirely": "Boolean"  
        }  
      \],  
      "output\_validation": {  
        "enabled": "Boolean",  
        "schema": "JSON\_SCHEMA | null (Expected output structure)"  
      }  
    }  
  },

  "io\_contract": {  
    "input": {  
      "schema": {  
        "type": "object",  
        "properties": {  
          "field\_name": {  
            "type": "String (JSON Schema type)",  
            "description": "String",  
            "required": "Boolean",  
            "default": "Any | null"  
          }  
        }  
      },  
      "validation\_rules": \[  
        {  
          "rule": "String (e.g., 'email must be valid format')",  
          "validator": "String (Function reference or regex)"  
        }  
      \]  
    },  
    "output": {  
      "schema": {  
        "type": "object",  
        "properties": {  
          "field\_name": {  
            "type": "String",  
            "description": "String"  
          }  
        }  
      },  
      "transformations": \[  
        {  
          "field": "String (Output field name)",  
          "transform": "String (Function reference, e.g., 'capitalize')"  
        }  
      \]  
    },  
    "state\_contract": {  
      "reads\_from": \["String (State key names this entity reads)"\],  
      "writes\_to": \["String (State key names this entity writes)"\],  
      "side\_effects": \["String (External effects, e.g., 'sends\_email')"\]  
    }  
  },

  "observability": {  
    "logging": {  
      "log\_level": "Enum: DEBUG | INFO | WARN | ERROR",  
      "log\_thoughts": "Boolean (Log LLM reasoning)",  
      "log\_tool\_calls": "Boolean",  
      "log\_state\_changes": "Boolean"  
    },  
    "metrics": {  
      "track\_latency": "Boolean",  
      "track\_token\_usage": "Boolean",  
      "track\_cost": "Boolean",  
      "custom\_metrics": \[  
        {  
          "metric\_name": "String",  
          "aggregation": "Enum: SUM | AVG | MAX | MIN | COUNT"  
        }  
      \]  
    },  
    "tracing": {  
      "trace\_id\_propagation": "Boolean (Pass trace\_id to children)",  
      "span\_annotations": \["String (Custom labels for trace spans)"\]  
    }  
  },

  "metadata\_extensions": {  
    "custom\_fields": {  
      "field\_name": "Any (Extensible for domain-specific needs)"  
    },  
    "ui\_hints": {  
      "form\_layout": "String (UI rendering instructions)",  
      "visibility": "Enum: PUBLIC | PRIVATE | WORKSPACE",  
      "is\_template": "Boolean (Can be cloned)"  
    }  
  }

}

---

## **3\. Field-by-Field Specification & Implementation Logic**

### **3.1 Metadata Section**

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `id` | UUID | Yes | Generated on entity creation. Immutable. Used for all references. |
| `version` | String | Yes | Semantic versioning. Auto-incremented on updates. Enables rollback. |
| `type` | Enum | Yes | Determines execution behavior. Cannot be changed after creation. |
| `created_at` | ISO8601 | Yes | Auto-generated timestamp. Used for audit trails. |
| `updated_at` | ISO8601 | Yes | Auto-updated on any modification. Triggers re-validation. |
| `created_by` | UUID | Yes | User ID for access control. Links to IAM system. |
| `tags` | Array\[String\] | No | Searchable metadata. Max 20 tags. Used for filtering in UI. |
| `status` | Enum | Yes | Controls execution eligibility. Only ACTIVE entities can run. |

**Implementation Notes:**

* Version changes trigger dependency validation across child entities  
* Status transitions must be logged for compliance  
* Tags enable workspace-level search and categorization

### **3.2 Identity Section**

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `name` | String | Yes | Unique constraint within workspace. Used for API references. |
| `display_name` | String | No | UI-only field. Can contain special characters. |
| `description` | Text | Yes | Rendered in UI tooltips. Max 1000 chars. |
| `persona.system_prompt` | Text | Conditional\* | **Required for Agents/Processes**. Prepended to all LLM calls. Defines role, tone, and constraints. |
| `persona.examples` | Array | No | Few-shot learning examples. Each example \~200 tokens max. |
| `persona.behavioral_constraints` | Array\[String\] | No | Hard rules (e.g., "Never delete data"). Checked before tool execution. |

**Implementation Notes:**

* `system_prompt` is compiled into the LLM context at runtime  
* Examples are dynamically selected based on input similarity (vector search)  
* Behavioral constraints are evaluated using a rule engine before any tool call

### **3.3 Hierarchy Section**

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `parent_id` | UUID | Conditional | Null for top-level Processes. Creates execution tree. |
| `children` | Array\[Object\] | No | Defines composition. Empty for atomic Actions. |
| `children[].child_id` | UUID | Yes | Reference to another entity. Validated on save. |
| `children[].relationship` | Enum | Yes | Determines execution order: SEQUENTIAL (waterfall), PARALLEL (concurrent), CONDITIONAL (if-then). |
| `children[].condition` | Object | Conditional | Required if relationship=CONDITIONAL. Uses JSONLogic for evaluation. |
| `is_atomic` | Boolean | Auto | Calculated: true if children array is empty. |
| `composition_depth` | Integer | Auto | Calculated from root. Used to enforce max\_recursion\_depth. |

**Implementation Notes:**

* Circular dependencies are rejected during validation  
* PARALLEL children execute concurrently with Promise.all()  
* CONDITIONAL children are evaluated using JSONLogic expressions against current state  
* Maximum depth defaults to 5 (configurable in governance)

### **3.4 Logic Gate Section**

This section defines the "brain" of the entity—how it reasons and recovers from failures.

#### **3.4.1 Reasoning Config**

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `model_provider` | String | Yes | Routes to correct API client (Google, OpenAI, Anthropic). |
| `model_name` | String | Yes | Specific model (e.g., gemini-2.0-flash). Affects cost/speed. |
| `temperature` | Float | Yes | Controls randomness. Lower \= deterministic. Higher \= creative. |
| `top_p` | Float | No | Nucleus sampling. Used with temperature for fine control. |
| `max_tokens` | Integer | No | Hard limit on completion length. Prevents runaway costs. |
| `reasoning_mode` | Enum | Yes | REACT (thought-action cycles), CHAIN\_OF\_THOUGHT (step-by-step), REFLECTION (self-critique), TREE\_OF\_THOUGHTS (explore multiple paths). |

**Implementation Logic:**

python  
def get\_llm\_response(config, prompt, context):  
    client \= get\_client(config.model\_provider)  
      
    *\# Apply reasoning mode wrapper*  
    if config.reasoning\_mode \== "REACT":  
        prompt \= f"Think step-by-step and act iteratively:\\n{prompt}"  
    elif config.reasoning\_mode \== "REFLECTION":  
        prompt \= f"{prompt}\\n\\nAfter answering, critique your response."  
      
    response \= client.complete(  
        model\=config.model\_name,  
        prompt\=prompt,  
        temperature\=config.temperature,  
        max\_tokens\=config.max\_tokens  
    )  
    

    return response

#### **3.4.2 Retry Policy**

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `max_retries` | Integer | Yes | Number of retry attempts before failure propagates up. |
| `backoff_strategy` | Enum | Yes | LINEAR (wait 1s, 2s, 3s), EXPONENTIAL (1s, 2s, 4s, 8s), NONE. |
| `backoff_multiplier` | Float | Conditional | Required for EXPONENTIAL. Base multiplier for wait time. |
| `retry_on` | Array\[Enum\] | Yes | Specifies which error types trigger retries. |

**Implementation Logic:**

python  
async def execute\_with\_retry(step, retry\_policy):  
    for attempt in range(retry\_policy.max\_retries \+ 1):  
        try:  
            result \= await execute\_step(step)  
            return result  
        except Exception as e:  
            if error\_type(e) not in retry\_policy.retry\_on:  
                raise  *\# Don't retry this error type*  
              
            if attempt \== retry\_policy.max\_retries:  
                raise  *\# Max retries exceeded*  
              
            *\# Calculate backoff*  
            if retry\_policy.backoff\_strategy \== "EXPONENTIAL":  
                wait\_time \= (retry\_policy.backoff\_multiplier \*\* attempt)  
            elif retry\_policy.backoff\_strategy \== "LINEAR":  
                wait\_time \= attempt \+ 1  
            else:  
                wait\_time \= 0  
            

            await asyncio.sleep(wait\_time)

#### **3.4.3 Review Mechanism**

This is the **self-healing** component that allows entities to critique and correct their own output.

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `enabled` | Boolean | Yes | If false, output is accepted as-is. |
| `review_prompt` | String | Conditional | Template for LLM to judge output quality. Must include {output} placeholder. |
| `success_criteria` | Array\[Object\] | Conditional | List of validation checks. All must pass. |
| `on_failure` | Enum | Yes | RETRY (re-run step), ESCALATE (notify parent), ALTERNATIVE\_PATH (try different approach), ABORT (stop execution). |

**Implementation Logic:**

python  
async def review\_output(output, review\_mechanism):  
    if not review\_mechanism.enabled:  
        return {"passed": True}  
      
    *\# Run all validation checks*  
    all\_passed \= True  
    for criterion in review\_mechanism.success\_criteria:  
        if criterion.validation\_type \== "REGEX":  
            passed \= re.match(criterion.validator, output)  
        elif criterion.validation\_type \== "SCHEMA":  
            passed \= validate\_json\_schema(output, criterion.validator)  
        elif criterion.validation\_type \== "LLM\_JUDGE":  
            prompt \= review\_mechanism.review\_prompt.format(output\=output)  
            judgment \= await call\_llm(prompt)  
            passed \= "success" in judgment.lower()  
        elif criterion.validation\_type \== "FUNCTION":  
            func \= load\_function(criterion.validator)  
            passed \= func(output)  
          
        if not passed:  
            all\_passed \= False  
            break  
      
    return {  
        "passed": all\_passed,  
        "failed\_criterion": criterion if not all\_passed else None

    }

### **3.5 Planning Section**

This is the most complex section, managing the dual static/dynamic planning system.

#### **3.5.1 Static Plan**

The static plan is the **design-time blueprint** created via the UI.

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `enabled` | Boolean | Yes | If false, entity relies purely on dynamic planning (risky). |
| `steps` | Array\[Object\] | Conditional | Required if enabled=true. Ordered list of predefined steps. |
| `steps[].step_id` | UUID | Yes | Unique identifier for this step. Used in execution logs. |
| `steps[].order` | Integer | Yes | 1-based. Determines execution sequence. |
| `steps[].type` | Enum | Yes | THOUGHT (LLM reasoning), TOOL\_CALL (external API), CHILD\_ENTITY\_INVOCATION (recursive call). |
| `steps[].target` | Object | Yes | Specifies what to execute (entity, tool, or prompt). |
| `steps[].required` | Boolean | Yes | If true, step cannot be skipped by dynamic planning. |
| `steps[].exit_conditions` | Array\[Object\] | No | Allows early exit based on state (e.g., "if candidate score \< 5, escalate"). |
| `fallback_behavior` | Enum | Yes | STRICT (reject dynamic deviations), ADAPTIVE (merge plans), DYNAMIC\_ONLY (ignore static). |

**Implementation Logic:**

* Static plan is loaded once at execution start  
* Required steps are marked as "immutable" during reconciliation  
* Exit conditions are evaluated after each step execution

#### **3.5.2 Dynamic Planning**

Dynamic planning allows the LLM to **generate or modify the plan at runtime**.

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `enabled` | Boolean | Yes | If false, entity strictly follows static plan. |
| `planning_prompt` | String | Conditional | Template instructing LLM how to generate a plan. |
| `constraints` | Array\[String\] | No | Hard rules for the LLM (e.g., "Must validate before writing to DB"). |
| `reconciliation_strategy` | Enum | Yes | STATIC\_PRIORITY (static wins conflicts), DYNAMIC\_PRIORITY (dynamic wins), HYBRID (intelligent merge). |
| `allowed_deviations` | Object | Yes | Defines boundaries for dynamic changes. |

**Implementation Logic:**

python  
async def generate\_dynamic\_plan(entity, input\_data, context):  
    if not entity.planning.dynamic\_planning.enabled:  
        return None  
      
    *\# Build planning prompt*  
    constraints\_text \= "\\n".join(entity.planning.dynamic\_planning.constraints)  
    prompt \= f"""  
    {entity.planning.dynamic\_planning.planning\_prompt}  
      
    Input: {input\_data}  
    Context: {context}  
      
    Constraints:  
    {constraints\_text}  
      
    Generate a step-by-step plan in JSON format.  
    """  
      
    response \= await call\_llm(prompt)  
    dynamic\_plan \= parse\_json(response)  
      
    *\# Validate against constraints*  
    for step in dynamic\_plan:  
        if violates\_constraints(step, constraints\_text):  
            raise PlanValidationError(f"Step {step} violates constraints")  
    

    return dynamic\_plan

#### **3.5.3 Loop Control**

Essential for Skills with iterative/cyclic behavior.

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `max_iterations` | Integer | Yes | Prevents infinite loops. **Critical safety feature**. |
| `convergence_criteria` | Array\[Object\] | No | Defines when to stop iterating (e.g., "quality score \> 0.9"). |
| `iteration_context_mode` | Enum | Yes | FULL\_HISTORY (pass all iterations to LLM), SUMMARIZED (compress old iterations), LAST\_N (only recent N). |

**Implementation Logic:**

python  
async def execute\_loop(entity, context):  
    iteration \= 0  
    results \= \[\]  
      
    while iteration \< entity.planning.loop\_control.max\_iterations:  
        *\# Prepare context based on mode*  
        if entity.planning.loop\_control.iteration\_context\_mode \== "LAST\_N":  
            iteration\_context \= results\[\-3:\]  *\# Last 3 iterations*  
        elif entity.planning.loop\_control.iteration\_context\_mode \== "SUMMARIZED":  
            iteration\_context \= summarize\_results(results)  
        else:  
            iteration\_context \= results  
          
        *\# Execute iteration*  
        result \= await execute\_entity(entity, iteration\_context)  
        results.append(result)  
          
        *\# Check convergence*  
        converged \= check\_convergence(results, entity.planning.loop\_control.convergence\_criteria)  
        if converged:  
            break  
          
        iteration \+= 1  
    

    return results

### **3.6 Capabilities Section**

#### **3.6.1 Tools**

Tools are the entity's "hands"—how it interacts with the external world.

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `tool_id` | String | Yes | Unique identifier. Used in function calling. |
| `name` | String | Yes | Human-readable name. |
| `description` | String | Yes | Concise explanation for LLM. Critical for tool selection. |
| `provider` | String | Yes | Service provider (e.g., "google", "slack", "internal"). |
| `authentication` | Object | Yes | Credentials management. |
| `function_schema` | Object | Yes | OpenAI-compatible function definition for LLM. |
| `rate_limit` | Object | No | Prevents API quota exhaustion. |
| `permissions` | Enum | Yes | READ (safe), WRITE (requires approval), EXECUTE (dangerous). |
| `sandbox_mode` | Boolean | No | If true, execute in isolated environment (for testing). |

**Implementation Logic:**

python  
async def invoke\_tool(tool, parameters, context):  
    *\# Check rate limits*  
    if exceeds\_rate\_limit(tool):  
        raise RateLimitError(f"Tool {tool.name} rate limit exceeded")  
      
    *\# Validate parameters against schema*  
    validate\_parameters(parameters, tool.function\_schema)  
      
    *\# Check permissions*  
    if tool.permissions \== "WRITE":  
        if not context.has\_write\_permission:  
            raise PermissionError(f"Write permission required for {tool.name}")  
      
    *\# Get credentials*  
    credentials \= get\_credentials(tool.authentication.credentials\_ref)  
      
    *\# Execute tool*  
    if tool.sandbox\_mode:  
        result \= await execute\_in\_sandbox(tool, parameters, credentials)  
    else:  
        result \= await execute\_tool(tool, parameters, credentials)  
      
    *\# Log usage*  
    log\_tool\_call(context.run\_id, tool.tool\_id, parameters, result)  
    

    return result

#### **3.6.2 Memory**

Memory allows entities to remember past interactions.

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `enabled` | Boolean | Yes | If false, entity is stateless. |
| `scope` | Enum | Yes | SESSION (cleared after execution), ENTITY (persists across runs), GLOBAL (shared across entities). |
| `storage_backend` | Enum | Yes | REDIS (fast), POSTGRES\_JSONB (structured), VECTOR\_DB (semantic search). |
| `retention_policy` | Object | Yes | Controls memory lifecycle. |
| `access_pattern` | Enum | Yes | FULL (load all memory), SEMANTIC\_SEARCH (vector similarity), RECENT\_N (last N items). |

**Implementation Logic:**

python  
class Memory:  
    def \_\_init\_\_(self, config):  
        self.config \= config  
        self.backend \= get\_storage\_backend(config.storage\_backend)  
      
    async def store(self, key, value, context):  
        *\# Apply retention policy*  
        if self.config.retention\_policy.max\_items:  
            current\_count \= await self.backend.count(context.entity\_id)  
            if current\_count \>= self.config.retention\_policy.max\_items:  
                await self.summarize\_and\_prune(context)  
          
        await self.backend.set(  
            key\=f"{context.entity\_id}:{key}",  
            value\=value,  
            ttl\=self.config.retention\_policy.ttl\_seconds  
        )  
      
    async def retrieve(self, query, context):  
        if self.config.access\_pattern \== "SEMANTIC\_SEARCH":  
            return await self.backend.vector\_search(query, top\_k\=5)  
        elif self.config.access\_pattern \== "RECENT\_N":  
            return await self.backend.get\_last\_n(context.entity\_id, n\=10)  
        else:

            return await self.backend.get\_all(context.entity\_id)

#### **3.6.3 Context Engineering**

Controls how much context is fed to the LLM.

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `max_context_tokens` | Integer | Yes | Hard limit. Prevents token overflow. |
| `context_priority` | Array\[Enum\] | Yes | Order in which context elements are included. |
| `artifact_handling` | Object | Yes | How to handle large objects (resumes, documents). |

**Implementation Logic:**

python  
def build\_context(entity, input\_data, state, memory):  
    context\_elements \= \[\]  
      
    *\# Build elements based on priority*  
    for priority in entity.capabilities.context\_engineering.context\_priority:  
        if priority \== "SYSTEM\_PROMPT":  
            context\_elements.append({  
                "type": "system",  
                "content": entity.identity.persona.system\_prompt,  
                "tokens": count\_tokens(entity.identity.persona.system\_prompt)  
            })  
        elif priority \== "STATIC\_PLAN":  
            context\_elements.append({  
                "type": "static\_plan",  
                "content": json.dumps(entity.planning.static\_plan.steps),  
                "tokens": count\_tokens(json.dumps(entity.planning.static\_plan.steps))  
            })  
        *\# ... other priorities*  
      
    *\# Trim to fit max\_context\_tokens*  
    total\_tokens \= sum(e\["tokens"\] for e in context\_elements)  
    max\_tokens \= entity.capabilities.context\_engineering.max\_context\_tokens  
      
    if total\_tokens \> max\_tokens:  
        *\# Remove lowest priority elements*  
        context\_elements \= trim\_context(context\_elements, max\_tokens)  
    

    return context\_elements

### **3.7 Governance Section**

#### **3.7.1 Cost Controls**

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `max_cost_usd` | Decimal | No | Per-execution budget. Execution stops if exceeded. |
| `cumulative_cost_usd` | Decimal | No | Lifetime budget for this entity. |
| `alert_threshold_usd` | Decimal | No | Warning notification before hitting limit. |

**Implementation Logic:**

python  
class CostTracker:  
    def track\_llm\_call(self, run\_id, prompt\_tokens, completion\_tokens, model):  
        cost \= calculate\_cost(model, prompt\_tokens, completion\_tokens)  
          
        *\# Update run cost*  
        self.db.increment\_cost(run\_id, cost)  
          
        *\# Check limits*  
        current\_cost \= self.db.get\_run\_cost(run\_id)  
        entity \= self.db.get\_entity(run\_id)  
          
        if entity.governance.cost\_controls.max\_cost\_usd:  
            if current\_cost \>= entity.governance.cost\_controls.max\_cost\_usd:  
                raise CostLimitExceeded(f"Execution cost ${current\_cost} exceeds limit")  
          
        if entity.governance.cost\_controls.alert\_threshold\_usd:  
            if current\_cost \>= entity.governance.cost\_controls.alert\_threshold\_usd:

                send\_alert(f"Cost approaching limit: ${current\_cost}")

#### **3.7.2 Execution Limits**

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `timeout_ms` | Integer | Yes | Maximum execution time. Prevents hanging. |
| `max_recursion_depth` | Integer | Yes | Maximum nesting level. Prevents infinite delegation. |
| `max_tool_calls` | Integer | No | Limit on external API calls per execution. |
| `max_llm_calls` | Integer | No | Limit on LLM invocations per execution. |

#### **3.7.3 Human Oversight**

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `hitl_checkpoints` | Array\[Object\] | No | Points where human approval is required. |
| `hitl_checkpoints[].trigger` | Enum | Yes | BEFORE\_EXECUTION, AFTER\_PLANNING, BEFORE\_TOOL\_CALL, ON\_FAILURE, CUSTOM\_CONDITION. |
| `hitl_checkpoints[].approval_required` | Boolean | Yes | If true, execution pauses until human approves. |
| `hitl_checkpoints[].timeout_action` | Enum | Yes | PROCEED (continue without approval), ABORT (stop), ESCALATE (notify manager). |

**Implementation Logic:**

python  
async def check\_hitl(checkpoint, context):  
    if checkpoint.condition:  
        should\_trigger \= evaluate\_condition(checkpoint.condition, context.state)  
        if not should\_trigger:  
            return  
      
    if checkpoint.approval\_required:  
        *\# Pause execution and request approval*  
        approval\_id \= await request\_approval(  
            run\_id\=context.run\_id,  
            checkpoint\=checkpoint,  
            context\=context  
        )  
          
        *\# Wait for approval with timeout*  
        try:  
            approved \= await wait\_for\_approval(  
                approval\_id,   
                timeout\=checkpoint.timeout\_ms  
            )  
        except TimeoutError:  
            if checkpoint.timeout\_action \== "PROCEED":  
                return  
            elif checkpoint.timeout\_action \== "ABORT":  
                raise ExecutionAborted("HITL approval timeout")  
            elif checkpoint.timeout\_action \== "ESCALATE":  
                await escalate\_to\_manager(context)  
                raise ExecutionPaused("Awaiting manager decision")  
          
        if not approved:

            raise ExecutionRejected("Human reviewer rejected execution")

#### **3.7.4 Safety Rails**

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `content_filters` | Array\[Enum\] | No | TOXICITY, PII, PROFANITY, BIAS filters applied to LLM output. |
| `action_restrictions` | Array\[Object\] | No | List of dangerous actions requiring special handling. |
| `output_validation` | Object | No | JSON schema validation for entity output. |

### **3.8 IO Contract Section**

Defines the input/output interface for the entity.

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `input.schema` | JSON Schema | Yes | Validates input data before execution. |
| `input.validation_rules` | Array\[Object\] | No | Additional custom validation (e.g., business rules). |
| `output.schema` | JSON Schema | Yes | Validates output before returning to parent. |
| `output.transformations` | Array\[Object\] | No | Post-processing (e.g., format dates, capitalize names). |
| `state_contract.reads_from` | Array\[String\] | No | Documents which state keys this entity reads. |
| `state_contract.writes_to` | Array\[String\] | No | Documents which state keys this entity modifies. |
| `state_contract.side_effects` | Array\[String\] | No | External effects (e.g., "sends\_email", "creates\_database\_record"). |

### **3.9 Observability Section**

| Field | Type | Required | Implementation Logic |
| ----- | ----- | ----- | ----- |
| `logging.log_level` | Enum | Yes | DEBUG (everything), INFO (key events), WARN (issues), ERROR (failures). |
| `logging.log_thoughts` | Boolean | Yes | If true, log all LLM reasoning steps. |
| `logging.log_tool_calls` | Boolean | Yes | If true, log all tool invocations with parameters. |
| `metrics.track_latency` | Boolean | Yes | Measure execution time for each step. |
| `metrics.track_token_usage` | Boolean | Yes | Count tokens for cost attribution. |
| `tracing.trace_id_propagation` | Boolean | Yes | Pass trace\_id to child entities for hierarchical tracing. |

---

## **4\. Execution Logic Framework**

### **4.1 Unified Execution Engine**

The execution engine operates as a recursive state machine that handles all entity types uniformly:

python  
*\# Pseudo-code for unified execution logic*  
async def execute\_entity(entity\_id: UUID, input\_data: Dict, parent\_run\_id: UUID \= None) \-\> ExecutionResult:  
    *\# 1\. Load Entity Definition*  
    entity \= load\_entity(entity\_id)  
      
    *\# 2\. Create Execution Run Record*  
    run \= create\_execution\_run(  
        entity\_id\=entity\_id,  
        parent\_run\_id\=parent\_run\_id,  
        input\_data\=input\_data,  
        status\=ExecutionStatus.RUNNING  
    )  
      
    *\# 3\. Initialize Context*  
    context \= ExecutionContext(  
        entity\=entity,  
        run\=run,  
        state\={},  
        memory\=load\_memory(entity.capabilities.memory),  
        trace\_id\=run.id  
    )  
      
    *\# 4\. Plan Generation/Loading*  
    if entity.planning.dynamic\_planning.enabled:  
        dynamic\_plan \= await generate\_dynamic\_plan(entity, input\_data, context)  
        reconciled\_plan \= reconcile\_plans(  
            entity.planning.static\_plan,  
            dynamic\_plan,  
            entity.planning.dynamic\_planning.reconciliation\_strategy  
        )  
    else:  
        reconciled\_plan \= entity.planning.static\_plan  
      
    *\# 5\. Execute Plan Steps*  
    results \= \[\]  
    iteration\_count \= 0  
      
    while not plan\_complete(reconciled\_plan, results) and iteration\_count \< entity.planning.loop\_control.max\_iterations:  
        step \= get\_next\_step(reconciled\_plan, results, context)  
          
        *\# HITL Checkpoint*  
        if requires\_human\_approval(step, entity.governance.human\_oversight):  
            await request\_approval(step, context)  
          
        *\# Execute Step*  
        step\_result \= await execute\_step(step, context, entity)  
          
        *\# Review Mechanism*  
        if entity.logic\_gate.review\_mechanism.enabled:  
            review \= await review\_step\_output(step\_result, entity.logic\_gate.review\_mechanism)  
            if not review.passed:  
                step\_result \= await handle\_review\_failure(  
                    step\_result,  
                    review,  
                    entity.logic\_gate.review\_mechanism.on\_failure  
                )  
          
        results.append(step\_result)  
          
        *\# Update Context*  
        context \= update\_context(context, step\_result)  
          
        *\# Check Convergence*  
        if check\_convergence(results, entity.planning.loop\_control.convergence\_criteria):  
            break  
          
        iteration\_count \+= 1  
      
    *\# 6\. Finalize Execution*  
    output \= extract\_output(results, entity.io\_contract.output)  
      
    update\_execution\_run(  
        run\_id\=run.id,  
        status\=ExecutionStatus.COMPLETED,  
        output\=output,  
        dynamic\_plan\=reconciled\_plan  
    )  
      
    return ExecutionResult(  
        run\_id\=run.id,  
        output\=output,  
        metrics\=collect\_metrics(context)  
    )

async def execute\_step(step: PlanStep, context: ExecutionContext, entity: Entity) \-\> StepResult:  
    if step.type \== StepType.CHILD\_ENTITY\_INVOCATION:  
        *\# Recursive call \- treat child entity as sub-execution*  
        child\_output \= await execute\_entity(  
            entity\_id\=step.target.entity\_id,  
            input\_data\=prepare\_child\_input(step, context),  
            parent\_run\_id\=context.run.id  
        )  
        return StepResult(type\=StepType.CHILD\_ENTITY\_INVOCATION, output\=child\_output)  
      
    elif step.type \== StepType.TOOL\_CALL:  
        *\# Execute tool*  
        tool \= get\_tool(step.target.tool\_id, entity.capabilities.tools)  
        tool\_output \= await invoke\_tool(tool, step.parameters, context)  
          
        *\# Log tool interaction*  
        log\_tool\_call(  
            run\_id\=context.run.id,  
            tool\_id\=tool.tool\_id,  
            input\=step.parameters,  
            output\=tool\_output  
        )  
          
        return StepResult(type\=StepType.TOOL\_CALL, output\=tool\_output)  
      
    elif step.type \== StepType.THOUGHT:  
        *\# LLM reasoning step*  
        llm\_response \= await call\_llm(  
            model\=entity.logic\_gate.reasoning\_config,  
            prompt\=render\_prompt(step.target.prompt\_template, context),  
            context\=context  
        )  
          
        *\# Log LLM interaction*  
        log\_llm\_call(  
            run\_id\=context.run.id,  
            model\=entity.logic\_gate.reasoning\_config.model\_name,  
            prompt\=llm\_response.prompt,  
            response\=llm\_response.output,  
            prompt\_tokens\=llm\_response.prompt\_tokens,  
            completion\_tokens\=llm\_response.completion\_tokens  
        )  
        

        return StepResult(type\=StepType.THOUGHT, output\=llm\_response.output)

### **4.2 Plan Reconciliation Algorithm**

python  
def reconcile\_plans(static\_plan: StaticPlan, dynamic\_plan: List\[PlanStep\], strategy: ReconciliationStrategy) \-\> List\[PlanStep\]:  
    if strategy \== ReconciliationStrategy.STATIC\_PRIORITY:  
        *\# Static plan is authoritative; dynamic additions only fill gaps*  
        merged \= static\_plan.steps.copy()  
        for dyn\_step in dynamic\_plan:  
            if not violates\_constraints(dyn\_step, static\_plan) and is\_gap\_filler(dyn\_step, merged):  
                merged.append(dyn\_step)  
        return merged  
      
    elif strategy \== ReconciliationStrategy.DYNAMIC\_PRIORITY:  
        *\# Dynamic plan is authoritative; static only provides guardrails*  
        filtered \= \[step for step in dynamic\_plan if not violates\_constraints(step, static\_plan)\]  
        return ensure\_required\_steps(filtered, static\_plan)  
      
    elif strategy \== ReconciliationStrategy.HYBRID:  
        *\# Intelligent merge: required static steps \+ optimized dynamic additions*  
        merged \= \[step for step in static\_plan.steps if step.required\]  
          
        for dyn\_step in dynamic\_plan:  
            if not violates\_constraints(dyn\_step, static\_plan):  
                insertion\_point \= find\_optimal\_insertion(dyn\_step, merged, static\_plan)  
                merged.insert(insertion\_point, dyn\_step)  
        

        return merged

---

## **5\. Database Schema**

### **5.1 Core Tables**

#### **Table: `hierarchical_entities`**

Stores the design-time configuration of all entities.

sql  
CREATE TABLE hierarchical\_entities (  
    id UUID PRIMARY KEY DEFAULT gen\_random\_uuid(),  
    version VARCHAR(20) NOT NULL,  
    type VARCHAR(20) NOT NULL CHECK (type IN ('ACTION', 'SKILL', 'AGENT', 'PROCESS')),  
    created\_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),  
    updated\_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),  
    created\_by UUID NOT NULL REFERENCES users(id),  
    tags TEXT\[\],  
    status VARCHAR(20) NOT NULL CHECK (status IN ('DRAFT', 'ACTIVE', 'DEPRECATED', 'ARCHIVED')),  
      
    *\-- Identity*  
    name VARCHAR(100) UNIQUE NOT NULL,  
    display\_name VARCHAR(200),  
    description TEXT,  
    persona JSONB,  
    icon VARCHAR(50),  
    color VARCHAR(7),  
      
    *\-- Hierarchy*  
    parent\_id UUID REFERENCES hierarchical\_entities(id),  
    children JSONB,  
    is\_atomic BOOLEAN,  
    composition\_depth INTEGER,  
      
    *\-- Logic Gate*  
    logic\_gate JSONB NOT NULL,  
      
    *\-- Planning*  
    planning JSONB NOT NULL,  
      
    *\-- Capabilities*  
    capabilities JSONB NOT NULL,  
      
    *\-- Governance*  
    governance JSONB NOT NULL,  
      
    *\-- IO Contract*  
    io\_contract JSONB NOT NULL,  
      
    *\-- Observability*  
    observability JSONB NOT NULL,  
      
    *\-- Extensions*  
    metadata\_extensions JSONB  
);

CREATE INDEX idx\_entities\_type ON hierarchical\_entities(type);  
CREATE INDEX idx\_entities\_parent ON hierarchical\_entities(parent\_id);  
CREATE INDEX idx\_entities\_status ON hierarchical\_entities(status);

CREATE INDEX idx\_entities\_tags ON hierarchical\_entities USING GIN(tags);

#### **Table: `execution_runs`**

Captures runtime instances of entity executions.

sql  
CREATE TABLE execution\_runs (  
    id UUID PRIMARY KEY DEFAULT gen\_random\_uuid(),  
    entity\_id UUID NOT NULL REFERENCES hierarchical\_entities(id),  
    parent\_run\_id UUID REFERENCES execution\_runs(id),  
      
    started\_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),  
    completed\_at TIMESTAMP WITH TIME ZONE,  
    status VARCHAR(20) NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'PAUSED')),  
      
    input\_data JSONB,  
    output\_data JSONB,  
      
    dynamic\_plan JSONB,  
    context\_state JSONB,  
      
    error\_message TEXT,  
      
    total\_cost\_usd DECIMAL(10, 4) DEFAULT 0,  
    total\_tokens INTEGER DEFAULT 0,  
    execution\_time\_ms INTEGER,  
      
    trace\_id UUID NOT NULL,  
    span\_id VARCHAR(50)  
);

CREATE INDEX idx\_runs\_entity ON execution\_runs(entity\_id);  
CREATE INDEX idx\_runs\_parent ON execution\_runs(parent\_run\_id);  
CREATE INDEX idx\_runs\_trace ON execution\_runs(trace\_id);  
CREATE INDEX idx\_runs\_status ON execution\_runs(status);

CREATE INDEX idx\_runs\_started ON execution\_runs(started\_at DESC);

#### **Table: `llm_interaction_logs`**

Granular logging for every LLM call.

sql  
CREATE TABLE llm\_interaction\_logs (  
    id UUID PRIMARY KEY DEFAULT gen\_random\_uuid(),  
    run\_id UUID NOT NULL REFERENCES execution\_runs(id),  
      
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),  
      
    model\_provider VARCHAR(50) NOT NULL,  
    model\_name VARCHAR(100) NOT NULL,  
      
    input\_prompt TEXT NOT NULL,  
    output\_response TEXT NOT NULL,  
      
    prompt\_tokens INTEGER NOT NULL,  
    completion\_tokens INTEGER NOT NULL,  
    total\_tokens INTEGER GENERATED ALWAYS AS (prompt\_tokens \+ completion\_tokens) STORED,  
      
    cost\_usd DECIMAL(10, 6) NOT NULL,  
    latency\_ms INTEGER NOT NULL,  
      
    temperature FLOAT,  
    reasoning\_mode VARCHAR(50),  
      
    metadata JSONB  
);

CREATE INDEX idx\_llm\_logs\_run ON llm\_interaction\_logs(run\_id);  
CREATE INDEX idx\_llm\_logs\_timestamp ON llm\_interaction\_logs(timestamp DESC);

CREATE INDEX idx\_llm\_logs\_model ON llm\_interaction\_logs(model\_provider, model\_name);

#### **Table: `tool_interaction_logs`**

Logs all tool/function calls.

sql  
CREATE TABLE tool\_interaction\_logs (

    id UUID PRIMARY KEY DEFAULT gen\_random\_

uuid(), run\_id UUID NOT NULL REFERENCES execution\_runs(id),

timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

tool\_id VARCHAR(100) NOT NULL,  
tool\_name VARCHAR(200) NOT NULL,  
provider VARCHAR(50),

input\_parameters JSONB NOT NULL,  
output\_result JSONB,

success BOOLEAN NOT NULL,  
error\_message TEXT,

latency\_ms INTEGER NOT NULL,

metadata JSONB

);

CREATE INDEX idx\_tool\_logs\_run ON tool\_interaction\_logs(run\_id); CREATE INDEX idx\_tool\_logs\_tool ON tool\_interaction\_logs(tool\_id); CREATE INDEX idx\_tool\_logs\_timestamp ON tool\_interaction\_logs(timestamp DESC);

\#\#\#\# \*\*Table: \`human\_approvals\`\*\*

Tracks HITL checkpoint approvals.  
\`\`\`sql  
CREATE TABLE human\_approvals (  
    id UUID PRIMARY KEY DEFAULT gen\_random\_uuid(),  
    run\_id UUID NOT NULL REFERENCES execution\_runs(id),  
      
    checkpoint\_trigger VARCHAR(50) NOT NULL,  
      
    requested\_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),  
    responded\_at TIMESTAMP WITH TIME ZONE,  
      
    status VARCHAR(20) NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'TIMEOUT')),  
      
    requested\_by VARCHAR(100),  
    responded\_by UUID REFERENCES users(id),  
      
    context\_snapshot JSONB,  
    reviewer\_notes TEXT,  
      
    notification\_channels TEXT\[\],  
    timeout\_ms INTEGER  
);

CREATE INDEX idx\_approvals\_run ON human\_approvals(run\_id);  
CREATE INDEX idx\_approvals\_status ON human\_approvals(status);  
CREATE INDEX idx\_approvals\_requested ON human\_approvals(requested\_at DESC);  
\`\`\`

\---

\#\# \*\*6. Practical Implementation Example\*\*

\#\#\# \*\*6.1 Example: Video Advertising Process\*\*

Let's define a complete Process for creating video advertisements for job postings.

\#\#\#\# \*\*Process Entity: "Video Ad Creation Process"\*\*  
\`\`\`json  
{  
  "metadata": {  
    "id": "proc-001",  
    "version": "1.0.0",  
    "type": "PROCESS",  
    "created\_at": "2025-01-15T10:00:00Z",  
    "updated\_at": "2025-01-15T10:00:00Z",  
    "created\_by": "user-123",  
    "tags": \["recruitment", "video", "advertising"\],  
    "status": "ACTIVE"  
  },  
    
  "identity": {  
    "name": "video\_ad\_creation\_process",  
    "display\_name": "Video Ad Creation Process",  
    "description": "Automated process to create video advertisements for job postings",  
    "persona": {  
      "system\_prompt": "You are a creative recruitment marketing process manager. Your goal is to coordinate the creation of compelling video advertisements that attract qualified candidates. Ensure all content is professional, inclusive, and compliant with employment law.",  
      "examples": \[  
        {  
          "scenario": "Creating video for Senior Software Engineer position",  
          "ideal\_response": "I will first analyze the job description, then generate a script highlighting technical challenges and company culture, create visual storyboards, and finally produce a 30-second video with captions."  
        }  
      \],  
      "behavioral\_constraints": \[  
        "Never use discriminatory language or imagery",  
        "Always include accessibility features (captions, audio descriptions)",  
        "Obtain approval before publishing externally"  
      \]  
    },  
    "icon": "video-camera",  
    "color": "\#FF6B6B"  
  },  
    
  "hierarchy": {  
    "parent\_id": null,  
    "children": \[  
      {  
        "child\_id": "agent-001",  
        "child\_type": "AGENT",  
        "relationship": "SEQUENTIAL",  
        "condition": {  
          "enabled": false  
        }  
      },  
      {  
        "child\_id": "agent-002",  
        "child\_type": "AGENT",  
        "relationship": "SEQUENTIAL",  
        "condition": {  
          "enabled": false  
        }  
      },  
      {  
        "child\_id": "agent-003",  
        "child\_type": "AGENT",  
        "relationship": "SEQUENTIAL",  
        "condition": {  
          "enabled": false  
        }  
      }  
    \],  
    "is\_atomic": false,  
    "composition\_depth": 0  
  },  
    
  "logic\_gate": {  
    "reasoning\_config": {  
      "model\_provider": "google",  
      "model\_name": "gemini-2.0-flash",  
      "model\_version": null,  
      "temperature": 0.7,  
      "top\_p": 0.95,  
      "max\_tokens": 2048,  
      "reasoning\_mode": "REACT"  
    },  
    "retry\_policy": {  
      "max\_retries": 2,  
      "backoff\_strategy": "EXPONENTIAL",  
      "backoff\_multiplier": 2.0,  
      "retry\_on": \["TOOL\_FAILURE", "LLM\_ERROR", "TIMEOUT"\]  
    },  
    "review\_mechanism": {  
      "enabled": true,  
      "review\_prompt": "Review the complete video ad creation process. Ensure all steps completed successfully and the final video meets quality standards. Output: {output}",  
      "success\_criteria": \[  
        {  
          "criterion": "Video file exists and is valid",  
          "validation\_type": "FUNCTION",  
          "validator": "validate\_video\_file"  
        },  
        {  
          "criterion": "Video duration is between 20-40 seconds",  
          "validation\_type": "FUNCTION",  
          "validator": "check\_video\_duration"  
        }  
      \],  
      "on\_failure": "ESCALATE"  
    }  
  },  
    
  "planning": {  
    "static\_plan": {  
      "enabled": true,  
      "steps": \[  
        {  
          "step\_id": "step-001",  
          "order": 1,  
          "name": "Analyze Job Description",  
          "description": "Invoke Content Analyst Agent to extract key selling points",  
          "type": "CHILD\_ENTITY\_INVOCATION",  
          "target": {  
            "entity\_id": "agent-001",  
            "tool\_id": null,  
            "prompt\_template": null  
          },  
          "required": true,  
          "exit\_conditions": \[\]  
        },  
        {  
          "step\_id": "step-002",  
          "order": 2,  
          "name": "Generate Script & Storyboard",  
          "description": "Invoke Creative Director Agent to create video script",  
          "type": "CHILD\_ENTITY\_INVOCATION",  
          "target": {  
            "entity\_id": "agent-002",  
            "tool\_id": null,  
            "prompt\_template": null  
          },  
          "required": true,  
          "exit\_conditions": \[\]  
        },  
        {  
          "step\_id": "step-003",  
          "order": 3,  
          "name": "Produce Video",  
          "description": "Invoke Video Production Agent to create final video",  
          "type": "CHILD\_ENTITY\_INVOCATION",  
          "target": {  
            "entity\_id": "agent-003",  
            "tool\_id": null,  
            "prompt\_template": null  
          },  
          "required": true,  
          "exit\_conditions": \[\]  
        }  
      \],  
      "fallback\_behavior": "ADAPTIVE"  
    },  
    "dynamic\_planning": {  
      "enabled": true,  
      "planning\_prompt": "Given the job description and company requirements, determine if additional steps are needed (e.g., translation for multilingual markets, A/B testing variants, compliance review).",  
      "constraints": \[  
        "All videos must go through compliance review before external publishing",  
        "Budget cannot exceed $500 per video"  
      \],  
      "reconciliation\_strategy": "HYBRID",  
      "allowed\_deviations": {  
        "can\_add\_steps": true,  
        "can\_skip\_optional\_steps": true,  
        "can\_reorder\_steps": false,  
        "can\_change\_tools": false  
      }  
    },  
    "loop\_control": {  
      "max\_iterations": 1,  
      "convergence\_criteria": \[\],  
      "iteration\_context\_mode": "FULL\_HISTORY",  
      "summary\_every\_n\_iterations": null  
    }  
  },  
    
  "capabilities": {  
    "tools": \[\],  
    "memory": {  
      "enabled": true,  
      "scope": "ENTITY",  
      "storage\_backend": "POSTGRES\_JSONB",  
      "retention\_policy": {  
        "max\_items": 100,  
        "ttl\_seconds": 2592000,  
        "summarization\_threshold": 50  
      },  
      "access\_pattern": "RECENT\_N"  
    },  
    "context\_engineering": {  
      "max\_context\_tokens": 128000,  
      "context\_priority": \[  
        "SYSTEM\_PROMPT",  
        "USER\_INPUT",  
        "STATIC\_PLAN",  
        "MEMORY",  
        "DYNAMIC\_PLAN"  
      \],  
      "artifact\_handling": {  
        "store\_large\_objects": true,  
        "artifact\_reference\_mode": "REFERENCE"  
      }  
    }  
  },  
    
  "governance": {  
    "cost\_controls": {  
      "max\_cost\_usd": 5.00,  
      "cumulative\_cost\_usd": null,  
      "alert\_threshold\_usd": 3.00  
    },  
    "execution\_limits": {  
      "timeout\_ms": 300000,  
      "max\_recursion\_depth": 4,  
      "max\_tool\_calls": 50,  
      "max\_llm\_calls": 20  
    },  
    "human\_oversight": {  
      "hitl\_checkpoints": \[  
        {  
          "trigger": "BEFORE\_EXECUTION",  
          "condition": null,  
          "approval\_required": false,  
          "notification\_channels": \["IN\_APP"\],  
          "timeout\_action": "PROCEED"  
        },  
        {  
          "trigger": "ON\_FAILURE",  
          "condition": null,  
          "approval\_required": true,  
          "notification\_channels": \["EMAIL", "SLACK"\],  
          "timeout\_action": "ABORT"  
        }  
      \],  
      "audit\_level": "STANDARD",  
      "pii\_handling": "REDACT"  
    },  
    "safety\_rails": {  
      "content\_filters": \["TOXICITY", "BIAS"\],  
      "action\_restrictions": \[\],  
      "output\_validation": {  
        "enabled": true,  
        "schema": {  
          "type": "object",  
          "properties": {  
            "video\_url": {"type": "string"},  
            "duration\_seconds": {"type": "number"},  
            "script": {"type": "string"}  
          },  
          "required": \["video\_url", "duration\_seconds"\]  
        }  
      }  
    }  
  },  
    
  "io\_contract": {  
    "input": {  
      "schema": {  
        "type": "object",  
        "properties": {  
          "job\_description": {  
            "type": "string",  
            "description": "Full text of job posting",  
            "required": true  
          },  
          "company\_name": {  
            "type": "string",  
            "description": "Company name",  
            "required": true  
          },  
          "target\_audience": {  
            "type": "string",  
            "description": "Target candidate persona",  
            "required": false  
          }  
        }  
      },  
      "validation\_rules": \[  
        {  
          "rule": "job\_description must be at least 100 characters",  
          "validator": "length\_validator"  
        }  
      \]  
    },  
    "output": {  
      "schema": {  
        "type": "object",  
        "properties": {  
          "video\_url": {  
            "type": "string",  
            "description": "URL to final video file"  
          },  
          "script": {  
            "type": "string",  
            "description": "Final approved script"  
          },  
          "duration\_seconds": {  
            "type": "number",  
            "description": "Video duration"  
          },  
          "cost\_usd": {  
            "type": "number",  
            "description": "Total production cost"  
          }  
        }  
      },  
      "transformations": \[\]  
    },  
    "state\_contract": {  
      "reads\_from": \[\],  
      "writes\_to": \["video\_production\_history"\],  
      "side\_effects": \["uploads\_to\_cdn", "sends\_notification"\]  
    }  
  },  
    
  "observability": {  
    "logging": {  
      "log\_level": "INFO",  
      "log\_thoughts": true,  
      "log\_tool\_calls": true,  
      "log\_state\_changes": true  
    },  
    "metrics": {  
      "track\_latency": true,  
      "track\_token\_usage": true,  
      "track\_cost": true,  
      "custom\_metrics": \[  
        {  
          "metric\_name": "video\_quality\_score",  
          "aggregation": "AVG"  
        }  
      \]  
    },  
    "tracing": {  
      "trace\_id\_propagation": true,  
      "span\_annotations": \["video\_production", "recruitment"\]  
    }  
  },  
    
  "metadata\_extensions": {  
    "custom\_fields": {  
      "department": "marketing",  
      "compliance\_reviewed": true  
    },  
    "ui\_hints": {  
      "form\_layout": "wizard",  
      "visibility": "WORKSPACE",  
      "is\_template": true  
    }  
  }  
}  
\`\`\`

\#\#\#\# \*\*Agent Entity: "Content Analyst Agent"\*\*  
\`\`\`json  
{  
  "metadata": {  
    "id": "agent-001",  
    "version": "1.0.0",  
    "type": "AGENT",  
    "status": "ACTIVE"  
  },  
    
  "identity": {  
    "name": "content\_analyst\_agent",  
    "display\_name": "Content Analyst",  
    "description": "Analyzes job descriptions and extracts key messaging points",  
    "persona": {  
      "system\_prompt": "You are an expert recruitment marketing analyst. Your role is to analyze job descriptions and identify the most compelling aspects that will attract qualified candidates. Focus on: unique selling points, company culture, growth opportunities, and technical challenges.",  
      "behavioral\_constraints": \[  
        "Avoid generic corporate jargon",  
        "Focus on candidate-centric value propositions"  
      \]  
    }  
  },  
    
  "hierarchy": {  
    "parent\_id": "proc-001",  
    "children": \[  
      {  
        "child\_id": "skill-001",  
        "child\_type": "SKILL",  
        "relationship": "SEQUENTIAL"  
      },  
      {  
        "child\_id": "skill-002",  
        "child\_type": "SKILL",  
        "relationship": "SEQUENTIAL"  
      }  
    \],  
    "is\_atomic": false,  
    "composition\_depth": 1  
  },  
    
  "planning": {  
    "static\_plan": {  
      "enabled": true,  
      "steps": \[  
        {  
          "step\_id": "step-a1",  
          "order": 1,  
          "name": "Extract Key Information",  
          "type": "CHILD\_ENTITY\_INVOCATION",  
          "target": {  
            "entity\_id": "skill-001"  
          },  
          "required": true  
        },  
        {  
          "step\_id": "step-a2",  
          "order": 2,  
          "name": "Identify Selling Points",  
          "type": "CHILD\_ENTITY\_INVOCATION",  
          "target": {  
            "entity\_id": "skill-002"  
          },  
          "required": true  
        }  
      \]  
    },  
    "dynamic\_planning": {  
      "enabled": false  
    }  
  },  
    
  "io\_contract": {  
    "input": {  
      "schema": {  
        "type": "object",  
        "properties": {  
          "job\_description": {"type": "string", "required": true}  
        }  
      }  
    },  
    "output": {  
      "schema": {  
        "type": "object",  
        "properties": {  
          "key\_requirements": {"type": "array"},  
          "selling\_points": {"type": "array"},  
          "target\_persona": {"type": "string"}  
        }  
      }  
    }  
  }  
}  
\`\`\`

\#\#\#\# \*\*Skill Entity: "Information Extraction Skill"\*\*  
\`\`\`json  
{  
  "metadata": {  
    "id": "skill-001",  
    "version": "1.0.0",  
    "type": "SKILL",  
    "status": "ACTIVE"  
  },  
    
  "identity": {  
    "name": "information\_extraction\_skill",  
    "display\_name": "Information Extraction",  
    "description": "Extracts structured information from unstructured job descriptions"  
  },  
    
  "hierarchy": {  
    "parent\_id": "agent-001",  
    "children": \[  
      {  
        "child\_id": "action-001",  
        "child\_type": "ACTION",  
        "relationship": "SEQUENTIAL"  
      },  
      {  
        "child\_id": "action-002",  
        "child\_type": "ACTION",  
        "relationship": "SEQUENTIAL"  
      }  
    \],  
    "is\_atomic": false,  
    "composition\_depth": 2  
  },  
    
  "planning": {  
    "static\_plan": {  
      "enabled": true,  
      "steps": \[  
        {  
          "step\_id": "step-s1",  
          "order": 1,  
          "name": "Parse Job Description",  
          "type": "CHILD\_ENTITY\_INVOCATION",  
          "target": {  
            "entity\_id": "action-001"  
          },  
          "required": true  
        },  
        {  
          "step\_id": "step-s2",  
          "order": 2,  
          "name": "Validate Extracted Data",  
          "type": "CHILD\_ENTITY\_INVOCATION",  
          "target": {  
            "entity\_id": "action-002"  
          },  
          "required": true  
        }  
      \]  
    },  
    "dynamic\_planning": {  
      "enabled": true,  
      "planning\_prompt": "If the job description is poorly formatted, add additional cleanup steps.",  
      "reconciliation\_strategy": "HYBRID",  
      "allowed\_deviations": {  
        "can\_add\_steps": true,  
        "can\_skip\_optional\_steps": false  
      }  
    },  
    "loop\_control": {  
      "max\_iterations": 3,  
      "convergence\_criteria": \[  
        {  
          "metric": "extraction\_confidence",  
          "threshold": 0.8,  
          "operator": "GTE"  
        }  
      \],  
      "iteration\_context\_mode": "LAST\_N"  
    }  
  }  
}  
\`\`\`

\#\#\#\# \*\*Action Entity: "NLP Parsing Action"\*\*  
\`\`\`json  
{  
  "metadata": {  
    "id": "action-001",  
    "version": "1.0.0",  
    "type": "ACTION",  
    "status": "ACTIVE"  
  },  
    
  "identity": {  
    "name": "nlp\_parsing\_action",  
    "display\_name": "NLP Parsing",  
    "description": "Uses NLP to parse job description into structured fields"  
  },  
    
  "hierarchy": {  
    "parent\_id": "skill-001",  
    "children": \[\],  
    "is\_atomic": true,  
    "composition\_depth": 3  
  },  
    
  "logic\_gate": {  
    "reasoning\_config": {  
      "model\_provider": "google",  
      "model\_name": "gemini-2.0-flash",  
      "temperature": 0.3,  
      "reasoning\_mode": "CHAIN\_OF\_THOUGHT"  
    },  
    "retry\_policy": {  
      "max\_retries": 3,  
      "backoff\_strategy": "EXPONENTIAL",  
      "retry\_on": \["LLM\_ERROR", "TIMEOUT"\]  
    },  
    "review\_mechanism": {  
      "enabled": true,  
      "review\_prompt": "Review the extracted fields. Are all required fields present and accurate? Output: {output}",  
      "success\_criteria": \[  
        {  
          "criterion": "All required fields extracted",  
          "validation\_type": "SCHEMA",  
          "validator": "{\\"required\\": \[\\"title\\", \\"requirements\\", \\"responsibilities\\"\]}"  
        }  
      \],  
      "on\_failure": "RETRY"  
    }  
  },  
    
  "planning": {  
    "static\_plan": {  
      "enabled": true,  
      "steps": \[  
        {  
          "step\_id": "step-act1",  
          "order": 1,  
          "name": "Call NLP Tool",  
          "type": "TOOL\_CALL",  
          "target": {  
            "tool\_id": "nlp\_parser"  
          },  
          "required": true  
        }  
      \]  
    },  
    "dynamic\_planning": {  
      "enabled": false  
    },  
    "loop\_control": {  
      "max\_iterations": 1  
    }  
  },  
    
  "capabilities": {  
    "tools": \[  
      {  
        "tool\_id": "nlp\_parser",  
        "name": "NLP Parser",  
        "description": "Parses text and extracts structured entities",  
        "provider": "internal",  
        "authentication": {  
          "type": "API\_KEY",  
          "credentials\_ref": "nlp\_api\_key"  
        },  
        "function\_schema": {  
          "name": "parse\_job\_description",  
          "description": "Extract structured information from job description text",  
          "parameters": {  
            "type": "object",  
            "properties": {  
              "text": {  
                "type": "string",  
                "description": "Job description text to parse",  
                "required": true  
              },  
              "extract\_fields": {  
                "type": "array",  
                "description": "Fields to extract",  
                "required": false  
              }  
            }  
          }  
        },  
        "rate\_limit": {  
          "calls\_per\_minute": 60,  
          "calls\_per\_hour": 1000  
        },  
        "permissions": "READ",  
        "sandbox\_mode": false  
      }  
    \]  
  },  
    
  "io\_contract": {  
    "input": {  
      "schema": {  
        "type": "object",  
        "properties": {  
          "job\_description": {"type": "string", "required": true}  
        }  
      }  
    },  
    "output": {  
      "schema": {  
        "type": "object",  
        "properties": {  
          "title": {"type": "string"},  
          "requirements": {"type": "array"},  
          "responsibilities": {"type": "array"},  
          "benefits": {"type": "array"}  
        }  
      }  
    }  
  }  
}  
\`\`\`

\---

\#\# \*\*7. API Contract Definitions\*\*

\#\#\# \*\*7.1 Execute Entity API\*\*

\*\*Endpoint:\*\* \`POST /api/v1/entities/{entity\_id}/execute\`

\*\*Request:\*\*  
\`\`\`json  
{  
  "input\_data": {  
    "job\_description": "We are seeking a Senior Software Engineer...",  
    "company\_name": "TechCorp"  
  },  
  "context": {  
    "user\_id": "user-123",  
    "workspace\_id": "ws-456"  
  },  
  "execution\_options": {  
    "async": true,  
    "webhook\_url": "https://app.hirebuddha.com/webhooks/execution-complete"  
  }  
}  
\`\`\`

\*\*Response:\*\*  
\`\`\`json  
{  
  "run\_id": "run-789",  
  "status": "RUNNING",  
  "started\_at": "2025-01-15T10:30:00Z",  
  "estimated\_completion": "2025-01-15T10:35:00Z",  
  "trace\_url": "https://app.hirebuddha.com/traces/run-789"  
}  
\`\`\`

\#\#\# \*\*7.2 Get Execution Status API\*\*

\*\*Endpoint:\*\* \`GET /api/v1/runs/{run\_id}\`

\*\*Response:\*\*  
\`\`\`json  
{  
  "run\_id": "run-789",  
  "entity\_id": "proc-001",  
  "status": "COMPLETED",  
  "started\_at": "2025-01-15T10:30:00Z",  
  "completed\_at": "2025-01-15T10:34:23Z",  
  "output\_data": {  
    "video\_url": "https://cdn.hirebuddha.com/videos/vid-xyz.mp4",  
    "script": "Join TechCorp and work on...",  
    "duration\_seconds": 32,  
    "cost\_usd": 2.45  
  },  
  "metrics": {  
    "total\_cost\_usd": 2.45,  
    "total\_tokens": 12453,  
    "execution\_time\_ms": 263000,  
    "llm\_calls": 8,  
    "tool\_calls": 15  
  },  
  "child\_runs": \[  
    {  
      "run\_id": "run-790",  
      "entity\_id": "agent-001",  
      "status": "COMPLETED"  
    },  
    {  
      "run\_id": "run-791",  
      "entity\_id": "agent-002",  
      "status": "COMPLETED"  
    }  
  \]  
}  
\`\`\`

\#\#\# \*\*7.3 Get Execution Trace API\*\*

\*\*Endpoint:\*\* \`GET /api/v1/runs/{run\_id}/trace\`

\*\*Response:\*\*  
\`\`\`json  
{  
  "run\_id": "run-789",  
  "trace\_tree": {  
    "node": {  
      "run\_id": "run-789",  
      "entity\_name": "video\_ad\_creation\_process",  
      "type": "PROCESS",  
      "status": "COMPLETED",  
      "started\_at": "2025-01-15T10:30:00Z",  
      "completed\_at": "2025-01-15T10:34:23Z"  
    },  
    "children": \[  
      {  
        "node": {  
          "run\_id": "run-790",  
          "entity\_name": "content\_analyst\_agent",  
          "type": "AGENT",  
          "status": "COMPLETED"  
        },  
        "children": \[  
          {  
            "node": {  
              "run\_id": "run-792",  
              "entity\_name": "information\_extraction\_skill",  
              "type": "SKILL",  
              "status": "COMPLETED"  
            },  
            "children": \[  
              {  
                "node": {  
                  "run\_id": "run-793",  
                  "entity\_name": "nlp\_parsing\_action",  
                  "type": "ACTION",  
                  "status": "COMPLETED",  
                  "tool\_calls": \[  
                    {  
                      "tool\_id": "nlp\_parser",  
                      "latency\_ms": 234  
                    }  
                  \],  
                  "llm\_calls": \[  
                    {  
                      "model": "gemini-2.0-flash",  
                      "tokens": 1543  
                    }  
                  \]  
                },  
                "children": \[\]  
              }  
            \]  
          }  
        \]  
      }  
    \]  
  }  
}  
\`\`\`

\---

\#\# \*\*8. Implementation Considerations\*\*

\#\#\# \*\*8.1 Entity Type Differences\*\*

While the structure is unified, behavioral nuances exist:

| Aspect | Action | Skill | Agent | Process |  
|--------|--------|-------|-------|---------|  
| \*\*Typical Depth\*\* | 3-4 | 2-3 | 1-2 | 0 (root) |  
| \*\*Persona Importance\*\* | Low | Medium | High | Very High |  
| \*\*Dynamic Planning\*\* | Rare | Common | Very Common | Essential |  
| \*\*Memory Scope\*\* | SESSION | SESSION | ENTITY | GLOBAL |  
| \*\*Loop Control\*\* | N/A | Critical | Optional | Rare |  
| \*\*Cost Budget\*\* | \<$0.10 | \<$0.50 | \<$2.00 | \<$10.00 |

\#\#\# \*\*8.2 Performance Optimization\*\*

1\. \*\*Lazy Loading:\*\* Load child entity definitions only when invoked  
2\. \*\*Caching:\*\* Cache frequently used static plans and tool schemas  
3\. \*\*Parallel Execution:\*\* Execute PARALLEL children using async/await  
4\. \*\*Context Compression:\*\* Automatically summarize context when approaching token limits  
5\. \*\*Tool Result Caching:\*\* Cache deterministic tool results (e.g., database lookups)

\#\#\# \*\*8.3 Security Considerations\*\*

1\. \*\*Tool Permissions:\*\* Enforce READ/WRITE/EXECUTE permissions at runtime  
2\. \*\*API Key Rotation:\*\* Support automatic credential rotation  
3\. \*\*Output Sanitization:\*\* Filter PII from logs based on governance settings  
4\. \*\*Audit Trails:\*\* Immutable logs for all WRITE operations  
5\. \*\*Rate Limiting:\*\* Per-user and per-workspace execution quotas

\---

\#\# \*\*9. Validation Requirements\*\*

\#\#\# \*\*9.1 Design-Time Validation\*\*

When a user creates/updates an entity via UI:

1\. \*\*Schema Validation:\*\* Ensure all required fields present  
2\. \*\*Circular Dependency Check:\*\* Prevent entity from being its own ancestor  
3\. \*\*Tool Availability:\*\* Verify all referenced tools exist  
4\. \*\*Child Entity Existence:\*\* Validate all child\_id references  
5\. \*\*Budget Coherence:\*\* Ensure child budgets sum to less than parent budget  
6\. \*\*Depth Limit:\*\* Prevent composition\_depth \> max\_recursion\_depth

\#\#\# \*\*9.2 Runtime Validation\*\*

Before executing an entity:

1\. \*\*Input Schema Validation:\*\* Validate input\_data against io\_contract.input.schema  
2\. \*\*Status Check:\*\* Ensure entity status is ACTIVE  
3\. \*\*Cost Pre-Check:\*\* Verify user has sufficient budget  
4\. \*\*Permission Check:\*\* Ensure user can execute this entity  
5\. \*\*Dependency Availability:\*\* Check if required tools/services are online

\---

\#\# \*\*10. Migration & Versioning Strategy\*\*

\#\#\# \*\*10.1 Entity Versioning\*\*

\- \*\*Semantic Versioning:\*\* MAJOR.MINOR.PATCH  
  \- MAJOR: Breaking changes to io\_contract  
  \- MINOR: New features (e.g., adding tools)  
  \- PATCH: Bug fixes, config tweaks

\#\#\# \*\*10.2 Backward Compatibility\*\*

\- Old versions remain executable  
\- Parent entities can reference specific child versions  
\- UI shows "Upgrade Available" warnings for outdated entities

\---

\#\# \*\*11. Monitoring & Alerting\*\*

\#\#\# \*\*11.1 Key Metrics\*\*

1\. \*\*Execution Success Rate:\*\* % of runs that complete successfully  
2\. \*\*Average Cost per Execution:\*\* Track cost trends  
3\. \*\*P95 Latency:\*\* 95th percentile execution time  
4\. \*\*Token Efficiency:\*\* Average tokens per successful execution  
5\. \*\*HITL Approval Rate:\*\* % of checkpoints that get approved

\#\#\# \*\*11.2 Alert Triggers\*\*

1\. \*\*Cost Spike:\*\* Execution cost \>2x historical average  
2\. \*\*Failure Spike:\*\* Success rate drops below 80%  
3\. \*\*Latency Spike:\*\* P95 \>2x baseline  
4\. \*\*Stuck Execution:\*\* Run exceeds timeout by 50%  
5\. \*\*Budget Exhaustion:\*\* User approaches 90% of monthly quota

\---

\#\# \*\*12. Conclusion\*\*

This specification provides a comprehensive, production-ready framework for the HireBuddha Hierarchical Autonomous AI Agentic Platform. The unified data structure enables:

1\. \*\*Flexibility:\*\* Users have granular control over every aspect of behavior  
2\. \*\*Scalability:\*\* Recursive architecture supports arbitrary complexity  
3\. \*\*Observability:\*\* Exhaustive logging and tracing for debugging  
4\. \*\*Safety:\*\* Multiple layers of governance and human oversight  
5\. \*\*Maintainability:\*\* Single execution engine for all entity types

The design balances \*\*static determinism\*\* (user-defined plans) with \*\*dynamic adaptation\*\* (LLM-generated plans), creating a system that is both reliable and intelligent.

\---

\#\# \*\*Appendices\*\*

\#\#\# \*\*A. Glossary\*\*

\- \*\*Entity:\*\* Generic term for Action, Skill, Agent, or Process  
\- \*\*Static Plan:\*\* User-defined execution blueprint  
\- \*\*Dynamic Plan:\*\* LLM-generated execution plan at runtime  
\- \*\*Reconciliation:\*\* Algorithm for merging static and dynamic plans  
\- \*\*HITL:\*\* Human-in-the-Loop checkpoint  
\- \*\*ReAct:\*\* Reasoning \+ Acting LLM pattern  
\- \*\*Bounded Autonomy:\*\* AI freedom within defined constraints

\#\#\# \*\*B. Reference Implementations\*\*

See \`/examples\` directory for:  
\- Complete Process definition (Video Ad Creation)  
\- Agent implementation (Content Analyst)  
\- Skill with loops (Resume Fact-Checking)  
\- Atomic Action (Email Sender)

\---

\*\*Document End\*\*

