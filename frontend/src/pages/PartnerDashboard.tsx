import React, { useState, useEffect, useCallback } from 'react';
import { partnerService, TenantSummary, PartnerAnalytics } from '@/services/platform.service';
import './PartnerDashboard.css';

const PartnerDashboard: React.FC = () => {
    const [tenants, setTenants] = useState<TenantSummary[]>([]);
    const [analytics, setAnalytics] = useState<PartnerAnalytics | null>(null);
    const [loading, setLoading] = useState(true);
    const [selectedTenant, setSelectedTenant] = useState<any>(null);

    const loadData = useCallback(async () => {
        try {
            const [tenantRes, analyticsRes] = await Promise.all([
                partnerService.getTenants(),
                partnerService.getAnalytics(),
            ]);
            setTenants(tenantRes.tenants || []);
            setAnalytics(analyticsRes);
        } catch (err) {
            console.error('Failed to load partner data:', err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { loadData(); }, [loadData]);

    const handleViewDetails = async (tenantId: string) => {
        try {
            const detail = await partnerService.getTenantDetails(tenantId);
            setSelectedTenant(detail);
        } catch (err) {
            console.error('Failed to load tenant details:', err);
        }
    };

    if (loading) {
        return <div className="partner-loading">Loading partner dashboard…</div>;
    }

    return (
        <div className="partner-dashboard">
            {/* Header */}
            <div className="page-header">
                <div>
                    <h1>Partner Dashboard</h1>
                    <p>Manage your tenants and monitor platform health</p>
                </div>
            </div>

            {/* Aggregate Stats */}
            {analytics && (
                <div className="partner-stats-grid">
                    <div className="partner-stat-card tenants">
                        <div className="stat-label">Total Tenants</div>
                        <div className="stat-value">{analytics.total_tenants}</div>
                        <div className="stat-sub">
                            {analytics.active_tenants} active · {analytics.suspended_tenants} suspended
                        </div>
                    </div>
                    <div className="partner-stat-card entities">
                        <div className="stat-label">AI Entities</div>
                        <div className="stat-value">{analytics.total_entities}</div>
                        <div className="stat-sub">Across all tenants</div>
                    </div>
                    <div className="partner-stat-card executions">
                        <div className="stat-label">Executions</div>
                        <div className="stat-value">{analytics.total_executions.toLocaleString()}</div>
                        <div className="stat-sub">Total runs to date</div>
                    </div>
                    <div className="partner-stat-card wallet">
                        <div className="stat-label">Combined Balance</div>
                        <div className="stat-value">${analytics.total_wallet_balance.toFixed(2)}</div>
                        <div className="stat-sub">Aggregate wallet balance</div>
                    </div>
                    <div className="partner-stat-card cost">
                        <div className="stat-label">Platform Billing</div>
                        <div className="stat-value">${analytics.total_cost_usd.toFixed(2)}</div>
                        <div className="stat-sub">Total AI billing</div>
                    </div>
                </div>
            )}

            {/* Tenant List */}
            <div className="tenant-list-header">
                <h3>Managed Tenants ({tenants.length})</h3>
            </div>

            {tenants.length === 0 ? (
                <div className="partner-empty">
                    <div className="empty-icon">🏗️</div>
                    <h3>No tenants yet</h3>
                    <p>Create your first tenant from the Platform Management page.</p>
                </div>
            ) : (
                <div className="tenant-grid">
                    {tenants.map((t) => (
                        <div
                            key={t.id}
                            className="tenant-card"
                            onClick={() => handleViewDetails(t.id)}
                        >
                            <div className="tenant-card-header">
                                <div className="tenant-avatar">
                                    {t.name.charAt(0).toUpperCase()}
                                </div>
                                <div className="tenant-info">
                                    <div className="tenant-name">{t.name}</div>
                                    <div className="tenant-meta">
                                        <span className={`health-badge ${t.health_level}`}>
                                            ● {t.health_level}
                                        </span>
                                        <span className={`onboarding-pill ${t.onboarding_status.replace('-', '_')}`}>
                                            {t.onboarding_status}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            <div className="tenant-stats-row">
                                <div className="tenant-mini-stat">
                                    <div className="mini-value">{t.entity_count}</div>
                                    <div className="mini-label">Entities</div>
                                </div>
                                <div className="tenant-mini-stat">
                                    <div className="mini-value">{t.user_count}</div>
                                    <div className="mini-label">Users</div>
                                </div>
                                <div className="tenant-mini-stat">
                                    <div className="mini-value">{t.integration_count}</div>
                                    <div className="mini-label">Integrations</div>
                                </div>
                                <div className="tenant-mini-stat">
                                    <div className="mini-value">{t.recent_executions_7d}</div>
                                    <div className="mini-label">Runs/7d</div>
                                </div>
                            </div>

                            <div className="health-bar-container">
                                <div className="health-bar">
                                    <div
                                        className={`health-bar-fill ${t.health_level}`}
                                        style={{ width: `${t.health_score}%` }}
                                    />
                                </div>
                                <span className="health-score-text">{t.health_score}</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Tenant Detail Modal */}
            {selectedTenant && (
                <div className="tenant-detail-overlay" onClick={() => setSelectedTenant(null)}>
                    <div className="tenant-detail-modal" onClick={(e) => e.stopPropagation()}>
                        <button className="detail-close" onClick={() => setSelectedTenant(null)}>
                            ✕ Close
                        </button>

                        <h2 style={{ marginBottom: 'var(--spacing-2)' }}>{selectedTenant.name}</h2>
                        <div className="tenant-meta" style={{ marginBottom: 'var(--spacing-lg)' }}>
                            <span className={`health-badge ${selectedTenant.health_level}`}>
                                Health: {selectedTenant.health_score}/100
                            </span>
                        </div>

                        {/* Wallet */}
                        <div className="detail-section">
                            <h4>💰 Billing</h4>
                            <div className="detail-row">
                                <span className="label">Wallet Balance</span>
                                <span className="value">${selectedTenant.wallet_balance?.toFixed(2) || '0.00'}</span>
                            </div>
                            <div className="detail-row">
                                <span className="label">Daily Credits</span>
                                <span className="value">${selectedTenant.daily_credits?.toFixed(2) || '0.00'}</span>
                            </div>
                        </div>

                        {/* Users */}
                        {selectedTenant.users?.length > 0 && (
                            <div className="detail-section">
                                <h4>👥 Users ({selectedTenant.users.length})</h4>
                                {selectedTenant.users.map((u: any) => (
                                    <div key={u.id} className="detail-row">
                                        <span className="label">{u.full_name}</span>
                                        <span className="value">{u.role}</span>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Integrations */}
                        {selectedTenant.integrations?.length > 0 && (
                            <div className="detail-section">
                                <h4>🔗 Integrations ({selectedTenant.integrations.length})</h4>
                                {selectedTenant.integrations.map((int: any) => (
                                    <div key={int.id} className="detail-row">
                                        <span className="label">{int.provider_name}</span>
                                        <span className="value">{int.service_category}</span>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Entities */}
                        {selectedTenant.entities?.length > 0 && (
                            <div className="detail-section">
                                <h4>⚡ Entities ({selectedTenant.entities.length})</h4>
                                {selectedTenant.entities.slice(0, 5).map((e: any) => (
                                    <div key={e.id} className="detail-row">
                                        <span className="label">{e.name}</span>
                                        <span className="value">{e.type} · {e.status}</span>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Recent Executions */}
                        {selectedTenant.recent_executions?.length > 0 && (
                            <div className="detail-section">
                                <h4>📊 Recent Executions</h4>
                                {selectedTenant.recent_executions.slice(0, 5).map((r: any) => (
                                    <div key={r.id} className="detail-row">
                                        <span className="label">{r.status}</span>
                                        <span className="value">${(r.billed_amount != null ? r.billed_amount : r.total_cost_usd).toFixed(4)}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

export default PartnerDashboard;
