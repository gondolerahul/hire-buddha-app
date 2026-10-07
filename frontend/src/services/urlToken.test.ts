/**
 * FE-28: browser-loaded URLs carry a URL token, cached per scope and per login.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const post = vi.fn();
vi.mock('./api.client', () => ({ apiClient: { post: (...args: unknown[]) => post(...args) } }));
vi.mock('@/config/api', () => ({ API_ORIGIN: 'http://api.test' }));

import { getUrlToken, withUrlToken } from './urlToken';

let minted = 0;

beforeEach(() => {
    post.mockReset();
    post.mockImplementation(async (_url: string, body: { scope: string }) => {
        minted += 1;
        return { data: { token: `t${minted}:${body.scope}`, expires_in: 600 } };
    });
    localStorage.setItem('access_token', 'login-a');
});

describe('getUrlToken', () => {
    it('mints for the scope and reuses the token while it is fresh', async () => {
        const first = await getUrlToken('/api/v1/artifacts/');
        const again = await getUrlToken('/api/v1/artifacts/');
        expect(first).toBe(again);
        expect(post).toHaveBeenCalledTimes(1);
        expect(post).toHaveBeenCalledWith('/auth/url-token', { scope: '/api/v1/artifacts/' });
    });

    it('mints again for another login', async () => {
        const forA = await getUrlToken('/api/v1/ai/executions/');
        localStorage.setItem('access_token', 'login-b');
        const forB = await getUrlToken('/api/v1/ai/executions/');
        expect(forB).not.toBe(forA);
    });

    it('mints again when asked for a fresh one', async () => {
        const cached = await getUrlToken('/api/v1/artifacts/');
        const fresh = await getUrlToken('/api/v1/artifacts/', true);
        expect(fresh).not.toBe(cached);
    });
});

describe('withUrlToken', () => {
    it('never puts the login token in the URL', () => {
        const url = withUrlToken('/api/v1/artifacts/a1/download', 'url-tok');
        expect(url).toBe('http://api.test/api/v1/artifacts/a1/download?token=url-tok');
        expect(url).not.toContain('login-a');
    });

    it('keeps an absolute URL and an existing query string', () => {
        expect(withUrlToken('http://x.test/api/v1/ai/executions/r/stream?a=1', 't'))
            .toBe('http://x.test/api/v1/ai/executions/r/stream?a=1&token=t');
    });
});
