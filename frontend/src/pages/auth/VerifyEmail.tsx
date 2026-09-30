import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { GlassCard, GlassInput, JellyButton } from '@/components/ui';
import { authService } from '@/services/auth.service';
import logo from '@/assets/logo.png';
import './LoginPage.css';
import './PasswordReset.css';

/**
 * /verify-email
 *   ?token=…  — the link from the verification email: verifies, then offers sign-in.
 *   ?email=…  — after registering: "check your inbox", with a resend button.
 * An account cannot sign in until its address is verified (AU-08).
 */
export const VerifyEmailPage: React.FC = () => {
    const [params] = useSearchParams();
    const navigate = useNavigate();
    const token = params.get('token');
    const [email, setEmail] = useState(params.get('email') || '');
    const [state, setState] = useState<'idle' | 'verifying' | 'verified' | 'failed'>(token ? 'verifying' : 'idle');
    const [message, setMessage] = useState('');
    const [sending, setSending] = useState(false);
    const started = useRef(false);

    useEffect(() => {
        if (!token || started.current) return;
        started.current = true;
        authService
            .verifyEmail(token)
            .then(() => setState('verified'))
            .catch((err: any) => {
                setState('failed');
                setMessage(err.response?.data?.detail || 'This link is invalid or has expired.');
            });
    }, [token]);

    const resend = async (e: React.FormEvent) => {
        e.preventDefault();
        setSending(true);
        try {
            const reply = await authService.resendVerification(email);
            setState('idle');
            setMessage(reply.message);
        } catch (err: any) {
            setMessage(err.response?.data?.detail || 'Could not send the link. Try again later.');
        } finally {
            setSending(false);
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
                        <p>Verify your email address</p>
                    </div>

                    {state === 'verifying' && <p>Verifying your email address…</p>}

                    {state === 'verified' && (
                        <div className="success-message">
                            <h3>Email verified</h3>
                            <p>Your account is ready. Sign in to continue.</p>
                            <JellyButton roseGold onClick={() => navigate('/login')} className="auth-submit">
                                Go to Login
                            </JellyButton>
                        </div>
                    )}

                    {(state === 'idle' || state === 'failed') && (
                        <form onSubmit={resend} className="auth-form">
                            {state === 'idle' ? (
                                <p>
                                    We've sent a verification link to <strong>{email || 'your email address'}</strong>.
                                    Open it to finish creating your account. It works for 24 hours.
                                </p>
                            ) : (
                                <div className="error-message">{message || 'This link is invalid or has expired.'}</div>
                            )}
                            <GlassInput
                                type="email"
                                label="Email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                            />
                            {state === 'idle' && message && <p>{message}</p>}
                            <JellyButton type="submit" roseGold disabled={sending || !email} className="auth-submit">
                                {sending ? 'Sending...' : 'Send the link again'}
                            </JellyButton>
                        </form>
                    )}
                </GlassCard>
            </div>
        </div>
    );
};
