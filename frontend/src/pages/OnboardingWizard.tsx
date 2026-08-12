import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { onboardingService, OnboardingStatus } from '@/services/platform.service';
import './OnboardingWizard.css';

const STEPS = [
    {
        key: 'company_profile',
        icon: '🏢',
        title: 'Set Up Your Workspace',
        description: 'Give your workspace a name and brand identity to get started.',
        fields: ['name', 'industry'],
    },
    {
        key: 'integrations',
        icon: '🔗',
        title: 'Connect Your AI Provider',
        description: 'Link your preferred AI provider — we\'ll handle the rest.',
        features: [
            { icon: '🤖', name: 'Google Gemini / Vertex AI', desc: 'Multi-modal AI capabilities' },
            { icon: '🧠', name: 'OpenAI GPT', desc: 'Industry-leading language models' },
            { icon: '📧', name: 'Email Integration', desc: 'Gmail / SMTP for outreach' },
            { icon: '📱', name: 'WhatsApp Business', desc: 'Messaging automation' },
        ],
    },
    {
        key: 'first_agent',
        icon: '⚡',
        title: 'Create Your First Agent',
        description: 'Pick from our templates or build a custom AI agent from scratch.',
        features: [
            { icon: '📋', name: 'Research Agent', desc: 'Automated deep research & reporting' },
            { icon: '📞', name: 'Voice Agent', desc: 'AI-powered phone calls & outreach' },
            { icon: '💬', name: 'Chat Agent', desc: 'Customer support & engagement' },
            { icon: '✍️', name: 'Custom Agent', desc: 'Build your own from scratch' },
        ],
    },
    {
        key: 'phone_setup',
        icon: '📞',
        title: 'Phone Number Setup',
        description: 'Claim a phone number for voice calls and SMS — you can skip this for now.',
        skippable: true,
        features: [
            { icon: '🇮🇳', name: 'Indian Numbers', desc: 'Tata Teleservices DID numbers' },
            { icon: '🌍', name: 'International', desc: 'Twilio-powered global numbers' },
        ],
    },
    {
        key: 'billing',
        icon: '💳',
        title: 'Review Your Credits',
        description: 'Your workspace has been provisioned with daily credits. Here\'s what you get.',
        features: [
            { icon: '🎁', name: 'Free Daily Credits', desc: 'Automatic daily credit top-up included' },
            { icon: '📊', name: 'Usage Tracking', desc: 'Real-time cost monitoring per agent' },
            { icon: '🔒', name: 'Budget Controls', desc: 'Set spending limits per execution' },
        ],
    },
];

const OnboardingWizard: React.FC = () => {
    const navigate = useNavigate();
    const { user } = useAuth();
    const [currentStep, setCurrentStep] = useState(0);
    const [status, setStatus] = useState<OnboardingStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    // Form state for company_profile step
    const [companyName, setCompanyName] = useState('');
    const [industry, setIndustry] = useState('');

    const loadStatus = useCallback(async () => {
        try {
            const s = await onboardingService.getStatus();
            setStatus(s);
            // Find the first incomplete step
            const idx = STEPS.findIndex(step => !s.completed_steps.includes(step.key));
            if (idx >= 0) setCurrentStep(idx);
            if (s.status === 'completed') {
                navigate('/dashboard', { replace: true });
            }
        } catch (err) {
            console.error('Failed to load onboarding status:', err);
        } finally {
            setLoading(false);
        }
    }, [navigate]);

    useEffect(() => {
        loadStatus();
    }, [loadStatus]);

    const handleCompleteStep = async () => {
        const step = STEPS[currentStep];
        setSaving(true);
        try {
            let stepData: Record<string, any> | undefined;
            if (step.key === 'company_profile') {
                stepData = { name: companyName || user?.full_name + "'s Workspace", industry };
            }
            const updated = await onboardingService.completeStep(step.key, stepData);
            setStatus(updated);

            if (currentStep < STEPS.length - 1) {
                setCurrentStep(currentStep + 1);
            } else {
                // Finalize
                await onboardingService.finalizeOnboarding();
                navigate('/dashboard', { replace: true });
            }
        } catch (err) {
            console.error('Step completion failed:', err);
        } finally {
            setSaving(false);
        }
    };

    const handleSkipOnboarding = async () => {
        try {
            await onboardingService.skipOnboarding();
            navigate('/dashboard', { replace: true });
        } catch (err) {
            console.error('Skip failed:', err);
        }
    };

    if (loading) {
        return (
            <div className="onboarding-wizard">
                <div style={{ color: 'var(--color-text-tertiary)', fontSize: '0.9rem' }}>
                    Loading setup wizard…
                </div>
            </div>
        );
    }

    const step = STEPS[currentStep];
    const isCompleted = status?.completed_steps.includes(step.key);

    return (
        <div className="onboarding-wizard">
            <div className="onboarding-container">
                {/* Progress bar */}
                <div className="onboarding-progress">
                    {STEPS.map((s, i) => (
                        <div
                            key={s.key}
                            className={`progress-step ${
                                status?.completed_steps.includes(s.key) ? 'completed' :
                                i === currentStep ? 'active' : ''
                            }`}
                        />
                    ))}
                </div>

                {/* Step content */}
                <div className="step-card">
                    <div className="step-header">
                        <div className="step-icon">{step.icon}</div>
                        <h2>{step.title}</h2>
                        <p>{step.description}</p>
                    </div>

                    <div className="step-content">
                        {/* Company Profile — form inputs */}
                        {step.key === 'company_profile' && (
                            <>
                                <div className="form-group">
                                    <label>Workspace Name</label>
                                    <input
                                        id="onboarding-company-name"
                                        type="text"
                                        placeholder="e.g. Acme Corp"
                                        value={companyName}
                                        onChange={(e) => setCompanyName(e.target.value)}
                                    />
                                </div>
                                <div className="form-group">
                                    <label>Industry</label>
                                    <select
                                        id="onboarding-industry"
                                        value={industry}
                                        onChange={(e) => setIndustry(e.target.value)}
                                    >
                                        <option value="">Select your industry…</option>
                                        <option value="technology">Technology</option>
                                        <option value="real_estate">Real Estate</option>
                                        <option value="healthcare">Healthcare</option>
                                        <option value="education">Education</option>
                                        <option value="finance">Finance & Banking</option>
                                        <option value="ecommerce">E-Commerce</option>
                                        <option value="consulting">Consulting</option>
                                        <option value="marketing">Marketing & Advertising</option>
                                        <option value="other">Other</option>
                                    </select>
                                </div>
                            </>
                        )}

                        {/* Feature lists for other steps */}
                        {step.features && (
                            <div className="feature-list">
                                {step.features.map((f, i) => (
                                    <div key={i} className={`feature-item ${isCompleted ? 'completed' : ''}`}>
                                        <div className="feature-icon">{f.icon}</div>
                                        <div className="feature-text">
                                            <strong>{f.name}</strong>
                                            <span>{f.desc}</span>
                                        </div>
                                        {isCompleted && <span className="feature-check">✓</span>}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Navigation */}
                    <div className="step-nav">
                        <span className="step-counter">
                            Step {currentStep + 1} of {STEPS.length}
                        </span>
                        <div className="step-nav-buttons">
                            {currentStep > 0 && (
                                <button
                                    className="btn-step secondary"
                                    onClick={() => setCurrentStep(currentStep - 1)}
                                >
                                    ← Back
                                </button>
                            )}
                            {(step as any).skippable && (
                                <button
                                    className="btn-step secondary"
                                    onClick={handleCompleteStep}
                                >
                                    Skip
                                </button>
                            )}
                            <button
                                id="onboarding-next-btn"
                                className="btn-step primary"
                                onClick={handleCompleteStep}
                                disabled={saving}
                            >
                                {saving ? 'Saving…' :
                                    currentStep === STEPS.length - 1 ? 'Get Started →' : 'Continue →'}
                            </button>
                        </div>
                    </div>
                </div>

                {/* Skip onboarding entirely */}
                <div style={{ textAlign: 'center', marginTop: 'var(--spacing-4)' }}>
                    <button className="btn-skip" onClick={handleSkipOnboarding}>
                        I'll set this up later — skip to dashboard
                    </button>
                </div>
            </div>
        </div>
    );
};

export default OnboardingWizard;
