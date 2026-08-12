/**
 * components/agent/SupervisorAndBandit — Track 4 widgets.
 *
 *   - SupervisorVerdictCard — recommendation + confidence + reasoning
 *                                 + proposed subgoals (REPLAN only).
 *   - BanditArmsPanel       — per-(entity, task_class) arm table.
 *   - CriticCostShareGauge  — small ring showing critic-cost share.
 */
import React, { useEffect, useState } from 'react';

import { agentService } from '@/services/agent.service';
import type {
    BanditArmState,
    BanditTable,
    Subgoal,
    SupervisorRecommendation,
} from '@/types/agentKernel';

import './SupervisorAndBandit.css';

// ---------------------------------------------------------------------------
// Supervisor verdict card
// ---------------------------------------------------------------------------

const _REC_COLORS: Record<SupervisorRecommendation, string> = {
    CONTINUE: '#2a8',
    REPLAN:   '#d80',
    ABORT:    '#d33',
    PAUSE:    '#888',
};

interface SupervisorCardProps {
    recommendation: SupervisorRecommendation;
    confidence: number;
    reasoning?: string;
    proposedSubgoals?: Subgoal[];
}

export const SupervisorVerdictCard: React.FC<SupervisorCardProps> = ({
    recommendation,
    confidence,
    reasoning,
    proposedSubgoals,
}) => {
    const color = _REC_COLORS[recommendation] ?? '#888';
    return (
        <div className="agentk-super-card" style={{ borderLeftColor: color }}>
            <div className="agentk-super-card__header">
                <span className="agentk-super-card__rec" style={{ color }}>
                    Supervisor: <strong>{recommendation}</strong>
                </span>
                <span className="agentk-super-card__conf">
                    confidence {(confidence * 100).toFixed(0)}%
                </span>
            </div>
            {reasoning && <p className="agentk-super-card__reasoning">{reasoning}</p>}
            {recommendation === 'REPLAN' && proposedSubgoals && proposedSubgoals.length > 0 && (
                <div className="agentk-super-card__subgoals">
                    <h5>Proposed subgoals</h5>
                    <ul>
                        {proposedSubgoals.map((sg) => (
                            <li key={sg.id}>
                                {sg.description}
                                {typeof sg.priority === 'number' && (
                                    <span className="agentk-super-card__priority">
                                        priority {sg.priority}
                                    </span>
                                )}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
};

// ---------------------------------------------------------------------------
// Critic cost share gauge
// ---------------------------------------------------------------------------

export const CriticCostShareGauge: React.FC<{ share: number; cap?: number }> = ({
    share,
    cap = 0.25,
}) => {
    const pct = Math.max(0, Math.min(1, share));
    const over = pct > cap;
    const color = over ? '#d33' : pct > cap * 0.8 ? '#d80' : '#2a8';
    return (
        <div className="agentk-critic-gauge" title={`Critic cost share ${(pct * 100).toFixed(1)}% (cap ${(cap * 100).toFixed(0)}%)`}>
            <svg viewBox="0 0 36 36" className="agentk-critic-gauge__ring">
                <path
                    className="agentk-critic-gauge__bg"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
                <path
                    className="agentk-critic-gauge__fill"
                    strokeDasharray={`${pct * 100}, 100`}
                    style={{ stroke: color }}
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
                <text x="18" y="20.35" className="agentk-critic-gauge__text">
                    {(pct * 100).toFixed(0)}%
                </text>
            </svg>
            <div className="agentk-critic-gauge__label">critic cost share</div>
        </div>
    );
};

// ---------------------------------------------------------------------------
// Bandit arm table
// ---------------------------------------------------------------------------

interface BanditPanelProps {
    entityId: string;
    taskClass?: string;
}

export const BanditArmsPanel: React.FC<BanditPanelProps> = ({
    entityId,
    taskClass = 'general',
}) => {
    const [table, setTable] = useState<BanditTable | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        agentService
            .getBanditState(entityId, taskClass)
            .then((data) => {
                if (!cancelled) setTable(data);
            })
            .catch((err) => {
                if (!cancelled) setError(String(err));
            });
        return () => {
            cancelled = true;
        };
    }, [entityId, taskClass]);

    if (error) {
        return (
            <div className="agentk-bandit-panel agentk-bandit-panel--error">
                bandit unavailable: {error}
            </div>
        );
    }
    if (!table) return <div className="agentk-bandit-panel">loading bandit…</div>;
    const armEntries = Object.entries(table.arms);

    return (
        <div className="agentk-bandit-panel">
            <h4>Plan-style bandit · {table.task_class}</h4>
            {armEntries.length === 0 ? (
                <p className="agentk-bandit-panel__empty">no pulls yet</p>
            ) : (
                <table>
                    <thead>
                        <tr>
                            <th>arm</th>
                            <th>pulls</th>
                            <th>wins</th>
                            <th>win rate</th>
                            <th>avg cost</th>
                            <th>last pull</th>
                        </tr>
                    </thead>
                    <tbody>
                        {armEntries
                            .sort(_byWinRate)
                            .map(([arm, st]) => {
                                const wr = st.pulls ? st.successes / st.pulls : 0;
                                return (
                                    <tr key={arm}>
                                        <td className="agentk-bandit-panel__arm">{arm}</td>
                                        <td>{st.pulls}</td>
                                        <td>{st.successes}</td>
                                        <td>{(wr * 100).toFixed(0)}%</td>
                                        <td>${st.avg_cost_usd.toFixed(4)}</td>
                                        <td className="agentk-bandit-panel__ts">
                                            {st.last_pull_at?.slice(0, 16) ?? '—'}
                                        </td>
                                    </tr>
                                );
                            })}
                    </tbody>
                </table>
            )}
        </div>
    );
};

function _byWinRate(
    a: [string, BanditArmState],
    b: [string, BanditArmState],
): number {
    const aWr = a[1].pulls ? a[1].successes / a[1].pulls : 0;
    const bWr = b[1].pulls ? b[1].successes / b[1].pulls : 0;
    return bWr - aWr;
}
