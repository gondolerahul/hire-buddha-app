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

interface UseAgentEventsOptions {
    url: string | null;
    onEvent: AgentEventListener;
    onUnknown?: (raw: unknown) => void;
    onError?: (err: Event) => void;
}

/**
 * Low-level hook: opens a single EventSource, parses every message
 * into `AgentEvent | null`, and routes to the callback.
 *
 * Auth: an EventSource cannot send headers, so a URL token for
 * `/api/v1/ai/executions/` goes in `?token=` — never the login token, which
 * the API refuses there (FE-28). If the stream is closed for good (an expired
 * or refused token), it is reopened with a fresh token, up to three times.
 */
export function useAgentEvents({
    url,
    onEvent,
    onUnknown,
    onError,
}: UseAgentEventsOptions): void {
    const eventRef = useRef<AgentEventListener>(onEvent);
    eventRef.current = onEvent;

    useEffect(() => {
        if (!url) return;
        let source: EventSource | null = null;
        let closed = false;
        let reopened = 0;
        let timer: ReturnType<typeof setTimeout> | undefined;

        const open = async (fresh: boolean) => {
            let token: string;
            try {
                token = await getUrlToken('/api/v1/ai/executions/', fresh);
            } catch {
                if (!closed) timer = setTimeout(() => void open(true), 5_000);
                return;
            }
            if (closed) return;
            const current = new EventSource(withUrlToken(url, token));
            source = current;

            current.onopen = () => {
                reopened = 0;
            };
            current.onmessage = (msg) => {
                try {
                    const raw = JSON.parse(msg.data);
                    // An iteration's frames arrive as one message (AK-I9).
                    const items: unknown[] = raw && raw.type === 'batch' && Array.isArray(raw.events) ? raw.events : [raw];
                    for (const item of items) {
                        const parsed = parseAgentEvent(item);
                        if (parsed) eventRef.current(parsed);
                        else if (onUnknown) onUnknown(item);
                    }
                } catch {
                    // Non-JSON payload — ignore.
                }
            };
            current.onerror = (e) => {
                onError?.(e);
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
