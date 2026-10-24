/**
 * The menu each role sees (Phase 15 T9-1; 07 §4): one snapshot per role and
 * partner type, so a change to anyone's menu is a reviewed change. Plus the
 * rules the snapshots rest on: workspaces, staff functions, partner types,
 * locked entitlements, and route access matching the menu.
 */
import { describe, expect, it } from 'vitest';

import { menuFor, routeAccess, type Viewer } from './config';

const outline = (viewer: Viewer) => menuFor(viewer).map(g => ({
    group: g.label,
    items: g.items.map(i => `${i.label} ${i.route}${i.locked ? ' (locked)' : ''}`),
}));

describe('menus by role (07 §4)', () => {
    const cases: Array<[string, Viewer]> = [
        ['app_admin', { role: 'app_admin' }],
        ['app_user (support)', { role: 'app_user', staffFunctions: ['support'] }],
        ['app_user (finance)', { role: 'app_user', staffFunctions: ['finance'] }],
        ['app_user (sales, ops)', { role: 'app_user', staffFunctions: ['sales', 'ops'] }],
        ['partner_admin (Gold)', { role: 'partner_admin', partnerType: 'GOLD' }],
        ['partner_admin (Silver)', { role: 'partner_admin', partnerType: 'SILVER' }],
        ['partner_user (Gold)', { role: 'partner_user', partnerType: 'GOLD' }],
        ['partner_user (Silver)', { role: 'partner_user', partnerType: 'SILVER' }],
        ['tenant_admin', { role: 'tenant_admin' }],
        ['tenant_user', { role: 'tenant_user' }],
    ];
    it.each(cases)('%s', (_name, viewer) => {
        expect(outline(viewer)).toMatchSnapshot();
    });
});

describe('the rules', () => {
    it('gives each role its own workspace only', () => {
        const routes = (role: string) => menuFor({ role }).flatMap(g => g.items.map(i => i.route));
        expect(routes('app_admin').every(r => r.startsWith('/console'))).toBe(true);
        expect(routes('partner_admin').every(r => r.startsWith('/partner'))).toBe(true);
        expect(routes('tenant_admin').some(r => r.startsWith('/console') || r.startsWith('/partner'))).toBe(false);
    });

    it('never gives a tenant user billing or settings', () => {
        const groups = menuFor({ role: 'tenant_user' }).map(g => g.id);
        expect(groups).not.toContain('billing');
        expect(groups).not.toContain('settings');
    });

    it('never shows an app_user pricing, plans, rules or flags', () => {
        const ids = menuFor({ role: 'app_user', staffFunctions: ['support', 'sales', 'finance', 'ops'] })
            .flatMap(g => g.items.map(i => i.id));
        for (const id of ['pricing', 'plans', 'currency', 'daily-credits', 'programme-rules', 'kernel-flags']) {
            expect(ids).not.toContain(id);
        }
    });

    it('locks, not hides, what the plan leaves out', () => {
        const viewer: Viewer = { role: 'tenant_admin', entitlements: { 'feature.voice.outbound_campaigns': false } };
        const campaigns = menuFor(viewer).flatMap(g => g.items).find(i => i.id === 'campaigns');
        expect(campaigns?.locked).toBe(true);
        expect(routeAccess('/calls/campaigns/123', viewer)).toBe('locked');
        expect(routeAccess('/calls', viewer)).toBe('ok');
    });

    it('keeps Silver out of tenant data and charges', () => {
        const viewer: Viewer = { role: 'partner_admin', partnerType: 'SILVER' };
        expect(routeAccess('/partner/tenants', viewer)).toBe('forbidden');
        expect(routeAccess('/partner/charges', viewer)).toBe('forbidden');
        expect(routeAccess('/partner/customers', viewer)).toBe('ok');
    });

    it('forbids another workspace\'s routes', () => {
        expect(routeAccess('/console/companies', { role: 'tenant_admin' })).toBe('forbidden');
        expect(routeAccess('/billing', { role: 'partner_admin', partnerType: 'GOLD' })).toBe('forbidden');
        expect(routeAccess('/partner/earnings', { role: 'partner_user', partnerType: 'GOLD' })).toBe('forbidden');
        expect(routeAccess('/console/finance/payments', { role: 'app_user', staffFunctions: ['support'] })).toBe('forbidden');
        expect(routeAccess('/console/finance/payments', { role: 'app_user', staffFunctions: ['finance'] })).toBe('ok');
        expect(routeAccess('/profile', { role: 'tenant_user' })).toBe('ok');
    });
});

describe('acting in a tenant (07 §2.7)', () => {
    it('gives staff and Gold partners the business menu while acting', () => {
        const groups = (viewer: Viewer) => menuFor(viewer).map(g => g.id);
        expect(groups({ role: 'app_admin', acting: true })).toContain('billing');
        expect(groups({ role: 'partner_admin', partnerType: 'GOLD', acting: true })).toContain('billing');
        expect(groups({ role: 'partner_user', partnerType: 'GOLD', acting: true })).not.toContain('billing');
    });

    it('lets staff open business pages, partners only while acting', () => {
        expect(routeAccess('/work/42', { role: 'app_admin' })).toBe('ok');
        expect(routeAccess('/work/42', { role: 'partner_admin', partnerType: 'GOLD' })).toBe('forbidden');
        expect(routeAccess('/work/42', { role: 'partner_admin', partnerType: 'GOLD', acting: true })).toBe('ok');
        expect(routeAccess('/billing', { role: 'partner_user', partnerType: 'GOLD', acting: true })).toBe('forbidden');
    });
});
