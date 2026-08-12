import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { LucideIcon } from 'lucide-react';
import {
    Search, Upload, Filter, Image, Video, Mic, Download, Trash2,
    X, Play, Pause, ZoomIn, FileText, File, Bot, User2, Info
} from 'lucide-react';
import { artifactService, Artifact, ArtifactListFilters } from '@/services/artifact.service';
import { apiClient } from '@/services/api.client';
import './Artifacts.css';

const FILE_CATEGORY_OPTIONS = [
    { value: '', label: 'All Types' },
    { value: 'recordings', label: 'Recordings' },
    { value: 'images', label: 'Images' },
    { value: 'videos', label: 'Videos' },
    { value: 'documents', label: 'Documents' },
    { value: 'text', label: 'Text / Notes' },
];

const ORIGIN_OPTIONS = [
    { value: '', label: 'All Sources' },
    { value: 'user-uploads', label: 'User Uploads' },
    { value: 'system-generated', label: 'System Generated' },
];

const CATEGORY_ICON: Record<string, LucideIcon> = {
    recordings: Mic,
    images: Image,
    videos: Video,
    documents: FileText,
    text: File,
};

function formatFileSize(bytes: number | null): string {
    if (!bytes) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(2)} MB`;
}

function formatDuration(secs: number | null): string {
    if (!secs) return '';
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
}

// ─── Audio Player ──────────────────────────────────────────────────────────

interface AudioPlayerProps { src: string; }
const AudioPlayer: React.FC<AudioPlayerProps> = ({ src }) => {
    const [playing, setPlaying] = useState(false);
    const [progress, setProgress] = useState(0);
    const [duration, setDuration] = useState(0);
    const audioRef = useRef<HTMLAudioElement>(null);

    const toggle = () => {
        if (!audioRef.current) return;
        if (playing) { audioRef.current.pause(); } else { audioRef.current.play(); }
        setPlaying(!playing);
    };

    return (
        <div className="audio-player">
            <audio
                ref={audioRef}
                src={src}
                onTimeUpdate={() => setProgress(audioRef.current?.currentTime || 0)}
                onLoadedMetadata={() => setDuration(audioRef.current?.duration || 0)}
                onEnded={() => setPlaying(false)}
            />
            <button className="play-btn" onClick={toggle}>
                {playing ? <Pause size={16} /> : <Play size={16} />}
            </button>
            <div className="progress-bar">
                <div
                    className="progress-fill"
                    style={{ width: duration ? `${(progress / duration) * 100}%` : '0%' }}
                />
            </div>
            <span className="duration-text">
                {formatDuration(Math.floor(progress))} / {formatDuration(Math.floor(duration))}
            </span>
        </div>
    );
};

// ─── Image Lightbox ──────────────────────────────────────────────────────────

interface LightboxProps { src: string; onClose: () => void; }
const Lightbox: React.FC<LightboxProps> = ({ src, onClose }) => (
    <div className="lightbox-overlay" onClick={onClose}>
        <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
            <button className="lightbox-close" onClick={onClose}><X size={20} /></button>
            <img src={src} alt="Artifact preview" className="lightbox-img" />
        </div>
    </div>
);

// ─── Provenance Badge ─────────────────────────────────────────────────────────

const OriginBadge: React.FC<{ origin: string }> = ({ origin }) => (
    <div className={`origin-badge origin-${origin === 'user-uploads' ? 'user' : 'system'}`}>
        {origin === 'user-uploads'
            ? <><User2 size={11} /> User Upload</>
            : <><Bot size={11} /> AI Generated</>}
    </div>
);

// ─── Main Component ──────────────────────────────────────────────────────────


export const Artifacts: React.FC = () => {
    const [artifacts, setArtifacts] = useState<Artifact[]>([]);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
    const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [tooltipId, setTooltipId] = useState<string | null>(null);
    const [filters, setFilters] = useState<ArtifactListFilters>({
        origin: undefined,
        file_category: undefined,
        date_from: undefined,
        date_to: undefined,
        limit: 50,
        offset: 0,
    });
    const [searchAgentId, setSearchAgentId] = useState('');
    const [searchCampaignId, setSearchCampaignId] = useState('');
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [uploadCategory, setUploadCategory] = useState<string>('images');

    const fetchArtifacts = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const f: ArtifactListFilters = { ...filters };
            if (searchAgentId.trim()) f.agent_id = searchAgentId.trim();
            if (searchCampaignId.trim()) f.campaign_id = searchCampaignId.trim();
            const res = await artifactService.list(f);
            setArtifacts(res.artifacts);
        } catch (e: any) {
            setError(e?.response?.data?.detail || 'Failed to load artifacts');
        } finally {
            setLoading(false);
        }
    }, [filters, searchAgentId, searchCampaignId]);

    useEffect(() => { fetchArtifacts(); }, [fetchArtifacts]);

    const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setUploading(true);
        try {
            await artifactService.upload(file, uploadCategory);
            fetchArtifacts();
        } catch (err: any) {
            setError(err?.response?.data?.detail || 'Upload failed');
        } finally {
            setUploading(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    const handleDelete = async (id: string) => {
        if (!confirm('Delete this artifact permanently?')) return;
        await artifactService.delete(id);
        setArtifacts((prev) => prev.filter((a) => a.id !== id));
    };

    const handleDownload = async (artifact: Artifact) => {
        try {
            const response = await apiClient.get(`/artifacts/${artifact.id}/download`, {
                responseType: 'blob',
            });
            const blob = response.data as Blob;
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = artifact.file_name;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (err: any) {
            setError(err?.message || 'Download failed');
        }
    };

    const getPreviewUrl = (artifact: Artifact) => {
        const base = import.meta.env.VITE_API_URL || '';
        const token = localStorage.getItem('access_token') || '';
        return `${base}/api/v1/artifacts/${artifact.id}/download?token=${token}`;
    };

    return (
        <div className="artifact-page">
            {lightboxSrc && <Lightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />}

            <div className="page-header">
                <div>
                    <h1 className="page-title">Artifacts</h1>
                    <p className="page-subtitle">All files — user uploads and AI-generated content, organised by company</p>
                </div>
                <div className="upload-area">
                    <select
                        id="upload-category-select"
                        className="upload-type-select"
                        value={uploadCategory}
                        onChange={(e) => setUploadCategory(e.target.value)}
                    >
                        <option value="recordings">Recording</option>
                        <option value="images">Image</option>
                        <option value="videos">Video</option>
                        <option value="documents">Document</option>
                        <option value="text">Text / Note</option>
                    </select>
                    <button
                        id="upload-artifact-btn"
                        className="btn-primary"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={uploading}
                    >
                        <Upload size={16} />
                        {uploading ? 'Uploading…' : 'Upload Artifact'}
                    </button>
                    <input ref={fileInputRef} type="file" hidden onChange={handleUpload} />
                </div>
            </div>

            {/* Filters */}
            <div className="filter-panel glass">
                <div className="filter-row">
                    <div className="filter-group">
                        <label>Source</label>
                        <select
                            id="filter-origin"
                            value={filters.origin || ''}
                            onChange={(e) => setFilters((f) => ({ ...f, origin: e.target.value as any || undefined }))}
                        >
                            {ORIGIN_OPTIONS.map((o) => (
                                <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                        </select>
                    </div>

                    <div className="filter-group">
                        <label>File Type</label>
                        <select
                            id="filter-file-category"
                            value={filters.file_category || ''}
                            onChange={(e) => setFilters((f) => ({ ...f, file_category: e.target.value as any || undefined }))}
                        >
                            {FILE_CATEGORY_OPTIONS.map((o) => (
                                <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                        </select>
                    </div>

                    <div className="filter-group">
                        <label>Agent ID</label>
                        <div className="search-input">
                            <Search size={14} />
                            <input
                                id="filter-agent-id"
                                placeholder="Filter by Agent ID…"
                                value={searchAgentId}
                                onChange={(e) => setSearchAgentId(e.target.value)}
                            />
                        </div>
                    </div>

                    <div className="filter-group">
                        <label>Campaign ID</label>
                        <div className="search-input">
                            <Search size={14} />
                            <input
                                id="filter-campaign-id"
                                placeholder="Filter by Campaign ID…"
                                value={searchCampaignId}
                                onChange={(e) => setSearchCampaignId(e.target.value)}
                            />
                        </div>
                    </div>

                    <div className="filter-group">
                        <label>From</label>
                        <input
                            id="filter-date-from"
                            type="date"
                            value={filters.date_from || ''}
                            onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value || undefined }))}
                        />
                    </div>

                    <div className="filter-group">
                        <label>To</label>
                        <input
                            id="filter-date-to"
                            type="date"
                            value={filters.date_to || ''}
                            onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value || undefined }))}
                        />
                    </div>

                    <button id="apply-filters-btn" className="btn-secondary" onClick={fetchArtifacts}>
                        <Filter size={14} /> Apply
                    </button>
                </div>
            </div>

            {error && <div className="error-banner">{error}</div>}

            {/* Artifact Grid */}
            {loading ? (
                <div className="loading-state">
                    <div className="pulse">Loading artifacts…</div>
                </div>
            ) : artifacts.length === 0 ? (
                <div className="empty-state glass">
                    <div className="empty-icon">📦</div>
                    <h3>No artifacts found</h3>
                    <p>Upload a file or adjust the filters. AI-generated files will appear here automatically.</p>
                </div>
            ) : (
                <div className="artifact-grid">
                    {artifacts.map((artifact) => {
                        const Icon = CATEGORY_ICON[artifact.file_category] || File;
                        const previewUrl = getPreviewUrl(artifact);
                        return (
                            <div
                                key={artifact.id}
                                className={`artifact-card glass artifact-type-${artifact.file_category}`}
                            >
                                <div className="artifact-card-header">
                                    <div className="artifact-type-badge">
                                        <Icon size={14} />
                                        <span>{artifact.file_category}</span>
                                    </div>
                                    <div className="artifact-actions">
                                        {/* Info tooltip */}
                                        {(artifact.purpose || artifact.generated_by) && (
                                            <div
                                                className="info-btn-wrapper"
                                                onMouseEnter={() => setTooltipId(artifact.id)}
                                                onMouseLeave={() => setTooltipId(null)}
                                            >
                                                <button className="icon-btn" title="Info">
                                                    <Info size={14} />
                                                </button>
                                                {tooltipId === artifact.id && (
                                                    <div className="artifact-tooltip-box">
                                                        {artifact.purpose && <p><strong>Purpose:</strong> {artifact.purpose}</p>}
                                                        {artifact.generated_by && <p><strong>Generated by:</strong> {artifact.generated_by}</p>}
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                        <button className="icon-btn" title="Download" onClick={() => handleDownload(artifact)}>
                                            <Download size={14} />
                                        </button>
                                        <button
                                            className="icon-btn danger"
                                            onClick={() => handleDelete(artifact.id)}
                                            title="Delete"
                                        >
                                            <Trash2 size={14} />
                                        </button>
                                    </div>
                                </div>

                                {/* Origin badge */}
                                <OriginBadge origin={artifact.origin} />

                                {/* Preview */}
                                <div className="artifact-preview">
                                    {artifact.file_category === 'images' && (
                                        <div
                                            className="image-preview"
                                            onClick={() => setLightboxSrc(previewUrl)}
                                            title="Click to enlarge"
                                        >
                                            <img src={previewUrl} alt={artifact.file_name} loading="lazy" />
                                            <div className="image-overlay"><ZoomIn size={20} /></div>
                                        </div>
                                    )}
                                    {artifact.file_category === 'videos' && (
                                        <video controls className="video-preview" src={previewUrl} />
                                    )}
                                    {artifact.file_category === 'recordings' && (
                                        <AudioPlayer src={previewUrl} />
                                    )}
                                    {(artifact.file_category === 'documents' || artifact.file_category === 'text') && (
                                        <div className="doc-preview">
                                            <Icon size={40} opacity={0.3} />
                                        </div>
                                    )}
                                </div>

                                {/* Metadata */}
                                <div className="artifact-meta">
                                    <p className="artifact-name" title={artifact.file_name}>{artifact.file_name}</p>
                                    <div className="artifact-meta-row">
                                        <span>{formatFileSize(artifact.file_size)}</span>
                                        {artifact.duration_seconds && <span>{formatDuration(artifact.duration_seconds)}</span>}
                                        <span>{parseServerDate(artifact.created_at).toLocaleDateString()}</span>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};

export default Artifacts;
