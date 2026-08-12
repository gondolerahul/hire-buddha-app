import { parseServerDate } from '@/utils/datetime';
/**
 * CortexExplorer — Memory Tree Management Page
 * 
 * Lists all CORTEX cognitive trees for the current company.
 * Provides actions to view/resume/suspend trees and navigate their structure.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { cortexService, CortexTree } from '@/services/cortex.service';
import { JellyButton } from '@/components/ui';
import { Brain, Play, Pause, Eye, TreePine, Clock, Hash, ChevronRight, Archive } from 'lucide-react';
import './CortexExplorer.css';

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
    active: { label: 'Active', color: '#22c55e', icon: <Play size={12} /> },
    suspended: { label: 'Suspended', color: '#f59e0b', icon: <Pause size={12} /> },
    complete: { label: 'Complete', color: '#6366f1', icon: <Eye size={12} /> },
    archived: { label: 'Archived', color: '#6b7280', icon: <Archive size={12} /> },
};

const TYPE_ICONS: Record<string, string> = {
    root: '🌳', knowledge: '📚', finding: '🔬', task: '📋', output: '📝', checkpoint: '📌',
};

export const CortexExplorer: React.FC = () => {
    const navigate = useNavigate();
    const [trees, setTrees] = useState<CortexTree[]>([]);
    const [loading, setLoading] = useState(true);
    const [statusFilter, setStatusFilter] = useState<string>('');

    useEffect(() => {
        loadTrees();
    }, [statusFilter]);

    const loadTrees = async () => {
        setLoading(true);
        try {
            const data = await cortexService.listTrees(undefined, statusFilter || undefined);
            setTrees(data);
        } catch (err) {
            console.error('Failed to load CORTEX trees:', err);
        } finally {
            setLoading(false);
        }
    };

    const handleSuspend = async (treeId: string, e: React.MouseEvent) => {
        e.stopPropagation();
        try {
            await cortexService.suspendTree(treeId);
            loadTrees();
        } catch (err) {
            console.error('Failed to suspend tree:', err);
        }
    };

    const handleResume = async (treeId: string, e: React.MouseEvent) => {
        e.stopPropagation();
        try {
            await cortexService.resumeTree(treeId);
            loadTrees();
        } catch (err) {
            console.error('Failed to resume tree:', err);
        }
    };

    const formatDate = (dateStr: string | null): string => {
        if (!dateStr) return '—';
        return parseServerDate(dateStr).toLocaleString('en-US', {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
        });
    };

    return (
        <div className="cortex-explorer">
            <div className="cortex-explorer-header">
                <div className="cortex-explorer-title">
                    <Brain size={28} />
                    <div>
                        <h1>CORTEX Memory Trees</h1>
                        <p>Persistent cognitive trees powering agent long-term memory and reasoning</p>
                    </div>
                </div>
                <div className="cortex-explorer-filters">
                    <select
                        value={statusFilter}
                        onChange={(e) => setStatusFilter(e.target.value)}
                        className="cortex-filter-select"
                    >
                        <option value="">All Statuses</option>
                        <option value="active">🟢 Active</option>
                        <option value="suspended">🟡 Suspended</option>
                        <option value="complete">🟣 Complete</option>
                        <option value="archived">⚪ Archived</option>
                    </select>
                </div>
            </div>

            {loading ? (
                <div className="cortex-loading">
                    <div className="cortex-loading-spinner" />
                    <p>Loading memory trees…</p>
                </div>
            ) : trees.length === 0 ? (
                <div className="cortex-empty">
                    <TreePine size={64} strokeWidth={1} />
                    <h2>No Memory Trees Yet</h2>
                    <p>CORTEX trees are automatically created when entities execute. Each execution generates a persistent cognitive tree.</p>
                    <p>Run an entity to see its memory tree appear here.</p>
                </div>
            ) : (
                <div className="cortex-tree-grid">
                    {trees.map(tree => {
                        const statusCfg = STATUS_CONFIG[tree.status] || STATUS_CONFIG.active;
                        return (
                            <div
                                key={tree.id}
                                className="cortex-tree-card"
                                onClick={() => navigate(`/cortex/trees/${tree.id}`)}
                            >
                                <div className="cortex-tree-card-header">
                                    <span
                                        className="cortex-status-badge"
                                        style={{ background: statusCfg.color + '22', color: statusCfg.color, borderColor: statusCfg.color + '44' }}
                                    >
                                        {statusCfg.icon} {statusCfg.label}
                                    </span>
                                    <span className="cortex-tree-id" title={tree.id}>
                                        {tree.id.slice(0, 8)}…
                                    </span>
                                </div>

                                <h3 className="cortex-tree-task">
                                    {tree.task_description || 'Untitled Task'}
                                </h3>

                                <div className="cortex-tree-meta">
                                    <span><Hash size={13} /> {tree.total_nodes} nodes</span>
                                    <span><Clock size={13} /> {formatDate(tree.last_active_at)}</span>
                                </div>

                                <div className="cortex-tree-actions">
                                    {tree.status === 'active' && (
                                        <JellyButton size="sm" variant="secondary" onClick={(e) => handleSuspend(tree.id, e)}>
                                            <Pause size={14} /> Suspend
                                        </JellyButton>
                                    )}
                                    {tree.status === 'suspended' && (
                                        <JellyButton size="sm" onClick={(e) => handleResume(tree.id, e)}>
                                            <Play size={14} /> Resume
                                        </JellyButton>
                                    )}
                                    <JellyButton size="sm" variant="secondary" onClick={() => navigate(`/cortex/trees/${tree.id}`)}>
                                        <Eye size={14} /> Explore <ChevronRight size={14} />
                                    </JellyButton>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};
