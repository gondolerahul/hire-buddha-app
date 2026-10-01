import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { GlassCard, JellyButton } from '@/components/ui';
import { Plus, Play, Pause, Square, Info, RefreshCw, PhoneForwarded, Download, RotateCcw, Smartphone } from 'lucide-react';
import { CampaignCreateModal } from './CampaignCreateModal';
import './CampaignsPage.css';
import { apiClient } from '@/services/api.client';
import { apiErrorMessage } from '@/utils/apiError';

interface Campaign {
    id: string;
    name: string;
    description: string;
    status: string;
    total_contacts: number;
    calls_initiated: number;
    calls_completed: number;
    calls_failed: number;
    calls_calling?: number;
    calls_pending?: number;
    provider?: string;
    execution_mode?: 'server_dialer' | 'mobile_conference';
    created_at: string;
}

export const CampaignsPage: React.FC = () => {
    const navigate = useNavigate();
    const [campaigns, setCampaigns] = useState<Campaign[]>([]);
    const [loading, setLoading] = useState(true);
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
    const [actionLoading, setActionLoading] = useState<string | null>(null);
    const [downloadingInterested, setDownloadingInterested] = useState(false);
    const [retryingFailed, setRetryingFailed] = useState(false);

    const campaignsRef = useRef<Campaign[]>([]);

    useEffect(() => {
        fetchCampaigns();
    }, []);

    // Update ref whenever campaigns change
    useEffect(() => {
        campaignsRef.current = campaigns;
    }, [campaigns]);

    // Set up polling interval only once
    useEffect(() => {
        const interval = setInterval(() => {
            const hasRunning = campaignsRef.current.some(c => c.status === 'running');
            if (hasRunning) {
                fetchCampaigns(false);
            }
        }, 5000);

        return () => clearInterval(interval);
    }, []); // Empty dependency array - only set up once

    const fetchCampaigns = async (showLoading = true) => {
        if (showLoading) setLoading(true);
        try {
            const { data } = await apiClient.get('/campaigns');
            setCampaigns(data.campaigns || []);
        } catch (error) {
            console.error('Error fetching campaigns:', error);
        } finally {
            if (showLoading) setLoading(false);
        }
    };

    const downloadInterestedLeads = async () => {
        setDownloadingInterested(true);
        try {
            const { data: blob } = await apiClient.get('/campaigns/interested/download', { responseType: 'blob' });
            const url= window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'Interested_Leads.xlsx';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (error) {
            console.error('Error downloading interested leads:', error);
            alert('Failed to download interested leads');
        } finally {
            setDownloadingInterested(false);
        }
    };

    const retryFailedCalls = async () => {
        if (!window.confirm('Retry all failed calls across all campaigns? The affected campaigns will start running again.')) {
            return;
        }
        setRetryingFailed(true);
        try {
            const { data } = await apiClient.post('/campaigns/retry-failed');
            alert(data.message);
            await fetchCampaigns(false);
        } catch (error) {
            console.error('Error retrying failed calls:', error);
            alert(apiErrorMessage(error, 'Failed to retry failed calls'));
        } finally {
            setRetryingFailed(false);
        }
    };

    const updateStatus = async (campaignId: string, status: string) => {
        setActionLoading(campaignId);
        try {
            await apiClient.patch(`/campaigns/${campaignId}/status`, null, { params: { status } });
            await fetchCampaigns(false);
        } catch (error) {
            console.error('Error updating campaign status:', error);
            alert(apiErrorMessage(error, 'Failed to update campaign status'));
        } finally {
            setActionLoading(null);
        }
    };

    const getStatusColor = (status: string) => {
        const colors: Record<string, string> = {
            'draft': 'gray',
            'scheduled': 'blue',
            'running': 'green',
            'paused': 'yellow',
            'completed': 'purple',
            'completed-voicemail': 'blue',
            'failed': 'red',
            'stopped': 'red'
        };
        return colors[status] || 'gray';
    };

    const calculateProgress = (campaign: Campaign) => {
        if (campaign.total_contacts === 0) return 0;
        const done = (campaign.calls_completed ?? 0) + (campaign.calls_failed ?? 0);
        return Math.round((done / campaign.total_contacts) * 100);
    };

    if (loading) {
        return (
            <div className="loading-container">
                <RefreshCw size={48} className="pulse" color="var(--color-rose-gold)" />
                <div className="loading">Syncing voice campaigns...</div>
            </div>
        );
    }

    return (
        <div className="campaigns-page">
            <div className="page-header">
                <div>
                    <h1>Voice Campaigns</h1>
                    <p className="subtitle">Orchestrate and monitor high-volume outbound AI calling</p>
                </div>
                <div className="header-actions">
                    <JellyButton
                        variant="secondary"
                        onClick={downloadInterestedLeads}
                        disabled={downloadingInterested}
                    >
                        <Download size={16} />
                        {downloadingInterested ? 'Downloading...' : 'Download Interested'}
                    </JellyButton>
                    <JellyButton
                        variant="secondary"
                        onClick={retryFailedCalls}
                        disabled={retryingFailed}
                    >
                        <RotateCcw size={16} />
                        {retryingFailed ? 'Queueing...' : 'Retry Failed'}
                    </JellyButton>
                    <JellyButton roseGold onClick={() => setIsCreateModalOpen(true)}>
                        <Plus size={20} />
                        Launch Campaign
                    </JellyButton>
                </div>
            </div>

            <GlassCard>
                <div className="campaigns-grid">
                    {campaigns.length === 0 ? (
                        <div className="empty-state">
                            <PhoneForwarded size={64} color="var(--text-tertiary)" style={{ marginBottom: '1.5rem' }} />
                            <h3>No Active Pipelines</h3>
                            <p>Configure a neural agent and contact list to initiate outreach.</p>
                            <JellyButton
                                variant="secondary"
                                style={{ marginTop: '1.5rem' }}
                                onClick={() => setIsCreateModalOpen(true)}
                            >
                                <Plus size={16} /> Create First Campaign
                            </JellyButton>
                        </div>
                    ) : (
                        <div className="campaign-cards">
                            {campaigns.map(campaign => (
                                <div key={campaign.id} className="campaign-card">
                                    <div className="campaign-header">
                                        <h3>{campaign.name}</h3>
                                        <span className={`status-badge ${getStatusColor(campaign.status)}`}>
                                            {campaign.status}
                                        </span>
                                    </div>

                                    {campaign.description && (
                                        <p className="campaign-description">{campaign.description}</p>
                                    )}

                                    <div className="campaign-stats">
                                        <div className="stat">
                                            <span className="stat-label">Total</span>
                                            <span className="stat-value">{campaign.total_contacts}</span>
                                        </div>
                                        <div className="stat">
                                            <span className="stat-label">Completed</span>
                                            <span className="stat-value success">{campaign.calls_completed ?? 0}</span>
                                        </div>
                                        <div className="stat">
                                            <span className="stat-label">Pending</span>
                                            <span className="stat-value">{campaign.calls_pending ?? campaign.total_contacts - ((campaign.calls_completed ?? 0) + (campaign.calls_failed ?? 0))}</span>
                                        </div>
                                    </div>

                                    <div className="progress-bar">
                                        <div
                                            className={`progress-fill ${campaign.status === 'running' ? 'progress-animated' : ''}`}
                                            style={{ width: `${calculateProgress(campaign)}%` }}
                                        />
                                    </div>
                                    <div className="progress-label-row">
                                        <span className="progress-percent">{calculateProgress(campaign)}%</span>
                                        <span className="progress-detail">{campaign.calls_completed} of {campaign.total_contacts} contacts</span>
                                    </div>

                                    <div className="campaign-actions">
                                        {campaign.execution_mode === 'mobile_conference' ? (
                                            // Reps start, pause and stop these from the mobile app.
                                            <span className="mobile-mode-hint" title="Run from the HireBuddha mobile app">
                                                <Smartphone size={16} /> Run from mobile app
                                            </span>
                                        ) : campaign.status === 'draft' || campaign.status === 'paused' || campaign.status === 'failed' || campaign.status === 'stopped' ? (
                                            <button
                                                className="action-btn start"
                                                onClick={() => updateStatus(campaign.id, 'running')}
                                                disabled={actionLoading === campaign.id}
                                                title="Start Campaign"
                                            >
                                                <Play size={18} fill="currentColor" />
                                            </button>
                                        ) : campaign.status === 'running' ? (
                                            <button
                                                className="action-btn pause"
                                                onClick={() => updateStatus(campaign.id, 'paused')}
                                                disabled={actionLoading === campaign.id}
                                                title="Pause Campaign"
                                            >
                                                <Pause size={18} fill="currentColor" />
                                            </button>
                                        ) : null}

                                        {campaign.execution_mode !== 'mobile_conference' && (campaign.status === 'running' || campaign.status === 'paused') ? (
                                            <button
                                                className="action-btn stop"
                                                onClick={() => updateStatus(campaign.id, 'stopped')}
                                                disabled={actionLoading === campaign.id}
                                                title="Hard Stop"
                                            >
                                                <Square size={18} fill="currentColor" />
                                            </button>
                                        ) : null}

                                        <div className="spacer" />

                                        <button
                                            className="btn-view"
                                            onClick={() => navigate(`/streaming/campaigns/${campaign.id}`)}
                                        >
                                            <Info size={16} /> Details
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </GlassCard>

            <CampaignCreateModal
                isOpen={isCreateModalOpen}
                onClose={() => setIsCreateModalOpen(false)}
                onSuccess={() => fetchCampaigns()}
            />
        </div>
    );
};

