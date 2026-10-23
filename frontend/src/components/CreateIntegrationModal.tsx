import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import { GlassCard } from './ui/GlassCard';
import { GlassInput } from './ui/GlassInput';
import { JellyButton } from './ui/JellyButton';
import { integrationService, Model, Integration, CostUnitOption } from '../services/integration.service';
import { User } from '../types';
import { currencyService } from '../services/currency.service';
import { formatMoney } from '../utils/money';

interface CreateIntegrationModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSubmit: (data: any) => Promise<void>;
    currentUser: User | null;
    editingIntegration?: Integration | null;
    userRole?: string;
}

const COMPONENT_TYPES = [
    { id: 'input_token', name: 'Input Token' },
    { id: 'output_token', name: 'Output Token' },
    { id: 'analysis', name: 'Analysis' },
    { id: 'minute', name: 'Minute' },
    { id: 'character', name: 'Character' },
    { id: 'flat_fee', name: 'Flat Fee' },
    { id: 'image', name: 'Per Image' },
    { id: 'per_second', name: 'Per Second (Video, Speech)' },
    { id: 'clip', name: 'Per Clip (Music)' }
];

// ServiceCategory in backend/src/config/models.py — the API refuses anything else (LP-11).
const SERVICE_CATEGORIES = [
    { id: 'LLM', name: 'LLM (AI Model)' },
    { id: 'LLM_LIVE', name: 'Live Voice Model' },
    { id: 'EMBEDDING', name: 'Embedding' },
    { id: 'COMMUNICATION', name: 'Communication (Twilio/Exotel)' },
    { id: 'API_TOOL', name: 'API Tool (Apollo/Clay/Zapier)' },
    { id: 'IMAGE_GENERATION', name: 'Image Generation' },
    { id: 'VIDEO_GENERATION', name: 'Video Generation' },
    { id: 'SPEECH_GENERATION', name: 'Speech Generation (Text to Speech)' },
    { id: 'MUSIC_GENERATION', name: 'Music Generation' },
    { id: 'SANDBOX', name: 'Sandbox Time' },
    { id: 'EMAIL', name: 'Email (IMAP/SMTP)' },
    { id: 'SOCIAL_MEDIA', name: 'Social Media (WhatsApp/Instagram)' },
    { id: 'OTHER', name: 'Other' }
];

// Providers that authenticate with Google Application Default Credentials and
// store no key (ADC_PROVIDERS in backend/src/config/models.py, LP-12).
const ADC_PROVIDERS = new Set(['google', 'gemini', 'google_vertex', 'anthropic', 'anthropic_vertex']);

// Categories that tenant users are allowed to manage
const TENANT_ALLOWED_CATEGORY_IDS = new Set(['EMAIL', 'SOCIAL_MEDIA', 'API_TOOL', 'OTHER']);

export const CreateIntegrationModal: React.FC<CreateIntegrationModalProps> = ({
    isOpen,
    onClose,
    onSubmit,
    currentUser,
    editingIntegration,
    userRole
}) => {
    const isTenantUser = userRole === 'tenant_admin' || userRole === 'tenant_user';
    const availableCategories = isTenantUser
        ? SERVICE_CATEGORIES.filter(c => TENANT_ALLOWED_CATEGORY_IDS.has(c.id))
        : SERVICE_CATEGORIES;
    const [models, setModels] = useState<Model[]>([]);
    // The enumerated units (Phase 15 T1-7): a price is per one of these, never free text.
    const [costUnits, setCostUnits] = useState<CostUnitOption[]>([]);
    // Today's INR rate, for the ₹ preview (staff can read rates; others see USD only).
    const [inrPerUsd, setInrPerUsd] = useState<number | null>(null);
    const [formData, setFormData] = useState({
        provider_name: '',
        model_name: '',
        service_sku: '',
        service_category: 'LLM',
        component_type: 'input_token',
        internal_cost: 0,
        cost_unit_code: 'PER_1M_TOKENS',
        api_key: '',
        status: 'active',
        service_metadata: {} as Record<string, any>
    });
    const [metadataJson, setMetadataJson] = useState('{}');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchModels = async () => {
            try {
                const data = await integrationService.getModels();
                setModels(data);
            } catch (err) {
                console.error('Failed to fetch models', err);
            }
        };
        if (isOpen) {
            fetchModels();
            integrationService.getCostUnits().then(setCostUnits).catch(() => setCostUnits([]));
            currencyService.listCurrencies()
                .then(rows => setInrPerUsd(rows.find(c => c.code === 'INR')?.current_rate?.units_per_usd ?? null))
                .catch(() => setInrPerUsd(null));
        }
    }, [isOpen]);

    useEffect(() => {
        if (editingIntegration) {
            setFormData({
                provider_name: editingIntegration.provider_name,
                model_name: editingIntegration.model_name || '',
                service_sku: editingIntegration.service_sku,
                service_category: editingIntegration.service_category || 'LLM',
                component_type: editingIntegration.component_type,
                internal_cost: editingIntegration.internal_cost,
                cost_unit_code: editingIntegration.cost_unit_code,
                api_key: '', // Don't show existing key
                status: editingIntegration.status,
                service_metadata: editingIntegration.service_metadata || {}
            });
            setMetadataJson(JSON.stringify(editingIntegration.service_metadata || {}, null, 2));
        } else {
            setFormData({
                provider_name: '',
                model_name: '',
                service_sku: '',
                service_category: 'LLM',
                component_type: 'input_token',
                internal_cost: 0,
                cost_unit_code: 'PER_1M_TOKENS',
                api_key: '',
                status: 'active',
                service_metadata: {}
            });
            setMetadataJson('{}');
        }
    }, [editingIntegration, isOpen]);

    if (!isOpen) return null;

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        setLoading(true);

        try {
            let metadata = formData.service_metadata;

            // If the provider isn't twilio, try to parse the JSON field
            if (formData.provider_name.toLowerCase() !== 'twilio') {
                try {
                    metadata = JSON.parse(metadataJson);
                } catch (e) {
                    throw new Error('Invalid Metadata JSON format');
                }
            }

            const payload = {
                ...formData,
                service_metadata: metadata,
                company_id: currentUser?.company_id,
                internal_cost: Number(formData.internal_cost)
            };

            // An empty key is not sent: an edit keeps the stored one, and an ADC
            // provider stores none.
            if (!formData.api_key) {
                delete (payload as any).api_key;
            }

            await onSubmit(payload);
            onClose();
        } catch (err: any) {
            setError(err.message || err.response?.data?.detail || 'Failed to save integration');
        } finally {
            setLoading(false);
        }
    };

    const handleModelChange = (modelKey: string) => {
        const model = models.find(m => m.model_key === modelKey);
        if (model) {
            setFormData({
                ...formData,
                model_name: model.model_key,
                provider_name: model.provider,
                service_sku: `${model.model_key}-${formData.component_type === 'input_token' ? 'in' : 'out'}`
            });
        }
    };

    const selectedUnit = costUnits.find(u => u.code === formData.cost_unit_code);
    const isTwilio = formData.provider_name.toLowerCase() === 'twilio';
    const usesAdc = ADC_PROVIDERS.has(formData.provider_name.toLowerCase());

    return (
        <div className="modal-overlay">
            <GlassCard className="w-full max-w-2xl p-8 relative max-h-90vh overflow-y-auto">
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 p-2 text-gray-400 hover:text-white transition-colors"
                >
                    <X size={20} />
                </button>

                <h2 className="text-2xl font-bold text-white mb-6">
                    {editingIntegration ? 'Edit Integration' : 'Add New Integration'}
                </h2>

                <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-6">
                    <div className="col-span-1">
                        <label className="block text-sm font-medium text-gray-300 mb-2">Model Template (Optional)</label>
                        <select
                            onChange={(e) => handleModelChange(e.target.value)}
                            value={formData.model_name}
                            className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-rose-500/50 transition-all"
                        >
                            <option value="" className="bg-gray-900">Custom / Select Model...</option>
                            {models.map(m => (
                                <option key={m.model_key} value={m.model_key} className="bg-gray-900">
                                    {m.model_name} ({m.provider})
                                </option>
                            ))}
                        </select>
                    </div>

                    <div className="col-span-1">
                        <label className="block text-sm font-medium text-gray-300 mb-2">Service Category</label>
                        <select
                            value={formData.service_category}
                            onChange={(e) => setFormData({ ...formData, service_category: e.target.value })}
                            className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-rose-500/50 transition-all"
                            required
                        >
                            {availableCategories.map(c => (
                                <option key={c.id} value={c.id} className="bg-gray-900">{c.name}</option>
                            ))}
                        </select>
                    </div>

                    <GlassInput
                        label="Provider Name"
                        value={formData.provider_name}
                        onChange={(e) => setFormData({ ...formData, provider_name: e.target.value })}
                        required
                    />

                    <GlassInput
                        label="Model Name"
                        value={formData.model_name}
                        onChange={(e) => setFormData({ ...formData, model_name: e.target.value })}
                        placeholder="e.g. gemini-1.5-pro"
                    />

                    <GlassInput
                        label="Service SKU (Unique)"
                        value={formData.service_sku}
                        onChange={(e) => setFormData({ ...formData, service_sku: e.target.value })}
                        required
                        placeholder="e.g. gpt-4o-in"
                    />

                    <div className="col-span-1">
                        <label className="block text-sm font-medium text-gray-300 mb-2">Component Type</label>
                        <select
                            value={formData.component_type}
                            onChange={(e) => setFormData({ ...formData, component_type: e.target.value })}
                            className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-rose-500/50 transition-all"
                            required
                        >
                            {COMPONENT_TYPES.map(t => (
                                <option key={t.id} value={t.id} className="bg-gray-900">{t.name}</option>
                            ))}
                        </select>
                    </div>

                    <GlassInput
                        label="Internal Cost"
                        type="number"
                        step="any"
                        value={formData.internal_cost.toString()}
                        onChange={(e) => setFormData({ ...formData, internal_cost: parseFloat(e.target.value) })}
                        required
                    />

                    <div className="col-span-1">
                        <label className="block text-sm font-medium text-gray-300 mb-2">Cost Unit</label>
                        <select
                            value={formData.cost_unit_code}
                            onChange={(e) => setFormData({ ...formData, cost_unit_code: e.target.value })}
                            className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-rose-500/50 transition-all"
                            required
                        >
                            {costUnits.length === 0 && (
                                <option value={formData.cost_unit_code} className="bg-gray-900">{formData.cost_unit_code}</option>
                            )}
                            {costUnits.map(u => (
                                <option key={u.code} value={u.code} className="bg-gray-900">{u.label}</option>
                            ))}
                        </select>
                        {selectedUnit && Number(formData.internal_cost) > 0 && (
                            <p className="text-xs text-gray-400 mt-1">
                                = ${(Number(formData.internal_cost) / selectedUnit.per_quantity).toPrecision(4)} per {selectedUnit.dimension.replace('_', '-')}
                                {inrPerUsd != null && (
                                    <> · {formatMoney(Number(formData.internal_cost) * inrPerUsd, 'INR')} {selectedUnit.label} at today's rate</>
                                )}
                            </p>
                        )}
                    </div>

                    <div className="col-span-2">
                        <GlassInput
                            label={editingIntegration ? "API Key / Auth Token (Leave blank to keep current)"
                                : usesAdc ? "API Key (not needed: Vertex AI uses the service account)" : "API Key / Auth Token"}
                            type="password"
                            value={formData.api_key}
                            onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                            required={!editingIntegration && !usesAdc}
                        />
                    </div>

                    {isTwilio ? (
                        <div className="col-span-2">
                            <GlassInput
                                label="Twilio Account SID"
                                value={formData.service_metadata.account_sid || ''}
                                onChange={(e) => setFormData({
                                    ...formData,
                                    service_metadata: { ...formData.service_metadata, account_sid: e.target.value }
                                })}
                                required
                                placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                            />
                        </div>
                    ) : (
                        <div className="col-span-2">
                            <label className="block text-sm font-medium text-gray-300 mb-2">Service Metadata (JSON)</label>
                            <div className="bg-white/5 border border-white/10 rounded-lg overflow-hidden focus-within:ring-2 focus-within:ring-rose-500/50 transition-all">
                                <textarea
                                    value={metadataJson}
                                    onChange={(e) => setMetadataJson(e.target.value)}
                                    className="w-full bg-transparent p-4 text-white focus:outline-none h-32 font-mono text-sm border-none resize-none"
                                    placeholder='{ "key": "value" }'
                                />
                            </div>
                            <p className="text-[10px] text-gray-500 mt-1 uppercase tracking-wider">Configure additional provider settings as JSON</p>
                        </div>
                    )}

                    {error && (
                        <p className="col-span-2 text-red-400 text-sm bg-red-400/10 p-3 rounded-lg border border-red-400/20">
                            {error}
                        </p>
                    )}

                    <div className="col-span-2 flex justify-end gap-4 pt-6 mt-2 border-t border-white/5">
                        <JellyButton
                            variant="ghost"
                            onClick={onClose}
                        >
                            Cancel
                        </JellyButton>
                        <JellyButton
                            type="submit"
                            roseGold
                            disabled={loading}
                        >
                            {loading ? 'Saving...' : (editingIntegration ? 'Update Integration' : 'Create Integration')}
                        </JellyButton>
                    </div>
                </form>
            </GlassCard>
        </div >
    );
};
