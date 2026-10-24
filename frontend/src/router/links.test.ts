/**
 * No dead links (Phase 15 T9-11): every in-app link (`to=`, `navigate(`, `href=`)
 * and every menu route goes to a route the router serves, and no link uses an
 * old route that only redirects.
 */
import { describe, expect, it } from 'vitest';

const sources = import.meta.glob(['/src/**/*.tsx', '/src/**/*.ts', '!/src/**/*.test.*'],
                                 { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const router = sources['/src/router/index.tsx'];

const table = (name: string) => router.split(`export const ${name}`)[1].split('\n];')[0];
const routes = [...table('ROUTES').matchAll(/\['(\/[^']*)', </g)].map(m => m[1]);
const redirects = [...table('REDIRECTS').matchAll(/\['(\/[^']*)', '(\/[^']*)'\]/g)].map(m => [m[1], m[2]] as const);
const elsewhere = [...router.matchAll(/path="(\/[^"]*)"/g)].map(m => m[1]);

const matcher = (path: string) => new RegExp(`^${path.replace(/:\w+/g, '[^/]+')}$`);
const served = [...routes, ...elsewhere].map(matcher);
const old = redirects.map(([from]) => from).filter(p => p !== '/' && p !== '/dashboard').map(matcher);

/** `${x}` becomes one segment; a query or hash is dropped. */
const normalise = (raw: string) => raw.replace(/\$\{[^}]*\}/g, 'x').split(/[?#]/)[0].replace(/\/$/, '') || '/';

const links: Array<{ file: string; path: string }> = [];
for (const [file, text] of Object.entries(sources)) {
    if (file === '/src/router/index.tsx') continue;
    for (const m of text.matchAll(/(?:\bto=\{?|navigate\(|href=|route: )[`'"](\/[^`'"]*)[`'"]/g)) {
        links.push({ file, path: normalise(m[1]) });
    }
}

describe('in-app links', () => {
    it('finds the route table and links', () => {
        expect(routes.length).toBeGreaterThan(90);
        expect(links.length).toBeGreaterThan(50);
    });

    it('go to a route the router serves', () => {
        const dead = links.filter(l => !served.some(r => r.test(l.path)) && !old.some(r => r.test(l.path)));
        expect(dead).toEqual([]);
    });

    it('do not use an old route', () => {
        const stale = links.filter(l => old.some(r => r.test(l.path)) && !served.some(r => r.test(l.path)));
        expect(stale).toEqual([]);
    });

    it('every redirect lands on a served route', () => {
        const broken = redirects.filter(([, to]) => to !== '/dashboard' && !served.some(r => r.test(to.replace(/:\w+/g, 'x'))));
        expect(broken).toEqual([]);
    });
});
