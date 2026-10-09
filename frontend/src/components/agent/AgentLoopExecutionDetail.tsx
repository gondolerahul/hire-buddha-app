/**
 * components/agent/AgentLoopExecutionDetail — Phase 11 ExecutionDetail layout.
 *
 * Composes the typed AgentState (via REST one-shot) + the live SSE event
 * stream (via `useExecutionEvents`) + the per-iteration timeline cards.
 *
 * Mounted by `pages/ai/ExecutionDetail.tsx` when `agent_loop.enabled`
 * is on for the run; otherwise the legacy ExecutionDetail body renders
 * as before.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { agentService } from '@/services/agent.service';
import type { ExecutionEventState } from '@/hooks/useExecutionEvents';
import type { StreamConnection } from '@/services/events';
import type {
    AgentStateSnapshot,
    HealthRecordRow,
    SpanNode,
    TraceSpan,
} from '@/types/agentKernel';

import { AgentStatePanel } from './AgentStatePanel';
import { IterationCard } from './IterationCard';

import './AgentLoopExecutionDetail.css';

interface Props {
    runId: string;
    /** The run's live stream, read once by the page (`useExecutionEvents`). */
    events: ExecutionEventState;
    connection: StreamConnection;
    milestones: number;
    /** The run has reached a terminal status. */
    finished: boolean;
    headerBlock?: React.ReactNode;
}

/** Fallback polls before giving up (~5 min at 3 s). */
const MAX_FALLBACK_POLLS = 100;

export const AgentLoopExecutionDetail: React.FC<Props> = ({
    runId,
    events,
    connection,
    milestones,
    finished,
    headerBlock,
}) => {
    const [snapshot, setSnapshot] = useState<AgentStateSnapshot | null>(null);
    const [loading, setLoading] = useState(true);
    const [healthRecords, setHealthRecords] = useState<HealthRecordRow[]>([]);
    const [traceSpans, setTraceSpans] = useState<TraceSpan[]>([]);

    // The agent-state snapshot, health records and trace over REST drive the
    // AgentState rail and backfill the iteration timeline.
    const currentRun = useRef(runId);
    currentRun.current = runId;
    const load = useCallback(async () => {
        const [state, hrs, trace] = await Promise.all([
            agentService.getAgentState(runId).catch(() => null),
            agentService.getHealthRecords(runId).catch(() => []),
            agentService.getTrace(runId).catch(() => []),
        ]);
        if (currentRun.current !== runId) return; // another run's page by now
        setSnapshot(state);
        setHealthRecords(hrs);
        setTraceSpans(trace);
        setLoading(false);
    }, [runId]);

    // Read once, again when the run finishes, and again shortly after each
    // frame that changes what is stored (GW-18) — no poll while the stream works.
    useEffect(() => {
        setLoading(true);
        void load();
    }, [load]);
    useEffect(() => {
        if (finished) void load();
    }, [finished, load]);
    useEffect(() => {
        if (!milestones) return;
        const timer = window.setTimeout(() => void load(), 500);
        return () => window.clearTimeout(timer);
    }, [milestones, load]);

    // Poll every 3 s only while the stream is not delivering (a buffering
    // proxy, a dropped connection) and the run is still going.
    const snapshotDone = !!(snapshot && (snapshot as { done?: boolean }).done);
    useEffect(() => {
        if (finished || snapshotDone || connection === 'open') return;
        let polls = 0;
        const timer = window.setInterval(() => {
            polls += 1;
            if (polls > MAX_FALLBACK_POLLS) window.clearInterval(timer);
            else void load();
        }, 3000);
        return () => window.clearInterval(timer);
    }, [finished, snapshotDone, connection, load]);

    // Merge persisted health records into the per-iteration slices the
    // SSE reducer maintains, so the page shows accurate verdicts even
    // for iterations that finished before the page subscribed.
    const mergedIterations = useMemo(() => {
        const out = { ...events.iterations };
        for (const row of healthRecords) {
            const iter = row.record.iteration;
            const prev = out[iter] ?? { iteration: iter };
            out[iter] = {
                ...prev,
                pre_critic: row.record.pre_critic_verdict
                    ? {
                          verdict: row.record.pre_critic_verdict,
                          concerns_count: (row.record.pre_critic_concerns ?? []).length,
                          cost_usd: Number(row.record.pre_critic_cost_usd ?? 0),
                      }
                    : prev.pre_critic,
                post_critic: row.record.post_critic_verdict
                    ? {
                          verdict: row.record.post_critic_verdict,
                          tags: row.record.post_critic_tags ?? [],
                          cost_usd: Number(row.record.post_critic_cost_usd ?? 0),
                      }
                    : prev.post_critic,
                alignment:
                    typeof row.record.alignment_aligned === 'boolean'
                        ? {
                              aligned: row.record.alignment_aligned,
                              drift: Number(row.record.alignment_drift ?? 0),
                          }
                        : prev.alignment,
                supervisor: row.record.supervisor_recommendation
                    ? {
                              recommendation: row.record.supervisor_recommendation,
                              confidence: Number(row.record.supervisor_confidence ?? 0),
                          }
                    : prev.supervisor,
            };
        }
        return out;
    }, [events.iterations, healthRecords]);

    // Merge REST-backfilled spans with the live SSE span map (live wins on
    // span_id collision), then assemble a parent→children forest grouped by
    // iteration. Mirrors the health-record merge above.
    const spansByIteration = useMemo(() => {
        const merged = new Map<string, TraceSpan>();
        for (const s of traceSpans) merged.set(s.span_id, s);
        for (const s of Object.values(events.spans)) merged.set(s.span_id, s);

        const nodes = new Map<string, SpanNode>();
        for (const s of merged.values()) nodes.set(s.span_id, { ...s, children: [] });

        const byIter: Record<number, SpanNode[]> = {};
        // Stable order by seq so roots and siblings render in execution order.
        const ordered = [...nodes.values()].sort((a, b) => a.seq - b.seq);
        for (const node of ordered) {
            const parent = node.parent_span_id
                ? nodes.get(node.parent_span_id)
                : undefined;
            if (parent) {
                parent.children.push(node);
            } else {
                const iter = node.iteration ?? 0;
                (byIter[iter] ??= []).push(node);
            }
        }
        return byIter;
    }, [traceSpans, events.spans]);

    const orderedIters = useMemo(() => {
        const set = new Set<number>([
            ...events.iterationOrder,
            ...Object.keys(mergedIterations).map((n) => Number(n)),
            ...Object.keys(spansByIteration).map((n) => Number(n)),
        ]);
        return [...set].sort((a, b) => a - b);
    }, [events.iterationOrder, mergedIterations, spansByIteration]);

    return (
        <div className="agentk-agentloop-detail">
            <div className="agentk-agentloop-detail__main">
                {headerBlock}

                <h2 className="agentk-agentloop-detail__title">
                    Iteration timeline
                </h2>

                {events.replans.length > 0 && (
                    <div className="agentk-agentloop-detail__replan-banner">
                        <strong>{events.replans.length}</strong> replan
                        {events.replans.length > 1 ? 's' : ''} triggered during this
                        run.
                    </div>
                )}

                {Object.entries(events.liveText).map(([step, text]) => (
                    <div key={step} className="agentk-agentloop-detail__live" aria-live="polite">
                        <strong>Live output — {step}</strong>
                        <pre>{text || '…'}</pre>
                    </div>
                ))}

                {orderedIters.length === 0 ? (
                    <p className="agentk-agentloop-detail__empty">
                        No iterations yet. Waiting for the worker…
                    </p>
                ) : (
                    <div className="agentk-agentloop-detail__timeline">
                        {orderedIters.map((iter) => (
                            <IterationCard
                                key={iter}
                                slice={
                                    mergedIterations[iter] ?? { iteration: iter }
                                }
                                spans={spansByIteration[iter]}
                            />
                        ))}
                    </div>
                )}
            </div>

            <div className="agentk-agentloop-detail__rail">
                <AgentStatePanel state={snapshot} loading={loading} />
            </div>
        </div>
    );
};
