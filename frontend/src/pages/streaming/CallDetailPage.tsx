import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard } from '@/components/ui';
import {
  ArrowLeft, Phone, PhoneOutgoing, PhoneIncoming, Clock,
  Download, Play, Pause, FileText, Sparkles, CheckCircle2,
  AlertCircle, Loader2, User, Bot, Calendar, Hash, Save
} from 'lucide-react';
import './CallDetailPage.css';

interface TranscriptTurn {
  turn_number: number;
  speaker: string;
  content: string;
  message_type?: string;
  timestamp: string | null;
  audio_duration_ms?: number;
}

interface SessionDetail {
  id: string;
  customer_id: string;
  agent_id: string;
  phone_number: string;
  from_number?: string | null;
  to_number?: string | null;
  provider: string;
  call_sid: string;
  stream_sid?: string;
  direction: string;
  status: string;
  started_at: string;
  ended_at?: string;
  duration_seconds?: number;
  total_cost_usd: number;
  billed_amount: number;
  transcript: TranscriptTurn[];
  call_summary?: string | null;
  conversation_log?: any[];
  context_state?: any;
  session_metadata?: any;
  recording_url?: string | null;
  recording_file_name?: string | null;
  next_action?: string | null;
}

export const CallDetailPage: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const { token } = useAuth();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [manualNextAction, setManualNextAction] = useState('');
  const [savingAction, setSavingAction] = useState(false);
  const [actionSaved, setActionSaved] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    if (sessionId) fetchSession();
  }, [sessionId]);

  const fetchSession = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `${import.meta.env.VITE_API_BASE_URL}/streaming/voice-sessions/${sessionId}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!response.ok) throw new Error('Failed to fetch session');
      const data = await response.json();
      setSession(data);
      // Initialize manual next action from persisted state
      if (data.next_action) {
        setManualNextAction(data.next_action);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const formatDuration = (seconds?: number) => {
    if (!seconds) return '—';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  const formatDate = (iso: string) => {
    const d = parseServerDate(iso);
    return d.toLocaleString('en-IN', {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  };

  const getRecordingUrl = () => {
    if (!session?.recording_url) return null;
    const base = import.meta.env.VITE_API_BASE_URL?.replace('/api/v1', '') || '';
    const url = `${base}${session.recording_url}`;
    // Append JWT token for authentication (the download endpoint supports ?token=)
    return token ? `${url}${url.includes('?') ? '&' : '?'}token=${token}` : url;
  };

  const togglePlayback = () => {
    if (!audioRef.current) return;
    if (isPlaying) {
      audioRef.current.pause();
    } else {
      audioRef.current.play();
    }
    setIsPlaying(!isPlaying);
  };

  const extractNextActions = (summary?: string | null): string[] => {
    if (!summary) return [];
    const lines = summary.split('\n').filter(l => l.trim());
    const actionLines: string[] = [];
    let inActions = false;
    for (const line of lines) {
      const lower = line.toLowerCase();
      if (lower.includes('action') || lower.includes('follow') || lower.includes('next step')) {
        inActions = true;
      }
      if (inActions && (line.startsWith('-') || line.startsWith('•') || /^\d+[\.\)]/.test(line.trim()))) {
        actionLines.push(line.replace(/^[-•\d.\)]+\s*/, '').trim());
      }
    }
    return actionLines;
  };

  const saveNextAction = async () => {
    if (!sessionId || !token) return;
    setSavingAction(true);
    setActionSaved(false);
    try {
      const response = await fetch(
        `${import.meta.env.VITE_API_BASE_URL}/streaming/voice-sessions/${sessionId}/next-action`,
        {
          method: 'PATCH',
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ next_action: manualNextAction }),
        }
      );
      if (response.ok) {
        setActionSaved(true);
        setTimeout(() => setActionSaved(false), 3000);
      }
    } catch (err) {
      console.error('Failed to save next action:', err);
    } finally {
      setSavingAction(false);
    }
  };

  if (loading) {
    return (
      <div className="call-detail-page">
        <div className="loading-state">
          <Loader2 size={48} className="spin" />
          <p>Loading call details...</p>
        </div>
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="call-detail-page">
        <div className="error-state">
          <AlertCircle size={48} />
          <p>{error || 'Session not found'}</p>
          <button className="btn-back" onClick={() => navigate(-1)}>
            <ArrowLeft size={16} /> Go Back
          </button>
        </div>
      </div>
    );
  }

  const recordingUrl = getRecordingUrl();
  const nextActions = extractNextActions(session.call_summary);
  const statusClass = session.status === 'completed' || session.status === 'ended'
    ? 'success' : session.status === 'active' ? 'active' : 'neutral';

  return (
    <div className="call-detail-page">
      {/* Header */}
      <div className="call-detail-header">
        <button className="btn-back" onClick={() => navigate(-1)}>
          <ArrowLeft size={18} />
          <span>Back</span>
        </button>

        <div className="header-title">
          {session.direction === 'inbound' ? (
            <PhoneIncoming size={24} className="direction-icon inbound" />
          ) : (
            <PhoneOutgoing size={24} className="direction-icon outbound" />
          )}
          <div>
            <h1>Call Details</h1>
            <p className="header-sub">{session.phone_number} · {session.direction}</p>
          </div>
        </div>

        <span className={`call-status-badge ${statusClass}`}>
          {session.status === 'ended' ? 'Completed' : session.status}
        </span>
      </div>

      {/* Overview Cards */}
      <div className="overview-grid">
        <GlassCard>
          <div className="overview-card">
            <PhoneOutgoing size={20} className="card-icon" />
            <div>
              <span className="card-label">From Number</span>
              <span className="card-value">{session.from_number || session.phone_number || '—'}</span>
            </div>
          </div>
        </GlassCard>
        <GlassCard>
          <div className="overview-card">
            <PhoneIncoming size={20} className="card-icon" />
            <div>
              <span className="card-label">To Number</span>
              <span className="card-value">{session.to_number || '—'}</span>
            </div>
          </div>
        </GlassCard>
        <GlassCard>
          <div className="overview-card">
            <Clock size={20} className="card-icon" />
            <div>
              <span className="card-label">Duration</span>
              <span className="card-value">{formatDuration(session.duration_seconds)}</span>
            </div>
          </div>
        </GlassCard>
        <GlassCard>
          <div className="overview-card">
            <Calendar size={20} className="card-icon" />
            <div>
              <span className="card-label">Date</span>
              <span className="card-value">{formatDate(session.started_at)}</span>
            </div>
          </div>
        </GlassCard>
        <GlassCard>
          <div className="overview-card">
            <Hash size={20} className="card-icon" />
            <div>
              <span className="card-label">Provider</span>
              <span className="card-value capitalize">{session.provider === 'tata_tele' ? 'Tata Tele' : session.provider}</span>
            </div>
          </div>
        </GlassCard>
      </div>

      {/* Main Content */}
      <div className="call-content-grid">
        {/* Left Column — Summary & Actions */}
        <div className="call-left-column">
          {/* AI Call Summary */}
          <GlassCard>
            <div className="section-card">
              <div className="section-header">
                <Sparkles size={20} className="accent-icon" />
                <h2>AI Call Summary</h2>
              </div>
              {session.call_summary ? (
                <div className="summary-content">
                  {session.call_summary}
                </div>
              ) : (
                <div className="empty-section">
                  <p>No summary available. Summary is generated after the call ends with at least 2 transcript turns.</p>
                </div>
              )}
            </div>
          </GlassCard>

          {/* Next Actions — always visible */}
          <GlassCard>
            <div className="section-card">
              <div className="section-header">
                <CheckCircle2 size={20} className="accent-icon green" />
                <h2>Next Actions</h2>
              </div>
              {nextActions.length > 0 && (
                <ul className="actions-list">
                  {nextActions.map((action, i) => (
                    <li key={i}>{action}</li>
                  ))}
                </ul>
              )}
              <div className="next-action-input-group">
                <textarea
                  className="next-action-textarea"
                  placeholder="Add a follow-up action or note..."
                  value={manualNextAction}
                  onChange={(e) => setManualNextAction(e.target.value)}
                  rows={3}
                />
                <div className="next-action-footer">
                  {actionSaved && (
                    <span className="saved-indicator">
                      <CheckCircle2 size={14} /> Saved
                    </span>
                  )}
                  <button
                    className="save-action-btn"
                    onClick={saveNextAction}
                    disabled={savingAction}
                  >
                    {savingAction ? (
                      <Loader2 size={14} className="spin" />
                    ) : (
                      <Save size={14} />
                    )}
                    {savingAction ? 'Saving...' : 'Save'}
                  </button>
                </div>
              </div>
            </div>
          </GlassCard>

          {/* Recording */}
          <GlassCard>
            <div className="section-card">
              <div className="section-header">
                <Phone size={20} className="accent-icon blue" />
                <h2>Call Recording</h2>
              </div>
              {recordingUrl ? (
                <div className="recording-player">
                  <audio
                    ref={audioRef}
                    src={recordingUrl}
                    onEnded={() => setIsPlaying(false)}
                    onPause={() => setIsPlaying(false)}
                    onPlay={() => setIsPlaying(true)}
                  />
                  <div className="player-controls">
                    <button
                      className={`play-btn ${isPlaying ? 'playing' : ''}`}
                      onClick={togglePlayback}
                    >
                      {isPlaying ? <Pause size={20} /> : <Play size={20} />}
                    </button>
                    <div className="player-info">
                      <span className="file-name">
                        {session.recording_file_name || 'Recording'}
                      </span>
                      <span className="file-duration">
                        {formatDuration(session.duration_seconds)}
                      </span>
                    </div>
                    <a
                      href={recordingUrl}
                      download={session.recording_file_name || 'recording'}
                      className="download-btn"
                      title="Download Recording"
                    >
                      <Download size={18} />
                    </a>
                  </div>
                </div>
              ) : (
                <div className="empty-section">
                  <p>No recording available for this call.</p>
                </div>
              )}
            </div>
          </GlassCard>

          {/* Session Metadata */}
          {session.session_metadata && Object.keys(session.session_metadata).length > 0 && (
            <GlassCard>
              <div className="section-card">
                <div className="section-header">
                  <FileText size={20} className="accent-icon" />
                  <h2>Call Metadata</h2>
                </div>
                <div className="metadata-grid">
                  {Object.entries(session.session_metadata).map(([key, value]) => (
                    <div className="metadata-item" key={key}>
                      <span className="meta-key">{key.replace(/_/g, ' ')}</span>
                      <span className="meta-value">
                        {typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </GlassCard>
          )}
        </div>

        {/* Right Column — Transcript */}
        <div className="call-right-column">
          <GlassCard>
            <div className="section-card transcript-section">
              <div className="section-header">
                <FileText size={20} className="accent-icon" />
                <h2>Call Transcript</h2>
                {session.transcript && session.transcript.length > 0 && (
                  <span className="turn-count">{session.transcript.length} turns</span>
                )}
              </div>

              {session.transcript && session.transcript.length > 0 ? (
                <div className="transcript-container">
                  {session.transcript.map((turn, idx) => (
                    <div
                      key={idx}
                      className={`transcript-bubble ${turn.speaker === 'agent' ? 'agent' : 'customer'}`}
                    >
                      <div className="bubble-header">
                        <span className="speaker-icon">
                          {turn.speaker === 'agent' ? (
                            <><Bot size={14} /> Agent</>
                          ) : (
                            <><User size={14} /> Customer</>
                          )}
                        </span>
                        {turn.timestamp && (
                          <span className="bubble-time">
                            {parseServerDate(turn.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                          </span>
                        )}
                      </div>
                      <div className="bubble-content">{turn.content}</div>
                    </div>
                  ))}
                </div>
              ) : session.conversation_log && session.conversation_log.length > 0 ? (
                <div className="transcript-container">
                  {session.conversation_log.map((turn: any, idx: number) => (
                    <div
                      key={idx}
                      className={`transcript-bubble ${turn.speaker === 'agent' ? 'agent' : 'customer'}`}
                    >
                      <div className="bubble-header">
                        <span className="speaker-icon">
                          {turn.speaker === 'agent' ? (
                            <><Bot size={14} /> Agent</>
                          ) : (
                            <><User size={14} /> {turn.speaker}</>
                          )}
                        </span>
                      </div>
                      <div className="bubble-content">{turn.content}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-section centered">
                  <FileText size={40} className="muted-icon" />
                  <p>No transcript available for this call.</p>
                </div>
              )}
            </div>
          </GlassCard>
        </div>
      </div>
    </div>
  );
};
