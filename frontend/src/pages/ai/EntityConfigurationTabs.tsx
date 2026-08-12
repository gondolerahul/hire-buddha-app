import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { JellyButton } from '@/components/ui';
import { Info, Brain, Settings, Route, Wrench, Shield, Plus, Trash2, Volume2, VolumeX, ChevronDown, ChevronRight, AlertTriangle, Sliders, Database, Upload, User, GitBranch, Search, CheckSquare, Square, File, X, FolderOpen, Lock, FileText, Image, Music, Video, FileSpreadsheet } from 'lucide-react';
import { EntityType, EntityStatus, HierarchicalEntity, HITLCheckpoint, HITLTriggerType, ToolUsage } from '@/types';
import { EntityFlow } from './EntityFlow';
import { Node, Edge } from 'reactflow';
import { apiClient } from '@/services/api.client';
import './EntityConfigurationTabs.css';

const GEMINI_VOICES = [
    'Aoede', 'Puck', 'Charon', 'Kore', 'Fenrir', 'Orbit', 'Zephyr', 'Leda',
    'Orus', 'Rigel', 'Schedar', 'Pulcherrima', 'Achird', 'Zubenelgenubi',
    'Vindemiatrix', 'Sadachbia', 'Sadaltager', 'Sulafat',
];

// Default prompts — mirrors backend schemas.py defaults
const DEFAULT_PLANNING_SYSTEM_PROMPT = `You are an AI planning agent. Given a user goal and available capabilities, generate a structured execution plan.

Output a JSON array of steps in this format:
[
  {
    "step_id": "step_1",
    "order": 1,
    "name": "Step Name",
    "description": "What this step accomplishes",
    "type": "TOOL_CALL",
    "target": {
      "tool_id": "tool_name_if_applicable",
      "prompt_template": "Use {{step_1}} to reference the output of step_1",
      "input_dependencies": ["step_1"]
    },
    "required": true
  }
]

Rules:
1. Use type "TOOL_CALL" when a tool should be invoked directly. Use type "ACTION" when the LLM needs to reason/transform data.
2. Break complex tasks into atomic, sequential steps.
3. Use available tools when they can help accomplish the goal.
4. Each step should have clear success criteria implied in its description.
5. For TOOL_CALL steps: put the tool name in target.tool_id and use {{step_N}} in prompt_template.
6. For ACTION steps: describe clearly in the description what the LLM should do with the data.
7. List input_dependencies to declare which prior steps this step depends on.
8. Keep the number of steps minimal — prefer 3-4 focused steps over 5+ granular ones.`;

const DEFAULT_REVIEW_SYSTEM_PROMPT = `You are a quality assurance critic. Review the output of an AI step execution.

Evaluate if the output meets the requirements described in the step description.

Respond with a JSON object:
{
  "passed": true/false,
  "reason": "Explanation of why it passed or failed",
  "suggestion": "If failed, specific suggestion for improvement"
}

Be strict but fair. Minor formatting issues are acceptable if the core task is accomplished.`;

const HITL_TRIGGER_TYPES: { value: HITLTriggerType; label: string; description: string }[] = [
    { value: 'BEFORE_STEP', label: 'Before Step', description: 'Pause before a specific step executes' },
    { value: 'AFTER_STEP', label: 'After Step', description: 'Pause after a specific step completes' },
    { value: 'COST_THRESHOLD', label: 'Cost Threshold', description: 'Pause when execution cost exceeds a threshold' },
    { value: 'TOOL_CALL', label: 'Tool Call', description: 'Pause before a specific tool is called' },
    { value: 'CUSTOM', label: 'Custom Expression', description: 'Pause when a custom expression evaluates to true' },
];

interface EntityConfigurationTabsProps {
    entity?: HierarchicalEntity;
    onSave: (entityData: any) => void;
    onCancel: () => void;
    userRole?: string;
    userCompanyId?: string;
    onCompanyChange?: (companyId: string | null) => void;
}

interface CompanyOption {
    id: string;
    name: string;
    type: string;
}

export const EntityConfigurationTabs: React.FC<EntityConfigurationTabsProps> = ({ entity, onSave, onCancel, userRole, userCompanyId, onCompanyChange }) => {
    const [activeTab, setActiveTab] = useState('basics');

    // ═══════════════════════════════════════════════════════════════════════════
    // TAB 1: BASICS — "What is this entity?"
    // ═══════════════════════════════════════════════════════════════════════════
    const [name, setName] = useState(entity?.name || '');
    // display_name is auto-generated from name + role (set in useEffect below)
    const [type, setType] = useState<EntityType>(entity?.type || EntityType.AGENT);
    const [description, setDescription] = useState(entity?.description || '');
    const [version, setVersion] = useState(entity?.version || '1.0.0');
    const [status, setStatus] = useState<EntityStatus>(entity?.status || EntityStatus.DRAFT);
    const [tags, setTags] = useState<string[]>(entity?.tags || []);
    const [tagInput, setTagInput] = useState('');
    const [inputSchema, setInputSchema] = useState(JSON.stringify(entity?.io_contract?.input_schema || { type: 'object', properties: {} }, null, 2));
    const [outputSchema, setOutputSchema] = useState(JSON.stringify(entity?.io_contract?.output_schema || { type: 'object', properties: {} }, null, 2));

    // Company assignment for admin/partner users
    const isAdminOrPartner = userRole === 'app_admin' || userRole === 'partner_admin' || userRole === 'partner_user';
    const [companies, setCompanies] = useState<CompanyOption[]>([]);
    const [selectedCompanyId, setSelectedCompanyId] = useState<string>(userCompanyId || '');

    useEffect(() => {
        if (isAdminOrPartner) {
            // Fetch companies available to this user
            const endpoint = '/companies';
            apiClient.get(endpoint).then(res => {
                const data = res.data;
                let companyList: CompanyOption[] = [];
                if (Array.isArray(data)) {
                    companyList = data.map((c: any) => ({
                        id: c.id || c.company_id,
                        name: c.name || c.company_name || 'Unknown',
                        type: c.type || 'TENANT',
                    }));
                } else if (data.companies) {
                    companyList = data.companies.map((c: any) => ({
                        id: c.id, name: c.name, type: c.type || 'TENANT',
                    }));
                } else if (data.tenants) {
                    companyList = data.tenants.map((c: any) => ({
                        id: c.id || c.company_id,
                        name: c.name || c.company_name || 'Unknown',
                        type: 'TENANT',
                    }));
                }
                setCompanies(companyList);
            }).catch(() => {});
        }
    }, [userRole]);

    const handleCompanyChange = (companyId: string) => {
        setSelectedCompanyId(companyId);
        if (onCompanyChange) {
            onCompanyChange(companyId !== userCompanyId ? companyId : null);
        }
    };

    // Hierarchy — hydrate from entity.hierarchy.children
    const buildInitialGraph = () => {
        const children = entity?.hierarchy?.children || [];
        if (children.length === 0) return { nodes: [] as Node[], edges: [] as Edge[] };

        const nodes: Node[] = children.map((child: any, idx: number) => ({
            id: child.child_id || `child-${idx}`,
            type: 'entityNode',
            position: { x: 100 + (idx % 3) * 300, y: 100 + Math.floor(idx / 3) * 160 },
            data: {
                label: child.child_name || child.child_id || `Child ${idx + 1}`,
                stepType: child.child_type || 'AGENT',
                type: child.child_type || 'AGENT',
                entityRef: child.child_id ? { id: child.child_id, name: child.child_name || child.child_id, type: child.child_type || 'AGENT' } : undefined,
                required: true,
            },
        }));

        const edges: Edge[] = [];
        for (let i = 0; i < nodes.length - 1; i++) {
            const rel = children[i + 1]?.relationship || 'SEQUENTIAL';
            edges.push({
                id: `e-${nodes[i].id}-${nodes[i + 1].id}`,
                source: nodes[i].id,
                target: nodes[i + 1].id,
                type: 'relationship',
                label: rel,
                animated: rel === 'PARALLEL',
            });
        }
        return { nodes, edges };
    };
    const initialGraph = buildInitialGraph();
    const [hierarchyNodes, setHierarchyNodes] = useState<Node[]>(initialGraph.nodes);
    const [hierarchyEdges, setHierarchyEdges] = useState<Edge[]>(initialGraph.edges);

    // ═══════════════════════════════════════════════════════════════════════════
    // TAB 2: BRAIN — "How does this entity think?"
    // ═══════════════════════════════════════════════════════════════════════════
    // identity.name removed — use top-level entity.name instead
    const [personaRole, setPersonaRole] = useState(entity?.identity?.role || '');
    const [personaBio, setPersonaBio] = useState(entity?.identity?.bio || '');
    const [profileImageUrl, setProfileImageUrl] = useState(entity?.identity?.profile_image_url || '');
    // Personality Matrix
    const [tone, setTone] = useState(entity?.identity?.personality?.tone || 'professional');
    const [verbosity, setVerbosity] = useState(entity?.identity?.personality?.verbosity || 'concise');
    const [empathyLevel, setEmpathyLevel] = useState<number>(entity?.identity?.personality?.empathy_level ?? 0.7);
    const [humorLevel, setHumorLevel] = useState<number>(entity?.identity?.personality?.humor_level ?? 0.2);
    const [formality, setFormality] = useState(entity?.identity?.personality?.formality || 'semi-formal');
    const [decisionConfidence, setDecisionConfidence] = useState<number>(entity?.identity?.personality?.decision_confidence ?? 0.8);
    // Voice Agent toggle + config
    const [isVoiceAgent, setIsVoiceAgent] = useState<boolean>(
        !!(entity?.identity?.voice?.voice_name) || false
    );
    const [voiceName, setVoiceName] = useState(entity?.identity?.voice?.voice_name || 'Aoede');
    const [languageCode, setLanguageCode] = useState(entity?.identity?.voice?.language_code || 'en-US');
    const [speakingRate, setSpeakingRate] = useState<number>(entity?.identity?.voice?.speaking_rate ?? 1.0);
    const [voicePitch, setVoicePitch] = useState<number>(entity?.identity?.voice?.pitch ?? 0.0);
    // Dynamic injection hooks (voice)
    const [greetingTemplate, setGreetingTemplate] = useState(entity?.identity?.greeting_template || '');
    const [escalationMessage, setEscalationMessage] = useState(entity?.identity?.escalation_message || '');
    const [closingMessage, setClosingMessage] = useState(entity?.identity?.closing_message || '');
    // Prompt engineering
    const [systemPrompt, setSystemPrompt] = useState(entity?.identity?.system_prompt || '');
    const [goal, setGoal] = useState(entity?.goal || '');
    const [fewShotExamples, setFewShotExamples] = useState<{ [key: string]: string }[]>(entity?.identity?.few_shot_examples || []);
    const [behavioralConstraints, setBehavioralConstraints] = useState<string[]>(entity?.identity?.behavioral_constraints || []);
    const [constraintInput, setConstraintInput] = useState('');

    // ═══════════════════════════════════════════════════════════════════════════
    // TAB 3: PLANNING — "What's the strategy?"
    // ═══════════════════════════════════════════════════════════════════════════
    const [taskType, setTaskType] = useState(entity?.logic_gate?.reasoning_config?.task_type || 'text_generation');
    const [temperature, setTemperature] = useState(entity?.logic_gate?.reasoning_config?.temperature || 0.7);
    const [topP, setTopP] = useState(entity?.logic_gate?.reasoning_config?.top_p || 1.0);
    const [maxTokens, setMaxTokens] = useState<number | undefined>(entity?.logic_gate?.reasoning_config?.max_tokens);
    const [reasoningMode, setReasoningMode] = useState<string>(entity?.logic_gate?.reasoning_config?.reasoning_mode || 'REACT');
    const [modelName, setModelName] = useState(entity?.logic_gate?.reasoning_config?.model_name || '');
    // Phase 5: Autonomous mode
    const [executionMode, setExecutionMode] = useState<string>(entity?.logic_gate?.reasoning_config?.execution_mode || 'STANDARD');
    const [goalValidationInterval, setGoalValidationInterval] = useState(entity?.logic_gate?.reasoning_config?.goal_validation_interval || 2);
    const [confidenceThreshold, setConfidenceThreshold] = useState(entity?.logic_gate?.reasoning_config?.confidence_threshold || 0.85);
    const [maxReplanningAttempts, setMaxReplanningAttempts] = useState(entity?.logic_gate?.reasoning_config?.max_replanning_attempts || 3);
    const [selfReflectionEnabled, setSelfReflectionEnabled] = useState(entity?.logic_gate?.reasoning_config?.self_reflection_enabled || false);
    // Planning
    const [staticPlanEnabled, setStaticPlanEnabled] = useState(entity?.planning?.static_plan?.enabled ?? true);
    const [fallbackBehavior, setFallbackBehavior] = useState<string>(entity?.planning?.static_plan?.fallback_behavior || 'ADAPTIVE');
    const [dynamicPlanningEnabled, setDynamicPlanningEnabled] = useState(entity?.planning?.dynamic_planning?.enabled ?? false);
    const [planningPrompt, setPlanningPrompt] = useState(entity?.planning?.dynamic_planning?.planning_prompt || '');
    const [planningSystemPrompt, setPlanningSystemPrompt] = useState(entity?.planning?.dynamic_planning?.planning_system_prompt || DEFAULT_PLANNING_SYSTEM_PROMPT);
    const [reconciliationStrategy, setReconciliationStrategy] = useState<string>(entity?.planning?.dynamic_planning?.reconciliation_strategy || 'HYBRID');
    const [allowedDeviations, setAllowedDeviations] = useState(entity?.planning?.dynamic_planning?.allowed_deviations || {
        can_add_steps: true, can_skip_optional_steps: true, can_reorder_steps: false, can_change_tools: false
    });
    const [maxIterations, setMaxIterations] = useState(entity?.planning?.loop_control?.max_iterations || 10);
    const [iterationContextMode, setIterationContextMode] = useState<string>(entity?.planning?.loop_control?.iteration_context_mode || 'FULL_HISTORY');
    // Review
    const [reviewEnabled, setReviewEnabled] = useState(entity?.logic_gate?.review_mechanism?.enabled || false);
    const [reviewPrompt, setReviewPrompt] = useState(entity?.logic_gate?.review_mechanism?.review_prompt || '');
    const [reviewSystemPrompt, setReviewSystemPrompt] = useState(entity?.logic_gate?.review_mechanism?.review_system_prompt || DEFAULT_REVIEW_SYSTEM_PROMPT);
    const [reviewOnFailure, setReviewOnFailure] = useState<string>(entity?.logic_gate?.review_mechanism?.on_failure || 'RETRY');
    const [successCriteria] = useState<any[]>(entity?.logic_gate?.review_mechanism?.success_criteria || []);
    // Retry
    const [maxRetries, setMaxRetries] = useState(entity?.logic_gate?.retry_policy?.max_retries || 3);
    const [backoffStrategy, setBackoffStrategy] = useState<string>(entity?.logic_gate?.retry_policy?.backoff_strategy || 'EXPONENTIAL');
    const [backoffMultiplier, setBackoffMultiplier] = useState(entity?.logic_gate?.retry_policy?.backoff_multiplier || 2.0);

    // ═══════════════════════════════════════════════════════════════════════════
    // TAB 4: CAPABILITIES — "What tools and context does it have?"
    // ═══════════════════════════════════════════════════════════════════════════
    interface ToolAssignment { tool_id: string; usage: ToolUsage; description?: string; }
    const [toolAssignments, setToolAssignments] = useState<ToolAssignment[]>(
        (entity?.capabilities?.tools || []).map((t: any) => ({
            tool_id: t.tool_id || t,
            usage: (t.usage as ToolUsage) || 'AUTONOMOUS',
        }))
    );
    // Available tools from the registry
    const [availableTools, setAvailableTools] = useState<{ name: string; display_name?: string; description: string; category?: string; is_enabled?: boolean }[]>([]);
    const [toolSearchQuery, setToolSearchQuery] = useState('');
    useEffect(() => {
        apiClient.get<any[]>('/ai/tools').then(res => setAvailableTools(res.data.filter((t: any) => t.is_enabled !== false))).catch(() => {});
    }, []);
    const toggleToolAssignment = (toolName: string) => {
        if (toolAssignments.find(t => t.tool_id === toolName)) {
            setToolAssignments(toolAssignments.filter(t => t.tool_id !== toolName));
        } else {
            setToolAssignments([...toolAssignments, { tool_id: toolName, usage: 'AUTONOMOUS' }]);
        }
    };
    const setToolUsage = (toolName: string, usage: ToolUsage) => {
        setToolAssignments(toolAssignments.map(t => t.tool_id === toolName ? { ...t, usage } : t));
    };
    const filteredAvailableTools = availableTools.filter(t =>
        t.name.toLowerCase().includes(toolSearchQuery.toLowerCase()) ||
        t.description.toLowerCase().includes(toolSearchQuery.toLowerCase()) ||
        (t.display_name || '').toLowerCase().includes(toolSearchQuery.toLowerCase())
    );
    const [memoryEnabled, setMemoryEnabled] = useState(entity?.capabilities?.memory?.enabled || false);
    const [memoryMode, setMemoryMode] = useState<string>(entity?.capabilities?.memory?.mode || 'STANDARD');
    const [episodicMemoryCount, setEpisodicMemoryCount] = useState(entity?.capabilities?.memory?.episodic_memory_count || 10);
    const [semanticSearchEnabled, setSemanticSearchEnabled] = useState(entity?.capabilities?.memory?.semantic_search_enabled ?? true);
    const [semanticTopK, setSemanticTopK] = useState(entity?.capabilities?.memory?.semantic_top_k || 5);
    const [cortexMaxChildren, setCortexMaxChildren] = useState(entity?.capabilities?.memory?.cortex_config?.max_children || 12);
    const [cortexPageSize, setCortexPageSize] = useState(entity?.capabilities?.memory?.cortex_config?.page_size_tokens || 8000);
    const [cortexContextBudget, setCortexContextBudget] = useState(entity?.capabilities?.memory?.cortex_config?.context_budget_pct || 40);
    const [cortexAutoCheckpoint, setCortexAutoCheckpoint] = useState(entity?.capabilities?.memory?.cortex_config?.auto_checkpoint ?? true);
    const [cortexResumeEnabled, setCortexResumeEnabled] = useState(entity?.capabilities?.memory?.cortex_config?.resume_enabled ?? true);
    // Context Engineering
    const [injectEpisodicMemory, setInjectEpisodicMemory] = useState(entity?.capabilities?.context_engineering?.inject_episodic_memory ?? true);
    const [injectSemanticContext, setInjectSemanticContext] = useState(entity?.capabilities?.context_engineering?.inject_semantic_context ?? true);
    const [injectCortexViewport, setInjectCortexViewport] = useState(entity?.capabilities?.context_engineering?.inject_cortex_viewport ?? true);
    const [noTruncation, setNoTruncation] = useState(entity?.capabilities?.context_engineering?.no_truncation ?? true);
    const [contextSources, setContextSources] = useState<any[]>(entity?.capabilities?.context_engineering?.context_sources || []);
    // Context Policy (moved from Logic Gate)
    const [contextPolicyType, setContextPolicyType] = useState<'FULL' | 'LAST_N' | 'SLIDING_WINDOW' | 'EXPLICIT'>(entity?.logic_gate?.context_policy?.type || 'FULL');
    const [contextPolicyN, setContextPolicyN] = useState<number | undefined>(entity?.logic_gate?.context_policy?.n);
    const [contextPolicyMaxChars, setContextPolicyMaxChars] = useState<number | undefined>(entity?.logic_gate?.context_policy?.max_chars);
    const [contextPolicySummarizeThreshold, setContextPolicySummarizeThreshold] = useState<number | undefined>(entity?.logic_gate?.context_policy?.summarize_threshold);
    const [preserveKeys, setPreserveKeys] = useState<string[]>(entity?.logic_gate?.context_policy?.preserve_keys || []);
    const [preserveKeyInput, setPreserveKeyInput] = useState('');

    // ═══════════════════════════════════════════════════════════════════════════
    // TAB 5: SAFEGUARDS — "What are the limits?"
    // ═══════════════════════════════════════════════════════════════════════════
    const [maxCostUsd, setMaxCostUsd] = useState<number | undefined>(entity?.governance?.max_cost_usd);
    const [timeoutMs, setTimeoutMs] = useState(entity?.governance?.timeout_ms || 300000);
    const [maxRecursionDepth, setMaxRecursionDepth] = useState(entity?.governance?.execution_limits?.max_recursion_depth || 5);
    const [maxToolCalls, setMaxToolCalls] = useState<number | undefined>(entity?.governance?.execution_limits?.max_tool_calls);
    const [checkpointEveryNSteps, setCheckpointEveryNSteps] = useState(entity?.governance?.checkpoint_every_n_steps || 3);
    const [hitlCheckpoints, setHitlCheckpoints] = useState<HITLCheckpoint[]>(entity?.governance?.hitl_checkpoints || []);
    // Observability (moved from its own tab)
    const [logLevel, setLogLevel] = useState(entity?.observability?.log_level || 'INFO');
    const [logThoughts, setLogThoughts] = useState(entity?.observability?.log_thoughts ?? true);
    const [trackCost, setTrackCost] = useState(entity?.observability?.track_cost ?? true);

    // Collapsible sections
    const [showPlanningPrompt, setShowPlanningPrompt] = useState(false);
    const [showReviewPrompt, setShowReviewPrompt] = useState(false);

    // ── Initialize hierarchy from entity ──────────────────────────────────────
    useEffect(() => {
        if (entity?.planning?.static_plan?.steps && entity.planning.static_plan.steps.length > 0) {
            const steps = entity.planning.static_plan.steps;
            const nodes: Node[] = steps.map((step: any, idx: number) => ({
                id: step.step_id || crypto.randomUUID(),
                type: step.type === 'CHILD_ENTITY_INVOCATION' ? 'entityNode' : step.type === 'TOOL_CALL' ? 'toolNode' : 'defaultNode',
                position: { x: 400, y: 100 + idx * 150 },
                data: {
                    label: step.name, description: step.description, required: step.required,
                    entityRef: step.target?.entity_id ? { id: step.target.entity_id } : undefined,
                    toolRef: step.target?.tool_id ? { tool_id: step.target.tool_id } : undefined,
                    stepType: step.type,
                }
            }));
            setHierarchyNodes(nodes);
            const edges: Edge[] = [];
            for (let i = 0; i < nodes.length - 1; i++) {
                edges.push({ id: `e${nodes[i].id}-${nodes[i + 1].id}`, source: nodes[i].id, target: nodes[i + 1].id, animated: true, label: 'SEQUENTIAL' });
            }
            setHierarchyEdges(edges);
        }
    }, [entity?.id]);

    // ── Handlers ──────────────────────────────────────────────────────────────
    const addTag = () => { if (tagInput.trim() && !tags.includes(tagInput.trim())) { setTags([...tags, tagInput.trim()]); setTagInput(''); } };
    const removeTag = (tag: string) => setTags(tags.filter(t => t !== tag));
    const addConstraint = () => { if (constraintInput.trim()) { setBehavioralConstraints([...behavioralConstraints, constraintInput.trim()]); setConstraintInput(''); } };
    const removeConstraint = (idx: number) => setBehavioralConstraints(behavioralConstraints.filter((_, i) => i !== idx));
    const addFewShot = () => setFewShotExamples([...fewShotExamples, { input: '', output: '' }]);
    const updateFewShot = (idx: number, key: string, value: string) => { const u = [...fewShotExamples]; u[idx] = { ...u[idx], [key]: value }; setFewShotExamples(u); };
    const removeFewShot = (idx: number) => setFewShotExamples(fewShotExamples.filter((_, i) => i !== idx));
    const addPreserveKey = () => { if (preserveKeyInput.trim() && !preserveKeys.includes(preserveKeyInput.trim())) { setPreserveKeys([...preserveKeys, preserveKeyInput.trim()]); setPreserveKeyInput(''); } };
    const removePreserveKey = (key: string) => setPreserveKeys(preserveKeys.filter(k => k !== key));

    // Avatar upload handler
    const avatarInputRef = useRef<HTMLInputElement>(null);
    const [avatarUploading, setAvatarUploading] = useState(false);
    const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setAvatarUploading(true);
        try {
            const formData = new FormData();
            formData.append('file', file);
            const res = await apiClient.post<{ url: string }>('/ai/avatar/upload', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            setProfileImageUrl(res.data.url);
        } catch (err) {
            console.error('Avatar upload failed:', err);
        } finally {
            setAvatarUploading(false);
            if (avatarInputRef.current) avatarInputRef.current.value = '';
        }
    };

    // ── Context Source handlers ──────────────────────────────────────────
    const removeContextSource = (idx: number) => setContextSources(contextSources.filter((_, i) => i !== idx));

    // File upload state
    const [uploadingFile, setUploadingFile] = useState(false);
    const [dragOver, setDragOver] = useState(false);
    const contextFileInputRef = useRef<HTMLInputElement>(null);

    const handleContextFileUpload = async (files: FileList | null) => {
        if (!files || files.length === 0) return;
        setUploadingFile(true);
        try {
            for (const file of Array.from(files)) {
                const formData = new FormData();
                formData.append('file', file);
                const res = await apiClient.post<{
                    artifact_id: string; document_id: string | null;
                    file_name: string; file_size: number; mime_type: string; file_category: string;
                }>('/ai/context-sources/upload', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });
                const d = res.data;
                setContextSources(prev => [...prev, {
                    source_type: 'DOCUMENT' as const,
                    reference_id: d.artifact_id,
                    description: d.file_name,
                    file_name: d.file_name,
                    file_type: d.mime_type,
                    file_size: d.file_size,
                }]);
            }
        } catch (err) {
            console.error('Context source upload failed:', err);
        } finally {
            setUploadingFile(false);
            if (contextFileInputRef.current) contextFileInputRef.current.value = '';
        }
    };

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setDragOver(false);
        handleContextFileUpload(e.dataTransfer.files);
    }, []);

    // Knowledge Base (Artifacts) browser
    const [showKBModal, setShowKBModal] = useState(false);
    const [kbArtifacts, setKbArtifacts] = useState<any[]>([]);
    const [kbLoading, setKbLoading] = useState(false);
    const [kbSearch, setKbSearch] = useState('');

    const openKBModal = async () => {
        setShowKBModal(true);
        setKbLoading(true);
        try {
            // Load both artifacts and documents in parallel for unified KB view
            const [artRes, docRes] = await Promise.allSettled([
                apiClient.get<{ artifacts: any[]; count: number }>('/artifacts?limit=200'),
                apiClient.get<any[]>('/ai/documents'),
            ]);

            const items: any[] = [];
            const seenIds = new Set<string>();

            // Add artifacts
            if (artRes.status === 'fulfilled') {
                for (const a of (artRes.value.data?.artifacts || artRes.value.data || [])) {
                    if (!seenIds.has(a.id)) {
                        seenIds.add(a.id);
                        items.push(a);
                    }
                }
            }

            // Add documents (merge, avoid duplicates)
            if (docRes.status === 'fulfilled') {
                for (const d of (docRes.value.data || [])) {
                    if (!seenIds.has(d.id)) {
                        seenIds.add(d.id);
                        items.push({
                            id: d.id,
                            file_name: d.filename,
                            file_category: 'documents',
                            file_size: d.file_size ? parseInt(d.file_size) : null,
                            mime_type: d.file_type,
                            created_at: d.created_at,
                            _source: 'documents',
                        });
                    }
                }
            }

            setKbArtifacts(items);
        } catch (err) {
            console.error('Failed to load knowledge base:', err);
            setKbArtifacts([]);
        } finally { setKbLoading(false); }
    };

    const selectKBItem = (artifact: any) => {
        // Check not already added
        if (contextSources.find(s => s.reference_id === artifact.id)) return;
        setContextSources(prev => [...prev, {
            source_type: 'KNOWLEDGE_BASE' as const,
            reference_id: artifact.id,
            description: artifact.file_name || artifact.filename || 'Document',
            file_name: artifact.file_name || artifact.filename,
            file_type: artifact.mime_type || artifact.file_type,
            file_size: artifact.file_size ? Number(artifact.file_size) : undefined,
        }]);
        setShowKBModal(false);
    };

    const filteredKBItems = kbArtifacts.filter(a =>
        (a.file_name || a.filename || '').toLowerCase().includes(kbSearch.toLowerCase()) ||
        (a.file_category || '').toLowerCase().includes(kbSearch.toLowerCase())
    );

    // CORTEX Tree picker
    const [showTreeModal, setShowTreeModal] = useState(false);
    const [cortexTrees, setCortexTrees] = useState<any[]>([]);
    const [treeLoading, setTreeLoading] = useState(false);
    const [treeSearch, setTreeSearch] = useState('');

    const openTreeModal = async () => {
        setShowTreeModal(true);
        setTreeLoading(true);
        try {
            const res = await apiClient.get<any[]>('/cortex/trees');
            setCortexTrees(Array.isArray(res.data) ? res.data : []);
        } catch (err) {
            console.error('Failed to load CORTEX trees:', err);
            setCortexTrees([]);
        } finally { setTreeLoading(false); }
    };

    const selectTree = (tree: any) => {
        if (contextSources.find(s => s.reference_id === tree.id)) return;
        setContextSources(prev => [...prev, {
            source_type: 'CORTEX_TREE' as const,
            reference_id: tree.id,
            description: tree.task_description || `Tree ${tree.id.slice(0,8)}`,
            tree_status: tree.status,
            tree_node_count: tree.total_nodes,
        }]);
        setShowTreeModal(false);
    };

    const filteredTrees = cortexTrees.filter(t =>
        (t.task_description || '').toLowerCase().includes(treeSearch.toLowerCase()) ||
        (t.id || '').toLowerCase().includes(treeSearch.toLowerCase())
    );

    // File type icon helper
    const getFileIcon = (mimeOrExt: string) => {
        if (!mimeOrExt) return <File size={16} />;
        const m = mimeOrExt.toLowerCase();
        if (m.includes('image')) return <Image size={16} />;
        if (m.includes('video')) return <Video size={16} />;
        if (m.includes('audio')) return <Music size={16} />;
        if (m.includes('spreadsheet') || m.includes('excel') || m.includes('csv') || m.includes('xlsx')) return <FileSpreadsheet size={16} />;
        if (m.includes('pdf') || m.includes('doc') || m.includes('text') || m.includes('txt')) return <FileText size={16} />;
        return <File size={16} />;
    };

    const formatFileSize = (bytes?: number) => {
        if (!bytes) return '';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    // HITL Checkpoint handlers
    const addCheckpoint = () => {
        setHitlCheckpoints([...hitlCheckpoints, {
            trigger_type: 'BEFORE_STEP',
            timeout_ms: 300000,
            notification_channels: ['dashboard'],
            auto_approve_on_timeout: false,
        }]);
    };
    const updateCheckpoint = (idx: number, field: string, value: any) => {
        const updated = [...hitlCheckpoints];
        updated[idx] = { ...updated[idx], [field]: value };
        setHitlCheckpoints(updated);
    };
    const removeCheckpoint = (idx: number) => setHitlCheckpoints(hitlCheckpoints.filter((_, i) => i !== idx));

    // ── Convert graph → steps/children ───────────────────────────────────────
    const convertNodesToSteps = (nodes: Node[], edges: Edge[]) =>
        nodes.filter(n => n.id !== 'root').map((node, idx) => ({
            step_id: node.id, order: idx + 1, name: node.data.label,
            description: node.data.description || '',
            type: node.data.entityRef ? 'CHILD_ENTITY_INVOCATION' : node.data.toolRef ? 'TOOL_CALL' : (node.data.stepType || 'ACTION'),
            target: {
                entity_id: node.data.entityRef?.id, tool_id: node.data.toolRef?.tool_id,
                prompt_template: !node.data.entityRef && !node.data.toolRef ? node.data.description : undefined,
                input_dependencies: edges.filter(e => e.target === node.id).map(e => e.source),
            },
            required: node.data.required ?? true,
        }));

    const extractChildrenFromGraph = (nodes: Node[], edges: Edge[]) =>
        nodes.filter(n => n.data.entityRef).map(n => ({
            child_id: n.data.entityRef.id, child_type: n.data.entityRef.type,
            relationship: edges.find(e => e.target === n.id)?.label || 'SEQUENTIAL',
        }));

    // ── Save Handler ─────────────────────────────────────────────────────────
    const handleSave = () => {
        // Auto-generate display_name as "Name - Role"
        const autoDisplayName = personaRole ? `${name} - ${personaRole}` : name;

        const entityData = {
            name,
            display_name: autoDisplayName,
            type,
            description,
            goal,
            version,
            status,
            tags,

            identity: {
                // identity.name removed — name is the top-level entity.name
                role: personaRole,
                bio: personaBio || description || undefined,  // Auto-sync fallback
                profile_image_url: profileImageUrl || undefined,
                personality: { tone, verbosity, empathy_level: empathyLevel, humor_level: humorLevel, formality, decision_confidence: decisionConfidence },
                ...(isVoiceAgent ? {
                    voice: { voice_name: voiceName, language_code: languageCode, speaking_rate: speakingRate, pitch: voicePitch },
                    greeting_template: greetingTemplate || undefined,
                    escalation_message: escalationMessage || undefined,
                    closing_message: closingMessage || undefined,
                } : {}),
                system_prompt: systemPrompt,
                behavioral_constraints: behavioralConstraints,
                few_shot_examples: fewShotExamples,
            },

            logic_gate: {
                reasoning_config: {
                    task_type: taskType, temperature, top_p: topP, max_tokens: maxTokens,
                    reasoning_mode: reasoningMode, model_name: modelName || undefined,
                    execution_mode: executionMode,
                    goal_validation_interval: goalValidationInterval,
                    confidence_threshold: confidenceThreshold,
                    max_replanning_attempts: maxReplanningAttempts,
                    self_reflection_enabled: selfReflectionEnabled,
                },
                retry_policy: { max_retries: maxRetries, backoff_strategy: backoffStrategy, backoff_multiplier: backoffMultiplier },
                review_mechanism: {
                    enabled: reviewEnabled,
                    review_prompt: reviewPrompt,
                    review_system_prompt: reviewSystemPrompt,
                    on_failure: reviewOnFailure,
                    success_criteria: successCriteria,
                },
                context_policy: {
                    type: contextPolicyType, n: contextPolicyN,
                    max_chars: contextPolicyMaxChars, summarize_threshold: contextPolicySummarizeThreshold,
                    preserve_keys: preserveKeys,
                },
            },

            planning: {
                static_plan: { enabled: staticPlanEnabled, steps: convertNodesToSteps(hierarchyNodes, hierarchyEdges), fallback_behavior: fallbackBehavior },
                dynamic_planning: {
                    enabled: dynamicPlanningEnabled,
                    planning_prompt: planningPrompt,
                    planning_system_prompt: planningSystemPrompt,
                    reconciliation_strategy: reconciliationStrategy,
                    allowed_deviations: allowedDeviations,
                },
                loop_control: { max_iterations: maxIterations, iteration_context_mode: iterationContextMode },
            },

            capabilities: {
                tools: toolAssignments.map(t => ({ tool_id: t.tool_id, usage: t.usage })),
                memory: {
                    enabled: memoryEnabled, mode: memoryMode,
                    episodic_memory_count: episodicMemoryCount,
                    semantic_search_enabled: semanticSearchEnabled, semantic_top_k: semanticTopK,
                    ...(memoryMode === 'CORTEX' ? {
                        cortex_config: {
                            max_children: cortexMaxChildren, page_size_tokens: cortexPageSize,
                            context_budget_pct: cortexContextBudget, auto_checkpoint: cortexAutoCheckpoint,
                            resume_enabled: cortexResumeEnabled,
                        }
                    } : {}),
                },
                context_engineering: {
                    context_sources: contextSources,
                    inject_episodic_memory: injectEpisodicMemory, inject_semantic_context: injectSemanticContext,
                    inject_cortex_viewport: injectCortexViewport, no_truncation: noTruncation,
                },
            },

            governance: {
                max_cost_usd: maxCostUsd, timeout_ms: timeoutMs,
                execution_limits: { max_recursion_depth: maxRecursionDepth, max_tool_calls: maxToolCalls },
                hitl_checkpoints: hitlCheckpoints, checkpoint_every_n_steps: checkpointEveryNSteps,
            },

            io_contract: { input_schema: JSON.parse(inputSchema), output_schema: JSON.parse(outputSchema) },
            observability: { log_level: logLevel, log_thoughts: logThoughts, track_cost: trackCost },
            hierarchy: { children: extractChildrenFromGraph(hierarchyNodes, hierarchyEdges), is_atomic: hierarchyNodes.length === 0 },
        };
        onSave(entityData);
    };

    // ══════════════════════════════════════════════════════════════════════════
    // TAB DEFINITIONS — 5 tabs
    // ══════════════════════════════════════════════════════════════════════════

    const tabs = [
        { id: 'basics', label: 'Basics', icon: Info },
        { id: 'hierarchy', label: 'Hierarchy', icon: GitBranch },
        { id: 'brain', label: 'Brain', icon: Brain },
        { id: 'planning', label: 'Planning', icon: Route },
        { id: 'capabilities', label: 'Capabilities', icon: Wrench },
        { id: 'safeguards', label: 'Safeguards', icon: Shield },
    ];

    return (
        <div className="entity-configuration-tabs">
            <div className="tabs-header">
                {tabs.map(tab => (
                    <button key={tab.id} className={`tab-button ${activeTab === tab.id ? 'active' : ''}`} onClick={() => setActiveTab(tab.id)}>
                        <tab.icon size={16} />{tab.label}
                    </button>
                ))}
            </div>

            <div className="tabs-content">
                {/* ═══════════════════════════════ TAB 1: BASICS ═══════════════════════════════ */}
                {activeTab === 'basics' && (
                    <div className="tab-panel">
                        <div className="form-section">
                            <h3>Identity</h3>
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Name *</label>
                                    <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. John" />
                                    <small>Human-friendly name for this entity</small>
                                </div>
                                <div className="form-group">
                                    <label>Role</label>
                                    <input type="text" value={personaRole} onChange={(e) => setPersonaRole(e.target.value)} placeholder="e.g. Market Research Expert" />
                                    <small>Injected into the system prompt as the entity's role</small>
                                </div>
                            </div>
                            <div className="form-group">
                                <label>Display Name (auto-generated)</label>
                                <input type="text" value={personaRole ? `${name} - ${personaRole}` : name} readOnly disabled style={{ opacity: 0.6 }} />
                                <small>Auto-generated from Name + Role — used as unique identifier</small>
                            </div>
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Entity Type *</label>
                                    <select value={type} onChange={(e) => setType(e.target.value as EntityType)}>
                                        {Object.values(EntityType).map(t => <option key={t} value={t}>{t}</option>)}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label>Status</label>
                                    <select value={status} onChange={(e) => setStatus(e.target.value as EntityStatus)}>
                                        {Object.values(EntityStatus).map(s => <option key={s} value={s}>{s}</option>)}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label>Version</label>
                                    <input type="text" value={version} onChange={(e) => setVersion(e.target.value)} />
                                </div>
                            </div>
                            <div className="form-group">
                                <label>Description</label>
                                <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} placeholder="What does this entity do?" />
                            </div>
                            <div className="form-group">
                                <label>Tags</label>
                                <div className="tag-input-row">
                                    <input type="text" value={tagInput} onChange={(e) => setTagInput(e.target.value)} placeholder="Add tag..." onKeyDown={(e) => e.key === 'Enter' && addTag()} />
                                    <JellyButton variant="ghost" onClick={addTag}><Plus size={14} /></JellyButton>
                                </div>
                                <div className="tags-list">{tags.map(tag => <span key={tag} className="tag-badge">{tag} <Trash2 size={12} onClick={() => removeTag(tag)} /></span>)}</div>
                            </div>

                            {/* Company Assignment — only for admin/partner */}
                            {isAdminOrPartner && (
                                <div className="form-group">
                                    <label>Company Assignment</label>
                                    <select
                                        value={selectedCompanyId}
                                        onChange={(e) => handleCompanyChange(e.target.value)}
                                    >
                                        {userCompanyId && (
                                            <option value={userCompanyId}>My Company (default)</option>
                                        )}
                                        {companies
                                            .filter(c => c.id !== userCompanyId)
                                            .map(c => (
                                                <option key={c.id} value={c.id}>
                                                    {c.name} ({c.type})
                                                </option>
                                            ))}
                                    </select>
                                    <small>Assign this entity to a specific company</small>
                                </div>
                            )}

                            {/* Avatar */}
                            <div className="form-group">
                                <label>Avatar</label>
                                <div className="avatar-upload-row">
                                    <div className="avatar-preview">
                                        {profileImageUrl ? (
                                            <img src={profileImageUrl} alt="Avatar" />
                                        ) : (
                                            <User size={32} />
                                        )}
                                    </div>
                                    <div className="avatar-controls">
                                        <input type="text" value={profileImageUrl} onChange={(e) => setProfileImageUrl(e.target.value)} placeholder="Avatar URL or upload an image" />
                                        <input type="file" ref={avatarInputRef} accept="image/*" onChange={handleAvatarUpload} style={{ display: 'none' }} />
                                        <JellyButton variant="ghost" size="sm" onClick={() => avatarInputRef.current?.click()} disabled={avatarUploading}>
                                            <Upload size={14} /> {avatarUploading ? 'Uploading...' : 'Upload'}
                                        </JellyButton>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="form-section collapsible">
                            <h3>Input / Output Contract</h3>
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Input Schema (JSON)</label>
                                    <textarea className="code-editor" value={inputSchema} onChange={(e) => setInputSchema(e.target.value)} rows={4} />
                                </div>
                                <div className="form-group">
                                    <label>Output Schema (JSON)</label>
                                    <textarea className="code-editor" value={outputSchema} onChange={(e) => setOutputSchema(e.target.value)} rows={4} />
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* ═══════════════════════════════ TAB: HIERARCHY ═══════════════════════════════ */}
                {activeTab === 'hierarchy' && (
                    <div className="tab-panel hierarchy-tab-panel">
                        <div className="form-section" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                            <h3><GitBranch size={16} /> Hierarchy & Execution Flow</h3>
                            <div className="hierarchy-hint">
                                <Info size={16} />
                                <span>Drag entities and tools from the sidebar onto the canvas to define execution flow. Click edge labels to cycle between SEQUENTIAL / PARALLEL / CONDITIONAL.</span>
                            </div>
                            <EntityFlow
                                initialNodes={hierarchyNodes}
                                initialEdges={hierarchyEdges}
                                plannedTools={toolAssignments}
                                onSave={(nodes, edges) => { setHierarchyNodes(nodes); setHierarchyEdges(edges); }}
                            />
                        </div>
                    </div>
                )}

                {/* ═══════════════════════════════ TAB 2: BRAIN ════════════════════════════════ */}
                {activeTab === 'brain' && (
                    <div className="tab-panel">

                        {/* Voice Agent Toggle */}
                        <div className="form-section">
                            <div className="section-header-toggle">
                                <h3>{isVoiceAgent ? <Volume2 size={18} /> : <VolumeX size={18} />} Voice Agent</h3>
                                <label className="toggle-switch">
                                    <input type="checkbox" checked={isVoiceAgent} onChange={(e) => setIsVoiceAgent(e.target.checked)} />
                                    <span className="toggle-slider"></span>
                                </label>
                            </div>
                            {isVoiceAgent && (
                                <div className="voice-settings-panel">
                                    {/* Bio — used by persona_service for voice prompt fallback */}
                                    <div className="form-group">
                                        <label>Bio</label>
                                        <textarea value={personaBio} onChange={(e) => setPersonaBio(e.target.value)} rows={2} placeholder="Agent's background and expertise (used in voice prompt)" />
                                        <small>Injected into voice system prompt when no custom system prompt is set.</small>
                                    </div>

                                    <h4>Voice Settings</h4>
                                    <div className="form-row">
                                        <div className="form-group">
                                            <label>Voice</label>
                                            <select value={voiceName} onChange={(e) => setVoiceName(e.target.value)}>
                                                {GEMINI_VOICES.map(v => <option key={v} value={v}>{v}</option>)}
                                            </select>
                                        </div>
                                        <div className="form-group">
                                            <label>Language</label>
                                            <input type="text" value={languageCode} onChange={(e) => setLanguageCode(e.target.value)} />
                                        </div>
                                    </div>
                                    <div className="form-row">
                                        <div className="form-group">
                                            <label>Speaking Rate ({speakingRate}x)</label>
                                            <input type="range" min="0.25" max="4" step="0.05" value={speakingRate} onChange={(e) => setSpeakingRate(parseFloat(e.target.value))} />
                                        </div>
                                        <div className="form-group">
                                            <label>Pitch ({voicePitch} semitones)</label>
                                            <input type="range" min="-20" max="20" step="0.5" value={voicePitch} onChange={(e) => setVoicePitch(parseFloat(e.target.value))} />
                                        </div>
                                    </div>

                                    <h4><Sliders size={14} /> Personality Matrix</h4>
                                    <div className="form-row">
                                        <div className="form-group">
                                            <label>Tone</label>
                                            <select value={tone} onChange={(e) => setTone(e.target.value)}>
                                                <option value="professional">Professional</option>
                                                <option value="friendly">Friendly</option>
                                                <option value="formal">Formal</option>
                                                <option value="empathetic">Empathetic</option>
                                                <option value="assertive">Assertive</option>
                                            </select>
                                        </div>
                                        <div className="form-group">
                                            <label>Verbosity</label>
                                            <select value={verbosity} onChange={(e) => setVerbosity(e.target.value)}>
                                                <option value="concise">Concise</option>
                                                <option value="moderate">Moderate</option>
                                                <option value="verbose">Verbose</option>
                                            </select>
                                        </div>
                                        <div className="form-group">
                                            <label>Formality</label>
                                            <select value={formality} onChange={(e) => setFormality(e.target.value)}>
                                                <option value="informal">Informal</option>
                                                <option value="semi-formal">Semi-Formal</option>
                                                <option value="formal">Formal</option>
                                            </select>
                                        </div>
                                    </div>
                                    <div className="form-row">
                                        <div className="form-group">
                                            <label>Empathy Level ({empathyLevel})</label>
                                            <input type="range" min="0" max="1" step="0.1" value={empathyLevel} onChange={(e) => setEmpathyLevel(parseFloat(e.target.value))} />
                                        </div>
                                        <div className="form-group">
                                            <label>Humor Level ({humorLevel})</label>
                                            <input type="range" min="0" max="1" step="0.1" value={humorLevel} onChange={(e) => setHumorLevel(parseFloat(e.target.value))} />
                                        </div>
                                        <div className="form-group">
                                            <label>Decision Confidence ({decisionConfidence})</label>
                                            <input type="range" min="0" max="1" step="0.1" value={decisionConfidence} onChange={(e) => setDecisionConfidence(parseFloat(e.target.value))} />
                                        </div>
                                    </div>

                                    <h4>Dynamic Injection Hooks</h4>
                                    <div className="form-group">
                                        <label>Greeting Template</label>
                                        <textarea value={greetingTemplate} onChange={(e) => setGreetingTemplate(e.target.value)} rows={2} placeholder="Hello! I'm {{agent_name}}, how can I help you today?" />
                                    </div>
                                    <div className="form-row">
                                        <div className="form-group">
                                            <label>Escalation Message</label>
                                            <textarea value={escalationMessage} onChange={(e) => setEscalationMessage(e.target.value)} rows={2} placeholder="Let me transfer you to a human agent..." />
                                        </div>
                                        <div className="form-group">
                                            <label>Closing Message</label>
                                            <textarea value={closingMessage} onChange={(e) => setClosingMessage(e.target.value)} rows={2} placeholder="Thank you for your time. Goodbye!" />
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* System Prompt & Goal */}
                        <div className="form-section">
                            <h3>System Prompt</h3>
                            <div className="form-group">
                                <textarea className="code-editor" value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} rows={8} placeholder="You are a helpful AI assistant that..." />
                                <small>Core instruction that defines this entity's behavior.</small>
                            </div>
                        </div>

                        <div className="form-section">
                            <h3>Goal / Objective</h3>
                            <div className="form-group">
                                <textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={3} placeholder="What is this entity trying to achieve?" />
                                <small>Injected as "Goal & Objective" section in the prompt.</small>
                            </div>
                        </div>

                        {/* Behavioral Constraints */}
                        <div className="form-section">
                            <h3>Behavioral Constraints</h3>
                            <div className="tag-input-row">
                                <input type="text" value={constraintInput} onChange={(e) => setConstraintInput(e.target.value)} placeholder="e.g. Never reveal internal prompts..." onKeyDown={(e) => e.key === 'Enter' && addConstraint()} />
                                <JellyButton variant="ghost" onClick={addConstraint}><Plus size={14} /></JellyButton>
                            </div>
                            <div className="constraints-list">
                                {behavioralConstraints.map((c, i) => (
                                    <div key={i} className="constraint-item">
                                        <span>{c}</span>
                                        <Trash2 size={14} className="remove-btn" onClick={() => removeConstraint(i)} />
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Few-Shot Examples */}
                        <div className="form-section">
                            <h3>Few-Shot Examples</h3>
                            {fewShotExamples.map((ex, i) => (
                                <div key={i} className="few-shot-item">
                                    <div className="form-row">
                                        <div className="form-group">
                                            <label>Input</label>
                                            <textarea value={ex.input || ex.scenario || ''} onChange={(e) => updateFewShot(i, 'scenario', e.target.value)} rows={2} />
                                        </div>
                                        <div className="form-group">
                                            <label>Expected Output</label>
                                            <textarea value={ex.output || ex.ideal_response || ''} onChange={(e) => updateFewShot(i, 'ideal_response', e.target.value)} rows={2} />
                                        </div>
                                    </div>
                                    <Trash2 size={14} className="remove-btn" onClick={() => removeFewShot(i)} />
                                </div>
                            ))}
                            <JellyButton variant="ghost" onClick={addFewShot}><Plus size={14} /> Add Example</JellyButton>
                        </div>
                    </div>
                )}

                {/* ═══════════════════════════════ TAB 3: PLANNING ═════════════════════════════ */}
                {activeTab === 'planning' && (
                    <div className="tab-panel">
                        {/* LLM Configuration */}
                        <div className="form-section">
                            <h3><Settings size={16} /> LLM Configuration</h3>
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Task Type</label>
                                    <select value={taskType} onChange={(e) => setTaskType(e.target.value)}>
                                        <option value="text_generation">Text Generation</option>
                                        <option value="code_generation">Code Generation</option>
                                        <option value="analysis">Analysis</option>
                                        <option value="conversation">Conversation</option>
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label>Reasoning Mode</label>
                                    <select value={reasoningMode} onChange={(e) => setReasoningMode(e.target.value)}>
                                        <option value="REACT">ReAct</option>
                                        <option value="CHAIN_OF_THOUGHT">Chain of Thought</option>
                                        <option value="REFLECTION">Reflection</option>
                                        <option value="TREE_OF_THOUGHTS">Tree of Thoughts</option>
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label>Model Override</label>
                                    <input type="text" value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="e.g. gemini-3.1-pro-preview" />
                                    <small>Leave blank for default</small>
                                </div>
                            </div>
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Temperature ({temperature})</label>
                                    <input type="range" min="0" max="2" step="0.1" value={temperature} onChange={(e) => setTemperature(parseFloat(e.target.value))} />
                                </div>
                                <div className="form-group">
                                    <label>Top P ({topP})</label>
                                    <input type="range" min="0" max="1" step="0.05" value={topP} onChange={(e) => setTopP(parseFloat(e.target.value))} />
                                </div>
                                <div className="form-group">
                                    <label>Max Tokens</label>
                                    <input type="number" value={maxTokens || ''} onChange={(e) => setMaxTokens(e.target.value ? parseInt(e.target.value) : undefined)} placeholder="Auto" />
                                </div>
                            </div>
                        </div>

                        {/* Phase 5: Autonomous Mode */}
                        <div className="form-section">
                            <div className="section-header-toggle">
                                <h3>⚡ Execution Mode</h3>
                                <select value={executionMode} onChange={(e) => setExecutionMode(e.target.value)} style={{ width: 'auto', minWidth: 160 }}>
                                    <option value="STANDARD">Standard (Plan → Execute)</option>
                                    <option value="AUTONOMOUS">Autonomous (Goal-Centric)</option>
                                </select>
                            </div>
                            {executionMode === 'AUTONOMOUS' && (
                                <div className="voice-settings-panel">
                                    <small style={{ display: 'block', marginBottom: 12, opacity: 0.7 }}>
                                        Autonomous mode validates goal progress during execution and can re-plan on failure.
                                    </small>
                                    <div className="form-row">
                                        <div className="form-group">
                                            <label>Goal Validation Interval</label>
                                            <input type="number" min={1} max={10} value={goalValidationInterval} onChange={(e) => setGoalValidationInterval(parseInt(e.target.value) || 2)} />
                                            <small>Check goal progress every N steps</small>
                                        </div>
                                        <div className="form-group">
                                            <label>Confidence Threshold ({(confidenceThreshold * 100).toFixed(0)}%)</label>
                                            <input type="range" min="0" max="1" step="0.05" value={confidenceThreshold} onChange={(e) => setConfidenceThreshold(parseFloat(e.target.value))} />
                                            <small>Early-exit if goal score exceeds this</small>
                                        </div>
                                        <div className="form-group">
                                            <label>Max Re-planning Attempts</label>
                                            <input type="number" min={0} max={5} value={maxReplanningAttempts} onChange={(e) => setMaxReplanningAttempts(parseInt(e.target.value) || 3)} />
                                            <small>Limit LLM re-plans on step failures</small>
                                        </div>
                                    </div>
                                    <div className="section-header-toggle" style={{ marginTop: 8 }}>
                                        <span>Self-Reflection (CORTEX)</span>
                                        <label className="toggle-switch">
                                            <input type="checkbox" checked={selfReflectionEnabled} onChange={(e) => setSelfReflectionEnabled(e.target.checked)} />
                                            <span className="toggle-slider"></span>
                                        </label>
                                    </div>
                                    {selfReflectionEnabled && (
                                        <small style={{ display: 'block', opacity: 0.6, marginTop: 4 }}>
                                            Agent queries prior CORTEX knowledge before THOUGHT steps and writes reflection nodes after each step.
                                        </small>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Planning Strategy */}
                        <div className="form-section">
                            <h3><Route size={16} /> Planning Strategy</h3>
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="checkbox-label">
                                        <input type="checkbox" checked={staticPlanEnabled} onChange={(e) => setStaticPlanEnabled(e.target.checked)} /> Static Plan Enabled
                                    </label>
                                </div>
                                <div className="form-group">
                                    <label className="checkbox-label">
                                        <input type="checkbox" checked={dynamicPlanningEnabled} onChange={(e) => setDynamicPlanningEnabled(e.target.checked)} /> Dynamic Planning Enabled
                                    </label>
                                </div>
                                <div className="form-group">
                                    <label>Fallback Behavior</label>
                                    <select value={fallbackBehavior} onChange={(e) => setFallbackBehavior(e.target.value)}>
                                        <option value="STRICT">Strict</option>
                                        <option value="ADAPTIVE">Adaptive</option>
                                        <option value="DYNAMIC_ONLY">Dynamic Only</option>
                                    </select>
                                </div>
                            </div>

                            {dynamicPlanningEnabled && (
                                <>
                                    <div className="form-group">
                                        <label>Additional Planning Instructions</label>
                                        <textarea value={planningPrompt} onChange={(e) => setPlanningPrompt(e.target.value)} rows={3} placeholder="Extra instructions appended to the planning prompt..." />
                                    </div>
                                    <div className="collapsible-section">
                                        <button className="collapsible-header" onClick={() => setShowPlanningPrompt(!showPlanningPrompt)}>
                                            {showPlanningPrompt ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                            Planning System Prompt (Advanced)
                                        </button>
                                        {showPlanningPrompt && (
                                            <div className="form-group">
                                                <textarea className="code-editor" value={planningSystemPrompt} onChange={(e) => setPlanningSystemPrompt(e.target.value)} rows={12} />
                                                <small>The base system prompt for the dynamic planner. Modify with caution.</small>
                                            </div>
                                        )}
                                    </div>
                                    <div className="form-row">
                                        <div className="form-group">
                                            <label>Reconciliation Strategy</label>
                                            <select value={reconciliationStrategy} onChange={(e) => setReconciliationStrategy(e.target.value)}>
                                                <option value="STATIC_PRIORITY">Static Priority</option>
                                                <option value="DYNAMIC_PRIORITY">Dynamic Priority</option>
                                                <option value="HYBRID">Hybrid</option>
                                            </select>
                                        </div>
                                    </div>
                                    <div className="form-row">
                                        <div className="form-group"><label className="checkbox-label"><input type="checkbox" checked={allowedDeviations.can_add_steps} onChange={(e) => setAllowedDeviations({ ...allowedDeviations, can_add_steps: e.target.checked })} /> Can Add Steps</label></div>
                                        <div className="form-group"><label className="checkbox-label"><input type="checkbox" checked={allowedDeviations.can_skip_optional_steps} onChange={(e) => setAllowedDeviations({ ...allowedDeviations, can_skip_optional_steps: e.target.checked })} /> Can Skip Optional</label></div>
                                        <div className="form-group"><label className="checkbox-label"><input type="checkbox" checked={allowedDeviations.can_reorder_steps} onChange={(e) => setAllowedDeviations({ ...allowedDeviations, can_reorder_steps: e.target.checked })} /> Can Reorder Steps</label></div>
                                    </div>
                                </>
                            )}

                            <div className="form-row">
                                <div className="form-group">
                                    <label>Max Iterations</label>
                                    <input type="number" value={maxIterations} onChange={(e) => setMaxIterations(parseInt(e.target.value))} />
                                </div>
                                <div className="form-group">
                                    <label>Iteration Context Mode</label>
                                    <select value={iterationContextMode} onChange={(e) => setIterationContextMode(e.target.value)}>
                                        <option value="FULL_HISTORY">Full History</option>
                                        <option value="SUMMARIZED">Summarized</option>
                                        <option value="LAST_N">Last N</option>
                                    </select>
                                </div>
                            </div>
                        </div>

                        {/* Quality Review */}
                        <div className="form-section">
                            <div className="section-header-toggle">
                                <h3>Quality Review</h3>
                                <label className="toggle-switch">
                                    <input type="checkbox" checked={reviewEnabled} onChange={(e) => setReviewEnabled(e.target.checked)} />
                                    <span className="toggle-slider"></span>
                                </label>
                            </div>
                            {reviewEnabled && (
                                <>
                                    <div className="form-group">
                                        <label>Additional Review Criteria</label>
                                        <textarea value={reviewPrompt} onChange={(e) => setReviewPrompt(e.target.value)} rows={3} placeholder="Custom criteria appended to the review prompt..." />
                                    </div>
                                    <div className="collapsible-section">
                                        <button className="collapsible-header" onClick={() => setShowReviewPrompt(!showReviewPrompt)}>
                                            {showReviewPrompt ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                            Review System Prompt (Advanced)
                                        </button>
                                        {showReviewPrompt && (
                                            <div className="form-group">
                                                <textarea className="code-editor" value={reviewSystemPrompt} onChange={(e) => setReviewSystemPrompt(e.target.value)} rows={8} />
                                                <small>The base system prompt for the quality critic. Modify with caution.</small>
                                            </div>
                                        )}
                                    </div>
                                    <div className="form-row">
                                        <div className="form-group">
                                            <label>On Failure</label>
                                            <select value={reviewOnFailure} onChange={(e) => setReviewOnFailure(e.target.value)}>
                                                <option value="RETRY">Retry</option>
                                                <option value="ESCALATE">Escalate</option>
                                                <option value="ABORT">Abort</option>
                                            </select>
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>

                        {/* Retry Policy */}
                        <div className="form-section">
                            <h3>Retry Policy</h3>
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Max Retries</label>
                                    <input type="number" value={maxRetries} onChange={(e) => setMaxRetries(parseInt(e.target.value))} min={0} max={10} />
                                </div>
                                <div className="form-group">
                                    <label>Backoff Strategy</label>
                                    <select value={backoffStrategy} onChange={(e) => setBackoffStrategy(e.target.value)}>
                                        <option value="EXPONENTIAL">Exponential</option>
                                        <option value="LINEAR">Linear</option>
                                        <option value="NONE">None</option>
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label>Backoff Multiplier</label>
                                    <input type="number" step="0.5" value={backoffMultiplier} onChange={(e) => setBackoffMultiplier(parseFloat(e.target.value))} />
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* ═══════════════════════════════ TAB 4: CAPABILITIES ═════════════════════════ */}
                {activeTab === 'capabilities' && (
                    <div className="tab-panel">
                        {/* Unified Tool Pool */}
                        <div className="form-section">
                            <h3><Wrench size={16} /> Tools & Integrations</h3>
                            <small className="section-hint">Select tools and choose how each is used — <strong>Autonomous</strong> (LLM decides when to call), <strong>Planned</strong> (deterministic step in execution plan), or <strong>Both</strong>.</small>
                            <div className="tool-pool-search">
                                <Search size={16} />
                                <input type="text" placeholder="Search tools..." value={toolSearchQuery} onChange={(e) => setToolSearchQuery(e.target.value)} />
                            </div>
                            <div className="tool-pool-list">
                                {filteredAvailableTools.length === 0 ? (
                                    <div className="tool-pool-empty">No tools found</div>
                                ) : filteredAvailableTools.map(tool => {
                                    const assignment = toolAssignments.find(t => t.tool_id === tool.name);
                                    const isSelected = !!assignment;
                                    return (
                                        <div key={tool.name} className={`tool-pool-item ${isSelected ? 'selected' : ''}`}>
                                            <div className="tool-pool-item-check" onClick={() => toggleToolAssignment(tool.name)}>
                                                {isSelected ? <CheckSquare size={18} /> : <Square size={18} />}
                                            </div>
                                            <div className="tool-pool-item-info" onClick={() => toggleToolAssignment(tool.name)}>
                                                <div className="tool-pool-item-name"><Wrench size={14} /> {tool.display_name || tool.name}</div>
                                                <div className="tool-pool-item-desc">{tool.description}</div>
                                            </div>
                                            {isSelected && (
                                                <div className="tool-pool-item-usage">
                                                    <select value={assignment!.usage} onChange={(e) => setToolUsage(tool.name, e.target.value as ToolUsage)}>
                                                        <option value="AUTONOMOUS">Autonomous</option>
                                                        <option value="PLANNED">Planned</option>
                                                        <option value="BOTH">Both</option>
                                                    </select>
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                            <div className="tool-pool-summary">
                                {toolAssignments.length} tool{toolAssignments.length !== 1 ? 's' : ''} assigned
                                {toolAssignments.filter(t => t.usage === 'AUTONOMOUS' || t.usage === 'BOTH').length > 0 && (
                                    <span className="usage-badge autonomous">🤖 {toolAssignments.filter(t => t.usage === 'AUTONOMOUS' || t.usage === 'BOTH').length} autonomous</span>
                                )}
                                {toolAssignments.filter(t => t.usage === 'PLANNED' || t.usage === 'BOTH').length > 0 && (
                                    <span className="usage-badge planned">📋 {toolAssignments.filter(t => t.usage === 'PLANNED' || t.usage === 'BOTH').length} planned</span>
                                )}
                            </div>
                        </div>

                        {/* Memory & Context — ALL memory fields unified */}
                        <div className="form-section">
                            <div className="section-header-toggle">
                                <h3>Memory & Context</h3>
                                <label className="toggle-switch">
                                    <input type="checkbox" checked={memoryEnabled} onChange={(e) => setMemoryEnabled(e.target.checked)} />
                                    <span className="toggle-slider"></span>
                                </label>
                            </div>
                            {memoryEnabled && (
                                <>
                                    <div className="form-group">
                                        <label>Memory Mode</label>
                                        <select value={memoryMode} onChange={(e) => setMemoryMode(e.target.value)}>
                                            <option value="STANDARD">Standard (Episodic + Semantic)</option>
                                            <option value="CORTEX">CORTEX (Cognitive Tree)</option>
                                        </select>
                                    </div>

                                    {memoryMode === 'STANDARD' && (
                                        <div className="form-row">
                                            <div className="form-group">
                                                <label>Episodic Memory Count</label>
                                                <input type="number" value={episodicMemoryCount} onChange={(e) => setEpisodicMemoryCount(parseInt(e.target.value))} />
                                            </div>
                                            <div className="form-group">
                                                <label className="checkbox-label">
                                                    <input type="checkbox" checked={semanticSearchEnabled} onChange={(e) => setSemanticSearchEnabled(e.target.checked)} /> Semantic Search
                                                </label>
                                            </div>
                                            <div className="form-group">
                                                <label>Semantic Top K</label>
                                                <input type="number" value={semanticTopK} onChange={(e) => setSemanticTopK(parseInt(e.target.value))} />
                                            </div>
                                        </div>
                                    )}

                                    {memoryMode === 'CORTEX' && (
                                        <>
                                            <div className="form-row">
                                                <div className="form-group">
                                                    <label>Max Children per Node</label>
                                                    <input type="number" value={cortexMaxChildren} onChange={(e) => setCortexMaxChildren(parseInt(e.target.value))} />
                                                </div>
                                                <div className="form-group">
                                                    <label>Page Size (tokens)</label>
                                                    <input type="number" value={cortexPageSize} onChange={(e) => setCortexPageSize(parseInt(e.target.value))} />
                                                </div>
                                                <div className="form-group">
                                                    <label>Context Budget (%)</label>
                                                    <input type="number" value={cortexContextBudget} onChange={(e) => setCortexContextBudget(parseInt(e.target.value))} min={10} max={90} />
                                                </div>
                                            </div>
                                            <div className="form-row">
                                                <div className="form-group"><label className="checkbox-label"><input type="checkbox" checked={cortexAutoCheckpoint} onChange={(e) => setCortexAutoCheckpoint(e.target.checked)} /> Auto Checkpoint</label></div>
                                                <div className="form-group"><label className="checkbox-label"><input type="checkbox" checked={cortexResumeEnabled} onChange={(e) => setCortexResumeEnabled(e.target.checked)} /> Resume Enabled</label></div>
                                            </div>
                                        </>
                                    )}

                                    {/* Context Injection */}
                                    <h4>Context Injection</h4>
                                    <div className="form-row">
                                        <div className="form-group"><label className="checkbox-label"><input type="checkbox" checked={injectEpisodicMemory} onChange={(e) => setInjectEpisodicMemory(e.target.checked)} /> Inject Episodic Memory</label></div>
                                        <div className="form-group"><label className="checkbox-label"><input type="checkbox" checked={injectSemanticContext} onChange={(e) => setInjectSemanticContext(e.target.checked)} /> Inject Semantic Context</label></div>
                                        <div className="form-group"><label className="checkbox-label"><input type="checkbox" checked={injectCortexViewport} onChange={(e) => setInjectCortexViewport(e.target.checked)} /> Inject CORTEX Viewport</label></div>
                                        <div className="form-group"><label className="checkbox-label"><input type="checkbox" checked={noTruncation} onChange={(e) => setNoTruncation(e.target.checked)} /> No Truncation</label></div>
                                    </div>

                                    {/* Context Policy */}
                                    <h4>Context Policy</h4>
                                    <div className="form-row">
                                        <div className="form-group">
                                            <label>Policy Type</label>
                                            <select value={contextPolicyType} onChange={(e) => setContextPolicyType(e.target.value as any)}>
                                                <option value="FULL">Full Context</option>
                                                <option value="LAST_N">Last N Steps</option>
                                                <option value="SLIDING_WINDOW">Sliding Window</option>
                                                <option value="EXPLICIT">Explicit Keys</option>
                                            </select>
                                        </div>
                                        {contextPolicyType === 'LAST_N' && (
                                            <div className="form-group"><label>N Steps</label><input type="number" value={contextPolicyN || ''} onChange={(e) => setContextPolicyN(parseInt(e.target.value))} /></div>
                                        )}
                                        {contextPolicyType === 'SLIDING_WINDOW' && (
                                            <div className="form-group"><label>Max Chars</label><input type="number" value={contextPolicyMaxChars || ''} onChange={(e) => setContextPolicyMaxChars(parseInt(e.target.value))} /></div>
                                        )}
                                        <div className="form-group">
                                            <label>Summarize Threshold</label>
                                            <input type="number" value={contextPolicySummarizeThreshold || ''} onChange={(e) => setContextPolicySummarizeThreshold(parseInt(e.target.value))} placeholder="8000" />
                                        </div>
                                    </div>
                                    <div className="form-group">
                                        <label>Preserve Keys</label>
                                        <div className="tag-input-row">
                                            <input type="text" value={preserveKeyInput} onChange={(e) => setPreserveKeyInput(e.target.value)} placeholder="Key to preserve..." onKeyDown={(e) => e.key === 'Enter' && addPreserveKey()} />
                                            <JellyButton variant="ghost" onClick={addPreserveKey}><Plus size={14} /></JellyButton>
                                        </div>
                                        <div className="tags-list">{preserveKeys.map(k => <span key={k} className="tag-badge">{k} <Trash2 size={12} onClick={() => removePreserveKey(k)} /></span>)}</div>
                                    </div>
                                </>
                            )}
                        </div>

                        {/* Context Sources — Redesigned */}
                        <div className="form-section">
                            <h3><Database size={16} /> Context Sources</h3>
                            <p className="section-description">Attach documents, knowledge bases, or CORTEX trees to provide background context during execution. All sources are automatically ingested into CORTEX memory.</p>

                            {/* ── Sub-panel 1: External Documents (Upload) ── */}
                            <div className="context-source-panel">
                                <div className="cs-panel-header">
                                    <Upload size={16} />
                                    <span>External Documents</span>
                                    <span className="cs-panel-badge">{contextSources.filter(s => s.source_type === 'DOCUMENT').length}</span>
                                </div>
                                <p className="cs-panel-desc">Upload files to use as context. Supports PDF, DOCX, TXT, CSV, XLSX, images, audio, and video (max 500 MB).</p>

                                {/* Drop zone */}
                                <div
                                    className={`cs-upload-zone ${dragOver ? 'drag-over' : ''} ${uploadingFile ? 'uploading' : ''}`}
                                    onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                                    onDragLeave={() => setDragOver(false)}
                                    onDrop={handleDrop}
                                    onClick={() => contextFileInputRef.current?.click()}
                                >
                                    <input
                                        ref={contextFileInputRef}
                                        type="file"
                                        multiple
                                        style={{ display: 'none' }}
                                        accept=".pdf,.docx,.doc,.txt,.csv,.xlsx,.xls,.pptx,.ppt,.md,.json,.xml,.html,.jpg,.jpeg,.png,.webp,.gif,.mp3,.wav,.ogg,.mp4,.webm"
                                        onChange={(e) => handleContextFileUpload(e.target.files)}
                                    />
                                    {uploadingFile ? (
                                        <div className="cs-upload-spinner">Uploading...</div>
                                    ) : (
                                        <>
                                            <Upload size={24} className="cs-upload-icon" />
                                            <span className="cs-upload-text">Drop files here or click to browse</span>
                                            <span className="cs-upload-hint">PDF, DOCX, TXT, CSV, XLSX, Images, Audio, Video</span>
                                        </>
                                    )}
                                </div>

                                {/* Uploaded file chips */}
                                <div className="cs-source-list">
                                    {contextSources.filter(s => s.source_type === 'DOCUMENT').map((src, _i) => {
                                        const realIdx = contextSources.indexOf(src);
                                        return (
                                            <div key={src.reference_id || _i} className="cs-source-chip">
                                                <div className="cs-chip-icon">{getFileIcon(src.file_type || '')}</div>
                                                <div className="cs-chip-info">
                                                    <span className="cs-chip-name">{src.file_name || src.description || 'Document'}</span>
                                                    <span className="cs-chip-meta">{formatFileSize(src.file_size)}{src.file_type ? ` • ${src.file_type.split('/').pop()}` : ''}</span>
                                                </div>
                                                <X size={14} className="cs-chip-remove" onClick={() => removeContextSource(realIdx)} />
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>

                            {/* ── Sub-panel 2: Knowledge Base (Browse Company Docs) ── */}
                            <div className="context-source-panel">
                                <div className="cs-panel-header">
                                    <FolderOpen size={16} />
                                    <span>Knowledge Base</span>
                                    <span className="cs-panel-badge">{contextSources.filter(s => s.source_type === 'KNOWLEDGE_BASE').length}</span>
                                </div>
                                <p className="cs-panel-desc">Browse and select from your company's existing documents and artifacts.</p>

                                <JellyButton variant="ghost" onClick={openKBModal}>
                                    <Search size={14} /> Browse Knowledge Base
                                </JellyButton>

                                {/* Selected KB items */}
                                <div className="cs-source-list">
                                    {contextSources.filter(s => s.source_type === 'KNOWLEDGE_BASE').map((src, _i) => {
                                        const realIdx = contextSources.indexOf(src);
                                        return (
                                            <div key={src.reference_id || _i} className="cs-source-chip cs-chip-kb">
                                                <div className="cs-chip-icon"><FolderOpen size={16} /></div>
                                                <div className="cs-chip-info">
                                                    <span className="cs-chip-name">{src.file_name || src.description || 'Knowledge Base Item'}</span>
                                                    <span className="cs-chip-meta">{formatFileSize(src.file_size)}{src.file_type ? ` • ${src.file_type}` : ''}</span>
                                                </div>
                                                <X size={14} className="cs-chip-remove" onClick={() => removeContextSource(realIdx)} />
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>

                            {/* ── Sub-panel 3: CORTEX Trees ── */}
                            <div className="context-source-panel">
                                <div className="cs-panel-header">
                                    <Brain size={16} />
                                    <span>CORTEX Trees</span>
                                    <span className="cs-panel-badge">{contextSources.filter(s => s.source_type === 'CORTEX_TREE').length}</span>
                                </div>
                                <p className="cs-panel-desc">Link an existing CORTEX memory tree to inject its knowledge into this entity's context.</p>

                                <JellyButton variant="ghost" onClick={openTreeModal}>
                                    <Search size={14} /> Browse CORTEX Trees
                                </JellyButton>

                                {/* Selected trees */}
                                <div className="cs-source-list">
                                    {contextSources.filter(s => s.source_type === 'CORTEX_TREE').map((src, _i) => {
                                        const realIdx = contextSources.indexOf(src);
                                        return (
                                            <div key={src.reference_id || _i} className="cs-source-chip cs-chip-tree">
                                                <div className="cs-chip-icon"><Brain size={16} /></div>
                                                <div className="cs-chip-info">
                                                    <span className="cs-chip-name">{src.description || `Tree ${(src.reference_id || '').slice(0,8)}`}</span>
                                                    <span className="cs-chip-meta">
                                                        {src.tree_status && <span className={`cs-tree-status cs-tree-${src.tree_status}`}>{src.tree_status}</span>}
                                                        {src.tree_node_count != null && ` • ${src.tree_node_count} nodes`}
                                                    </span>
                                                </div>
                                                <X size={14} className="cs-chip-remove" onClick={() => removeContextSource(realIdx)} />
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>

                            {/* ── Sub-panel 4: DB Records (Coming Soon) ── */}
                            <div className="context-source-panel cs-panel-disabled">
                                <div className="cs-panel-header">
                                    <Database size={16} />
                                    <span>Database Records</span>
                                    <span className="cs-coming-soon-badge"><Lock size={10} /> Coming Soon</span>
                                </div>
                                <p className="cs-panel-desc">Query and attach database records as context for your entity. This feature is under development.</p>
                            </div>
                        </div>

                        {/* ── Knowledge Base Browser Modal ── */}
                        {showKBModal && (
                            <div className="cs-modal-overlay" onClick={() => setShowKBModal(false)}>
                                <div className="cs-modal" onClick={e => e.stopPropagation()}>
                                    <div className="cs-modal-header">
                                        <h3><FolderOpen size={18} /> Browse Knowledge Base</h3>
                                        <X size={18} className="cs-modal-close" onClick={() => setShowKBModal(false)} />
                                    </div>
                                    <div className="cs-modal-search">
                                        <Search size={14} />
                                        <input
                                            type="text"
                                            value={kbSearch}
                                            onChange={(e) => setKbSearch(e.target.value)}
                                            placeholder="Search documents..."
                                            autoFocus
                                        />
                                    </div>
                                    <div className="cs-modal-list">
                                        {kbLoading ? (
                                            <div className="cs-modal-loading">Loading documents...</div>
                                        ) : filteredKBItems.length === 0 ? (
                                            <div className="cs-modal-empty">No documents found. Upload documents first via the artifacts manager.</div>
                                        ) : (
                                            filteredKBItems.map(a => {
                                                const isSelected = contextSources.some(s => s.reference_id === a.id);
                                                return (
                                                    <div
                                                        key={a.id}
                                                        className={`cs-modal-item ${isSelected ? 'selected' : ''}`}
                                                        onClick={() => !isSelected && selectKBItem(a)}
                                                    >
                                                        <div className="cs-modal-item-icon">{getFileIcon(a.mime_type || a.file_category || '')}</div>
                                                        <div className="cs-modal-item-info">
                                                            <span className="cs-modal-item-name">{a.file_name || a.filename}</span>
                                                            <span className="cs-modal-item-meta">
                                                                {a.file_category || a.file_type}
                                                                {a.file_size ? ` • ${formatFileSize(Number(a.file_size))}` : ''}
                                                                {a.created_at ? ` • ${parseServerDate(a.created_at).toLocaleDateString()}` : ''}
                                                            </span>
                                                        </div>
                                                        {isSelected && <span className="cs-modal-item-check">✓ Added</span>}
                                                    </div>
                                                );
                                            })
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* ── CORTEX Tree Picker Modal ── */}
                        {showTreeModal && (
                            <div className="cs-modal-overlay" onClick={() => setShowTreeModal(false)}>
                                <div className="cs-modal" onClick={e => e.stopPropagation()}>
                                    <div className="cs-modal-header">
                                        <h3><Brain size={18} /> Browse CORTEX Trees</h3>
                                        <X size={18} className="cs-modal-close" onClick={() => setShowTreeModal(false)} />
                                    </div>
                                    <div className="cs-modal-search">
                                        <Search size={14} />
                                        <input
                                            type="text"
                                            value={treeSearch}
                                            onChange={(e) => setTreeSearch(e.target.value)}
                                            placeholder="Search trees..."
                                            autoFocus
                                        />
                                    </div>
                                    <div className="cs-modal-list">
                                        {treeLoading ? (
                                            <div className="cs-modal-loading">Loading CORTEX trees...</div>
                                        ) : filteredTrees.length === 0 ? (
                                            <div className="cs-modal-empty">No CORTEX trees found. Trees are created during entity execution.</div>
                                        ) : (
                                            filteredTrees.map(t => {
                                                const isSelected = contextSources.some(s => s.reference_id === t.id);
                                                return (
                                                    <div
                                                        key={t.id}
                                                        className={`cs-modal-item ${isSelected ? 'selected' : ''}`}
                                                        onClick={() => !isSelected && selectTree(t)}
                                                    >
                                                        <div className="cs-modal-item-icon"><Brain size={16} /></div>
                                                        <div className="cs-modal-item-info">
                                                            <span className="cs-modal-item-name">{t.task_description || `Tree ${t.id.slice(0,8)}`}</span>
                                                            <span className="cs-modal-item-meta">
                                                                <span className={`cs-tree-status cs-tree-${t.status}`}>{t.status}</span>
                                                                {` • ${t.total_nodes || 0} nodes`}
                                                                {t.created_at ? ` • ${parseServerDate(t.created_at).toLocaleDateString()}` : ''}
                                                            </span>
                                                        </div>
                                                        {isSelected && <span className="cs-modal-item-check">✓ Added</span>}
                                                    </div>
                                                );
                                            })
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* ═══════════════════════════════ TAB 5: SAFEGUARDS ═══════════════════════════ */}
                {activeTab === 'safeguards' && (
                    <div className="tab-panel">
                        {/* Cost Controls */}
                        <div className="form-section">
                            <h3>Cost Controls</h3>
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Max Cost (USD)</label>
                                    <input type="number" step="0.01" value={maxCostUsd || ''} onChange={(e) => setMaxCostUsd(e.target.value ? parseFloat(e.target.value) : undefined)} placeholder="No limit" />
                                </div>
                                <div className="form-group">
                                    <label className="checkbox-label">
                                        <input type="checkbox" checked={trackCost} onChange={(e) => setTrackCost(e.target.checked)} /> Track Execution Cost & Tokens
                                    </label>
                                </div>
                            </div>
                        </div>

                        {/* Execution Limits */}
                        <div className="form-section">
                            <h3>Execution Limits</h3>
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Timeout (ms)</label>
                                    <input type="number" value={timeoutMs} onChange={(e) => setTimeoutMs(parseInt(e.target.value))} />
                                    <small>Per-step timeout. Now enforced via asyncio.wait_for().</small>
                                </div>
                                <div className="form-group">
                                    <label>Max Recursion Depth</label>
                                    <input type="number" value={maxRecursionDepth} onChange={(e) => setMaxRecursionDepth(parseInt(e.target.value))} />
                                </div>
                                <div className="form-group">
                                    <label>Max Tool Calls</label>
                                    <input type="number" value={maxToolCalls || ''} onChange={(e) => setMaxToolCalls(e.target.value ? parseInt(e.target.value) : undefined)} placeholder="Unlimited" />
                                </div>
                            </div>
                            <div className="form-group">
                                <label>Checkpoint Every N Steps</label>
                                <input type="number" value={checkpointEveryNSteps} onChange={(e) => setCheckpointEveryNSteps(parseInt(e.target.value))} min={1} />
                                <small>CORTEX memory auto-checkpoint frequency.</small>
                            </div>
                        </div>

                        {/* HITL Checkpoints */}
                        <div className="form-section">
                            <h3><AlertTriangle size={16} /> Human-in-the-Loop Checkpoints</h3>
                            <p className="section-description">Configure points where execution pauses for human approval.</p>

                            {hitlCheckpoints.map((cp, idx) => (
                                <div key={idx} className="hitl-checkpoint-card">
                                    <div className="checkpoint-header">
                                        <span className="checkpoint-badge">{idx + 1}</span>
                                        <select value={cp.trigger_type} onChange={(e) => updateCheckpoint(idx, 'trigger_type', e.target.value)}>
                                            {HITL_TRIGGER_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                                        </select>
                                        <Trash2 size={14} className="remove-btn" onClick={() => removeCheckpoint(idx)} />
                                    </div>
                                    <small className="trigger-description">
                                        {HITL_TRIGGER_TYPES.find(t => t.value === cp.trigger_type)?.description}
                                    </small>
                                    <div className="form-row mt-2">
                                        {(cp.trigger_type === 'BEFORE_STEP' || cp.trigger_type === 'AFTER_STEP') && (
                                            <div className="form-group">
                                                <label>Step Reference</label>
                                                <input type="text" value={cp.step_ref || ''} onChange={(e) => updateCheckpoint(idx, 'step_ref', e.target.value)} placeholder="step_1 or Step Name" />
                                            </div>
                                        )}
                                        {cp.trigger_type === 'TOOL_CALL' && (
                                            <div className="form-group">
                                                <label>Tool ID</label>
                                                <input type="text" value={cp.tool_ref || ''} onChange={(e) => updateCheckpoint(idx, 'tool_ref', e.target.value)} placeholder="scraper_tool" />
                                            </div>
                                        )}
                                        {cp.trigger_type === 'COST_THRESHOLD' && (
                                            <div className="form-group">
                                                <label>Cost Threshold (USD)</label>
                                                <input type="number" step="0.01" value={cp.threshold || ''} onChange={(e) => updateCheckpoint(idx, 'threshold', parseFloat(e.target.value))} />
                                            </div>
                                        )}
                                        {cp.trigger_type === 'CUSTOM' && (
                                            <div className="form-group">
                                                <label>Expression</label>
                                                <input type="text" value={cp.expression || ''} onChange={(e) => updateCheckpoint(idx, 'expression', e.target.value)} placeholder="cost > 0.50 or step_count > 5" />
                                            </div>
                                        )}
                                        <div className="form-group">
                                            <label>Timeout (ms)</label>
                                            <input type="number" value={cp.timeout_ms} onChange={(e) => updateCheckpoint(idx, 'timeout_ms', parseInt(e.target.value))} />
                                        </div>
                                    </div>
                                    <div className="form-row">
                                        <div className="form-group">
                                            <label>Message</label>
                                            <input type="text" value={cp.message || ''} onChange={(e) => updateCheckpoint(idx, 'message', e.target.value)} placeholder="Approval required: ..." />
                                        </div>
                                        <div className="form-group">
                                            <label className="checkbox-label">
                                                <input type="checkbox" checked={cp.auto_approve_on_timeout} onChange={(e) => updateCheckpoint(idx, 'auto_approve_on_timeout', e.target.checked)} />
                                                Auto-approve on timeout
                                            </label>
                                        </div>
                                    </div>
                                </div>
                            ))}

                            <JellyButton variant="ghost" onClick={addCheckpoint}><Plus size={14} /> Add Checkpoint</JellyButton>
                        </div>

                        {/* Observability */}
                        <div className="form-section">
                            <h3>Observability</h3>
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Log Level</label>
                                    <select value={logLevel} onChange={(e) => setLogLevel(e.target.value)}>
                                        <option value="DEBUG">Debug</option>
                                        <option value="INFO">Info</option>
                                        <option value="WARN">Warn</option>
                                        <option value="ERROR">Error</option>
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="checkbox-label">
                                        <input type="checkbox" checked={logThoughts} onChange={(e) => setLogThoughts(e.target.checked)} /> Log Internal Thoughts
                                    </label>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            <div className="tabs-footer">
                <JellyButton variant="ghost" onClick={onCancel}>Cancel</JellyButton>
                <JellyButton roseGold onClick={handleSave}>Save Entity</JellyButton>
            </div>
        </div>
    );
};
