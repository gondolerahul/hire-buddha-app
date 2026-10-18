/**
 * pages/automation/AutomationSettings — a business's automation settings
 * (Phase 14 WS3/WS8 8.5, functional spec §3.5 and §8; decision D47).
 *
 *   - Running / paused, with pause and resume (the kill switch)
 *   - The business time zone schedules use
 *   - Every automation limit: none unless the business (or the platform) sets one
 *
 * Owners and admins edit; others see the values and may pause. The server
 * decides who may do what — the page only reflects it.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { AutomationLimitsForm } from '@/components/automation/AutomationLimitsForm';
import { JellyButton } from '@/components/ui';
import { useAuth } from '@/hooks/useAuth';
import { queryKeys } from '@/queries/keys';
import { automationService, type AutomationSettings as Settings, type LimitValues } from '@/services/automation.service';
import { companyService } from '@/services/company.service';
import { UserRole } from '@/types';

import './AutomationSettings.css';

const EDITORS = [UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN];

const timeZones = (): string[] => {
    const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
    return supported ? supported('timeZone') : ['Asia/Kolkata', 'UTC'];
};

const errorText = (err: unknown): string => {
    const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    return typeof detail === 'string' ? detail : 'Could not save. Try again.';
};

export const AutomationSettings: React.FC = () => {
    const { user } = useAuth();
    const queryClient = useQueryClient();
    const canEdit = EDITORS.includes(user?.role as UserRole);

    const { data, isLoading, error } = useQuery({
        queryKey: queryKeys.automation.settings,
        queryFn: automationService.getSettings,
    });

    const [limits, setLimits] = useState<LimitValues>({});
    const [timezone, setTimezone] = useState('');
    const [reason, setReason] = useState('');
    const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
    const [busy, setBusy] = useState(false);

    // Reset the form only when the stored values change (a save, another
    // tab) — not when pausing or resuming returns the same values, which
    // would throw away edits not yet saved.
    const storedLimits = JSON.stringify(data?.business ?? {});
    useEffect(() => {
        if (data) setLimits(JSON.parse(storedLimits) as LimitValues);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [storedLimits]);
    useEffect(() => {
        if (data) setTimezone(data.timezone);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [data?.timezone]);

    const zones = useMemo(timeZones, []);
    const limitsChanged = data ? JSON.stringify(limits) !== JSON.stringify(data.business) : false;

    const apply = (next: Settings) => queryClient.setQueryData(queryKeys.automation.settings, next);

    const run = async (action: () => Promise<void>, done: string) => {
        setBusy(true);
        setMessage(null);
        try {
            await action();
            setMessage({ kind: 'ok', text: done });
        } catch (err) {
            setMessage({ kind: 'error', text: errorText(err) });
        } finally {
            setBusy(false);
        }
    };

    if (isLoading) return <div className="page-container">Loading…</div>;
    if (error || !data) return <div className="page-container">Could not load the automation settings.</div>;

    const paused = data.automation_state === 'paused';

    return (
        <div className="page-container as-page">
            <header className="page-header">
                <h1>Automation settings</h1>
                <p>
                    How this business's automatic work runs: schedules, triggers and what agents may do on
                    their own. No limit applies unless you set one.
                </p>
            </header>

            <section className={`as-page__state ${paused ? 'as-page__state--paused' : ''}`}>
                <div>
                    <strong>Automation: {paused ? 'Paused' : 'Running'}</strong>
                    {paused && data.paused_reason && <span className="as-page__reason">— {data.paused_reason}</span>}
                    <p>
                        {paused
                            ? 'New events are held and schedules do not fire. Resuming runs held events in order.'
                            : 'Pausing holds new events and stops schedules; work already running finishes.'}
                    </p>
                </div>
                <div className="as-page__state-actions">
                    {!paused && (
                        <input
                            className="as-page__input"
                            placeholder="Reason (optional)"
                            value={reason}
                            onChange={e => setReason(e.target.value)}
                        />
                    )}
                    <JellyButton
                        variant={paused ? 'primary' : 'ghost'}
                        disabled={busy}
                        onClick={() => run(async () => {
                            apply(paused ? await automationService.resume() : await automationService.pause(reason));
                            setReason('');
                        }, paused ? 'Automation resumed.' : 'Automation paused.')}
                    >
                        {paused ? 'Resume automation' : 'Pause all'}
                    </JellyButton>
                </div>
            </section>

            <section className="as-page__section">
                <h2>Business time zone</h2>
                <p>Schedules, reports and an agent's "today" use it.</p>
                <div className="as-page__row">
                    <select
                        className="as-page__input"
                        aria-label="Business time zone"
                        disabled={!canEdit || busy}
                        value={timezone}
                        onChange={e => setTimezone(e.target.value)}
                    >
                        {!zones.includes(timezone) && timezone && <option value={timezone}>{timezone}</option>}
                        {zones.map(zone => <option key={zone} value={zone}>{zone}</option>)}
                    </select>
                    {canEdit && (
                        <JellyButton
                            variant="primary"
                            disabled={busy || timezone === data.timezone}
                            onClick={() => run(async () => {
                                await companyService.updateCompany(data.company_id, { timezone });
                                apply({ ...data, timezone });
                            }, 'Time zone saved.')}
                        >
                            Save time zone
                        </JellyButton>
                    )}
                </div>
            </section>

            <section className="as-page__section">
                <h2>Limits</h2>
                <p>
                    Each limit is off unless set here or as a platform default; a value you set here wins.
                    The wallet check before every automated run always applies.
                </p>
                <AutomationLimitsForm
                    catalogue={data.catalogue}
                    values={limits}
                    inherited={data.platform}
                    onChange={setLimits}
                    disabled={!canEdit || busy}
                />
                {canEdit && (
                    <div className="as-page__actions">
                        <JellyButton variant="ghost" disabled={busy || !limitsChanged} onClick={() => setLimits(data.business)}>
                            Undo changes
                        </JellyButton>
                        <JellyButton
                            variant="primary"
                            disabled={busy || !limitsChanged}
                            onClick={() => run(async () => { apply(await automationService.saveLimits(limits)); }, 'Limits saved.')}
                        >
                            Save limits
                        </JellyButton>
                    </div>
                )}
            </section>

            {message && <p className={`as-page__message as-page__message--${message.kind}`} role="status">{message.text}</p>}
        </div>
    );
};

export default AutomationSettings;
