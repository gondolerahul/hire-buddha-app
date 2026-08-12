import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard, GlassInput, JellyButton } from '@/components/ui';
import logo from '@/assets/logo.png';
import './LoginPage.css';

export const RegisterPage: React.FC = () => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [fullName, setFullName] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { register } = useAuth();
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');

        // Validate password length
        if (password.length < 12) {
            setError('Password must be at least 12 characters long');
            return;
        }

        setLoading(true);

        try {
            await register(email, password, fullName);
            navigate('/dashboard');
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Registration failed. Please try again.');
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
                        <p>Create your account</p>
                    </div>

                    <form onSubmit={handleSubmit} className="auth-form">
                        <GlassInput
                            type="text"
                            label="Full Name"
                            value={fullName}
                            onChange={(e) => setFullName(e.target.value)}
                            required
                        />

                        <GlassInput
                            type="email"
                            label="Email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                        />

                        <div>
                            <GlassInput
                                type="password"
                                label="Password (min 12 characters)"
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

                        {error && <div className="error-message">{error}</div>}

                        <div className="info-message">
                            <p>A workspace will be automatically created for you</p>
                        </div>

                        <JellyButton
                            type="submit"
                            roseGold
                            disabled={loading}
                            className="auth-submit"
                        >
                            {loading ? 'Creating Account...' : 'Create Account'}
                        </JellyButton>
                    </form>

                    <div className="auth-footer">
                        <p>
                            Already have an account?{' '}
                            <Link to="/login" className="text-rose-gold">
                                Sign in
                            </Link>
                        </p>
                    </div>
                </GlassCard>
            </div>
        </div>
    );
};
