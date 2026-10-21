// @vitest-environment jsdom
/**
 * HireBuddha's provider apps (Phase 14 M1-12): staff register an app with its
 * settings and its secrets' vault names; the list says which are in the vault.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const saveOauthApp = vi.fn();
const apps = [
    { provider: 'meta', registered: true, status: 'active', settings: { client_id: '123' }, secret: 'oauth-meta-app-secret',
      secret_in_vault: true, refs: { verify_token: 'oauth-meta-verify-token' }, refs_in_vault: { verify_token: false },
      required: ['client_id'], required_refs: [] },
    { provider: 'github', registered: false, status: null, settings: {}, secret: null, secret_in_vault: null,
      refs: {}, refs_in_vault: {}, required: ['client_id', 'app_id', 'app_slug'], required_refs: ['private_key', 'webhook_secret'] },
];

vi.mock('@/services/connections.service', () => ({
    connectionsService: {
        oauthApps: vi.fn(async () => apps),
        saveOauthApp: (...args: unknown[]) => saveOauthApp(...args),
    },
}));

import { ProviderAppsPanel } from './ProviderAppsPanel';

afterEach(() => { cleanup(); saveOauthApp.mockReset(); });

const setup = () => render(<QueryClientProvider client={new QueryClient()}><ProviderAppsPanel /></QueryClientProvider>);
const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe('ProviderAppsPanel', () => {
    it('shows whether each named secret is in the vault', async () => {
        setup();
        expect(await screen.findByText('client secret: ✓ in vault')).toBeTruthy();
        expect(screen.getByText('verify_token: ✗ not in vault')).toBeTruthy();
        expect(screen.getByText('Not yet')).toBeTruthy();
    });

    it('registers an app with its settings and its secrets by vault name', async () => {
        saveOauthApp.mockResolvedValue({ ...apps[1], registered: true });
        setup();
        fireEvent.click(await screen.findByText('register'));
        fill('client_id', 'Iv1.abc');
        fill('app_id', '123');
        fill('app_slug', 'hirebuddha');
        fill('private_key vault name', 'oauth-github-private-key');
        fill('webhook_secret vault name', 'oauth-github-webhook-secret');
        fireEvent.click(screen.getByText('Register'));
        await waitFor(() => expect(saveOauthApp).toHaveBeenCalled());
        expect(saveOauthApp).toHaveBeenCalledWith('github', {
            settings: { client_id: 'Iv1.abc', app_id: '123', app_slug: 'hirebuddha' },
            refs: { private_key: 'oauth-github-private-key', webhook_secret: 'oauth-github-webhook-secret' },
            secret: 'oauth-github-client-secret',
        });
        expect(await screen.findByRole('status')).toBeTruthy();
    });
});
