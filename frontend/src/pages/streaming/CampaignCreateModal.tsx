import React, { useState, useEffect } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { JellyButton } from '@/components/ui';
import { X, Upload, CheckCircle, AlertCircle, Smartphone, Server } from 'lucide-react';
import { apiClient } from '@/services/api.client';
import { HierarchicalEntity, EntityType } from '@/types';
import './CampaignCreateModal.css';
import { API_BASE_URL } from '@/config/api';

interface CampaignCreateModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

type ExecutionMode = 'server_dialer' | 'mobile_conference';

interface UploadRowError {
    row: number;
    field: string;
    value: string;
    reason: string;
}

interface UploadReport {
    upload_id: string;
    file_type: string;
    total_rows: number;
    valid_rows: number;
    invalid_rows: number;
    duplicate_rows: number;
    columns: string[];
    errors: UploadRowError[];
}

interface CompanyUser {
    id: string;
    full_name: string;
    email: string;
    role: string;
    company_id: string;
}

const MOBILE_ROLES = ['tenant_admin', 'tenant_user'];

/** FastAPI errors are either {"detail": "text"} or {"detail": {"code", "message"}}. */
const errorMessage = async (response: Response, fallback: string) => {
    try {
        const body = await response.json();
        if (typeof body.detail === 'string') return body.detail;
        if (body.detail?.message) return body.detail.message;
    } catch {
        // non-JSON body
    }
    return `${fallback} (${response.status})`;
};

export const CampaignCreateModal: React.FC<CampaignCreateModalProps> = ({ isOpen, onClose, onSuccess }) => {
    const { token, user } = useAuth();
    const [agents, setAgents] = useState<HierarchicalEntity[]>([]);
    const [users, setUsers] = useState<CompanyUser[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [step, setStep] = useState(1); // 1: Details, 2: Contacts

    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [agentId, setAgentId] = useState('');
    const [provider, setProvider] = useState('tata_tele');
    const [mode, setMode] = useState<ExecutionMode>('server_dialer');
    const [assignees, setAssignees] = useState<string[]>([]);
    const [file, setFile] = useState<File | null>(null);
    const [report, setReport] = useState<UploadReport | null>(null);

    useEffect(() => {
        if (isOpen) {
            fetchAgents();
            fetchUsers();
            setStep(1);
            setName('');
            setDescription('');
            setAgentId('');
            setFile(null);
            setReport(null);
            setProvider('tata_tele');
            setMode('server_dialer');
            setAssignees([]);
            setError('');
        }
    }, [isOpen]);

    const fetchAgents = async () => {
        try {
            const { data } = await apiClient.get('/ai/entities');
            setAgents(data.filter((e: HierarchicalEntity) => e.type === EntityType.AGENT));
        } catch (err) {
            console.error('Error fetching agents:', err);
        }
    };

    const fetchUsers = async () => {
        try {
            const { data } = await apiClient.get('/users');
            setUsers((data as CompanyUser[]).filter(u => MOBILE_ROLES.includes(u.role)));
        } catch {
            setUsers([]); // tenant users can't list colleagues; the campaign is assigned to them
        }
    };

    const selectedAgent = agents.find(a => a.id === agentId);
    const assignableUsers = selectedAgent
        ? users.filter(u => u.company_id === selectedAgent.company_id)
        : users;

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const picked = e.target.files?.[0];
        if (!picked) return;
        if (!token) {
            setError('Authentication token not found. Please log in again.');
            return;
        }
        setFile(picked);
        setLoading(true);
        setError('');
        setReport(null);

        const formData = new FormData();
        formData.append('file', picked);
        try {
            const response = await fetch(`${API_BASE_URL}/campaigns/upload-contacts`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` },
                body: formData,
            });
            if (!response.ok) throw new Error(await errorMessage(response, 'Failed to upload contacts'));
            setReport(await response.json());
        } catch (err: any) {
            setError(err.message || 'Error processing file');
            setFile(null);
        } finally {
            setLoading(false);
        }
    };

    const handleCreate = async () => {
        if (!name || !agentId || !report || report.valid_rows === 0) {
            setError('Please fill in all required fields and upload contacts');
            return;
        }
        setLoading(true);
        setError('');
        try {
            const body: Record<string, unknown> = {
                name,
                description,
                agent_id: agentId,
                provider,
                contact_upload_id: report.upload_id,
                execution_mode: mode,
            };
            if (mode === 'mobile_conference' && assignees.length > 0) body.assignee_user_ids = assignees;
            const response = await fetch(`${API_BASE_URL}/campaigns`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!response.ok) throw new Error(await errorMessage(response, 'Failed to create campaign'));
            onSuccess();
            onClose();
        } catch (err: any) {
            setError(err.message || 'Error creating campaign');
        } finally {
            setLoading(false);
        }
    };

    const toggleAssignee = (id: string) =>
        setAssignees(prev => (prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]));

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
                            <input type="text" value={name} onChange={e => setName(e.target.value)}
                                placeholder="E.g., Q1 Sales Outreach" className="glass-input" />
                        </div>

                        <div className="form-group">
                            <label>Description</label>
                            <textarea value={description} onChange={e => setDescription(e.target.value)}
                                placeholder="Describe the goal of this campaign..." className="glass-input" />
                        </div>

                        <div className="form-group">
                            <label>How will leads be called? *</label>
                            <div className="mode-options">
                                <button type="button" className={`mode-option ${mode === 'server_dialer' ? 'selected' : ''}`}
                                    onClick={() => setMode('server_dialer')}>
                                    <Server size={18} />
                                    <span><strong>AI calls leads</strong><small>Dialed automatically from the agent's number</small></span>
                                </button>
                                <button type="button" className={`mode-option ${mode === 'mobile_conference' ? 'selected' : ''}`}
                                    onClick={() => { setMode('mobile_conference'); setProvider('tata_tele'); }}>
                                    <Smartphone size={18} />
                                    <span><strong>Reps call from the mobile app</strong><small>Rep's phone calls the lead and merges in the AI</small></span>
                                </button>
                            </div>
                        </div>

                        <div className="form-row">
                            <div className="form-group">
                                <label>AI Agent *</label>
                                <select value={agentId} onChange={e => setAgentId(e.target.value)} className="glass-input">
                                    <option value="">Select an Agent</option>
                                    {agents.map(agent => (
                                        <option key={agent.id} value={agent.id}>{agent.display_name || agent.name}</option>
                                    ))}
                                </select>
                            </div>

                            {mode === 'server_dialer' && (
                                <div className="form-group">
                                    <label>Provider</label>
                                    <select value={provider} onChange={e => setProvider(e.target.value)} className="glass-input">
                                        <option value="tata_tele">Tata Tele (India)</option>
                                        <option value="twilio">Twilio (US/Global)</option>
                                    </select>
                                </div>
                            )}
                        </div>

                        {mode === 'mobile_conference' && (
                            <div className="form-group">
                                <label>Assign reps</label>
                                {assignableUsers.length === 0 ? (
                                    <p className="form-hint">The campaign will be assigned to you.</p>
                                ) : (
                                    <div className="assignee-list">
                                        {assignableUsers.map(u => (
                                            <label key={u.id} className="assignee-item">
                                                <input type="checkbox" checked={assignees.includes(u.id)} onChange={() => toggleAssignee(u.id)} />
                                                <span>{u.full_name}</span>
                                                <small>{u.email}</small>
                                            </label>
                                        ))}
                                    </div>
                                )}
                                {user?.role && !['tenant_admin', 'tenant_user'].includes(user.role) && assignees.length === 0 && (
                                    <p className="form-hint">Choose at least one rep from the tenant.</p>
                                )}
                            </div>
                        )}

                        <div className="modal-footer">
                            <JellyButton variant="secondary" onClick={onClose}>Cancel</JellyButton>
                            <JellyButton variant="primary" onClick={() => setStep(2)} disabled={!name || !agentId}>
                                Next: Contacts
                            </JellyButton>
                        </div>
                    </div>
                ) : (
                    <div className="step-content">
                        <div className="upload-section">
                            <label className="upload-dropzone">
                                <input type="file" accept=".csv,.xlsx" onChange={handleFileUpload} style={{ display: 'none' }} />
                                <div className="upload-ui">
                                    <Upload size={48} className={loading ? 'pulse' : ''} />
                                    <h3>{file ? file.name : 'Upload Contact List (.xlsx or .csv)'}</h3>
                                    <p>Needs a phone column (phone, mobile or contact). Other columns become lead details the AI can use.</p>
                                </div>
                            </label>
                        </div>

                        {report && (
                            <div className="upload-summary">
                                <div className="summary-item">
                                    <CheckCircle size={16} className="success" />
                                    <span>{report.valid_rows} valid contacts</span>
                                </div>
                                {report.invalid_rows > 0 && (
                                    <div className="summary-item">
                                        <AlertCircle size={16} className="danger" />
                                        <span>{report.invalid_rows} invalid rows</span>
                                    </div>
                                )}
                                {report.duplicate_rows > 0 && (
                                    <div className="summary-item">
                                        <AlertCircle size={16} />
                                        <span>{report.duplicate_rows} duplicates removed</span>
                                    </div>
                                )}
                            </div>
                        )}

                        {report && report.errors.length > 0 && (
                            <div className="upload-errors glass">
                                <h4>Rows skipped:</h4>
                                <ul>
                                    {report.errors.slice(0, 8).map((err, idx) => (
                                        <li key={idx}>Row {err.row}: {err.value || '(empty)'} — {err.reason.replace(/_/g, ' ')}</li>
                                    ))}
                                    {report.errors.length > 8 && <li>... and {report.errors.length - 8} more</li>}
                                </ul>
                            </div>
                        )}

                        <div className="modal-footer">
                            <JellyButton variant="secondary" onClick={() => setStep(1)}>Back</JellyButton>
                            <JellyButton variant="primary" onClick={handleCreate} disabled={loading || !report || report.valid_rows === 0}>
                                {loading ? 'Creating...' : mode === 'mobile_conference' ? 'Create for Mobile App' : 'Initialize Campaign'}
                            </JellyButton>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
