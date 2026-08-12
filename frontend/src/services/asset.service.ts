import { apiClient } from './api.client';

export interface Asset {
    id: string;
    company_id: string;
    campaign_id: string | null;
    agent_id: string | null;
    run_id: string | null;
    file_type: 'recordings' | 'images' | 'videos';
    file_name: string;
    file_path: string;
    file_size: number | null;
    mime_type: string | null;
    duration_seconds: number | null;
    asset_metadata: Record<string, unknown> | null;
    created_at: string;
    download_url: string;
}

export interface AssetListFilters {
    file_type?: 'recordings' | 'images' | 'videos';
    agent_id?: string;
    campaign_id?: string;
    date_from?: string;
    date_to?: string;
    limit?: number;
    offset?: number;
}

export interface AssetListResponse {
    assets: Asset[];
    count: number;
}

export const assetService = {
    list: async (filters: AssetListFilters = {}): Promise<AssetListResponse> => {
        const params = new URLSearchParams();
        Object.entries(filters).forEach(([key, value]) => {
            if (value !== undefined && value !== null && value !== '') {
                params.append(key, String(value));
            }
        });
        const { data } = await apiClient.get<AssetListResponse>(
            `/assets?${params.toString()}`
        );
        return data;
    },

    get: async (id: string): Promise<Asset> => {
        const { data } = await apiClient.get<Asset>(`/assets/${id}`);
        return data;
    },

    upload: async (
        file: File,
        asset_type: 'recordings' | 'images' | 'videos',
        campaign_id?: string,
        agent_id?: string
    ): Promise<Asset> => {
        const form = new FormData();
        form.append('file', file);
        form.append('asset_type', asset_type);
        if (campaign_id) form.append('campaign_id', campaign_id);
        if (agent_id) form.append('agent_id', agent_id);

        const { data } = await apiClient.post<Asset>('/assets/upload', form, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        return data;
    },

    delete: async (id: string): Promise<void> => {
        await apiClient.delete(`/assets/${id}`);
    },

    getDownloadUrl: (id: string): string => {
        const base = (window as any).__API_BASE__ || import.meta.env.VITE_API_URL || '';
        return `${base}/api/v1/assets/${id}/download`;
    },
};
