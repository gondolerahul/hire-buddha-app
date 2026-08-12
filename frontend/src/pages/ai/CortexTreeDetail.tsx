/**
 * CortexTreeDetail — Interactive Tree Node Explorer
 * 
 * Provides viewport-based navigation through a CORTEX cognitive tree,
 * mirroring the same navigation model the agent uses internally.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { cortexService, CortexTree, CortexViewport, CortexNodeContent } from '@/services/cortex.service';
import { JellyButton } from '@/components/ui';
import {
    Brain, ChevronRight, ChevronLeft, ArrowUp, Eye, FileText,
    BookOpen, Search, Target, Pause, Play, Download, Hash, Clock,
    Layers, TreePine, CheckCircle, AlertCircle, Loader,
} from 'lucide-react';
import './CortexTreeDetail.css';

const NODE_TYPE_CONFIG: Record<string, { icon: string; color: string }> = {
    root: { icon: '🌳', color: '#22c55e' },
    knowledge: { icon: '📚', color: '#3b82f6' },
    finding: { icon: '🔬', color: '#f59e0b' },
    task: { icon: '📋', color: '#ef4444' },
    output: { icon: '📝', color: '#6366f1' },
    checkpoint: { icon: '📌', color: '#ec4899' },
};

const STATUS_STYLES: Record<string, { bg: string; color: string; label: string }> = {
    pending: { bg: '#64748b22', color: '#94a3b8', label: 'Pending' },
    active: { bg: '#22c55e22', color: '#22c55e', label: 'Active' },
    complete: { bg: '#6366f122', color: '#818cf8', label: 'Complete' },
    summarised: { bg: '#f59e0b22', color: '#fbbf24', label: 'Summarised' },
};

export const CortexTreeDetail: React.FC = () => {
    const { treeId } = useParams();
    const navigate = useNavigate();
    const [tree, setTree] = useState<CortexTree | null>(null);
    const [viewport, setViewport] = useState<CortexViewport | null>(null);
    const [nodeContent, setNodeContent] = useState<CortexNodeContent | null>(null);
    const [loading, setLoading] = useState(true);
    const [contentLoading, setContentLoading] = useState(false);
    const [showContent, setShowContent] = useState(false);

    useEffect(() => {
        if (treeId) loadTree();
    }, [treeId]);

    const loadTree = async () => {
        if (!treeId) return;
        setLoading(true);
        try {
            const treeData = await cortexService.getTree(treeId);
            setTree(treeData);
            if (treeData.root_node_id) {
                const vp = await cortexService.navigate(treeId, treeData.resume_cursor_id || treeData.root_node_id);
                setViewport(vp);
            }
        } catch (err) {
            console.error('Failed to load tree:', err);
        } finally {
            setLoading(false);
        }
    };

    const navigateTo = useCallback(async (nodeId: string) => {
        if (!treeId) return;
        setShowContent(false);
        setNodeContent(null);
        try {
            const vp = await cortexService.navigate(treeId, nodeId);
            setViewport(vp);
        } catch (err) {
            console.error('Navigation failed:', err);
        }
    }, [treeId]);

    const readContent = useCallback(async (nodeId: string, page = 0) => {
        if (!treeId) return;
        setContentLoading(true);
        setShowContent(true);
        try {
            const content = await cortexService.readNode(treeId, nodeId, page);
            setNodeContent(content);
        } catch (err) {
            console.error('Read failed:', err);
        } finally {
            setContentLoading(false);
        }
    }, [treeId]);

    const handleSuspend = async () => {
        if (!treeId) return;
        await cortexService.suspendTree(treeId);
        loadTree();
    };

    const handleResume = async () => {
        if (!treeId) return;
        await cortexService.resumeTree(treeId);
        loadTree();
    };

    const handleAssembleOutput = async () => {
        if (!treeId) return;
        try {
            const { output } = await cortexService.assembleOutput(treeId);
            // Download as text file
            const blob = new Blob([output], { type: 'text/markdown' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `cortex-output-${treeId.slice(0, 8)}.md`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (err) {
            console.error('Assembly failed:', err);
        }
    };

    if (loading) {
        return (
            <div className="cortex-detail-loading">
                <Loader className="cortex-detail-spin" size={32} />
                <p>Loading CORTEX tree…</p>
            </div>
        );
    }

    if (!tree || !viewport) {
        return (
            <div className="cortex-detail-loading">
                <AlertCircle size={32} />
                <p>Tree not found</p>
                <JellyButton onClick={() => navigate('/cortex')}>Back to Explorer</JellyButton>
            </div>
        );
    }

    const current = viewport.current_node;
    const typeCfg = NODE_TYPE_CONFIG[current.node_type] || NODE_TYPE_CONFIG.root;

    return (
        <div className="cortex-detail">
            {/* Header */}
            <div className="cortex-detail-header">
                <div className="cortex-detail-header-left">
                    <JellyButton size="sm" variant="secondary" onClick={() => navigate('/cortex')}>
                        <ChevronLeft size={14} /> All Trees
                    </JellyButton>
                    <Brain size={22} className="cortex-detail-icon" />
                    <h1>{tree.task_description || 'CORTEX Tree'}</h1>
                </div>
                <div className="cortex-detail-header-right">
                    <span className="cortex-tree-meta-badge">
                        <Hash size={13} /> {tree.total_nodes} nodes
                    </span>
                    {tree.status === 'active' && (
                        <JellyButton size="sm" variant="secondary" onClick={handleSuspend}>
                            <Pause size={14} /> Suspend
                        </JellyButton>
                    )}
                    {tree.status === 'suspended' && (
                        <JellyButton size="sm" onClick={handleResume}>
                            <Play size={14} /> Resume
                        </JellyButton>
                    )}
                    <JellyButton size="sm" variant="secondary" onClick={handleAssembleOutput}>
                        <Download size={14} /> Export Output
                    </JellyButton>
                </div>
            </div>

            {/* Breadcrumb */}
            <div className="cortex-breadcrumb">
                {viewport.breadcrumb.map((crumb, i) => (
                    <React.Fragment key={crumb.id}>
                        {i > 0 && <ChevronRight size={14} className="cortex-breadcrumb-sep" />}
                        <button
                            className={`cortex-breadcrumb-item ${crumb.id === current.id ? 'active' : ''}`}
                            onClick={() => navigateTo(crumb.id)}
                        >
                            {crumb.title.length > 30 ? crumb.title.slice(0, 30) + '…' : crumb.title}
                        </button>
                    </React.Fragment>
                ))}
            </div>

            <div className="cortex-detail-body">
                {/* Current Node */}
                <div className="cortex-current-node">
                    <div className="cortex-node-header">
                        <div className="cortex-node-type-badge" style={{ background: typeCfg.color + '18', color: typeCfg.color, borderColor: typeCfg.color + '44' }}>
                            <span>{typeCfg.icon}</span> {current.node_type}
                        </div>
                        <span className={`cortex-node-status cortex-status-${current.status}`}
                            style={STATUS_STYLES[current.status] ? {
                                background: STATUS_STYLES[current.status].bg,
                                color: STATUS_STYLES[current.status].color,
                            } : {}}>
                            {STATUS_STYLES[current.status]?.label || current.status}
                        </span>
                        {viewport.parent && (
                            <button className="cortex-up-btn" onClick={() => navigateTo(viewport.parent!.id)}>
                                <ArrowUp size={14} /> Up
                            </button>
                        )}
                    </div>

                    <h2 className="cortex-current-title">{current.title}</h2>

                    {current.summary && (
                        <p className="cortex-current-summary">{current.summary}</p>
                    )}

                    <div className="cortex-node-meta-row">
                        <span><Layers size={13} /> Depth {current.depth}</span>
                        <span><FileText size={13} /> {current.content_tokens} tokens</span>
                    </div>

                    {current.content_tokens > 0 && !showContent && (
                        <JellyButton size="sm" onClick={() => readContent(current.id)}>
                            <BookOpen size={14} /> Read Content
                        </JellyButton>
                    )}
                </div>

                {/* Content Panel */}
                {showContent && (
                    <div className="cortex-content-panel">
                        <div className="cortex-content-header">
                            <h3><BookOpen size={16} /> Content: {nodeContent?.title || current.title}</h3>
                            <button className="cortex-close-btn" onClick={() => setShowContent(false)}>✕</button>
                        </div>
                        {contentLoading ? (
                            <div className="cortex-content-loading">
                                <Loader className="cortex-detail-spin" size={20} />
                            </div>
                        ) : nodeContent ? (
                            <>
                                <pre className="cortex-content-body">{nodeContent.content}</pre>
                                {nodeContent.total_pages > 1 && (
                                    <div className="cortex-content-pagination">
                                        <span>Page {nodeContent.page + 1} of {nodeContent.total_pages}</span>
                                        <div className="cortex-page-btns">
                                            {nodeContent.page > 0 && (
                                                <JellyButton size="sm" variant="secondary" onClick={() => readContent(nodeContent.node_id, nodeContent.page - 1)}>
                                                    ← Prev
                                                </JellyButton>
                                            )}
                                            {nodeContent.page < nodeContent.total_pages - 1 && (
                                                <JellyButton size="sm" variant="secondary" onClick={() => readContent(nodeContent.node_id, nodeContent.page + 1)}>
                                                    Next →
                                                </JellyButton>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </>
                        ) : null}
                    </div>
                )}

                {/* Children */}
                <div className="cortex-children-section">
                    <h3 className="cortex-children-heading">
                        <TreePine size={16} /> Children ({viewport.children.length})
                    </h3>
                    {viewport.children.length === 0 ? (
                        <div className="cortex-no-children">
                            <p>Leaf node — no children</p>
                        </div>
                    ) : (
                        <div className="cortex-children-list">
                            {viewport.children.map((child, i) => {
                                const childCfg = NODE_TYPE_CONFIG[child.node_type] || NODE_TYPE_CONFIG.root;
                                const childStatus = STATUS_STYLES[child.status];
                                return (
                                    <div
                                        key={child.id}
                                        className="cortex-child-card"
                                        onClick={() => navigateTo(child.id)}
                                    >
                                        <div className="cortex-child-header">
                                            <span className="cortex-child-order">{i + 1}</span>
                                            <span className="cortex-child-type" style={{ color: childCfg.color }}>{childCfg.icon}</span>
                                            <span className="cortex-child-title">{child.title}</span>
                                            <span className="cortex-child-status" style={childStatus ? { color: childStatus.color } : {}}>
                                                {child.status === 'complete' ? <CheckCircle size={13} /> : null}
                                                {childStatus?.label || child.status}
                                            </span>
                                        </div>
                                        {child.summary && (
                                            <p className="cortex-child-summary">{child.summary}</p>
                                        )}
                                        <span className="cortex-child-tokens">{child.content_tokens} tok</span>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
