/**
 * components/agent/IterationCard — One row per iteration on the
 * AgentLoop timeline.
 *
 * Shows the executor, decision, the four critic verdicts (Track 3),
 * any retry the Strategist queued (Track 3), and a resume marker
 * when the worker picked up from a snapshot (Track 2).
 */
import React from 'react';

import type {
    IterationSlice,
} from '@/hooks/useExecutionEvents';
import type { SpanNode } from '@/types/agentKernel';

import {
    CriticVerdictChip,
    ExecutorBadge,
    FailureTagChip,
    ResumeIndicator,
    RetryStrategyBadge,
} from './AgentKernel';
import { SpanTree } from './SpanTree';

import './IterationCard.css';

interface Props {
    slice: IterationSlice;
    /** Resolved span-tree roots for this iteration (steps/tools/LLM calls). */
    spans?: SpanNode[];
}

export const IterationCard: React.FC<Props> = ({ slice, spans }) => {
    const cost = Number(slice.cost_iter_usd ?? 0);
    return (
        <div className={`agentk-iter-card agentk-iter-card--${slice.outcome ?? 'pending'}`}>
            <div className="agentk-iter-card__header">
                <span className="agentk-iter-card__num">iter #{slice.iteration}</span>
                <ExecutorBadge executor={slice.executor as never} />
                {typeof slice.resumed_from === 'number' && (
                    <ResumeIndicator fromIteration={slice.resumed_from} />
                )}
                <span className="agentk-iter-card__decision">
                    {slice.decision ?? (slice.outcome ? slice.outcome : 'running…')}
                </span>
                {cost > 0 && (
                    <span className="agentk-iter-card__cost" title="iteration cost">
                        ${cost.toFixed(4)}
                    </span>
                )}
            </div>

            <div className="agentk-iter-card__verdicts">
                {slice.pre_critic && (
                    <CriticVerdictChip
                        label="pre"
                        verdict={slice.pre_critic.verdict}
                        title={
                            slice.pre_critic.concerns_count
                                ? `${slice.pre_critic.concerns_count} concerns`
                                : undefined
                        }
                    />
                )}
                {slice.post_critic && (
                    <CriticVerdictChip
                        label="post"
                        verdict={slice.post_critic.verdict}
                    />
                )}
                {slice.alignment && (
                    <CriticVerdictChip
                        label="align"
                        verdict={slice.alignment.aligned ? 'PASS' : 'REVISE'}
                        title={`drift ${(slice.alignment.drift * 100).toFixed(0)}%`}
                    />
                )}
                {slice.supervisor && (
                    <CriticVerdictChip
                        label="super"
                        verdict={slice.supervisor.recommendation}
                        title={`conf ${(slice.supervisor.confidence * 100).toFixed(0)}%`}
                    />
                )}
                {slice.retry && (
                    <RetryStrategyBadge strategy={slice.retry.strategy} />
                )}
            </div>

            {slice.post_critic?.tags?.length ? (
                <div className="agentk-iter-card__tags">
                    {slice.post_critic.tags.map((t) => (
                        <FailureTagChip key={t} tag={t} />
                    ))}
                </div>
            ) : null}

            {spans && spans.length > 0 && <SpanTree roots={spans} />}
        </div>
    );
};
