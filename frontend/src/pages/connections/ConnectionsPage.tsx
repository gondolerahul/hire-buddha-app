/**
 * pages/connections/ConnectionsPage — the business's own accounts (Phase 14 WS8 8.3; functional spec §6.2, §6.3).
 *
 * Connected accounts with their health, then what can be connected:
 * **Connect** (available), **Preview** (works, limited support), **Coming
 * soon** (not yet approved). Connecting opens the provider's sign-in; the
 * provider sends the browser back here (`?pending=…`) to choose the accounts
 * and who may use them. API-key services and mailboxes are a short form.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation, useSearchParams } from 'react-router-dom';

import { JellyButton } from '@/components/ui';
import { ago } from '@/components/automation/describe';
import { useAuth } from '@/hooks/useAuth';
import { useEntityList } from '@/queries/hooks';
import {
    CATEGORY_LABELS, STATUS_BADGE, connectionsService,
    type Connection, type Connector, type Grant,
} from '@/services/connections.service';
import { problemText } from '@/services/records.service';
import { EntityType, UserRole, type HierarchicalEntity } from '@/types';
import { parseServerDate } from '@/utils/datetime';

import '@/components/automation/automation.css';

const MANAGERS = [UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN];

export const healthOf = (c: Connection): { label: string; tone: string } => {
    if (c.status === 'needs_reconnect' || c.status === 'revoked') return { label: 'Needs reconnect', tone: 'dead' };
    if (c.status === 'error' || c.health.last_error) return { label: 'Problem', tone: 'dead' };
    if (c.status === 'expiring' && c.token_expires_at) {
        const days = Math.max(0, Math.round((parseServerDate(c.token_expires_at).getTime() - Date.now()) / 86_400_000));
        return { label: `Expires in ${days} day${days === 1 ? '' : 's'}`, tone: 'paused' };
    }
    return { label: 'Healthy', tone: 'active' };
};

/** Who may use a connection: everyone's agents, or the ones chosen. */
export const GrantPicker: React.FC<{ value: Grant[]; onChange: (grants: Grant[]) => void }> = ({ value, onChange }) => {
    const { data: entities = [] } = useEntityList<HierarchicalEntity>();
    const agents = entities.filter(e => e.type === EntityType.AGENT);
    const all = value.some(g => g.principal_kind === 'all_agents');
    const chosen = new Set(value.filter(g => g.principal_kind === 'entity').map(g => g.principal_id));
    return (
        <fieldset className="ar-group">
            <legend>Who may use it</legend>
            <label className="ar-check ar-check--small">
                <input type="radio" checked={all} onChange={() => onChange([{ principal_kind: 'all_agents', principal_id: null,
                                                                             actions: ['*'] }])} />
                <span>All agents</span>
            </label>
            <label className="ar-check ar-check--small">
                <input type="radio" checked={!all} onChange={() => onChange([])} />
                <span>Only these agents</span>
            </label>
            {!all && (
                <div className="ar-targets">
                    {agents.map(a => (
                        <label key={a.id} className="ar-check ar-check--small">
                            <input type="checkbox" checked={chosen.has(a.id)} onChange={() => {
                                const next = new Set(chosen);
                                if (next.has(a.id)) next.delete(a.id); else next.add(a.id);
                                onChange([...next].map(id => ({ principal_kind: 'entity', principal_id: id, actions: ['*'] })));
                            }} />
                            <span>{a.display_name || a.name}</span>
                        </label>
                    ))}
                    {!agents.length && <p className="ar-note">No agents yet.</p>}
                </div>
            )}
        </fieldset>
    );
};

const ALL_AGENTS: Grant[] = [{ principal_kind: 'all_agents', principal_id: null, actions: ['*'] }];

const ChooseAccounts: React.FC<{ pendingId: string; onDone: (message: string) => void; onCancel: () => void }> = ({
    pendingId, onDone, onCancel }) => {
    const pending = useQuery({ queryKey: ['connections', 'pending', pendingId],
                               queryFn: () => connectionsService.pending(pendingId), retry: false });
    const [chosen, setChosen] = useState<Set<string>>(new Set());
    const [grants, setGrants] = useState<Grant[]>(ALL_AGENTS);
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
        if (pending.data) setChosen(new Set(pending.data.accounts.filter(a => a.available).map(a => a.external_id)));
    }, [pending.data]);
    if (pending.isError) return <p className="ar-note ar-note--bad">{problemText(pending.error, 'This request expired.')}</p>;
    if (!pending.data) return <p className="ar-note">Loading…</p>;
    return (
        <section className="ar-section" aria-label="Choose accounts">
            <h2>Connect {pending.data.display_name}: choose the accounts</h2>
            {pending.data.accounts.map(a => (
                <label key={a.external_id} className="ar-check ar-check--small">
                    <input type="checkbox" disabled={!a.available} checked={chosen.has(a.external_id)} onChange={() => {
                        const next = new Set(chosen);
                        if (next.has(a.external_id)) next.delete(a.external_id); else next.add(a.external_id);
                        setChosen(next);
                    }} />
                    <span>{a.name}{!a.available && <small> — already connected to another business; support can help</small>}</span>
                </label>
            ))}
            <GrantPicker value={grants} onChange={setGrants} />
            {error && <p className="ar-note ar-note--bad" role="alert">{error}</p>}
            <div className="ar-actions">
                <JellyButton variant="ghost" size="sm" onClick={onCancel}>Cancel</JellyButton>
                <JellyButton size="sm" disabled={!chosen.size} onClick={async () => {
                    try {
                        const made = await connectionsService.finalize(pendingId, [...chosen], grants);
                        onDone(`Connected ${made.length} account${made.length === 1 ? '' : 's'}.`);
                    } catch (err) { setError(problemText(err, 'Could not connect.')); }
                }}>Connect</JellyButton>
            </div>
        </section>
    );
};

const ConnectForm: React.FC<{ connector: Connector; onDone: (message: string) => void; onCancel: () => void }> = ({
    connector, onDone, onCancel }) => {
    const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(
        connector.form.map(f => [f.name, f.default === undefined || f.default === null ? '' : String(f.default)])));
    const [displayName, setDisplayName] = useState('');
    const [grants, setGrants] = useState<Grant[]>(ALL_AGENTS);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    return (
        <form className="ar-section" aria-label={`Connect ${connector.display_name}`} onSubmit={async e => {
            e.preventDefault();
            setBusy(true);
            setError(null);
            try {
                const fields = Object.fromEntries(connector.form.map(f => [f.name,
                    f.kind === 'number' && values[f.name] !== '' ? Number(values[f.name]) : values[f.name]]));
                await connectionsService.form(connector.id, fields, displayName || undefined, grants);
                onDone(`${connector.display_name} connected.`);
            } catch (err) { setError(problemText(err, 'Could not connect: check the details.')); }
            finally { setBusy(false); }
        }}>
            <h2>Connect {connector.display_name}</h2>
            {connector.help && <p className="ar-note">{connector.help}</p>}
            <div className="ar-row">
                <label className="ar-field"><span>Name it (optional)</span>
                    <input className="ar-input" value={displayName} onChange={e => setDisplayName(e.target.value)} /></label>
                {connector.form.map(f => (
                    <label key={f.name} className="ar-field"><span>{f.label}{f.required ? ' *' : ''}</span>
                        {f.kind === 'select' ? (
                            <select className="ar-input" required={f.required} value={values[f.name]}
                                    onChange={e => setValues({ ...values, [f.name]: e.target.value })}>
                                {(f.options || []).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                            </select>
                        ) : (
                            <input className="ar-input" required={f.required} autoComplete="off"
                                   type={f.kind === 'secret' ? 'password' : f.kind === 'number' ? 'number' : f.kind}
                                   value={values[f.name]} onChange={e => setValues({ ...values, [f.name]: e.target.value })} />
                        )}
                        {f.help && <small>{f.help}</small>}
                    </label>
                ))}
            </div>
            <GrantPicker value={grants} onChange={setGrants} />
            <p className="ar-note">Stored encrypted with your business's own key; never shown again.</p>
            {error && <p className="ar-note ar-note--bad" role="alert">{error}</p>}
            <div className="ar-actions">
                <JellyButton variant="ghost" size="sm" onClick={onCancel}>Cancel</JellyButton>
                <JellyButton type="submit" size="sm" disabled={busy}>{busy ? 'Testing…' : 'Connect'}</JellyButton>
            </div>
        </form>
    );
};

/** What HireBuddha will do with the account, before the provider's window opens (SH-13). */
const Disclosure: React.FC<{ connector: Connector; onContinue: () => void; onCancel: () => void }> = ({
    connector, onContinue, onCancel }) => (
    <section className="ar-section" role="dialog" aria-label={`Before you connect ${connector.display_name}`}>
        <h2>Before you connect {connector.display_name}</h2>
        <p>{connector.disclosure}</p>
        {connector.privacy_url && (
            <p className="ar-note"><a href={connector.privacy_url} target="_blank" rel="noreferrer">HireBuddha's privacy
                policy</a> says what is kept, for how long, and how to have it deleted.</p>
        )}
        <div className="ar-actions">
            <JellyButton variant="ghost" size="sm" onClick={onCancel}>Cancel</JellyButton>
            <JellyButton size="sm" onClick={onContinue}>Continue</JellyButton>
        </div>
    </section>
);

export const ConnectionsPage: React.FC = () => {
    const { user } = useAuth();
    const manager = MANAGERS.includes(user?.role as UserRole);
    const queryClient = useQueryClient();
    const location = useLocation();
    const [params, setParams] = useSearchParams();
    const [disclosing, setDisclosing] = useState<Connector | null>(null);
    const notice = (location.state as { notice?: string } | null)?.notice;
    const connectors = useQuery({ queryKey: ['connections', 'connectors'], queryFn: connectionsService.connectors });
    const connections = useQuery({ queryKey: ['connections', 'list'], queryFn: connectionsService.list });
    const [category, setCategory] = useState('');
    const [search, setSearch] = useState('');
    const [form, setForm] = useState<Connector | null>(null);
    const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(
        params.get('error') ? { kind: 'error', text: params.get('error')! }
            : params.get('notice') ? { kind: 'ok', text: params.get('notice')! } : null);
    const [consent, setConsent] = useState<{ url: string; message: string } | null>(null);
    // Microsoft's "only an administrator may approve mail access" (MS-E3): offer the admin's link.
    const needsAdmin = message?.kind === 'error' && message.text.includes('Admin consent link');
    const pendingId = params.get('pending');

    const byId = useMemo(() => Object.fromEntries((connectors.data || []).map(c => [c.id, c])), [connectors.data]);
    const categories = useMemo(() => [...new Set((connectors.data || []).map(c => c.category))], [connectors.data]);
    const available = (connectors.data || []).filter(c => (!category || c.category === category)
        && c.display_name.toLowerCase().includes(search.toLowerCase()));
    const live = (connections.data || []).filter(c => c.status !== 'revoked');
    const refresh = () => queryClient.invalidateQueries({ queryKey: ['connections'] });
    const done = (text: string) => {
        setForm(null);
        setParams({});
        setMessage({ kind: 'ok', text });
        refresh();
    };

    const connect = async (connector: Connector, disclosed = false) => {
        setMessage(null);
        if (connector.disclosure && !disclosed) {  // the person reads what HireBuddha will do first (SH-13)
            setDisclosing(connector);
            return;
        }
        setDisclosing(null);
        try {
            const started = await connectionsService.start(connector.id, '/connections');
            if (started.kind === 'redirect') window.location.assign(started.url);
            else if (started.kind === 'form') setForm({ ...connector, form: started.form });
            else setMessage({ kind: 'error', text: 'WhatsApp sign-up needs Meta\'s window, which opens once HireBuddha\'s '
                + 'Meta app is approved.' });
        } catch (err) {
            setMessage({ kind: 'error', text: problemText(err, `Could not start connecting ${connector.display_name}.`) });
        }
    };

    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>Connections</h1>
                    <p>Your own accounts — pages, mailboxes, GitHub, CRMs — connected once and used by the agents and apps you choose.</p>
                </div>
            </header>
            {message && <p className={`ar-note ar-note--${message.kind === 'ok' ? 'ok' : 'bad'}`} role="status">{message.text}</p>}
            {notice && !message && <p className="ar-note ar-note--ok" role="status">Disconnected. {notice}</p>}
            {needsAdmin && manager && !consent && (
                <div className="ar-actions">
                    <JellyButton size="sm" variant="secondary" onClick={async () => {
                        try { setConsent(await connectionsService.adminConsent(params.get('connector') || 'outlook_mail')); }
                        catch (err) { setMessage({ kind: 'error', text: problemText(err, 'Could not make the link.') }); }
                    }}>Admin consent link</JellyButton>
                </div>
            )}
            {consent && (
                <section className="ar-section" aria-label="Admin consent link">
                    <p>{consent.message}</p>
                    <input className="ar-input" readOnly value={consent.url} aria-label="Link for the administrator"
                           onFocus={e => e.currentTarget.select()} />
                </section>
            )}
            {disclosing && <Disclosure connector={disclosing} onContinue={() => connect(disclosing, true)}
                                       onCancel={() => setDisclosing(null)} />}
            {pendingId && manager && <ChooseAccounts pendingId={pendingId} onDone={done} onCancel={() => setParams({})} />}
            {form && <ConnectForm connector={form} onDone={done} onCancel={() => setForm(null)} />}

            <section className="ar-section" aria-label="Connected">
                <h2>Connected</h2>
                {!live.length && <p className="ar-note">Nothing connected yet.</p>}
                <table className="ar-table">
                    <tbody>
                        {live.map(c => {
                            const health = healthOf(c);
                            return (
                                <tr key={c.id}>
                                    <td>{byId[c.connector_id]?.display_name ?? c.connector_id}</td>
                                    <td>{c.display_name}{c.external_account_name && c.external_account_name !== c.display_name
                                        && <small> ({c.external_account_name})</small>}</td>
                                    <td><span className={`ar-pill ar-pill--${health.tone}`}>{health.label}</span></td>
                                    <td>{c.last_used_at ? `used ${ago(c.last_used_at)}` : 'not used yet'}</td>
                                    <td className="ar-row-actions"><Link to={`/connections/${c.id}`}>Manage</Link></td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </section>

            <section className="ar-section" aria-label="Available">
                <div className="ar-tabs">
                    <h2 style={{ margin: 0 }}>Available</h2>
                    <input className="ar-input ar-tabs__new" placeholder="Search apps…" aria-label="Search apps"
                           value={search} onChange={e => setSearch(e.target.value)} />
                </div>
                <nav className="ar-tabs" aria-label="Categories">
                    <button className={!category ? 'ar-tab--on' : ''} onClick={() => setCategory('')}>All</button>
                    {categories.map(c => (
                        <button key={c} className={category === c ? 'ar-tab--on' : ''}
                                onClick={() => setCategory(c)}>{CATEGORY_LABELS[c] ?? c}</button>
                    ))}
                </nav>
                <div className="ar-kinds">
                    {available.map(c => (
                        <div key={c.id} className="ar-kind" title={c.events.length ? `Events: ${c.events.join(', ')}` : undefined}>
                            <span>{c.display_name}</span>
                            {c.connectable && manager ? (
                                <JellyButton size="sm" variant={c.status === 'preview' ? 'secondary' : 'primary'}
                                             onClick={() => connect(c)}>{STATUS_BADGE[c.status]}</JellyButton>
                            ) : <span className="ar-tag">{STATUS_BADGE[c.status]}</span>}
                        </div>
                    ))}
                </div>
                {!manager && <p className="ar-note">Owners and admins connect accounts.</p>}
            </section>
        </div>
    );
};

export default ConnectionsPage;
