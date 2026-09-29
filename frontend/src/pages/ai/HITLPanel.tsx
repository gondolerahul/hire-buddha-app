import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { GlassCard, JellyButton } from '@/components/ui';
import { CheckCircle, XCircle, Clock, Shield, ChevronDown, ChevronRight } from 'lucide-react';
import { apiClient } from '@/services/api.client';
import { HumanApproval, HITLContextSnapshot } from '@/types';
import './HITLPanel.css';

/** One labelled block of snapshot text, kept readable for long prompts and outputs. */
const SnapshotField: React.FC<{ label: string; value?: string }> = ({ label, value }) =>
    value ? (
        <div>
            <div className="text-[10px] uppercase tracking-widest text-tertiary mb-1">{label}</div>
            <pre className="hitl-snapshot-text">{value}</pre>
        </div>
    ) : null;

/** What the agent is about to do (BEFORE) or has just produced (AFTER). */
const SnapshotDetails: React.FC<{ snapshot: HITLContextSnapshot }> = ({ snapshot }) => (
    <div className="space-y-3 mt-3">
        <SnapshotField
            label={snapshot.phase === 'AFTER' ? 'Step prompt (ran)' : 'Step prompt (about to run)'}
            value={snapshot.step_prompt}
        />
        <SnapshotField label="Step output" value={snapshot.step_output} />
        <SnapshotField label="Step description" value={snapshot.step_description} />
        <SnapshotField label="Run input" value={snapshot.run_input} />
        {snapshot.run_cost_usd !== undefined && (
            <div className="flex items-center justify-between text-xs text-tertiary">
                <span>RUN COST SO FAR</span>
                <span className="text-secondary font-mono">${snapshot.run_cost_usd.toFixed(4)}</span>
            </div>
        )}
    </div>
);

export const HITLPanel: React.FC = () => {
    const [approvals, setApprovals] = useState<HumanApproval[]>([]);
    const [loading, setLoading] = useState(true);
    const [expanded, setExpanded] = useState<Set<string>>(new Set());
    const [error, setError] = useState<string | null>(null);

    const toggleExpanded = (id: string) =>
        setExpanded(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });

    useEffect(() => {
        fetchPendingApprovals();
        const interval = setInterval(fetchPendingApprovals, 10000);
        return () => clearInterval(interval);
    }, []);

    const fetchPendingApprovals = async () => {
        try {
            const { data } = await apiClient.get<HumanApproval[]>('/ai/approvals/pending');
            setApprovals(data);
        } catch (error) {
            console.error('Failed to fetch approvals:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleRespond = async (approvalId: string, status: 'APPROVED' | 'REJECTED') => {
        setError(null);
        try {
            await apiClient.post(`/ai/approvals/${approvalId}/respond`, {
                status,
                notes: `Responded via HITL Dashboard`
            });
            setApprovals(prev => prev.filter(a => a.id !== approvalId));
        } catch (err: any) {
            const detail = err?.response?.data?.detail;
            setError(typeof detail === 'string' ? detail : 'Could not record your decision. Please try again.');
            // Already answered, or the run stopped waiting: the list is stale.
            if (err?.response?.status === 409 || err?.response?.status === 404) fetchPendingApprovals();
        }
    };

    if (loading) return <div className="loading">Authorized Personnel Required...</div>;

    return (
        <div className="page-container hitl-panel">
            <header className="page-header">
                <div>
                    <h1>Guardian Oversight</h1>
                    <p>Decision center for Human-in-the-Loop interventions</p>
                </div>
                <div className="badge badge-purple px-6 py-2 text-sm font-bold tracking-widest">
                    {approvals.length} PENDING BLOCKS
                </div>
            </header>

            {error && (
                <GlassCard className="mb-6 p-4 border border-red-400/40 text-red-300">
                    <div className="flex items-center justify-between gap-4" role="alert">
                        <span>{error}</span>
                        <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
                            <XCircle size={16} />
                        </button>
                    </div>
                </GlassCard>
            )}

            <div className="standard-grid">
                {approvals.length === 0 ? (
                    <GlassCard className="col-span-full py-20 opacity-30 flex flex-col items-center">
                        <CheckCircle size={64} className="mb-4 text-green-400" />
                        <p>All neural systems are operating within nominal autonomous boundaries.</p>
                    </GlassCard>
                ) : (
                    approvals.map(approval => {
                        const snapshot = approval.context_snapshot || {};
                        const isOpen = expanded.has(approval.id);
                        const hasDetails = Boolean(
                            snapshot.step_prompt || snapshot.step_output ||
                            snapshot.run_input || snapshot.step_description
                        );
                        return (
                            <GlassCard key={approval.id} className="flex flex-col h-full" hover>
                                <div className="p-6 flex-1">
                                    <div className="flex items-start gap-4 mb-6">
                                        <div className="bg-red-500/10 p-3 rounded-lg text-red-400">
                                            <Shield size={24} />
                                        </div>
                                        <div className="min-w-0 flex-1">
                                            <h3 className="mb-1 truncate text-lg">Checkpoint Required</h3>
                                            <div className="text-xs text-tertiary font-mono truncate">{approval.checkpoint_trigger}</div>
                                        </div>
                                    </div>

                                    {snapshot.message && (
                                        <p className="text-sm text-secondary mb-4">{snapshot.message}</p>
                                    )}

                                    <div className="space-y-4 mb-6">
                                        {snapshot.entity_name && (
                                            <div className="flex items-center justify-between text-xs text-tertiary">
                                                <span>AGENT</span>
                                                <span className="text-secondary truncate ml-4">{snapshot.entity_name}</span>
                                            </div>
                                        )}
                                        {snapshot.step_name && (
                                            <div className="flex items-center justify-between text-xs text-tertiary">
                                                <span>STEP</span>
                                                <span className="text-secondary truncate ml-4">{snapshot.step_name}</span>
                                            </div>
                                        )}
                                        {snapshot.tool_id && (
                                            <div className="flex items-center justify-between text-xs text-tertiary">
                                                <span>TOOL</span>
                                                <span className="text-secondary font-mono bg-white/5 px-2 py-1 rounded">{snapshot.tool_id}</span>
                                            </div>
                                        )}
                                        <div className="flex items-center justify-between text-xs text-tertiary">
                                            <span>EXECUTION REF</span>
                                            <Link
                                                to={`/ai/executions/${approval.run_id}`}
                                                className="text-secondary font-mono bg-white/5 px-2 py-1 rounded hover:text-white"
                                            >
                                                {approval.run_id.slice(0, 12)}
                                            </Link>
                                        </div>
                                        <div className="flex items-center justify-between text-xs text-tertiary">
                                            <span>REQUESTED AT</span>
                                            <div className="flex items-center gap-1.5 text-secondary">
                                                <Clock size={12} />
                                                {parseServerDate(approval.requested_at).toLocaleTimeString()}
                                            </div>
                                        </div>
                                    </div>

                                    {hasDetails && (
                                        <div className="mb-2">
                                            <button
                                                type="button"
                                                onClick={() => toggleExpanded(approval.id)}
                                                className="flex items-center gap-1 text-xs text-secondary hover:text-white"
                                                aria-expanded={isOpen}
                                            >
                                                {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                                {isOpen ? 'Hide details' : 'Show what is being approved'}
                                            </button>
                                            {isOpen && <SnapshotDetails snapshot={snapshot} />}
                                        </div>
                                    )}
                                </div>

                                <div className="p-4 pt-0 border-t border-white/5 mt-auto grid grid-cols-2 gap-3">
                                    <JellyButton
                                        roseGold
                                        onClick={() => handleRespond(approval.id, 'APPROVED')}
                                        className="w-full"
                                    >
                                        <CheckCircle size={16} /> Authorize
                                    </JellyButton>
                                    <JellyButton
                                        variant="ghost"
                                        onClick={() => handleRespond(approval.id, 'REJECTED')}
                                        className="w-full text-red-500 hover:text-red-400"
                                    >
                                        <XCircle size={16} /> Block Cycle
                                    </JellyButton>
                                </div>
                            </GlassCard>
                        );
                    })
                )}
            </div>
        </div>
    );
};
