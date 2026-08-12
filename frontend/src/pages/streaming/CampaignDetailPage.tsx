import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard, JellyButton } from '@/components/ui';
import { ArrowLeft, Download, Info, RefreshCw, AlertCircle } from 'lucide-react';
import './CampaignsPage.css';
import './CampaignDetailPage.css';

interface CampaignCallRecord {
    id: string;
    contact_name: string;
    contact_phone: string;
    contact_company: string;
    status: string;
    disposition: string | null;
    disposition_reason: string | null;
    called_at: string | null;
    voice_session_id: string | null;
}

export const CampaignDetailPage: React.FC = () => {
    const { campaignId } = useParams<{ campaignId: string }>();
    const { token } = useAuth();
    const navigate = useNavigate();
    const [campaign, setCampaign] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const campaignRef = useRef<any>(null);

    useEffect(() => {
        fetchCampaign();
    }, [campaignId]);

    useEffect(() => {
        campaignRef.current = campaign;
    }, [campaign]);

    // Poll while the campaign is running so metrics stay live
    useEffect(() => {
        const interval = setInterval(() => {
            const c = campaignRef.current;
            if (c && (c.status === 'running' || (c.calls_calling ?? 0) > 0)) {
                fetchCampaign(false);
            }
        }, 5000);
        return () => clearInterval(interval);
    }, [campaignId]);

    const fetchCampaign = async (showLoading = true) => {
        if (showLoading) setLoading(true);
        try {
            const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/campaigns/${campaignId}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!response.ok) throw new Error('Campaign not found');
            const data = await response.json();
            setCampaign(data);
            setError(null);
        } catch (err) {
            console.error('Error fetching campaign details:', err);
            setError('Failed to load campaign details');
        } finally {
            if (showLoading) setLoading(false);
        }
    };

    const downloadReport = async () => {
        try {
            const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/campaigns/${campaignId}/download`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (!response.ok) throw new Error('Failed to download report');

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `Campaign_Report_${(campaign?.name || 'campaign').replace(/\s+/g, '_')}.xlsx`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (err) {
            console.error('Error downloading report:', err);
            alert('Failed to download campaign report');
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

    const getDispositionColor = (disposition: string) => {
        const colors: Record<string, string> = {
            'interested': 'green',
            'not_interested': 'yellow',
            'voicemail': 'blue',
            'rejected': 'red',
            'busy': 'gray',
            'no_answer': 'gray',
            'failed': 'red'
        };
        return colors[disposition] || 'gray';
    };

    const formatDisposition = (disposition: string) =>
        disposition.replace(/_/g, ' ');

    if (loading) {
        return (
            <div className="loading-container">
                <RefreshCw size={48} className="pulse" color="var(--color-rose-gold)" />
                <div className="loading">Loading campaign details...</div>
            </div>
        );
    }

    if (error || !campaign) {
        return (
            <div className="campaign-detail-page">
                <div className="campaign-detail-error">
                    <AlertCircle size={48} />
                    <p>{error || 'Campaign not found'}</p>
                    <button className="btn-back" onClick={() => navigate('/streaming/campaigns')}>
                        <ArrowLeft size={16} /> Back to Campaigns
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="campaign-detail-page">
            <div className="campaign-detail-header">
                <button className="btn-back" onClick={() => navigate('/streaming/campaigns')}>
                    <ArrowLeft size={18} />
                    <span>Back</span>
                </button>

                <div className="header-title">
                    <div>
                        <h1>{campaign.name}</h1>
                        {campaign.description && (
                            <p className="header-sub">{campaign.description}</p>
                        )}
                    </div>
                </div>

                <span className={`status-badge ${getStatusColor(campaign.status)}`}>
                    {campaign.status}
                </span>

                <JellyButton variant="secondary" onClick={downloadReport}>
                    <Download size={16} />
                    Download Report
                </JellyButton>
            </div>

            <GlassCard>
                <div className="campaign-detail-body">
                    <div className="detail-section">
                        <h3>Campaign Metrics</h3>
                        <div className="detail-grid">
                            <div className="detail-item">
                                <span className="label">Outreach Engine</span>
                                <strong>{campaign.provider === 'tata_tele' ? 'Tata Tele' : 'Twilio'}</strong>
                            </div>
                            <div className="detail-item">
                                <span className="label">Total Contacts</span>
                                <strong>{campaign.total_contacts}</strong>
                            </div>
                            <div className="detail-item">
                                <span className="label">Completed</span>
                                <strong className="success">{campaign.calls_completed ?? 0}</strong>
                            </div>
                            <div className="detail-item">
                                <span className="label">In Progress</span>
                                <strong style={{ color: '#3b82f6' }}>{campaign.calls_calling ?? 0}</strong>
                            </div>
                            <div className="detail-item">
                                <span className="label">Pending</span>
                                <strong>{campaign.calls_pending ?? 0}</strong>
                            </div>
                            <div className="detail-item">
                                <span className="label">Voicemail</span>
                                <strong style={{ color: '#3b82f6' }}>{campaign.calls_voicemail ?? 0}</strong>
                            </div>
                            <div className="detail-item">
                                <span className="label">Failed</span>
                                <strong className="danger">{campaign.calls_failed ?? 0}</strong>
                            </div>
                        </div>
                    </div>

                    {campaign.calls && campaign.calls.length > 0 && (
                        <div className="detail-section">
                            <h3>Call Records</h3>
                            <div className="call-records-table full-page">
                                <table className="data-table compact">
                                    <thead>
                                        <tr>
                                            <th>Contact</th>
                                            <th>Phone</th>
                                            <th>Company</th>
                                            <th>Status</th>
                                            <th>Disposition</th>
                                            <th>Reason</th>
                                            <th>Called At</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {campaign.calls.map((call: CampaignCallRecord) => (
                                            <tr key={call.id}>
                                                <td>{call.contact_name}</td>
                                                <td className="phone-number">{call.contact_phone}</td>
                                                <td>{call.contact_company || '—'}</td>
                                                <td>
                                                    <span className={`status-badge ${getStatusColor(call.status)}`}>
                                                        {call.status}
                                                    </span>
                                                </td>
                                                <td>
                                                    {call.disposition ? (
                                                        <span className={`status-badge ${getDispositionColor(call.disposition)}`}>
                                                            {formatDisposition(call.disposition)}
                                                        </span>
                                                    ) : '—'}
                                                </td>
                                                <td className="disposition-reason">
                                                    {call.disposition_reason ? formatDisposition(call.disposition_reason) : '—'}
                                                </td>
                                                <td>{call.called_at ? parseServerDate(call.called_at).toLocaleString() : '—'}</td>
                                                <td>
                                                    {call.voice_session_id && (
                                                        <button
                                                            className="btn-view"
                                                            onClick={() => navigate(`/streaming/calls/${call.voice_session_id}`)}
                                                        >
                                                            <Info size={14} /> View Call
                                                        </button>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    <div className="detail-section">
                        <h3>Configuration</h3>
                        <div className="detail-grid">
                            <div className="detail-item">
                                <span className="label">Concurrency</span>
                                <strong>{campaign.max_concurrent_calls || 5} streams</strong>
                            </div>
                            <div className="detail-item">
                                <span className="label">Target Zone</span>
                                <strong>{campaign.provider === 'tata_tele' ? 'India' : 'International'}</strong>
                            </div>
                            {campaign.scheduled_start && (
                                <div className="detail-item">
                                    <span className="label">Scheduled Window</span>
                                    <strong>{parseServerDate(campaign.scheduled_start).toLocaleString()}</strong>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </GlassCard>
        </div>
    );
};
