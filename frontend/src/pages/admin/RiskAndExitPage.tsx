import { parseServerDate } from '@/utils/datetime';
/**
 * pages/admin/RiskAndExitPage — Phase 11 Track 15 risk dashboard.
 *
 * Three sections:
 *   1. Risk indicators — live signal for each programme-level risk
 *      with status pill (ok / warn / breach) and threshold comparison.
 *   2. Exit checklist — programmatic check of the §5 exit criteria.
 *   3. Decision log — append-only history with an "add" form.
 *
 * Polling: every 60s, paused when tab hidden (matches FeatureFlags
 * provider cadence — admin pages don't need real-time refresh).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { kpiService } from '@/services/kpi.service';
import type {
    DecisionRow, ExitChecklistResponse, RiskIndicator,
    RiskIndicatorsResponse, RiskStatus,
} from '@/types/agentKernel';

import './RiskAndExitPage.css';


const POLL_MS = 60_000;


export const RiskAndExitPage: React.FC = () => {
    const [risks, setRisks] = useState<RiskIndicatorsResponse | null>(null);
    const [exit, setExit] = useState<ExitChecklistResponse | null>(null);
    const [decisions, setDecisions] = useState<DecisionRow[]>([]);
    const [loading, setLoading] = useState(true);
    const [since, setSince] = useState<'24h' | '7d' | '30d'>('7d');

    const refresh = useCallback(async () => {
        try {
            const [r, e, d] = await Promise.all([
                kpiService.getRiskIndicators({ since }),
                kpiService.getExitChecklist(),
                kpiService.listDecisions(25),
            ]);
            setRisks(r);
            setExit(e);
            setDecisions(d);
        } catch (err) {
            // eslint-disable-next-line no-console
            console.warn('[RiskAndExit] refresh failed', err);
        } finally {
            setLoading(false);
        }
    }, [since]);

    useEffect(() => {
        void refresh();
        const onVis = () => {
            if (document.visibilityState === 'visible') void refresh();
        };
        document.addEventListener('visibilitychange', onVis);
        const handle = window.setInterval(() => {
            if (document.visibilityState === 'visible') void refresh();
        }, POLL_MS);
        return () => {
            document.removeEventListener('visibilitychange', onVis);
            window.clearInterval(handle);
        };
    }, [refresh]);

    if (loading && !risks) return <p className="rep-page__loading">loading…</p>;

    return (
        <div className="page-container rep-page">
            <header className="page-header">
                <h1>Programme Risk &amp; Exit</h1>
                <p>
                    Live signal for each Phase 11 risk vs. its mitigation
                    threshold, plus the programme exit checklist and the
                    append-only decision log.
                </p>
            </header>

            <div className="rep-page__controls">
                <label>
                    window:
                    <select value={since} onChange={(e) => setSince(e.target.value as any)}>
                        <option value="24h">last 24h</option>
                        <option value="7d">last 7d</option>
                        <option value="30d">last 30d</option>
                    </select>
                </label>
                <button onClick={() => void refresh()}>↻ refresh</button>
                {risks && <OverallBadge status={risks.overall} />}
            </div>

            {risks && (
                <RiskIndicatorsSection
                    risks={risks.indicators}
                    asOf={risks.as_of}
                />
            )}

            {exit && (
                <ExitChecklistSection
                    exit={exit}
                />
            )}

            <DecisionLogSection
                decisions={decisions}
                onAppended={refresh}
            />
        </div>
    );
};


// ---------------------------------------------------------------------------
// Overall rollup badge
// ---------------------------------------------------------------------------


const OverallBadge: React.FC<{ status: RiskStatus }> = ({ status }) => (
    <span className={`rep-page__overall rep-page__overall--${status}`}
          aria-label={`overall programme risk status: ${status}`}>
        {status === 'ok' && '● programme green'}
        {status === 'warn' && '▲ watch'}
        {status === 'breach' && '✖ breach'}
    </span>
);


// ---------------------------------------------------------------------------
// Risk indicators — table + chart
// ---------------------------------------------------------------------------


const RiskIndicatorsSection: React.FC<{
    risks: RiskIndicator[];
    asOf: string;
}> = ({ risks, asOf }) => {
    const sortedRisks = useMemo(() => {
        const rank: Record<RiskStatus, number> = { breach: 0, warn: 1, ok: 2 };
        return [...risks].sort((a, b) => rank[a.status] - rank[b.status]);
    }, [risks]);

    return (
        <section className="rep-page__section" aria-labelledby="risk-heading">
            <h2 id="risk-heading">Risk indicators</h2>
            <p className="rep-page__as-of">as of {fmtTs(asOf)}</p>
            <table className="rep-page__table" role="table">
                <thead>
                    <tr>
                        <th scope="col">ID</th>
                        <th scope="col">Risk</th>
                        <th scope="col" className="rep-page__num">metric</th>
                        <th scope="col" className="rep-page__num">threshold</th>
                        <th scope="col">status</th>
                        <th scope="col">notes</th>
                    </tr>
                </thead>
                <tbody>
                    {sortedRisks.map((r) => (
                        <tr key={r.id} className={`rep-page__row--${r.status}`}>
                            <td className="rep-page__id">{r.id}</td>
                            <td>{r.title}</td>
                            <td className="rep-page__num">{formatMetric(r.metric)}</td>
                            <td className="rep-page__num">{formatMetric(r.threshold)}</td>
                            <td>
                                <span className={`rep-page__pill rep-page__pill--${r.status}`}>
                                    {r.status.toUpperCase()}
                                </span>
                            </td>
                            <td className="rep-page__detail">{r.details}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </section>
    );
};


// ---------------------------------------------------------------------------
// Exit checklist
// ---------------------------------------------------------------------------


const ExitChecklistSection: React.FC<{
    exit: ExitChecklistResponse;
}> = ({ exit }) => (
    <section className="rep-page__section" aria-labelledby="exit-heading">
        <h2 id="exit-heading">
            Programme exit checklist
            <span className="rep-page__exit-count">
                {exit.satisfied} / {exit.total}{' '}
                ({Math.round(exit.percent_complete * 100)}%)
            </span>
        </h2>
        <p className="rep-page__as-of">as of {fmtTs(exit.as_of)}</p>
        <ul className="rep-page__exit-list" role="list">
            {exit.items.map((item) => (
                <li
                    key={item.id}
                    className={`rep-page__exit-item rep-page__exit-item--${item.satisfied ? 'ok' : 'pending'}`}
                >
                    <span className="rep-page__exit-mark" aria-hidden>
                        {item.satisfied ? '✓' : '○'}
                    </span>
                    <span className="rep-page__id">{item.id}</span>
                    <span className="rep-page__exit-title">{item.title}</span>
                    <span className="rep-page__exit-detail">{item.detail}</span>
                </li>
            ))}
        </ul>
    </section>
);


// ---------------------------------------------------------------------------
// Decision log
// ---------------------------------------------------------------------------


const DecisionLogSection: React.FC<{
    decisions: DecisionRow[];
    onAppended: () => Promise<void>;
}> = ({ decisions, onAppended }) => {
    const [open, setOpen] = useState(false);
    const [summary, setSummary] = useState('');
    const [rationale, setRationale] = useState('');
    const [kind, setKind] = useState<DecisionRow['kind']>('decision');
    const [busy, setBusy] = useState(false);

    const append = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!summary.trim()) return;
        setBusy(true);
        try {
            await kpiService.appendDecision({ summary, rationale, kind });
            setSummary(''); setRationale(''); setKind('decision');
            setOpen(false);
            await onAppended();
        } catch (err: any) {
            // eslint-disable-next-line no-alert
            alert(`append failed: ${err?.response?.data?.detail ?? err}`);
        } finally {
            setBusy(false);
        }
    };

    return (
        <section className="rep-page__section" aria-labelledby="decisions-heading">
            <h2 id="decisions-heading">
                Decision log
                <button
                    className="rep-page__add-btn"
                    onClick={() => setOpen((v) => !v)}
                >{open ? '× close' : '+ add'}</button>
            </h2>
            {open && (
                <form className="rep-page__decision-form" onSubmit={append}>
                    <div>
                        <label htmlFor="dl-kind">kind</label>
                        <select id="dl-kind" value={kind}
                                onChange={(e) => setKind(e.target.value)}>
                            <option value="decision">decision</option>
                            <option value="pivot">pivot</option>
                            <option value="defer">defer</option>
                            <option value="accept-risk">accept-risk</option>
                        </select>
                    </div>
                    <div className="rep-page__form-wide">
                        <label htmlFor="dl-summary">summary</label>
                        <input
                            id="dl-summary"
                            value={summary}
                            onChange={(e) => setSummary(e.target.value)}
                            placeholder="e.g. agent_loop.enabled → ON for canary tenants"
                            required
                        />
                    </div>
                    <div className="rep-page__form-wide">
                        <label htmlFor="dl-rationale">rationale (optional)</label>
                        <input
                            id="dl-rationale"
                            value={rationale}
                            onChange={(e) => setRationale(e.target.value)}
                            placeholder="why now / what trade-off"
                        />
                    </div>
                    <button type="submit" disabled={busy}>
                        {busy ? 'appending…' : 'append'}
                    </button>
                </form>
            )}
            {decisions.length === 0 ? (
                <p className="rep-page__empty">no decisions logged yet</p>
            ) : (
                <ol className="rep-page__decisions" role="list">
                    {decisions.map((d, i) => (
                        <li key={`${d.date}-${i}`} className="rep-page__decision">
                            <span className="rep-page__decision-date">{d.date}</span>
                            <span className={`rep-page__decision-kind rep-page__decision-kind--${d.kind}`}>
                                {d.kind}
                            </span>
                            <span className="rep-page__decision-summary">{d.summary}</span>
                            {d.rationale && (
                                <span className="rep-page__decision-rationale">
                                    rationale: {d.rationale}
                                </span>
                            )}
                        </li>
                    ))}
                </ol>
            )}
        </section>
    );
};


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------


function formatMetric(v: number): string {
    if (Number.isInteger(v)) return v.toString();
    // Show three decimals for ratios, otherwise two.
    return v >= 1 ? v.toFixed(2) : v.toFixed(3);
}


function fmtTs(ts: string): string {
    if (!ts) return '—';
    try {
        const d = parseServerDate(ts);
        return d.toLocaleString();
    } catch {
        return ts;
    }
}


export default RiskAndExitPage;
