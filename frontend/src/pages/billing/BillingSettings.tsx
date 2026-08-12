import React, { useState, useEffect } from 'react';
import { DollarSign, Settings, Save, Plus, Trash2, Edit } from 'lucide-react';
import { billingService, BillingConfig, SubscriptionTier } from '@/services/billing.service';
import './BillingSettings.css';

export const BillingSettings: React.FC = () => {
    const [config, setConfig] = useState<Partial<BillingConfig>>({});
    const [tiers, setTiers] = useState<SubscriptionTier[]>([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [successMsg, setSuccessMsg] = useState<string | null>(null);

    // Form state for creating/editing tier
    const [showTierModal, setShowTierModal] = useState(false);
    const [editingTier, setEditingTier] = useState<Partial<SubscriptionTier>>({});

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        setLoading(true);
        try {
            const [configRes, tiersRes] = await Promise.all([
                billingService.getConfig(),
                billingService.getSubscriptionTiers()
            ]);

            if (configRes.config) {
                setConfig(configRes.config);
            } else {
                // Initialize default empty
                setConfig({
                    multiplier_factor: 1.0,
                    platform_fee_pct: 0.0,
                    sales_partner_fee_pct: 0.0,
                    discount_pct: 0.0,
                    default_daily_credits: 0,
                });
            }
            setTiers(tiersRes);
        } catch (err: any) {
            setError(err?.response?.data?.detail || 'Failed to load billing configuration.');
        } finally {
            setLoading(false);
        }
    };

    const handleConfigSave = async () => {
        setSaving(true);
        setError(null);
        setSuccessMsg(null);
        try {
            const payload = {
                multiplier_factor: config.multiplier_factor,
                platform_fee_pct: config.platform_fee_pct,
                sales_partner_fee_pct: config.sales_partner_fee_pct,
                discount_pct: config.discount_pct,
                default_daily_credits: config.default_daily_credits,
                base_cost_telephony: config.base_cost_telephony || undefined,
                base_cost_llm: config.base_cost_llm || undefined,
                base_cost_image_gen: config.base_cost_image_gen || undefined,
            };
            const res = await billingService.updateConfig(payload);
            setConfig(res.config);
            setSuccessMsg('Billing configuration saved successfully.');
        } catch (err: any) {
            setError(err?.response?.data?.detail || 'Failed to save billing configuration.');
        } finally {
            setSaving(false);
        }
    };

    const handleTierSave = async () => {
        setError(null);
        try {
            if (editingTier.id) {
                await billingService.updateSubscriptionTier(editingTier.id, {
                    name: editingTier.name,
                    monthly_fee: editingTier.monthly_fee,
                    bonus_pct: editingTier.bonus_pct,
                    is_active: editingTier.is_active,
                });
            } else {
                await billingService.createSubscriptionTier({
                    name: editingTier.name || '',
                    tier_level: editingTier.tier_level || 0,
                    monthly_fee: editingTier.monthly_fee || 0,
                    bonus_pct: editingTier.bonus_pct || 0,
                    is_active: editingTier.is_active !== false,
                });
            }
            setShowTierModal(false);
            fetchData();
            setSuccessMsg('Subscription tier saved successfully.');
        } catch (err: any) {
            setError(err?.response?.data?.detail || 'Failed to save subscription tier.');
        }
    };

    const handleDeleteTier = async (id: string) => {
        if (!confirm('Are you sure you want to delete this subscription tier?')) return;
        try {
            await billingService.deleteSubscriptionTier(id);
            fetchData();
            setSuccessMsg('Subscription tier deleted.');
        } catch (err: any) {
            setError(err?.response?.data?.detail || 'Failed to delete tier.');
        }
    };

    if (loading) {
        return <div className="loading-state"><div className="pulse">Loading Settings...</div></div>;
    }

    return (
        <div className="billing-settings-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title">
                        <Settings size={28} className="mr-3" />
                        Billing & Subscription Administration
                    </h1>
                    <p className="page-subtitle">Configure formula parameters, costs, tier rules, and feature allocations</p>
                </div>
            </div>

            {error && <div className="error-banner glass">{error}</div>}
            {successMsg && <div className="success-banner glass">{successMsg}</div>}

            <div className="settings-grid">
                {/* Global Config Section */}
                <div className="settings-card glass">
                    <h2><DollarSign size={18} /> Default Global Settings</h2>
                    <p className="card-desc">Controls the primary billing variables calculated via TB formula.</p>

                    <div className="form-group">
                        <label>Multiplier Factor (mf)</label>
                        <input
                            type="number" step="0.01"
                            value={config.multiplier_factor || ''}
                            onChange={e => setConfig({ ...config, multiplier_factor: parseFloat(e.target.value) })}
                        />
                    </div>

                    <div className="form-row">
                        <div className="form-group">
                            <label>Platform Fee % (pf)</label>
                            <input
                                type="number" step="0.01"
                                value={config.platform_fee_pct || ''}
                                onChange={e => setConfig({ ...config, platform_fee_pct: parseFloat(e.target.value) })}
                            />
                        </div>
                        <div className="form-group">
                            <label>Partner Fee % (spf)</label>
                            <input
                                type="number" step="0.01"
                                value={config.sales_partner_fee_pct || ''}
                                onChange={e => setConfig({ ...config, sales_partner_fee_pct: parseFloat(e.target.value) })}
                            />
                        </div>
                        <div className="form-group">
                            <label>Discount % (d)</label>
                            <input
                                type="number" step="0.01"
                                value={config.discount_pct || ''}
                                onChange={e => setConfig({ ...config, discount_pct: parseFloat(e.target.value) })}
                            />
                        </div>
                    </div>

                    <div className="form-group mb-4">
                        <label>Default Daily Credits ($)</label>
                        <input
                            type="number" step="0.50"
                            value={config.default_daily_credits || ''}
                            onChange={e => setConfig({ ...config, default_daily_credits: parseFloat(e.target.value) })}
                        />
                    </div>

                    <hr className="divider" />
                    <h3 className="section-subtitle mt-4">Base Cost Overrides</h3>
                    <p className="card-desc">Optional overrides to standard API cost rates. Leave empty to use exact usage rates.</p>

                    <div className="form-row">
                        <div className="form-group">
                            <label>Telephony ($/min)</label>
                            <input
                                type="number" step="0.0001"
                                value={config.base_cost_telephony || ''}
                                onChange={e => setConfig({ ...config, base_cost_telephony: parseFloat(e.target.value) || null })}
                                placeholder="0.008"
                            />
                        </div>
                        <div className="form-group">
                            <label>Image Gen ($/image)</label>
                            <input
                                type="number" step="0.0001"
                                value={config.base_cost_image_gen || ''}
                                onChange={e => setConfig({ ...config, base_cost_image_gen: parseFloat(e.target.value) || null })}
                                placeholder="0.05"
                            />
                        </div>
                        <div className="form-group">
                            <label>LLM Overlay ($/call)</label>
                            <input
                                type="number" step="0.0001"
                                value={config.base_cost_llm || ''}
                                onChange={e => setConfig({ ...config, base_cost_llm: parseFloat(e.target.value) || null })}
                            />
                        </div>
                    </div>

                    <button className="btn-primary mt-4 w-full" onClick={handleConfigSave} disabled={saving}>
                        <Save size={16} /> {saving ? 'Saving...' : 'Save Global Settings'}
                    </button>
                </div>

                {/* Subscriptions Section */}
                <div className="settings-card glass">
                    <div className="tier-header">
                        <div>
                            <h2>Subscription Tiers</h2>
                            <p className="card-desc">Manage tiers shown to tenants/users</p>
                        </div>
                        <button className="btn-secondary" onClick={() => { setEditingTier({}); setShowTierModal(true); }}>
                            <Plus size={16} /> New Tier
                        </button>
                    </div>

                    <div className="tier-list">
                        {tiers.length === 0 && <p className="empty-text">No active tiers configured.</p>}
                        {tiers.map(tier => (
                            <div key={tier.id} className="tier-item">
                                <div className="tier-info">
                                    <span className="tier-badge">Level {tier.tier_level}</span>
                                    <h4>{tier.name}</h4>
                                    <div className="tier-meta">
                                        <span>${tier.monthly_fee}/mo</span>
                                        <span>• {tier.bonus_pct}% Bonus</span>
                                        <span className={tier.is_active ? 'active' : 'inactive'}>
                                            {tier.is_active ? 'Active' : 'Archived'}
                                        </span>
                                    </div>
                                </div>
                                <div className="tier-actions">
                                    <button onClick={() => { setEditingTier(tier); setShowTierModal(true); }}><Edit size={16} /></button>
                                    <button className="text-error" onClick={() => handleDeleteTier(tier.id)}><Trash2 size={16} /></button>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Modal for Tiers */}
            {showTierModal && (
                <div className="modal-overlay">
                    <div className="modal-content glass">
                        <h3>{editingTier.id ? 'Edit Tier' : 'Create New Tier'}</h3>

                        <div className="form-group">
                            <label>Tier Name (e.g., Pro Plan)</label>
                            <input
                                type="text" value={editingTier.name || ''}
                                onChange={e => setEditingTier({ ...editingTier, name: e.target.value })}
                            />
                        </div>

                        {!editingTier.id && (
                            <div className="form-group">
                                <label>Tier Level (1, 2, 3...)</label>
                                <input
                                    type="number" value={editingTier.tier_level || ''}
                                    onChange={e => setEditingTier({ ...editingTier, tier_level: parseInt(e.target.value) })}
                                />
                            </div>
                        )}

                        <div className="form-group">
                            <label>Monthly Fee ($)</label>
                            <input
                                type="number" step="0.01" value={editingTier.monthly_fee || ''}
                                onChange={e => setEditingTier({ ...editingTier, monthly_fee: parseFloat(e.target.value) })}
                            />
                        </div>

                        <div className="form-group">
                            <label>Bonus Credit Percentage (%)</label>
                            <input
                                type="number" step="0.1" value={editingTier.bonus_pct || ''}
                                onChange={e => setEditingTier({ ...editingTier, bonus_pct: parseFloat(e.target.value) })}
                            />
                        </div>

                        <div className="form-group checkbox-group">
                            <input
                                type="checkbox" id="activeToggle"
                                checked={editingTier.is_active !== false}
                                onChange={e => setEditingTier({ ...editingTier, is_active: e.target.checked })}
                            />
                            <label htmlFor="activeToggle">Tier is Active and visible to users</label>
                        </div>

                        <div className="modal-actions">
                            <button className="btn-secondary" onClick={() => setShowTierModal(false)}>Cancel</button>
                            <button className="btn-primary" onClick={handleTierSave}>
                                <Save size={16} /> Save Tier
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
