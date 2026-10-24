import { apiClient } from './api.client';
import { Company } from '@/types';

export interface CompanyCreate {
    name: string;
    type: 'APP' | 'PARTNER' | 'TENANT';
    parent_id?: string;
}

export interface CompanyUpdate {
    name?: string;
    status?: 'active' | 'suspended';
    monthly_spend_cap_usd?: number | null;
    // An IANA time zone (Phase 14); the API refuses anything else.
    timezone?: string;
}

export const companyService = {
    getPartners: async (): Promise<Company[]> => {
        const response = await apiClient.get<Company[]>('/companies/partners');
        return response.data;
    },

    getTenants: async (): Promise<Company[]> => {
        const response = await apiClient.get<Company[]>('/companies/tenants');
        return response.data;
    },

    createCompany: async (data: CompanyCreate): Promise<Company> => {
        const response = await apiClient.post<Company>('/companies', data);
        return response.data;
    },

    updateCompany: async (id: string, data: CompanyUpdate): Promise<Company> => {
        const response = await apiClient.patch<Company>(`/companies/${id}`, data);
        return response.data;
    }
};
