import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard } from '@/components/ui';
import './StreamingSessionsPage.css';

interface VoiceSession {
    id: string;
    customer_id: string;
    phone_number: string;
    provider: string;
    call_sid: string;
    direction: string;
    status: string;
    started_at: string;
    ended_at?: string;
    duration_seconds?: number;
    total_cost_usd: number;
    billed_amount: number;
    has_transcript: boolean;
    transcript?: Array<{ turn_number: number; speaker: string; content: string; timestamp: string | null }>;
    call_summary?: string | null;
    conversation_log?: any[];
    recording_url?: string | null;
    recording_file_name?: string | null;
}

interface WhatsAppSession {
    id: string;
    customer_id: string;
    phone_number: string;
    provider: string;
    conversation_id: string;
    status: string;
    started_at: string;
    last_message_at?: string;
    message_count: number;
    total_cost_usd: number;
    billed_amount: number;
}

interface Stats {
    voice: {
        total_calls: number;
        completed_calls: number;
        total_duration_minutes: number;
        total_cost_usd: number;
        total_billed: number;
    };
    whatsapp: {
        total_sessions: number;
        active_sessions: number;
        total_messages: number;
        total_cost_usd: number;
        total_billed: number;
    };
}

export const StreamingSessionsPage: React.FC = () => {
    const { token } = useAuth();
    const navigate = useNavigate();
    const [activeTab, setActiveTab] = useState<'voice' | 'whatsapp' | 'stats'>('voice');
    const [voiceSessions, setVoiceSessions] = useState<VoiceSession[]>([]);
    const [whatsappSessions, setWhatsAppSessions] = useState<WhatsAppSession[]>([]);
    const [stats, setStats] = useState<Stats | null>(null);
    const [loading, setLoading] = useState(true);
    const [selectedSession, setSelectedSession] = useState<any>(null);

    useEffect(() => {
        if (activeTab === 'voice') {
            fetchVoiceSessions();
        } else if (activeTab === 'whatsapp') {
            fetchWhatsAppSessions();
        } else {
            fetchStats();
        }
    }, [activeTab]);

    const fetchVoiceSessions = async () => {
        setLoading(true);
        try {
            const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/streaming/voice-sessions`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await response.json();
            setVoiceSessions(data.sessions || []);
        } catch (error) {
            console.error('Error fetching voice sessions:', error);
        } finally {
            setLoading(false);
        }
    };

    const fetchWhatsAppSessions = async () => {
        setLoading(true);
        try {
            const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/streaming/whatsapp-sessions`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await response.json();
            setWhatsAppSessions(data.sessions || []);
        } catch (error) {
            console.error('Error fetching WhatsApp sessions:', error);
        } finally {
            setLoading(false);
        }
    };

    const fetchStats = async () => {
        setLoading(true);
        try {
            const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/streaming/stats?days=7`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await response.json();
            setStats(data);
        } catch (error) {
            console.error('Error fetching stats:', error);
        } finally {
            setLoading(false);
        }
    };

    const viewSessionDetails = async (sessionId: string, type: 'voice' | 'whatsapp') => {
        try {
            const endpoint = type === 'voice'
                ? `voice-sessions/${sessionId}`
                : `whatsapp-sessions/${sessionId}`;

            const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/streaming/${endpoint}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await response.json();
            setSelectedSession({ ...data, type });
        } catch (error) {
            console.error('Error fetching session details:', error);
        }
    };

    const formatDuration = (seconds?: number) => {
        if (!seconds) return 'N/A';
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}m ${secs}s`;
    };

    const formatCost = (cost: number) => {
        return `$${cost.toFixed(4)}`;
    };

    return (
        <div className="streaming-sessions-page">
            <div className="page-header">
                <div>
                    <h1>Streaming Sessions</h1>
                    <p className="subtitle">View voice calls and WhatsApp conversations</p>
                </div>
            </div>

            <div className="tabs">
                <button
                    className={`tab ${activeTab === 'voice' ? 'active' : ''}`}
                    onClick={() => setActiveTab('voice')}
                >
                    📞 Voice Calls
                </button>
                <button
                    className={`tab ${activeTab === 'whatsapp' ? 'active' : ''}`}
                    onClick={() => setActiveTab('whatsapp')}
                >
                    💬 WhatsApp
                </button>
                <button
                    className={`tab ${activeTab === 'stats' ? 'active' : ''}`}
                    onClick={() => setActiveTab('stats')}
                >
                    📊 Statistics
                </button>
            </div>

            <GlassCard>
                {loading ? (
                    <div className="loading">Loading...</div>
                ) : activeTab === 'voice' ? (
                    <div className="sessions-grid">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>Phone Number</th>
                                    <th>Provider</th>
                                    <th>Direction</th>
                                    <th>Status</th>
                                    <th>Started</th>
                                    <th>Duration</th>
                                    <th>Billed</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {voiceSessions.length === 0 ? (
                                    <tr>
                                        <td colSpan={8} className="empty-state">
                                            No voice sessions found
                                        </td>
                                    </tr>
                                ) : (
                                    voiceSessions.map(session => (
                                        <tr key={session.id}>
                                            <td className="phone-number">{session.phone_number}</td>
                                            <td>
                                                <span className={`provider-badge ${session.provider}`}>
                                                    {session.provider}
                                                </span>
                                            </td>
                                            <td>{session.direction}</td>
                                            <td>
                                                <span className={`status-badge ${session.status}`}>
                                                    {session.status}
                                                </span>
                                            </td>
                                            <td>{parseServerDate(session.started_at).toLocaleString()}</td>
                                            <td>{formatDuration(session.duration_seconds)}</td>
                                            <td>{formatCost(session.billed_amount)}</td>
                                            <td>
                                                <button
                                                    className="btn-view"
                                                    onClick={() => navigate(`/streaming/calls/${session.id}`)}
                                                >
                                                    View
                                                </button>
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                ) : activeTab === 'whatsapp' ? (
                    <div className="sessions-grid">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>Phone Number</th>
                                    <th>Provider</th>
                                    <th>Status</th>
                                    <th>Started</th>
                                    <th>Last Message</th>
                                    <th>Messages</th>
                                    <th>Billed</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {whatsappSessions.length === 0 ? (
                                    <tr>
                                        <td colSpan={8} className="empty-state">
                                            No WhatsApp sessions found
                                        </td>
                                    </tr>
                                ) : (
                                    whatsappSessions.map(session => (
                                        <tr key={session.id}>
                                            <td className="phone-number">{session.phone_number}</td>
                                            <td>
                                                <span className={`provider-badge ${session.provider}`}>
                                                    {session.provider}
                                                </span>
                                            </td>
                                            <td>
                                                <span className={`status-badge ${session.status}`}>
                                                    {session.status}
                                                </span>
                                            </td>
                                            <td>{parseServerDate(session.started_at).toLocaleString()}</td>
                                            <td>
                                                {session.last_message_at
                                                    ? parseServerDate(session.last_message_at).toLocaleString()
                                                    : 'N/A'}
                                            </td>
                                            <td>{session.message_count}</td>
                                            <td>{formatCost(session.billed_amount)}</td>
                                            <td>
                                                <button
                                                    className="btn-view"
                                                    onClick={() => viewSessionDetails(session.id, 'whatsapp')}
                                                >
                                                    View
                                                </button>
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                ) : stats ? (
                    <div className="stats-grid">
                        <div className="stat-card">
                            <h3>Voice Calls (Last 7 Days)</h3>
                            <div className="stat-row">
                                <span>Total Calls:</span>
                                <strong>{stats.voice.total_calls}</strong>
                            </div>
                            <div className="stat-row">
                                <span>Completed:</span>
                                <strong>{stats.voice.completed_calls}</strong>
                            </div>
                            <div className="stat-row">
                                <span>Total Duration:</span>
                                <strong>{stats.voice.total_duration_minutes.toFixed(1)} min</strong>
                            </div>
                            <div className="stat-row">
                                <span>Total Billed:</span>
                                <strong>{formatCost(stats.voice.total_billed)}</strong>
                            </div>
                        </div>

                        <div className="stat-card">
                            <h3>WhatsApp (Last 7 Days)</h3>
                            <div className="stat-row">
                                <span>Total Sessions:</span>
                                <strong>{stats.whatsapp.total_sessions}</strong>
                            </div>
                            <div className="stat-row">
                                <span>Active Sessions:</span>
                                <strong>{stats.whatsapp.active_sessions}</strong>
                            </div>
                            <div className="stat-row">
                                <span>Total Messages:</span>
                                <strong>{stats.whatsapp.total_messages}</strong>
                            </div>
                            <div className="stat-row">
                                <span>Total Billed:</span>
                                <strong>{formatCost(stats.whatsapp.total_billed)}</strong>
                            </div>
                        </div>
                    </div>
                ) : null}
            </GlassCard>

            {selectedSession && (
                <div className="modal-overlay" onClick={() => setSelectedSession(null)}>
                    <div className="modal-content session-details" onClick={e => e.stopPropagation()}>
                        <h2>Session Details</h2>
                        <div className="detail-section">
                            <h3>Basic Information</h3>
                            <div className="detail-row">
                                <span>Session ID:</span>
                                <code>{selectedSession.id}</code>
                            </div>
                            <div className="detail-row">
                                <span>Phone Number:</span>
                                <strong>{selectedSession.phone_number}</strong>
                            </div>
                            <div className="detail-row">
                                <span>Provider:</span>
                                <strong>{selectedSession.provider}</strong>
                            </div>
                            <div className="detail-row">
                                <span>Direction:</span>
                                <strong>{selectedSession.direction}</strong>
                            </div>
                            <div className="detail-row">
                                <span>Duration:</span>
                                <strong>{formatDuration(selectedSession.duration_seconds)}</strong>
                            </div>
                            <div className="detail-row">
                                <span>Billed Amount:</span>
                                <strong>{formatCost(selectedSession.billed_amount || selectedSession.total_cost_usd || 0)}</strong>
                            </div>
                            <div className="detail-row">
                                <span>Status:</span>
                                <span className={`status-badge ${selectedSession.status}`}>
                                    {selectedSession.status}
                                </span>
                            </div>
                        </div>

                        {/* AI Call Summary */}
                        {selectedSession.call_summary && (
                            <div className="detail-section">
                                <h3>✨ AI Call Summary</h3>
                                <div style={{
                                    background: 'rgba(99, 102, 241, 0.08)',
                                    borderLeft: '3px solid #6366f1',
                                    borderRadius: '6px',
                                    padding: '12px 16px',
                                    lineHeight: '1.6',
                                    fontSize: '0.95rem',
                                    color: 'var(--text-primary, #e2e8f0)'
                                }}>
                                    {selectedSession.call_summary}
                                </div>
                            </div>
                        )}

                        {/* Recording File */}
                        {selectedSession.recording_url && (
                            <div className="detail-section">
                                <h3>🎙️ Recording</h3>
                                <div className="detail-row">
                                    <span>File:</span>
                                    <a
                                        href={`${import.meta.env.VITE_API_BASE_URL?.replace('/api/v1', '')}${selectedSession.recording_url}`}
                                        target="_blank"
                                        rel="noreferrer"
                                        download={selectedSession.recording_file_name || 'recording'}
                                    >
                                        ⬇️ {selectedSession.recording_file_name || 'Download Recording'}
                                    </a>
                                </div>
                            </div>
                        )}

                        {/* Transcript */}
                        {selectedSession.transcript && selectedSession.transcript.length > 0 && (
                            <div className="detail-section">
                                <h3>📝 Transcript</h3>
                                <div className="conversation-log">
                                    {selectedSession.transcript.map((turn: any, idx: number) => (
                                        <div key={idx} className={`message ${turn.speaker}`}>
                                            <div className="message-header">
                                                <strong>{turn.speaker === 'agent' ? '🤖 Agent' : '👤 Customer'}</strong>
                                                {turn.timestamp && (
                                                    <span className="timestamp">
                                                        {parseServerDate(turn.timestamp).toLocaleTimeString()}
                                                    </span>
                                                )}
                                            </div>
                                            <div className="message-content">{turn.content}</div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Fallback: conversation_log if transcript is empty */}
                        {(!selectedSession.transcript || selectedSession.transcript.length === 0) &&
                            selectedSession.conversation_log && selectedSession.conversation_log.length > 0 && (
                                <div className="detail-section">
                                    <h3>📝 Conversation Log</h3>
                                    <div className="conversation-log">
                                        {selectedSession.conversation_log.map((turn: any, idx: number) => (
                                            <div key={idx} className={`message ${turn.speaker}`}>
                                                <div className="message-header">
                                                    <strong>{turn.speaker}</strong>
                                                    <span className="timestamp">
                                                        {parseServerDate(turn.timestamp).toLocaleTimeString()}
                                                    </span>
                                                </div>
                                                <div className="message-content">{turn.content}</div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                        {/* No data message */}
                        {(!selectedSession.transcript || selectedSession.transcript.length === 0) &&
                            (!selectedSession.conversation_log || selectedSession.conversation_log.length === 0) &&
                            !selectedSession.recording_url && (
                                <div className="detail-section">
                                    <p style={{ color: 'var(--text-muted, #888)', textAlign: 'center' }}>
                                        No transcript or recording available for this session.
                                    </p>
                                </div>
                            )}

                        <button className="btn-primary" onClick={() => setSelectedSession(null)}>
                            Close
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
};
