import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard, GlassInput, JellyButton } from '@/components/ui';
import { oauthService, OAuthProvider } from '@/services/oauth.service';
import logo from '@/assets/logo.png';
import './LoginPage.css';

const PROVIDER_BUTTONS: Record<OAuthProvider, { label: string; icon: React.ReactNode }> = {
    google: {
        label: 'Google',
        icon: (
            <svg viewBox="0 0 48 48" aria-hidden="true">
                <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
                <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
                <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
                <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
            </svg>
        ),
    },
    microsoft: {
        label: 'Microsoft',
        icon: (
            <svg viewBox="0 0 21 21" aria-hidden="true">
                <rect x="1" y="1" width="9" height="9" fill="#F25022" />
                <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
                <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
                <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
            </svg>
        ),
    },
};

// Only providers with a client id configured get a button (FE-11).
const OAUTH_PROVIDERS = oauthService.configuredProviders();

export const LoginPage: React.FC = () => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { login } = useAuth();
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            await login(email, password);
            navigate('/dashboard');
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Login failed. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="auth-page">
            <div className="liquid-background" />

            <div className="auth-container">
                <GlassCard className="auth-card">
                    <div className="auth-header">
                        <img src={logo} alt="HireBuddha" className="auth-logo" />
                        <h1 className="text-rose-gold">HireBuddha</h1>
                        <p>Sign in to your account</p>
                    </div>

                    <form onSubmit={handleSubmit} className="auth-form">
                        <GlassInput
                            type="email"
                            label="Email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                        />

                        <GlassInput
                            type="password"
                            label="Password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                        />

                        {error && <div className="error-message">{error}</div>}
                        {error.includes('verify your email') && (
                            <Link to={`/verify-email?email=${encodeURIComponent(email)}`} className="auth-link">
                                Send the verification link again
                            </Link>
                        )}

                        <JellyButton
                            type="submit"
                            roseGold
                            disabled={loading}
                            className="auth-submit"
                        >
                            {loading ? 'Signing in...' : 'Sign In'}
                        </JellyButton>
                    </form>

                    {OAUTH_PROVIDERS.length > 0 && (
                        <>
                            <div className="auth-divider">
                                <span>or continue with</span>
                            </div>

                            <div className="oauth-buttons">
                                {OAUTH_PROVIDERS.map(provider => (
                                    <JellyButton
                                        key={provider}
                                        variant="secondary"
                                        className="oauth-button"
                                        onClick={() => oauthService.start(provider)}
                                    >
                                        {PROVIDER_BUTTONS[provider].icon}
                                        {PROVIDER_BUTTONS[provider].label}
                                    </JellyButton>
                                ))}
                            </div>
                        </>
                    )}

                    <div className="auth-footer">
                        <p>
                            Don't have an account?{' '}
                            <Link to="/register" className="text-rose-gold">
                                Create one
                            </Link>
                        </p>
                    </div>
                </GlassCard>
            </div>
        </div>
    );
};
