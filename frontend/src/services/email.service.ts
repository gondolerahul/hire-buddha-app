import { apiClient } from './api.client';

export interface EmailConnection {
    id: string;
    company_id: string;
    email_address: string;
    imap_host: string;
    imap_port: number;
    smtp_host: string;
    smtp_port: number;
    provider_type: string;
    folder_prefix: string | null;
    is_active: boolean;
    last_connected_at: string | null;
    status: string;
    created_at: string;
    updated_at: string;
}

export interface EmailConnectionCreate {
    email_address: string;
    app_password: string;
    imap_host?: string;
    imap_port?: number;
    smtp_host?: string;
    smtp_port?: number;
    provider_type?: string;
    folder_prefix?: string;
}

export interface ProviderDefaults {
    [key: string]: {
        imap_host: string;
        imap_port: number;
        smtp_host: string;
        smtp_port: number;
        folder_prefix: string;
        help_url: string;
    };
}

export const emailService = {
    getProviderDefaults: async (): Promise<ProviderDefaults> => {
        const response = await apiClient.get<ProviderDefaults>('/email/provider-defaults');
        return response.data;
    },

    getConnections: async (companyId: string): Promise<EmailConnection[]> => {
        const response = await apiClient.get<EmailConnection[]>(`/email/connections?company_id=${companyId}`);
        return response.data;
    },

    createConnection: async (data: EmailConnectionCreate & { company_id: string }): Promise<EmailConnection> => {
        const response = await apiClient.post<EmailConnection>(`/email/connections?company_id=${data.company_id}`, data);
        return response.data;
    },

    validateConnection: async (connectionId: string): Promise<{ valid: boolean; message: string }> => {
        const response = await apiClient.post<{ valid: boolean; message: string }>(
            `/email/connections/${connectionId}/validate`
        );
        return response.data;
    },

    deleteConnection: async (connectionId: string): Promise<void> => {
        await apiClient.delete(`/email/connections/${connectionId}`);
    }
};
