import { apiClient } from './api.client';
import { User, Company } from '@/types';

export const profileService = {
    uploadAvatar: async (file: File): Promise<User> => {
        const formData = new FormData();
        formData.append('file', file);
        const response = await apiClient.post<User>('/profile/avatar', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
        return response.data;
    },

    uploadLogo: async (file: File): Promise<Company> => {
        const formData = new FormData();
        formData.append('file', file);
        const response = await apiClient.post<Company>('/profile/company-logo', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
        return response.data;
    }
};
