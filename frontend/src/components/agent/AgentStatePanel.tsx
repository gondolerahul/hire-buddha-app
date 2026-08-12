/**
 * components/agent/AgentStatePanel — Sticky right-rail of
 * ExecutionDetail. Renders live AgentState: budget, subgoals,
 * blockers, last action / observation, recent reflections.
 */
import React from 'react';

import type { AgentStateSnapshot } from '@/types/agentKernel';

import { BudgetBar, ExecutorBadge } from './AgentKernel';

import './AgentStatePanel.css';

interface Props {
    state: AgentStateSnapshot | null;
    loading?: boolean;
}

export const AgentStatePanel: React.FC<Props> = ({ state, loading }) => {
    if (loading && !state) {
        return (
            <aside className="agentk-state-panel">
                <h3>Agent State</h3>
                <p className="agentk-state-panel__loading">loading…</p>
            </aside>
        );
    }
    if (!state) {
        return (
            <aside className="agentk-state-panel">
                <h3>Agent State</h3>
                <p className="agentk-state-panel__empty">No snapshot yet.</p>
            </aside>
        );
    }
    // Defensive: a snapshot may be partial (older runs / mid-write); never
    // crash on a missing array field.
    const openSubgoals = state.open_subgoals ?? [];
    const achieved = state.achieved ?? [];
    const blockers = state.blockers ?? [];

    return (
        <aside className="agentk-state-panel">
            <h3>Agent State</h3>

            <section className="agentk-state-panel__section">
                <h4>Budget · iter #{state.iteration}</h4>
                <BudgetBar budget={state.budget} />
                {state.task_class && (
                    <div className="agentk-state-panel__taskclass">
                        task class: <code>{state.task_class}</code>
                    </div>
                )}
            </section>

            <section className="agentk-state-panel__section">
                <h4>Open subgoals ({openSubgoals.length})</h4>
                {openSubgoals.length === 0 ? (
                    <p className="agentk-state-panel__empty">none</p>
                ) : (
                    <ul className="agentk-state-panel__list">
                        {openSubgoals.map((sg) => (
                            <li key={sg.id}>
                                <strong>{sg.description}</strong>
                                {sg.blocked_on ? (
                                    <span className="agentk-state-panel__blocked">
                                        blocked: {sg.blocked_on}
                                    </span>
                                ) : null}
                            </li>
                        ))}
                    </ul>
                )}
            </section>

            {achieved.length > 0 && (
                <section className="agentk-state-panel__section">
                    <h4>Achieved ({achieved.length})</h4>
                    <ul className="agentk-state-panel__list agentk-state-panel__list--muted">
                        {achieved.map((sg) => (
                            <li key={sg.id}>✓ {sg.description}</li>
                        ))}
                    </ul>
                </section>
            )}

            {blockers.length > 0 && (
                <section className="agentk-state-panel__section">
                    <h4>Blockers</h4>
                    <ul className="agentk-state-panel__list">
                        {blockers.map((b, i) => (
                            <li key={i} className="agentk-state-panel__blocker">
                                <span className="agentk-state-panel__blocker-kind">{b.kind}</span>{' '}
                                {b.detail}
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            {(state.last_action || state.last_observation) && (
                <section className="agentk-state-panel__section">
                    <h4>Last activity</h4>
                    {state.last_action && (
                        <div>
                            <ExecutorBadge executor={state.last_action.executor} />{' '}
                            <span className="agentk-state-panel__muted">
                                iter {state.last_action.iteration}
                            </span>
                        </div>
                    )}
                    {state.last_observation && (
                        <p className="agentk-state-panel__obs">
                            <span className={`agentk-state-panel__outcome agentk-state-panel__outcome--${state.last_observation.outcome}`}>
                                {state.last_observation.outcome}
                            </span>{' '}
                            {state.last_observation.summary?.slice(0, 200) || ''}
                        </p>
                    )}
                </section>
            )}

            <ReflectionsList state={state} />
        </aside>
    );
};

const ReflectionsList: React.FC<{ state: AgentStateSnapshot }> = ({ state }) => {
    const recent = (state.reflections ?? []).slice(-5).reverse();
    if (!recent.length) return null;
    return (
        <section className="agentk-state-panel__section">
            <h4>Reflections (last {recent.length})</h4>
            <ul className="agentk-state-panel__list">
                {recent.map((r, i) => (
                    <li key={i} className="agentk-state-panel__refl">
                        <span className={`agentk-state-panel__refl-scope agentk-state-panel__refl-scope--${r.scope}`}>
                            {r.scope}
                        </span>
                        {r.proposed_change ? (
                            <strong>{r.proposed_change}</strong>
                        ) : (
                            <em>{r.what_worked || r.what_didnt || '—'}</em>
                        )}
                    </li>
                ))}
            </ul>
        </section>
    );
};
