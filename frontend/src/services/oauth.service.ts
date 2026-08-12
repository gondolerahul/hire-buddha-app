

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;
const MICROSOFT_CLIENT_ID = import.meta.env.VITE_MICROSOFT_CLIENT_ID;
const REDIRECT_URI = `${window.location.origin}/auth/callback`;

export const oauthService = {
    /**
     * Initiate Google OAuth flow
     */
    loginWithGoogle() {
        const params = new URLSearchParams({
            client_id: GOOGLE_CLIENT_ID,
            redirect_uri: REDIRECT_URI,
            response_type: 'code',
            scope: 'openid email profile',
            access_type: 'offline',
            prompt: 'consent',
        });

        window.location.href = `https://accounts.google.com/o/oauth2/v2/auth?${params}`;
    },

    /**
     * Initiate Microsoft OAuth flow
     */
    loginWithMicrosoft() {
        const params = new URLSearchParams({
            client_id: MICROSOFT_CLIENT_ID,
            redirect_uri: REDIRECT_URI,
            response_type: 'code',
            scope: 'openid email profile',
            response_mode: 'query',
        });

        window.location.href = `https://login.microsoftonline.com/common/oauth2/v2.0/authorize?${params}`;
    },

    /**
     * Handle OAuth callback
     * This should be called from the callback page
     */
    async handleCallback(provider: 'google' | 'microsoft'): Promise<void> {
        const urlParams = new URLSearchParams(window.location.search);
        const code = urlParams.get('code');
        const error = urlParams.get('error');

        if (error) {
            throw new Error(`OAuth error: ${error}`);
        }

        if (!code) {
            throw new Error('No authorization code received');
        }

        // Send code to backend for token exchange
        const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/auth/oauth/${provider}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ code, redirect_uri: REDIRECT_URI }),
        });

        if (!response.ok) {
            throw new Error('Failed to authenticate with OAuth provider');
        }

        const data = await response.json();

        // Store tokens
        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);

        // Redirect to dashboard
        window.location.href = '/dashboard';
    },
};
