// @vitest-environment jsdom
/**
 * Acting for another company (Phase 14 M2-4): the switcher lists the other
 * companies the caller may see and remembers the choice; every request then
 * names it in X-Company-Id; the banner goes back to the caller's own company.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const visible = vi.hoisted(() => ({
    companies: [] as Array<{ id: string; name: string; type: string; status: string }>,
}));
vi.mock('@/queries/hooks', () => ({ useCompanyList: () => ({ data: visible.companies }) }));
const BOTH = [
    { id: 'own', name: 'HireBuddha', type: 'APP', status: 'active' },
    { id: 'acme', name: 'Acme', type: 'TENANT', status: 'active' },
];

import { ActingCompanyBanner, ActingCompanySwitcher } from './ActingCompany';
import { ACTING_COMPANY_HEADER, getActingCompany, setActingCompany } from '@/services/actingCompany';

beforeEach(() => {
    localStorage.clear();
    visible.companies = BOTH;
});
afterEach(cleanup);

function wrap(node: React.ReactNode) {
    return render(<QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>);
}

describe('ActingCompanySwitcher', () => {
    it('lists the other companies and remembers the one chosen', () => {
        const reload = vi.fn();
        wrap(<ActingCompanySwitcher expanded ownCompanyId="own" reload={reload} />);
        const select = screen.getByLabelText('Working in') as HTMLSelectElement;
        expect(Array.from(select.options).map((o) => o.textContent)).toEqual(['My own company', 'Acme']);
        fireEvent.change(select, { target: { value: 'acme' } });
        expect(getActingCompany()).toEqual({ id: 'acme', name: 'Acme' });
        expect(reload).toHaveBeenCalledOnce();
    });

    it('is not shown to someone who sees only their own company', () => {
        visible.companies = [BOTH[1]];
        const { container } = wrap(<ActingCompanySwitcher expanded ownCompanyId="acme" />);
        expect(container.innerHTML).toBe('');
    });
});

describe('ActingCompanyBanner', () => {
    it('says whose data is shown and goes back', () => {
        setActingCompany({ id: 'acme', name: 'Acme' });
        const reload = vi.fn();
        wrap(<ActingCompanyBanner reload={reload} />);
        expect(screen.getByRole('status').textContent).toContain('Acme');
        fireEvent.click(screen.getByText('Back to my company'));
        expect(getActingCompany()).toBeNull();
        expect(reload).toHaveBeenCalledOnce();
    });

    it('shows nothing in your own company', () => {
        const { container } = wrap(<ActingCompanyBanner />);
        expect(container.innerHTML).toBe('');
    });
});

describe('the API client', () => {
    it('names the acting company on every request, unless a request names one itself', async () => {
        const { apiClient } = await import('@/services/api.client');
        const seen: Array<string | undefined> = [];
        const adapter = async (config: { headers: Record<string, string> }) => {
            seen.push(config.headers[ACTING_COMPANY_HEADER]);
            return { data: {}, status: 200, statusText: 'OK', headers: {}, config };
        };
        await apiClient.get('/x', { adapter } as never);
        setActingCompany({ id: 'acme', name: 'Acme' });
        await apiClient.get('/x', { adapter } as never);
        await apiClient.get('/x', { adapter, headers: { [ACTING_COMPANY_HEADER]: 'beta' } } as never);
        expect(seen).toEqual([undefined, 'acme', 'beta']);
    });
});
