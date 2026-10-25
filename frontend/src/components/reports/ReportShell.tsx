/**
 * components/reports/ReportShell — the one frame every report is drawn in (Phase 15 T9-4; 07 §2.6, §7.4).
 *
 * Title, period picker, filters, KPI tiles, a chart, a sortable table with
 * drill-down, export (CSV, XLSX, PDF), the "as of" time and the currency. The
 * money view is the API's: a customer's or partner's report has no cost in it.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Download, RefreshCw } from 'lucide-react';

import { Button, Card, Field, Notice, PageHeader, Tile } from '@/components/ui/brand';
import { ReportData, ReportQuery, reportLibrary } from '@/services/reportLibrary.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDateTime } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

const PERIODS = [
    { value: '', label: 'This month' }, { value: 'last', label: 'Last month' }, { value: '30d', label: 'Last 30 days' },
    { value: '90d', label: 'Last 90 days' }, { value: '12m', label: 'Last 12 months' },
];
const PALETTE = ['#edab48', '#7bb487', '#6fa8dc', '#d4664f', '#b48ead', '#c9a66b', '#88c0d0', '#a3be8c', '#ebcb8b', '#5e81ac'];

function lastMonth(): string {
    const d = new Date();
    d.setDate(1);
    d.setMonth(d.getMonth() - 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export function formatCell(value: any, kind: string, currency: string): string {
    if (value === null || value === undefined || value === '') return '—';
    if (kind === 'money') return formatMoney(value, currency);
    if (kind === 'percent') return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })} %`;
    if (kind === 'number') return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
    if (kind === 'date') return String(value).slice(0, 10);
    if (typeof value === 'boolean') return value ? 'yes' : 'no';
    return String(value);
}

export const ReportShell: React.FC<{ reportId: string; companyId?: string; embedded?: boolean }> = ({ reportId, companyId, embedded }) => {
    const navigate = useNavigate();
    const [query, setQuery] = useState<ReportQuery>({});
    const [data, setData] = useState<ReportData | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(null);

    const effective = useMemo<ReportQuery>(() => ({
        ...query, period: query.period === 'last' ? lastMonth() : query.period, company_id: companyId ?? query.company_id,
    }), [query, companyId]);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            setData(await reportLibrary.run(reportId, effective));
        } catch (err) {
            setError(apiErrorMessage(err, 'The report could not be made'));
        } finally {
            setLoading(false);
        }
    }, [reportId, effective]);

    useEffect(() => { load(); }, [load]);

    const rows = useMemo(() => {
        if (!data || !sort) return data?.rows ?? [];
        const kind = data.columns.find(c => c.key === sort.key)?.kind;
        const numeric = kind === 'money' || kind === 'number' || kind === 'percent';
        return [...data.rows].sort((a, b) => {
            const x = a[sort.key], y = b[sort.key];
            const cmp = numeric ? Number(x ?? 0) - Number(y ?? 0) : String(x ?? '').localeCompare(String(y ?? ''));
            return sort.desc ? -cmp : cmp;
        });
    }, [data, sort]);

    const drill = (row: Record<string, any>, key: string) => {
        const template = data?.drill?.[key];
        if (!template) return;
        navigate(template.replace(/\{(\w+)\}/g, (_, name: string) => encodeURIComponent(String(row[name] ?? ''))));
    };

    const exportAs = (format: 'csv' | 'xlsx' | 'pdf') => reportLibrary.download(reportId, effective, format)
        .catch(err => setError(apiErrorMessage(err, 'The export failed')));

    const chart = data?.chart;
    const tileValue = (t: ReportData['tiles'][number]) => formatCell(t.value, t.kind, data?.currency ?? 'INR');

    return (
        <div className={embedded ? '' : 'b-page'}>
            {!embedded && (
                <PageHeader eyebrow={reportId} title={data?.title ?? 'Report'} subtitle={data?.description}
                            actions={<>
                                <Button size="sm" onClick={() => exportAs('csv')}><Download size={14} /> CSV</Button>
                                <Button size="sm" onClick={() => exportAs('xlsx')}><Download size={14} /> XLSX</Button>
                                <Button size="sm" onClick={() => exportAs('pdf')}><Download size={14} /> PDF</Button>
                            </>} />
            )}
            <div className="b-row" style={{ marginBottom: 16 }}>
                {data?.period !== null && (
                    <Field label="Period">
                        <select value={query.period ?? ''} onChange={e => setQuery({ ...query, period: e.target.value || undefined })}>
                            {PERIODS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
                        </select>
                    </Field>
                )}
                {(data?.filters ?? []).map(f => (
                    <Field key={f.key} label={f.label}>
                        {f.choices.length ? (
                            <select value={query[f.key] ?? ''} onChange={e => setQuery({ ...query, [f.key]: e.target.value || undefined })}>
                                <option value="">All</option>
                                {f.choices.map(c => <option key={c} value={c}>{f.choice_labels?.[c] ?? c}</option>)}
                            </select>
                        ) : (
                            <input type="text" value={query[f.key] ?? ''} onChange={e => setQuery({ ...query, [f.key]: e.target.value || undefined })} />
                        )}
                    </Field>
                ))}
                <Button size="sm" variant="ghost" onClick={load} disabled={loading}><RefreshCw size={14} /> Refresh</Button>
                {data && (
                    <span className="b-muted" style={{ fontSize: 12, marginLeft: 'auto' }}>
                        {data.period ? `${data.period.from} – ${data.period.to} · ` : ''}{data.currency} · as of {formatDateTime(data.as_of)}
                    </span>
                )}
            </div>
            {error && <Notice tone="negative">{error}</Notice>}
            {data && (
                <>
                    {data.tiles.length > 0 && (
                        <div className="b-tiles">
                            {data.tiles.map(t => (
                                <Tile key={t.label} label={t.label} value={tileValue(t)} hint={t.hint ?? undefined}
                                      tone={(t.tone as any) ?? 'neutral'} />
                            ))}
                        </div>
                    )}
                    {chart && chart.data.length > 0 && (
                        <Card>
                            <div style={{ width: '100%', height: 280 }} role="img" aria-label={`${data.title}: chart`}>
                                <ResponsiveContainer>
                                    {chart.type === 'line' ? (
                                        <LineChart data={chart.data}>
                                            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                                            <XAxis dataKey={chart.x} stroke="var(--fg-subtle)" fontSize={11} />
                                            <YAxis stroke="var(--fg-subtle)" fontSize={11} />
                                            <Tooltip contentStyle={{ background: 'var(--surface-2)', border: '1px solid var(--border-strong)' }} />
                                            <Legend />
                                            {chart.series.map((s, i) => <Line key={s.key} type="monotone" dataKey={s.key} name={s.label}
                                                                              stroke={PALETTE[i % PALETTE.length]} dot={false} />)}
                                        </LineChart>
                                    ) : (
                                        <BarChart data={chart.data}>
                                            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                                            <XAxis dataKey={chart.x} stroke="var(--fg-subtle)" fontSize={11} />
                                            <YAxis stroke="var(--fg-subtle)" fontSize={11} />
                                            <Tooltip contentStyle={{ background: 'var(--surface-2)', border: '1px solid var(--border-strong)' }} />
                                            <Legend />
                                            {chart.series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.label}
                                                                             stackId={chart.type === 'stacked' ? 'a' : undefined}
                                                                             fill={PALETTE[i % PALETTE.length]} />)}
                                        </BarChart>
                                    )}
                                </ResponsiveContainer>
                            </div>
                        </Card>
                    )}
                    {data.columns.length > 0 && (
                        <Card>
                            {rows.length === 0 ? <p className="b-muted">Nothing in this period.</p> : (
                                <table className="b-table">
                                    <thead>
                                        <tr>
                                            {data.columns.map(c => (
                                                <th key={c.key} className={['money', 'number', 'percent'].includes(c.kind) ? 'num' : ''}
                                                    onClick={() => setSort(s => ({ key: c.key, desc: s?.key === c.key ? !s.desc : true }))}
                                                    style={{ cursor: 'pointer' }} aria-sort={sort?.key === c.key ? (sort.desc ? 'descending' : 'ascending') : 'none'}>
                                                    {c.label}{c.kind === 'money' ? ` (${data.currency})` : ''}{sort?.key === c.key ? (sort.desc ? ' ↓' : ' ↑') : ''}
                                                </th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {rows.map((row, i) => (
                                            <tr key={i}>
                                                {data.columns.map(c => (
                                                    <td key={c.key} className={['money', 'number', 'percent'].includes(c.kind) ? 'num' : ''}>
                                                        {c.kind === 'link' && data.drill?.[c.key]
                                                            ? <a href="#" onClick={e => { e.preventDefault(); drill(row, c.key); }}>{formatCell(row[c.key], 'text', data.currency)}</a>
                                                            : <span className={c.kind === 'money' && Number(row[c.key]) < 0 ? 'b-neg' : ''}>
                                                                {formatCell(row[c.key], c.kind, data.currency)}
                                                            </span>}
                                                    </td>
                                                ))}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            )}
                        </Card>
                    )}
                    {data.notes.map(n => <p key={n} className="b-muted" style={{ fontSize: 13 }}>{n}</p>)}
                </>
            )}
        </div>
    );
};

export default ReportShell;
