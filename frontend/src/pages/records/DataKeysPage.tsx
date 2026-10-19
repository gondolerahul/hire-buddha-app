/**
 * pages/records/DataKeysPage — keys for the business's records (Phase 14 WS8 8.2; functional spec §5.1).
 *
 * A key is limited to chosen tables and actions and shown **once**. Keys an
 * app made for the public (a website's form) work only while **public API
 * access** is on — off by default. The API docs always match the tables.
 */
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { JellyButton } from '@/components/ui';
import { ago } from '@/components/automation/describe';
import { useAuth } from '@/hooks/useAuth';
import { problemText, recordsService, type DataKey } from '@/services/records.service';
import { UserRole } from '@/types';

import '@/components/automation/automation.css';

const ADMINS = [UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN];
const OPERATIONS = ['read', 'create', 'update', 'delete'];

export const canDo = (key: DataKey): string =>
    Object.entries(key.scopes.objects || {}).map(([object, ops]) =>
        `${object === '*' ? 'Everything' : object}: ${ops.length === 4 ? 'read/write/delete' : ops.join('/')}`).join(' · ');

const usedBy = (key: DataKey): string =>
    key.scopes.public ? 'Website (public)' : key.name.startsWith('app ') ? `App: ${key.name.slice(4)}`
        : key.external ? 'Outside system' : 'App';

export const DataKeysPage: React.FC = () => {
    const { user } = useAuth();
    const admin = ADMINS.includes(user?.role as UserRole);
    const queryClient = useQueryClient();
    const keys = useQuery({ queryKey: ['records', 'keys'], queryFn: recordsService.keys, enabled: admin });
    const settings = useQuery({ queryKey: ['records', 'settings'], queryFn: recordsService.settings });
    const schema = useQuery({ queryKey: ['records', 'schema'], queryFn: recordsService.schema });
    const [creating, setCreating] = useState(false);
    const [name, setName] = useState('');
    const [external, setExternal] = useState(false);
    const [grants, setGrants] = useState<Record<string, string[]>>({});
    const [shownKey, setShownKey] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const refresh = () => queryClient.invalidateQueries({ queryKey: ['records'] });

    if (!admin) return <div className="page-container ar-page"><h1>API keys</h1>
        <p className="ar-note">Owners and admins manage keys.</p></div>;

    const toggle = (object: string, op: string) => {
        const ops = new Set(grants[object] || []);
        if (ops.has(op)) ops.delete(op); else ops.add(op);
        setGrants({ ...grants, [object]: OPERATIONS.filter(o => ops.has(o)) });
    };
    const create = async () => {
        setError(null);
        const objects = Object.fromEntries(Object.entries(grants).filter(([, ops]) => ops.length));
        try {
            const made = await recordsService.createKey(name, objects, external);
            setShownKey(made.key);
            setCreating(false);
            setName('');
            setGrants({});
            refresh();
        } catch (err) {
            setError(problemText(err, 'Could not make the key.'));
        }
    };
    const live = (keys.data || []).filter(k => !k.revoked_at);
    const publicOn = settings.data?.public_api_access ?? false;

    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>API keys</h1>
                    <p>Apps and outside systems reach your records only with a key, limited to the tables and actions you choose.</p>
                </div>
                <div className="ar-row">
                    <Link to="/records" className="ar-link">Records</Link>
                    <a className="ar-link" href={recordsService.docsUrl} target="_blank" rel="noreferrer"
                       onClick={async e => {
                           e.preventDefault();
                           const doc = await recordsService.openapi();
                           const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }));
                           window.open(url, '_blank', 'noopener');
                       }}>API docs</a>
                    <JellyButton size="sm" onClick={() => setCreating(true)}>+ New key</JellyButton>
                </div>
            </header>
            {shownKey && (
                <div className="ar-section" role="status" aria-label="New key">
                    <h2>Your new key</h2>
                    <p className="ar-note">Copy it now: it is not shown again.</p>
                    <code className="ar-mono" style={{ wordBreak: 'break-all' }}>{shownKey}</code>
                    <div className="ar-actions">
                        <JellyButton size="sm" variant="ghost" onClick={() => navigator.clipboard?.writeText(shownKey)}>Copy</JellyButton>
                        <JellyButton size="sm" onClick={() => setShownKey(null)}>Done</JellyButton>
                    </div>
                </div>
            )}
            {creating && (
                <section className="ar-section" aria-label="New key">
                    <h2>New key</h2>
                    <div className="ar-row">
                        <label className="ar-field"><span>Name</span>
                            <input className="ar-input" value={name} onChange={e => setName(e.target.value)} /></label>
                        <label className="ar-check ar-check--small">
                            <input type="checkbox" checked={external} onChange={e => setExternal(e.target.checked)} />
                            <span>For an outside system (a lower rate)</span>
                        </label>
                    </div>
                    <table className="ar-table" aria-label="What the key may do">
                        <thead><tr><th>Table</th>{OPERATIONS.map(o => <th key={o}>{o}</th>)}</tr></thead>
                        <tbody>
                            {Object.entries(schema.data?.objects || {}).map(([object, spec]) => (
                                <tr key={object}><td>{spec.plural}</td>
                                    {OPERATIONS.map(op => (
                                        <td key={op}><input type="checkbox" aria-label={`${op} ${object}`}
                                                            checked={(grants[object] || []).includes(op)}
                                                            onChange={() => toggle(object, op)} /></td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {error && <p className="ar-note ar-note--bad" role="alert">{error}</p>}
                    <div className="ar-actions">
                        <JellyButton variant="ghost" size="sm" onClick={() => setCreating(false)}>Cancel</JellyButton>
                        <JellyButton size="sm" disabled={!name.trim()} onClick={create}>Make key</JellyButton>
                    </div>
                </section>
            )}
            <table className="ar-table" aria-label="Keys">
                <thead><tr><th>Name</th><th>Used by</th><th>Can do</th><th>Last used</th><th /></tr></thead>
                <tbody>
                    {live.map(k => (
                        <tr key={k.id}>
                            <td>{k.name}<div className="ar-mono">{k.prefix}…</div></td>
                            <td>{usedBy(k)}</td>
                            <td>{canDo(k)}</td>
                            <td>{k.last_used_at ? ago(k.last_used_at) : 'never'}</td>
                            <td className="ar-row-actions">
                                <JellyButton size="sm" variant="danger" onClick={async () => {
                                    if (!window.confirm(`Revoke ${k.name}? Whatever uses it stops at once.`)) return;
                                    await recordsService.revokeKey(k.id);
                                    refresh();
                                }}>Revoke</JellyButton>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
            {keys.data && !live.length && <p className="ar-note">No keys yet.</p>}
            <div className="ar-section">
                <span>Public access: <strong>{publicOn ? 'On' : 'Off'}</strong></span>{' '}
                <JellyButton size="sm" variant="ghost" onClick={async () => {
                    await recordsService.saveSettings({ public_api_access: !publicOn });
                    refresh();
                }}>{publicOn ? 'Turn off' : 'Turn on'}</JellyButton>
                <p className="ar-note">Websites' forms use public keys, which may only create records. They work only while
                    this is on, and are rate-limited.</p>
            </div>
        </div>
    );
};

export default DataKeysPage;
