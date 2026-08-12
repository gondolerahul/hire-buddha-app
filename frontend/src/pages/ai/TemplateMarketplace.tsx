import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard, JellyButton } from '@/components/ui';
import {
    Brain, Workflow, Zap, Activity, Layers, Tag, Copy, Trash2, Eye,
    Search, GitBranch, Cpu, Sparkles, AlertCircle, CheckCircle2,
} from 'lucide-react';
import { templateService } from '@/services/template.service';
import { HierarchicalEntity, EntityType, EntityStatus, UserRole } from '@/types';
import './TemplateMarketplace.css';

// ── Helpers ───────────────────────────────────────────────────────────────

const TYPE_ICONS: Record<EntityType, React.ReactNode> = {
    [EntityType.ACTION]:  <Zap size={20} />,
    [EntityType.SKILL]:   <Activity size={20} />,
    [EntityType.AGENT]:   <Brain size={20} />,
    [EntityType.PROCESS]: <Workflow size={20} />,
};

const TYPE_COLORS: Record<EntityType, string> = {
    [EntityType.ACTION]:  'var(--color-primary)',
    [EntityType.SKILL]:   'var(--color-secondary)',
    [EntityType.AGENT]:   'var(--color-rose-gold)',
    [EntityType.PROCESS]: 'var(--color-accent)',
};

const STATUS_COLORS: Record<string, string> = {
    [EntityStatus.ACTIVE]:     'var(--color-success)',
    [EntityStatus.DRAFT]:      'var(--color-warning)',
    [EntityStatus.DEPRECATED]: 'var(--color-text-tertiary)',
    [EntityStatus.ARCHIVED]:   'var(--color-text-tertiary)',
};

// ── Toast ─────────────────────────────────────────────────────────────────

interface Toast { message: string; type: 'success' | 'error'; id: number; }

const ToastContainer: React.FC<{ toasts: Toast[] }> = ({ toasts }) => (
    <>
        {toasts.map((t, i) => (
            <div key={t.id} className={`template-toast ${t.type}`} style={{ bottom: `${24 + i * 60}px` }}>
                {t.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                {t.message}
            </div>
        ))}
    </>
);

// ── Component ─────────────────────────────────────────────────────────────

export const TemplateMarketplace: React.FC = () => {
    const { user } = useAuth();
    const navigate = useNavigate();

    const [templates, setTemplates] = useState<HierarchicalEntity[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState<EntityType | 'ALL'>('ALL');
    const [search, setSearch] = useState('');
    const [cloningId, setCloningId] = useState<string | null>(null);
    const [toasts, setToasts] = useState<Toast[]>([]);

    const isAdmin = user?.role === UserRole.APP_ADMIN;

    // ── Fetch ──────────────────────────────────────────────────────────
    const fetchTemplates = useCallback(async () => {
        try {
            const data = await templateService.listTemplates();
            setTemplates(data);
        } catch (error) {
            console.error('Failed to fetch templates:', error);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { fetchTemplates(); }, [fetchTemplates]);

    // ── Toast helper ──────────────────────────────────────────────────
    const showToast = (message: string, type: 'success' | 'error') => {
        const id = Date.now();
        setToasts(prev => [...prev, { message, type, id }]);
        setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
    };

    // ── Clone ──────────────────────────────────────────────────────────
    const handleClone = async (templateId: string, templateName: string) => {
        setCloningId(templateId);
        try {
            const cloned = await templateService.cloneTemplate(templateId);
            const entityType = (cloned.type || '').toLowerCase();
            showToast(
                `"${templateName}" cloned successfully as ${entityType}! All child entities included.`,
                'success'
            );
            // Navigate to the cloned entity's edit page after a brief pause
            setTimeout(() => navigate(`/ai/entities/edit/${cloned.id}`), 1200);
        } catch (error: any) {
            console.error('Failed to clone template:', error);
            // Extract detailed error message from API response
            const detail = error?.response?.data?.detail;
            const message = typeof detail === 'string'
                ? detail.split('\n')[0]   // Show first line of multi-line errors
                : 'Clone failed. Please try again.';
            showToast(message, 'error');
        } finally {
            setCloningId(null);
        }
    };

    // ── Delete ─────────────────────────────────────────────────────────
    const handleDelete = async (id: string) => {
        if (!window.confirm('Are you sure you want to delete this template? This cannot be undone.')) return;
        try {
            await templateService.deleteTemplate(id);
            setTemplates(prev => prev.filter(t => t.id !== id));
            showToast('Template deleted.', 'success');
        } catch (error) {
            console.error('Failed to delete template:', error);
            showToast('Delete failed.', 'error');
        }
    };

    // ── Derived data ──────────────────────────────────────────────────
    const filtered = templates
        .filter(t => filter === 'ALL' || t.type === filter)
        .filter(t => {
            if (!search) return true;
            const q = search.toLowerCase();
            return t.name.toLowerCase().includes(q)
                || (t.description || '').toLowerCase().includes(q)
                || (t.goal || '').toLowerCase().includes(q);
        });

    const typeCounts = templates.reduce((acc, t) => {
        acc[t.type] = (acc[t.type] || 0) + 1;
        return acc;
    }, {} as Record<string, number>);

    // ── Loading ───────────────────────────────────────────────────────
    if (loading) {
        return (
            <div className="loading-container">
                <Layers size={48} className="pulse" color="var(--color-rose-gold)" />
                <div className="loading">Loading Template Marketplace…</div>
            </div>
        );
    }

    // ── Render ─────────────────────────────────────────────────────────
    return (
        <div className="template-marketplace-page">
            {/* Header */}
            <div className="page-header">
                <div>
                    <h1>Template Marketplace</h1>
                    <p>Browse and clone pre-built agent hierarchies — Actions, Skills, Agents &amp; Processes</p>
                </div>
                <div className="header-actions" style={{ display: 'flex', gap: 'var(--spacing-md)', alignItems: 'center' }}>
                    {/* Search */}
                    <div style={{ position: 'relative' }}>
                        <Search size={16} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-tertiary)' }} />
                        <input
                            type="text"
                            placeholder="Search templates…"
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            style={{
                                padding: '8px 12px 8px 32px',
                                borderRadius: 'var(--radius-md)',
                                border: '1px solid rgba(255,255,255,0.1)',
                                background: 'rgba(255,255,255,0.04)',
                                color: 'var(--color-text)',
                                fontSize: '0.9rem',
                                width: 220,
                                outline: 'none',
                            }}
                            id="template-search-input"
                        />
                    </div>
                </div>
            </div>

            {/* Filter Tabs */}
            <div className="filter-tabs">
                {(['ALL', ...Object.values(EntityType)] as const).map(t => (
                    <button
                        key={t}
                        className={`filter-tab ${filter === t ? 'active' : ''}`}
                        onClick={() => setFilter(t)}
                        id={`filter-tab-${t.toLowerCase()}`}
                    >
                        {t}
                        {t !== 'ALL' && typeCounts[t] ? ` (${typeCounts[t]})` : ''}
                        {t === 'ALL' ? ` (${templates.length})` : ''}
                    </button>
                ))}
            </div>

            {/* Template Grid */}
            <div className="entities-grid">
                {filtered.length === 0 ? (
                    <GlassCard className="empty-state">
                        <Sparkles size={64} color="var(--color-text-tertiary)" />
                        <h3>No templates found</h3>
                        <p>{search ? 'Try adjusting your search.' : 'Templates will appear here once an admin creates them.'}</p>
                    </GlassCard>
                ) : (
                    filtered.map(template => {
                        const typeColor = TYPE_COLORS[template.type];
                        const stepCount = template.planning?.static_plan?.steps?.length || 0;
                        const isCloning = cloningId === template.id;

                        return (
                            <GlassCard
                                key={template.id}
                                hover
                                className="template-card"
                                style={{ '--card-accent': typeColor } as React.CSSProperties}
                            >
                                {/* Template badge */}
                                <span className="template-badge">Template</span>

                                {/* Header */}
                                <div className="card-header">
                                    <div className="card-icon-wrapper" style={{ color: typeColor }}>
                                        {TYPE_ICONS[template.type]}
                                    </div>
                                    <div className="entity-info">
                                        <div className="title-row">
                                            <h3 title={template.name}>{template.display_name || template.name}</h3>
                                            <span className="version-tag">v{template.version}</span>
                                        </div>
                                        <div className="badge-row">
                                            <span
                                                className="entity-type-badge"
                                                style={{
                                                    backgroundColor: typeColor + '22',
                                                    color: typeColor,
                                                }}
                                            >
                                                {template.type}
                                            </span>
                                            <span className="status-badge" style={{ color: STATUS_COLORS[template.status] || 'var(--color-text-tertiary)' }}>
                                                {template.status}
                                            </span>
                                        </div>
                                    </div>
                                </div>

                                {/* Description */}
                                <p className="template-description">
                                    {template.description || 'No description provided.'}
                                </p>

                                {/* Goal */}
                                {template.goal && (
                                    <div className="template-goal">
                                        🎯 {template.goal}
                                    </div>
                                )}

                                {/* Meta */}
                                <div className="template-meta">
                                    {template.logic_gate?.reasoning_config?.model_name && (
                                        <span className="meta-item" title="Model">
                                            <Cpu size={12} /> {template.logic_gate.reasoning_config.model_name}
                                        </span>
                                    )}
                                    {stepCount > 0 && (
                                        <span className="meta-item" title="Plan Steps">
                                            <GitBranch size={12} /> {stepCount} steps
                                        </span>
                                    )}
                                    {template.tags && template.tags.length > 0 && (
                                        <span className="meta-item" title="Tags">
                                            <Tag size={12} /> {template.tags.join(', ')}
                                        </span>
                                    )}
                                </div>

                                {/* Actions */}
                                <div className="template-actions">
                                    <JellyButton
                                        className="clone-btn"
                                        onClick={() => handleClone(template.id, template.display_name || template.name)}
                                        disabled={isCloning}
                                    >
                                        <Copy size={16} />
                                        {isCloning ? 'Cloning…' : 'Clone'}
                                    </JellyButton>
                                    <JellyButton
                                        variant="secondary"
                                        onClick={() => navigate(`/ai/entities/edit/${template.id}`)}
                                    >
                                        <Eye size={16} />
                                        View
                                    </JellyButton>
                                    {isAdmin && (
                                        <JellyButton
                                            variant="ghost"
                                            onClick={() => handleDelete(template.id)}
                                        >
                                            <Trash2 size={16} />
                                        </JellyButton>
                                    )}
                                </div>
                            </GlassCard>
                        );
                    })
                )}
            </div>

            {/* Toast Layer */}
            <ToastContainer toasts={toasts} />
        </div>
    );
};
