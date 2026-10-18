/**
 * pages/automation/ControlRoom — the business's automatic work at a glance
 * (Phase 14 WS3/WS8, functional spec §3.4; tech spec §7.12):
 *
 *   - Running / paused, with pause all and resume (the kill switch)
 *   - Today: runs started, waiting, failed events, missed schedules
 *   - Needs attention: failed events, triggers that keep being refused
 *   - Upcoming runs, runs waiting for an event (with cancel), then every
 *     trigger with its last and next run
 *   - The event log: what arrived, what each trigger decided and why
 *
 * Owners and admins create and change triggers; anyone running the business
 * may run one now, retry an event or pause. The server decides; the page reflects it.
 */
import React, { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { ago, describeNext, describeWhen, formatTime, outcomeLabel, outcomeTone } from '@/components/automation/describe';
import { EventLog } from '@/components/automation/EventLog';
import { TriggerEditor } from '@/components/automation/TriggerEditor';
import { JellyButton } from '@/components/ui';
import { useAuth } from '@/hooks/useAuth';
import { useEntityList } from '@/queries/hooks';
import { queryKeys } from '@/queries/keys';
import { automationService, type Trigger } from '@/services/automation.service';
import { UserRole, type HierarchicalEntity } from '@/types';

import '@/components/automation/automation.css';

const EDITORS = [UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN];

const errorText = (err: unknown, fallback: string): string => {
    const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    return typeof detail === 'string' ? detail : fallback;
};

const History: React.FC<{ trigger: Trigger; timezone: string }> = ({ trigger, timezone }) => {
    const { data, isLoading } = useQuery({
        queryKey: queryKeys.automation.firings(trigger.id),
        queryFn: () => automationService.firings(trigger.id),
    });
    if (isLoading) return <p className="ar-note">Loading…</p>;
    if (!data?.length) return <p className="ar-note">Nothing decided yet.</p>;
    return (
        <ul className="ar-decisions" aria-label={`History of ${trigger.name}`}>
            {data.map(f => (
                <li key={f.id} className={`ar-tone--${outcomeTone(f.outcome)}`}>
                    {formatTime(f.decided_at, timezone)} · <strong>{outcomeLabel(f.outcome)}</strong>
                    {f.reason && <span> — {f.reason}</span>}
                    {f.run_id && <> · <Link to={`/ai/executions/${f.run_id}`}>view run</Link></>}
                </li>
            ))}
        </ul>
    );
};

export const ControlRoom: React.FC = () => {
    const { user } = useAuth();
    const queryClient = useQueryClient();
    const canEdit = EDITORS.includes(user?.role as UserRole);

    const settings = useQuery({ queryKey: queryKeys.automation.settings, queryFn: automationService.getSettings });
    const health = useQuery({ queryKey: queryKeys.automation.health, queryFn: automationService.health,
                              refetchInterval: 30_000 });
    const triggers = useQuery({ queryKey: queryKeys.automation.triggers, queryFn: automationService.listTriggers,
                                refetchInterval: 30_000 });
    const waits = useQuery({ queryKey: queryKeys.automation.waits, queryFn: automationService.listWaits,
                             refetchInterval: 30_000 });

    const { data: entities = [] } = useEntityList<HierarchicalEntity>();
    const names = useMemo(() => Object.fromEntries(entities.map(e => [e.id, e.display_name || e.name])), [entities]);

    const [tab, setTab] = useState<'triggers' | 'events'>('triggers');
    const [eventFilter, setEventFilter] = useState<'' | 'dead'>('');
    const [editing, setEditing] = useState<Trigger | 'new' | null>(null);
    const [history, setHistory] = useState<string | null>(null);
    const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
    const [busy, setBusy] = useState(false);

    const timezone = settings.data?.timezone ?? 'Asia/Kolkata';
    const paused = (health.data?.automation_state ?? settings.data?.automation_state) === 'paused';
    const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.automation.all });

    const act = async (action: () => Promise<unknown>, done: string, fallback: string) => {
        setBusy(true);
        setMessage(null);
        try {
            await action();
            setMessage({ kind: 'ok', text: done });
            await refresh();
        } catch (err) {
            setMessage({ kind: 'error', text: errorText(err, fallback) });
        } finally {
            setBusy(false);
        }
    };

    const showFailed = () => { setEventFilter('dead'); setTab('events'); };

    const h = health.data;
    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>Control room</h1>
                    <p>Schedules, timers and event rules that run your agents, and everything they decided.</p>
                </div>
                <div className={`ar-state ${paused ? 'ar-state--paused' : ''}`}>
                    <span>Automation: <strong>{paused ? 'Paused' : 'Running'}</strong></span>
                    <JellyButton size="sm" variant={paused ? 'primary' : 'ghost'} disabled={busy}
                                 onClick={() => act(paused ? automationService.resume : () => automationService.pause(),
                                                    paused ? 'Automation resumed; held events run in order.' : 'Automation paused.',
                                                    'Could not change it.')}>
                        {paused ? 'Resume' : 'Pause all'}
                    </JellyButton>
                    <Link to="/settings/automation" className="ar-link">Settings</Link>
                </div>
            </header>

            {h && (
                <section className="ar-today" aria-label="Today">
                    <span><strong>{h.started_24h}</strong> runs started</span>
                    <span><strong>{h.queued_firings}</strong> waiting their turn</span>
                    <span><strong>{h.waiting_runs ?? 0}</strong> waiting for an event</span>
                    <span className={h.dead_events ? 'ar-tone--bad' : ''}><strong>{h.dead_events}</strong> failed events</span>
                    <span><strong>{h.missed_schedules_24h}</strong> missed schedules</span>
                    {h.parked_events > 0 && <span><strong>{h.parked_events}</strong> held while paused</span>}
                    <small>last 24 hours</small>
                </section>
            )}

            {h && (h.dead_events > 0 || (h.failing_triggers ?? []).length > 0) && (
                <section className="ar-section" aria-label="Needs attention">
                    <h2>Needs attention</h2>
                    <ul className="ar-attention">
                        {h.dead_events > 0 && (
                            <li>
                                ⚠ {h.dead_events} event{h.dead_events === 1 ? '' : 's'} failed five times
                                <JellyButton size="sm" variant="ghost" onClick={showFailed}>View</JellyButton>
                            </li>
                        )}
                        {(h.failing_triggers ?? []).map(f => (
                            <li key={f.trigger_id}>
                                ⚠ “{f.name}”: {outcomeLabel(f.last_outcome).toLowerCase()} {f.problems}× today
                                {f.last_reason && <span className="ar-note"> — {f.last_reason}</span>}
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            {h && (h.upcoming ?? []).length > 0 && (
                <section className="ar-section" aria-label="Upcoming">
                    <h2>Upcoming</h2>
                    <ul className="ar-upcoming">
                        {h.upcoming.map(u => (
                            <li key={u.trigger_id}>
                                <span className="ar-mono">{formatTime(u.next_fire_at, timezone)}</span>
                                {u.name} <span className="ar-note">({u.kind}{u.created_by_kind === 'agent' ? ', created by an agent' : ''})</span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            {(waits.data ?? []).length > 0 && (
                <section className="ar-section" aria-label="Waiting runs">
                    <h2>Waiting for an event</h2>
                    <ul className="ar-upcoming">
                        {(waits.data ?? []).map(w => (
                            <li key={w.id}>
                                <span>{w.entity_name ?? 'A run'} waits for <span className="ar-mono">{w.event_type}</span></span>
                                <span className="ar-note">until {formatTime(w.deadline_at, timezone)}</span>
                                <Link to={`/ai/executions/${w.run_id}`} className="ar-link">run</Link>
                                <JellyButton size="sm" variant="ghost" disabled={busy}
                                             onClick={() => act(() => automationService.cancelWait(w.id),
                                                                'Wait cancelled; the run goes on without the event.',
                                                                'Could not cancel the wait.')}>
                                    Cancel wait
                                </JellyButton>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            <div className="ar-tabs" role="tablist">
                <button role="tab" aria-selected={tab === 'triggers'} className={tab === 'triggers' ? 'ar-tab--on' : ''}
                        onClick={() => setTab('triggers')}>Triggers</button>
                <button role="tab" aria-selected={tab === 'events'} className={tab === 'events' ? 'ar-tab--on' : ''}
                        onClick={() => { setEventFilter(''); setTab('events'); }}>Event log</button>
                {canEdit && tab === 'triggers' && (
                    <JellyButton className="ar-tabs__new" size="sm" variant="primary" onClick={() => setEditing('new')}>New trigger</JellyButton>
                )}
            </div>

            {message && <p className={`ar-note ar-note--${message.kind === 'ok' ? 'ok' : 'bad'}`} role="status">{message.text}</p>}

            {tab === 'triggers' && (
                <section className="ar-section" aria-label="Triggers">
                    {triggers.isLoading ? <p className="ar-note">Loading…</p> : !triggers.data?.length ? (
                        <p className="ar-note">No triggers yet. {canEdit ? 'Create one to run an agent on a schedule, at a time, or when something happens.' : ''}</p>
                    ) : (
                        <table className="ar-table">
                            <thead>
                                <tr><th>Trigger</th><th>When</th><th>Last run</th><th>Next run</th><th>Status</th><th /></tr>
                            </thead>
                            <tbody>
                                {triggers.data.map(t => (
                                    <React.Fragment key={t.id}>
                                        <tr>
                                            <td>
                                                <strong>{t.name}</strong>
                                                {t.created_by_kind === 'agent' && <span className="ar-tag">created by agent</span>}
                                                {t.scope && <span className="ar-tag">{t.scope}</span>}
                                            </td>
                                            <td className="ar-mono">{describeWhen(t, timezone, names)}</td>
                                            <td title={formatTime(t.last_fired_at, timezone)}>{ago(t.last_fired_at)}</td>
                                            <td>{describeNext(t, timezone)}</td>
                                            <td><span className={`ar-pill ar-pill--${t.status}`}>{t.status === 'active' ? 'On' : t.status}</span></td>
                                            <td className="ar-row-actions">
                                                {canEdit && t.status !== 'finished' && (
                                                    <JellyButton size="sm" variant="ghost" disabled={busy}
                                                                 onClick={() => act(() => automationService.updateTrigger(t.id, { enabled: !t.enabled }),
                                                                                    t.enabled ? `“${t.name}” is off.` : `“${t.name}” is on.`,
                                                                                    'Could not change it.')}>
                                                        {t.enabled ? 'Turn off' : 'Turn on'}
                                                    </JellyButton>
                                                )}
                                                {t.enabled && (
                                                    <JellyButton size="sm" variant="ghost" disabled={busy}
                                                                 onClick={() => act(() => automationService.runTrigger(t.id),
                                                                                    `“${t.name}” sent to run. Its decision appears in the history.`,
                                                                                    'Could not run it.')}>
                                                        Run now
                                                    </JellyButton>
                                                )}
                                                <JellyButton size="sm" variant="ghost" onClick={() => setHistory(history === t.id ? null : t.id)}>
                                                    History
                                                </JellyButton>
                                                {canEdit && (
                                                    <>
                                                        <JellyButton size="sm" variant="ghost" onClick={() => setEditing(t)}>Edit</JellyButton>
                                                        <JellyButton size="sm" variant="danger" disabled={busy}
                                                                     onClick={() => window.confirm(`Delete “${t.name}”? Runs it started stay.`)
                                                                         && act(() => automationService.deleteTrigger(t.id), 'Trigger deleted.', 'Could not delete it.')}>
                                                            Delete
                                                        </JellyButton>
                                                    </>
                                                )}
                                            </td>
                                        </tr>
                                        {history === t.id && (
                                            <tr><td colSpan={6}><History trigger={t} timezone={timezone} /></td></tr>
                                        )}
                                    </React.Fragment>
                                ))}
                            </tbody>
                        </table>
                    )}
                </section>
            )}

            {tab === 'events' && <EventLog key={eventFilter} timezone={timezone} initialStatus={eventFilter} />}

            {editing && (
                <TriggerEditor
                    trigger={editing === 'new' ? undefined : editing}
                    timezone={timezone}
                    onClose={() => setEditing(null)}
                    onSaved={async saved => {
                        setEditing(null);
                        setMessage({ kind: 'ok', text: `“${saved.name}” saved. Nothing runs until it is due or you press Run now.` });
                        await refresh();
                    }}
                />
            )}
        </div>
    );
};

export default ControlRoom;
