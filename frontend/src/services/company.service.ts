import { apiClient } from './api.client';
import { Company } from '@/types';

export interface CompanyCreate {
    name: string;
    type: 'APP' | 'PARTNER' | 'TENANT';
    parent_id?: string;
    apply_default_daily_credits?: boolean;
    custom_daily_credits?: number;
}

export interface CompanyUpdate {
    name?: string;
    status?: 'active' | 'suspended';
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
