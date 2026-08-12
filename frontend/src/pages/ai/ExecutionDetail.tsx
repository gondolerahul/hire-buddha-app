import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { GlassCard, JellyButton } from '@/components/ui';
import {
    ArrowLeft, ChevronDown, ChevronRight, Zap, Cpu, MessageSquare, Wrench,
    DollarSign, Database, Brain, Layers, Activity, Download, RefreshCw,
    Clock, CheckCircle, XCircle, AlertTriangle, Eye, EyeOff, GitBranch,
    Sparkles, Send, SkipForward
} from 'lucide-react';
import { apiClient } from '@/services/api.client';
import { ExecutionRun, RunStatus, EntityType, LLMInteractionLog, ToolInteractionLog } from '@/types';
import { useFeatureFlag } from '@/hooks/useFeatureFlag';
import { AgentLoopExecutionDetail } from '@/components/agent/AgentLoopExecutionDetail';
import './ExecutionDetail.css';

const _API_BASE = (import.meta.env.VITE_API_BASE_URL as string)
    || 'https://gateway.hirebuddha.com/api/v1';

// Authenticated file download — uses apiClient (with auto token-refresh)
// for /api/ routes, falls back to direct fetch for static artifact paths.
const downloadArtifactFile = async (fileUrl: string, filename?: string) => {
    try {
        let blob: Blob;
        if (fileUrl.startsWith('/api/')) {
            // Use apiClient which has the 401→refresh interceptor
            const response = await apiClient.get(fileUrl.replace(/^\/api\/v1/, ''), {
                responseType: 'blob',
            });
            blob = response.data as Blob;
        } else {
            // Static file path (e.g. /artifact/system-generated/...) — no auth needed
            const response = await fetch(fileUrl);
            if (!response.ok) throw new Error('Download failed');
            blob = await response.blob();
        }
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename || 'document';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (err) {
        console.error('Artifact download failed:', err);
    }
};

// Supported document extensions for artifact detection
const DOCUMENT_EXTENSIONS = '(?:pdf|pptx|docx|xlsx)';

// ─── Step Result from result_data.steps ─────────────────────────────────────
interface StepResult {
    step: string;
    step_id?: string;
    type?: string;
    output?: any;
    error?: string;
    success?: boolean;
}

// ─── Step Timeline ──────────────────────────────────────────────────────────
const StepTimeline: React.FC<{
    steps: StepResult[];
    llmLogs: LLMInteractionLog[];
    toolLogs: ToolInteractionLog[];
    selectedStep: string | null;
    onSelectStep: (stepName: string | null) => void;
}> = ({ steps, llmLogs, toolLogs, selectedStep, onSelectStep }) => {
    const getStepIcon = (step: StepResult) => {
        if (step.error) return <XCircle size={16} className="text-error" />;
        if ((step as any).reused) return <SkipForward size={16} className="text-amber-400" />;
        if (step.type === 'TOOL_CALL') return <Wrench size={16} className="text-info" />;
        if (step.type === 'NAVIGATE' || step.type === 'READ' || step.type === 'WRITE')
            return <Brain size={16} className="text-secondary" />;
        return <CheckCircle size={16} className="text-success" />;
    };

    const getStepLLMLogs = (stepName: string) =>
        llmLogs.filter(l => l.step_name === stepName);

    const getStepToolLogs = (stepName: string) =>
        toolLogs.filter(l => {
            // Match tool logs by name similarity (tool logs don't have step_name)
            return false; // We rely on LLM logs' step_name for filtering
        });

    return (
        <div className="step-timeline">
            <div className="timeline-header">
                <GitBranch size={18} className="text-rose-gold" />
                <h3>Execution Steps ({steps.length})</h3>
            </div>
            <div className="timeline-track">
                {steps.map((step, idx) => {
                    const stepLogs = getStepLLMLogs(step.step || step.step_id || `step_${idx}`);
                    const isSelected = selectedStep === (step.step || `step_${idx}`);
                    const stepTokens = stepLogs.reduce((sum, l) => sum + l.prompt_tokens + l.completion_tokens, 0);
                    const stepCost = stepLogs.reduce((sum, l) => sum + (l.cost_usd || 0), 0);

                    return (
                        <div key={step.step_id || step.step || idx} className="timeline-step-wrapper">
                            <div
                                className={`timeline-step ${isSelected ? 'active' : ''} ${step.error ? 'error' : ''}`}
                                onClick={() => onSelectStep(isSelected ? null : (step.step || `step_${idx}`))}
                            >
                                <div className="step-indicator">
                                    <div className="step-dot">{getStepIcon(step)}</div>
                                    {idx < steps.length - 1 && <div className="step-line" />}
                                </div>
                                <div className="step-content">
                                    <div className="step-title">
                                        <span className="step-number">#{idx + 1}</span>
                                        <span className="step-name">{step.step || `Step ${idx + 1}`}</span>
                                        {step.type && <span className="step-type-badge">{step.type}</span>}
                                        {(step as any).reused && <span className="step-reused-badge">REUSED</span>}
                                    </div>
                                    <div className="step-stats">
                                        {stepLogs.length > 0 && (
                                            <span className="step-stat">
                                                <MessageSquare size={10} /> {stepLogs.length} LLM calls
                                            </span>
                                        )}
                                        {stepTokens > 0 && (
                                            <span className="step-stat">
                                                <Database size={10} /> {stepTokens.toLocaleString()} tokens
                                            </span>
                                        )}
                                        {stepCost > 0 && (
                                            <span className="step-stat">
                                                <DollarSign size={10} /> ${stepCost.toFixed(4)}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

// ─── Step Detail Drill-Down ─────────────────────────────────────────────────
const StepDetailPanel: React.FC<{
    step: StepResult;
    llmLogs: LLMInteractionLog[];
    onClose: () => void;
}> = ({ step, llmLogs, onClose }) => {
    const [expandedLogId, setExpandedLogId] = useState<string | null>(null);

    const stepLogs = llmLogs.filter(l => l.step_name === step.step);

    return (
        <div className="step-detail-panel">
            <div className="panel-header">
                <h3>{step.step}</h3>
                <div className="panel-actions">
                    {step.type && <span className="step-type-badge">{step.type}</span>}
                    <button className="close-btn" onClick={onClose}>✕</button>
                </div>
            </div>

            {/* Step Output */}
            <div className="panel-section">
                <h4>Output</h4>
                <div className="output-preview">
                    {step.error ? (
                        <div className="output-error">{step.error}</div>
                    ) : (
                        <pre className="output-text">
                            {typeof step.output === 'string'
                                ? step.output
                                : JSON.stringify(step.output, null, 2)}
                        </pre>
                    )}
                </div>
            </div>

            {/* LLM Interactions for this step */}
            {stepLogs.length > 0 && (
                <div className="panel-section">
                    <h4>LLM Interactions ({stepLogs.length})</h4>
                    <div className="llm-logs-list">
                        {stepLogs.map((log) => (
                            <div key={log.id} className="llm-log-card">
                                <div
                                    className="log-card-header"
                                    onClick={() => setExpandedLogId(expandedLogId === log.id ? null : log.id)}
                                >
                                    <div className="log-card-info">
                                        {log.reasoning_mode && (
                                            <span className={`reasoning-badge ${log.reasoning_mode.toLowerCase()}`}>
                                                {log.reasoning_mode}
                                            </span>
                                        )}
                                        <span className="log-model">{log.model_name}</span>
                                    </div>
                                    <div className="log-card-stats">
                                        <span>{(log.prompt_tokens + log.completion_tokens).toLocaleString()} tokens</span>
                                        <span>${(log.cost_usd || 0).toFixed(4)}</span>
                                        <span>{log.latency_ms}ms</span>
                                        {expandedLogId === log.id ? <EyeOff size={14} /> : <Eye size={14} />}
                                    </div>
                                </div>
                                {expandedLogId === log.id && (
                                    <div className="log-card-body">
                                        <div className="io-section">
                                            <label className="io-label">Prompt</label>
                                            <pre className="io-content prompt">{log.input_prompt}</pre>
                                        </div>
                                        <div className="io-section">
                                            <label className="io-label">Response</label>
                                            <pre className="io-content response">{log.output_response}</pre>
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};

// ─── Trace Node (existing hierarchy view, preserved) ────────────────────────
const TraceNode: React.FC<{ run: ExecutionRun; depth: number }> = ({ run, depth }) => {
    const [expanded, setExpanded] = useState(depth < 2);
    const [showLLMLogs, setShowLLMLogs] = useState(false);
    const [showToolLogs, setShowToolLogs] = useState(false);

    const hasChildren = run.child_runs && run.child_runs.length > 0;
    const hasLLMLogs = run.llm_logs && run.llm_logs.length > 0;
    const hasToolLogs = run.tool_logs && run.tool_logs.length > 0;

    const getStatusColor = (status: RunStatus) => {
        switch (status) {
            case RunStatus.COMPLETED: return 'var(--color-success)';
            case RunStatus.FAILED: return 'var(--color-error)';
            case RunStatus.RUNNING: return 'var(--color-info)';
            case 'PAUSED' as RunStatus: return 'var(--color-warning, #f59e0b)';
            case 'RESUMING' as RunStatus: return 'var(--color-info)';
            case 'PARTIAL_COMPLETE' as RunStatus: return 'var(--color-success)';
            default: return 'var(--color-text-tertiary)';
        }
    };

    // Helper function to extract artifact path from result data or tool logs
    const extractArtifactPath = (run: ExecutionRun): string | null => {
        const { result_data: resultData, tool_logs: toolLogs } = run;

        // Scan any string for embedded document paths (absolute or relative artifact paths)
        const scanStr = (s: string): string | null => {
            if (!s) return null;
            // Pattern 1: Auto-registered artifact download URL: /api/v1/artifacts/{uuid}/download or /api/v1/ai/artifacts/{uuid}/download
            // Also try to extract filename from surrounding context like "• filename.ext (size) — [Download](/api/...)"
            const apiArtifactMatch = s.match(/\/api\/v1\/(?:ai\/)?artifacts\/([0-9a-f-]{36})\/download/);
            if (apiArtifactMatch) {
                // Try to extract filename from nearby text: "• filename.ext" before the URL
                const fnMatch = s.match(/[•\-]\s*([\w][\w .()-]+\.(?:pptx|docx|xlsx|pdf|csv|html|png|jpg|svg))\s*\(/i);
                const filename = fnMatch ? fnMatch[1].trim() : 'document';
                return `__artifact_api__${apiArtifactMatch[1]}__${filename}`;
            }
            // Pattern 2: Absolute path: /some/path/artifact/uuid/uuid/file.ext
            const extPattern = new RegExp(`\\/[^\\s"']*\\/artifact\\/([^\\s"']+\\.${DOCUMENT_EXTENSIONS})`);
            const absMatch = s.match(extPattern);
            if (absMatch) return `artifact/${absMatch[1]}`;
            // Pattern 3: Relative: artifact/uuid/uuid/file.ext
            const relPattern = new RegExp(`artifact\\/([^\\s"']+\\.${DOCUMENT_EXTENSIONS})`);
            const relMatch = s.match(relPattern);
            if (relMatch) return `artifact/${relMatch[1]}`;
            // Pattern 4: Legacy /tmp path
            const tmpMatch = s.match(/\/tmp\/research_reports\/[a-zA-Z0-9_.-]+\.pdf/);
            if (tmpMatch) return tmpMatch[0];
            return null;
        };

        // 1. result_data.pdf_path or file_path
        if (resultData?.pdf_path) return scanStr(resultData.pdf_path) || resultData.pdf_path;
        if (resultData?.file_path) return scanStr(resultData.file_path) || resultData.file_path;
        if (resultData?.document_path) return scanStr(resultData.document_path) || resultData.document_path;

        // 2. tool logs
        if (toolLogs && toolLogs.length > 0) {
            for (const log of toolLogs) {
                if (log.output_result) {
                    const raw = typeof log.output_result === 'string'
                        ? log.output_result
                        : JSON.stringify(log.output_result);
                    try {
                        const parsed = JSON.parse(raw);
                        if (parsed.pdf_path) return scanStr(parsed.pdf_path) || parsed.pdf_path;
                        if (parsed.file_path) return scanStr(parsed.file_path) || parsed.file_path;
                        if (parsed.document_path) return scanStr(parsed.document_path) || parsed.document_path;
                    } catch { }
                    const found = scanStr(raw);
                    if (found) return found;
                }
            }
        }

        // 3. result_data.output
        if (resultData?.output) {
            const raw = typeof resultData.output === 'string'
                ? resultData.output
                : JSON.stringify(resultData.output);
            try {
                const parsed = JSON.parse(raw);
                if (parsed.pdf_path) return scanStr(parsed.pdf_path) || parsed.pdf_path;
                if (parsed.file_path) return scanStr(parsed.file_path) || parsed.file_path;
                if (parsed.document_path) return scanStr(parsed.document_path) || parsed.document_path;
            } catch { }
            const found = scanStr(raw);
            if (found) return found;
        }

        // 4. steps array
        if (resultData?.steps && Array.isArray(resultData.steps)) {
            for (const step of resultData.steps) {
                if (step.output) {
                    const raw = typeof step.output === 'string' ? step.output : JSON.stringify(step.output);
                    const found = scanStr(raw);
                    if (found) return found;
                }
            }
        }

        return null;
    };

    const pdfPath = extractArtifactPath(run);

    // Convert file path to URL accessible via the backend static files server
    const getPdfUrl = (filePath: string | null): string | null => {
        if (!filePath) return null;
        // Auto-registered artifact via /api/v1/artifacts/{id}/download
        if (filePath.startsWith('__artifact_api__')) {
            const parts = filePath.replace('__artifact_api__', '').split('__');
            const artifactId = parts[0];
            return `/api/v1/artifacts/${artifactId}/download`;
        }
        // Already a relative artifact path (normalised by extractPdfPath)
        if (filePath.startsWith('artifact/')) return `/${filePath}`;
        // Absolute server path – strip everything before "artifact/"
        const m = filePath.match(/artifact\/(.+)/);
        if (m) return `/artifact/${m[1]}`;
        // Legacy /tmp/research_reports/
        const filename = filePath.split('/').pop();
        return filename ? `/reports/${filename}` : null;
    };

    const pdfUrl = getPdfUrl(pdfPath);

    return (
        <div className="trace-node" style={{ marginLeft: depth > 0 ? '32px' : '0' }}>
            <div className={`node-header ${run.status.toLowerCase()}`} onClick={() => hasChildren && setExpanded(!expanded)}>
                <div className="node-icon">
                    {hasChildren ? (expanded ? <ChevronDown size={14} strokeWidth={3} /> : <ChevronRight size={14} strokeWidth={3} />) : <div style={{ width: 14 }} />}
                    {run.entity?.type === EntityType.ACTION ? <Zap size={16} className="text-rose-gold" /> : <Cpu size={16} className="text-secondary" />}
                </div>

                <div className="node-info">
                    <span className="node-type">{run.entity?.type || 'UNKNOWN'}</span>
                    <span className="node-name">{run.entity?.name || 'Anonymous Unit'}</span>
                </div>

                <div className="node-meta">
                    <div className="stat-group">
                        {(run.billed_amount != null ? run.billed_amount > 0 : run.total_cost_usd > 0) && (
                            <div className="stat-item mini" title="Billed">
                                <DollarSign size={10} /> ${(run.billed_amount != null ? run.billed_amount : run.total_cost_usd).toFixed(4)}
                            </div>
                        )}
                        {run.total_tokens > 0 && (
                            <div className="stat-item mini" title="Tokens">
                                <Database size={10} /> {run.total_tokens.toLocaleString()}
                            </div>
                        )}
                    </div>
                    <span className="node-status" style={{ color: getStatusColor(run.status) }}>
                        {run.status}
                    </span>
                    {run.execution_time_ms ? (
                        <span className="node-duration">{(run.execution_time_ms / 1000).toFixed(2)}s</span>
                    ) : run.completed_at && run.started_at && (
                        <span className="node-duration">
                            {((parseServerDate(run.completed_at).getTime() - parseServerDate(run.started_at).getTime()) / 1000).toFixed(2)}s
                        </span>
                    )}
                </div>
            </div>

            {expanded && (
                <div className="node-body">
                    {/* Reasoning / Thoughts */}
                    {run.context_state?.reasoning && (
                        <div className="node-thought">
                            <div className="thought-header"><MessageSquare size={12} /> AI Workspace / Reasoning</div>
                            <div className="thought-content">{run.context_state.reasoning}</div>
                        </div>
                    )}

                    {/* LLM Logs */}
                    {hasLLMLogs && (
                        <div className="node-logs">
                            <button className="text-btn" onClick={() => setShowLLMLogs(!showLLMLogs)}>
                                {showLLMLogs ? 'Hide' : 'Show'} LLM Interactions ({run.llm_logs?.length})
                            </button>
                            {showLLMLogs && run.llm_logs?.map((log: LLMInteractionLog) => (
                                <div key={log.id} className="log-entry">
                                    <div className="log-meta">
                                        <div className="stat-group">
                                            <span>{log.model_name} ({log.model_provider})</span>
                                            {log.reasoning_mode && <span className="badge">{log.reasoning_mode}</span>}
                                            {log.step_name && <span className="badge badge-step">{log.step_name}</span>}
                                        </div>
                                        <div className="stat-group">
                                            <span>{log.prompt_tokens + log.completion_tokens} tokens</span>
                                            <span>${log.cost_usd.toFixed(4)}</span>
                                            <span>{log.latency_ms}ms</span>
                                        </div>
                                    </div>
                                    <div className="log-io">
                                        <div className="io-box">
                                            <label>Prompt</label>
                                            <pre>{log.input_prompt}</pre>
                                        </div>
                                        <div className="io-box">
                                            <label>Response</label>
                                            <pre>{log.output_response}</pre>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Tool Logs */}
                    {hasToolLogs && (
                        <div className="node-tools">
                            <button className="text-btn" onClick={() => setShowToolLogs(!showToolLogs)}>
                                {showToolLogs ? 'Hide' : 'Show'} Tool Interactions ({run.tool_logs?.length})
                            </button>
                            {showToolLogs && run.tool_logs?.map((log: ToolInteractionLog) => (
                                <div key={log.id} className="tool-entry">
                                    <div className="tool-meta">
                                        <span><Wrench size={10} /> {log.tool_name}</span>
                                        <span>{log.latency_ms}ms</span>
                                        <span style={{ color: log.success ? 'var(--color-success)' : 'var(--color-error)' }}>
                                            {log.success ? 'SUCCESS' : 'FAILED'}
                                        </span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Document Download Button */}
                    {pdfUrl && (() => {
                        // Extract clean filename from pdfPath token
                        let displayName = 'document';
                        if (pdfPath?.startsWith('__artifact_api__')) {
                            const parts = pdfPath.replace('__artifact_api__', '').split('__');
                            displayName = parts[1] || 'document';
                        } else {
                            displayName = pdfPath?.split('/').pop() || 'document';
                        }
                        return (
                            <div className="node-result" style={{ marginBottom: '1rem' }}>
                                <label>Generated Document</label>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginTop: '0.5rem' }}>
                                    <code style={{ flex: 1, padding: '0.5rem', background: 'var(--color-bg-secondary)', borderRadius: '4px' }}>
                                        {displayName}
                                    </code>
                                    <JellyButton
                                        variant="secondary"
                                        size="sm"
                                        onClick={() => downloadArtifactFile(pdfUrl!, displayName)}
                                    >
                                        <Download size={16} /> Download
                                    </JellyButton>
                                </div>
                            </div>
                        );
                    })()}

                    {/* Result */}
                    {run.result_data && (
                        <div className="node-result">
                            <label>Structured Output</label>
                            <pre>{JSON.stringify(run.result_data, null, 2)}</pre>
                        </div>
                    )}

                    {/* Error */}
                    {run.error_message && (
                        <div className="node-error">
                            <label>Execution Error</label>
                            <div className="error-text">{run.error_message}</div>
                        </div>
                    )}

                    {/* Recursive Children */}
                    {hasChildren && (
                        <div className="node-children">
                            {run.child_runs?.map(child => (
                                <TraceNode key={child.id} run={child} depth={depth + 1} />
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

// ─── Main Execution Detail Page ─────────────────────────────────────────────
export const ExecutionDetail: React.FC = () => {
    const { id } = useParams();
    const navigate = useNavigate();
    const [run, setRun] = useState<ExecutionRun | null>(null);
    const [loading, setLoading] = useState(true);
    const [retrying, setRetrying] = useState(false);
    const [selectedStep, setSelectedStep] = useState<string | null>(null);
    const [activeTab, setActiveTab] = useState<'steps' | 'tree'>('steps');
    const runRef = useRef<ExecutionRun | null>(null);

    // Phase 11 Track 2 — flip to new AgentLoop layout per-run when on.
    const agentLoopEnabled = useFeatureFlag('agent_loop.enabled', {
        defaultValue: false,
        runMeta:
            (run as any)?.input_data?.feature_flags as
                | Record<string, boolean | undefined>
                | undefined,
    });

    // Refinement state
    const [showRefinePanel, setShowRefinePanel] = useState(false);
    const [refineFeedback, setRefineFeedback] = useState('');
    const [refining, setRefining] = useState(false);
    const [refineError, setRefineError] = useState('');

    // Update ref whenever run changes
    useEffect(() => {
        runRef.current = run;
    }, [run]);

    useEffect(() => {
        fetchRun();
    }, [id]);

    // Set up polling interval only once
    useEffect(() => {
        const interval = setInterval(() => {
            if (runRef.current?.status === RunStatus.RUNNING || runRef.current?.status === RunStatus.PENDING || (runRef.current?.status as string) === 'PAUSED' || (runRef.current?.status as string) === 'RESUMING' || runRef.current?.status === RunStatus.REFINING) {
                fetchRun();
            }
        }, 3000);
        return () => clearInterval(interval);
    }, [id]); // Only recreate if execution ID changes

    const fetchRun = async () => {
        try {
            const { data } = await apiClient.get<ExecutionRun>(`/ai/executions/${id}`);
            setRun(data);
        } catch (error) {
            console.error('Failed to fetch execution:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleRetry = async () => {
        if (!run || retrying) return;
        setRetrying(true);
        try {
            const { data } = await apiClient.post<ExecutionRun>(`/ai/executions/${run.id}/retry`);
            navigate(`/ai/executions/${data.id}`);
        } catch (error) {
            console.error('Retry failed:', error);
            alert('Failed to retry execution. See console for details.');
        } finally {
            setRetrying(false);
        }
    };

    const handleRefine = async () => {
        if (!run || refining || !refineFeedback.trim()) return;
        setRefining(true);
        setRefineError('');
        try {
            const { data } = await apiClient.post<ExecutionRun>(`/ai/executions/${run.id}/refine`, {
                feedback: refineFeedback.trim(),
            });
            navigate(`/ai/executions/${data.id}`);
        } catch (error: any) {
            console.error('Refine failed:', error);
            setRefineError(error.response?.data?.detail || 'Refinement failed. See console for details.');
        } finally {
            setRefining(false);
        }
    };

    // Helper to extract artifact path from a run (delegates to shared function in TraceNode)
    const getArtifactPath = (run: ExecutionRun): string | null => {
        const scanStr = (s: string): string | null => {
            if (!s) return null;
            // Pattern 1: Auto-registered artifact download URL: /api/v1/artifacts/{uuid}/download or /api/v1/ai/artifacts/{uuid}/download
            const apiArtifactMatch = s.match(/\/api\/v1\/(?:ai\/)?artifacts\/([0-9a-f-]{36})\/download/);
            if (apiArtifactMatch) {
                const fnMatch = s.match(/[•\-]\s*([\w][\w .()-]+\.(?:pptx|docx|xlsx|pdf|csv|html|png|jpg|svg))\s*\(/i);
                const filename = fnMatch ? fnMatch[1].trim() : 'document';
                return `__artifact_api__${apiArtifactMatch[1]}__${filename}`;
            }
            // Pattern 2: Absolute path with artifact/
            const extPattern = new RegExp(`\\/[^\\s"']*\\/artifact\\/([^\\s"']+\\.${DOCUMENT_EXTENSIONS})`);
            const absMatch = s.match(extPattern);
            if (absMatch) return `artifact/${absMatch[1]}`;
            // Pattern 3: Relative artifact path
            const relPattern = new RegExp(`artifact\\/([^\\s"']+\\.${DOCUMENT_EXTENSIONS})`);
            const relMatch = s.match(relPattern);
            if (relMatch) return `artifact/${relMatch[1]}`;
            // Pattern 4: Legacy /tmp path
            const tmpMatch = s.match(/\/tmp\/research_reports\/[a-zA-Z0-9_.-]+\.pdf/);
            if (tmpMatch) return tmpMatch[0];
            return null;
        };

        const { result_data: resultData, tool_logs: toolLogs } = run;
        if (resultData?.pdf_path) return scanStr(resultData.pdf_path) || resultData.pdf_path;
        if (resultData?.file_path) return scanStr(resultData.file_path) || resultData.file_path;
        if (resultData?.document_path) return scanStr(resultData.document_path) || resultData.document_path;

        if (toolLogs) {
            for (const log of toolLogs) {
                if (log.output_result) {
                    const raw = typeof log.output_result === 'string'
                        ? log.output_result
                        : JSON.stringify(log.output_result);
                    try {
                        const parsed = JSON.parse(raw);
                        if (parsed.download_url) return scanStr(parsed.download_url) || parsed.download_url;
                        if (parsed.document_path) return scanStr(parsed.document_path) || parsed.document_path;
                        if (parsed.pdf_path) return scanStr(parsed.pdf_path) || parsed.pdf_path;
                        if (parsed.file_path) return scanStr(parsed.file_path) || parsed.file_path;
                    } catch { }
                    const found = scanStr(raw);
                    if (found) return found;
                }
            }
        }

        if (resultData?.output) {
            const raw = typeof resultData.output === 'string'
                ? resultData.output
                : JSON.stringify(resultData.output);
            const found = scanStr(raw);
            if (found) return found;
        }

        return null;
    };

    // Recursively find artifact in the entire tree
    const findArtifactInTree = (run: ExecutionRun): string | null => {
        const path = getArtifactPath(run);
        if (path) return path;

        if (run.child_runs) {
            for (const child of run.child_runs) {
                const childPath = findArtifactInTree(child);
                if (childPath) return childPath;
            }
        }
        return null;
    };

    const globalArtifactPath = run ? findArtifactInTree(run) : null;
    const globalArtifactUrl = globalArtifactPath
        ? globalArtifactPath.startsWith('__artifact_api__')
            ? (() => {
                const parts = globalArtifactPath.replace('__artifact_api__', '').split('__');
                return `/api/v1/artifacts/${parts[0]}/download`;
              })()
            : globalArtifactPath.startsWith('artifact/')
                ? `/${globalArtifactPath}`
                : globalArtifactPath.includes('/artifact/')
                    ? `/artifact/${globalArtifactPath.split('/artifact/')[1]}`
                    : `/reports/${globalArtifactPath.split('/').pop()}`
        : null;
    const globalArtifactFilename = (() => {
        if (!globalArtifactPath) return 'document';
        if (globalArtifactPath.startsWith('__artifact_api__')) {
            const parts = globalArtifactPath.replace('__artifact_api__', '').split('__');
            return parts[1] || 'document';
        }
        return globalArtifactPath.split('/').pop() || 'document';
    })();

    // ── Issue 2: Flatten child entity steps into the Step Timeline ──────────
    // Recursively collect steps from child_runs with entity context
    const flattenChildSteps = (childRuns: ExecutionRun[]): StepResult[] => {
        const flattened: StepResult[] = [];
        for (const child of childRuns) {
            const entityLabel = `${child.entity?.type || 'CHILD'}: ${child.entity?.name || 'Unknown'}`;
            // Add a separator/header step for this child entity
            flattened.push({
                step: `── ${entityLabel} ──`,
                step_id: `__child_header_${child.id}`,
                type: child.entity?.type || 'CHILD_ENTITY',
                output: `Status: ${child.status}${child.execution_time_ms ? ` | Duration: ${(child.execution_time_ms / 1000).toFixed(1)}s` : ''}`,
            });
            // Add the child's own steps
            const childSteps: StepResult[] = child.result_data?.steps || [];
            for (const cs of childSteps) {
                flattened.push({
                    ...cs,
                    step: `  └ ${cs.step || 'Unnamed'}`,
                    step_id: cs.step_id ? `${child.id}_${cs.step_id}` : undefined,
                });
            }
            // Recurse into grandchildren
            if (child.child_runs && child.child_runs.length > 0) {
                flattened.push(...flattenChildSteps(child.child_runs));
            }
        }
        return flattened;
    };

    // Recursively collect LLM logs from child runs
    const collectChildLLMLogs = (childRuns: ExecutionRun[]): LLMInteractionLog[] => {
        const logs: LLMInteractionLog[] = [];
        for (const child of childRuns) {
            if (child.llm_logs) logs.push(...child.llm_logs);
            if (child.child_runs) logs.push(...collectChildLLMLogs(child.child_runs));
        }
        return logs;
    };

    // Extract steps from result_data + child runs
    const parentSteps: StepResult[] = run?.result_data?.steps || [];
    const childSteps: StepResult[] = run?.child_runs && run.child_runs.length > 0
        ? flattenChildSteps(run.child_runs)
        : [];
    const steps: StepResult[] = [...parentSteps, ...childSteps];

    // Aggregate LLM logs from parent + all child runs
    const parentLLMLogs: LLMInteractionLog[] = run?.llm_logs || [];
    const childLLMLogs: LLMInteractionLog[] = run?.child_runs
        ? collectChildLLMLogs(run.child_runs)
        : [];
    const llmLogs: LLMInteractionLog[] = [...parentLLMLogs, ...childLLMLogs];
    const toolLogs: ToolInteractionLog[] = run?.tool_logs || [];

    // Get the selected step details
    const selectedStepData = selectedStep
        ? steps.find(s => s.step === selectedStep)
        : null;

    // Get CORTEX tree ID from context
    const cortexTreeId = run?.context_state?.__cortex_tree_id__;

    if (loading) return (
        <div className="loading-container">
            <Brain size={48} className="pulse" color="var(--color-secondary)" />
            <div className="loading-text">Retracing Neuronal Path...</div>
        </div>
    );
    if (!run) return <div className="error-message">Execution not found.</div>;

    // Phase 11 Track 2: render the new AgentLoop layout when the
    // run's company has the `agent_loop.enabled` flag on.
    if (agentLoopEnabled) {
        const streamUrl = `${_API_BASE}/ai/executions/${run.id}/stream`;
        return (
            <div className="page-container execution-detail-page">
                <header className="page-header">
                    <div className="flex items-center gap-6">
                        <JellyButton variant="ghost" onClick={() => navigate('/ai/executions')} className="p-2">
                            <ArrowLeft size={24} />
                        </JellyButton>
                        <div>
                            <h1>Agent Loop</h1>
                            <p>{run.entity?.name} • Run ID: {run.id.slice(0, 12)} • status: {run.status}</p>
                        </div>
                    </div>
                </header>
                <AgentLoopExecutionDetail runId={run.id} streamUrl={streamUrl} />
            </div>
        );
    }

    return (
        <div className="page-container execution-detail-page">
            <header className="page-header">
                <div className="flex items-center gap-6">
                    <JellyButton variant="ghost" onClick={() => navigate('/ai/executions')} className="p-2">
                        <ArrowLeft size={24} />
                    </JellyButton>
                    <div>
                        <h1>Neural Trace Archive</h1>
                        <p>{run.entity?.name} • Deployment ID: {run.id.slice(0, 12)}</p>
                    </div>
                </div>
                <div className="flex items-center gap-4">
                    {/* Retry Button for FAILED runs */}
                    {run.status === RunStatus.FAILED && (
                        <JellyButton
                            variant="secondary"
                            size="md"
                            onClick={handleRetry}
                            disabled={retrying}
                            className="flex items-center gap-2"
                        >
                            <RefreshCw size={18} className={retrying ? 'spin' : ''} />
                            {retrying ? 'Retrying...' : 'Retry Execution'}
                        </JellyButton>
                    )}

                    {/* Refine Button for COMPLETED runs */}
                    {run.status === RunStatus.COMPLETED && (
                        <JellyButton
                            variant="secondary"
                            size="md"
                            onClick={() => setShowRefinePanel(!showRefinePanel)}
                            className="flex items-center gap-2 refine-trigger-btn"
                        >
                            <Sparkles size={18} />
                            {showRefinePanel ? 'Cancel Refine' : 'Refine Output'}
                        </JellyButton>
                    )}

                    {/* CORTEX Tree Link */}
                    {cortexTreeId && (
                        <JellyButton
                            variant="ghost"
                            size="md"
                            onClick={() => navigate(`/ai/cortex/${cortexTreeId}`)}
                            className="flex items-center gap-2"
                        >
                            <Brain size={18} /> CORTEX Tree
                        </JellyButton>
                    )}

                    {globalArtifactUrl && (
                        <JellyButton
                            variant="primary"
                            size="md"
                            className="flex items-center gap-2"
                            onClick={() => downloadArtifactFile(globalArtifactUrl!, globalArtifactFilename)}
                        >
                            <Download size={18} />
                            Download {globalArtifactFilename}
                        </JellyButton>
                    )}
                    <div className={`badge ${run.status === RunStatus.COMPLETED ? 'badge-ready' : run.status === RunStatus.FAILED ? 'badge-failed' : (run.status as string) === 'PAUSED' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-blue-500/20 text-blue-400'} px-6 py-3 text-sm font-bold tracking-widest`}>
                        {run.status.toUpperCase()}
                    </div>
                </div>
            </header>

            {/* ── Refine Panel ─────────────────────────────────────────── */}
            {showRefinePanel && run.status === RunStatus.COMPLETED && (
                <div className="refine-panel-wrapper">
                    <GlassCard className="refine-panel">
                        <div className="refine-panel-header">
                            <div className="refine-panel-title">
                                <Sparkles size={20} className="text-amber-400" />
                                <h3>Refine This Output</h3>
                            </div>
                            <p className="refine-panel-desc">
                                Describe what you'd like to change. The system will intelligently
                                determine which steps need re-running and reuse cached results for the rest.
                            </p>
                        </div>
                        <div className="refine-input-area">
                            <textarea
                                className="refine-textarea"
                                placeholder="e.g., 'Make the title font bigger and use a blue color scheme' or 'Add a summary section at the beginning'..."
                                value={refineFeedback}
                                onChange={(e) => setRefineFeedback(e.target.value)}
                                rows={3}
                            />
                            <JellyButton
                                roseGold
                                onClick={handleRefine}
                                disabled={refining || !refineFeedback.trim()}
                                className="refine-submit-btn"
                            >
                                {refining ? (
                                    <><RefreshCw size={16} className="spin" /> Analyzing...</>
                                ) : (
                                    <><Send size={16} /> Refine</>
                                )}
                            </JellyButton>
                        </div>
                        {refineError && (
                            <div className="refine-error">
                                <AlertTriangle size={14} />
                                {refineError}
                            </div>
                        )}
                        {/* Show reused vs re-run info */}
                        {run.result_data?.steps && (
                            <div className="refine-step-info">
                                <span className="refine-info-label">Pipeline steps:</span>
                                {(run.result_data.steps as any[]).map((s: any, i: number) => (
                                    <span key={i} className={`refine-step-chip ${s.reused ? 'reused' : ''}`}>
                                        {s.step || `Step ${i + 1}`}
                                    </span>
                                ))}
                            </div>
                        )}
                    </GlassCard>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
                <div className="lg:col-span-3">
                    {/* Tab Switcher */}
                    <div className="tab-switcher">
                        <button
                            className={`tab-btn ${activeTab === 'steps' ? 'active' : ''}`}
                            onClick={() => setActiveTab('steps')}
                        >
                            <Activity size={16} /> Step Timeline
                        </button>
                        <button
                            className={`tab-btn ${activeTab === 'tree' ? 'active' : ''}`}
                            onClick={() => setActiveTab('tree')}
                        >
                            <Layers size={16} /> Invocation Tree
                        </button>
                    </div>

                    {/* Step Timeline Tab */}
                    {activeTab === 'steps' && (
                        <GlassCard className="p-8">
                            {steps.length > 0 ? (
                                <div className="step-timeline-layout">
                                    <StepTimeline
                                        steps={steps}
                                        llmLogs={llmLogs}
                                        toolLogs={toolLogs}
                                        selectedStep={selectedStep}
                                        onSelectStep={setSelectedStep}
                                    />
                                    {selectedStepData && (
                                        <StepDetailPanel
                                            step={selectedStepData}
                                            llmLogs={llmLogs}
                                            onClose={() => setSelectedStep(null)}
                                        />
                                    )}
                                </div>
                            ) : run.child_runs && run.child_runs.length > 0 ? (
                                <div className="empty-steps">
                                    <Layers size={32} className="text-tertiary" />
                                    <p>
                                        This execution delegated work to {run.child_runs.length} child entities.
                                        Switch to the <strong>Invocation Tree</strong> tab to see their full execution traces.
                                    </p>
                                    <JellyButton variant="secondary" size="sm" onClick={() => setActiveTab('tree')}>
                                        <Layers size={16} /> View Invocation Tree
                                    </JellyButton>
                                </div>
                            ) : (
                                <div className="empty-steps">
                                    <Clock size={32} className="text-tertiary" />
                                    <p>
                                        {run.status === RunStatus.RUNNING || run.status === RunStatus.PENDING
                                            ? 'Execution in progress — steps will appear as they complete...'
                                            : 'No step data available for this execution.'}
                                    </p>
                                </div>
                            )}

                            {/* Error display */}
                            {run.error_message && (
                                <div className="execution-error-banner">
                                    <AlertTriangle size={18} />
                                    <div>
                                        <strong>Execution Failed</strong>
                                        <p>{run.error_message}</p>
                                    </div>
                                </div>
                            )}
                        </GlassCard>
                    )}

                    {/* Invocation Tree Tab */}
                    {activeTab === 'tree' && (
                        <GlassCard className="p-8">
                            <div className="flex items-center gap-3 mb-8">
                                <Layers size={24} className="text-rose-gold" />
                                <h2 className="text-2xl font-black italic uppercase tracking-tighter">Hierarchical Invocation Tree</h2>
                            </div>
                            <div className="trace-container">
                                <TraceNode run={run} depth={0} />
                            </div>
                        </GlassCard>
                    )}
                </div>

                <div className="space-y-8 operational-context-card">
                    <GlassCard className="p-8">
                        <h2 className="text-lg font-bold mb-8 flex items-center gap-2 border-b border-white/5 pb-4">
                            <Activity size={18} className="text-rose-gold" />
                            Operational Context
                        </h2>
                        <div className="space-y-6">
                            <div className="context-item">
                                <label className="context-label">Timeline</label>
                                <span className="context-value">{parseServerDate(run.created_at).toLocaleString()}</span>
                            </div>

                            <div className="grid grid-cols-1 gap-4">
                                <div className="context-item">
                                    <label className="context-label">Deployment Status</label>
                                    <div className="flex items-center gap-2 mt-1">
                                        <div className={`w-2 h-2 rounded-full ${run.status === RunStatus.COMPLETED ? 'bg-success' : 'bg-error'} animate-pulse`} />
                                        <span className="text-sm font-bold uppercase tracking-widest">{run.status}</span>
                                    </div>
                                </div>
                            </div>

                            {run.execution_time_ms && (
                                <div className="context-item">
                                    <label className="context-label">Duration</label>
                                    <span className="context-value">
                                        {run.execution_time_ms >= 60000
                                            ? `${Math.floor(run.execution_time_ms / 60000)}m ${Math.round((run.execution_time_ms % 60000) / 1000)}s`
                                            : `${(run.execution_time_ms / 1000).toFixed(1)}s`}
                                    </span>
                                </div>
                            )}

                            <div className="grid grid-cols-2 gap-4">
                                <div className="context-item border-l-2 border-rose-gold">
                                    <label className="context-label">Billed Amount</label>
                                    <span className="text-xl font-black text-rose-gold">
                                        ${run.billed_amount != null ? run.billed_amount.toFixed(4) : run.total_cost_usd.toFixed(4)}
                                    </span>
                                    {/* Transparency: show the raw provider cost beside the
                                        billed charge so the platform markup is visible
                                        (DOC_FACTORY_REDESIGN.md §5.3). */}
                                    {run.billed_amount != null &&
                                        Math.abs(run.billed_amount - run.total_cost_usd) > 0.0001 && (
                                        <span
                                            className="context-value block mt-1 opacity-70"
                                            title="Raw provider cost before platform markup"
                                        >
                                            raw ${run.total_cost_usd.toFixed(4)}
                                            {run.total_cost_usd > 0 && (
                                                <> · {(run.billed_amount / run.total_cost_usd).toFixed(2)}×</>
                                            )}
                                        </span>
                                    )}
                                </div>
                                <div className="context-item border-l-2 border-secondary">
                                    <label className="context-label">Tokens</label>
                                    <span className="text-xl font-black text-secondary">{run.total_tokens.toLocaleString()}</span>
                                </div>
                            </div>

                            {/* Child entity count */}
                            {run.child_runs && run.child_runs.length > 0 && (
                                <div className="context-item">
                                    <label className="context-label">Child Entities</label>
                                    <span className="context-value">{run.child_runs.length} entities invoked</span>
                                </div>
                            )}

                            {/* Execution metrics */}
                            <div className="context-item">
                                <label className="context-label">Steps Completed</label>
                                <span className="context-value">{steps.length}</span>
                            </div>

                            <div className="context-item">
                                <label className="context-label">LLM Calls</label>
                                <span className="context-value">{llmLogs.length}</span>
                            </div>

                            {cortexTreeId && (
                                <div className="context-item">
                                    <label className="context-label">CORTEX Tree</label>
                                    <span className="context-value cortex-link"
                                        onClick={() => navigate(`/ai/cortex/${cortexTreeId}`)}
                                    >
                                        {cortexTreeId.slice(0, 12)}...
                                    </span>
                                </div>
                            )}

                            <div className="context-item">
                                <label className="context-label">Input Sequence</label>
                                <pre className="mt-2">
                                    {JSON.stringify(run.input_data, null, 2)}
                                </pre>
                            </div>
                        </div>
                    </GlassCard>
                </div>
            </div>
        </div>
    );
};
