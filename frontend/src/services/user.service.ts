import { apiClient } from './api.client';
import { User, UserRole } from '@/types';

export interface UserCreateAdmin {
    email: string;
    password: string;
    full_name: string;
    company_id: string;
    role: UserRole;
}

export const userService = {
    getUsers: async (): Promise<User[]> => {
        const response = await apiClient.get<User[]>('/users');
        return response.data;
    },

    createUser: async (data: UserCreateAdmin): Promise<User> => {
        const response = await apiClient.post<User>('/users', data);
        return response.data;
    },

    updateUser: async (id: string, data: Partial<User>): Promise<User> => {
        const response = await apiClient.patch<User>(`/users/${id}`, data);
        return response.data;
    }
};
