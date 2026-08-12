import React, { useState, useEffect } from 'react';
import { apiClient } from '@/services/api.client';
import { Search, Wrench, CheckSquare, Square } from 'lucide-react';
import './ToolSelectionPanel.css';

interface Tool {
    name: string;
    display_name?: string;
    description: string;
    category?: string;
    tool_type?: string;
    is_enabled?: boolean;
}

interface ToolSelectionPanelProps {
    selectedTools: string[];
    onChange: (tools: string[]) => void;
}

export const ToolSelectionPanel: React.FC<ToolSelectionPanelProps> = ({ selectedTools, onChange }) => {
    const [tools, setTools] = useState<Tool[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');

    useEffect(() => {
        fetchTools();
    }, []);

    const fetchTools = async () => {
        try {
            const { data } = await apiClient.get<Tool[]>('/ai/tools');
            setTools(data);
        } catch (error) {
            console.error('Failed to fetch tools:', error);
        } finally {
            setLoading(false);
        }
    };

    const toggleTool = (toolName: string) => {
        if (selectedTools.includes(toolName)) {
            onChange(selectedTools.filter(t => t !== toolName));
        } else {
            onChange([...selectedTools, toolName]);
        }
    };

    const filteredTools = tools
        .filter(tool => tool.is_enabled !== false)
        .filter(tool =>
            tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            tool.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
            (tool.display_name || '').toLowerCase().includes(searchQuery.toLowerCase())
        );

    if (loading) {
        return <div className="tool-selection-loading">Loading tools...</div>;
    }

    return (
        <div className="tool-selection-panel">
            <div className="tool-search">
                <Search size={16} />
                <input
                    type="text"
                    placeholder="Search tools..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                />
            </div>

            <div className="tool-list">
                {filteredTools.length === 0 ? (
                    <div className="tool-empty">No tools found</div>
                ) : (
                    filteredTools.map((tool) => {
                        const isSelected = selectedTools.includes(tool.name);
                        return (
                            <div
                                key={tool.name}
                                className={`tool-item ${isSelected ? 'selected' : ''}`}
                                onClick={() => toggleTool(tool.name)}
                            >
                                <div className="tool-item-header">
                                    <div className="tool-item-icon">
                                        {isSelected ? <CheckSquare size={18} /> : <Square size={18} />}
                                        <Wrench size={16} />
                                    </div>
                                    <div className="tool-item-name">{tool.display_name || tool.name}</div>
                                    {tool.category && (
                                        <span className="tool-item-category">{tool.category}</span>
                                    )}
                                </div>
                                <div className="tool-item-description">{tool.description}</div>
                            </div>
                        );
                    })
                )}
            </div>

            <div className="tool-selection-summary">
                {selectedTools.length} tool{selectedTools.length !== 1 ? 's' : ''} selected
            </div>
        </div>
    );
};

