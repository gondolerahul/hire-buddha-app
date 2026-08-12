import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard, JellyButton } from '@/components/ui';
import { Plus, Brain, Workflow, Zap, Activity, Edit, Trash2, Play, Layers, Tag, BookCopy, CheckCircle } from 'lucide-react';
import { apiClient } from '@/services/api.client';
import { templateService } from '@/services/template.service';
import { metaService } from '@/services/meta.service';
import { HierarchicalEntity, EntityType, EntityStatus, UserRole } from '@/types';
import './EntityLibrary.css';

export const EntityLibrary: React.FC = () => {
    const { user } = useAuth();
    const [entities, setEntities] = useState<HierarchicalEntity[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState<EntityType | 'ALL'>('ALL');
    const [convertingId, setConvertingId] = useState<string | null>(null);
    const [promotingId, setPromotingId] = useState<string | null>(null);

    const isAdmin = user?.role === UserRole.APP_ADMIN;

    useEffect(() => {
        fetchEntities();
    }, []);

    const fetchEntities = async () => {
        try {
            const { data } = await apiClient.get('/ai/entities');
            setEntities(data);
        } catch (error) {
            console.error('Failed to fetch entities:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleDelete = async (id: string) => {
        if (window.confirm('Are you sure you want to delete this entity?')) {
            try {
                await apiClient.delete(`/ai/entities/${id}`);
                setEntities(entities.filter(e => e.id !== id));
            } catch (error) {
                console.error('Failed to delete entity:', error);
            }
        }
    };

    const handlePromoteDraft = async (id: string, name: string) => {
        if (!window.confirm(`Promote "${name}" from DRAFT to ACTIVE? This bypasses the Meta-Agent Board gates.`)) return;
        setPromotingId(id);
        try {
            const result = await metaService.promoteDraftEntity(id);
            setEntities((prev) => prev.map((e) =>
                e.id === id ? { ...e, status: result.status as EntityStatus } : e,
            ));
        } catch (error: any) {
            const msg = error?.response?.data?.detail || 'Promote failed.';
            alert(`❌ ${msg}`);
        } finally {
            setPromotingId(null);
        }
    };

    const handleConvertToTemplate = async (id: string, name: string) => {
        if (!window.confirm(`Publish "${name}" (and all its children) as a reusable template?`)) return;
        setConvertingId(id);
        try {
            await templateService.convertToTemplate(id);
            alert(`✅ "${name}" has been published as a template! View it in the Template Marketplace.`);
        } catch (error: any) {
            const msg = error?.response?.data?.detail || 'Failed to convert to template.';
            alert(`❌ ${msg}`);
        } finally {
            setConvertingId(null);
        }
    };

    const getTypeIcon = (type: EntityType) => {
        switch (type) {
            case EntityType.ACTION: return <Zap size={20} />;
            case EntityType.SKILL: return <Activity size={20} />;
            case EntityType.AGENT: return <Brain size={20} />;
            case EntityType.PROCESS: return <Workflow size={20} />;
        }
    };

    const getTypeColor = (type: EntityType) => {
        switch (type) {
            case EntityType.ACTION: return 'var(--color-primary)';
            case EntityType.SKILL: return 'var(--color-secondary)';
            case EntityType.AGENT: return 'var(--color-rose-gold)';
            case EntityType.PROCESS: return 'var(--color-accent)';
        }
    };

    const getStatusColor = (status: EntityStatus) => {
        switch (status) {
            case EntityStatus.ACTIVE: return 'var(--color-success)';
            case EntityStatus.DRAFT: return 'var(--color-warning)';
            default: return 'var(--color-text-tertiary)';
        }
    };

    const filteredEntities = filter === 'ALL'
        ? entities
        : entities.filter(e => e.type === filter);

    if (loading) {
        return (
            <div className="loading-container">
                <Layers size={48} className="pulse" color="var(--color-rose-gold)" />
                <div className="loading">Initializing Neural Hub...</div>
            </div>
        );
    }

    return (
        <div className="entity-library-page">
            <div className="page-header">
                <div>
                    <h1>Entity Library</h1>
                    <p>Orchestrate Actions, Skills, Agents, and Processes</p>
                </div>
                <div className="header-actions">
                    <Link to="/ai/entities/create">
                        <JellyButton roseGold>
                            <Plus size={20} />
                            Create Entity
                        </JellyButton>
                    </Link>
                </div>
            </div>

            <div className="filter-tabs">
                {(['ALL', ...Object.values(EntityType)] as const).map(t => (
                    <button
                        key={t}
                        className={`filter-tab ${filter === t ? 'active' : ''}`}
                        onClick={() => setFilter(t)}
                    >
                        {t}
                    </button>
                ))}
            </div>

            <div className="entities-grid">
                {filteredEntities.length === 0 ? (
                    <GlassCard className="empty-state">
                        <Brain size={64} color="var(--color-text-tertiary)" />
                        <h3>Nothing here yet</h3>
                        <p>Begin by creating an Atomic Action or a Complex Process</p>
                    </GlassCard>
                ) : (
                    filteredEntities.map((entity) => (
                        <GlassCard key={entity.id} hover className="entity-card">
                            <div className="card-header">
                                <div className="card-icon-wrapper entity-icon" style={{ color: getTypeColor(entity.type) }}>
                                    {getTypeIcon(entity.type)}
                                </div>
                                <div className="entity-info">
                                    <div className="title-row">
                                        <h3>{entity.name}</h3>
                                        <span className="version-tag">v{entity.version}</span>
                                    </div>
                                    <div className="badge-row">
                                        <span className="entity-type-badge" style={{ backgroundColor: getTypeColor(entity.type) + '22', color: getTypeColor(entity.type) }}>
                                            {entity.type}
                                        </span>
                                        <span className="status-badge" style={{ color: getStatusColor(entity.status) }}>
                                            {entity.status}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            <p className="entity-description">
                                {entity.description || 'No description provided.'}
                            </p>

                            <div className="entity-meta">
                                {entity.logic_gate?.reasoning_config && (
                                    <span className="meta-item" title="Model">
                                        <Brain size={12} /> {entity.logic_gate.reasoning_config.model_name}
                                    </span>
                                )}
                                {entity.planning?.static_plan?.steps && (
                                    <span className="meta-item" title="Steps">
                                        <Activity size={12} /> {entity.planning.static_plan.steps.length} steps
                                    </span>
                                )}
                                {entity.tags && entity.tags.length > 0 && (
                                    <span className="meta-item">
                                        <Tag size={12} /> {entity.tags.length}
                                    </span>
                                )}
                            </div>

                            <div className="entity-actions">
                                <Link to={`/ai/execute/${entity.id}`}>
                                    <JellyButton variant="primary">
                                        <Play size={16} />
                                        Run
                                    </JellyButton>
                                </Link>
                                <Link to={`/ai/entities/edit/${entity.id}`}>
                                    <JellyButton variant="secondary">
                                        <Edit size={16} />
                                        Edit
                                    </JellyButton>
                                </Link>
                                {isAdmin && entity.status === EntityStatus.DRAFT && (
                                    <span title="Promote DRAFT → ACTIVE">
                                        <JellyButton
                                            variant="secondary"
                                            onClick={() => handlePromoteDraft(entity.id, entity.name)}
                                            disabled={promotingId === entity.id}
                                        >
                                            <CheckCircle size={16} />
                                            {promotingId === entity.id ? '…' : ''}
                                        </JellyButton>
                                    </span>
                                )}
                                {isAdmin && (
                                    <JellyButton
                                        variant="secondary"
                                        onClick={() => handleConvertToTemplate(entity.id, entity.name)}
                                        disabled={convertingId === entity.id}
                                    >
                                        <BookCopy size={16} />
                                        {convertingId === entity.id ? '…' : ''}
                                    </JellyButton>
                                )}
                                <JellyButton
                                    variant="ghost"
                                    onClick={() => handleDelete(entity.id)}
                                >
                                    <Trash2 size={16} />
                                </JellyButton>
                            </div>
                        </GlassCard>
                    ))
                )}
            </div>
        </div>
    );
};
