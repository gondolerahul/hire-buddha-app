import React, { useState, useEffect } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { JellyButton } from '@/components/ui';
import { X, Upload, CheckCircle, AlertCircle } from 'lucide-react';
import { apiClient } from '@/services/api.client';
import { HierarchicalEntity, EntityType } from '@/types';
import './CampaignCreateModal.css';

interface CampaignCreateModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

export const CampaignCreateModal: React.FC<CampaignCreateModalProps> = ({ isOpen, onClose, onSuccess }) => {
    const { token } = useAuth();
    const [agents, setAgents] = useState<HierarchicalEntity[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [step, setStep] = useState(1); // 1: Details, 2: Contacts

    // Form data
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [agentId, setAgentId] = useState('');
    const [provider, setProvider] = useState('tata_tele');
    const [contacts, setContacts] = useState<any[]>([]);
    const [csvFile, setCsvFile] = useState<File | null>(null);
    const [uploadResults, setUploadResults] = useState<any>(null);

    useEffect(() => {
        if (isOpen) {
            fetchAgents();
            // Reset form
            setStep(1);
            setName('');
            setDescription('');
            setAgentId('');
            setContacts([]);
            setCsvFile(null);
            setUploadResults(null);
            setProvider('tata_tele');
            setError('');
        }
    }, [isOpen]);

    const fetchAgents = async () => {
        try {
            const { data } = await apiClient.get('/ai/entities');
            const filteredAgents = data.filter((e: HierarchicalEntity) => e.type === EntityType.AGENT);
            setAgents(filteredAgents);
        } catch (err) {
            console.error('Error fetching agents:', err);
        }
    };

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        if (!token) {
            setError('Authentication token not found. Please log in again.');
            return;
        }

        setCsvFile(file);
        setLoading(true);
        setError('');

        const formData = new FormData();
        formData.append('file', file);

        try {
            console.log('Uploading CSV with token:', token ? 'Token exists' : 'No token');
            const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/campaigns/upload-csv`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`
                },
                body: formData
            });

            console.log('Upload response status:', response.status);

            if (!response.ok) {
                const errorText = await response.text();
                console.error('Upload error:', errorText);
                throw new Error(`Failed to upload CSV (${response.status}): ${errorText}`);
            }

            const data = await response.json();
            setUploadResults(data);
            setContacts(data.all_contacts || []);
        } catch (err: any) {
            console.error('CSV upload error:', err);
            setError(err.message || 'Error processing CSV');
            setCsvFile(null);
        } finally {
            setLoading(false);
        }
    };

    const handleCreate = async () => {
        if (!name || !agentId || contacts.length === 0) {
            setError('Please fill in all required fields and upload contacts');
            return;
        }

        setLoading(true);
        setError('');

        try {
            const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/campaigns`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    name,
                    description,
                    agent_id: agentId,
                    provider,
                    contact_list: contacts
                })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Failed to create campaign');
            }

            onSuccess();
            onClose();
        } catch (err: any) {
            setError(err.message || 'Error creating campaign');
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal-content campaign-create-modal" onClick={e => e.stopPropagation()}>
                <div className="modal-header">
                    <h2>Launch New Voice Campaign</h2>
                    <button className="close-btn" onClick={onClose}><X size={20} /></button>
                </div>

                <div className="step-indicator">
                    <div className={`step-dot ${step >= 1 ? 'active' : ''}`}>1</div>
                    <div className="step-line"></div>
                    <div className={`step-dot ${step >= 2 ? 'active' : ''}`}>2</div>
                </div>

                {error && (
                    <div className="error-message">
                        <AlertCircle size={16} />
                        {error}
                    </div>
                )}

                {step === 1 ? (
                    <div className="step-content">
                        <div className="form-group">
                            <label>Campaign Name *</label>
                            <input
                                type="text"
                                value={name}
                                onChange={e => setName(e.target.value)}
                                placeholder="E.g., Q1 Sales Outreach"
                                className="glass-input"
                            />
                        </div>

                        <div className="form-group">
                            <label>Description</label>
                            <textarea
                                value={description}
                                onChange={e => setDescription(e.target.value)}
                                placeholder="Describe the goal of this campaign..."
                                className="glass-input"
                            />
                        </div>

                        <div className="form-row">
                            <div className="form-group">
                                <label>AI Agent *</label>
                                <select
                                    value={agentId}
                                    onChange={e => setAgentId(e.target.value)}
                                    className="glass-input"
                                >
                                    <option value="">Select an Agent</option>
                                    {agents.map(agent => (
                                        <option key={agent.id} value={agent.id}>
                                            {agent.display_name || agent.name}
                                        </option>
                                    ))}
                                </select>
                            </div>

                            <div className="form-group">
                                <label>Provider</label>
                                <select
                                    value={provider}
                                    onChange={e => setProvider(e.target.value)}
                                    className="glass-input"
                                >
                                    <option value="tata_tele">Tata Tele (India)</option>
                                    <option value="twilio">Twilio (US/Global)</option>
                                </select>
                            </div>
                        </div>

                        <div className="modal-footer">
                            <JellyButton variant="secondary" onClick={onClose}>Cancel</JellyButton>
                            <JellyButton
                                variant="primary"
                                onClick={() => setStep(2)}
                                disabled={!name || !agentId}
                            >
                                Next: Contacts
                            </JellyButton>
                        </div>
                    </div>
                ) : (
                    <div className="step-content">
                        <div className="upload-section">
                            <label className="upload-dropzone">
                                <input
                                    type="file"
                                    accept=".csv"
                                    onChange={handleFileUpload}
                                    style={{ display: 'none' }}
                                />
                                <div className="upload-ui">
                                    <Upload size={48} className={loading ? 'pulse' : ''} />
                                    <h3>{csvFile ? csvFile.name : 'Upload Contact List (CSV)'}</h3>
                                    <p>CSV must contain at least a 'phone' column</p>
                                </div>
                            </label>
                        </div>

                        {uploadResults && (
                            <div className="upload-summary">
                                <div className="summary-item">
                                    <CheckCircle size={16} className="success" />
                                    <span>{uploadResults.valid} Valid Contacts</span>
                                </div>
                                {uploadResults.invalid > 0 && (
                                    <div className="summary-item">
                                        <AlertCircle size={16} className="danger" />
                                        <span>{uploadResults.invalid} Invalid/Duplicate Rows</span>
                                    </div>
                                )}
                            </div>
                        )}

                        {uploadResults?.errors?.length > 0 && (
                            <div className="upload-errors glass">
                                <h4>Validation Errors:</h4>
                                <ul>
                                    {uploadResults.errors.slice(0, 5).map((err: any, idx: number) => (
                                        <li key={idx}>Row {err.row}: {err.error}</li>
                                    ))}
                                    {uploadResults.errors.length > 5 && <li>... and {uploadResults.errors.length - 5} more</li>}
                                </ul>
                            </div>
                        )}

                        <div className="modal-footer">
                            <JellyButton variant="secondary" onClick={() => setStep(1)}>Back</JellyButton>
                            <JellyButton
                                variant="primary"
                                onClick={handleCreate}
                                disabled={loading || contacts.length === 0}
                            >
                                {loading ? 'Launching...' : 'Initialize Campaign'}
                            </JellyButton>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
