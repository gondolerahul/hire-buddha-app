import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard, GlassInput, JellyButton } from '@/components/ui';
import logo from '@/assets/logo.png';
import './LoginPage.css';

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

                        <JellyButton
                            type="submit"
                            roseGold
                            disabled={loading}
                            className="auth-submit"
                        >
                            {loading ? 'Signing in...' : 'Sign In'}
                        </JellyButton>
                    </form>

                    <div className="auth-divider">
                        <span>or continue with</span>
                    </div>

                    <div className="oauth-buttons">
                        <JellyButton variant="secondary" className="oauth-button">
                            <img src="/google-icon.svg" alt="Google" />
                            Google
                        </JellyButton>
                        <JellyButton variant="secondary" className="oauth-button">
                            <img src="/microsoft-icon.svg" alt="Microsoft" />
                            Microsoft
                        </JellyButton>
                    </div>

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
