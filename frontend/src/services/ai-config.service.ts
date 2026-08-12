import { apiClient } from './api.client';
import { Integration } from './integration.service';

export interface ModelTaskDefault {
    id: string;
    company_id: string;
    task_type: string;
    integration_id: string;
    routing_mode: 'single' | 'router';
    is_default: boolean;
    created_at: string;
    updated_at: string;

    // Joined field when returning from API
    integration?: Integration;
}

export interface ModelTaskDefaultCreate {
    task_type: string;
    integration_id: string;
    routing_mode: 'single' | 'router';
}

export const aiConfigService = {
    getTaskDefaults: async (): Promise<ModelTaskDefault[]> => {
        const response = await apiClient.get<ModelTaskDefault[]>('/config/task-defaults');
        return response.data;
    },

    setTaskDefault: async (data: ModelTaskDefaultCreate): Promise<ModelTaskDefault> => {
        const response = await apiClient.post<ModelTaskDefault>('/config/task-defaults', data);
        return response.data;
    },

    deleteTaskDefault: async (taskType: string): Promise<void> => {
        await apiClient.delete(`/config/task-defaults/${taskType}`);
    }
};
