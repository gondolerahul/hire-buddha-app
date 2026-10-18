/**
 * pages/admin/AutomationPlatformPage — platform-wide automation defaults and
 * the emergency stop (HireBuddha staff; decision D47, functional spec §2.1, §9).
 *
 * Defaults apply to every business that has not set its own value; "no
 * limit" is the default for each. The emergency stop pauses automation for
 * every business at once; ending it leaves businesses paused on their own paused.
 */
import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { AutomationLimitsForm } from '@/components/automation/AutomationLimitsForm';
import { JellyButton } from '@/components/ui';
import { queryKeys } from '@/queries/keys';
import { automationService, type LimitValues, type PlatformAutomation } from '@/services/automation.service';

import '../automation/AutomationSettings.css';

export const AutomationPlatformPage: React.FC = () => {
    const queryClient = useQueryClient();
    const { data, isLoading, error } = useQuery({
        queryKey: queryKeys.automation.platform,
        queryFn: automationService.getPlatform,
    });
    const [limits, setLimits] = useState<LimitValues>({});
    const [reason, setReason] = useState('');
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState<string | null>(null);

    useEffect(() => {
        if (data) setLimits(data.platform);
    }, [data]);

    const apply = (next: PlatformAutomation) => {
        queryClient.setQueryData(queryKeys.automation.platform, next);
        // Every business's effective values may change with the defaults.
        queryClient.invalidateQueries({ queryKey: queryKeys.automation.settings });
    };

    const run = async (action: () => Promise<PlatformAutomation>, done: string) => {
        setBusy(true);
        setMessage(null);
        try {
            apply(await action());
            setMessage(done);
        } catch {
            setMessage('Could not save. Try again.');
        } finally {
            setBusy(false);
        }
    };

    if (isLoading) return <div className="page-container">Loading…</div>;
    if (error || !data) return <div className="page-container">Could not load the platform automation settings.</div>;

    const stopped = data.automation_state === 'paused';
    const changed = JSON.stringify(limits) !== JSON.stringify(data.platform);

    return (
        <div className="page-container as-page">
            <header className="page-header">
                <h1>Platform automation</h1>
                <p>Defaults for every business that has not set its own limits, and the emergency stop.</p>
            </header>

            <section className={`as-page__state ${stopped ? 'as-page__state--paused' : ''}`}>
                <div>
                    <strong>{stopped ? 'Emergency stop: automation paused for every business' : 'Automation running'}</strong>
                    {stopped && data.paused_reason && <span className="as-page__reason">— {data.paused_reason}</span>}
                </div>
                <div className="as-page__state-actions">
                    {!stopped && (
                        <input className="as-page__input" placeholder="Reason" value={reason}
                               onChange={e => setReason(e.target.value)} />
                    )}
                    <JellyButton
                        variant={stopped ? 'primary' : 'ghost'}
                        disabled={busy}
                        onClick={() => run(
                            () => (stopped ? automationService.resumePlatform() : automationService.pausePlatform(reason)),
                            stopped ? 'Emergency stop ended.' : 'Automation paused for every business.',
                        )}
                    >
                        {stopped ? 'End emergency stop' : 'Emergency stop'}
                    </JellyButton>
                </div>
            </section>

            <section className="as-page__section">
                <h2>Default limits</h2>
                <p>No limit unless set. A business's own value always wins.</p>
                <AutomationLimitsForm catalogue={data.catalogue} values={limits} onChange={setLimits} disabled={busy} />
                <div className="as-page__actions">
                    <JellyButton variant="ghost" disabled={busy || !changed} onClick={() => setLimits(data.platform)}>
                        Undo changes
                    </JellyButton>
                    <JellyButton variant="primary" disabled={busy || !changed}
                                 onClick={() => run(() => automationService.savePlatformLimits(limits), 'Defaults saved.')}>
                        Save defaults
                    </JellyButton>
                </div>
            </section>

            {message && <p className="as-page__message" role="status">{message}</p>}
        </div>
    );
};

export default AutomationPlatformPage;
