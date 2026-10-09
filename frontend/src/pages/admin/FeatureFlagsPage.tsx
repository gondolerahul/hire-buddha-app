/**
 * pages/admin/FeatureFlagsPage — View & toggle Phase 11 feature flags.
 *
 * Tabs:
 *   1. Effective — every boolean flag as it resolves for this company, and
 *      the tier that set it (GH-20): an entity, company or global row, the
 *      `AI_FLAG_` env var, or the code default.
 *   2. Admin     — every row in `feature_flags` visible to the caller,
 *      with toggle/delete actions and a "create override" form.
 *   3. Numeric   — float / int knobs, with their value and tier too.
 */
import React, { useCallback, useEffect, useState } from 'react';

import { useAuth } from '@/hooks/useAuth';
import { featureFlagsService } from '@/services/feature_flags.service';
import type { FeatureFlagRow, FlagExplanation, FlagSource } from '@/types/agentKernel';
import { UserRole } from '@/types';

import './FeatureFlagsPage.css';

type Tab = 'effective' | 'admin' | 'numeric';

/** Each tier, as the source column names it (GH-20). */
const SOURCE_LABELS: Record<FlagSource, string> = {
    entity_row: 'entity row',
    company: 'company row',
    global: 'global row',
    env: 'AI_FLAG_ env var',
    default: 'code default',
};

const SOURCE_HINTS: Record<FlagSource, string> = {
    entity_row: 'A feature_flags row for one entity',
    company: 'A feature_flags row for this company',
    global: 'A feature_flags row for every company',
    env: 'AI_FLAG_<KEY> in the environment of the API and the workers',
    default: 'No row and no env var: the default in backend/src/ai/core/feature_flags.py',
};

const SourceCell: React.FC<{ source: FlagSource }> = ({ source }) => (
    <td className="ff-page__source" title={SOURCE_HINTS[source] ?? ''}>
        {SOURCE_LABELS[source] ?? source}
    </td>
);

export const FeatureFlagsPage: React.FC = () => {
    const { user } = useAuth();
    const [tab, setTab] = useState<Tab>('effective');
    const [flags, setFlags] = useState<FlagExplanation[] | null>(null);
    const [loading, setLoading] = useState(true);

    const isAppAdmin = user?.role === UserRole.APP_ADMIN;

    const refreshEffective = useCallback(() => {
        setLoading(true);
        featureFlagsService.explain()
            .then(setFlags)
            .catch(() => setFlags([]))
            .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        refreshEffective();
    }, [refreshEffective]);

    if (loading && !flags) return <p>loading…</p>;

    return (
        <div className="page-container ff-page">
            <header className="page-header">
                <h1>Feature Flags</h1>
                <p>
                    A flag takes the first value it finds: an entity row, a company row,
                    a global row, the <code>AI_FLAG_</code> env var, then the code default.
                    The source column says which one set it.
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
                    title="Re-fetch /feature_flags/explain"
                >↻ refresh</button>
            </nav>

            {tab === 'effective' && flags && <EffectiveTab flags={flags.filter((f) => f.kind === 'boolean')} />}
            {tab === 'admin' && (
                <AdminTab
                    isAppAdmin={isAppAdmin}
                    onChange={refreshEffective}
                    companyId={user?.company_id ?? null}
                />
            )}
            {tab === 'numeric' && flags && <NumericTab flags={flags.filter((f) => f.kind === 'numeric')} />}
        </div>
    );
};

// ---------------------------------------------------------------------------
// Tab: Effective
// ---------------------------------------------------------------------------

const EffectiveTab: React.FC<{ flags: FlagExplanation[] }> = ({ flags }) => (
    <table className="ff-page__table">
        <thead>
            <tr>
                <th>flag</th>
                <th>effective</th>
                <th>source</th>
            </tr>
        </thead>
        <tbody>
            {flags.map((f) => (
                <tr key={f.flag_key}>
                    <td className="ff-page__key">{f.flag_key}</td>
                    <td>
                        <span className={`ff-page__pill ff-page__pill--${f.value ? 'on' : 'off'}`}>
                            {f.value ? 'ON' : 'OFF'}
                        </span>
                    </td>
                    <SourceCell source={f.source} />
                </tr>
            ))}
        </tbody>
    </table>
);

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
            alert(`toggle failed: ${e?.response?.data?.detail ?? e}`);
        } finally {
            setBusy(null);
        }
    };

    const deleteRow = async (row: FeatureFlagRow) => {
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

const NumericTab: React.FC<{ flags: FlagExplanation[] }> = ({ flags }) => (
    <table className="ff-page__table">
        <thead>
            <tr><th>flag</th><th>value</th><th>source</th></tr>
        </thead>
        <tbody>
            {flags.map((f) => (
                <tr key={f.flag_key}>
                    <td className="ff-page__key">{f.flag_key}</td>
                    <td>{String(f.value)}</td>
                    <SourceCell source={f.source} />
                </tr>
            ))}
        </tbody>
    </table>
);

export default FeatureFlagsPage;
