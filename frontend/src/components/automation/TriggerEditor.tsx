/**
 * components/automation/TriggerEditor — create or change a trigger
 * (functional spec §3.2): WHEN → RUN → RULES → PREVIEW.
 *
 * Saving never runs anything. A schedule shows its next ten times in the
 * business time zone; an event filter can be tested against the business's
 * recent real events before saving. Every rule left on "business setting"
 * follows the automation settings (decision D47: none unless set).
 */
import React, { useEffect, useMemo, useState } from 'react';

import { JellyButton } from '@/components/ui';
import { useEntityList } from '@/queries/hooks';
import {
    automationService,
    type FilterCondition,
    type Trigger,
    type TriggerFields,
    type TriggerFilter,
    type TriggerKind,
} from '@/services/automation.service';
import type { HierarchicalEntity } from '@/types';
import { parseServerDate } from '@/utils/datetime';

import { formatDay, formatTime, runFinishedFields, watchedAgent, type RunOutcome } from './describe';
import './automation.css';

// "When an agent finishes" is an event trigger on run.* for one agent, shown as its own choice.
type EditorKind = TriggerKind | 'finished';

const KINDS: { kind: EditorKind; label: string }[] = [
    { kind: 'schedule', label: 'On a schedule' },
    { kind: 'timer', label: 'At a time' },
    { kind: 'event', label: 'When something happens' },
    { kind: 'finished', label: 'When an agent finishes' },
    { kind: 'manual', label: 'Only when run by hand' },
];

const OPERATORS = [
    ['eq', 'is'], ['ne', 'is not'], ['contains', 'contains'], ['starts_with', 'starts with'],
    ['gt', '>'], ['gte', '≥'], ['lt', '<'], ['lte', '≤'], ['exists', 'is present'],
] as const;

interface Props {
    trigger?: Trigger;
    timezone: string;
    onClose: () => void;
    onSaved: (trigger: Trigger) => void;
}

const errorText = (err: unknown): string => {
    const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map(d => (d as { msg?: string }).msg ?? String(d)).join('; ');
    return 'Could not save. Try again.';
};

/** A flat list of conditions, or null when the filter is more than that (edit it as JSON). */
const asConditions = (filter: TriggerFilter | null): FilterCondition[] | null => {
    if (!filter) return [];
    if ('path' in filter) return [filter];
    if ('all' in filter && filter.all.every(f => 'path' in f)) return filter.all as FilterCondition[];
    return null;
};

const toFilter = (conditions: FilterCondition[]): TriggerFilter | null => {
    const used = conditions.filter(c => c.path.trim());
    if (!used.length) return null;
    return { all: used.map(c => ({ path: c.path.trim(), op: c.op, value: c.op === 'exists' ? true : coerce(c.value) })) };
};

const coerce = (value: unknown): unknown => {
    if (typeof value !== 'string') return value;
    if (/^-?\d+(\.\d+)?$/.test(value.trim())) return Number(value);
    if (value === 'true' || value === 'false') return value === 'true';
    return value;
};

/** The input box: plain text is `{"input": text}`; text starting with `{` is the JSON itself. */
const inputText = (template: Record<string, unknown> | undefined): string => {
    if (!template || !Object.keys(template).length) return '';
    const keys = Object.keys(template);
    if (keys.length === 1 && keys[0] === 'input' && typeof template.input === 'string') return template.input;
    return JSON.stringify(template, null, 2);
};

const parseInput = (text: string): Record<string, unknown> => {
    const trimmed = text.trim();
    if (!trimmed) return {};
    if (trimmed.startsWith('{')) return JSON.parse(trimmed) as Record<string, unknown>;
    return { input: text };
};

/** `datetime-local` (the browser's time) to and from an API time. */
const toLocalInput = (value: string | null): string => {
    if (!value) return '';
    const date = parseServerDate(value);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const fromLocalInput = (value: string): string => {
    const [day, time] = value.split('T');
    const [year, month, date] = day.split('-').map(Number);
    const [hours, minutes] = time.split(':').map(Number);
    const local = new Date();  // the browser's own time: what the person typed
    local.setFullYear(year, month - 1, date);
    local.setHours(hours, minutes, 0, 0);
    return local.toISOString();
};

const numberOrNull = (text: string): number | null => (text.trim() ? Number(text) : null);

export const TriggerEditor: React.FC<Props> = ({ trigger, timezone, onClose, onSaved }) => {
    const editing = Boolean(trigger);
    const { data: entities = [] } = useEntityList<HierarchicalEntity>();
    const agents = useMemo(
        () => entities.filter(e => String(e.status).toUpperCase() !== 'DELETED')
            .sort((a, b) => (a.display_name || a.name).localeCompare(b.display_name || b.name)),
        [entities]);

    const [name, setName] = useState(trigger?.name ?? '');
    const watched = trigger ? watchedAgent(trigger) : null;
    const [kind, setKind] = useState<EditorKind>(watched ? 'finished' : trigger?.kind ?? 'schedule');
    const [watchedId, setWatchedId] = useState(watched?.agentId ?? '');
    const [outcome, setOutcome] = useState<RunOutcome>(watched?.outcome ?? 'completed');
    const [entityId, setEntityId] = useState(trigger?.entity_id ?? '');
    const [cron, setCron] = useState(trigger?.cron ?? '0 9 * * 1-5');
    const [zone, setZone] = useState(trigger?.timezone ?? '');
    const [runAt, setRunAt] = useState(toLocalInput(trigger?.run_at ?? null));
    const [eventType, setEventType] = useState(trigger?.event_type ?? '');
    const initialConditions = asConditions(trigger?.filter ?? null);
    const [conditions, setConditions] = useState<FilterCondition[]>(initialConditions ?? []);
    const [filterJson, setFilterJson] = useState(initialConditions === null ? JSON.stringify(trigger?.filter, null, 2) : '');
    const [input, setInput] = useState(inputText(trigger?.input_template));
    const [overlap, setOverlap] = useState(trigger?.overlap ?? '');
    const [catchUp, setCatchUp] = useState(trigger?.catch_up ?? '');
    const [rate, setRate] = useState(trigger?.rate_per_hour?.toString() ?? '');
    const [maxRuns, setMaxRuns] = useState(trigger?.max_firings?.toString() ?? '');
    const [scope, setScope] = useState(trigger?.scope ?? '');

    const [preview, setPreview] = useState<{ times: string[]; timezone: string } | null>(null);
    const [previewError, setPreviewError] = useState('');
    const [tested, setTested] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);

    // The next ten times, as the schedule is typed.
    useEffect(() => {
        if (kind !== 'schedule' || !cron.trim()) {
            setPreview(null);
            return;
        }
        const handle = window.setTimeout(async () => {
            try {
                setPreview(await automationService.preview({ kind, cron, timezone: zone || null, count: 10 }));
                setPreviewError('');
            } catch (err) {
                setPreview(null);
                setPreviewError(errorText(err));
            }
        }, 400);
        return () => window.clearTimeout(handle);
    }, [kind, cron, zone]);

    const filter = (): TriggerFilter | null => (filterJson.trim() ? JSON.parse(filterJson) as TriggerFilter : toFilter(conditions));

    const testFilter = async () => {
        setTested('');
        try {
            const result = await automationService.testFilter(eventType, filter());
            setTested(result.checked
                ? `Matches ${result.matched} of the last ${result.checked} ${eventType} events.`
                : `No ${eventType} events yet to test against.`);
        } catch (err) {
            setTested(err instanceof SyntaxError ? 'The filter is not valid JSON.' : errorText(err));
        }
    };

    const save = async () => {
        setError('');
        if (kind === 'finished' && (!watchedId || watchedId === entityId)) {
            setError(watchedId ? 'An agent cannot start itself each time it finishes; choose another agent to run.'
                : 'Choose the agent whose finishing starts this one.');
            return;
        }
        let fields: TriggerFields;
        try {
            fields = {
                name: name.trim(),
                entity_id: entityId,
                input_template: parseInput(input),
                cron: kind === 'schedule' ? cron.trim() : null,
                timezone: kind === 'schedule' ? (zone || null) : null,
                run_at: kind === 'timer' && runAt ? fromLocalInput(runAt) : null,
                event_type: kind === 'event' ? eventType.trim() : null,
                filter: kind === 'event' ? filter() : null,
                ...(kind === 'finished' ? runFinishedFields(watchedId, outcome) : {}),
                overlap: overlap || null,
                catch_up: catchUp || null,
                rate_per_hour: numberOrNull(rate),
                max_firings: numberOrNull(maxRuns),
                scope: scope.trim() || null,
            };
        } catch {
            setError('The input or the filter is not valid JSON.');
            return;
        }
        setBusy(true);
        try {
            const saved = editing && trigger
                ? await automationService.updateTrigger(trigger.id, fields)
                : await automationService.createTrigger({ ...fields, kind: kind === 'finished' ? 'event' : kind });
            onSaved(saved);
        } catch (err) {
            setError(errorText(err));
        } finally {
            setBusy(false);
        }
    };

    const setCondition = (index: number, change: Partial<FilterCondition>) =>
        setConditions(list => list.map((c, i) => (i === index ? { ...c, ...change } : c)));

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal-content ar-editor" role="dialog" aria-label={editing ? 'Edit trigger' : 'New trigger'}
                 onClick={e => e.stopPropagation()}>
                <h2>{editing ? 'Edit trigger' : 'New trigger'}</h2>

                <label className="ar-field">
                    <span>Name</span>
                    <input className="ar-input" value={name} onChange={e => setName(e.target.value)}
                           placeholder="Daily sales report" aria-label="Name" />
                </label>

                <fieldset className="ar-group">
                    <legend>When</legend>
                    <div className="ar-kinds" role="radiogroup" aria-label="When">
                        {KINDS.map(k => (
                            <label key={k.kind} className={`ar-kind ${kind === k.kind ? 'ar-kind--on' : ''}`}>
                                <input type="radio" name="kind" value={k.kind} checked={kind === k.kind}
                                       disabled={editing} onChange={() => setKind(k.kind)} />
                                {k.label}
                            </label>
                        ))}
                    </div>

                    {kind === 'schedule' && (
                        <div className="ar-row">
                            <label className="ar-field">
                                <span>Repeat (cron)</span>
                                <input className="ar-input ar-mono" value={cron} onChange={e => setCron(e.target.value)}
                                       aria-label="Cron" placeholder="0 9 * * 1-5" />
                            </label>
                            <label className="ar-field">
                                <span>Time zone</span>
                                <input className="ar-input" value={zone} onChange={e => setZone(e.target.value)}
                                       aria-label="Time zone" placeholder={`${timezone} (business)`} />
                            </label>
                        </div>
                    )}
                    {kind === 'timer' && (
                        <label className="ar-field">
                            <span>Run at (your time)</span>
                            <input className="ar-input" type="datetime-local" value={runAt} aria-label="Run at"
                                   onChange={e => setRunAt(e.target.value)} />
                            {runAt && <small>{formatTime(fromLocalInput(runAt), timezone)} business time</small>}
                        </label>
                    )}
                    {kind === 'finished' && (
                        <div className="ar-row">
                            <label className="ar-field">
                                <span>When this agent</span>
                                <select className="ar-input" value={watchedId} aria-label="Watched agent"
                                        onChange={e => setWatchedId(e.target.value)}>
                                    <option value="">Choose an agent…</option>
                                    {agents.map(a => <option key={a.id} value={a.id}>{a.display_name || a.name}</option>)}
                                </select>
                            </label>
                            <label className="ar-field">
                                <span>Finishes</span>
                                <select className="ar-input" value={outcome} aria-label="Outcome"
                                        onChange={e => setOutcome(e.target.value as RunOutcome)}>
                                    <option value="completed">successfully</option>
                                    <option value="failed">with a failure</option>
                                    <option value="any">either way</option>
                                </select>
                            </label>
                        </div>
                    )}
                    {kind === 'event' && (
                        <>
                            <label className="ar-field">
                                <span>Event</span>
                                <input className="ar-input ar-mono" value={eventType} aria-label="Event type"
                                       onChange={e => setEventType(e.target.value)}
                                       placeholder="social.comment.created or record.order.*" />
                            </label>
                            {filterJson ? (
                                <label className="ar-field">
                                    <span>Only if (filter JSON)</span>
                                    <textarea className="ar-input ar-mono" rows={5} value={filterJson}
                                              onChange={e => setFilterJson(e.target.value)} aria-label="Filter" />
                                </label>
                            ) : (
                                <div className="ar-conditions">
                                    <span>Only if</span>
                                    {conditions.map((c, i) => (
                                        <div className="ar-row" key={i}>
                                            <input className="ar-input ar-mono" value={c.path} placeholder="data.text"
                                                   aria-label={`Condition ${i + 1} field`}
                                                   onChange={e => setCondition(i, { path: e.target.value })} />
                                            <select className="ar-input" value={c.op} aria-label={`Condition ${i + 1} test`}
                                                    onChange={e => setCondition(i, { op: e.target.value })}>
                                                {OPERATORS.map(([op, label]) => <option key={op} value={op}>{label}</option>)}
                                            </select>
                                            {c.op !== 'exists' && (
                                                <input className="ar-input" value={String(c.value ?? '')} placeholder="price"
                                                       aria-label={`Condition ${i + 1} value`}
                                                       onChange={e => setCondition(i, { value: e.target.value })} />
                                            )}
                                            <JellyButton size="sm" variant="ghost"
                                                         onClick={() => setConditions(list => list.filter((_, j) => j !== i))}>
                                                Remove
                                            </JellyButton>
                                        </div>
                                    ))}
                                    <div className="ar-row">
                                        <JellyButton size="sm" variant="ghost"
                                                     onClick={() => setConditions(list => [...list, { path: 'data.', op: 'contains', value: '' }])}>
                                            + condition
                                        </JellyButton>
                                        <JellyButton size="sm" variant="ghost" disabled={!eventType.trim()} onClick={testFilter}>
                                            Test against recent events
                                        </JellyButton>
                                    </div>
                                </div>
                            )}
                            {tested && <p className="ar-note" role="status">{tested}</p>}
                        </>
                    )}
                </fieldset>

                <fieldset className="ar-group">
                    <legend>Run</legend>
                    <label className="ar-field">
                        <span>Agent</span>
                        <select className="ar-input" value={entityId} onChange={e => setEntityId(e.target.value)} aria-label="Agent">
                            <option value="">Choose an agent…</option>
                            {agents.map(a => (
                                <option key={a.id} value={a.id}>{a.display_name || a.name} ({String(a.type).toLowerCase()})</option>
                            ))}
                        </select>
                    </label>
                    <label className="ar-field">
                        <span>Input</span>
                        <textarea className="ar-input" rows={3} value={input} onChange={e => setInput(e.target.value)}
                                  aria-label="Input"
                                  placeholder={kind === 'event' ? 'Reply politely to: {{ event.data.text }}'
                                      : kind === 'finished' ? 'Write up the research: {{ event.data.output }}'
                                          : 'Write today\'s sales report'} />
                    </label>
                </fieldset>

                <fieldset className="ar-group">
                    <legend>Rules</legend>
                    <div className="ar-row">
                        <label className="ar-field">
                            <span>If still running from last time</span>
                            <select className="ar-input" value={overlap} onChange={e => setOverlap(e.target.value)} aria-label="Overlap">
                                <option value="">Business setting</option>
                                <option value="allow">Run anyway</option>
                                <option value="queue">Wait its turn</option>
                                <option value="skip">Skip</option>
                            </select>
                        </label>
                        {(kind === 'schedule' || kind === 'timer') && (
                            <label className="ar-field">
                                <span>Missed while paused or down</span>
                                <select className="ar-input" value={catchUp} onChange={e => setCatchUp(e.target.value)} aria-label="Catch-up">
                                    <option value="">Business setting</option>
                                    <option value="all">Run each</option>
                                    <option value="once">Run once</option>
                                    <option value="skip">Skip</option>
                                </select>
                            </label>
                        )}
                    </div>
                    <div className="ar-row">
                        <label className="ar-field">
                            <span>At most runs per hour</span>
                            <input className="ar-input" type="number" min={1} value={rate} placeholder="business setting"
                                   onChange={e => setRate(e.target.value)} aria-label="Runs per hour" />
                        </label>
                        <label className="ar-field">
                            <span>Stop after runs</span>
                            <input className="ar-input" type="number" min={1} value={maxRuns} placeholder="no limit"
                                   onChange={e => setMaxRuns(e.target.value)} aria-label="Stop after" />
                        </label>
                        <label className="ar-field">
                            <span>Department or process</span>
                            <input className="ar-input" value={scope} placeholder="sales"
                                   onChange={e => setScope(e.target.value)} aria-label="Scope" />
                        </label>
                    </div>
                </fieldset>

                {kind === 'schedule' && (
                    <fieldset className="ar-group">
                        <legend>Preview</legend>
                        {previewError && <p className="ar-note ar-note--bad">{previewError}</p>}
                        {preview && (
                            <ol className="ar-preview" aria-label="Next run times">
                                {preview.times.map(t => <li key={t}>{formatDay(t, preview.timezone)}</li>)}
                            </ol>
                        )}
                        {preview && <small>Times in {preview.timezone}.</small>}
                    </fieldset>
                )}

                {error && <p className="ar-note ar-note--bad" role="alert">{error}</p>}
                <div className="ar-actions">
                    <JellyButton variant="ghost" onClick={onClose} disabled={busy}>Cancel</JellyButton>
                    <JellyButton variant="primary" onClick={save} disabled={busy || !name.trim() || !entityId}>
                        {editing ? 'Save changes' : 'Save trigger'}
                    </JellyButton>
                </div>
                <p className="ar-note">Saving runs nothing. Use <strong>Run now</strong> on the list to try it.</p>
            </div>
        </div>
    );
};

export default TriggerEditor;
