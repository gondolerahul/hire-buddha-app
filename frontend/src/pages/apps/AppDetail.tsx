/**
 * pages/apps/AppDetail — one app (Phase 14 WS8 8.4; functional spec §7.3).
 *
 * Tabs: Overview · Code & reviews · Builds · Preview & publish · Domains ·
 * Users & roles · Logs & metrics · Settings. Publishing, rollback and every
 * change are owners' and admins'; a pull request merges only once its checks
 * passed, by someone allowed to approve code.
 */
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { JellyButton } from '@/components/ui';
import { ago, formatTime } from '@/components/automation/describe';
import { useAuth } from '@/hooks/useAuth';
import {
    APP_STATUS_LABEL, appsService,
    type AppDetail as AppData, type AppRole, type CodeReview,
} from '@/services/apps.service';
import { problemText } from '@/services/records.service';
import { UserRole } from '@/types';

import { LOCAL_TZ } from '../records/RecordsPage';
import { statusTone } from './AppsPage';
import '@/components/automation/automation.css';

const MANAGERS = [UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN];
const TABS = [
    ['overview', 'Overview'], ['code', 'Code & reviews'], ['builds', 'Builds'], ['publish', 'Preview & publish'],
    ['domains', 'Domains'], ['users', 'Users & roles'], ['logs', 'Logs & metrics'], ['settings', 'Settings'],
] as const;
type Tab = typeof TABS[number][0];

type Act = (action: () => Promise<unknown>, done: string, fallback: string) => Promise<void>;

export const checkTone = (conclusion: string): string =>
    conclusion === 'failure' ? 'dead' : conclusion === 'success' ? 'active' : 'paused';

export const ReviewCard: React.FC<{ review: CodeReview; canApprove: boolean; act: Act }> = ({ review, canApprove, act }) => (
    <li className="ar-detail">
        <div className="ar-detail__head">
            <strong>#{review.number} {review.title}</strong>
            <span className={`ar-pill ar-pill--${review.status === 'merged' ? 'active' : review.status === 'closed' ? 'dead'
                : 'paused'}`}>{review.status}</span>
            <span>checks {review.checks_status}</span>
            {review.url?.startsWith('http') && <a href={review.url} target="_blank" rel="noreferrer">open</a>}
        </div>
        <ul className="ar-decisions">
            {review.checks.map(c => (
                <li key={c.name}><span className={`ar-pill ar-pill--${checkTone(c.conclusion)}`}>{c.conclusion}</span>
                    <strong>{c.name}</strong> <small>({c.tool})</small>
                    <details><summary>details</summary><pre className="ar-json">{c.summary}</pre></details></li>
            ))}
        </ul>
        {review.status === 'open' && canApprove && (
            <div className="ar-row">
                <JellyButton size="sm" disabled={review.checks_status !== 'passed'}
                             title={review.checks_status !== 'passed' ? 'The checks must pass first' : 'Merge it'}
                             onClick={() => act(() => appsService.approve(review.id), 'Merged.', 'Could not merge.')}>
                    Approve and merge</JellyButton>
                <JellyButton size="sm" variant="ghost"
                             onClick={() => act(() => appsService.rerunChecks(review.id), 'Checks running again.',
                                                'Could not run the checks.')}>Run checks again</JellyButton>
                <JellyButton size="sm" variant="danger"
                             onClick={() => act(() => appsService.reject(review.id), 'Closed.', 'Could not close it.')}>
                    Reject</JellyButton>
            </div>
        )}
        {review.merged_by_login && <p className="ar-note">Merged by {review.merged_by_login} {ago(review.merged_at)}</p>}
    </li>
);

const RoleEditor: React.FC<{ appId: string; objects: string[]; role?: AppRole; act: Act; onDone: () => void }> = ({
    appId, objects, role, act, onDone }) => {
    const [name, setName] = useState(role?.name ?? '');
    const [grants, setGrants] = useState<Record<string, string[]>>(role?.permissions.objects ?? {});
    const [own, setOwn] = useState(Boolean(role?.permissions.own_rows));
    const ops = ['read', 'create', 'update', 'delete'];
    return (
        <div className="ar-group">
            <label className="ar-field"><span>Role name</span>
                <input className="ar-input" value={name} disabled={Boolean(role)} onChange={e => setName(e.target.value)} />
            </label>
            <table className="ar-table"><thead><tr><th>Table</th>{ops.map(o => <th key={o}>{o}</th>)}</tr></thead>
                <tbody>{objects.map(o => (
                    <tr key={o}><td>{o}</td>{ops.map(op => (
                        <td key={op}><input type="checkbox" aria-label={`${op} ${o}`} checked={(grants[o] || []).includes(op)}
                                            onChange={() => {
                                                const set = new Set(grants[o] || []);
                                                if (set.has(op)) set.delete(op); else set.add(op);
                                                setGrants({ ...grants, [o]: ops.filter(x => set.has(x)) });
                                            }} /></td>))}</tr>))}</tbody></table>
            <label className="ar-check ar-check--small">
                <input type="checkbox" checked={own} onChange={e => setOwn(e.target.checked)} />
                <span>Only their own records (tables that name an owner field)</span>
            </label>
            <div className="ar-actions">
                <JellyButton size="sm" disabled={!name.trim()} onClick={async () => {
                    await act(() => appsService.saveRole(appId, name, Object.fromEntries(Object.entries(grants)
                        .filter(([, v]) => v.length)), own), 'Role saved.', 'Could not save the role.');
                    onDone();
                }}>Save role</JellyButton>
            </div>
        </div>
    );
};

const UsersTab: React.FC<{ app: AppData; manager: boolean; act: Act }> = ({ app, manager, act }) => {
    const users = useQuery({ queryKey: ['apps', 'users', app.id], queryFn: () => appsService.users(app.id), enabled: manager });
    const [email, setEmail] = useState('');
    const [role, setRole] = useState(app.roles[0]?.name ?? '');
    const [editing, setEditing] = useState<AppRole | 'new' | null>(null);
    const queryClient = useQueryClient();
    const reload = () => queryClient.invalidateQueries({ queryKey: ['apps'] });
    const returnUrl = app.url || window.location.origin;
    if (!manager) return <p className="ar-note">Owners and admins manage an app's users.</p>;
    return (
        <>
            <section className="ar-section" aria-label="App users">
                <h2>People who sign in to {app.display_name}</h2>
                <p className="ar-note">They are not HireBuddha users; each sees only what their role allows.</p>
                <div className="ar-row">
                    <label className="ar-field"><span>E-mail</span>
                        <input className="ar-input" type="email" value={email} onChange={e => setEmail(e.target.value)} /></label>
                    <label className="ar-field"><span>Role</span>
                        <select className="ar-input" value={role} onChange={e => setRole(e.target.value)}>
                            {app.roles.map(r => <option key={r.id} value={r.name}>{r.name}</option>)}
                        </select></label>
                    <JellyButton size="sm" disabled={!email.includes('@')} onClick={async () => {
                        await act(async () => {
                            const made = await appsService.addUser(app.id, { email, roles: role ? [role] : [] });
                            await appsService.invite(app.id, made.id, returnUrl);
                        }, `Invited ${email}.`, 'Could not invite.');
                        setEmail('');
                        reload();
                    }}>Invite</JellyButton>
                </div>
                <table className="ar-table"><thead><tr><th>Who</th><th>Roles</th><th>State</th><th>Last sign-in</th><th /></tr></thead>
                    <tbody>{(users.data || []).map(u => (
                        <tr key={u.id}><td>{u.email}</td><td>{u.roles.join(', ') || '—'}</td><td>{u.status}</td>
                            <td>{u.last_login_at ? ago(u.last_login_at) : 'never'}</td>
                            <td className="ar-row-actions">
                                {u.status === 'invited' && <JellyButton size="sm" variant="ghost" onClick={() =>
                                    act(() => appsService.invite(app.id, u.id, returnUrl), 'Sent again.', 'Could not send.')}>
                                    Send again</JellyButton>}
                                <JellyButton size="sm" variant="ghost" onClick={async () => {
                                    await act(() => appsService.updateUser(app.id, u.id, {
                                        status: u.status === 'disabled' ? 'active' : 'disabled' }),
                                        u.status === 'disabled' ? 'Enabled.' : 'Disabled: their sessions ended.', 'Could not change.');
                                    reload();
                                }}>{u.status === 'disabled' ? 'Enable' : 'Disable'}</JellyButton>
                            </td></tr>))}</tbody></table>
            </section>
            <section className="ar-section" aria-label="Roles">
                <h2>Roles</h2>
                <ul className="ar-attention">{app.roles.map(r => (
                    <li key={r.id}><strong>{r.name}</strong>
                        <span>{Object.entries(r.permissions.objects || {}).map(([o, ops]) => `${o}: ${ops.join('/')}`).join(' · ')}</span>
                        {r.permissions.own_rows && <span className="ar-tag">own records only</span>}
                        <button className="ar-link" onClick={() => setEditing(r)}>edit</button></li>))}</ul>
                <JellyButton size="sm" variant="ghost" onClick={() => setEditing('new')}>+ Role</JellyButton>
                {editing && <RoleEditor appId={app.id} objects={app.objects} role={editing === 'new' ? undefined : editing}
                                        act={act} onDone={() => { setEditing(null); reload(); }} />}
            </section>
        </>
    );
};

const SettingsTab: React.FC<{ app: AppData; act: Act }> = ({ app, act }) => {
    const [mode, setMode] = useState(app.mode);
    const [cpu, setCpu] = useState(app.resources.cpu ?? '250m');
    const [memory, setMemory] = useState(app.resources.memory ?? '256Mi');
    const [hosts, setHosts] = useState(app.outbound_allowlist.join('\n'));
    return (
        <section className="ar-section" aria-label="Settings">
            <h2>How it runs</h2>
            <div className="ar-kinds">
                {(['always_on', 'sleep'] as const).map(m => (
                    <label key={m} className={`ar-kind ${mode === m ? 'ar-kind--on' : ''}`}>
                        <input type="radio" checked={mode === m} onChange={() => setMode(m)} />
                        {m === 'always_on' ? 'Always on' : 'Sleep when idle (cheaper; the first visit wakes it)'}
                    </label>))}
            </div>
            <div className="ar-row">
                <label className="ar-field"><span>CPU (e.g. 250m, 1)</span>
                    <input className="ar-input" value={cpu} onChange={e => setCpu(e.target.value)} /></label>
                <label className="ar-field"><span>Memory (e.g. 256Mi, 1Gi)</span>
                    <input className="ar-input" value={memory} onChange={e => setMemory(e.target.value)} /></label>
            </div>
            <label className="ar-field"><span>Outside services it may call (one host a line; nothing else is reachable)</span>
                <textarea className="ar-input" rows={4} value={hosts} onChange={e => setHosts(e.target.value)} /></label>
            <div className="ar-actions">
                <JellyButton size="sm" variant="danger" onClick={() => {
                    if (window.confirm(`Archive ${app.display_name}? It stops; its code, builds and users are kept.`)) {
                        act(() => appsService.archive(app.id), 'Archived.', 'Could not archive.');
                    }
                }}>Archive app</JellyButton>
                <JellyButton size="sm" onClick={() => act(() => appsService.update(app.id, {
                    mode, resources: { cpu, memory }, outbound_allowlist: hosts.split(/\s+/).filter(Boolean) }),
                    'Saved; a live app picks it up now.', 'Could not save.')}>Save</JellyButton>
            </div>
        </section>
    );
};

export const AppDetail: React.FC = () => {
    const { id = '' } = useParams();
    const [params, setParams] = useSearchParams();
    const tab = (params.get('tab') as Tab) || 'overview';
    const { user } = useAuth();
    const manager = MANAGERS.includes(user?.role as UserRole);
    const queryClient = useQueryClient();
    const detail = useQuery({ queryKey: ['apps', 'detail', id], queryFn: () => appsService.get(id), refetchInterval: 15_000 });
    const reviews = useQuery({ queryKey: ['apps', 'reviews', id], queryFn: () => appsService.reviews({ app_id: id }) });
    const logs = useQuery({ queryKey: ['apps', 'logs', id], queryFn: () => appsService.logs(id), enabled: tab === 'logs'
        && Boolean(detail.data?.published_deployment_id), retry: false });
    const metrics = useQuery({ queryKey: ['apps', 'metrics', id], queryFn: () => appsService.metrics(id),
                               enabled: tab === 'logs' && Boolean(detail.data?.published_deployment_id), retry: false });
    const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
    const [hostname, setHostname] = useState('');
    const [log, setLog] = useState<{ build: string; text: string } | null>(null);

    const act: Act = async (action, done, fallback) => {
        setMessage(null);
        try {
            await action();
            setMessage({ kind: 'ok', text: done });
            await queryClient.invalidateQueries({ queryKey: ['apps'] });
        } catch (err) {
            setMessage({ kind: 'error', text: problemText(err, fallback) });
        }
    };

    if (detail.isError) return <div className="page-container ar-page">
        <p className="ar-note ar-note--bad">{problemText(detail.error, 'No such app.')}</p></div>;
    const app = detail.data;
    if (!app) return <div className="page-container ar-page"><p className="ar-note">Loading…</p></div>;
    const live = app.deployments.find(d => d.id === app.published_deployment_id);
    const latest = app.builds[0];
    const succeeded = app.builds.filter(b => b.status === 'succeeded');
    const pending = (reviews.data || []).filter(r => r.status === 'open');
    const hourly = metrics.data?.hourly ?? [];

    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>{app.display_name}</h1>
                    <p><span className={`ar-pill ar-pill--${statusTone(app.status)}`}>{APP_STATUS_LABEL[app.status]}</span>
                        {live && <> · build <span className="ar-mono">{app.builds.find(b => b.id === live.build_id)?.commit_sha.slice(0, 7)}</span></>}
                        {' '}· <Link to="/apps">All apps</Link></p>
                </div>
                <div className="ar-row">
                    {app.url && <a className="ar-link" href={app.url} target="_blank" rel="noreferrer">Open</a>}
                    {manager && live && <JellyButton size="sm" variant="ghost" onClick={() =>
                        act(() => appsService.rollback(app.id), 'Rolled back to the previous version.', 'Could not roll back.')}>
                        Roll back</JellyButton>}
                </div>
            </header>
            {message && <p className={`ar-note ar-note--${message.kind === 'ok' ? 'ok' : 'bad'}`} role="status">{message.text}</p>}
            <nav className="ar-tabs" aria-label="App">
                {TABS.map(([key, label]) => (
                    <button key={key} className={tab === key ? 'ar-tab--on' : ''} onClick={() => setParams({ tab: key })}>{label}</button>
                ))}
            </nav>

            {tab === 'overview' && (
                <section className="ar-section">
                    <p>Uses: {app.objects.length ? app.objects.join(', ') : 'no tables'} · {app.user_count} app user{app.user_count === 1 ? '' : 's'}</p>
                    <p>Hosting, last 24 hours: {hourly.reduce((s, h) => s + h.vcpu_hours, 0).toFixed(2)} vCPU-hours ·{' '}
                        {hourly.reduce((s, h) => s + h.gb_hours, 0).toFixed(2)} GB-hours (in your wallet)</p>
                    {latest && <p>Last build: {latest.status} {ago(latest.created_at)}</p>}
                    {pending.map(r => <p key={r.id}>Pending: PR #{r.number} “{r.title}” — checks {r.checks_status}{' '}
                        <button className="ar-link" onClick={() => setParams({ tab: 'code' })}>Open</button></p>)}
                </section>
            )}

            {tab === 'code' && (
                <section className="ar-section" aria-label="Code and reviews">
                    <h2>Pull requests</h2>
                    <p className="ar-note">Every change is a branch and a pull request; nothing goes straight to the main branch.</p>
                    <ul className="ar-attention">
                        {(reviews.data || []).map(r => <ReviewCard key={r.id} review={r} canApprove={manager} act={act} />)}
                    </ul>
                    {reviews.data && !reviews.data.length && <p className="ar-note">No pull requests yet.</p>}
                </section>
            )}

            {tab === 'builds' && (
                <section className="ar-section" aria-label="Builds">
                    {manager && <JellyButton size="sm" onClick={() => act(() => appsService.build(app.id),
                        'Building the main branch.', 'Could not start a build.')}>Build now</JellyButton>}
                    <table className="ar-table"><thead><tr><th>Commit</th><th>Result</th><th>Scan</th><th>Time</th><th>When</th><th /></tr></thead>
                        <tbody>{app.builds.map(b => (
                            <tr key={b.id}>
                                <td className="ar-mono">{b.commit_sha.slice(0, 7)}</td>
                                <td><span className={`ar-pill ar-pill--${b.status === 'succeeded' ? 'active' : b.status === 'failed'
                                    ? 'dead' : 'paused'}`}>{b.status}</span>{b.error && <small> {b.error.slice(0, 120)}</small>}</td>
                                <td>{b.scan.skipped ? 'not scanned' : b.scan.tool ? `${b.scan.critical ?? 0} critical, ${b.scan.high ?? 0} high` : '—'}</td>
                                <td>{b.duration_seconds != null ? `${b.duration_seconds}s` : '—'}</td>
                                <td>{formatTime(b.created_at, LOCAL_TZ)}</td>
                                <td className="ar-row-actions"><button className="ar-link" onClick={async () =>
                                    setLog({ build: b.id, text: await appsService.buildLog(app.id, b.id) })}>log</button></td>
                            </tr>))}</tbody></table>
                    {log && <pre className="ar-json" aria-label="Build log">{log.text}</pre>}
                </section>
            )}

            {tab === 'publish' && (
                <section className="ar-section" aria-label="Preview and publish">
                    <p>{live ? <>Live at <a href={live.url ?? '#'} target="_blank" rel="noreferrer">{live.hostnames[0]}</a></>
                        : 'Not published.'}</p>
                    {manager && <div className="ar-row">
                        <JellyButton size="sm" disabled={!succeeded.length} onClick={() => act(() => appsService.preview(app.id),
                            'Preview started (7 days).', 'Could not start a preview.')}>Preview the latest build</JellyButton>
                        <JellyButton size="sm" disabled={!succeeded.length} onClick={() => act(() => appsService.publish(app.id),
                            'Published.', 'Could not publish.')}>Publish the latest build</JellyButton>
                        {live && <>
                            <JellyButton size="sm" variant="ghost" onClick={() => act(() => appsService.operate(app.id,
                                app.status === 'stopped' ? 'start' : 'stop'), 'Done.', 'Could not change it.')}>
                                {app.status === 'stopped' ? 'Start' : 'Stop'}</JellyButton>
                            <JellyButton size="sm" variant="ghost" onClick={() => act(() => appsService.operate(app.id, 'restart'),
                                'Restarted.', 'Could not restart.')}>Restart</JellyButton>
                            <JellyButton size="sm" variant="danger" onClick={() => act(() => appsService.operate(app.id, 'unpublish'),
                                'Unpublished.', 'Could not unpublish.')}>Unpublish</JellyButton>
                        </>}
                    </div>}
                    <table className="ar-table"><thead><tr><th>Kind</th><th>Address</th><th>State</th><th>Expires</th><th>When</th></tr></thead>
                        <tbody>{app.deployments.map(d => (
                            <tr key={d.id}><td>{d.kind}{d.pr_number ? ` (PR #${d.pr_number})` : ''}</td>
                                <td>{d.url && d.status === 'active' ? <a href={d.url} target="_blank" rel="noreferrer">{d.hostnames[0]}</a>
                                    : d.hostnames[0]}</td>
                                <td>{d.status}{d.runtime_status.error && <small className="ar-tone--bad"> {d.runtime_status.error.slice(0, 120)}</small>}</td>
                                <td>{d.expires_at ? formatTime(d.expires_at, LOCAL_TZ) : '—'}</td>
                                <td>{formatTime(d.created_at, LOCAL_TZ)}</td></tr>))}</tbody></table>
                </section>
            )}

            {tab === 'domains' && (
                <section className="ar-section" aria-label="Domains">
                    <h2>Addresses</h2>
                    {manager && <div className="ar-row">
                        <label className="ar-field"><span>Your domain (e.g. crm.acme.com)</span>
                            <input className="ar-input" value={hostname} onChange={e => setHostname(e.target.value)} /></label>
                        <JellyButton size="sm" disabled={!hostname.includes('.')} onClick={async () => {
                            await act(() => appsService.addDomain(app.id, hostname), 'Added: create the two DNS records below.',
                                      'Could not add the domain.');
                            setHostname('');
                        }}>Add</JellyButton>
                    </div>}
                    {app.domains.map(d => (
                        <div key={d.hostname} className="ar-detail">
                            <div className="ar-detail__head"><strong>{d.hostname}</strong>
                                <span className={`ar-pill ar-pill--${d.status === 'verified' ? 'active' : d.status === 'failed' ? 'dead'
                                    : 'paused'}`}>{d.kind === 'custom' ? d.status : d.kind}</span>
                                {d.kind === 'custom' && d.status === 'verified' && <span>HTTPS: {d.cert_status}</span>}</div>
                            {d.kind === 'custom' && d.status !== 'verified' && (
                                <>
                                    <table className="ar-table"><thead><tr><th>Type</th><th>Name</th><th>Value</th></tr></thead>
                                        <tbody>{d.dns_records.map(r => <tr key={r.type + r.name}><td>{r.type}</td>
                                            <td className="ar-mono">{r.name}</td><td className="ar-mono">{r.value}{r.note && <small> ({r.note})</small>}</td>
                                        </tr>)}</tbody></table>
                                    {d.last_error && <p className="ar-note ar-note--bad">{d.last_error}</p>}
                                </>
                            )}
                            {manager && d.kind === 'custom' && <div className="ar-row">
                                {d.status !== 'verified' && <JellyButton size="sm" onClick={() => act(() =>
                                    appsService.verifyDomain(app.id, d.hostname), 'Checked.', 'Could not check.')}>Check DNS</JellyButton>}
                                <JellyButton size="sm" variant="ghost" onClick={() => act(() => appsService.removeDomain(app.id, d.hostname),
                                    'Removed.', 'Could not remove.')}>Remove</JellyButton>
                            </div>}
                        </div>
                    ))}
                </section>
            )}

            {tab === 'users' && <UsersTab app={app} manager={manager} act={act} />}

            {tab === 'logs' && (
                <section className="ar-section" aria-label="Logs and metrics">
                    {!live && <p className="ar-note">Logs and metrics appear once the app is published.</p>}
                    {hourly.length > 0 && (
                        <table className="ar-table"><thead><tr><th>Hour</th><th>vCPU-hours</th><th>GB-hours</th><th>GB out</th></tr></thead>
                            <tbody>{hourly.map(h => <tr key={h.window_start}><td>{formatTime(h.window_start, LOCAL_TZ)}</td>
                                <td>{h.vcpu_hours.toFixed(3)}</td><td>{h.gb_hours.toFixed(3)}</td><td>{h.egress_gb.toFixed(3)}</td></tr>)}</tbody></table>
                    )}
                    {logs.data !== undefined && <pre className="ar-json" aria-label="Logs">{logs.data || 'No log lines.'}</pre>}
                    {logs.isError && <p className="ar-note ar-note--bad">{problemText(logs.error, 'Logs are not available.')}</p>}
                </section>
            )}

            {tab === 'settings' && (manager ? <SettingsTab app={app} act={act} />
                : <p className="ar-note">Owners and admins change how an app runs.</p>)}
        </div>
    );
};

export default AppDetail;
