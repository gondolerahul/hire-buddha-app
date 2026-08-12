import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect } from 'react';
import { GlassCard, JellyButton } from '@/components/ui';
import { CheckCircle, XCircle, Clock, Shield } from 'lucide-react';
import { apiClient } from '@/services/api.client';
import { HumanApproval } from '@/types';
import './HITLPanel.css';

export const HITLPanel: React.FC = () => {
    const [approvals, setApprovals] = useState<HumanApproval[]>([]);
    const [loading, setLoading] = useState(true);

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
        try {
            await apiClient.post(`/ai/approvals/${approvalId}/respond`, {
                status,
                notes: `Responded via HITL Dashboard`
            });
            setApprovals(prev => prev.filter(a => a.id !== approvalId));
        } catch (error) {
            console.error('Failed to respond to approval:', error);
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

            <div className="standard-grid">
                {approvals.length === 0 ? (
                    <GlassCard className="col-span-full py-20 opacity-30 flex flex-col items-center">
                        <CheckCircle size={64} className="mb-4 text-green-400" />
                        <p>All neural systems are operating within nominal autonomous boundaries.</p>
                    </GlassCard>
                ) : (
                    approvals.map(approval => (
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

                                <div className="space-y-4 mb-8">
                                    <div className="flex items-center justify-between text-xs text-tertiary">
                                        <span>EXECUTION REF</span>
                                        <span className="text-secondary font-mono bg-white/5 px-2 py-1 rounded">{approval.run_id.slice(0, 12)}</span>
                                    </div>
                                    <div className="flex items-center justify-between text-xs text-tertiary">
                                        <span>REQUESTED AT</span>
                                        <div className="flex items-center gap-1.5 text-secondary">
                                            <Clock size={12} />
                                            {parseServerDate(approval.requested_at).toLocaleTimeString()}
                                        </div>
                                    </div>
                                </div>
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
                    ))
                )}
            </div>
        </div>
    );
};
