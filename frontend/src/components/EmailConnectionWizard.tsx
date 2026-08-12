import React, { useState, useEffect } from 'react';
import { X, Mail, Key, CheckCircle, AlertCircle, Loader2, ExternalLink } from 'lucide-react';
import { GlassCard } from './ui/GlassCard';
import { GlassInput } from './ui/GlassInput';
import { JellyButton } from './ui/JellyButton';
import { emailService, EmailConnection, ProviderDefaults } from '../services/email.service';

interface EmailConnectionWizardProps {
    isOpen: boolean;
    onClose: () => void;
    companyId: string;
    onConnectionCreated?: (connection: EmailConnection) => void;
}

type WizardStep = 'provider' | 'credentials' | 'validate' | 'complete';

const PROVIDERS = [
    { id: 'gmail', name: 'Gmail', icon: '📧', helpUrl: 'https://myaccount.google.com/apppasswords' },
    { id: 'outlook', name: 'Outlook / Office 365', icon: '📨', helpUrl: 'https://support.microsoft.com/en-us/account-billing/manage-app-passwords-for-two-step-verification' },
    { id: 'custom', name: 'Custom IMAP/SMTP', icon: '⚙️', helpUrl: '' }
];

export const EmailConnectionWizard: React.FC<EmailConnectionWizardProps> = ({
    isOpen,
    onClose,
    companyId,
    onConnectionCreated
}) => {
    const [step, setStep] = useState<WizardStep>('provider');
    const [selectedProvider, setSelectedProvider] = useState<string>('gmail');
    const [providerDefaults, setProviderDefaults] = useState<ProviderDefaults>({});
    const [formData, setFormData] = useState({
        email_address: '',
        app_password: '',
        imap_host: 'imap.gmail.com',
        imap_port: 993,
        smtp_host: 'smtp.gmail.com',
        smtp_port: 587
    });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [validationResult, setValidationResult] = useState<{ valid: boolean; message: string } | null>(null);
    const [createdConnection, setCreatedConnection] = useState<EmailConnection | null>(null);

    useEffect(() => {
        if (isOpen) {
            emailService.getProviderDefaults().then(setProviderDefaults).catch(console.error);
            // Reset state
            setStep('provider');
            setSelectedProvider('gmail');
            setError(null);
            setValidationResult(null);
            setCreatedConnection(null);
        }
    }, [isOpen]);

    useEffect(() => {
        // Update IMAP/SMTP settings when provider changes
        const defaults = providerDefaults[selectedProvider];
        if (defaults) {
            setFormData(prev => ({
                ...prev,
                imap_host: defaults.imap_host,
                imap_port: defaults.imap_port,
                smtp_host: defaults.smtp_host,
                smtp_port: defaults.smtp_port
            }));
        }
    }, [selectedProvider, providerDefaults]);

    if (!isOpen) return null;

    const handleProviderSelect = (providerId: string) => {
        setSelectedProvider(providerId);
        setStep('credentials');
    };

    const handleCreateConnection = async () => {
        setError(null);
        setLoading(true);

        try {
            const connection = await emailService.createConnection({
                ...formData,
                provider_type: selectedProvider,
                company_id: companyId
            });
            setCreatedConnection(connection);
            setStep('validate');
        } catch (err: any) {
            setError(err.response?.data?.detail || err.message || 'Failed to create connection');
        } finally {
            setLoading(false);
        }
    };

    const handleValidate = async () => {
        if (!createdConnection) return;
        setLoading(true);
        setError(null);

        try {
            const result = await emailService.validateConnection(createdConnection.id);
            setValidationResult(result);
            if (result.valid) {
                setStep('complete');
                onConnectionCreated?.(createdConnection);
            }
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Validation failed');
        } finally {
            setLoading(false);
        }
    };

    const selectedProviderInfo = PROVIDERS.find(p => p.id === selectedProvider);

    return (
        <div className="modal-overlay">
            <GlassCard className="w-full max-w-lg p-8 relative">
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 p-2 text-gray-400 hover:text-white transition-colors"
                >
                    <X size={20} />
                </button>

                <div className="flex items-center gap-3 mb-6">
                    <Mail className="text-rose-400" size={24} />
                    <h2 className="text-2xl font-bold text-white">Connect Email Account</h2>
                </div>

                {/* Progress indicator */}
                <div className="flex items-center gap-2 mb-8">
                    {['provider', 'credentials', 'validate', 'complete'].map((s, i) => (
                        <React.Fragment key={s}>
                            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all ${step === s ? 'bg-rose-500 text-white scale-110' :
                                    ['provider', 'credentials', 'validate', 'complete'].indexOf(step) > i
                                        ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                                        : 'bg-white/5 text-gray-500 border border-white/10'
                                }`}>
                                {['provider', 'credentials', 'validate', 'complete'].indexOf(step) > i ? '✓' : i + 1}
                            </div>
                            {i < 3 && <div className={`flex-1 h-0.5 ${['provider', 'credentials', 'validate', 'complete'].indexOf(step) > i ? 'bg-green-500/30' : 'bg-white/5'
                                }`} />}
                        </React.Fragment>
                    ))}
                </div>

                {/* Step 1: Provider Selection */}
                {step === 'provider' && (
                    <div className="space-y-4">
                        <p className="text-gray-400 text-sm mb-4">Select your email provider:</p>
                        {PROVIDERS.map(provider => (
                            <button
                                key={provider.id}
                                onClick={() => handleProviderSelect(provider.id)}
                                className="w-full flex items-center gap-4 p-4 bg-white/5 border border-white/10 rounded-xl hover:bg-white/10 hover:border-rose-500/30 transition-all text-left group"
                            >
                                <span className="text-2xl">{provider.icon}</span>
                                <div>
                                    <p className="text-white font-medium group-hover:text-rose-300 transition-colors">{provider.name}</p>
                                    <p className="text-gray-500 text-xs">App Password authentication</p>
                                </div>
                            </button>
                        ))}
                    </div>
                )}

                {/* Step 2: Credentials */}
                {step === 'credentials' && (
                    <div className="space-y-4">
                        <div className="flex items-center justify-between mb-2">
                            <p className="text-gray-400 text-sm">Enter your credentials for {selectedProviderInfo?.name}:</p>
                            {selectedProviderInfo?.helpUrl && (
                                <a
                                    href={selectedProviderInfo.helpUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="flex items-center gap-1 text-xs text-rose-400 hover:text-rose-300 transition-colors"
                                >
                                    <ExternalLink size={12} />
                                    Get App Password
                                </a>
                            )}
                        </div>

                        <GlassInput
                            label="Email Address"
                            type="email"
                            value={formData.email_address}
                            onChange={(e) => setFormData({ ...formData, email_address: e.target.value })}
                            placeholder="user@gmail.com"
                            required
                        />

                        <div>
                            <GlassInput
                                label="App Password"
                                type="password"
                                value={formData.app_password}
                                onChange={(e) => setFormData({ ...formData, app_password: e.target.value })}
                                placeholder="xxxx xxxx xxxx xxxx"
                                required
                            />
                            <p className="text-[10px] text-gray-500 mt-1 uppercase tracking-wider">
                                <Key size={10} className="inline mr-1" />
                                Use an App Password, not your regular password
                            </p>
                        </div>

                        {selectedProvider === 'custom' && (
                            <div className="grid grid-cols-2 gap-4 pt-2 border-t border-white/5">
                                <GlassInput
                                    label="IMAP Host"
                                    value={formData.imap_host}
                                    onChange={(e) => setFormData({ ...formData, imap_host: e.target.value })}
                                    required
                                />
                                <GlassInput
                                    label="IMAP Port"
                                    type="number"
                                    value={formData.imap_port.toString()}
                                    onChange={(e) => setFormData({ ...formData, imap_port: parseInt(e.target.value) })}
                                    required
                                />
                                <GlassInput
                                    label="SMTP Host"
                                    value={formData.smtp_host}
                                    onChange={(e) => setFormData({ ...formData, smtp_host: e.target.value })}
                                    required
                                />
                                <GlassInput
                                    label="SMTP Port"
                                    type="number"
                                    value={formData.smtp_port.toString()}
                                    onChange={(e) => setFormData({ ...formData, smtp_port: parseInt(e.target.value) })}
                                    required
                                />
                            </div>
                        )}

                        {error && (
                            <p className="text-red-400 text-sm bg-red-400/10 p-3 rounded-lg border border-red-400/20">
                                {error}
                            </p>
                        )}

                        <div className="flex justify-between pt-4">
                            <JellyButton variant="ghost" onClick={() => setStep('provider')}>
                                Back
                            </JellyButton>
                            <JellyButton
                                roseGold
                                onClick={handleCreateConnection}
                                disabled={loading || !formData.email_address || !formData.app_password}
                            >
                                {loading ? <><Loader2 size={16} className="animate-spin mr-2" /> Connecting...</> : 'Connect'}
                            </JellyButton>
                        </div>
                    </div>
                )}

                {/* Step 3: Validate */}
                {step === 'validate' && (
                    <div className="space-y-4 text-center">
                        <div className="w-16 h-16 bg-amber-500/10 rounded-full flex items-center justify-center mx-auto">
                            <AlertCircle className="text-amber-400" size={32} />
                        </div>
                        <h3 className="text-lg font-semibold text-white">Validate Connection</h3>
                        <p className="text-gray-400 text-sm">
                            Click below to test the IMAP connection to <strong className="text-white">{formData.email_address}</strong>
                        </p>

                        {validationResult && !validationResult.valid && (
                            <div className="bg-red-400/10 border border-red-400/20 rounded-lg p-3 text-sm text-red-400">
                                {validationResult.message}
                            </div>
                        )}

                        {error && (
                            <p className="text-red-400 text-sm bg-red-400/10 p-3 rounded-lg border border-red-400/20">
                                {error}
                            </p>
                        )}

                        <div className="flex justify-center gap-4 pt-4">
                            <JellyButton variant="ghost" onClick={onClose}>
                                Skip for Now
                            </JellyButton>
                            <JellyButton
                                roseGold
                                onClick={handleValidate}
                                disabled={loading}
                            >
                                {loading ? <><Loader2 size={16} className="animate-spin mr-2" /> Validating...</> : 'Validate Connection'}
                            </JellyButton>
                        </div>
                    </div>
                )}

                {/* Step 4: Complete */}
                {step === 'complete' && (
                    <div className="space-y-4 text-center">
                        <div className="w-16 h-16 bg-green-500/10 rounded-full flex items-center justify-center mx-auto">
                            <CheckCircle className="text-green-400" size={32} />
                        </div>
                        <h3 className="text-lg font-semibold text-white">Connection Successful!</h3>
                        <p className="text-gray-400 text-sm">
                            <strong className="text-white">{formData.email_address}</strong> is now connected.
                            Your AI agents can now read, classify, and draft emails.
                        </p>
                        <div className="pt-4">
                            <JellyButton roseGold onClick={onClose}>
                                Done
                            </JellyButton>
                        </div>
                    </div>
                )}
            </GlassCard>
        </div>
    );
};
