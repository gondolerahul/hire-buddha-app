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

const base64url = (bytes: Uint8Array): string =>
    btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

/** PKCE (RFC 7636): a random verifier, and its S256 challenge for the authorize request. */
async function pkcePair(): Promise<{ verifier: string; challenge: string }> {
    if (!crypto.subtle) {
        // Only a secure context (https, or localhost) has it.
        throw new Error('Sign-in with a provider needs a secure (https) connection');
    }
    const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    return { verifier, challenge: base64url(new Uint8Array(digest)) };
}

type AuthorizeParams = { clientId: string; state: string; challenge: string };

const AUTHORIZE_URL: Record<OAuthProvider, (p: AuthorizeParams) => string> = {
    google: ({ clientId, state, challenge }) => `https://accounts.google.com/o/oauth2/v2/auth?${new URLSearchParams({
        client_id: clientId,
        redirect_uri: REDIRECT_URI,
        response_type: 'code',
        scope: 'openid email profile',
        state,
        code_challenge: challenge,
        code_challenge_method: 'S256',
        prompt: 'select_account',
    })}`,
    // `User.Read`: the API reads the account from Graph's /me.
    microsoft: ({ clientId, state, challenge }) => `https://login.microsoftonline.com/common/oauth2/v2.0/authorize?${new URLSearchParams({
        client_id: clientId,
        redirect_uri: REDIRECT_URI,
        response_type: 'code',
        scope: 'openid email profile User.Read',
        response_mode: 'query',
        state,
        code_challenge: challenge,
        code_challenge_method: 'S256',
    })}`,
};

/**
 * Google and Microsoft sign-in, by the authorization-code flow (FE-11).
 *
 * The `state` is random, kept in sessionStorage with the provider, and must
 * come back unchanged: a callback this browser did not start — a link someone
 * else crafted to sign the user into *their* account — is refused. PKCE binds
 * the code to this browser too: the authorize request carries the verifier's
 * challenge, and only the exchange that sends the verifier gets tokens.
 */
export const oauthService = {
    /** The providers with a real client id; the login page shows only these. */
    configuredProviders(): OAuthProvider[] {
        return (Object.keys(CLIENT_IDS) as OAuthProvider[]).filter(p => isConfigured(CLIENT_IDS[p]));
    },

    /** Record a new sign-in for `provider` and return the provider's URL for it. */
    async begin(provider: OAuthProvider): Promise<string> {
        const clientId = CLIENT_IDS[provider];
        if (!isConfigured(clientId)) {
            throw new Error(`${provider} sign-in is not configured`);
        }
        const state = randomState();
        const { verifier, challenge } = await pkcePair();
        sessionStorage.setItem(STATE_KEY, JSON.stringify({ state, provider, verifier }));
        return AUTHORIZE_URL[provider]({ clientId, state, challenge });
    },

    /** Go to the provider's sign-in page. */
    async start(provider: OAuthProvider): Promise<void> {
        window.location.assign(await oauthService.begin(provider));
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
        let expected: { state?: string; provider?: OAuthProvider; verifier?: string } = {};
        try {
            expected = stored ? JSON.parse(stored) : {};
        } catch {
            // unreadable: treated as missing
        }
        if (!expected.state || !expected.provider || !expected.verifier || params.get('state') !== expected.state) {
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
            ({ data } = await apiClient.post(`/auth/oauth/${expected.provider}`, {
                code,
                redirect_uri: REDIRECT_URI,
                code_verifier: expected.verifier,
            }));
        } catch (err) {
            throw new Error(apiErrorMessage(err, 'Failed to authenticate with the sign-in provider'));
        }

        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);
        window.location.href = '/dashboard';
    },
};
