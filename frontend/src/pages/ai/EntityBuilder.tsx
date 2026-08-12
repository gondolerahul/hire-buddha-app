import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { JellyButton } from '@/components/ui';
import { X, Layers } from 'lucide-react';
import { apiClient } from '@/services/api.client';
import { useAuth } from '@/hooks/useAuth';
import { HierarchicalEntity } from '@/types';
import { EntityConfigurationTabs } from './EntityConfigurationTabs';
import './EntityBuilder.css';

export const EntityBuilder: React.FC = () => {
    const { id } = useParams();
    const navigate = useNavigate();
    const { user } = useAuth();
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [entity, setEntity] = useState<HierarchicalEntity | undefined>(undefined);
    const [targetCompanyId, setTargetCompanyId] = useState<string | null>(null);

    useEffect(() => {
        if (id) {
            fetchEntity();
        }
    }, [id]);

    const fetchEntity = async () => {
        try {
            setLoading(true);
            const { data } = await apiClient.get<HierarchicalEntity>(`/ai/entities/${id}`);
            setEntity(data);
        } catch (error) {
            console.error('Failed to fetch entity:', error);
            setError('Failed to load entity');
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async (entityData: any) => {
        setLoading(true);
        setError('');

        try {
            if (id) {
                await apiClient.put(`/ai/entities/${id}`, entityData);
            } else {
                // Pass target_company_id as query parameter for new entities
                const params = targetCompanyId ? `?target_company_id=${targetCompanyId}` : '';
                await apiClient.post(`/ai/entities${params}`, entityData);
            }
            navigate('/ai/entities');
        } catch (err: any) {
            const detail = err.response?.data?.detail;
            // Handle Pydantic validation errors which are arrays of {type, loc, msg, input}
            if (Array.isArray(detail)) {
                const messages = detail.map((e: any) => {
                    const location = e.loc?.join(' → ') || '';
                    return location ? `${location}: ${e.msg}` : e.msg;
                });
                setError(messages.join('; '));
            } else if (typeof detail === 'string') {
                setError(detail);
            } else if (detail && typeof detail === 'object' && detail.msg) {
                setError(detail.msg);
            } else {
                setError('Failed to save entity');
            }
        } finally {
            setLoading(false);
        }
    };

    const handleCancel = () => {
        navigate('/ai/entities');
    };

    return (
        <div className="entity-builder">
            <div className="builder-header">
                <div className="title-section">
                    <div className="breadcrumb">AI Core / {id ? 'Modify Interface' : 'Architect Interface'}</div>
                    <div className="flex items-center gap-4">
                        <div className="p-3 bg-white/5 rounded-2xl border border-white/10">
                            <Layers className="text-accent-primary" size={28} />
                        </div>
                        <h1>{entity?.display_name || entity?.name || 'New Neural Core'}</h1>
                    </div>
                </div>

                <div className="header-actions">
                    <JellyButton variant="ghost" className="hover:bg-red-500/10 hover:text-red-400 p-4 border border-white/5 rounded-2xl" onClick={handleCancel}>
                        <X size={24} />
                    </JellyButton>
                </div>
            </div>

            <div className="builder-main">
                {loading && !entity ? (
                    <div className="loading-state glass">
                        <div className="spinner"></div>
                        <p>Loading Entity...</p>
                    </div>
                ) : (
                    <EntityConfigurationTabs
                        entity={entity}
                        onSave={handleSave}
                        onCancel={handleCancel}
                        userRole={user?.role}
                        userCompanyId={user?.company_id}
                        onCompanyChange={setTargetCompanyId}
                    />
                )}
            </div>

            {error && <div className="error-toast glass">{error}</div>}
        </div>
    );
};
