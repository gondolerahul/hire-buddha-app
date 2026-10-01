import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GlassCard } from '@/components/ui';
import { Loader } from 'lucide-react';
import { oauthService } from '@/services/oauth.service';

export const OAuthCallbackPage: React.FC = () => {
    const [error, setError] = useState('');
    const navigate = useNavigate();
    // The state is single-use and so is the code: finish once, even when
    // StrictMode runs the effect twice.
    const started = useRef(false);

    useEffect(() => {
        if (started.current) return;
        started.current = true;
        oauthService.handleCallback().catch((err: Error) => {
            // The service redirects on success
            setError(err.message || 'Authentication failed');
            setTimeout(() => navigate('/login'), 3000);
        });
    }, [navigate]);

    return (
        <div className="auth-page">
            <div className="liquid-background" />

            <div className="auth-container">
                <GlassCard className="auth-card">
                    <div className="auth-header">
                        <h1 className="text-rose-gold">Authenticating...</h1>
                    </div>

                    {error ? (
                        <div className="error-message">
                            <p>{error}</p>
                            <p>Redirecting to login...</p>
                        </div>
                    ) : (
                        <div style={{ textAlign: 'center', padding: '2rem' }}>
                            <Loader className="spin" size={48} color="var(--color-accent-primary)" />
                            <p style={{ marginTop: '1rem', color: 'var(--color-text-secondary)' }}>
                                Please wait while we complete the authentication...
                            </p>
                        </div>
                    )}
                </GlassCard>
            </div>
        </div>
    );
};
