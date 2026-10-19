/**
 * pages/records/SchemaPage — tables and fields, and changes to them (Phase 14 WS8 8.2; functional spec §4.3).
 *
 * The schema designer lists every table with its fields; **Propose change**
 * adds a table or a field. Each proposal is previewed first (what it adds,
 * warnings), then sent: an owner's addition applies at once, an agent's waits
 * in **Changes to review** with its impact until a person approves or rejects.
 */
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { JellyButton } from '@/components/ui';
import { formatTime } from '@/components/automation/describe';
import { useAuth } from '@/hooks/useAuth';
import { actorLabel, problemText, recordsService, type FieldType, type SchemaChange } from '@/services/records.service';
import { UserRole } from '@/types';

import { LOCAL_TZ } from './RecordsPage';
import '@/components/automation/automation.css';

const ADMINS = [UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN];

export const FIELD_TYPES: { type: FieldType; label: string }[] = [
    { type: 'text', label: 'Text' }, { type: 'long_text', label: 'Long text' }, { type: 'integer', label: 'Number' },
    { type: 'decimal', label: 'Decimal' }, { type: 'money', label: 'Money' }, { type: 'boolean', label: 'Yes / no' },
    { type: 'date', label: 'Date' }, { type: 'datetime', label: 'Date and time' }, { type: 'enum', label: 'Choice list' },
    { type: 'email', label: 'Email' }, { type: 'phone', label: 'Phone' }, { type: 'url', label: 'Web address' },
    { type: 'ref', label: 'Link to another table' }, { type: 'file', label: 'File' },
];

/** A name from a label: lower-case letters, digits and underscores (functional spec §4.4). */
export const nameFrom = (label: string): string =>
    label.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^(\d)/, 'f_$1').slice(0, 40);

interface FieldDraft { label: string; type: FieldType; required: boolean; values: string; to: string }

const emptyField = (): FieldDraft => ({ label: '', type: 'text', required: false, values: '', to: '' });

/** The proposal's operations from what the person filled in. */
export const operationsFor = (mode: 'table' | 'field', table: string, tableLabel: string, fields: FieldDraft[]):
    Record<string, unknown>[] => {
    const definition = (f: FieldDraft): Record<string, unknown> => ({
        type: f.type, label: f.label, ...(f.required ? { required: true } : {}),
        ...(f.type === 'enum' ? { values: f.values.split(',').map(v => v.trim()).filter(Boolean) } : {}),
        ...(f.type === 'ref' ? { to: f.to } : {}),
    });
    const named = fields.filter(f => f.label.trim());
    if (mode === 'table') {
        return [{ op: 'add_object', object: nameFrom(tableLabel), definition: {
            label: tableLabel, fields: Object.fromEntries(named.map(f => [nameFrom(f.label), definition(f)])) } }];
    }
    return named.map(f => ({ op: f.type === 'ref' ? 'add_relation' : 'add_field', object: table,
                             field: nameFrom(f.label), definition: definition(f) }));
};

const Proposal: React.FC<{ tables: string[]; onDone: (change: SchemaChange) => void; onCancel: () => void }> = ({
    tables, onDone, onCancel }) => {
    const [mode, setMode] = useState<'table' | 'field'>('table');
    const [table, setTable] = useState(tables[0] ?? '');
    const [tableLabel, setTableLabel] = useState('');
    const [fields, setFields] = useState<FieldDraft[]>([emptyField()]);
    const [reason, setReason] = useState('');
    const [preview, setPreview] = useState<SchemaChange | null>(null);
    const [error, setError] = useState<string | null>(null);
    const ops = operationsFor(mode, table, tableLabel, fields);

    const run = async (dryRun: boolean) => {
        setError(null);
        try {
            const change = await recordsService.propose(ops, reason || undefined, dryRun);
            if (dryRun) setPreview(change); else onDone(change);
        } catch (err) {
            setError(problemText(err, 'This change cannot be made.'));
            setPreview(null);
        }
    };
    const setField = (i: number, patch: Partial<FieldDraft>) =>
        setFields(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)));

    return (
        <section className="ar-section" aria-label="Propose a change">
            <h2>Propose a change</h2>
            <div className="ar-kinds">
                <label className={`ar-kind ${mode === 'table' ? 'ar-kind--on' : ''}`}>
                    <input type="radio" checked={mode === 'table'} onChange={() => setMode('table')} /> A new table
                </label>
                <label className={`ar-kind ${mode === 'field' ? 'ar-kind--on' : ''}`}>
                    <input type="radio" checked={mode === 'field'} onChange={() => setMode('field')} /> Fields on a table
                </label>
            </div>
            {mode === 'table' ? (
                <label className="ar-field"><span>Table name (e.g. Shipments → shipments)</span>
                    <input className="ar-input" value={tableLabel} onChange={e => setTableLabel(e.target.value)} />
                    {tableLabel && <small>Saved as <code>{nameFrom(tableLabel)}</code></small>}
                </label>
            ) : (
                <label className="ar-field"><span>Table</span>
                    <select className="ar-input" value={table} onChange={e => setTable(e.target.value)}>
                        {tables.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                </label>
            )}
            {fields.map((f, i) => (
                <div key={i} className="ar-row" role="group" aria-label={`Field ${i + 1}`}>
                    <label className="ar-field"><span>Field</span>
                        <input className="ar-input" value={f.label} onChange={e => setField(i, { label: e.target.value })} />
                    </label>
                    <label className="ar-field"><span>Type</span>
                        <select className="ar-input" value={f.type} onChange={e => setField(i, { type: e.target.value as FieldType })}>
                            {FIELD_TYPES.map(t => <option key={t.type} value={t.type}>{t.label}</option>)}
                        </select>
                    </label>
                    {f.type === 'enum' && (
                        <label className="ar-field"><span>Choices (comma-separated)</span>
                            <input className="ar-input" value={f.values} onChange={e => setField(i, { values: e.target.value })} />
                        </label>
                    )}
                    {f.type === 'ref' && (
                        <label className="ar-field"><span>Links to</span>
                            <select className="ar-input" value={f.to} onChange={e => setField(i, { to: e.target.value })}>
                                <option value="">—</option>
                                {tables.map(t => <option key={t} value={t}>{t}</option>)}
                            </select>
                        </label>
                    )}
                    <label className="ar-check ar-check--small">
                        <input type="checkbox" checked={f.required} onChange={e => setField(i, { required: e.target.checked })} />
                        <span>Required</span>
                    </label>
                </div>
            ))}
            <div className="ar-row">
                <JellyButton variant="ghost" size="sm" onClick={() => setFields([...fields, emptyField()])}>+ Field</JellyButton>
                <label className="ar-field"><span>Why (shown to whoever approves)</span>
                    <input className="ar-input" value={reason} onChange={e => setReason(e.target.value)} />
                </label>
            </div>
            {preview && (
                <div className="ar-detail" aria-label="Preview">
                    <h4>What it does</h4>
                    <ul className="ar-decisions">{(preview.plan?.summary || []).map(s => <li key={s}>{s}</li>)}</ul>
                    {(preview.plan?.checks || []).map(c => <p key={c.message} className="ar-note ar-note--bad">{c.message}</p>)}
                </div>
            )}
            {error && <p className="ar-note ar-note--bad" role="alert">{error}</p>}
            <div className="ar-actions">
                <JellyButton variant="ghost" size="sm" onClick={onCancel}>Cancel</JellyButton>
                <JellyButton variant="secondary" size="sm" disabled={!ops.length} onClick={() => run(true)}>Preview</JellyButton>
                <JellyButton size="sm" disabled={!preview} onClick={() => run(false)}>Propose</JellyButton>
            </div>
        </section>
    );
};

const ChangeRow: React.FC<{ change: SchemaChange; canDecide: boolean; onDecided: () => void }> = ({
    change, canDecide, onDecided }) => {
    const [error, setError] = useState<string | null>(null);
    const impact = change.impact || {};
    const decide = async (approve: boolean) => {
        try { await recordsService.decide(change.id, approve); onDecided(); }
        catch (err) { setError(problemText(err, 'Could not decide.')); }
    };
    return (
        <li className="ar-detail">
            <div className="ar-detail__head">
                <span className={`ar-pill ar-pill--${change.status === 'applied' ? 'active' : change.status === 'rejected'
                    ? 'dead' : 'paused'}`}>{change.status.replace(/_/g, ' ')}</span>
                <span>{formatTime(change.created_at, LOCAL_TZ)} by {actorLabel(change.actor_id || change.actor_kind)}</span>
                {change.reason && <em>— {change.reason}</em>}
            </div>
            <ul className="ar-decisions">{(change.plan?.summary || []).map(s => <li key={s}>{s}</li>)}</ul>
            {Object.keys(impact).length > 0 && (
                <p className="ar-note">Affects: {Object.entries(impact).map(([k, v]) =>
                    `${k.replace(/_/g, ' ')}: ${Array.isArray(v) ? v.length : String(v)}`).join(' · ')}</p>
            )}
            {change.error && <p className="ar-note ar-note--bad">{change.error}</p>}
            {canDecide && change.status === 'awaiting_approval' && (
                <div className="ar-row">
                    <JellyButton size="sm" onClick={() => decide(true)}>Approve</JellyButton>
                    <JellyButton size="sm" variant="ghost" onClick={() => decide(false)}>Reject</JellyButton>
                </div>
            )}
            {error && <p className="ar-note ar-note--bad">{error}</p>}
        </li>
    );
};

export const SchemaPage: React.FC = () => {
    const { user } = useAuth();
    const canDecide = ADMINS.includes(user?.role as UserRole);
    const queryClient = useQueryClient();
    const schema = useQuery({ queryKey: ['records', 'schema'], queryFn: recordsService.schema });
    const changes = useQuery({ queryKey: ['records', 'changes'], queryFn: () => recordsService.changes() });
    const [proposing, setProposing] = useState(false);
    const [note, setNote] = useState<string | null>(null);
    const objects = schema.data?.objects ?? {};
    const waiting = (changes.data || []).filter(c => c.status === 'awaiting_approval');
    const refresh = () => queryClient.invalidateQueries({ queryKey: ['records'] });

    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>Tables and fields</h1>
                    <p>Version {schema.data?.version ?? '—'}. Adding is easy; renaming keeps the old name working for a
                        while; removing means archiving.</p>
                </div>
                <div className="ar-row">
                    <Link to="/records" className="ar-link">Records</Link>
                    <JellyButton size="sm" onClick={() => setProposing(true)}>Propose change</JellyButton>
                </div>
            </header>
            {note && <p className="ar-note ar-note--ok" role="status">{note}</p>}
            {proposing && (
                <Proposal tables={Object.keys(objects)} onCancel={() => setProposing(false)}
                          onDone={change => {
                              setProposing(false);
                              setNote(change.status === 'applied' ? 'Applied: the table is live in Records, the API and agents.'
                                  : 'Sent for approval.');
                              refresh();
                          }} />
            )}
            {waiting.length > 0 && (
                <section className="ar-section" aria-label="Changes to review">
                    <h2>Changes to review ({waiting.length})</h2>
                    <ul className="ar-attention">
                        {waiting.map(c => <ChangeRow key={c.id} change={c} canDecide={canDecide} onDecided={refresh} />)}
                    </ul>
                </section>
            )}
            {Object.entries(objects).map(([name, object]) => (
                <section key={name} className="ar-section" aria-label={object.plural}>
                    <h2>{object.plural} <span className="ar-tag ar-mono">{name}</span>
                        {object.platform && <span className="ar-tag">standard</span>}
                        {object.row_policy && <span className="ar-tag">owner: {object.row_policy.owner_field}</span>}</h2>
                    <table className="ar-table">
                        <thead><tr><th>Field</th><th>Name</th><th>Type</th><th>Required</th><th>Links to</th></tr></thead>
                        <tbody>
                            {Object.entries(object.fields).filter(([, f]) => !f.archived).map(([field, spec]) => (
                                <tr key={field}>
                                    <td>{spec.label || field}</td><td className="ar-mono">{field}</td>
                                    <td>{FIELD_TYPES.find(t => t.type === spec.type)?.label ?? spec.type}
                                        {spec.sensitivity && spec.sensitivity !== 'none' && <span className="ar-tag">{spec.sensitivity}</span>}</td>
                                    <td>{spec.required ? 'Yes' : ''}</td><td>{spec.to ?? ''}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </section>
            ))}
            <section className="ar-section" aria-label="All changes">
                <h2>History of changes</h2>
                <ul className="ar-attention">
                    {(changes.data || []).filter(c => c.status !== 'awaiting_approval').slice(0, 30).map(c => (
                        <ChangeRow key={c.id} change={c} canDecide={false} onDecided={refresh} />
                    ))}
                </ul>
            </section>
        </div>
    );
};

export default SchemaPage;
