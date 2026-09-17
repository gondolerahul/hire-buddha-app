import React, { useEffect, useState } from 'react';
import { API_BASE_URL } from '@/config/api';
import './MobileAnalyticsPanel.css';

/** Shapes from GET /campaigns/{id}/mobile-analytics (docs/mobile-dialer-app/07-analytics.md). */
interface MobileAnalytics {
    funnel: {
        leads: number | null;
        attempted: number;
        attempts: number;
        ai_ready: number;
        lead_dialed: number;
        lead_answered: number;
        merged: number;
        conversation: number;
        interested: number;
    };
    rates: {
        answer: number | null;
        merge_success: number | null;
        identification: number | null;
        dtmf_confirmation: number | null;
        identification_conflict: number | null;
        conversion: number | null;
    };
    timing: {
        ai_ready_p50_s: number | null;
        ai_ready_p95_s: number | null;
        avg_conversation_s: number;
        talk_minutes: number;
        idle_ai_minutes: number;
    };
    outcomes: Record<string, number>;
    by_rep: {
        user_id: string;
        name: string;
        attempts: number;
        answer_rate: number | null;
        merge_success: number | null;
        interested: number;
        talk_minutes: number;
    }[];
}

const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);
const humanize = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase());

interface Props {
    campaignId: string;
    token: string | null;
    /** Poll while a rep is running the campaign. */
    live: boolean;
}

export const MobileAnalyticsPanel: React.FC<Props> = ({ campaignId, token, live }) => {
    const [data, setData] = useState<MobileAnalytics | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        const load = async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/campaigns/${campaignId}/mobile-analytics`, {
                    headers: { Authorization: `Bearer ${token}` },
                });
                if (!response.ok) throw new Error(`Analytics unavailable (${response.status})`);
                const json = await response.json();
                if (!cancelled) {
                    setData(json);
                    setError(null);
                }
            } catch (err: any) {
                if (!cancelled) setError(err.message);
            }
        };
        load();
        const interval = live ? setInterval(load, 5000) : undefined;
        return () => {
            cancelled = true;
            if (interval) clearInterval(interval);
        };
    }, [campaignId, token, live]);

    if (error && !data) return <div className="mobile-analytics-error">{error}</div>;
    if (!data) return <div className="mobile-analytics-loading">Loading mobile analytics…</div>;

    const f = data.funnel;
    const stages: [string, number][] = [
        ...(f.leads !== null ? [['Leads', f.leads] as [string, number]] : []),
        ['Attempted', f.attempted],
        ['Lead answered', f.lead_answered],
        ['Merged with AI', f.merged],
        ['Conversation ≥30s', f.conversation],
        ['Interested', f.interested],
    ];
    const max = Math.max(1, ...stages.map(s => s[1]));
    const conflictRate = data.rates.identification_conflict ?? 0;

    return (
        <div className="mobile-analytics">
            <div className="mobile-tiles">
                <Tile label="Answer rate" value={pct(data.rates.answer)} />
                <Tile label="Merge success" value={pct(data.rates.merge_success)} />
                <Tile label="Lead identified" value={pct(data.rates.identification)}
                    caption={`DTMF confirmed ${pct(data.rates.dtmf_confirmation)}`} />
                <Tile label="Conversion" value={pct(data.rates.conversion)} caption={`${f.interested} interested`} />
                <Tile label="Talk time" value={`${data.timing.talk_minutes} min`}
                    caption={`avg ${Math.round(data.timing.avg_conversation_s)}s per conversation`} />
                <Tile label="AI ready (p50)" value={data.timing.ai_ready_p50_s !== null ? `${data.timing.ai_ready_p50_s}s` : '—'}
                    caption={`idle AI ${data.timing.idle_ai_minutes} min`} />
            </div>

            {conflictRate > 0.005 && (
                <div className="mobile-analytics-alert">
                    Identification conflicts on {pct(conflictRate)} of calls — check reps' SIM caller ID and DTMF delivery.
                </div>
            )}

            <div className="mobile-section">
                <h4>Funnel</h4>
                {stages.map(([label, value], i) => (
                    <div className="funnel-row" key={label}>
                        <span className="funnel-label">{label}</span>
                        <div className="funnel-track">
                            <div className="funnel-bar" style={{ width: `${(value / max) * 100}%`, opacity: 1 - i * 0.12 }} />
                        </div>
                        <span className="funnel-value">{value}</span>
                    </div>
                ))}
            </div>

            {Object.keys(data.outcomes).length > 0 && (
                <div className="mobile-section">
                    <h4>Outcomes</h4>
                    <div className="outcome-chips">
                        {Object.entries(data.outcomes).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                            <span className="outcome-chip" key={k}>{humanize(k)} <strong>{v}</strong></span>
                        ))}
                    </div>
                </div>
            )}

            {data.by_rep.length > 0 && (
                <div className="mobile-section">
                    <h4>Reps</h4>
                    <table className="data-table compact">
                        <thead>
                            <tr>
                                <th>Rep</th>
                                <th>Calls</th>
                                <th>Answer rate</th>
                                <th>Merge success</th>
                                <th>Interested</th>
                                <th>Talk min</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.by_rep.map(r => (
                                <tr key={r.user_id}>
                                    <td>{r.name}</td>
                                    <td>{r.attempts}</td>
                                    <td>{pct(r.answer_rate)}</td>
                                    <td>{pct(r.merge_success)}</td>
                                    <td>{r.interested}</td>
                                    <td>{r.talk_minutes}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

const Tile: React.FC<{ label: string; value: string; caption?: string }> = ({ label, value, caption }) => (
    <div className="mobile-tile">
        <span className="tile-label">{label}</span>
        <strong className="tile-value">{value}</strong>
        {caption && <span className="tile-caption">{caption}</span>}
    </div>
);
