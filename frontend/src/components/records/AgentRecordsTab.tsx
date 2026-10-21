/**
 * components/records/AgentRecordsTab — an agent's Records tab in the builder
 * (Phase 14 W4-2; tech spec §7.11, §9.3).
 *
 * Which of the business's tables the agent may use, and how: read, create,
 * update, archive — its `capabilities.records`, which its run token carries
 * to the Data API. Run reports, and propose changes to the data structure (a
 * person approves each in Approvals). The record tools follow the choices:
 * each is granted while some table allows what it does, so the model is only
 * offered tools it can use.
 */
import React from 'react';
import { useQuery } from '@tanstack/react-query';

import { problemText, recordsService, type Blueprint } from '@/services/records.service';

import '../automation/automation.css';

export type RecordOperation = 'read' | 'create' | 'update' | 'delete';

export interface AgentRecords {
    objects: Record<string, RecordOperation[]>;
    reports: boolean;
    schema_changes: 'none' | 'propose';
}

const OPERATIONS: { op: RecordOperation; label: string }[] = [
    { op: 'read', label: 'Read' }, { op: 'create', label: 'Create' },
    { op: 'update', label: 'Update' }, { op: 'delete', label: 'Archive' },
];

/** The record tools each permission needs (src/ai/tools/records). */
export const TOOLS_FOR: Record<RecordOperation, string[]> = {
    read: ['describe_schema', 'find_records', 'get_record'],
    create: ['describe_schema', 'create_record'],
    update: ['describe_schema', 'update_record', 'link_records'],
    delete: ['describe_schema', 'archive_record'],
};
export const REPORT_TOOLS = ['run_report'];
export const PROPOSE_TOOLS = ['describe_schema', 'propose_schema_change'];
export const RECORD_TOOLS = Array.from(new Set([...Object.values(TOOLS_FOR).flat(), ...REPORT_TOOLS, ...PROPOSE_TOOLS]));

const ALL: RecordOperation[] = ['read', 'create', 'update', 'delete'];

export const recordsOf = (capabilities: unknown): AgentRecords => {
    const raw = (capabilities as { records?: { objects?: Record<string, unknown>; reports?: boolean;
                                                schema_changes?: string } } | undefined)?.records;
    // "*" (every operation) as the four; an all-tables "*" entry is kept as it is.
    const objects: AgentRecords['objects'] = {};
    for (const [name, ops] of Object.entries(raw?.objects ?? {})) {
        const list = ops === '*' ? ['*'] : Array.isArray(ops) ? ops.map(String) : [];
        objects[name] = list.includes('*') ? [...ALL] : ALL.filter(op => list.includes(op));
    }
    return {
        objects,
        reports: Boolean(raw?.reports),
        schema_changes: raw?.schema_changes === 'propose' ? 'propose' : 'none',
    };
};

/** The record tools a set of permissions needs. */
export const toolsFor = (value: AgentRecords): string[] => {
    const tools = new Set<string>();
    for (const ops of Object.values(value.objects)) ops.forEach(op => TOOLS_FOR[op]?.forEach(t => tools.add(t)));
    if (value.reports) REPORT_TOOLS.forEach(t => tools.add(t));
    if (value.schema_changes === 'propose') PROPOSE_TOOLS.forEach(t => tools.add(t));
    return Array.from(tools);
};

interface Props {
    value: AgentRecords;
    onChange: (next: AgentRecords) => void;
    /** Grant (true) or withdraw (false) tools; called with every record tool, then with the ones needed. */
    onToolsChange: (tools: string[], granted: boolean) => void;
    /** For tests: the business's data structure (else read from the Data API). */
    blueprint?: Blueprint;
}

export const AgentRecordsTab: React.FC<Props> = ({ value, onChange, onToolsChange, blueprint }) => {
    const schema = useQuery({ queryKey: ['records', 'schema'], queryFn: recordsService.schema, enabled: !blueprint,
                              retry: false });
    const objects = Object.entries((blueprint ?? schema.data)?.objects ?? {})
        .sort(([, a], [, b]) => a.label.localeCompare(b.label));

    const change = (next: AgentRecords) => {
        onChange(next);
        onToolsChange(RECORD_TOOLS, false);
        const needed = toolsFor(next);
        if (needed.length) onToolsChange(needed, true);
    };
    const toggle = (name: string, op: RecordOperation, on: boolean) => {
        const current = new Set(value.objects[name] ?? []);
        if (on) {
            current.add(op);
            if (op !== 'read') current.add('read'); // changing a record means finding it first
        } else {
            current.delete(op);
            if (op === 'read') current.clear();     // nothing else works without reading
        }
        const objectsNext = { ...value.objects };
        if (current.size) objectsNext[name] = OPERATIONS.map(o => o.op).filter(o => current.has(o));
        else delete objectsNext[name];
        change({ ...value, objects: objectsNext });
    };

    return (
        <div className="tab-panel ar-agent-tab">
            <div className="form-section">
                <h3>The business's records it may use</h3>
                <p className="ar-note">What this agent's record tools may do in each table. Nothing is allowed
                    until you tick it; archived records stay recoverable.</p>
                {!blueprint && schema.isLoading && <p className="ar-note">Loading the tables…</p>}
                {!blueprint && schema.isError && (
                    <p className="ar-note" role="alert">{problemText(schema.error, 'The tables could not be read.')}</p>
                )}
                {objects.length > 0 && (
                    <table className="ar-table" aria-label="Tables and what it may do">
                        <thead>
                            <tr><th>Table</th>{OPERATIONS.map(o => <th key={o.op}>{o.label}</th>)}</tr>
                        </thead>
                        <tbody>
                            {objects.map(([name, spec]) => (
                                <tr key={name}>
                                    <td>{spec.plural || spec.label} <small>({name})</small></td>
                                    {OPERATIONS.map(o => (
                                        <td key={o.op}>
                                            <input type="checkbox" aria-label={`${o.label} ${spec.plural || spec.label}`}
                                                   checked={(value.objects[name] ?? []).includes(o.op)}
                                                   onChange={e => toggle(name, o.op, e.target.checked)} />
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
            <div className="form-section">
                <h3>Beyond single records</h3>
                <label className="ar-check">
                    <input type="checkbox" checked={value.reports} aria-label="May run reports"
                           onChange={e => change({ ...value, reports: e.target.checked })} />
                    <span>
                        <strong>May run reports</strong>
                        <small>Counts, sums and averages over the tables it may read ("revenue by month").</small>
                    </span>
                </label>
                <label className="ar-check">
                    <input type="checkbox" checked={value.schema_changes === 'propose'}
                           aria-label="May propose data changes"
                           onChange={e => change({ ...value, schema_changes: e.target.checked ? 'propose' : 'none' })} />
                    <span>
                        <strong>May propose changes to the data structure</strong>
                        <small>A new table or field it needs. Each proposal waits in Approvals for a person, unless
                            the business auto-approves simple additions.</small>
                    </span>
                </label>
            </div>
        </div>
    );
};

export default AgentRecordsTab;
