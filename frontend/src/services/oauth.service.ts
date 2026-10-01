import { apiClient } from '@/services/api.client';
import { apiErrorMessage } from '@/utils/apiError';

export type OAuthProvider = 'google' | 'microsoft';

const CLIENT_IDS: Record<OAuthProvider, string | undefined> = {
    google: import.meta.env.VITE_GOOGLE_CLIENT_ID,
    microsoft: import.meta.env.VITE_MICROSOFT_CLIENT_ID,
};
const REDIRECT_URI = `${window.location.origin}/auth/callback`;

/** The sign-in this browser started: compared with what the provider sends back. */
const STATE_KEY = 'oauth_state';

/** A client id that is set and is not the `.env.example` placeholder (`your_…_here`). */
const isConfigured = (id?: string): id is string => !!id && !/^your_.*_here$/i.test(id.trim());

const randomState = (): string =>
    Array.from(crypto.getRandomValues(new Uint8Array(32)), b => b.toString(16).padStart(2, '0')).join('');

const AUTHORIZE_URL: Record<OAuthProvider, (clientId: string, state: string) => string> = {
    google: (clientId, state) => `https://accounts.google.com/o/oauth2/v2/auth?${new URLSearchParams({
        client_id: clientId,
        redirect_uri: REDIRECT_URI,
        response_type: 'code',
        scope: 'openid email profile',
        state,
        prompt: 'select_account',
    })}`,
    // `User.Read`: the API reads the account from Graph's /me.
    microsoft: (clientId, state) => `https://login.microsoftonline.com/common/oauth2/v2.0/authorize?${new URLSearchParams({
        client_id: clientId,
        redirect_uri: REDIRECT_URI,
        response_type: 'code',
        scope: 'openid email profile User.Read',
        response_mode: 'query',
        state,
    })}`,
};

/**
 * Google and Microsoft sign-in, by the authorization-code flow (FE-11).
 *
 * The `state` is random, kept in sessionStorage with the provider, and must
 * come back unchanged: a callback this browser did not start — a link someone
 * else crafted to sign the user into *their* account — is refused.
 */
export const oauthService = {
    /** The providers with a real client id; the login page shows only these. */
    configuredProviders(): OAuthProvider[] {
        return (Object.keys(CLIENT_IDS) as OAuthProvider[]).filter(p => isConfigured(CLIENT_IDS[p]));
    },

    /** Record a new sign-in for `provider` and return the provider's URL for it. */
    begin(provider: OAuthProvider): string {
        const clientId = CLIENT_IDS[provider];
        if (!isConfigured(clientId)) {
            throw new Error(`${provider} sign-in is not configured`);
        }
        const state = randomState();
        sessionStorage.setItem(STATE_KEY, JSON.stringify({ state, provider }));
        return AUTHORIZE_URL[provider](clientId, state);
    },

    /** Go to the provider's sign-in page. */
    start(provider: OAuthProvider): void {
        window.location.assign(oauthService.begin(provider));
    },

    /**
     * Finish the sign-in on `/auth/callback`: check the state, exchange the
     * code for this app's tokens, and go to the dashboard.
     */
    async handleCallback(search: string = window.location.search): Promise<void> {
        const params = new URLSearchParams(search);

        // Single use: whatever happens next, this state cannot be replayed.
        const stored = sessionStorage.getItem(STATE_KEY);
        sessionStorage.removeItem(STATE_KEY);
        let expected: { state?: string; provider?: OAuthProvider } = {};
        try {
            expected = stored ? JSON.parse(stored) : {};
        } catch {
            // unreadable: treated as missing
        }
        if (!expected.state || !expected.provider || params.get('state') !== expected.state) {
            throw new Error('This sign-in was not started from this browser. Please sign in again.');
        }

        const error = params.get('error');
        if (error) {
            throw new Error(`Sign-in was not completed: ${params.get('error_description') || error}`);
        }
        const code = params.get('code');
        if (!code) {
            throw new Error('No authorization code received');
        }

        let data;
        try {
            ({ data } = await apiClient.post(`/auth/oauth/${expected.provider}`, { code, redirect_uri: REDIRECT_URI }));
        } catch (err) {
            throw new Error(apiErrorMessage(err, 'Failed to authenticate with the sign-in provider'));
        }

        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);
        window.location.href = '/dashboard';
    },
};
