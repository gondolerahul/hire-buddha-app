/**
 * pages/admin/ConnectorApprovalsPage — what businesses may connect (HireBuddha staff;
 * Phase 14 WS8 8.6; functional spec §6.6, §9; E09-S11).
 *
 * Each connector with its provider review (verification, expiry, limits, notes)
 * and its status: Available, Preview, Unavailable or Coming soon — staff's
 * switch wins over the catalog's until cleared. **Unrouted events**: provider
 * webhooks for accounts no business has connected (kept 7 days, hashes only).
 * **HireBuddha's provider apps** (M1-12): the apps businesses connect through.
 */
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { JellyButton } from '@/components/ui';
import { formatTime } from '@/components/automation/describe';
import { STATUS_BADGE, connectionsService, type ConnectorAdmin, type ConnectorStatus } from '@/services/connections.service';
import { problemText } from '@/services/records.service';

import { LOCAL_TZ } from '../records/RecordsPage';
import { ProviderAppsPanel } from './ProviderAppsPanel';
import '@/components/automation/automation.css';

const STATUSES: ConnectorStatus[] = ['available', 'preview', 'unavailable', 'planned'];

const Review: React.FC<{ connector: ConnectorAdmin; onSaved: () => void }> = ({ connector, onSaved }) => {
    const approval = connector.approval || {};
    const [state, setState] = useState(String(approval.state ?? ''));
    const [expires, setExpires] = useState(String(approval.expires_at ?? ''));
    const [notes, setNotes] = useState(String(approval.notes ?? ''));
    const [error, setError] = useState<string | null>(null);
    return (
        <div className="ar-group">
            <div className="ar-row">
                <label className="ar-field"><span>Provider review</span>
                    <input className="ar-input" value={state} placeholder="submitted / approved / limited"
                           onChange={e => setState(e.target.value)} /></label>
                <label className="ar-field"><span>Approval expires</span>
                    <input className="ar-input" type="date" value={expires} onChange={e => setExpires(e.target.value)} /></label>
                <label className="ar-field"><span>Limits and notes</span>
                    <input className="ar-input" value={notes} onChange={e => setNotes(e.target.value)} /></label>
            </div>
            {error && <p className="ar-note ar-note--bad">{error}</p>}
            <div className="ar-actions">
                <JellyButton size="sm" onClick={async () => {
                    try {
                        await connectionsService.setConnector(connector.id, { approval: { state, expires_at: expires || null, notes } });
                        onSaved();
                    } catch (err) { setError(problemText(err, 'Could not save.')); }
                }}>Save review</JellyButton>
            </div>
        </div>
    );
};

export const ConnectorApprovalsPage: React.FC = () => {
    const queryClient = useQueryClient();
    const connectors = useQuery({ queryKey: ['admin', 'connectors'], queryFn: connectionsService.adminConnectors });
    const unrouted = useQuery({ queryKey: ['admin', 'unrouted'], queryFn: connectionsService.unrouted });
    const [tab, setTab] = useState<'connectors' | 'unrouted' | 'apps'>('connectors');
    const [open, setOpen] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin'] });

    const switchTo = async (connector: ConnectorAdmin, status: ConnectorStatus | 'catalog') => {
        try {
            await connectionsService.setConnector(connector.id, status === 'catalog' ? { clear_override: true }
                : { status_override: status });
            setMessage(`${connector.display_name}: ${status === 'catalog' ? 'back to the catalog\'s status' : STATUS_BADGE[status]}.`);
            refresh();
        } catch (err) { setMessage(problemText(err, 'Could not change it.')); }
    };

    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>Connector approvals</h1>
                    <p>Only approved connectors can be connected. A provider's review decides; this page records it.</p>
                </div>
            </header>
            {message && <p className="ar-note" role="status">{message}</p>}
            <nav className="ar-tabs">
                <button className={tab === 'connectors' ? 'ar-tab--on' : ''} onClick={() => setTab('connectors')}>Connectors</button>
                <button className={tab === 'unrouted' ? 'ar-tab--on' : ''} onClick={() => setTab('unrouted')}>
                    Unrouted events ({unrouted.data?.length ?? 0})</button>
                <button className={tab === 'apps' ? 'ar-tab--on' : ''} onClick={() => setTab('apps')}>
                    HireBuddha's provider apps</button>
            </nav>
            {tab === 'apps' && <ProviderAppsPanel />}
            {tab === 'connectors' && (
                <table className="ar-table" aria-label="Connectors">
                    <thead><tr><th>Connector</th><th>Catalog</th><th>Now</th><th>Review</th><th>Switch</th></tr></thead>
                    <tbody>
                        {(connectors.data || []).map(c => (
                            <React.Fragment key={c.id}>
                                <tr>
                                    <td>{c.display_name} <span className="ar-mono">{c.id}</span></td>
                                    <td>{c.yaml_status ? STATUS_BADGE[c.yaml_status] : '—'}</td>
                                    <td><strong>{STATUS_BADGE[c.status]}</strong>{c.status_override && <span className="ar-tag">staff</span>}</td>
                                    <td>{String(c.approval?.state ?? '—')}{c.approval?.expires_at ? ` · until ${c.approval.expires_at}` : ''}
                                        {' '}<button className="ar-link" onClick={() => setOpen(open === c.id ? null : c.id)}>edit</button></td>
                                    <td className="ar-row-actions">
                                        <select className="ar-input" aria-label={`Status of ${c.display_name}`}
                                                value={c.status_override ?? 'catalog'}
                                                onChange={e => switchTo(c, e.target.value as ConnectorStatus | 'catalog')}>
                                            <option value="catalog">As the catalog says</option>
                                            {STATUSES.map(s => <option key={s} value={s}>{STATUS_BADGE[s]}</option>)}
                                        </select>
                                    </td>
                                </tr>
                                {open === c.id && <tr><td colSpan={5}><Review connector={c} onSaved={() => { setOpen(null); refresh(); }} /></td></tr>}
                            </React.Fragment>
                        ))}
                    </tbody>
                </table>
            )}
            {tab === 'unrouted' && (
                <table className="ar-table" aria-label="Unrouted events">
                    <thead><tr><th>When</th><th>Provider</th><th>Account</th><th>Event</th><th>Size</th></tr></thead>
                    <tbody>{(unrouted.data || []).map(e => (
                        <tr key={e.id}><td>{formatTime(e.received_at, LOCAL_TZ)}</td><td>{e.provider}</td>
                            <td className="ar-mono">{e.external_account_id ?? '—'}</td><td>{e.event_type ?? '—'}</td>
                            <td>{e.payload_bytes} B</td></tr>))}</tbody>
                </table>
            )}
            {tab === 'unrouted' && unrouted.data && !unrouted.data.length && <p className="ar-note">None in the last 7 days.</p>}
        </div>
    );
};

export default ConnectorApprovalsPage;
