import { apiClient } from './api.client';

export interface ToolRegistryEntry {
    id: string | null;
    name: string;
    display_name: string | null;
    description: string | null;
    category: string | null;
    tool_type: 'BUILT_IN' | 'CUSTOM';
    function_schema: Record<string, any> | null;
    is_enabled: boolean;
    configuration?: Record<string, any> | null;
    created_by?: string | null;
    created_at: string | null;
    updated_at: string | null;
}

export interface ToolRegistryEntryCreate {
    name: string;
    display_name?: string;
    description?: string;
    category?: string;
    function_schema?: Record<string, any>;
    is_enabled?: boolean;
    configuration?: Record<string, any>;
}

export interface ToolRegistryEntryUpdate {
    display_name?: string;
    description?: string;
    category?: string;
    function_schema?: Record<string, any>;
    is_enabled?: boolean;
    configuration?: Record<string, any>;
}

export const toolService = {
    listTools: async (): Promise<ToolRegistryEntry[]> => {
        const response = await apiClient.get<ToolRegistryEntry[]>('/ai/tool-registry');
        return response.data;
    },

    getTool: async (toolId: string): Promise<ToolRegistryEntry> => {
        const response = await apiClient.get<ToolRegistryEntry>(`/ai/tool-registry/${toolId}`);
        return response.data;
    },

    createTool: async (data: ToolRegistryEntryCreate): Promise<ToolRegistryEntry> => {
        const response = await apiClient.post<ToolRegistryEntry>('/ai/tool-registry', data);
        return response.data;
    },

    updateTool: async (toolId: string, data: ToolRegistryEntryUpdate): Promise<ToolRegistryEntry> => {
        const response = await apiClient.put<ToolRegistryEntry>(`/ai/tool-registry/${toolId}`, data);
        return response.data;
    },

    deleteTool: async (toolId: string): Promise<void> => {
        await apiClient.delete(`/ai/tool-registry/${toolId}`);
    },

    toggleTool: async (toolId: string): Promise<ToolRegistryEntry> => {
        const response = await apiClient.post<ToolRegistryEntry>(`/ai/tool-registry/${toolId}/toggle`);
        return response.data;
    },

    syncBuiltIn: async (): Promise<{ status: string; created: number }> => {
        const response = await apiClient.post<{ status: string; created: number }>('/ai/tool-registry/sync-built-in');
        return response.data;
    },
};
