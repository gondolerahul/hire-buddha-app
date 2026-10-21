/**
 * components/automation/ConditionEditor — the "if" of a condition trigger
 * (Phase 14 W4-2; backend src/automation/conditions.py): "every hour, if the
 * count of products where stock < 10 is more than 0 → run the re-order agent".
 *
 * One number from the business's records — a count, or the sum / average /
 * minimum / maximum of a field over the records passing the filters —
 * compared with a value. Checked each time the schedule fires, without a
 * model call; when it does not hold, nothing runs.
 */
import React from 'react';
import { useQuery } from '@tanstack/react-query';

import { JellyButton } from '@/components/ui';
import type { TriggerCondition } from '@/services/automation.service';
import { recordsService, type Blueprint } from '@/services/records.service';

const MEASURES: { fn: TriggerCondition['measure']['fn']; label: string }[] = [
    { fn: 'count', label: 'the number of' }, { fn: 'sum', label: 'the total of' },
    { fn: 'avg', label: 'the average of' }, { fn: 'min', label: 'the lowest' }, { fn: 'max', label: 'the highest' },
];
const COMPARISONS: { op: TriggerCondition['op']; label: string }[] = [
    { op: 'gt', label: 'is more than' }, { op: 'gte', label: 'is at least' }, { op: 'lt', label: 'is less than' },
    { op: 'lte', label: 'is at most' }, { op: 'eq', label: 'is' }, { op: 'ne', label: 'is not' },
];
const FILTER_OPS: [string, string][] = [
    ['eq', 'is'], ['ne', 'is not'], ['lt', '<'], ['lte', '≤'], ['gt', '>'], ['gte', '≥'],
    ['contains', 'contains'], ['starts_with', 'starts with'], ['in', 'is one of'], ['is_null', 'is empty'],
];
const NUMERIC = new Set(['integer', 'decimal', 'money']);

export const emptyCondition = (): TriggerCondition => ({ object: '', filter: [], measure: { fn: 'count' }, op: 'gt', value: 0 });

/** The condition as the backend stores it, or null when it is not complete enough to save. */
export const conditionProblem = (c: TriggerCondition): string | null => {
    if (!c.object) return 'Choose the records to check.';
    if (c.measure.fn !== 'count' && !c.measure.field) return 'Choose the field to add up.';
    if (c.filter.some(([field]) => !field)) return 'Each filter needs a field.';
    if (String(c.value).trim() === '' || Number.isNaN(Number(c.value))) return 'The value to compare with is a number.';
    return null;
};

/** A filter value as typed: numbers and true/false as such (the Data API reads text too). */
const typed = (text: string): unknown => {
    if (/^-?\d+(\.\d+)?$/.test(text.trim())) return Number(text);
    if (text === 'true' || text === 'false') return text === 'true';
    return text;
};

interface Props {
    value: TriggerCondition;
    onChange: (next: TriggerCondition) => void;
    /** For tests: the business's data structure (else read from the Data API). */
    blueprint?: Blueprint;
}

export const ConditionEditor: React.FC<Props> = ({ value, onChange, blueprint }) => {
    const schema = useQuery({ queryKey: ['records', 'schema'], queryFn: recordsService.schema, enabled: !blueprint,
                              retry: false });
    const objects = (blueprint ?? schema.data)?.objects ?? {};
    const fields = Object.entries(objects[value.object]?.fields ?? {}).filter(([, f]) => !f.archived);
    const numeric = fields.filter(([, f]) => NUMERIC.has(f.type));
    const set = (change: Partial<TriggerCondition>) => onChange({ ...value, ...change });
    const setFilter = (index: number, part: 0 | 1 | 2, next: unknown) =>
        set({ filter: value.filter.map((rule, i) => {
            if (i !== index) return rule;
            const copy = [...rule] as [string, string, unknown];
            if (part === 2) copy[2] = next;
            else copy[part] = String(next);
            return copy;
        }) });

    return (
        <div className="ar-conditions" aria-label="Condition">
            <span>Only if</span>
            {!blueprint && schema.isError && (
                <p className="ar-note ar-note--bad" role="alert">This business has no records to check yet.</p>
            )}
            <div className="ar-row">
                <select className="ar-input" aria-label="Measure" value={value.measure.fn}
                        onChange={e => set({ measure: { fn: e.target.value as TriggerCondition['measure']['fn'],
                                                         ...(e.target.value === 'count' ? {} : { field: value.measure.field }) } })}>
                    {MEASURES.map(m => <option key={m.fn} value={m.fn}>{m.label}</option>)}
                </select>
                {value.measure.fn !== 'count' && (
                    <select className="ar-input" aria-label="Measured field" value={value.measure.field ?? ''}
                            onChange={e => set({ measure: { ...value.measure, field: e.target.value } })}>
                        <option value="">field…</option>
                        {numeric.map(([name, f]) => <option key={name} value={name}>{f.label || name}</option>)}
                    </select>
                )}
                <select className="ar-input" aria-label="Records" value={value.object}
                        onChange={e => set({ object: e.target.value, filter: [], measure: { fn: value.measure.fn } })}>
                    <option value="">records…</option>
                    {Object.entries(objects).map(([name, o]) => <option key={name} value={name}>{o.plural || o.label}</option>)}
                </select>
            </div>
            {value.filter.map(([field, op, val], i) => (
                <div className="ar-row" key={i}>
                    <span className="ar-note">{i === 0 ? 'where' : 'and'}</span>
                    <select className="ar-input" aria-label={`Filter ${i + 1} field`} value={field}
                            onChange={e => setFilter(i, 0, e.target.value)}>
                        <option value="">field…</option>
                        {fields.map(([name, f]) => <option key={name} value={name}>{f.label || name}</option>)}
                    </select>
                    <select className="ar-input" aria-label={`Filter ${i + 1} test`} value={op}
                            onChange={e => setFilter(i, 1, e.target.value)}>
                        {FILTER_OPS.map(([o, label]) => <option key={o} value={o}>{label}</option>)}
                    </select>
                    {op === 'is_null' ? null : (
                        <input className="ar-input" aria-label={`Filter ${i + 1} value`} value={String(val ?? '')}
                               placeholder="10, now-7d, paid" onChange={e => setFilter(i, 2, typed(e.target.value))} />
                    )}
                    <JellyButton size="sm" variant="ghost"
                                 onClick={() => set({ filter: value.filter.filter((_, j) => j !== i) })}>Remove</JellyButton>
                </div>
            ))}
            <div className="ar-row">
                <JellyButton size="sm" variant="ghost" disabled={!value.object}
                             onClick={() => set({ filter: [...value.filter, ['', 'lt', '']] })}>+ filter</JellyButton>
            </div>
            <div className="ar-row">
                <select className="ar-input" aria-label="Comparison" value={value.op}
                        onChange={e => set({ op: e.target.value as TriggerCondition['op'] })}>
                    {COMPARISONS.map(c => <option key={c.op} value={c.op}>{c.label}</option>)}
                </select>
                <input className="ar-input" aria-label="Compared with" type="number" value={String(value.value)}
                       onChange={e => set({ value: e.target.value === '' ? '' : Number(e.target.value) })} />
            </div>
            <small>Checked each time the schedule fires, without a model call; when it does not hold, nothing runs.
                The run's input can use <code>{'{{ trigger.condition.value }}'}</code>.</small>
        </div>
    );
};

export default ConditionEditor;
