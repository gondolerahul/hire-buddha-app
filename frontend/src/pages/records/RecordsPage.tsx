/**
 * pages/records/RecordsPage — the business's own records (Phase 14 WS8 8.2; functional spec §4.2).
 *
 * Tables as tabs (Accounts, Contacts, … and every table the business added);
 * a table's records with search and paging; a record's form and its history
 * (who changed what: a person, an agent, an app). A second save of a record
 * someone else changed is refused: "this record changed — reload".
 */
import React, { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { JellyButton } from '@/components/ui';
import { formatTime } from '@/components/automation/describe';
import {
    actorLabel, editableFields, isStale, problemText, recordsService,
    type FieldSpec, type ObjectSpec, type RecordRow,
} from '@/services/records.service';

import '@/components/automation/automation.css';

/** The viewer's own time zone, for when records changed. */
export const LOCAL_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

const INPUT_TYPE: Record<string, string> = {
    integer: 'number', decimal: 'number', money: 'number', date: 'date', datetime: 'datetime-local',
    email: 'email', url: 'url', phone: 'tel',
};

const shown = (value: unknown): string => {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    return String(value);
};

const NAME_LIKE = ['name', 'title', 'first_name', 'email', 'subject'];

/** The field the search box searches: a name-like one first, else the first text or e-mail field. */
export const searchFieldOf = (object: ObjectSpec): string | undefined => {
    const fields = Object.entries(object.fields).filter(([, f]) => ['text', 'email'].includes(f.type) && !f.archived);
    return NAME_LIKE.find(n => fields.some(([field]) => field === n)) ?? fields[0]?.[0];
};

/** A form value as the Data API takes it. */
export const toValue = (spec: FieldSpec, raw: string | boolean): unknown => {
    if (spec.type === 'boolean') return Boolean(raw);
    if (raw === '') return null;
    if (spec.type === 'integer') return Number(raw);
    return raw;
};

const RecordForm: React.FC<{
    name: string; object: ObjectSpec; record: RecordRow | null; onDone: () => void; onCancel: () => void;
}> = ({ name, object, record, onDone, onCancel }) => {
    const fields = editableFields(object);
    const [values, setValues] = useState<Record<string, string | boolean>>(() => Object.fromEntries(
        fields.map(([field, spec]) => [field, spec.type === 'boolean' ? Boolean(record?.[field])
            : record?.[field] === null || record?.[field] === undefined ? '' : String(record[field])])));
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const history = useQuery({
        queryKey: ['records', 'history', name, record?.id],
        queryFn: () => recordsService.history(name, record!.id),
        enabled: Boolean(record),
    });

    const save = async (event: React.FormEvent) => {
        event.preventDefault();
        setBusy(true);
        setError(null);
        const body: Record<string, unknown> = {};
        for (const [field, spec] of fields) {
            const value = toValue(spec, values[field]);
            const before = record?.[field] ?? null;
            if (!record || String(value ?? '') !== String(before ?? '')) body[field] = value;
        }
        try {
            if (record) {
                if (Object.keys(body).length) await recordsService.update(name, record.id, record.row_version, body);
            } else {
                await recordsService.create(name, body);
            }
            onDone();
        } catch (err) {
            setError(isStale(err) ? 'This record changed since you opened it — reload it and make your change again.'
                : problemText(err, 'Could not save.'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="ar-section" onSubmit={save} aria-label={record ? `Edit ${object.label}` : `New ${object.label}`}>
            <h2>{record ? `${object.label}` : `New ${object.label}`}</h2>
            <div className="ar-row">
                {fields.map(([field, spec]) => (
                    <label key={field} className="ar-field">
                        <span>{spec.label || field}{spec.required ? ' *' : ''}</span>
                        {spec.type === 'enum' ? (
                            <select className="ar-input" value={String(values[field])}
                                    onChange={e => setValues({ ...values, [field]: e.target.value })}>
                                <option value="">—</option>
                                {(spec.values || []).map(v => <option key={v} value={v}>{v}</option>)}
                            </select>
                        ) : spec.type === 'boolean' ? (
                            <input type="checkbox" checked={Boolean(values[field])}
                                   onChange={e => setValues({ ...values, [field]: e.target.checked })} />
                        ) : spec.type === 'long_text' ? (
                            <textarea className="ar-input" rows={3} value={String(values[field])}
                                      onChange={e => setValues({ ...values, [field]: e.target.value })} />
                        ) : (
                            <input className="ar-input" type={INPUT_TYPE[spec.type] || 'text'}
                                   step={spec.type === 'decimal' || spec.type === 'money' ? 'any' : undefined}
                                   required={spec.required && !record} value={String(values[field])}
                                   placeholder={spec.type === 'ref' ? `${spec.to} id` : undefined}
                                   onChange={e => setValues({ ...values, [field]: e.target.value })} />
                        )}
                    </label>
                ))}
            </div>
            {error && <p className="ar-note ar-note--bad" role="alert">{error}</p>}
            <div className="ar-actions">
                {record && (
                    <JellyButton variant="danger" size="sm" disabled={busy} onClick={async () => {
                        if (!window.confirm(`Archive this ${object.label.toLowerCase()}? It disappears from lists.`)) return;
                        try { await recordsService.archive(name, record.id); onDone(); }
                        catch (err) { setError(problemText(err, 'Could not archive.')); }
                    }}>Archive</JellyButton>
                )}
                <JellyButton variant="ghost" size="sm" onClick={onCancel}>Cancel</JellyButton>
                <JellyButton type="submit" size="sm" disabled={busy}>{busy ? 'Saving…' : 'Save'}</JellyButton>
            </div>
            {record && (
                <>
                    <h4>History</h4>
                    {history.isLoading ? <p className="ar-note">Loading…</p> : (
                        <ul className="ar-decisions" aria-label="History">
                            {(history.data || []).map((h, i) => (
                                <li key={i}>{formatTime(h.at, LOCAL_TZ)} · <strong>{h.action}</strong> by {actorLabel(h.actor)}
                                    {h.changed.length > 0 && <span> — {h.changed.join(', ')}</span>}</li>
                            ))}
                        </ul>
                    )}
                </>
            )}
        </form>
    );
};

export const RecordsPage: React.FC = () => {
    const queryClient = useQueryClient();
    const schema = useQuery({ queryKey: ['records', 'schema'], queryFn: recordsService.schema });
    const objects = useMemo(() => schema.data?.objects ?? {}, [schema.data]);
    const names = useMemo(() => Object.keys(objects), [objects]);
    const [current, setCurrent] = useState<string | null>(null);
    const name = current && objects[current] ? current : names[0];
    const object = name ? objects[name] : undefined;
    const [search, setSearch] = useState('');
    const [after, setAfter] = useState<string | undefined>(undefined);
    const [editing, setEditing] = useState<RecordRow | 'new' | null>(null);

    const searchField = useMemo(() => object && searchFieldOf(object), [object]);
    const params: Record<string, string> = {};
    if (after) params['page[after]'] = after;
    if (search && searchField) params[`filter[${searchField}][contains]`] = search;
    const page = useQuery({
        queryKey: ['records', 'list', name, params],
        queryFn: () => recordsService.list(name!, params),
        enabled: Boolean(name),
    });
    const columns = object ? editableFields(object).slice(0, 5) : [];

    if (schema.isError) {
        return (
            <div className="page-container ar-page">
                <h1>Records</h1>
                <p className="ar-note ar-note--bad">{problemText(schema.error, 'Your records are not available yet.')}</p>
            </div>
        );
    }
    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>Records</h1>
                    <p>Your business's own tables. Agents, apps and keys use the same records through the Data API.</p>
                </div>
                <div className="ar-row">
                    <Link to="/records/schema" className="ar-link">Tables and fields</Link>
                    <Link to="/records/keys" className="ar-link">API keys</Link>
                </div>
            </header>
            <nav className="ar-tabs" aria-label="Tables">
                {names.map(n => (
                    <button key={n} className={n === name ? 'ar-tab--on' : ''}
                            onClick={() => { setCurrent(n); setAfter(undefined); setEditing(null); setSearch(''); }}>
                        {objects[n].plural}
                    </button>
                ))}
            </nav>
            {object && name && (
                <>
                    <div className="ar-row">
                        {searchField && (
                            <label className="ar-field" style={{ maxWidth: 320 }}>
                                <span>Search {object.fields[searchField].label || searchField}</span>
                                <input className="ar-input" value={search}
                                       onChange={e => { setSearch(e.target.value); setAfter(undefined); }} />
                            </label>
                        )}
                        <JellyButton size="sm" onClick={() => setEditing('new')}>+ New {object.label}</JellyButton>
                    </div>
                    {editing && (
                        <RecordForm key={editing === 'new' ? 'new' : editing.id} name={name} object={object}
                                    record={editing === 'new' ? null : editing}
                                    onCancel={() => setEditing(null)}
                                    onDone={() => { setEditing(null);
                                        queryClient.invalidateQueries({ queryKey: ['records', 'list', name] }); }} />
                    )}
                    <table className="ar-table" aria-label={object.plural}>
                        <thead><tr>
                            {columns.map(([field, spec]) => <th key={field}>{spec.label || field}</th>)}
                            <th>Updated</th>
                        </tr></thead>
                        <tbody>
                            {(page.data?.items || []).map(row => (
                                <tr key={row.id} className="ar-clickable" onClick={() => setEditing(row)}>
                                    {columns.map(([field]) => <td key={field}>{shown(row[field])}</td>)}
                                    <td>{row.updated_at ? formatTime(String(row.updated_at), LOCAL_TZ) : '—'}
                                        {row.updated_by && <small> by {actorLabel(String(row.updated_by))}</small>}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {page.isLoading && <p className="ar-note">Loading…</p>}
                    {page.data && !page.data.items.length && <p className="ar-note">No {object.plural.toLowerCase()} yet.</p>}
                    <div className="ar-row">
                        {after && <JellyButton variant="ghost" size="sm" onClick={() => setAfter(undefined)}>First page</JellyButton>}
                        {page.data?.next && <JellyButton variant="ghost" size="sm"
                                                         onClick={() => setAfter(page.data!.next!)}>Next page</JellyButton>}
                    </div>
                </>
            )}
        </div>
    );
};

export default RecordsPage;
