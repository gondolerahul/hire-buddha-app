/**
 * services/events.ts — Typed SSE event surface for Phase 11.
 *
 * The backend emits agent.* events through the existing
 * /api/v1/ai/executions/{id}/stream channel (and the rest of the
 * SSE channels we already use). This module gives them a TypeScript
 * shape (`AgentEvent` discriminated union) and a low-level hook that
 * funnels every parsed payload into a typed callback.
 *
 * Higher-level consumers should use `hooks/useExecutionEvents.ts`
 * rather than this module directly.
 */
import { useEffect, useRef } from 'react';
import { getUrlToken, withUrlToken } from '@/services/urlToken';

import type { AgentEvent } from '@/types/agentKernel';

export type AgentEventListener = (event: AgentEvent) => void;

/**
 * Where a run's stream is: opening, delivering, down (the page should poll),
 * or ended by the run's last frame.
 */
export type StreamConnection = 'connecting' | 'open' | 'error' | 'done';

/**
 * Best-effort parser. Returns the event when the payload matches
 * something we model in `AgentEvent`; returns `null` for unknowns
 * (caller can fall through to legacy handling).
 */
export function parseAgentEvent(raw: unknown): AgentEvent | null {
    if (!raw || typeof raw !== 'object') return null;
    const obj = raw as Record<string, unknown>;
    if (typeof obj.type !== 'string') return null;
    return obj as unknown as AgentEvent;
}

/** The run's last frame says so with `terminal: true` (GW-19). */
export function isTerminalFrame(raw: unknown): boolean {
    return !!raw && typeof raw === 'object' && (raw as Record<string, unknown>).terminal === true;
}

/** The stream URL, resuming after `lastEventId` when there is one (GW-18). */
export function resumeUrl(url: string, lastEventId: string | null): string {
    if (!lastEventId) return url;
    return `${url}${url.includes('?') ? '&' : '?'}last_event_id=${encodeURIComponent(lastEventId)}`;
}

interface UseAgentEventsOptions {
    url: string | null;
    onEvent: AgentEventListener;
    onUnknown?: (raw: unknown) => void;
    onError?: (err: Event) => void;
    onConnection?: (state: StreamConnection) => void;
}

/**
 * Low-level hook: opens a single EventSource, parses every message
 * into `AgentEvent | null`, and routes to the callback.
 *
 * Auth: an EventSource cannot send headers, so a URL token for
 * `/api/v1/ai/executions/` goes in `?token=` — never the login token, which
 * the API refuses there (FE-28). If the stream is closed for good (an expired
 * or refused token), it is reopened with a fresh token, up to three times.
 *
 * Replay (GW-18): every frame carries an `id:`. The browser's own reconnect
 * sends it back as `Last-Event-ID`; a reopened stream asks for what came after
 * it with `?last_event_id=`, so nothing published while it was down is lost.
 * The run's last frame (`terminal: true`) closes the stream for good.
 */
export function useAgentEvents({
    url,
    onEvent,
    onUnknown,
    onError,
    onConnection,
}: UseAgentEventsOptions): void {
    const eventRef = useRef<AgentEventListener>(onEvent);
    eventRef.current = onEvent;
    const connectionRef = useRef(onConnection);
    connectionRef.current = onConnection;

    useEffect(() => {
        if (!url) return;
        let source: EventSource | null = null;
        let closed = false;
        let finished = false;
        let reopened = 0;
        let lastEventId: string | null = null;
        let timer: ReturnType<typeof setTimeout> | undefined;
        connectionRef.current?.('connecting');

        const open = async (fresh: boolean) => {
            let token: string;
            try {
                token = await getUrlToken('/api/v1/ai/executions/', fresh);
            } catch {
                connectionRef.current?.('error');
                if (!closed) timer = setTimeout(() => void open(true), 5_000);
                return;
            }
            if (closed) return;
            const current = new EventSource(withUrlToken(resumeUrl(url, lastEventId), token));
            source = current;

            current.onopen = () => {
                reopened = 0;
                connectionRef.current?.('open');
            };
            current.onmessage = (msg) => {
                if (msg.lastEventId) lastEventId = msg.lastEventId;
                let raw: unknown;
                try {
                    raw = JSON.parse(msg.data);
                } catch {
                    return; // Non-JSON payload — ignore.
                }
                // An iteration's frames arrive as one message (AK-I9).
                const batch = raw as { type?: unknown; events?: unknown };
                const items: unknown[] = batch && batch.type === 'batch' && Array.isArray(batch.events) ? batch.events : [raw];
                for (const item of items) {
                    const parsed = parseAgentEvent(item);
                    if (parsed) eventRef.current(parsed);
                    else if (onUnknown) onUnknown(item);
                }
                if (isTerminalFrame(raw)) {
                    finished = true;
                    current.close();
                    connectionRef.current?.('done');
                }
            };
            current.onerror = (e) => {
                if (finished) return;
                onError?.(e);
                connectionRef.current?.('error');
                if (current.readyState === EventSource.CLOSED && !closed && reopened < 3) {
                    reopened += 1;
                    current.close();
                    timer = setTimeout(() => void open(true), 1_000 * reopened);
                }
            };
        };

        void open(false);
        return () => {
            closed = true;
            if (timer) clearTimeout(timer);
            source?.close();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [url]);
}
