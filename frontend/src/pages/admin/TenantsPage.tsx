/**
 * pages/admin/TenantsPage — every business's own database (HireBuddha staff; Phase 14 WS8 8.6; functional spec §9).
 *
 * The tenant directory: database, server, schema version, automation state
 * and — on request — health (does the database answer, is it at the current
 * schema); a tenant's provisioning log with **Retry** for a failed setup; the
 * servers with how full they are; giving a company its database.
 */
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { JellyButton } from '@/components/ui';
import { formatTime } from '@/components/automation/describe';
import { problemText } from '@/services/records.service';
import { STEP_LABELS, tenancyService } from '@/services/tenancy.service';

import { LOCAL_TZ } from '../records/RecordsPage';
import '@/components/automation/automation.css';

const Log: React.FC<{ companyId: string }> = ({ companyId }) => {
    const detail = useQuery({ queryKey: ['admin', 'tenant', companyId], queryFn: () => tenancyService.tenant(companyId) });
    if (!detail.data) return <p className="ar-note">Loading…</p>;
    return (
        <ul className="ar-decisions" aria-label="Provisioning log">
            {detail.data.steps.map(s => (
                <li key={s.step} className={`ar-tone--${s.outcome === 'failed' ? 'bad' : s.outcome === 'succeeded' ? 'ok' : 'wait'}`}>
                    {STEP_LABELS[s.step] ?? s.step}: <strong>{s.outcome}</strong>
                    {s.attempt > 1 && <span> (attempt {s.attempt})</span>}{s.at && <span> · {formatTime(s.at, LOCAL_TZ)}</span>}
                    {s.error && <span> — {s.error}</span>}
                </li>
            ))}
        </ul>
    );
};

export const TenantsPage: React.FC = () => {
    const queryClient = useQueryClient();
    const [health, setHealth] = useState(false);
    const tenants = useQuery({ queryKey: ['admin', 'tenants', health], queryFn: () => tenancyService.tenants(health) });
    const servers = useQuery({ queryKey: ['admin', 'servers'], queryFn: tenancyService.servers });
    const [open, setOpen] = useState<string | null>(null);
    const [companyId, setCompanyId] = useState('');
    const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

    const act = async (action: () => Promise<unknown>, done: string, fallback: string) => {
        setMessage(null);
        try { await action(); setMessage({ kind: 'ok', text: done }); await queryClient.invalidateQueries({ queryKey: ['admin'] }); }
        catch (err) { setMessage({ kind: 'error', text: problemText(err, fallback) }); }
    };

    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>Tenants</h1>
                    <p>Mode: <strong>{tenants.data?.mode ?? '—'}</strong>. Each business's own database, where it lives and how it is.</p>
                </div>
                <label className="ar-check ar-check--small">
                    <input type="checkbox" checked={health} onChange={e => setHealth(e.target.checked)} />
                    <span>Check health (connects to every database)</span>
                </label>
            </header>
            {message && <p className={`ar-note ar-note--${message.kind === 'ok' ? 'ok' : 'bad'}`} role="status">{message.text}</p>}
            <table className="ar-table" aria-label="Tenants">
                <thead><tr><th>Tenant</th><th>Database</th><th>Server</th><th>State</th><th>Schema</th><th>Automation</th>
                    {health && <th>Health</th>}<th /></tr></thead>
                <tbody>
                    {(tenants.data?.tenants || []).map(t => (
                        <React.Fragment key={t.company_id}>
                            <tr>
                                <td>{t.slug}<div className="ar-mono">{t.tenant_key}</div></td>
                                <td className="ar-mono">{t.database}</td><td>{t.server ?? '—'}</td>
                                <td><span className={`ar-pill ar-pill--${t.status === 'active' ? 'active' : t.status === 'failed'
                                    ? 'dead' : 'paused'}`}>{t.status.replace(/_/g, ' ')}</span></td>
                                <td className="ar-mono">{t.platform_schema_version ?? '—'}</td>
                                <td>{t.automation_state}</td>
                                {health && <td>{t.health ? (t.health.reachable === false ? `unreachable${t.health.error ? `: ${t.health.error}` : ''}`
                                    : t.health.schema === 'behind' ? 'schema behind'
                                    : `ok${t.health.latency_ms != null ? ` (${t.health.latency_ms} ms)` : ''}`) : '—'}</td>}
                                <td className="ar-row-actions">
                                    <button className="ar-link" onClick={() => setOpen(open === t.company_id ? null : t.company_id)}>log</button>
                                    {t.status !== 'active' && <JellyButton size="sm" variant="ghost" onClick={() => act(
                                        () => tenancyService.retry(t.company_id), 'Setup queued again.', 'Could not retry.')}>Retry</JellyButton>}
                                </td>
                            </tr>
                            {open === t.company_id && <tr><td colSpan={health ? 8 : 7}><Log companyId={t.company_id} /></td></tr>}
                        </React.Fragment>
                    ))}
                </tbody>
            </table>
            <section className="ar-section" aria-label="Give a company its database">
                <h2>Give a company its own database</h2>
                <div className="ar-row">
                    <label className="ar-field"><span>Company id</span>
                        <input className="ar-input ar-mono" value={companyId} onChange={e => setCompanyId(e.target.value)} /></label>
                    <JellyButton size="sm" disabled={!/^[0-9a-f-]{36}$/i.test(companyId)} onClick={() => act(
                        () => tenancyService.provision(companyId), 'Requested; setup is queued.', 'Could not request it.')}>
                        Provision</JellyButton>
                </div>
            </section>
            <section className="ar-section" aria-label="Servers">
                <h2>Database servers</h2>
                <table className="ar-table"><thead><tr><th>Server</th><th>Kind</th><th>Region</th><th>Tenants</th><th>State</th></tr></thead>
                    <tbody>{(servers.data || []).map(s => (
                        <tr key={s.name}><td>{s.name}<div className="ar-mono">{s.host}</div></td><td>{s.kind}</td><td>{s.region}</td>
                            <td>{s.tenants} / {s.capacity}</td><td>{s.status}</td></tr>))}</tbody></table>
                <p className="ar-note">Moving a tenant to a dedicated server is a staff operation (`python -m src.common.tenancy.split`
                    onto the new server, then the switch-over).</p>
            </section>
        </div>
    );
};

export default TenantsPage;
