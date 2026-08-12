import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { GlassCard } from '@/components/ui';
import { Loader } from 'lucide-react';
import { oauthService } from '@/services/oauth.service';

export const OAuthCallbackPage: React.FC = () => {
    const [error, setError] = useState('');
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();

    useEffect(() => {
        const handleOAuthCallback = async () => {
            const provider = searchParams.get('state') as 'google' | 'microsoft';

            if (!provider) {
                setError('Invalid OAuth state');
                return;
            }

            try {
                await oauthService.handleCallback(provider);
                // Redirect is handled in the service
            } catch (err: any) {
                setError(err.message || 'Authentication failed');
                setTimeout(() => navigate('/login'), 3000);
            }
        };

        handleOAuthCallback();
    }, [searchParams, navigate]);

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
