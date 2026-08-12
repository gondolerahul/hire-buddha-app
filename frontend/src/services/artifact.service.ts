import { apiClient } from './api.client';

export interface Artifact {
    id: string;
    company_id: string;
    campaign_id: string | null;
    agent_id: string | null;
    run_id: string | null;
    origin: 'user-uploads' | 'system-generated';
    file_category: string;
    file_name: string;
    file_path: string;
    file_size: number | null;
    mime_type: string | null;
    duration_seconds: number | null;
    purpose: string | null;
    generated_by: string | null;
    artifact_metadata: Record<string, unknown> | null;
    created_at: string;
    download_url: string;
}

export interface ArtifactListFilters {
    origin?: 'user-uploads' | 'system-generated';
    file_category?: string;
    agent_id?: string;
    campaign_id?: string;
    date_from?: string;
    date_to?: string;
    limit?: number;
    offset?: number;
}

export interface ArtifactListResponse {
    artifacts: Artifact[];
    count: number;
}

export const artifactService = {
    list: async (filters: ArtifactListFilters = {}): Promise<ArtifactListResponse> => {
        const params = new URLSearchParams();
        Object.entries(filters).forEach(([key, value]) => {
            if (value !== undefined && value !== null && value !== '') {
                params.append(key, String(value));
            }
        });
        const { data } = await apiClient.get<ArtifactListResponse>(
            `/artifacts?${params.toString()}`
        );
        return data;
    },

    get: async (id: string): Promise<Artifact> => {
        const { data } = await apiClient.get<Artifact>(`/artifacts/${id}`);
        return data;
    },

    upload: async (
        file: File,
        file_category: string,
        campaign_id?: string,
        agent_id?: string,
        purpose?: string,
    ): Promise<Artifact> => {
        const form = new FormData();
        form.append('file', file);
        form.append('file_category', file_category);
        if (campaign_id) form.append('campaign_id', campaign_id);
        if (agent_id) form.append('agent_id', agent_id);
        if (purpose) form.append('purpose', purpose);

        const { data } = await apiClient.post<Artifact>('/artifacts/upload', form, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        return data;
    },

    delete: async (id: string): Promise<void> => {
        await apiClient.delete(`/artifacts/${id}`);
    },

    getDownloadUrl: (id: string): string => {
        const base = (window as any).__API_BASE__ || import.meta.env.VITE_API_URL || '';
        return `${base}/api/v1/artifacts/${id}/download`;
    },
};
