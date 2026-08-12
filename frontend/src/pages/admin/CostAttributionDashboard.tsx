/**
 * pages/admin/CostAttributionDashboard — Phase 11 Track 8 cost UI.
 *
 * Renders the `usage_logs.attribution` breakdown for the current
 * company over the chosen window. App-admins see a company picker;
 * everyone else is scoped to their own company.
 */
import React, { useEffect, useMemo, useState } from 'react';

import { kpiService } from '@/services/kpi.service';
import type { CostAttributionRow } from '@/types/agentKernel';

import './CostAttributionDashboard.css';

const _DEFAULT_WINDOWS = ['24h', '7d', '30d'];

const _ATTRIBUTION_COLORS: Record<string, string> = {
    planner:          '#5b6fff',
    actor_step:       '#2a8',
    critic_pre:       '#d80',
    critic_post:      '#d33',
    critic_align:     '#d80',
    critic_super:     '#d33',
    reformat_retry:   '#888',
    meta_review:      '#a06fff',
    dreaming:         '#a06fff',
    tool:             '#0aa',
    child_run:        '#5b6fff',
    embedding:        '#888',
    meta_spec_critic: '#a06fff',
    test_driver:      '#d80',
};

export const CostAttributionDashboard: React.FC = () => {
    const [window, setWindow] = useState<string>('7d');
    const [rows, setRows] = useState<CostAttributionRow[]>([]);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        setLoading(true);
        kpiService
            .getCostBreakdown({ since: window })
            .then(setRows)
            .finally(() => setLoading(false));
    }, [window]);

    const total = useMemo(
        () => rows.reduce((s, r) => s + (r.cost_usd ?? 0), 0),
        [rows],
    );

    return (
        <div className="page-container cost-attr-page">
            <header className="page-header">
                <h1>Cost by attribution</h1>
                <p>Where the run cost is going, by Phase 11 attribution tag.</p>
            </header>

            <div className="cost-attr-page__controls">
                {_DEFAULT_WINDOWS.map((w) => (
                    <button
                        key={w}
                        onClick={() => setWindow(w)}
                        className={window === w ? 'active' : ''}
                    >
                        last {w}
                    </button>
                ))}
            </div>

            <div className="cost-attr-page__total">
                Total: <strong>${total.toFixed(4)}</strong>{' '}
                <span className="cost-attr-page__total-charges">
                    ({rows.reduce((s, r) => s + r.charges, 0)} charges)
                </span>
            </div>

            {loading ? (
                <p>loading…</p>
            ) : rows.length === 0 ? (
                <p className="cost-attr-page__empty">No charges in this window.</p>
            ) : (
                <>
                    <ul className="cost-attr-page__bars">
                        {rows.map((r) => {
                            const pct = total > 0 ? (r.cost_usd / total) * 100 : 0;
                            const color = _ATTRIBUTION_COLORS[r.attribution] ?? '#888';
                            return (
                                <li key={r.attribution} className="cost-attr-page__row">
                                    <div className="cost-attr-page__row-label">
                                        <span
                                            className="cost-attr-page__swatch"
                                            style={{ background: color }}
                                        />
                                        {r.attribution}
                                    </div>
                                    <div className="cost-attr-page__row-bar">
                                        <div
                                            style={{
                                                width: `${pct}%`,
                                                background: color,
                                            }}
                                        />
                                    </div>
                                    <div className="cost-attr-page__row-value">
                                        ${r.cost_usd.toFixed(4)} · {pct.toFixed(1)}%
                                        <span className="cost-attr-page__row-charges">
                                            {' '}({r.charges} charges)
                                        </span>
                                    </div>
                                </li>
                            );
                        })}
                    </ul>
                </>
            )}
        </div>
    );
};

export default CostAttributionDashboard;
