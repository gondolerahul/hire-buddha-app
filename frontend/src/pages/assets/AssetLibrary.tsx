import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { LucideIcon } from 'lucide-react';
import { Search, Upload, Filter, Image, Video, Mic, Download, Trash2, X, Play, Pause, ZoomIn } from 'lucide-react';
import { assetService, Asset, AssetListFilters } from '@/services/asset.service';
import './AssetLibrary.css';

const FILE_TYPE_OPTIONS = [
    { value: '', label: 'All Types' },
    { value: 'recordings', label: 'Recordings' },
    { value: 'images', label: 'Images' },
    { value: 'videos', label: 'Videos' },
];

const FILE_TYPE_ICON: Record<string, LucideIcon> = {
    recordings: Mic,
    images: Image,
    videos: Video,
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
            <img src={src} alt="Asset preview" className="lightbox-img" />
        </div>
    </div>
);

// ─── Main Component ──────────────────────────────────────────────────────────

export const AssetLibrary: React.FC = () => {
    const [assets, setAssets] = useState<Asset[]>([]);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
    const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [filters, setFilters] = useState<AssetListFilters>({
        file_type: undefined,
        date_from: undefined,
        date_to: undefined,
        limit: 50,
        offset: 0,
    });
    const [searchAgentId, setSearchAgentId] = useState('');
    const [searchCampaignId, setSearchCampaignId] = useState('');
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [uploadType, setUploadType] = useState<'recordings' | 'images' | 'videos'>('images');

    const fetchAssets = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const f: AssetListFilters = { ...filters };
            if (searchAgentId.trim()) f.agent_id = searchAgentId.trim();
            if (searchCampaignId.trim()) f.campaign_id = searchCampaignId.trim();
            const res = await assetService.list(f);
            setAssets(res.assets);
        } catch (e: any) {
            setError(e?.response?.data?.detail || 'Failed to load assets');
        } finally {
            setLoading(false);
        }
    }, [filters, searchAgentId, searchCampaignId]);

    useEffect(() => { fetchAssets(); }, [fetchAssets]);

    const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setUploading(true);
        try {
            await assetService.upload(file, uploadType);
            fetchAssets();
        } catch (err: any) {
            setError(err?.response?.data?.detail || 'Upload failed');
        } finally {
            setUploading(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    const handleDelete = async (id: string) => {
        if (!confirm('Delete this asset permanently?')) return;
        await assetService.delete(id);
        setAssets((prev) => prev.filter((a) => a.id !== id));
    };

    const getDownloadUrl = (asset: Asset) => {
        const base = import.meta.env.VITE_API_URL || '';
        return `${base}/api/v1/assets/${asset.id}/download`;
    };

    return (
        <div className="asset-library-page">
            {lightboxSrc && <Lightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />}

            <div className="page-header">
                <div>
                    <h1 className="page-title">Asset Library</h1>
                    <p className="page-subtitle">Manage recordings, images, and videos generated by Agents</p>
                </div>
                <div className="upload-area">
                    <select
                        className="upload-type-select"
                        value={uploadType}
                        onChange={(e) => setUploadType(e.target.value as any)}
                    >
                        <option value="recordings">Recording</option>
                        <option value="images">Image</option>
                        <option value="videos">Video</option>
                    </select>
                    <button
                        className="btn-primary"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={uploading}
                    >
                        <Upload size={16} />
                        {uploading ? 'Uploading…' : 'Upload Asset'}
                    </button>
                    <input ref={fileInputRef} type="file" hidden onChange={handleUpload} />
                </div>
            </div>

            {/* Filters */}
            <div className="filter-panel glass">
                <div className="filter-row">
                    <div className="filter-group">
                        <label>Asset Type</label>
                        <select
                            value={filters.file_type || ''}
                            onChange={(e) => setFilters((f) => ({ ...f, file_type: e.target.value as any || undefined }))}
                        >
                            {FILE_TYPE_OPTIONS.map((o) => (
                                <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                        </select>
                    </div>

                    <div className="filter-group">
                        <label>Agent ID</label>
                        <div className="search-input">
                            <Search size={14} />
                            <input
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
                                placeholder="Filter by Campaign ID…"
                                value={searchCampaignId}
                                onChange={(e) => setSearchCampaignId(e.target.value)}
                            />
                        </div>
                    </div>

                    <div className="filter-group">
                        <label>From</label>
                        <input
                            type="date"
                            value={filters.date_from || ''}
                            onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value || undefined }))}
                        />
                    </div>

                    <div className="filter-group">
                        <label>To</label>
                        <input
                            type="date"
                            value={filters.date_to || ''}
                            onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value || undefined }))}
                        />
                    </div>

                    <button className="btn-secondary" onClick={fetchAssets}>
                        <Filter size={14} /> Apply
                    </button>
                </div>
            </div>

            {error && <div className="error-banner">{error}</div>}

            {/* Asset Grid */}
            {loading ? (
                <div className="loading-state">
                    <div className="pulse">Loading assets…</div>
                </div>
            ) : assets.length === 0 ? (
                <div className="empty-state glass">
                    <div className="empty-icon">📁</div>
                    <h3>No assets found</h3>
                    <p>Upload your first asset or adjust the filters.</p>
                </div>
            ) : (
                <div className="asset-grid">
                    {assets.map((asset) => {
                        const Icon = FILE_TYPE_ICON[asset.file_type] || Image;
                        const downloadUrl = getDownloadUrl(asset);
                        return (
                            <div key={asset.id} className={`asset-card glass asset-type-${asset.file_type}`}>
                                <div className="asset-card-header">
                                    <div className="asset-type-badge">
                                        <Icon size={14} />
                                        <span>{asset.file_type}</span>
                                    </div>
                                    <div className="asset-actions">
                                        <a href={downloadUrl} download={asset.file_name} target="_blank" rel="noreferrer">
                                            <button className="icon-btn" title="Download"><Download size={14} /></button>
                                        </a>
                                        <button className="icon-btn danger" onClick={() => handleDelete(asset.id)} title="Delete">
                                            <Trash2 size={14} />
                                        </button>
                                    </div>
                                </div>

                                <div className="asset-preview">
                                    {asset.file_type === 'images' && (
                                        <div
                                            className="image-preview"
                                            onClick={() => setLightboxSrc(downloadUrl)}
                                            title="Click to enlarge"
                                        >
                                            <img src={downloadUrl} alt={asset.file_name} loading="lazy" />
                                            <div className="image-overlay"><ZoomIn size={20} /></div>
                                        </div>
                                    )}
                                    {asset.file_type === 'videos' && (
                                        <video controls className="video-preview" src={downloadUrl} />
                                    )}
                                    {asset.file_type === 'recordings' && (
                                        <AudioPlayer src={downloadUrl} />
                                    )}
                                </div>

                                <div className="asset-meta">
                                    <p className="asset-name" title={asset.file_name}>{asset.file_name}</p>
                                    <div className="asset-meta-row">
                                        <span>{formatFileSize(asset.file_size)}</span>
                                        {asset.duration_seconds && <span>{formatDuration(asset.duration_seconds)}</span>}
                                        <span>{parseServerDate(asset.created_at).toLocaleDateString()}</span>
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
