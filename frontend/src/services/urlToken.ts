/**
 * URL tokens (FE-28): what goes in `?token=` for a URL the browser loads by
 * itself — an `<img>`/`<audio>`/`<video>` source, a download link, an
 * EventSource — none of which can send an Authorization header.
 *
 * A URL token lives ten minutes and is good only under one path prefix; the
 * API refuses the login token in a URL, where it would sit in logs, the
 * history and Referer headers for as long as it lives. Tokens are cached per
 * scope and per login (a new sign-in or a refreshed login token mints afresh)
 * and renewed a minute before they expire.
 */
import { useEffect, useState } from 'react';
import { API_ORIGIN } from '@/config/api';
import { apiClient } from './api.client';

/** The prefixes the API mints URL tokens for — the routes that read `?token=`. */
export type UrlTokenScope = '/api/v1/artifacts/' | '/api/v1/ai/executions/';

const RENEW_BEFORE_MS = 60_000;

interface CachedToken {
    token: string;
    expiresAt: number;
}

const cache = new Map<string, CachedToken>();
const inflight = new Map<string, Promise<CachedToken>>();

const cacheKey = (scope: UrlTokenScope): string => `${scope}|${localStorage.getItem('access_token') ?? ''}`;

async function mint(scope: UrlTokenScope): Promise<CachedToken> {
    const { data } = await apiClient.post<{ token: string; expires_in: number }>('/auth/url-token', { scope });
    return { token: data.token, expiresAt: Date.now() + data.expires_in * 1000 };
}

async function cachedToken(scope: UrlTokenScope, fresh: boolean): Promise<CachedToken> {
    const key = cacheKey(scope);
    const hit = cache.get(key);
    if (!fresh && hit && hit.expiresAt - Date.now() > RENEW_BEFORE_MS) return hit;
    let pending = inflight.get(key);
    if (!pending) {
        pending = mint(scope)
            .then((minted) => {
                cache.set(key, minted);
                return minted;
            })
            .finally(() => inflight.delete(key));
        inflight.set(key, pending);
    }
    return pending;
}

/** A URL token for `scope`; `fresh` skips the cache (after the API refused one). */
export async function getUrlToken(scope: UrlTokenScope, fresh = false): Promise<string> {
    return (await cachedToken(scope, fresh)).token;
}

/** `path` (an API path such as `/api/v1/artifacts/{id}/download`) as a loadable URL. */
export function withUrlToken(path: string, token: string): string {
    const url = /^https?:\/\//.test(path) ? path : `${API_ORIGIN}${path}`;
    return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
}

/**
 * The current URL token for `scope`, renewed before it expires; `null` until
 * the first one arrives or while `enabled` is false.
 */
export function useUrlToken(scope: UrlTokenScope, enabled = true): string | null {
    const [token, setToken] = useState<string | null>(null);

    useEffect(() => {
        if (!enabled) return;
        let alive = true;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const load = async () => {
            try {
                const current = await cachedToken(scope, false);
                if (!alive) return;
                setToken(current.token);
                timer = setTimeout(load, Math.max(current.expiresAt - Date.now() - RENEW_BEFORE_MS, 5_000));
            } catch {
                if (alive) timer = setTimeout(load, 15_000);
            }
        };
        void load();
        return () => {
            alive = false;
            if (timer) clearTimeout(timer);
        };
    }, [scope, enabled]);

    return enabled ? token : null;
}
