import { parseServerDate } from '@/utils/datetime';
import React, { useState, useRef, useEffect } from 'react';
import { GlassCard, JellyButton } from '@/components/ui';
import { Upload, FileText, Trash2, Loader, Search } from 'lucide-react';
import { apiClient } from '@/services/api.client';
import './KnowledgeBase.css';

interface Document {
    id: string;
    filename: string;
    file_type: string;
    file_size?: string;
    upload_status: 'processing' | 'completed' | 'failed';
    created_at: string;
    updated_at: string;
}

interface SearchResult {
    chunk_id: string;
    document_id: string;
    filename: string;
    content: string;
    similarity: number;
}

export const KnowledgeBase: React.FC = () => {
    const [documents, setDocuments] = useState<Document[]>([]);
    const [uploading, setUploading] = useState(false);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
    const [searching, setSearching] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        loadDocuments();
    }, []);

    const loadDocuments = async () => {
        try {
            const { data } = await apiClient.get('/ai/documents');
            setDocuments(data);
        } catch (error) {
            console.error('Failed to load documents:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files;
        if (!files || files.length === 0) return;

        setUploading(true);

        for (const file of Array.from(files)) {
            try {
                // Create FormData for multipart/form-data upload
                const formData = new FormData();
                formData.append('file', file);

                const { data } = await apiClient.post('/ai/documents/upload', formData, {
                    headers: {
                        'Content-Type': 'multipart/form-data',
                    },
                });

                console.log('Document uploaded:', data);
                await loadDocuments();
            } catch (error) {
                console.error('Upload failed:', error);
            }
        }

        setUploading(false);
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    const handleSearch = async () => {
        if (!searchQuery.trim()) {
            setSearchResults([]);
            return;
        }

        setSearching(true);
        try {
            const { data } = await apiClient.post('/ai/documents/search', null, {
                params: {
                    query: searchQuery,
                    top_k: 5
                }
            });
            setSearchResults(data);
        } catch (error) {
            console.error('Search failed:', error);
        } finally {
            setSearching(false);
        }
    };

    const handleDelete = async (id: string) => {
        if (window.confirm('Are you sure you want to delete this document?')) {
            try {
                await apiClient.delete(`/ai/documents/${id}`);
                await loadDocuments();
            } catch (error) {
                console.error('Delete failed:', error);
            }
        }
    };

    const formatFileSize = (sizeStr?: string) => {
        if (!sizeStr) return 'Unknown';
        const bytes = parseInt(sizeStr);
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    };

    const formatDate = (dateString: string) => {
        return parseServerDate(dateString).toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
        });
    };

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
            case 'failed':
                return <span className="status-badge failed">✕ Failed</span>;
            default:
                return null;
        }
    };

    return (
        <div className="page-container knowledge-base">
            <header className="page-header">
                <div>
                    <h1>Knowledge Base</h1>
                    <p>Power your AI with structured document context (RAG)</p>
                </div>
                <JellyButton roseGold onClick={() => fileInputRef.current?.click()}>
                    <Upload size={18} /> Add Documents
                </JellyButton>
            </header>

            {uploading && (
                <GlassCard className="mb-8 p-4 border-rose-gold/30">
                    <div className="flex items-center gap-4">
                        <Loader className="spin text-rose-gold" size={24} />
                        <span className="font-medium">Ingesting knowledge...</span>
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
                        onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
                        className="flex-1 bg-transparent border-none outline-none text-white py-2"
                    />
                    <JellyButton
                        variant="secondary"
                        onClick={handleSearch}
                        disabled={searching}
                        className="rounded-full"
                    >
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
                        <p>No knowledge assets found in scope.</p>
                    </GlassCard>
                ) : (
                    documents.map((doc) => (
                        <GlassCard key={doc.id} hover className="glass-card-item">
                            <div className="card-header">
                                <div className="card-icon" style={{ color: 'var(--color-rose-gold)' }}>
                                    <FileText size={20} />
                                </div>
                                <div className="card-info">
                                    <div className="card-title-row">
                                        <h3 title={doc.filename}>{doc.filename}</h3>
                                    </div>
                                    <div className="card-badge-row">
                                        {getStatusBadge(doc.upload_status)}
                                    </div>
                                </div>
                            </div>

                            <div className="card-description">
                                ID: {doc.id.slice(0, 8)}...
                            </div>

                            <div className="card-meta">
                                <span className="meta-item">
                                    <FileText size={12} /> {formatFileSize(doc.file_size)}
                                </span>
                                <span className="meta-item">
                                    {doc.file_type.toUpperCase()}
                                </span>
                                <span className="meta-item">
                                    {formatDate(doc.created_at)}
                                </span>
                            </div>

                            <div className="card-actions">
                                <JellyButton
                                    variant="ghost"
                                    onClick={() => handleDelete(doc.id)}
                                    className="w-full text-red-400 hover:text-red-300"
                                >
                                    <Trash2 size={16} /> Purge Asset
                                </JellyButton>
                            </div>
                        </GlassCard>
                    )))}
            </div>

            <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.txt"
                multiple
                onChange={handleFileSelect}
                style={{ display: 'none' }}
            />
        </div>
    );
};
