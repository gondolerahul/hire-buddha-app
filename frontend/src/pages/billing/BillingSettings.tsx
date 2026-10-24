import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { DollarSign, Layers, Settings, Save } from 'lucide-react';
import { billingService, BillingConfig, FormulaVersion } from '@/services/billing.service';
import { parseServerDate } from '@/utils/datetime';
import './BillingSettings.css';
import { apiErrorMessage } from '@/utils/apiError';

// pf, spf and d are fractions: 0.15 is 15% (BC-21).
const asPercent = (v?: number | null) =>
    v === undefined || v === null || Number.isNaN(v) ? '' : `= ${(v * 100).toFixed(1)}%`;

export const BillingSettings: React.FC = () => {
    const [config, setConfig] = useState<Partial<BillingConfig>>({});
    // Formula versions, newest first, and why the next one is made (Phase 15 T3-2).
    const [history, setHistory] = useState<FormulaVersion[]>([]);
    const [reason, setReason] = useState('');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [successMsg, setSuccessMsg] = useState<string | null>(null);

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        setLoading(true);
        try {
            const configRes = await billingService.getConfig();

            if (configRes.config) {
                setConfig(configRes.config);
            } else {
                // The identity formula: billed = cost
                setConfig({ multiplier_factor: 1.0, platform_fee_pct: 0.0, discount_pct: 0.0 });
            }
            setHistory(configRes.history ?? []);
        } catch (err: any) {
            setError(apiErrorMessage(err, 'Failed to load billing configuration.'));
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
                discount_pct: config.discount_pct,
                reason: reason.trim() || undefined,
            };
            const res = await billingService.updateConfig(payload);
            setConfig(res.config);
            setHistory(res.history ?? []);
            setReason('');
            setSuccessMsg('Saved. A formula change is a new version: new usage is priced with it; a run already running keeps its formula.');
        } catch (err: any) {
            setError(apiErrorMessage(err, 'Failed to save billing configuration.'));
        } finally {
            setSaving(false);
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
                    <p className="page-subtitle">The usage price formula. Plans and what they include are on Plans &amp; Entitlements.</p>
                </div>
            </div>

            {error && <div className="error-banner glass">{error}</div>}
            {successMsg && <div className="success-banner glass">{successMsg}</div>}

            <div className="settings-grid">
                {/* Global Config Section */}
                <div className="settings-card glass">
                    <h2><DollarSign size={18} /> Default Global Settings</h2>
                    <p className="card-desc">The customer price of usage: TB = cost × mf × (1 + pf − d). Partners earn commission, not a share of the price.</p>

                    <div className="form-group">
                        <label>Multiplier Factor (mf)</label>
                        <input
                            type="number" step="0.01" min="0.01"
                            value={config.multiplier_factor || ''}
                            onChange={e => setConfig({ ...config, multiplier_factor: parseFloat(e.target.value) })}
                        />
                    </div>

                    <div className="form-row">
                        <div className="form-group">
                            <label>Platform Fee (pf) (fraction, 0–1)</label>
                            <input
                                type="number" step="0.01" min="0" max="1"
                                value={config.platform_fee_pct ?? ''}
                                onChange={e => setConfig({ ...config, platform_fee_pct: parseFloat(e.target.value) })}
                            />
                            <small className="field-hint">{asPercent(config.platform_fee_pct)}</small>
                        </div>
                        <div className="form-group">
                            <label>Discount (d) (fraction, 0–1)</label>
                            <input
                                type="number" step="0.01" min="0" max="1"
                                value={config.discount_pct ?? ''}
                                onChange={e => setConfig({ ...config, discount_pct: parseFloat(e.target.value) })}
                            />
                            <small className="field-hint">{asPercent(config.discount_pct)}</small>
                        </div>
                    </div>

                    <p className="field-hint mb-4">
                        Daily credits are policies now, set on <a href="/admin/daily-credits">Daily credits</a>.
                    </p>

                    <div className="form-group">
                        <label>Reason for the change (kept with the version)</label>
                        <input type="text" value={reason} onChange={e => setReason(e.target.value)} placeholder="e.g. Q4 price review" />
                    </div>

                    <hr className="divider" />
                    <h3 className="section-subtitle mt-4">Formula history</h3>
                    <p className="card-desc">A company's own telephony or image price is its registry row (System Integrations), not an override here.</p>
                    {history.length === 0 ? <p className="field-hint">No versions yet: billed = cost.</p> : (
                        <ul className="formula-history">
                            {history.map(v => (
                                <li key={v.id}>
                                    <strong>mf {v.multiplier_factor}, pf {v.platform_fee_pct}, d {v.discount_pct}</strong>
                                    {!v.active && ' (ended)'}
                                    {' · from '}{v.effective_from ? parseServerDate(v.effective_from).toLocaleString() : '—'}
                                    {v.reason ? ` · ${v.reason}` : ''}
                                </li>
                            ))}
                        </ul>
                    )}

                    <button className="btn-primary mt-4 w-full" onClick={handleConfigSave} disabled={saving}>
                        <Save size={16} /> {saving ? 'Saving...' : 'Save Global Settings'}
                    </button>
                </div>

                {/* Plans replaced subscription tiers (Phase 15 T6-1) */}
                <div className="settings-card glass">
                    <h2><Layers size={18} /> Plans</h2>
                    <p className="card-desc">
                        Plans — their price per currency, bonus, tolerance and entitlements — are managed
                        on <Link to="/admin/plans">Plans &amp; Entitlements</Link>.
                    </p>
                </div>
            </div>

        </div>
    );
};
