/**
 * pages/admin/FeatureFlagsPage — View & toggle Phase 11 feature flags.
 *
 * Tabs:
 *   1. Effective — what THIS user/company sees right now (defaults +
 *      overrides applied).
 *   2. Admin     — every row in `feature_flags` visible to the caller,
 *      with toggle/delete actions and a "create override" form.
 *   3. Numeric   — float / int knobs.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useAuth } from '@/hooks/useAuth';
import { featureFlagsService } from '@/services/feature_flags.service';
import type { FeatureFlagRow, FeatureFlagsResponse } from '@/types/agentKernel';
import { UserRole } from '@/types';

import './FeatureFlagsPage.css';

type Tab = 'effective' | 'admin' | 'numeric';

export const FeatureFlagsPage: React.FC = () => {
    const { user } = useAuth();
    const [tab, setTab] = useState<Tab>('effective');
    const [data, setData] = useState<FeatureFlagsResponse | null>(null);
    const [loading, setLoading] = useState(true);

    const isAppAdmin = user?.role === UserRole.APP_ADMIN;

    const refreshEffective = useCallback(() => {
        setLoading(true);
        featureFlagsService.fetchMine()
            .then(setData)
            .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        refreshEffective();
    }, [refreshEffective]);

    if (loading && !data) return <p>loading…</p>;

    return (
        <div className="page-container ff-page">
            <header className="page-header">
                <h1>Feature Flags</h1>
                <p>
                    Phase 11 feature-flag scope tiers: defaults &lt; global &lt;
                    per-company &lt; per-entity. Higher tiers win.
                </p>
            </header>

            <nav className="ff-page__tabs">
                <button
                    className={tab === 'effective' ? 'active' : ''}
                    onClick={() => setTab('effective')}
                >Effective</button>
                <button
                    className={tab === 'admin' ? 'active' : ''}
                    onClick={() => setTab('admin')}
                >Admin</button>
                <button
                    className={tab === 'numeric' ? 'active' : ''}
                    onClick={() => setTab('numeric')}
                >Numeric</button>
                <button
                    className="ff-page__refresh"
                    onClick={refreshEffective}
                    title="Re-fetch /feature_flags/me"
                >↻ refresh</button>
            </nav>

            {tab === 'effective' && data && <EffectiveTab data={data} />}
            {tab === 'admin' && (
                <AdminTab
                    isAppAdmin={isAppAdmin}
                    onChange={refreshEffective}
                    companyId={user?.company_id ?? null}
                />
            )}
            {tab === 'numeric' && data && <NumericTab data={data} />}
        </div>
    );
};

// ---------------------------------------------------------------------------
// Tab: Effective
// ---------------------------------------------------------------------------

const EffectiveTab: React.FC<{ data: FeatureFlagsResponse }> = ({ data }) => {
    const rows = useMemo(() => {
        const keys = new Set<string>([
            ...Object.keys(data.defaults ?? {}),
            ...Object.keys(data.overrides ?? {}),
        ]);
        return [...keys].sort().map((k) => {
            const ov = data.overrides?.[k];
            const eff = ov?.company ?? ov?.global ?? data.defaults?.[k] ?? false;
            const source = ov?.company !== undefined
                ? 'company'
                : ov?.global !== undefined
                    ? 'global'
                    : 'default';
            return { key: k, effective: eff, source };
        });
    }, [data]);

    return (
        <table className="ff-page__table">
            <thead>
                <tr>
                    <th>flag</th>
                    <th>effective</th>
                    <th>source</th>
                </tr>
            </thead>
            <tbody>
                {rows.map((r) => (
                    <tr key={r.key}>
                        <td className="ff-page__key">{r.key}</td>
                        <td>
                            <span
                                className={`ff-page__pill ff-page__pill--${r.effective ? 'on' : 'off'}`}
                            >
                                {r.effective ? 'ON' : 'OFF'}
                            </span>
                        </td>
                        <td className="ff-page__source">{r.source}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
};

// ---------------------------------------------------------------------------
// Tab: Admin (toggle + delete + create)
// ---------------------------------------------------------------------------

interface AdminTabProps {
    isAppAdmin: boolean;
    companyId: string | null;
    onChange: () => void;
}

const AdminTab: React.FC<AdminTabProps> = ({ isAppAdmin, companyId, onChange }) => {
    const [rows, setRows] = useState<FeatureFlagRow[]>([]);
    const [loading, setLoading] = useState(true);
    const [scope, setScope] = useState<'all' | 'global' | 'company' | 'entity'>('all');
    const [busy, setBusy] = useState<string | null>(null);
    const [showCreate, setShowCreate] = useState(false);

    const reload = useCallback(() => {
        setLoading(true);
        featureFlagsService.listAdmin(scope)
            .then(setRows)
            .finally(() => setLoading(false));
    }, [scope]);

    useEffect(() => {
        reload();
    }, [reload]);

    const toggleRow = async (row: FeatureFlagRow) => {
        setBusy(row.id);
        try {
            await featureFlagsService.set(row.flag_key, {
                scope: row.scope,
                enabled: !row.enabled,
                company_id: row.company_id ?? undefined,
                entity_id: row.entity_id ?? undefined,
            });
            await reload();
            onChange();
        } catch (e: any) {
            // eslint-disable-next-line no-alert
            alert(`toggle failed: ${e?.response?.data?.detail ?? e}`);
        } finally {
            setBusy(null);
        }
    };

    const deleteRow = async (row: FeatureFlagRow) => {
        // eslint-disable-next-line no-alert
        if (!window.confirm(`Delete ${row.scope} override for ${row.flag_key}?`)) return;
        setBusy(row.id);
        try {
            await featureFlagsService.remove(row.flag_key, row.scope, {
                company_id: row.company_id ?? undefined,
                entity_id: row.entity_id ?? undefined,
            });
            await reload();
            onChange();
        } catch (e: any) {
            // eslint-disable-next-line no-alert
            alert(`delete failed: ${e?.response?.data?.detail ?? e}`);
        } finally {
            setBusy(null);
        }
    };

    return (
        <>
            <div className="ff-page__admin-controls">
                <label>
                    scope:
                    <select value={scope} onChange={(e) => setScope(e.target.value as any)}>
                        <option value="all">all</option>
                        <option value="global">global</option>
                        <option value="company">per-company</option>
                        <option value="entity">per-entity</option>
                    </select>
                </label>
                <button onClick={() => setShowCreate((v) => !v)}>
                    {showCreate ? '× close' : '+ create override'}
                </button>
            </div>

            {showCreate && (
                <CreateOverrideForm
                    isAppAdmin={isAppAdmin}
                    defaultCompanyId={companyId}
                    onCreated={() => {
                        setShowCreate(false);
                        reload();
                        onChange();
                    }}
                />
            )}

            {loading ? (
                <p>loading…</p>
            ) : rows.length === 0 ? (
                <p className="ff-page__empty">no override rows for this scope</p>
            ) : (
                <table className="ff-page__table">
                    <thead>
                        <tr>
                            <th>flag</th>
                            <th>scope</th>
                            <th>company</th>
                            <th>entity</th>
                            <th>enabled</th>
                            <th>value_json</th>
                            <th>actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((r) => (
                            <tr key={r.id}>
                                <td className="ff-page__key">{r.flag_key}</td>
                                <td><span className={`ff-page__scope ff-page__scope--${r.scope}`}>{r.scope}</span></td>
                                <td className="ff-page__id">{r.company_id?.slice(0, 8) ?? '—'}</td>
                                <td className="ff-page__id">{r.entity_id?.slice(0, 8) ?? '—'}</td>
                                <td>
                                    <span className={`ff-page__pill ff-page__pill--${r.enabled ? 'on' : 'off'}`}>
                                        {r.enabled ? 'ON' : 'OFF'}
                                    </span>
                                </td>
                                <td className="ff-page__json">
                                    {r.value_json != null ? <code>{JSON.stringify(r.value_json)}</code> : '—'}
                                </td>
                                <td className="ff-page__actions">
                                    <button
                                        disabled={busy === r.id}
                                        onClick={() => toggleRow(r)}
                                    >toggle</button>
                                    <button
                                        disabled={busy === r.id}
                                        onClick={() => deleteRow(r)}
                                        className="ff-page__btn--danger"
                                    >delete</button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </>
    );
};

// ---------------------------------------------------------------------------
// Create override form
// ---------------------------------------------------------------------------

interface CreateFormProps {
    isAppAdmin: boolean;
    defaultCompanyId: string | null;
    onCreated: () => void;
}

const CreateOverrideForm: React.FC<CreateFormProps> = ({
    isAppAdmin, defaultCompanyId, onCreated,
}) => {
    const [flagKey, setFlagKey] = useState('');
    const [scope, setScope] = useState<'global' | 'company' | 'entity'>('company');
    const [enabled, setEnabled] = useState(true);
    const [companyId, setCompanyId] = useState(defaultCompanyId ?? '');
    const [entityId, setEntityId] = useState('');
    const [valueJsonText, setValueJsonText] = useState('');
    const [busy, setBusy] = useState(false);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!flagKey) return;
        let value_json: unknown;
        if (valueJsonText.trim()) {
            try {
                value_json = JSON.parse(valueJsonText);
            } catch (err) {
                // eslint-disable-next-line no-alert
                alert('value_json is not valid JSON');
                return;
            }
        }
        setBusy(true);
        try {
            await featureFlagsService.set(flagKey, {
                scope,
                enabled,
                company_id: scope !== 'global' ? companyId : undefined,
                entity_id: scope === 'entity' ? entityId : undefined,
                value_json,
            });
            onCreated();
            setFlagKey('');
            setValueJsonText('');
        } catch (e: any) {
            // eslint-disable-next-line no-alert
            alert(`create failed: ${e?.response?.data?.detail ?? e}`);
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="ff-page__create-form" onSubmit={submit}>
            <div>
                <label>flag_key</label>
                <input
                    value={flagKey}
                    onChange={(e) => setFlagKey(e.target.value)}
                    placeholder="agent_loop.enabled"
                    required
                />
            </div>
            <div>
                <label>scope</label>
                <select
                    value={scope}
                    onChange={(e) => setScope(e.target.value as any)}
                >
                    {isAppAdmin && <option value="global">global</option>}
                    <option value="company">company</option>
                    <option value="entity">entity</option>
                </select>
            </div>
            {scope !== 'global' && (
                <div>
                    <label>company_id</label>
                    <input
                        value={companyId}
                        onChange={(e) => setCompanyId(e.target.value)}
                        required
                    />
                </div>
            )}
            {scope === 'entity' && (
                <div>
                    <label>entity_id</label>
                    <input
                        value={entityId}
                        onChange={(e) => setEntityId(e.target.value)}
                        required
                    />
                </div>
            )}
            <div>
                <label>enabled</label>
                <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                />
            </div>
            <div className="ff-page__form-wide">
                <label>value_json (optional)</label>
                <input
                    value={valueJsonText}
                    onChange={(e) => setValueJsonText(e.target.value)}
                    placeholder="3.14 or {&quot;a&quot;:1}"
                />
            </div>
            <button type="submit" disabled={busy}>
                {busy ? 'creating…' : 'create'}
            </button>
        </form>
    );
};

// ---------------------------------------------------------------------------
// Tab: Numeric
// ---------------------------------------------------------------------------

const NumericTab: React.FC<{ data: FeatureFlagsResponse }> = ({ data }) => (
    <table className="ff-page__table">
        <thead>
            <tr><th>flag</th><th>value</th></tr>
        </thead>
        <tbody>
            {Object.entries(data.numeric_defaults ?? {}).sort().map(([k, v]) => (
                <tr key={k}>
                    <td className="ff-page__key">{k}</td>
                    <td>{v}</td>
                </tr>
            ))}
        </tbody>
    </table>
);

export default FeatureFlagsPage;
