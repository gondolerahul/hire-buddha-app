import { apiClient } from './api.client';
import { LoginRequest, RegisterRequest, AuthResponse, User } from '@/types';

export const authService = {
    async login(credentials: LoginRequest): Promise<AuthResponse> {
        const { data } = await apiClient.post('/auth/login', credentials);

        // Store tokens
        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);

        return data;
    },

    async register(userData: RegisterRequest): Promise<AuthResponse> {
        const { data } = await apiClient.post('/auth/register', userData);

        // Store tokens
        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);

        return data;
    },

    async getCurrentUser(): Promise<User> {
        const { data } = await apiClient.get('/auth/me');
        return data;
    },

    logout(): void {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
    },

    async refreshToken(refreshToken: string): Promise<AuthResponse> {
        const { data } = await apiClient.post('/auth/refresh', { refresh_token: refreshToken });

        // Update tokens
        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);

        return data;
    },

    isAuthenticated(): boolean {
        return !!localStorage.getItem('access_token');
    },
};
