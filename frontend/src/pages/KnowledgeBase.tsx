import { parseServerDate } from '@/utils/datetime';
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { GlassCard, JellyButton } from '@/components/ui';
import { Upload, FileText, Trash2, Loader, Search, Eye, Pencil, RefreshCw, X, Globe, Bot } from 'lucide-react';
import { apiClient } from '@/services/api.client';
import { useAuth } from '@/hooks/useAuth';
import './KnowledgeBase.css';

// A knowledge-base document: a `documents` row whose content is ingested into a
// CORTEX Knowledge Tree — the scoped agent's, or the company-wide one.
interface Document {
    id: string;
    entity_id: string | null;
    entity_name: string | null;
    filename: string;
    file_type: string;
    file_size?: number;
    upload_status: 'processing' | 'completed' | 'partial' | 'failed';
    created_at: string;
    updated_at: string;
}

interface DocumentDetail extends Document {
    chunks_total: number;
    chunks_embedded: number;
    sections: string[];
    preview: string;
    preview_truncated: boolean;
}

interface SearchResult {
    chunk_id: string;
    document_id: string;
    filename: string;
    content: string;
    similarity: number;
}

interface AgentOption {
    id: string;
    name: string;
}

const COMPANY_WIDE = '';
const ACCEPTED_TYPES = '.pdf,.docx,.txt,.md';

const errorText = (error: any, fallback: string): string => {
    const detail = error?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
    return fallback;
};

export const KnowledgeBase: React.FC = () => {
    const { user } = useAuth();
    const [documents, setDocuments] = useState<Document[]>([]);
    const [agents, setAgents] = useState<AgentOption[]>([]);
    const [uploadScope, setUploadScope] = useState<string>(COMPANY_WIDE);
    const [uploading, setUploading] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
    const [searching, setSearching] = useState(false);
    const [viewing, setViewing] = useState<DocumentDetail | null>(null);
    const [editing, setEditing] = useState<{ doc: Document; filename: string; scope: string } | null>(null);
    const [saving, setSaving] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const replaceInputRef = useRef<HTMLInputElement>(null);
    const replaceTarget = useRef<string | null>(null);

    const loadDocuments = useCallback(async () => {
        try {
            const { data } = await apiClient.get<Document[]>('/ai/documents');
            setDocuments(data);
        } catch (err) {
            setError(errorText(err, 'Failed to load documents'));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadDocuments();
    }, [loadDocuments]);

    // Agents a document can be scoped to: this company's own.
    useEffect(() => {
        if (!user?.company_id) return;
        apiClient.get('/ai/entities', { params: { company_id: user.company_id } })
            .then(({ data }) => setAgents(
                (data as any[])
                    .filter(e => e.company_id === user.company_id)
                    .map(e => ({ id: e.id, name: e.display_name || e.name }))
            ))
            .catch(() => setAgents([]));
    }, [user?.company_id]);

    // Ingestion runs on the worker; refresh while anything is still processing.
    useEffect(() => {
        if (!documents.some(d => d.upload_status === 'processing')) return;
        const timer = setTimeout(loadDocuments, 3000);
        return () => clearTimeout(timer);
    }, [documents, loadDocuments]);

    const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files;
        if (!files || files.length === 0) return;
        setUploading(true);
        setError(null);
        for (const file of Array.from(files)) {
            try {
                const formData = new FormData();
                formData.append('file', file);
                await apiClient.post('/ai/documents/upload', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                    params: uploadScope ? { entity_id: uploadScope } : undefined,
                });
            } catch (err) {
                setError(errorText(err, `Upload of ${file.name} failed`));
            }
        }
        await loadDocuments();
        setUploading(false);
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    const handleSearch = async () => {
        if (!searchQuery.trim()) {
            setSearchResults([]);
            return;
        }
        setSearching(true);
        try {
            const { data } = await apiClient.post('/ai/documents/search', null, {
                params: { query: searchQuery, top_k: 5 },
            });
            setSearchResults(data);
        } catch (err) {
            setError(errorText(err, 'Search failed'));
        } finally {
            setSearching(false);
        }
    };

    const handleView = async (id: string) => {
        try {
            const { data } = await apiClient.get<DocumentDetail>(`/ai/documents/${id}`);
            setViewing(data);
        } catch (err) {
            setError(errorText(err, 'Could not open the document'));
        }
    };

    const handleSaveEdit = async () => {
        if (!editing) return;
        const body: Record<string, unknown> = {};
        if (editing.filename.trim() !== editing.doc.filename) body.filename = editing.filename.trim();
        if (editing.scope !== (editing.doc.entity_id || COMPANY_WIDE)) body.entity_id = editing.scope || null;
        if (Object.keys(body).length === 0) {
            setEditing(null);
            return;
        }
        setSaving(true);
        try {
            await apiClient.patch(`/ai/documents/${editing.doc.id}`, body);
            setEditing(null);
            await loadDocuments();
        } catch (err) {
            setError(errorText(err, 'Could not save the document'));
        } finally {
            setSaving(false);
        }
    };

    const startReplace = (id: string) => {
        replaceTarget.current = id;
        replaceInputRef.current?.click();
    };

    const handleReplace = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        const id = replaceTarget.current;
        if (replaceInputRef.current) replaceInputRef.current.value = '';
        if (!file || !id) return;
        try {
            const formData = new FormData();
            formData.append('file', file);
            await apiClient.post(`/ai/documents/${id}/file`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            await loadDocuments();
        } catch (err) {
            setError(errorText(err, 'Could not replace the file'));
        }
    };

    const handleDelete = async (doc: Document) => {
        if (!window.confirm(`Delete "${doc.filename}"? Agents will no longer find it in their knowledge.`)) return;
        try {
            await apiClient.delete(`/ai/documents/${doc.id}`);
            setSearchResults(prev => prev.filter(r => r.document_id !== doc.id));
            await loadDocuments();
        } catch (err) {
            setError(errorText(err, 'Delete failed'));
        }
    };

    const formatFileSize = (bytes?: number) => {
        if (bytes == null) return 'Unknown';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    };

    const formatDate = (dateString: string) =>
        parseServerDate(dateString).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });

    const getStatusBadge = (status: string) => {
        switch (status) {
            case 'processing':
                return (
                    <span className="status-badge processing">
                        <Loader className="spin" size={14} />
                        Processing
                    </span>
                );
            case 'completed':
                return <span className="status-badge ready">● Ready</span>;
            case 'partial':
                return <span className="status-badge processing">◐ Partly searchable</span>;
            case 'failed':
                return <span className="status-badge failed">✕ Failed</span>;
            default:
                return null;
        }
    };

    const scopeLabel = (doc: Document) =>
        doc.entity_id ? (
            <span className="meta-item" title="Only this agent reads it"><Bot size={12} /> {doc.entity_name || 'Agent'}</span>
        ) : (
            <span className="meta-item" title="Every agent in the company reads it"><Globe size={12} /> Company-wide</span>
        );

    const scopeOptions = (
        <>
            <option value={COMPANY_WIDE}>Company-wide (every agent)</option>
            {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </>
    );

    return (
        <div className="page-container knowledge-base">
            <header className="page-header">
                <div>
                    <h1>Knowledge Base</h1>
                    <p>Documents your agents draw on, stored in their CORTEX Knowledge Trees</p>
                </div>
                <div className="kb-upload-controls">
                    <select
                        className="kb-select"
                        value={uploadScope}
                        onChange={e => setUploadScope(e.target.value)}
                        aria-label="Scope for new documents"
                    >
                        {scopeOptions}
                    </select>
                    <JellyButton roseGold onClick={() => fileInputRef.current?.click()}>
                        <Upload size={18} /> Add Documents
                    </JellyButton>
                </div>
            </header>

            {error && (
                <GlassCard className="mb-6 p-4 kb-error">
                    <div className="flex items-center justify-between gap-4">
                        <span>{error}</span>
                        <button type="button" onClick={() => setError(null)} aria-label="Dismiss"><X size={16} /></button>
                    </div>
                </GlassCard>
            )}

            {uploading && (
                <GlassCard className="mb-8 p-4 border-rose-gold/30">
                    <div className="flex items-center gap-4">
                        <Loader className="spin text-rose-gold" size={24} />
                        <span className="font-medium">Uploading...</span>
                    </div>
                </GlassCard>
            )}

            <div className="mb-6">
                <div className="search-bar-wrapper glass-effect p-2 rounded-full flex items-center gap-2 max-w-2xl">
                    <div className="pl-4 text-tertiary">
                        <Search size={20} />
                    </div>
                    <input
                        type="text"
                        placeholder="Search across all documents using semantic search..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                        className="flex-1 bg-transparent border-none outline-none text-white py-2"
                    />
                    <JellyButton variant="secondary" onClick={handleSearch} disabled={searching} className="rounded-full">
                        {searching ? <Loader className="spin" size={16} /> : 'Search'}
                    </JellyButton>
                </div>

                {searchResults.length > 0 && (
                    <div className="search-results mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
                        {searchResults.map((result) => (
                            <GlassCard key={result.chunk_id} className="p-4 bg-white/5 border-white/10">
                                <div className="flex items-center justify-between mb-2">
                                    <div className="flex items-center gap-2 text-rose-gold">
                                        <FileText size={16} />
                                        <span className="text-sm font-semibold truncate max-w-[150px]">{result.filename}</span>
                                    </div>
                                    <div className="badge badge-ready scale-75">
                                        {(result.similarity * 100).toFixed(0)}% MATCH
                                    </div>
                                </div>
                                <p className="text-sm text-secondary line-clamp-3 leading-relaxed">{result.content}</p>
                            </GlassCard>
                        ))}
                    </div>
                )}
            </div>

            <div className="standard-grid">
                {loading ? (
                    Array(3).fill(0).map((_, i) => (
                        <GlassCard key={i} className="glass-card-item opacity-50 pulse">
                            <div className="w-full h-32"></div>
                        </GlassCard>
                    ))
                ) : documents.length === 0 ? (
                    <GlassCard className="empty-state">
                        <FileText size={64} className="mb-4" />
                        <p>No documents yet. Add one to give your agents knowledge.</p>
                    </GlassCard>
                ) : (
                    documents.map((doc) => {
                        const busy = doc.upload_status === 'processing';
                        return (
                            <GlassCard key={doc.id} hover className="glass-card-item">
                                <div className="card-header">
                                    <div className="card-icon" style={{ color: 'var(--color-rose-gold)' }}>
                                        <FileText size={20} />
                                    </div>
                                    <div className="card-info">
                                        <div className="card-title-row">
                                            <h3 title={doc.filename}>{doc.filename}</h3>
                                        </div>
                                        <div className="card-badge-row">{getStatusBadge(doc.upload_status)}</div>
                                    </div>
                                </div>

                                <div className="card-meta">
                                    {scopeLabel(doc)}
                                    <span className="meta-item"><FileText size={12} /> {formatFileSize(doc.file_size)}</span>
                                    <span className="meta-item">{doc.file_type.toUpperCase()}</span>
                                    <span className="meta-item">{formatDate(doc.created_at)}</span>
                                </div>

                                <div className="card-actions kb-actions">
                                    <JellyButton variant="ghost" onClick={() => handleView(doc.id)} title="View what was ingested">
                                        <Eye size={16} />
                                    </JellyButton>
                                    <JellyButton
                                        variant="ghost"
                                        disabled={busy}
                                        onClick={() => setEditing({ doc, filename: doc.filename, scope: doc.entity_id || COMPANY_WIDE })}
                                        title="Rename or change scope"
                                    >
                                        <Pencil size={16} />
                                    </JellyButton>
                                    <JellyButton variant="ghost" disabled={busy} onClick={() => startReplace(doc.id)} title="Replace the file">
                                        <RefreshCw size={16} />
                                    </JellyButton>
                                    <JellyButton
                                        variant="ghost"
                                        onClick={() => handleDelete(doc)}
                                        className="text-red-400 hover:text-red-300"
                                        title="Delete"
                                    >
                                        <Trash2 size={16} />
                                    </JellyButton>
                                </div>
                            </GlassCard>
                        );
                    })
                )}
            </div>

            {viewing && (
                <div className="modal-overlay" onClick={() => setViewing(null)}>
                    <div className="kb-modal glass" onClick={e => e.stopPropagation()} role="dialog" aria-label={viewing.filename}>
                        <div className="kb-modal-header">
                            <h3 title={viewing.filename}>{viewing.filename}</h3>
                            <button type="button" onClick={() => setViewing(null)} aria-label="Close"><X size={18} /></button>
                        </div>
                        <div className="card-meta">
                            {scopeLabel(viewing)}
                            <span className="meta-item">{viewing.chunks_embedded}/{viewing.chunks_total} chunks searchable</span>
                            <span className="meta-item">{viewing.sections.length} sections</span>
                        </div>
                        {viewing.sections.length > 0 && (
                            <div className="kb-sections">
                                <div className="kb-label">Sections</div>
                                <ol>{viewing.sections.map((s, i) => <li key={i}>{s}</li>)}</ol>
                            </div>
                        )}
                        <div className="kb-label">Ingested text{viewing.preview_truncated ? ' (beginning)' : ''}</div>
                        <pre className="kb-preview">{viewing.preview || 'No text was extracted from this document.'}</pre>
                    </div>
                </div>
            )}

            {editing && (
                <div className="modal-overlay" onClick={() => !saving && setEditing(null)}>
                    <div className="kb-modal glass" onClick={e => e.stopPropagation()} role="dialog" aria-label="Edit document">
                        <div className="kb-modal-header">
                            <h3>Edit document</h3>
                            <button type="button" onClick={() => setEditing(null)} aria-label="Close"><X size={18} /></button>
                        </div>
                        <label className="kb-label" htmlFor="kb-filename">Name</label>
                        <input
                            id="kb-filename"
                            className="kb-input"
                            value={editing.filename}
                            onChange={e => setEditing({ ...editing, filename: e.target.value })}
                        />
                        <label className="kb-label" htmlFor="kb-scope">Who can use it</label>
                        <select
                            id="kb-scope"
                            className="kb-select kb-input"
                            value={editing.scope}
                            onChange={e => setEditing({ ...editing, scope: e.target.value })}
                        >
                            {scopeOptions}
                        </select>
                        <div className="kb-modal-actions">
                            <JellyButton variant="ghost" onClick={() => setEditing(null)} disabled={saving}>Cancel</JellyButton>
                            <JellyButton roseGold onClick={handleSaveEdit} disabled={saving || !editing.filename.trim()}>
                                {saving ? <Loader className="spin" size={16} /> : 'Save'}
                            </JellyButton>
                        </div>
                    </div>
                </div>
            )}

            <input ref={fileInputRef} type="file" accept={ACCEPTED_TYPES} multiple onChange={handleFileSelect} style={{ display: 'none' }} />
            <input ref={replaceInputRef} type="file" accept={ACCEPTED_TYPES} onChange={handleReplace} style={{ display: 'none' }} />
        </div>
    );
};
