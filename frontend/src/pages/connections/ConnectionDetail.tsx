/**
 * pages/connections/ConnectionDetail — one connected account (Phase 14 WS8 8.3; functional spec §6.4).
 *
 * Account, permissions, health and last check, expiry, last use; **who may
 * use it** (editable); what depends on it (agents, apps, triggers); the
 * activity log; Test, Reconnect, Disconnect — which first lists what stops.
 */
import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { JellyButton } from '@/components/ui';
import { ago, formatTime } from '@/components/automation/describe';
import { useAuth } from '@/hooks/useAuth';
import { connectionsService, type Grant, type Impact } from '@/services/connections.service';
import { problemText } from '@/services/records.service';
import { UserRole } from '@/types';

import { LOCAL_TZ } from '../records/RecordsPage';
import { GrantPicker, healthOf } from './ConnectionsPage';
import '@/components/automation/automation.css';

const MANAGERS = [UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN];

/** What stops if the connection goes, in words (shown before Disconnect). */
export const impactLines = (impact: Impact): string[] => {
    const lines: string[] = [];
    if (impact.all_agents) lines.push('Every agent loses it');
    else if (impact.agents.length) lines.push(`${impact.agents.length} agent${impact.agents.length === 1 ? ' loses' : 's lose'} it: `
        + impact.agents.map(a => a.name || a.id).join(', '));
    if (impact.apps.length) lines.push(`${impact.apps.length} app${impact.apps.length === 1 ? ' loses' : 's lose'} it`);
    const on = impact.triggers.filter(t => t.enabled);
    if (on.length) lines.push(`${on.length} trigger${on.length === 1 ? '' : 's'} will pause: ${on.map(t => t.name).join(', ')}`);
    return lines;
};

export const ConnectionDetail: React.FC = () => {
    const { id = '' } = useParams();
    const { user } = useAuth();
    const manager = MANAGERS.includes(user?.role as UserRole);
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const detail = useQuery({ queryKey: ['connections', 'detail', id], queryFn: () => connectionsService.detail(id) });
    const [grants, setGrants] = useState<Grant[] | null>(null);
    const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
    const [confirming, setConfirming] = useState(false);
    useEffect(() => { if (detail.data?.grants) setGrants(detail.data.grants); }, [detail.data]);
    const refresh = () => queryClient.invalidateQueries({ queryKey: ['connections'] });

    const act = async (action: () => Promise<unknown>, done: string, fallback: string) => {
        setMessage(null);
        try { await action(); setMessage({ kind: 'ok', text: done }); refresh(); }
        catch (err) { setMessage({ kind: 'error', text: problemText(err, fallback) }); }
    };

    if (detail.isError) return <div className="page-container ar-page"><p className="ar-note ar-note--bad">
        {problemText(detail.error, 'No such connection.')}</p></div>;
    const c = detail.data;
    if (!c) return <div className="page-container ar-page"><p className="ar-note">Loading…</p></div>;
    const health = healthOf(c);
    const lines = impactLines(c.impact);

    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>{c.display_name}</h1>
                    <p>{c.connector_id} · {c.external_account_name || c.external_account_id} ·{' '}
                        <span className={`ar-pill ar-pill--${health.tone}`}>{health.label}</span></p>
                </div>
                <div className="ar-row">
                    <Link to="/connections" className="ar-link">All connections</Link>
                    {manager && <>
                        <JellyButton size="sm" variant="ghost" onClick={() => act(async () => {
                            const result = await connectionsService.test(id);
                            if (!result.ok) throw { response: { data: { detail: `Test failed: ${result.detail}` } } };
                        }, 'It works.', 'Test failed.')}>Test</JellyButton>
                        <JellyButton size="sm" variant="secondary" onClick={() => act(async () => {
                            const started = await connectionsService.reconnect(id);
                            if (started.kind === 'redirect') window.location.assign(started.url);
                        }, 'Reconnecting…', 'Could not reconnect.')}>Reconnect</JellyButton>
                        <JellyButton size="sm" variant="danger" onClick={() => setConfirming(true)}>Disconnect</JellyButton>
                    </>}
                </div>
            </header>
            {message && <p className={`ar-note ar-note--${message.kind === 'ok' ? 'ok' : 'bad'}`} role="status">{message.text}</p>}
            {confirming && (
                <section className="ar-section" role="alertdialog" aria-label="Disconnect">
                    <h2>Disconnect {c.display_name}?</h2>
                    {lines.length ? <ul className="ar-decisions">{lines.map(l => <li key={l}>{l}</li>)}</ul>
                        : <p className="ar-note">Nothing uses it.</p>}
                    <div className="ar-actions">
                        <JellyButton variant="ghost" size="sm" onClick={() => setConfirming(false)}>Keep it</JellyButton>
                        <JellyButton variant="danger" size="sm" onClick={async () => {
                            try { await connectionsService.revoke(id); refresh(); navigate('/connections'); }
                            catch (err) { setMessage({ kind: 'error', text: problemText(err, 'Could not disconnect.') }); }
                        }}>Disconnect</JellyButton>
                    </div>
                </section>
            )}
            <section className="ar-section" aria-label="Details">
                <h2>Details</h2>
                <table className="ar-table"><tbody>
                    <tr><td>Permissions</td><td>{c.scopes.join(', ') || '—'}</td></tr>
                    <tr><td>Last check</td><td>{c.health.last_check_at ? ago(c.health.last_check_at) : 'never'}
                        {c.health.last_error && <span className="ar-tone--bad"> — {c.health.last_error}</span>}</td></tr>
                    <tr><td>Token expires</td><td>{c.token_expires_at ? formatTime(c.token_expires_at, LOCAL_TZ)
                        : 'does not expire'}</td></tr>
                    <tr><td>Last used</td><td>{c.last_used_at ? ago(c.last_used_at) : 'never'}</td></tr>
                    <tr><td>Connected</td><td>{formatTime(c.connected_at, LOCAL_TZ)}</td></tr>
                </tbody></table>
            </section>
            {grants && (
                <section className="ar-section" aria-label="Who may use it">
                    <GrantPicker value={grants} onChange={setGrants} />
                    {manager && <div className="ar-actions">
                        <JellyButton size="sm" onClick={() => act(() => connectionsService.setGrants(id, grants),
                                                                  'Saved who may use it.', 'Could not save.')}>Save</JellyButton>
                    </div>}
                </section>
            )}
            <section className="ar-section" aria-label="What depends on it">
                <h2>What depends on it</h2>
                {lines.length ? <ul className="ar-decisions">{c.impact.triggers.map(t => (
                    <li key={t.id}>Trigger <Link to="/automation">{t.name}</Link>{!t.enabled && ' (off)'}</li>))}
                    {lines.filter(l => !l.includes('trigger')).map(l => <li key={l}>{l.replace(/ loses? it/, ' may use it')}</li>)}
                </ul> : <p className="ar-note">Nothing yet.</p>}
            </section>
            <section className="ar-section" aria-label="Activity">
                <h2>Activity</h2>
                <ul className="ar-decisions">
                    {c.activity.map((a, i) => (
                        <li key={i}>{formatTime(a.at, LOCAL_TZ)} · <strong>{a.action.replace(/_/g, ' ')}</strong>
                            {a.actor_kind && <span> by {a.actor_kind}</span>}
                            {a.run_id && <> · <Link to={`/work/${a.run_id}`}>run</Link></>}</li>
                    ))}
                </ul>
            </section>
        </div>
    );
};

export default ConnectionDetail;
