/**
 * pages/settings/TenantSettings — the business's own settings (Phase 14 WS8 8.5; functional spec §8).
 *
 *   - Business time zone (schedules, reports, "today" for agents)
 *   - Automation running or paused (the kill switch; limits on their own page)
 *   - Auto-approve simple data additions by agents (off by default)
 *   - Scratch retention, 1–30 days (default 7)
 *   - Public API access, for websites' forms (off by default)
 *   - GitHub: where apps' code lives
 *
 * Owners and admins change them; everyone sees them.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { JellyButton } from '@/components/ui';
import { useAuth } from '@/hooks/useAuth';
import { queryKeys } from '@/queries/keys';
import { automationService } from '@/services/automation.service';
import { companyService } from '@/services/company.service';
import { connectionsService } from '@/services/connections.service';
import { problemText, recordsService } from '@/services/records.service';
import { tenancyService, STEP_LABELS } from '@/services/tenancy.service';
import { UserRole } from '@/types';

import '@/components/automation/automation.css';

const EDITORS = [UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN];

const timeZones = (): string[] => {
    const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
    return supported ? supported('timeZone') : ['Asia/Kolkata', 'UTC'];
};

export const TenantSettings: React.FC = () => {
    const { user } = useAuth();
    const canEdit = EDITORS.includes(user?.role as UserRole);
    const queryClient = useQueryClient();
    const automation = useQuery({ queryKey: queryKeys.automation.settings, queryFn: automationService.getSettings });
    const records = useQuery({ queryKey: ['records', 'settings'], queryFn: recordsService.settings, retry: false });
    const workspace = useQuery({ queryKey: ['workspace'], queryFn: tenancyService.workspace });
    const connections = useQuery({ queryKey: ['connections', 'list'], queryFn: connectionsService.list });
    const zones = useMemo(timeZones, []);
    const [timezone, setTimezone] = useState('');
    const [retention, setRetention] = useState('');
    const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
    const storedZone = automation.data?.timezone;
    const storedRetention = records.data?.scratch_retention_days;
    useEffect(() => { if (storedZone) setTimezone(storedZone); }, [storedZone]);
    useEffect(() => { setRetention(storedRetention ? String(storedRetention) : ''); }, [storedRetention]);

    const save = async (action: () => Promise<unknown>, done: string) => {
        setMessage(null);
        try {
            await action();
            setMessage({ kind: 'ok', text: done });
            await queryClient.invalidateQueries();
        } catch (err) {
            setMessage({ kind: 'error', text: problemText(err, 'Could not save. Try again.') });
        }
    };

    const paused = automation.data?.automation_state === 'paused';
    const github = (connections.data || []).find(c => c.connector_id === 'github' && c.status !== 'revoked');
    const r = records.data;

    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>Business settings</h1>
                    <p>How your workspace behaves: time, automation, data changes, code and public access.</p>
                </div>
            </header>
            {message && <p className={`ar-note ar-note--${message.kind === 'ok' ? 'ok' : 'bad'}`} role="status">{message.text}</p>}

            {workspace.data && !workspace.data.ready && (
                <section className="ar-section" aria-label="Workspace">
                    <h2>Your workspace is being set up</h2>
                    <ul className="ar-decisions">{workspace.data.steps.map(s => (
                        <li key={s.step}>{STEP_LABELS[s.step] ?? s.step}: <strong>{s.outcome}</strong></li>))}</ul>
                </section>
            )}

            <section className="ar-section" aria-label="Country and currency">
                <h2>Country and currency</h2>
                <p className="ar-note">
                    {user?.country_code ?? 'IN'} · billed in {user?.billing_currency ?? 'INR'}. Prices, your wallet and
                    invoices are in this currency; GST applies in India. HireBuddha support changes it when you move country.
                </p>
                {canEdit && <p className="ar-note">Spend limits are on <Link to="/billing/controls">Spend controls</Link>.</p>}
            </section>

            <section className="ar-section" aria-label="Business time zone">
                <h2>Business time zone</h2>
                <p className="ar-note">Schedules, reports and "today" for your agents use it.</p>
                <div className="ar-row">
                    <select className="ar-input" aria-label="Time zone" value={timezone} disabled={!canEdit}
                            onChange={e => setTimezone(e.target.value)}>
                        {!zones.includes(timezone) && timezone && <option value={timezone}>{timezone}</option>}
                        {zones.map(z => <option key={z} value={z}>{z}</option>)}
                    </select>
                    {canEdit && <JellyButton size="sm" disabled={!automation.data || timezone === automation.data.timezone}
                                             onClick={() => save(() => companyService.updateCompany(automation.data!.company_id,
                                                                                                    { timezone }),
                                                                 `Time zone set to ${timezone}.`)}>Save</JellyButton>}
                </div>
            </section>

            <section className="ar-section" aria-label="Automation">
                <h2>Automation: {paused ? 'Paused' : 'Running'}</h2>
                <div className="ar-row">
                    <JellyButton size="sm" variant={paused ? 'primary' : 'ghost'} onClick={() => save(
                        paused ? automationService.resume : () => automationService.pause(),
                        paused ? 'Automation resumed.' : 'Automation paused.')}>{paused ? 'Resume' : 'Pause all'}</JellyButton>
                    <Link to="/settings/automation" className="ar-link">Automation limits</Link>
                    <Link to="/automation" className="ar-link">Control room</Link>
                </div>
            </section>

            {records.isError ? (
                <section className="ar-section"><p className="ar-note">{problemText(records.error,
                    'Records settings appear once your workspace has its own database.')}</p></section>
            ) : r && (
                <>
                    <section className="ar-section" aria-label="Data changes by agents">
                        <h2>Data changes by agents</h2>
                        <label className="ar-check">
                            <input type="checkbox" checked={r.agents_auto_approve_additive} disabled={!canEdit}
                                   onChange={e => save(() => recordsService.saveSettings({
                                       agents_auto_approve_additive: e.target.checked }), 'Saved.')} />
                            <span>Auto-approve simple additions by agents
                                <small>A new table, an optional field or an index applies without a person; renaming,
                                    removing or narrowing always waits for one.</small></span>
                        </label>
                    </section>
                    <section className="ar-section" aria-label="Scratch code">
                        <h2>Scratch code</h2>
                        <p className="ar-note">Code agents write while working is deleted after this many days unless someone
                            promotes it.</p>
                        <div className="ar-row">
                            <input className="ar-input" type="number" min={1} max={30} aria-label="Days" style={{ width: 90 }}
                                   placeholder={String(r.scratch_retention_default)} value={retention} disabled={!canEdit}
                                   onChange={e => setRetention(e.target.value)} />
                            <span>days {!r.scratch_retention_days && `(default ${r.scratch_retention_default})`}</span>
                            {canEdit && <JellyButton size="sm" onClick={() => save(() => recordsService.saveSettings({
                                scratch_retention_days: retention ? Number(retention) : null }), 'Saved.')}>Save</JellyButton>}
                        </div>
                    </section>
                    <section className="ar-section" aria-label="Public API access">
                        <h2>Public API access: {r.public_api_access ? 'On' : 'Off'}</h2>
                        <p className="ar-note">Websites' forms use public keys that may only create records, rate-limited.
                            They work only while this is on.</p>
                        {canEdit && <JellyButton size="sm" variant="ghost" onClick={() => save(() => recordsService.saveSettings({
                            public_api_access: !r.public_api_access }), r.public_api_access ? 'Public access off.'
                            : 'Public access on.')}>{r.public_api_access ? 'Turn off' : 'Turn on'}</JellyButton>}
                    </section>
                </>
            )}

            <section className="ar-section" aria-label="GitHub">
                <h2>GitHub</h2>
                {github ? <p>Connected: <Link to={`/connections/${github.id}`}>{github.display_name}</Link>. New apps can keep
                    their code there; agents' changes arrive as pull requests.</p>
                    : <p>Not connected: apps use the built-in Git, and the history can be copied to GitHub later.{' '}
                        <Link to="/connections">Connect GitHub</Link></p>}
            </section>
        </div>
    );
};

export default TenantSettings;
