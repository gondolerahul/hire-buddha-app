import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import { GlassCard, GlassInput, JellyButton } from './ui';

import { Company } from '../types';

interface CreateCompanyModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSubmit: (id: string | undefined, data: any) => Promise<void>;
    type: 'PARTNER' | 'TENANT';
    parentId?: string;
    initialData?: Company;
}

export const CreateCompanyModal: React.FC<CreateCompanyModalProps> = ({
    isOpen,
    onClose,
    onSubmit,
    type,
    parentId,
    initialData
}) => {
    const [name, setName] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (isOpen) {
            setName(initialData?.name || '');
            setError(null);
        }
    }, [isOpen, initialData]);

    if (!isOpen) return null;

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        setLoading(true);

        try {
            await onSubmit(initialData?.id, {
                name,
                type: initialData?.type || type,
                parent_id: initialData?.parent_id || parentId
            });
            setName('');
            onClose();
        } catch (err: any) {
            setError(err.response?.data?.detail || `Failed to ${initialData ? 'update' : 'create'} company`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="modal-overlay">
            <GlassCard className="w-full max-w-md p-8 relative">
                <button
                    onClick={onClose}
                    className="absolute top-6 right-6 p-2 text-tertiary hover:text-white transition-colors"
                >
                    <X size={20} />
                </button>

                <h2 className="text-xl font-bold text-white mb-8">
                    {initialData ? 'Update' : 'Add'} {type.charAt(0) + type.slice(1).toLowerCase()}
                </h2>

                <form onSubmit={handleSubmit} className="space-y-8">
                    <GlassInput
                        label="Company Name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder={`e.g. ${type === 'PARTNER' ? 'Global Logic' : 'Business Unit A'}`}
                        required
                    />

                    {error && (
                        <div className="error-toast glass">
                            {error}
                        </div>
                    )}

                    <div className="flex justify-end gap-4 pt-4">
                        <JellyButton
                            type="button"
                            onClick={onClose}
                            variant="ghost"
                        >
                            Cancel
                        </JellyButton>
                        <JellyButton
                            type="submit"
                            disabled={loading || !name.trim()}
                            roseGold
                        >
                            {loading ? 'Synthesizing...' : (initialData ? 'Update Entity' : 'Establish Entity')}
                        </JellyButton>
                    </div>
                </form>
            </GlassCard>
        </div>
    );
};
