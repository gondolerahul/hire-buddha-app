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
 * Auth: tokens are injected via the `?token=` query param matching the
 * existing `useSSE` convention; the backend's SSE auth middleware
 * accepts both `Authorization` headers and query tokens.
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
        const token = localStorage.getItem('access_token');
        const sep = url.includes('?') ? '&' : '?';
        const source = new EventSource(`${url}${sep}token=${token ?? ''}`);

        source.onmessage = (msg) => {
            try {
                const raw = JSON.parse(msg.data);
                const parsed = parseAgentEvent(raw);
                if (parsed) eventRef.current(parsed);
                else if (onUnknown) onUnknown(raw);
            } catch {
                // Non-JSON payload — ignore; the legacy useSSE handler
                // already deals with these.
            }
        };
        source.onerror = (e) => onError?.(e);

        return () => {
            source.close();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [url]);
}
