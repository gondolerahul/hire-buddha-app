import React, { useState, useEffect, useCallback } from 'react';
import {
    Search, Plus, Wrench, Edit, Trash2, Power, RefreshCw,
    AlertTriangle, X, Package, Zap, Settings
} from 'lucide-react';
import { toolService, ToolRegistryEntry, ToolRegistryEntryCreate, ToolRegistryEntryUpdate } from '@/services/tool.service';
import { JellyButton } from '@/components/ui/JellyButton';
import './ToolManagement.css';

const CATEGORIES = [
    { value: '', label: 'All Categories' },
    { value: 'browser', label: '🌐 Browser' },
    { value: 'document', label: '📄 Document' },
    { value: 'email', label: '📧 Email' },
    { value: 'execution', label: '⚡ Execution' },
    { value: 'media', label: '🎨 Media' },
    { value: 'search', label: '🔍 Search' },
    { value: 'social', label: '📱 Social' },
    { value: 'utility', label: '🔧 Utility' },
    { value: 'custom', label: '⭐ Custom' },
    { value: 'general', label: '📦 General' },
];

const TOOL_TYPE_FILTER = [
    { value: '', label: 'All Types' },
    { value: 'BUILT_IN', label: 'Built-in' },
    { value: 'CUSTOM', label: 'Custom' },
];

export const ToolManagement: React.FC = () => {
    const [tools, setTools] = useState<ToolRegistryEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [categoryFilter, setCategoryFilter] = useState('');
    const [typeFilter, setTypeFilter] = useState('');
    const [showModal, setShowModal] = useState(false);
    const [editingTool, setEditingTool] = useState<ToolRegistryEntry | null>(null);
    const [deleteTarget, setDeleteTarget] = useState<ToolRegistryEntry | null>(null);
    const [syncing, setSyncing] = useState(false);

    // Form state
    const [formName, setFormName] = useState('');
    const [formDisplayName, setFormDisplayName] = useState('');
    const [formDescription, setFormDescription] = useState('');
    const [formCategory, setFormCategory] = useState('custom');
    const [formSchema, setFormSchema] = useState('');
    const [formEnabled, setFormEnabled] = useState(true);
    const [formConfig, setFormConfig] = useState('');
    const [formError, setFormError] = useState('');

    const fetchTools = useCallback(async () => {
        try {
            setLoading(true);
            const data = await toolService.listTools();
            setTools(data);
        } catch (err) {
            console.error('Failed to fetch tools:', err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchTools();
    }, [fetchTools]);

    // ─── Filtering ──────────────────────────────────────────────────
    const filteredTools = tools.filter(tool => {
        const matchesSearch = !searchQuery ||
            tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            (tool.display_name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
            (tool.description || '').toLowerCase().includes(searchQuery.toLowerCase());
        const matchesCategory = !categoryFilter || tool.category === categoryFilter;
        const matchesType = !typeFilter || tool.tool_type === typeFilter;
        return matchesSearch && matchesCategory && matchesType;
    });

    const builtInCount = tools.filter(t => t.tool_type === 'BUILT_IN').length;
    const customCount = tools.filter(t => t.tool_type === 'CUSTOM').length;
    const enabledCount = tools.filter(t => t.is_enabled).length;

    // ─── Modal Handlers ─────────────────────────────────────────────
    const openCreateModal = () => {
        setEditingTool(null);
        setFormName('');
        setFormDisplayName('');
        setFormDescription('');
        setFormCategory('custom');
        setFormSchema('{\n  "name": "my_tool",\n  "description": "Description of my tool",\n  "parameters": {\n    "type": "object",\n    "properties": {},\n    "required": []\n  }\n}');
        setFormEnabled(true);
        setFormConfig('');
        setFormError('');
        setShowModal(true);
    };

    const openEditModal = (tool: ToolRegistryEntry) => {
        setEditingTool(tool);
        setFormName(tool.name);
        setFormDisplayName(tool.display_name || '');
        setFormDescription(tool.description || '');
        setFormCategory(tool.category || 'custom');
        setFormSchema(tool.function_schema ? JSON.stringify(tool.function_schema, null, 2) : '');
        setFormEnabled(tool.is_enabled);
        setFormConfig(tool.configuration ? JSON.stringify(tool.configuration, null, 2) : '');
        setFormError('');
        setShowModal(true);
    };

    const handleSave = async () => {
        setFormError('');

        if (!editingTool && !formName.trim()) {
            setFormError('Tool name is required.');
            return;
        }

        let parsedSchema = null;
        if (formSchema.trim()) {
            try {
                parsedSchema = JSON.parse(formSchema);
            } catch {
                setFormError('Function Schema is not valid JSON.');
                return;
            }
        }

        let parsedConfig = null;
        if (formConfig.trim()) {
            try {
                parsedConfig = JSON.parse(formConfig);
            } catch {
                setFormError('Configuration is not valid JSON.');
                return;
            }
        }

        try {
            if (editingTool && editingTool.id) {
                const updateData: ToolRegistryEntryUpdate = {
                    display_name: formDisplayName || undefined,
                    description: formDescription || undefined,
                    category: formCategory || undefined,
                    function_schema: parsedSchema || undefined,
                    is_enabled: formEnabled,
                    configuration: parsedConfig || undefined,
                };
                await toolService.updateTool(editingTool.id, updateData);
            } else {
                const createData: ToolRegistryEntryCreate = {
                    name: formName.trim(),
                    display_name: formDisplayName || undefined,
                    description: formDescription || undefined,
                    category: formCategory || undefined,
                    function_schema: parsedSchema || undefined,
                    is_enabled: formEnabled,
                    configuration: parsedConfig || undefined,
                };
                await toolService.createTool(createData);
            }
            setShowModal(false);
            fetchTools();
        } catch (err: any) {
            setFormError(err?.response?.data?.detail || 'Failed to save tool.');
        }
    };

    const handleDelete = async () => {
        if (!deleteTarget?.id) return;
        try {
            await toolService.deleteTool(deleteTarget.id);
            setDeleteTarget(null);
            fetchTools();
        } catch (err: any) {
            alert(err?.response?.data?.detail || 'Failed to delete tool.');
        }
    };

    const handleToggle = async (tool: ToolRegistryEntry) => {
        if (!tool.id) return;
        try {
            await toolService.toggleTool(tool.id);
            fetchTools();
        } catch (err) {
            console.error('Failed to toggle tool:', err);
        }
    };

    const handleSync = async () => {
        setSyncing(true);
        try {
            const result = await toolService.syncBuiltIn();
            alert(`Sync complete: ${result.created} new tool(s) registered.`);
            fetchTools();
        } catch (err) {
            console.error('Failed to sync built-in tools:', err);
        } finally {
            setSyncing(false);
        }
    };

    // ─── Render ─────────────────────────────────────────────────────
    return (
        <div className="tool-management-page">
            <div className="page-header">
                <h1><Wrench size={28} /> Tool Registry</h1>
                <div className="page-header-actions">
                    <JellyButton variant="ghost" onClick={handleSync} disabled={syncing}>
                        <RefreshCw size={16} className={syncing ? 'spin' : ''} />
                        {syncing ? 'Syncing...' : 'Sync Built-in'}
                    </JellyButton>
                    <JellyButton roseGold onClick={openCreateModal}>
                        <Plus size={16} /> Create Custom Tool
                    </JellyButton>
                </div>
            </div>

            {/* Stats */}
            <div className="tool-stats-bar">
                <div className="tool-stat-chip">
                    <Package size={16} />
                    <span>Total: <span className="stat-value">{tools.length}</span></span>
                </div>
                <div className="tool-stat-chip">
                    <Wrench size={16} />
                    <span>Built-in: <span className="stat-value">{builtInCount}</span></span>
                </div>
                <div className="tool-stat-chip">
                    <Zap size={16} />
                    <span>Custom: <span className="stat-value">{customCount}</span></span>
                </div>
                <div className="tool-stat-chip">
                    <Power size={16} />
                    <span>Enabled: <span className="stat-value">{enabledCount}/{tools.length}</span></span>
                </div>
            </div>

            {/* Filters */}
            <div className="tool-filter-bar">
                <div className="tool-search-input">
                    <Search size={16} />
                    <input
                        type="text"
                        placeholder="Search tools by name or description..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                    />
                </div>
                <select
                    className="tool-filter-select"
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                >
                    {CATEGORIES.map(c => (
                        <option key={c.value} value={c.value}>{c.label}</option>
                    ))}
                </select>
                <select
                    className="tool-filter-select"
                    value={typeFilter}
                    onChange={(e) => setTypeFilter(e.target.value)}
                >
                    {TOOL_TYPE_FILTER.map(t => (
                        <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                </select>
            </div>

            {/* Tool Cards */}
            {loading ? (
                <div className="tool-loading">Loading tools...</div>
            ) : filteredTools.length === 0 ? (
                <div className="tool-empty-state">
                    <Wrench size={48} />
                    <h3>No tools found</h3>
                    <p>Try adjusting your search or filters.</p>
                </div>
            ) : (
                <div className="tool-cards-grid">
                    {filteredTools.map((tool) => (
                        <div key={tool.name} className={`tool-card ${!tool.is_enabled ? 'disabled' : ''}`}>
                            <div className="tool-card-header">
                                <div className="tool-card-title">
                                    <Wrench size={18} />
                                    <h3>{tool.display_name || tool.name}</h3>
                                </div>
                                <div className="tool-card-badges">
                                    <span className={`badge ${tool.tool_type === 'BUILT_IN' ? 'badge-builtin' : 'badge-custom'}`}>
                                        {tool.tool_type === 'BUILT_IN' ? 'Built-in' : 'Custom'}
                                    </span>
                                    {tool.category && (
                                        <span className="badge badge-category">{tool.category}</span>
                                    )}
                                    <span className={`badge ${tool.is_enabled ? 'badge-enabled' : 'badge-disabled'}`}>
                                        {tool.is_enabled ? 'Enabled' : 'Disabled'}
                                    </span>
                                </div>
                            </div>

                            <div className="tool-card-name">{tool.name}</div>
                            <div className="tool-card-description">
                                {tool.description || 'No description available.'}
                            </div>

                            <div className="tool-card-actions">
                                {tool.id && (
                                    <>
                                        <button onClick={() => handleToggle(tool)} title={tool.is_enabled ? 'Disable' : 'Enable'}>
                                            <Power size={14} /> {tool.is_enabled ? 'Disable' : 'Enable'}
                                        </button>
                                        <button onClick={() => openEditModal(tool)}>
                                            <Edit size={14} /> Edit
                                        </button>
                                        {tool.tool_type === 'CUSTOM' && (
                                            <button className="btn-danger" onClick={() => setDeleteTarget(tool)}>
                                                <Trash2 size={14} /> Delete
                                            </button>
                                        )}
                                    </>
                                )}
                                {!tool.id && (
                                    <span style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>
                                        Click "Sync Built-in" to enable management
                                    </span>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Create/Edit Modal */}
            {showModal && (
                <div className="tool-modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="tool-modal" onClick={(e) => e.stopPropagation()}>
                        <h2>
                            {editingTool ? <><Edit size={20} /> Edit Tool</> : <><Plus size={20} /> Create Custom Tool</>}
                        </h2>

                        {formError && (
                            <div style={{ padding: '0.75rem', marginBottom: '1rem', borderRadius: '8px', background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)', color: '#f87171', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <AlertTriangle size={16} /> {formError}
                            </div>
                        )}

                        <div className="form-row">
                            <div className="form-group">
                                <label>Tool Name *</label>
                                <input
                                    type="text"
                                    value={formName}
                                    onChange={(e) => setFormName(e.target.value)}
                                    placeholder="my_custom_tool"
                                    disabled={!!editingTool}
                                />
                                <small>Unique identifier, lowercase with underscores</small>
                            </div>
                            <div className="form-group">
                                <label>Display Name</label>
                                <input
                                    type="text"
                                    value={formDisplayName}
                                    onChange={(e) => setFormDisplayName(e.target.value)}
                                    placeholder="My Custom Tool"
                                />
                            </div>
                        </div>

                        <div className="form-row">
                            <div className="form-group">
                                <label>Category</label>
                                <select value={formCategory} onChange={(e) => setFormCategory(e.target.value)}>
                                    {CATEGORIES.filter(c => c.value).map(c => (
                                        <option key={c.value} value={c.value}>{c.label}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="form-group">
                                <label>Enabled</label>
                                <select value={formEnabled ? 'true' : 'false'} onChange={(e) => setFormEnabled(e.target.value === 'true')}>
                                    <option value="true">✅ Enabled</option>
                                    <option value="false">❌ Disabled</option>
                                </select>
                            </div>
                        </div>

                        <div className="form-group">
                            <label>Description</label>
                            <textarea
                                value={formDescription}
                                onChange={(e) => setFormDescription(e.target.value)}
                                placeholder="Describe what this tool does..."
                                rows={3}
                            />
                        </div>

                        <div className="form-group">
                            <label>Function Schema (JSON)</label>
                            <textarea
                                value={formSchema}
                                onChange={(e) => setFormSchema(e.target.value)}
                                placeholder='{"name": "...", "description": "...", "parameters": {...}}'
                                rows={10}
                                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.82rem' }}
                            />
                            <small>OpenAI-compatible function calling schema</small>
                        </div>

                        <div className="form-group">
                            <label>Configuration (JSON, optional)</label>
                            <textarea
                                value={formConfig}
                                onChange={(e) => setFormConfig(e.target.value)}
                                placeholder='{"api_key_ref": "TOOL_API_KEY", "base_url": "..."}'
                                rows={4}
                                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.82rem' }}
                            />
                            <small>Custom configuration for the tool (API keys, endpoints, etc.)</small>
                        </div>

                        <div className="tool-modal-actions">
                            <JellyButton variant="ghost" onClick={() => setShowModal(false)}>Cancel</JellyButton>
                            <JellyButton roseGold onClick={handleSave}>
                                {editingTool ? 'Update Tool' : 'Create Tool'}
                            </JellyButton>
                        </div>
                    </div>
                </div>
            )}

            {/* Delete Confirmation */}
            {deleteTarget && (
                <div className="delete-confirm-overlay" onClick={() => setDeleteTarget(null)}>
                    <div className="delete-confirm-dialog" onClick={(e) => e.stopPropagation()}>
                        <h3><AlertTriangle size={20} /> Delete Tool</h3>
                        <p>Are you sure you want to delete <strong>{deleteTarget.display_name || deleteTarget.name}</strong>? This action cannot be undone.</p>
                        <div className="delete-confirm-actions">
                            <JellyButton variant="ghost" onClick={() => setDeleteTarget(null)}>Cancel</JellyButton>
                            <JellyButton variant="danger" onClick={handleDelete}>Delete</JellyButton>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
