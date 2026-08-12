import React, { useState, useEffect } from 'react';
import {
    Brain, MessageSquare, Image as ImageIcon, Video, Mic,
    Music, Cuboid, Save, AlertCircle, Loader2, Route,
    ChevronDown, Trash2, Search
} from 'lucide-react';
import { GlassCard, JellyButton } from '@/components/ui';
import { aiConfigService, ModelTaskDefault } from '@/services/ai-config.service';
import { integrationService, Integration } from '@/services/integration.service';
import './AIModelConfigPage.css';

// Definition of all supported task types and their UI metadata
const TASK_TYPES = [
    { id: 'text_generation', name: 'Text Generation', icon: MessageSquare, category: 'llm', description: 'Standard completions, reasoning, and conversational agent responses.' },
    { id: 'thinking', name: 'Thinking (Reasoning)', icon: Brain, category: 'llm', description: 'Complex planning and chain-of-thought processing before answering.' },
    { id: 'embedding', name: 'Embedding', icon: Search, category: 'llm', description: 'Vector embedding generation for semantic search, memory retrieval, and similarity matching.' },
    { id: 'speech_to_speech', name: 'Live Streaming (Voice)', icon: Mic, category: 'realtime', description: 'Real-time WebSocket streaming models for low-latency voice AI.' },
    { id: 'text_to_image', name: 'Text to Image', icon: ImageIcon, category: 'image', description: 'Generating images from prompts.' },
    { id: 'image_to_image', name: 'Image to Image', icon: ImageIcon, category: 'image', description: 'Modifying images based on visual inputs and prompts.' },
    { id: 'text_to_speech', name: 'Text to Speech', icon: Mic, category: 'speech', description: 'Standard async TTS generation.' },
    { id: 'text_to_music', name: 'Audio/Music Generation', icon: Music, category: 'audio', description: 'Generating sound effects and background music.' },
    { id: 'text_to_video', name: 'Text to Video', icon: Video, category: 'video', description: 'Generating video sequences from text.' },
    { id: 'image_to_video', name: 'Image to Video', icon: Video, category: 'video', description: 'Animating still images.' },
    { id: 'audio_to_video', name: 'Audio to Video', icon: Video, category: 'video', description: 'Generating lip-sync or driven video from audio features.' },
    { id: 'text_to_3d', name: '3D Generation', icon: Cuboid, category: '3d', description: 'Generating 3D models and meshes from text prompts.' },
];

export const AIModelConfigPage: React.FC = () => {
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [successMessage, setSuccessMessage] = useState<string | null>(null);

    const [taskDefaults, setTaskDefaults] = useState<Record<string, ModelTaskDefault>>({});
    const [integrations, setIntegrations] = useState<Integration[]>([]);

    // Local changes before saving
    const [pendingChanges, setPendingChanges] = useState<Record<string, { integration_id: string, routing_mode: 'single' | 'router' }>>({});

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        setLoading(true);
        setError(null);
        try {
            const [defaultsData, integrationsData] = await Promise.all([
                aiConfigService.getTaskDefaults(),
                integrationService.getIntegrations()
            ]);

            // Map defaults by task_type for easy UI rendering
            const defaultsMap: Record<string, ModelTaskDefault> = {};
            defaultsData.forEach(d => {
                defaultsMap[d.task_type] = d;
            });

            setTaskDefaults(defaultsMap);
            setIntegrations(integrationsData);
        } catch (err: any) {
            setError('Failed to load AI configuration: ' + (err.message || String(err)));
        } finally {
            setLoading(false);
        }
    };

    const handleTaskChange = (taskType: string, field: 'integration_id' | 'routing_mode', value: string) => {
        setPendingChanges(prev => {
            const current = prev[taskType] || {
                integration_id: taskDefaults[taskType]?.integration_id || '',
                routing_mode: taskDefaults[taskType]?.routing_mode || 'single'
            };

            return {
                ...prev,
                [taskType]: {
                    ...current,
                    [field]: value
                }
            };
        });
    };

    const saveTaskDefault = async (taskType: string) => {
        const payload = pendingChanges[taskType];
        if (!payload || !payload.integration_id) return;

        setSaving(true);
        setError(null);
        setSuccessMessage(null);

        try {
            const saved = await aiConfigService.setTaskDefault({
                task_type: taskType,
                integration_id: payload.integration_id,
                routing_mode: payload.routing_mode
            });

            setTaskDefaults(prev => ({
                ...prev,
                [taskType]: saved
            }));

            // clear from pending
            const newPending = { ...pendingChanges };
            delete newPending[taskType];
            setPendingChanges(newPending);

            setSuccessMessage(`Saved configuration for ${TASK_TYPES.find(t => t.id === taskType)?.name}`);
            setTimeout(() => setSuccessMessage(null), 3000);
        } catch (err: any) {
            setError(`Failed to save configuration for ${taskType}: ` + (err.message || String(err)));
        } finally {
            setSaving(false);
        }
    };

    const clearTaskDefault = async (taskType: string) => {
        setSaving(true);
        setError(null);
        setSuccessMessage(null);

        try {
            await aiConfigService.deleteTaskDefault(taskType);

            setTaskDefaults(prev => {
                const updated = { ...prev };
                delete updated[taskType];
                return updated;
            });

            const newPending = { ...pendingChanges };
            delete newPending[taskType];
            setPendingChanges(newPending);

            setSuccessMessage(`Cleared configuration for ${TASK_TYPES.find(t => t.id === taskType)?.name}`);
            setTimeout(() => setSuccessMessage(null), 3000);
        } catch (err: any) {
            setError(`Failed to clear configuration for ${taskType}: ` + (err.message || String(err)));
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return (
            <div className="flex h-screen items-center justify-center">
                <Loader2 className="w-8 h-8 animate-spin text-rose-gold" />
            </div>
        );
    }

    return (
        <div className="page-container ai-config-page">
            <header className="page-header">
                <div>
                    <h1 className="flex items-center gap-3">
                        <Route className="text-rose-gold" />
                        AI Routing & Task Defaults
                    </h1>
                    <p className="mt-2 text-gray-400">
                        Configure which AI models from your Service Integrations will handle distinct reasoning and generation tasks system-wide.
                    </p>
                </div>
            </header>

            {error && (
                <GlassCard className="mb-6 border-red-500/30 bg-red-500/10 p-4 flex items-center gap-3 text-red-400">
                    <AlertCircle size={20} />
                    <p>{error}</p>
                </GlassCard>
            )}

            {successMessage && (
                <GlassCard className="mb-6 border-green-500/30 bg-green-500/10 p-4 flex items-center gap-3 text-green-400">
                    <AlertCircle size={20} />
                    <p>{successMessage}</p>
                </GlassCard>
            )}

            <div className="grid gap-6">
                {TASK_TYPES.map(task => {
                    const activeDefault = taskDefaults[task.id];
                    const pending = pendingChanges[task.id];

                    const currentIntegrationId = pending?.integration_id ?? activeDefault?.integration_id ?? '';
                    const currentMode = pending?.routing_mode ?? activeDefault?.routing_mode ?? 'single';
                    const hasUnsavedChanges = !!pending;

                    return (
                        <GlassCard key={task.id} className="ai-task-card p-6 border-white/10 hover:border-white/20">
                            <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">

                                <div className="flex items-start gap-4 flex-1">
                                    <div className="ai-task-icon flex-shrink-0">
                                        <task.icon size={20} />
                                    </div>
                                    <div>
                                        <h3 className="text-xl font-bold text-white mb-1">{task.name}</h3>
                                        <p className="text-sm text-gray-400 mb-2">{task.description}</p>
                                        <span className="inline-block px-2 py-0.5 rounded text-xs tracking-wider bg-white/5 border border-white/10 text-gray-500 uppercase">
                                            {task.category}
                                        </span>
                                    </div>
                                </div>

                                <div className="flex flex-col gap-4 flex-1 max-w-md w-full">
                                    {/* Provider Selection */}
                                    <div className="space-y-1">
                                        <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Default Integration</label>
                                        <div className="relative">
                                            <select
                                                value={currentIntegrationId}
                                                onChange={(e) => handleTaskChange(task.id, 'integration_id', e.target.value)}
                                                className="w-full bg-black/40 border border-white/10 rounded-lg py-2.5 pl-3 pr-10 text-white text-sm focus:border-rose-gold/50 focus:ring-1 focus:ring-rose-gold/50 appearance-none outline-none transition-all"
                                            >
                                                <option value="">-- Not Configured --</option>
                                                {integrations
                                                    // .filter(i => !task.category || i.service_category?.includes(task.category)) // Optional filtering
                                                    .map(int => (
                                                        <option key={int.id} value={int.id}>
                                                            {int.provider_name} {int.model_name ? `(${int.model_name})` : ''} — {int.service_sku || int.component_type}
                                                        </option>
                                                    ))}
                                            </select>
                                            <ChevronDown size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
                                        </div>
                                    </div>

                                    {/* Routing Mode */}
                                    <div className="space-y-1">
                                        <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Routing Mode</label>
                                        <div className="mode-toggle">
                                            <button
                                                className={currentMode === 'single' ? 'active' : ''}
                                                onClick={() => handleTaskChange(task.id, 'routing_mode', 'single')}
                                            >
                                                Strict Single
                                            </button>
                                            <button
                                                className={currentMode === 'router' ? 'active' : ''}
                                                onClick={() => handleTaskChange(task.id, 'routing_mode', 'router')}
                                                disabled // Disabled temporarily for beta until full router capability is exposed to UI
                                            >
                                                Fallback Router
                                            </button>
                                        </div>
                                    </div>

                                    {/* Action row */}
                                    <div className="flex justify-between items-center pt-2">
                                        {activeDefault && !hasUnsavedChanges ? (
                                            <span className="text-xs text-green-400 flex items-center gap-1">
                                                <AlertCircle size={12} /> Active Configuration
                                            </span>
                                        ) : hasUnsavedChanges ? (
                                            <span className="text-xs text-amber-400 flex items-center gap-1">
                                                <AlertCircle size={12} /> Unsaved Changes
                                            </span>
                                        ) : (
                                            <span className="text-xs text-gray-500">
                                                None configured
                                            </span>
                                        )}

                                        <div className="flex gap-2">
                                            {activeDefault && (
                                                <button
                                                    onClick={() => clearTaskDefault(task.id)}
                                                    className="p-2 text-gray-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
                                                    title="Clear default"
                                                    disabled={saving}
                                                >
                                                    <Trash2 size={16} />
                                                </button>
                                            )}

                                            <JellyButton
                                                roseGold
                                                onClick={() => saveTaskDefault(task.id)}
                                                disabled={!hasUnsavedChanges || !currentIntegrationId || saving}
                                                className="py-1.5 px-3 text-sm"
                                            >
                                                {saving && hasUnsavedChanges ? <Loader2 size={14} className="animate-spin mr-1" /> : <Save size={14} className="mr-1" />} Save
                                            </JellyButton>
                                        </div>
                                    </div>
                                </div>

                            </div>
                        </GlassCard>
                    );
                })}
            </div>
        </div>
    );
};
