import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { phonePoolService } from '@/services/platform.service';
import './PhonePool.css';

interface PhoneNumberEntry {
    id: string;
    phone_number: string;
    provider: string;
    country_code: string;
    status: string;
    label: string | null;
    monthly_cost_usd: number | null;
    capabilities: any;
    notes: string | null;
    is_active: boolean;
    // Ownership
    company_id: string | null;
    claimed_at: string | null;
    // Assignment
    agent_id: string | null;
    agent_name: string | null;
    customer_id: string | null;
    customer_name: string | null;
    assigned_at: string | null;
    // Timestamps
    created_at: string | null;
}

interface Agent {
    id: string;
    name: string;
}

interface CustomerCompany {
    id: string;
    name: string;
    type: string;
}

interface Company {
    id: string;
    name: string;
    type: string;
}

const PhonePool: React.FC = () => {
    const { user, token } = useAuth();
    const [numbers, setNumbers] = useState<PhoneNumberEntry[]>([]);
    const [agents, setAgents] = useState<Agent[]>([]);
    const [customers, setCustomers] = useState<CustomerCompany[]>([]);
    const [loading, setLoading] = useState(true);
    const [statusFilter, setStatusFilter] = useState('');
    const [providerFilter, setProviderFilter] = useState('');
    const [showAddModal, setShowAddModal] = useState(false);
    const [showAssignModal, setShowAssignModal] = useState<PhoneNumberEntry | null>(null);
    const [syncing, setSyncing] = useState(false);
    const [syncResult, setSyncResult] = useState<any>(null);

    // Confirmation modal state (replaces window.confirm)
    const [confirmModal, setConfirmModal] = useState<{
        message: string;
        action: () => Promise<void>;
    } | null>(null);
    const [confirmLoading, setConfirmLoading] = useState(false);

    // Edit modal state
    const [showEditModal, setShowEditModal] = useState<PhoneNumberEntry | null>(null);
    const [editForm, setEditForm] = useState({
        phone_number: '',
        provider: '',
        label: '',
        notes: '',
    });

    // Claim modal state — app_admin can choose target company
    const [showClaimModal, setShowClaimModal] = useState<PhoneNumberEntry | null>(null);
    const [claimCompanyId, setClaimCompanyId] = useState('');
    const [companies, setCompanies] = useState<Company[]>([]);

    const [addForm, setAddForm] = useState({
        phone_number: '',
        provider: 'tata_tele',
        country_code: '+91',
        label: '',
        notes: '',
    });

    const [assignForm, setAssignForm] = useState({
        agent_id: '',
        customer_name: '',
    });

    const isAdmin = user?.role === 'app_admin';

    const fetchNumbers = useCallback(async () => {
        try {
            setLoading(true);
            const data = await phonePoolService.listNumbers(statusFilter || undefined, providerFilter || undefined);
            setNumbers(data.phone_numbers || data || []);
        } catch (err) {
            console.error('Failed to fetch numbers:', err);
        } finally {
            setLoading(false);
        }
    }, [statusFilter, providerFilter]);

    const fetchAgents = async () => {
        try {
            // Fetch only ACTIVE, voice-enabled agents for assignment
            const response = await fetch(
                `${import.meta.env.VITE_API_BASE_URL}/ai/entities?type=AGENT&voice_enabled=true&status=ACTIVE`,
                { headers: { 'Authorization': `Bearer ${token}` } }
            );
            if (!response.ok) return;
            const data = await response.json();
            setAgents(Array.isArray(data) ? data : data.entities || data.data || []);
        } catch (err) {
            console.error('Error fetching agents:', err);
        }
    };

    const fetchCustomers = async () => {
        try {
            const results: CustomerCompany[] = [];
            // Fetch tenants
            const tenantRes = await fetch(
                `${import.meta.env.VITE_API_BASE_URL}/companies/tenants`,
                { headers: { 'Authorization': `Bearer ${token}` } }
            );
            if (tenantRes.ok) {
                const tenantData = await tenantRes.json();
                const tenants = Array.isArray(tenantData) ? tenantData : tenantData.data || [];
                results.push(...tenants.map((c: any) => ({ id: c.id, name: c.name, type: 'TENANT' })));
            }
            // Fetch partners (app_admin only)
            if (isAdmin) {
                const partnerRes = await fetch(
                    `${import.meta.env.VITE_API_BASE_URL}/companies/partners`,
                    { headers: { 'Authorization': `Bearer ${token}` } }
                );
                if (partnerRes.ok) {
                    const partnerData = await partnerRes.json();
                    const partners = Array.isArray(partnerData) ? partnerData : partnerData.data || [];
                    results.push(...partners.map((c: any) => ({ id: c.id, name: c.name, type: 'PARTNER' })));
                }
            }
            setCustomers(results);
        } catch (err) {
            console.error('Error fetching customers:', err);
        }
    };

    useEffect(() => { fetchNumbers(); }, [fetchNumbers]);
    useEffect(() => {
        fetchAgents();
        fetchCustomers();
        if (isAdmin) fetchCompanies();
    }, []);

    const fetchCompanies = async () => {
        try {
            const response = await fetch(
                `${import.meta.env.VITE_API_BASE_URL}/companies`,
                { headers: { 'Authorization': `Bearer ${token}` } }
            );
            if (!response.ok) return;
            const data = await response.json();
            setCompanies(Array.isArray(data) ? data : []);
        } catch (err) {
            console.error('Error fetching companies:', err);
        }
    };

    const handleSync = async () => {
        setSyncing(true);
        setSyncResult(null);
        try {
            const result = await phonePoolService.syncNumbers();
            setSyncResult(result);
            fetchNumbers();
        } catch (err: any) {
            setSyncResult({ error: err.message || 'Sync failed' });
        } finally {
            setSyncing(false);
        }
    };

    const handleAddNumber = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await phonePoolService.addNumber(addForm);
            setShowAddModal(false);
            setAddForm({ phone_number: '', provider: 'tata_tele', country_code: '+91', label: '', notes: '' });
            fetchNumbers();
        } catch (err: any) {
            alert(err?.response?.data?.detail || 'Failed to add number');
        }
    };

    const handleClaim = async (entry: PhoneNumberEntry) => {
        if (isAdmin && companies.length > 0) {
            // Show claim modal with company selector
            setShowClaimModal(entry);
            setClaimCompanyId('');
            return;
        }
        // Non-admin: direct claim
        try {
            await phonePoolService.claimNumber(entry.id);
            fetchNumbers();
        } catch (err: any) {
            alert(err?.response?.data?.detail || 'Failed to claim number');
        }
    };

    const handleClaimSubmit = async () => {
        if (!showClaimModal) return;
        try {
            await phonePoolService.claimNumber(
                showClaimModal.id,
                claimCompanyId || undefined
            );
            setShowClaimModal(null);
            setClaimCompanyId('');
            fetchNumbers();
        } catch (err: any) {
            alert(err?.response?.data?.detail || 'Failed to claim number');
        }
    };

    const handleRelease = (id: string) => {
        setConfirmModal({
            message: 'Are you sure you want to release this number back to the pool? The agent and customer assignments will be removed.',
            action: async () => {
                await phonePoolService.releaseNumber(id);
                fetchNumbers();
            },
        });
    };

    const handleAssign = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!showAssignModal) return;
        try {
            await phonePoolService.assignAgent(showAssignModal.id, {
                agent_id: assignForm.agent_id,
                customer_name: assignForm.customer_name || undefined,
            });
            setShowAssignModal(null);
            setAssignForm({ agent_id: '', customer_name: '' });
            fetchNumbers();
        } catch (err: any) {
            alert(err?.response?.data?.detail || 'Failed to assign');
        }
    };

    const handleToggleActive = async (id: string, currentActive: boolean) => {
        try {
            await phonePoolService.updateNumber(id, { is_active: !currentActive });
            fetchNumbers();
        } catch (err: any) {
            alert(err?.response?.data?.detail || 'Failed to update');
        }
    };

    const handleDelete = (id: string) => {
        setConfirmModal({
            message: 'Are you sure you want to permanently delete this phone number? This action cannot be undone.',
            action: async () => {
                await phonePoolService.deleteNumber(id);
                fetchNumbers();
            },
        });
    };

    const handleConfirmAction = async () => {
        if (!confirmModal) return;
        setConfirmLoading(true);
        try {
            await confirmModal.action();
            setConfirmModal(null);
        } catch (err: any) {
            alert(err?.response?.data?.detail || 'Operation failed');
        } finally {
            setConfirmLoading(false);
        }
    };

    const handleOpenEdit = (n: PhoneNumberEntry) => {
        setShowEditModal(n);
        setEditForm({
            phone_number: n.phone_number,
            provider: n.provider,
            label: n.label || '',
            notes: n.notes || '',
        });
    };

    const handleEditSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!showEditModal) return;
        try {
            const updates: any = {};
            if (editForm.phone_number !== showEditModal.phone_number) updates.phone_number = editForm.phone_number;
            if (editForm.provider !== showEditModal.provider) updates.provider = editForm.provider;
            if (editForm.label !== (showEditModal.label || '')) updates.label = editForm.label;
            if (editForm.notes !== (showEditModal.notes || '')) updates.notes = editForm.notes;

            if (Object.keys(updates).length === 0) {
                setShowEditModal(null);
                return;
            }

            await phonePoolService.updateNumber(showEditModal.id, updates);
            setShowEditModal(null);
            fetchNumbers();
        } catch (err: any) {
            alert(err?.response?.data?.detail || 'Failed to update number');
        }
    };

    const getStatusBadgeClass = (status: string) => {
        switch (status) {
            case 'available': return 'status-badge available';
            case 'claimed': return 'status-badge claimed';
            case 'assigned': return 'status-badge assigned';
            case 'retired': return 'status-badge retired';
            default: return 'status-badge';
        }
    };

    const renderSyncProviderResult = (provider: string, label: string, data: any) => {
        if (!data) return null;
        const isError = data.error;
        const hasWarning = data.warning;
        return (
            <div className={`sync-provider-result ${isError ? 'error' : hasWarning ? 'warning' : 'success'}`}>
                <div className="sync-provider-header">
                    <span className={`provider-badge ${provider}`}>{label}</span>
                    {isError ? (
                        <span className="sync-status-icon">⚠️</span>
                    ) : hasWarning ? (
                        <span className="sync-status-icon">⚠️</span>
                    ) : (
                        <span className="sync-status-icon">✅</span>
                    )}
                </div>
                {isError ? (
                    <p className="sync-error-msg">{data.error}</p>
                ) : (
                    <>
                        <div className="sync-stats">
                            <div className="sync-stat">
                                <span className="sync-stat-value success">{data.added ?? 0}</span>
                                <span className="sync-stat-label">Added</span>
                            </div>
                            <div className="sync-stat">
                                <span className="sync-stat-value skipped">{data.skipped ?? 0}</span>
                                <span className="sync-stat-label">Already in Pool</span>
                            </div>
                        </div>
                        {hasWarning && (
                            <p className="sync-warning-msg">{data.warning}</p>
                        )}
                    </>
                )}
            </div>
        );
    };

    return (
        <div className="phone-pool-page">
            <div className="page-header">
                <div>
                    <h1>Phone Numbers</h1>
                    <p className="subtitle">Unified inventory — sync, claim, and assign to agents</p>
                </div>
                <div className="header-actions-pool">
                    {isAdmin && (
                        <button
                            className="btn-sync-numbers"
                            onClick={handleSync}
                            disabled={syncing}
                        >
                            <span className={`sync-icon ${syncing ? 'spinning' : ''}`}>🔄</span>
                            {syncing ? 'Syncing…' : 'Sync from Providers'}
                        </button>
                    )}
                    <button className="btn-add-number" onClick={() => setShowAddModal(true)}>
                        + Add Number
                    </button>
                </div>
            </div>

            {/* Filters */}
            <div className="pool-filters">
                <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                    <option value="">All Statuses</option>
                    <option value="available">Available</option>
                    <option value="claimed">Claimed</option>
                    <option value="assigned">Assigned</option>
                    <option value="retired">Retired</option>
                </select>
                <select value={providerFilter} onChange={e => setProviderFilter(e.target.value)}>
                    <option value="">All Providers</option>
                    <option value="twilio">Twilio</option>
                    <option value="tata_tele">Tata Tele</option>
                </select>
            </div>

            {/* Table */}
            <div className="phone-table-container">
                {loading ? (
                    <div className="pool-empty"><div className="empty-icon">⏳</div><p>Loading...</p></div>
                ) : numbers.length === 0 ? (
                    <div className="pool-empty">
                        <div className="empty-icon">📱</div>
                        <h3>No phone numbers found</h3>
                        <p>Sync from providers or add numbers manually to get started.</p>
                    </div>
                ) : (
                    <table className="phone-table">
                        <thead>
                            <tr>
                                <th>Phone Number</th>
                                <th>Provider</th>
                                <th>Status</th>
                                <th>Agent</th>
                                <th>Customer</th>
                                <th>Label</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {numbers.map(n => (
                                <tr key={n.id}>
                                    <td className="phone-number">{n.phone_number}</td>
                                    <td>
                                        <span className={`provider-badge ${n.provider}`}>
                                            {n.provider === 'twilio' ? 'Twilio' : 'Tata Tele'}
                                        </span>
                                    </td>
                                    <td>
                                        <span className={getStatusBadgeClass(n.status)}>
                                            {n.status}
                                        </span>
                                        {!n.is_active && (
                                            <span className="status-badge retired" style={{ marginLeft: 6 }}>inactive</span>
                                        )}
                                    </td>
                                    <td>{n.agent_name || '—'}</td>
                                    <td>{n.customer_name || '—'}</td>
                                    <td>{n.label || '—'}</td>
                                    <td className="actions-cell">
                                        {n.status === 'available' && (
                                            <button className="btn-claim" onClick={() => handleClaim(n)}>
                                                Claim
                                            </button>
                                        )}
                                        {n.status === 'claimed' && (
                                            <>
                                                <button
                                                    className="btn-claim"
                                                    onClick={() => {
                                                        setShowAssignModal(n);
                                                        setAssignForm({ agent_id: '', customer_name: '' });
                                                        fetchAgents(); // Refresh agent list on every open
                                                    }}
                                                >
                                                    Assign Agent
                                                </button>
                                                <button className="btn-release" onClick={() => handleRelease(n.id)}>
                                                    Release
                                                </button>
                                            </>
                                        )}
                                        {n.status === 'assigned' && (
                                            <>
                                                <button
                                                    className="btn-icon"
                                                    onClick={() => handleToggleActive(n.id, n.is_active)}
                                                    title={n.is_active ? 'Deactivate' : 'Activate'}
                                                >
                                                    {n.is_active ? '⏸' : '▶'}
                                                </button>
                                                <button className="btn-release" onClick={() => handleRelease(n.id)}>
                                                    Release
                                                </button>
                                            </>
                                        )}
                                        <button className="btn-icon" onClick={() => handleOpenEdit(n)} title="Edit">
                                            ✏️
                                        </button>
                                        <button className="btn-delete" onClick={() => handleDelete(n.id)}>
                                            🗑
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            {/* Confirmation Modal (replaces window.confirm) */}
            {confirmModal && (
                <div className="pool-modal-overlay" onClick={() => !confirmLoading && setConfirmModal(null)}>
                    <div className="pool-modal confirm-modal" onClick={e => e.stopPropagation()}>
                        <div className="confirm-icon">⚠️</div>
                        <h3>Confirm Action</h3>
                        <p className="confirm-message">{confirmModal.message}</p>
                        <div className="pool-modal-actions">
                            <button
                                type="button"
                                className="btn-release"
                                onClick={() => setConfirmModal(null)}
                                disabled={confirmLoading}
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                className="btn-confirm-danger"
                                onClick={handleConfirmAction}
                                disabled={confirmLoading}
                            >
                                {confirmLoading ? 'Processing…' : 'Confirm'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Sync Results Modal */}
            {syncResult && (
                <div className="pool-modal-overlay" onClick={() => setSyncResult(null)}>
                    <div className="pool-modal sync-results-modal" onClick={e => e.stopPropagation()}>
                        <h3>Sync Results</h3>
                        <p className="sync-results-subtitle">Numbers synced from your configured providers</p>
                        <div className="sync-results-list">
                            {renderSyncProviderResult('twilio', 'Twilio', syncResult.twilio)}
                            {renderSyncProviderResult('tata_tele', 'Tata Tele', syncResult.tata_tele)}
                            {syncResult.error && <p className="sync-error-msg">{syncResult.error}</p>}
                        </div>
                        <div className="pool-modal-actions">
                            <button className="btn-add-number" onClick={() => setSyncResult(null)}>Done</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Add Number Modal */}
            {showAddModal && (
                <div className="pool-modal-overlay" onClick={() => setShowAddModal(false)}>
                    <div className="pool-modal" onClick={e => e.stopPropagation()}>
                        <h3>Add Phone Number</h3>
                        <form onSubmit={handleAddNumber}>
                            <div className="add-number-form">
                                <div className="form-group">
                                    <label>Phone Number</label>
                                    <input
                                        type="tel"
                                        value={addForm.phone_number}
                                        onChange={e => setAddForm({ ...addForm, phone_number: e.target.value })}
                                        placeholder="918065251146"
                                        required
                                    />
                                </div>
                                <div className="form-group">
                                    <label>Provider</label>
                                    <select
                                        value={addForm.provider}
                                        onChange={e => setAddForm({ ...addForm, provider: e.target.value })}
                                    >
                                        <option value="tata_tele">Tata Tele</option>
                                        <option value="twilio">Twilio</option>
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label>Label (optional)</label>
                                    <input
                                        type="text"
                                        value={addForm.label}
                                        onChange={e => setAddForm({ ...addForm, label: e.target.value })}
                                        placeholder="Sales line, Support, etc."
                                    />
                                </div>
                                <div className="form-group">
                                    <label>Country Code</label>
                                    <select
                                        value={addForm.country_code}
                                        onChange={e => setAddForm({ ...addForm, country_code: e.target.value })}
                                    >
                                        <option value="+91">+91 (India)</option>
                                        <option value="+1">+1 (US)</option>
                                        <option value="+44">+44 (UK)</option>
                                    </select>
                                </div>
                                <div className="form-group full-width">
                                    <label>Notes (optional)</label>
                                    <input
                                        type="text"
                                        value={addForm.notes}
                                        onChange={e => setAddForm({ ...addForm, notes: e.target.value })}
                                        placeholder="Internal notes..."
                                    />
                                </div>
                            </div>
                            <div className="pool-modal-actions">
                                <button type="button" className="btn-release" onClick={() => setShowAddModal(false)}>Cancel</button>
                                <button type="submit" className="btn-add-number">Add Number</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Assign Agent Modal */}
            {showAssignModal && (
                <div className="pool-modal-overlay" onClick={() => setShowAssignModal(null)}>
                    <div className="pool-modal" onClick={e => e.stopPropagation()}>
                        <h3>Assign Agent to {showAssignModal.phone_number}</h3>
                        <form onSubmit={handleAssign}>
                            <div className="add-number-form">
                                <div className="form-group full-width">
                                    <label>Agent</label>
                                    <select
                                        value={assignForm.agent_id}
                                        onChange={e => setAssignForm({ ...assignForm, agent_id: e.target.value })}
                                        required
                                    >
                                        <option value="">Select an agent...</option>
                                        {agents.map(a => (
                                            <option key={a.id} value={a.id}>{a.name}</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="form-group full-width">
                                    <label>Customer (optional)</label>
                                    <select
                                        value={assignForm.customer_name}
                                        onChange={e => setAssignForm({ ...assignForm, customer_name: e.target.value })}
                                    >
                                        <option value="">Select a customer...</option>
                                        {customers.map(c => (
                                            <option key={c.id} value={c.name}>{c.name} ({c.type})</option>
                                        ))}
                                    </select>
                                </div>
                            </div>
                            <div className="pool-modal-actions">
                                <button type="button" className="btn-release" onClick={() => setShowAssignModal(null)}>Cancel</button>
                                <button type="submit" className="btn-add-number">Assign</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Claim with Company Modal (app_admin) */}
            {showClaimModal && (
                <div className="pool-modal-overlay" onClick={() => setShowClaimModal(null)}>
                    <div className="pool-modal" onClick={e => e.stopPropagation()}>
                        <h3>Claim {showClaimModal.phone_number}</h3>
                        <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                            Select which company this number should belong to. This company will be billed for all calls on this number.
                        </p>
                        <div className="add-number-form">
                            <div className="form-group full-width">
                                <label>Company *</label>
                                <select
                                    value={claimCompanyId}
                                    onChange={e => setClaimCompanyId(e.target.value)}
                                    required
                                >
                                    <option value="">-- Select Company --</option>
                                    {companies.map(c => (
                                        <option key={c.id} value={c.id}>
                                            {c.name} ({c.type})
                                        </option>
                                    ))}
                                </select>
                            </div>
                        </div>
                        <div className="pool-modal-actions">
                            <button type="button" className="btn-release" onClick={() => setShowClaimModal(null)}>Cancel</button>
                            <button
                                type="button"
                                className="btn-add-number"
                                onClick={handleClaimSubmit}
                                disabled={!claimCompanyId}
                            >
                                Claim for Company
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Edit Number Modal */}
            {showEditModal && (
                <div className="pool-modal-overlay" onClick={() => setShowEditModal(null)}>
                    <div className="pool-modal" onClick={e => e.stopPropagation()}>
                        <h3>Edit Phone Number</h3>
                        <form onSubmit={handleEditSubmit}>
                            <div className="add-number-form">
                                <div className="form-group">
                                    <label>Phone Number</label>
                                    <input
                                        type="tel"
                                        value={editForm.phone_number}
                                        onChange={e => setEditForm({ ...editForm, phone_number: e.target.value })}
                                        placeholder="918065251146"
                                        required
                                    />
                                </div>
                                <div className="form-group">
                                    <label>Provider</label>
                                    <select
                                        value={editForm.provider}
                                        onChange={e => setEditForm({ ...editForm, provider: e.target.value })}
                                    >
                                        <option value="tata_tele">Tata Tele</option>
                                        <option value="twilio">Twilio</option>
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label>Label (optional)</label>
                                    <input
                                        type="text"
                                        value={editForm.label}
                                        onChange={e => setEditForm({ ...editForm, label: e.target.value })}
                                        placeholder="Sales line, Support, etc."
                                    />
                                </div>
                                <div className="form-group full-width">
                                    <label>Notes (optional)</label>
                                    <input
                                        type="text"
                                        value={editForm.notes}
                                        onChange={e => setEditForm({ ...editForm, notes: e.target.value })}
                                        placeholder="Internal notes..."
                                    />
                                </div>
                            </div>
                            <div className="pool-modal-actions">
                                <button type="button" className="btn-release" onClick={() => setShowEditModal(null)}>Cancel</button>
                                <button type="submit" className="btn-add-number">Save Changes</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default PhonePool;
