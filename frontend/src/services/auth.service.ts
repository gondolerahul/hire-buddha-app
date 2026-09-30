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

    /** Creates the account and emails a verification link; signs nobody in (AU-08). */
    async register(userData: RegisterRequest): Promise<{ email: string; message: string }> {
        const { data } = await apiClient.post('/auth/register', userData);
        return data;
    },

    async verifyEmail(token: string): Promise<{ message: string }> {
        const { data } = await apiClient.get('/auth/verify-email', { params: { token } });
        return data;
    },

    async resendVerification(email: string): Promise<{ message: string }> {
        const { data } = await apiClient.post('/auth/resend-verification', { email });
        return data;
    },

    async getCurrentUser(): Promise<User> {
        const { data } = await apiClient.get('/auth/me');
        return data;
    },

    /** Forget this browser's tokens without telling the server. */
    clearSession(): void {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
    },

    /** End this session on the server (its refresh token is revoked), then forget it. */
    async logout(allSessions = false): Promise<void> {
        const refreshToken = localStorage.getItem('refresh_token');
        this.clearSession();
        if (refreshToken) {
            await apiClient
                .post('/auth/logout', { refresh_token: refreshToken, all_sessions: allSessions })
                .catch(() => undefined);
        }
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
