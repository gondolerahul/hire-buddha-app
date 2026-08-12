import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GlassCard, GlassInput, JellyButton } from '@/components/ui';
import { ArrowLeft } from 'lucide-react';
import { apiClient } from '@/services/api.client';
import logo from '@/assets/logo.png';
import './LoginPage.css';
import './PasswordReset.css';

export const ForgotPasswordPage: React.FC = () => {
    const [email, setEmail] = useState('');
    const [loading, setLoading] = useState(false);
    const [success, setSuccess] = useState(false);
    const [error, setError] = useState('');
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            await apiClient.post('/auth/forgot-password', { email });
            setSuccess(true);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Failed to send reset email');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="auth-page">
            <div className="liquid-background" />

            <div className="auth-container">
                <GlassCard className="auth-card">
                    <button className="back-button" onClick={() => navigate('/login')}>
                        <ArrowLeft size={20} />
                        Back to Login
                    </button>

                    <div className="auth-header">
                        <img src={logo} alt="HireBuddha" className="auth-logo" />
                        <h1 className="text-rose-gold">HireBuddha</h1>
                        <p>Reset your password</p>
                    </div>

                    {success ? (
                        <div className="success-message">
                            <h3>Check your email</h3>
                            <p>
                                We've sent a password reset link to <strong>{email}</strong>.
                                Please check your inbox and follow the instructions.
                            </p>
                            <JellyButton
                                roseGold
                                onClick={() => navigate('/login')}
                                className="auth-submit"
                            >
                                Return to Login
                            </JellyButton>
                        </div>
                    ) : (
                        <form onSubmit={handleSubmit} className="auth-form">
                            <GlassInput
                                type="email"
                                label="Email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                            />

                            {error && <div className="error-message">{error}</div>}

                            <JellyButton
                                type="submit"
                                roseGold
                                disabled={loading}
                                className="auth-submit"
                            >
                                {loading ? 'Sending...' : 'Send Reset Link'}
                            </JellyButton>
                        </form>
                    )}
                </GlassCard>
            </div>
        </div>
    );
};

export const ResetPasswordPage: React.FC = () => {
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [loading, setLoading] = useState(false);
    const [success, setSuccess] = useState(false);
    const [error, setError] = useState('');
    const navigate = useNavigate();

    // Get token from URL query params
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');

        if (password.length < 12) {
            setError('Password must be at least 12 characters long');
            return;
        }

        if (password !== confirmPassword) {
            setError('Passwords do not match');
            return;
        }

        setLoading(true);

        try {
            await apiClient.post('/auth/reset-password', {
                token,
                new_password: password,
            });
            setSuccess(true);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Failed to reset password');
        } finally {
            setLoading(false);
        }
    };

    const getPasswordStrength = () => {
        const length = password.length;
        if (length === 0) return { strength: '', color: '' };
        if (length < 8) return { strength: 'Weak', color: 'var(--color-error)' };
        if (length < 12) return { strength: 'Fair', color: 'var(--color-warning)' };
        return { strength: 'Strong', color: 'var(--color-success)' };
    };

    const passwordStrength = getPasswordStrength();

    return (
        <div className="auth-page">
            <div className="liquid-background" />

            <div className="auth-container">
                <GlassCard className="auth-card">
                    <div className="auth-header">
                        <img src={logo} alt="HireBuddha" className="auth-logo" />
                        <h1 className="text-rose-gold">HireBuddha</h1>
                        <p>Set a new password</p>
                    </div>

                    {success ? (
                        <div className="success-message">
                            <h3>Password Reset Successful!</h3>
                            <p>Your password has been updated. You can now log in with your new password.</p>
                            <JellyButton
                                roseGold
                                onClick={() => navigate('/login')}
                                className="auth-submit"
                            >
                                Go to Login
                            </JellyButton>
                        </div>
                    ) : (
                        <form onSubmit={handleSubmit} className="auth-form">
                            <div>
                                <GlassInput
                                    type="password"
                                    label="New Password (min 12 characters)"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                />
                                {password && (
                                    <div
                                        className="password-strength"
                                        style={{ color: passwordStrength.color }}
                                    >
                                        {passwordStrength.strength}
                                    </div>
                                )}
                            </div>

                            <GlassInput
                                type="password"
                                label="Confirm Password"
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                required
                            />

                            {error && <div className="error-message">{error}</div>}

                            <JellyButton
                                type="submit"
                                roseGold
                                disabled={loading}
                                className="auth-submit"
                            >
                                {loading ? 'Resetting...' : 'Reset Password'}
                            </JellyButton>
                        </form>
                    )}
                </GlassCard>
            </div>
        </div>
    );
};
