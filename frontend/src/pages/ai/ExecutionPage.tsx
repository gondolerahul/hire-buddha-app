import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { GlassCard, GlassInput, JellyButton } from '@/components/ui';
import { Play, ArrowLeft, Loader, Cpu, Zap, Activity, Info, AlertTriangle } from 'lucide-react';
import { apiClient } from '@/services/api.client';
import { HierarchicalEntity } from '@/types';
import './ExecutionPage.css';

export const ExecutionPage: React.FC = () => {
    const { id } = useParams<{ id: string }>();
    const navigate = useNavigate();

    const [entity, setEntity] = useState<HierarchicalEntity | null>(null);
    const [variables, setVariables] = useState<Record<string, string>>({});
    const [requiredVars, setRequiredVars] = useState<string[]>([]);

    const [executing, setExecuting] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        fetchDetails();
    }, [id]);

    const fetchDetails = async () => {
        try {
            const { data } = await apiClient.get<HierarchicalEntity>(`/ai/entities/${id}`);
            setEntity(data);

            const allVars = new Set<string>();
            // Extract variables from IO Contract if available (canonical source of user inputs)
            if (data.io_contract?.input_schema?.properties) {
                Object.keys(data.io_contract.input_schema.properties).forEach(key => {
                    allVars.add(key);
                });
            }

            // Extract variables from all prompt templates in the plan,
            // but EXCLUDE internal step references which are resolved at
            // runtime from previous step outputs.
            // 1. Match step_N and step_N_anything patterns
            // 2. Also exclude any variable that matches a step_id in the plan
            const stepRefPattern = /^step_\d+/;
            const steps = data.planning?.static_plan?.steps || [];
            const planStepIds = new Set(steps.map(s => s.step_id).filter(Boolean));

            steps.forEach(step => {
                const promptTemplate = step.target?.prompt_template;
                if (promptTemplate) {
                    const regex = /\{\{(\w+)\}\}/g;
                    const matches = promptTemplate.matchAll(regex);
                    for (const match of matches) {
                        // Only add user-facing variables, not internal step references
                        if (!stepRefPattern.test(match[1]) && !planStepIds.has(match[1])) {
                            allVars.add(match[1]);
                        }
                    }
                }
            });

            const varsArray = Array.from(allVars);
            setRequiredVars(varsArray);

            // Initialize variable state
            const initialVars: Record<string, string> = {};
            varsArray.forEach(v => initialVars[v] = '');
            setVariables(initialVars);
        } catch (error) {
            console.error('Failed to fetch details:', error);
            setError('Failed to load execution target');
        }
    };

    const handleExecute = async () => {
        setError('');
        setExecuting(true);

        try {
            const payload = {
                entity_id: id,
                input_data: variables,
            };

            const { data } = await apiClient.post('/ai/execute', payload);

            // Redirect to detail page with trace
            setTimeout(() => {
                navigate(`/ai/executions/${data.id}`);
            }, 1000);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Execution failed');
            setExecuting(false);
        }
    };

    const canExecute = requiredVars.every(v => variables[v]?.trim());

    if (!entity && !error) return (
        <div className="loading-container">
            <Cpu size={48} className="pulse" color="var(--color-primary)" />
            <div className="loading">Calibrating Synapses...</div>
        </div>
    );

    return (
        <div className="page-container execution-page">
            <header className="page-header">
                <div className="flex items-center gap-6">
                    <JellyButton variant="ghost" onClick={() => navigate(-1)} className="p-2">
                        <ArrowLeft size={24} />
                    </JellyButton>
                    <div>
                        <h1>Execute {entity?.name}</h1>
                        <p>Configure and launch your neural unit into the cluster</p>
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    <span className="badge badge-purple px-4 py-2">{entity?.type.toUpperCase()}</span>
                    <span className="badge border-white/10 px-4 py-2 text-tertiary">VERSION {entity?.version}</span>
                </div>
            </header>

            <div className="execution-grid">
                {/* Input Panel */}
                <GlassCard className="p-8">
                    <div className="flex items-center gap-3 mb-8">
                        <div className="p-3 bg-rose-gold/10 rounded-lg text-rose-gold">
                            <Activity size={24} />
                        </div>
                        <div>
                            <h2 className="text-xl font-bold">Deployment Parameters</h2>
                            <p className="text-sm text-tertiary">Required context for the entity's reasoning engine</p>
                        </div>
                    </div>

                    {requiredVars.length > 0 ? (
                        <div className="space-y-6">
                            {requiredVars.map((varName) => (
                                <GlassInput
                                    key={varName}
                                    label={varName.replace(/_/g, ' ').toUpperCase()}
                                    placeholder={`Enter context for ${varName}...`}
                                    value={variables[varName] || ''}
                                    onChange={(e) => setVariables({ ...variables, [varName]: e.target.value })}
                                    required
                                />
                            ))}
                        </div>
                    ) : (
                        <div className="py-12 flex flex-col items-center opacity-30">
                            <Zap size={48} className="mb-4" />
                            <p>No external parameters required for this unit.</p>
                        </div>
                    )}

                    <div className="mt-10 pt-8 border-t border-white/10">
                        <JellyButton
                            roseGold
                            onClick={handleExecute}
                            disabled={executing || !canExecute}
                            className="w-full py-4 text-lg"
                        >
                            {executing ? (
                                <>
                                    <Loader className="spin" size={24} />
                                    Synchronizing...
                                </>
                            ) : (
                                <>
                                    <Play size={20} />
                                    Launch Execution
                                </>
                            )}
                        </JellyButton>
                        {error && (
                            <div className="execution-error-panel" id="execution-error">
                                <div className="error-header">
                                    <AlertTriangle size={18} />
                                    <span>Execution Blocked</span>
                                </div>
                                <div className="error-body">
                                    {error.split('\n').map((line, i) => (
                                        <div key={i} className={line.trim().startsWith('•') ? 'error-bullet' : 'error-line'}>
                                            {line}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </GlassCard>

                {/* Info Panel */}
                <GlassCard className="p-8 h-fit">
                    <div className="flex items-center gap-3 mb-8">
                        <div className="p-3 bg-blue-500/10 rounded-lg text-blue-400">
                            <Info size={24} />
                        </div>
                        <div>
                            <h2 className="text-xl font-bold">Execution Context</h2>
                            <p className="text-sm text-tertiary">Operational constraints and governance</p>
                        </div>
                    </div>

                    <div className="space-y-6">
                        <div className="p-4 rounded-xl bg-white/5 border border-white/5">
                            <label className="text-[10px] text-tertiary uppercase tracking-widest font-mono block mb-1">Reasoning Mode</label>
                            <span className="font-semibold text-rose-gold text-lg">{entity?.logic_gate?.reasoning_config?.reasoning_mode || 'STANDARD'}</span>
                        </div>

                        <div className="p-4 rounded-xl bg-white/5 border border-white/5">
                            <label className="text-[10px] text-tertiary uppercase tracking-widest font-mono block mb-1">Compute Resource</label>
                            <span className="font-medium text-secondary">{entity?.logic_gate?.reasoning_config?.model_name}</span>
                            <div className="text-xs text-tertiary mt-1 opacity-60">Provider: {entity?.logic_gate?.reasoning_config?.model_provider}</div>
                        </div>

                        {entity?.governance?.hitl_checkpoints && entity.governance.hitl_checkpoints.length > 0 && (
                            <div className="p-4 rounded-xl bg-red-400/5 border border-red-400/20">
                                <label className="text-[10px] text-red-400 uppercase tracking-widest font-bold block mb-1">Active Guardrails</label>
                                <div className="text-sm text-red-300">Human-in-the-loop enabled ({entity.governance.hitl_checkpoints.length} blocks)</div>
                            </div>
                        )}
                    </div>
                </GlassCard>
            </div>
        </div>
    );
};
