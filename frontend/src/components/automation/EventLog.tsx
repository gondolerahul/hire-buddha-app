/**
 * components/automation/EventLog — every event the business received, newest
 * first (functional spec §3.4): its status, and on opening it what each
 * trigger decided and why, with the runs it started. A failed event can be
 * retried and a held one released; a trigger that already decided about an
 * event never decides twice.
 */
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { JellyButton } from '@/components/ui';
import { queryKeys } from '@/queries/keys';
import { automationService, type AutomationEvent, type EventStatus } from '@/services/automation.service';

import { eventStatusLabel, formatTime, outcomeLabel, outcomeTone, sourceLabel } from './describe';
import './automation.css';

const PAGE = 50;

const EventDetailPanel: React.FC<{ id: string; timezone: string; onReplayed: () => void }> = ({ id, timezone, onReplayed }) => {
    const { data, isLoading, refetch } = useQuery({
        queryKey: queryKeys.automation.event(id),
        queryFn: () => automationService.getEvent(id),
    });
    const [message, setMessage] = useState('');

    if (isLoading || !data) return <div className="ar-detail">Loading…</div>;
    const replay = async () => {
        try {
            await automationService.replayEvent(id);
            setMessage('Sent to be handled again.');
            await refetch();
            onReplayed();
        } catch {
            setMessage('Could not retry it.');
        }
    };

    return (
        <div className="ar-detail" aria-label="Event detail">
            <div className="ar-detail__head">
                <strong>{data.type}</strong>
                <span className={`ar-pill ar-pill--${data.status}`}>{eventStatusLabel(data.status)}</span>
                {(data.status === 'dead' || data.status === 'parked') && (
                    <JellyButton size="sm" variant="primary" onClick={replay}>
                        {data.status === 'dead' ? 'Retry' : 'Run now'}
                    </JellyButton>
                )}
            </div>
            <p className="ar-note">
                {formatTime(data.time, timezone)} · from {sourceLabel(data.source)}
                {data.chain_depth > 0 && ` · step ${data.chain_depth} of a chain`}
                {data.attempts > 0 && ` · ${data.attempts} failed attempt${data.attempts === 1 ? '' : 's'}`}
            </p>
            {data.last_error && <p className="ar-note ar-note--bad">{data.last_error}</p>}
            {message && <p className="ar-note" role="status">{message}</p>}

            <h4>Decisions</h4>
            {data.firings.length === 0
                ? <p className="ar-note">{data.status === 'routed' ? 'No trigger matched this event.' : 'Not decided yet.'}</p>
                : (
                    <ul className="ar-decisions">
                        {data.firings.map(f => (
                            <li key={f.id} className={`ar-tone--${outcomeTone(f.outcome)}`}>
                                <strong>{outcomeLabel(f.outcome)}</strong>
                                {f.reason && <span> — {f.reason}</span>}
                                {f.run_id && <> · <Link to={`/ai/executions/${f.run_id}`}>view run</Link></>}
                            </li>
                        ))}
                    </ul>
                )}

            <h4>Data</h4>
            <pre className="ar-json">{JSON.stringify(data.data, null, 2)}</pre>
        </div>
    );
};

export const EventLog: React.FC<{ timezone: string; initialStatus?: EventStatus | '' }> = ({ timezone, initialStatus = '' }) => {
    const queryClient = useQueryClient();
    const [type, setType] = useState('');
    const [status, setStatus] = useState<EventStatus | ''>(initialStatus);
    const [pages, setPages] = useState<string[]>([]);  // the `before` cursor of each extra page
    const [open, setOpen] = useState<string | null>(null);

    const query = { type: type.trim() || undefined, status, limit: PAGE };
    const first = useQuery({
        queryKey: queryKeys.automation.events(query),
        queryFn: () => automationService.listEvents(query),
    });
    const more = useQuery({
        queryKey: queryKeys.automation.events({ ...query, pages }),
        queryFn: async () => {
            const rows: AutomationEvent[] = [];
            for (const before of pages) rows.push(...await automationService.listEvents({ ...query, before }));
            return rows;
        },
        enabled: pages.length > 0,
    });
    const rows = [...(first.data ?? []), ...(more.data ?? [])];
    const last = rows[rows.length - 1];

    const reset = () => { setPages([]); setOpen(null); };

    return (
        <section className="ar-section" aria-label="Event log">
            <div className="ar-row">
                <input className="ar-input ar-mono" placeholder="Type, or a prefix like social.*" value={type}
                       aria-label="Event type filter" onChange={e => { setType(e.target.value); reset(); }} />
                <select className="ar-input" value={status} aria-label="Event status filter"
                        onChange={e => { setStatus(e.target.value as EventStatus | ''); reset(); }}>
                    <option value="">Any status</option>
                    <option value="routed">Handled</option>
                    <option value="received">Waiting</option>
                    <option value="parked">Held</option>
                    <option value="dead">Failed</option>
                </select>
            </div>
            {first.isLoading ? <p className="ar-note">Loading…</p> : rows.length === 0 ? (
                <p className="ar-note">No events yet. Events arrive from connected accounts, data changes, schedules and agents.</p>
            ) : (
                <table className="ar-table">
                    <thead>
                        <tr><th>Time</th><th>Event</th><th>From</th><th>Status</th></tr>
                    </thead>
                    <tbody>
                        {rows.map(e => (
                            <React.Fragment key={e.id}>
                                <tr className={`ar-clickable ${open === e.id ? 'ar-open' : ''}`}
                                    onClick={() => setOpen(open === e.id ? null : e.id)}>
                                    <td>{formatTime(e.time, timezone)}</td>
                                    <td className="ar-mono">{e.type}</td>
                                    <td title={e.source}>{sourceLabel(e.source)}</td>
                                    <td><span className={`ar-pill ar-pill--${e.status}`}>{eventStatusLabel(e.status)}</span></td>
                                </tr>
                                {open === e.id && (
                                    <tr><td colSpan={4}>
                                        <EventDetailPanel id={e.id} timezone={timezone}
                                                          onReplayed={() => queryClient.invalidateQueries({ queryKey: queryKeys.automation.all })} />
                                    </td></tr>
                                )}
                            </React.Fragment>
                        ))}
                    </tbody>
                </table>
            )}
            {rows.length >= PAGE * (pages.length + 1) && last && (
                <div className="ar-actions">
                    <JellyButton variant="ghost" size="sm" onClick={() => setPages(p => [...p, last.id])}>Load more</JellyButton>
                </div>
            )}
        </section>
    );
};

export default EventLog;
