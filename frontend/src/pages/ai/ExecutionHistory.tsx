import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { GlassCard, JellyButton } from '@/components/ui';
import { Clock, CheckCircle, XCircle, Loader, Eye, RotateCcw, DollarSign, Database, Pause, Play } from 'lucide-react';
import { apiClient } from '@/services/api.client';
import { ExecutionRun, RunStatus } from '@/types';
import './ExecutionHistory.css';

export const ExecutionHistory: React.FC = () => {
    const [executions, setExecutions] = useState<ExecutionRun[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState<RunStatus | 'ALL'>('ALL');

    useEffect(() => {
        fetchExecutions();
    }, []);

    const fetchExecutions = async () => {
        try {
            const { data } = await apiClient.get('/ai/executions');
            setExecutions(data);
        } catch (error) {
            console.error('Failed to fetch executions:', error);
        } finally {
            setLoading(false);
        }
    };

    const getStatusIcon = (status: RunStatus) => {
        switch (status) {
            case RunStatus.COMPLETED:
                return <CheckCircle size={20} color="var(--color-success)" />;
            case RunStatus.FAILED:
                return <XCircle size={20} color="var(--color-error)" />;
            case RunStatus.RUNNING:
                return <Loader className="spin" size={20} color="var(--color-info)" />;
            case 'PAUSED' as RunStatus:
                return <Pause size={20} color="var(--color-warning, #f59e0b)" />;
            case 'RESUMING' as RunStatus:
                return <Play size={20} color="var(--color-info)" />;
            default:
                return <Clock size={20} color="var(--color-warning)" />;
        }
    };

    const formatDate = (dateString: string) => {
        const date = parseServerDate(dateString);
        return date.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    };

    const filteredExecutions = executions.filter(exec => {
        if (filter === 'ALL') return true;
        return exec.status === filter;
    });

    if (loading) {
        return (
            <div className="loading-container">
                <Clock size={48} className="pulse" color="var(--color-secondary)" />
                <div className="loading">Consulting Historical Records...</div>
            </div>
        );
    }

    return (
        <div className="page-container execution-history">
            <header className="page-header">
                <div>
                    <h1>Execution Records</h1>
                    <p>Audit trail of all hierarchical intelligence units</p>
                </div>
            </header>

            <div className="filter-bar">
                {(['ALL', ...Object.values(RunStatus), 'PAUSED', 'RESUMING', 'PARTIAL_COMPLETE'] as const).map(s => (
                    <button
                        key={s}
                        className={`filter-btn ${filter === s ? 'active' : ''}`}
                        onClick={() => setFilter(s as any)}
                    >
                        {s} ({s === 'ALL' ? executions.length : executions.filter(e => e.status === s).length})
                    </button>
                ))}
            </div>

            <div className="standard-grid">
                {filteredExecutions.length === 0 ? (
                    <GlassCard className="empty-state">
                        <Clock size={64} className="mb-4 text-tertiary" color="var(--color-text-tertiary)" />
                        <h3>Quiet in the archives</h3>
                        <p>
                            {filter === 'ALL'
                                ? 'Deploy a unit to see its trail here'
                                : `No executions found with status: ${filter}`}
                        </p>
                    </GlassCard>
                ) : (
                    filteredExecutions.map((execution) => (
                        <GlassCard key={execution.id} hover className="glass-card-item">
                            <div className="card-header">
                                <div className="card-icon">
                                    {getStatusIcon(execution.status)}
                                </div>
                                <div className="card-info">
                                    <div className="card-title-row">
                                        <h3 title={execution.entity?.name}>{execution.entity?.name || 'Anonymous Unit'}</h3>
                                        <span className="version-tag">{formatDate(execution.created_at)}</span>
                                    </div>
                                    <div className="card-badge-row">
                                        <span className={`status-badge ${execution.status.toLowerCase()}`} style={{
                                            color: execution.status === 'COMPLETED' ? 'var(--color-success)' :
                                                execution.status === 'FAILED' ? 'var(--color-error)' :
                                                    execution.status === 'RUNNING' ? 'var(--color-info)' : 'var(--color-warning)'
                                        }}>
                                            {execution.status}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            <div className="card-description">
                                {execution.error_message ? (
                                    <span style={{ color: 'var(--color-error)' }}>Error: {execution.error_message}</span>
                                ) : (
                                    <span>Executed successfully.</span>
                                )}
                            </div>

                            <div className="card-meta">
                                <span className="meta-item" title="Billed Amount">
                                    <DollarSign size={12} /> ${(execution.billed_amount != null ? execution.billed_amount : execution.total_cost_usd).toFixed(4)}
                                </span>
                                <span className="meta-item" title="Token Usage">
                                    <Database size={12} /> {execution.total_tokens.toLocaleString()}
                                </span>
                            </div>

                            <div className="card-actions">
                                <Link to={`/ai/executions/${execution.id}`}>
                                    <JellyButton variant="secondary" size="sm">
                                        <Eye size={16} /> Trace
                                    </JellyButton>
                                </Link>
                                <Link to={`/ai/execute/${execution.entity_id}`}>
                                    <JellyButton variant="ghost" size="sm">
                                        <RotateCcw size={16} /> Retry
                                    </JellyButton>
                                </Link>
                            </div>
                        </GlassCard>
                    ))
                )}
            </div>
        </div>
    );
};
