import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import { API_BASE_URL } from '@/config/api';

/** Told of every successful write: its method and path (FE-21). */
export type WriteListener = (method: string, url: string) => void;


class ApiClient {
    private client: AxiosInstance;

    constructor() {
        this.client = axios.create({
            baseURL: API_BASE_URL,
            headers: {
                'Content-Type': 'application/json',
            },
        });

        // Request interceptor to add auth token
        this.client.interceptors.request.use(
            (config: InternalAxiosRequestConfig) => {
                const token = localStorage.getItem('access_token');
                if (token && config.headers) {
                    config.headers.Authorization = `Bearer ${token}`;
                }
                return config;
            },
            (error) => Promise.reject(error)
        );

        // Response interceptor to handle 401 and refresh token.
        // Concurrent 401s share one refresh: a refresh token is rotated on use,
        // and presenting a rotated token again ends every session (AU-09).
        this.client.interceptors.response.use(
            (response) => {
                const method = (response.config.method || 'get').toLowerCase();
                if (method !== 'get' && method !== 'head' && method !== 'options') {
                    for (const listener of this.writeListeners) {
                        try {
                            listener(method, response.config.url || '');
                        } catch {
                            // A listener must never fail the request.
                        }
                    }
                }
                return response;
            },
            async (error) => {
                const originalRequest = error.config;

                // If 401 and not already retrying, try to refresh token. With no
                // refresh token there is nothing to try: pass the 401 on (public
                // pages make calls that 401 when signed out; redirecting would loop).
                const canRefresh = this.refreshing !== null || !!localStorage.getItem('refresh_token');
                if (error.response?.status === 401 && !originalRequest._retry && canRefresh) {
                    originalRequest._retry = true;

                    try {
                        const accessToken = await this.refreshAccessToken();
                        originalRequest.headers.Authorization = `Bearer ${accessToken}`;
                        return this.client(originalRequest);
                    } catch (refreshError) {
                        // Refresh failed, clear tokens and redirect to login
                        localStorage.removeItem('access_token');
                        localStorage.removeItem('refresh_token');
                        window.location.href = '/login';
                        return Promise.reject(refreshError);
                    }
                }

                return Promise.reject(error);
            }
        );
    }

    private refreshing: Promise<string> | null = null;

    private writeListeners: WriteListener[] = [];

    /** Call `listener` after every successful write; returns the unsubscribe. */
    onWrite(listener: WriteListener): () => void {
        this.writeListeners.push(listener);
        return () => {
            this.writeListeners = this.writeListeners.filter((l) => l !== listener);
        };
    }

    private refreshAccessToken(): Promise<string> {
        if (!this.refreshing) {
            const refreshToken = localStorage.getItem('refresh_token');
            this.refreshing = (refreshToken
                ? axios.post(`${API_BASE_URL}/auth/refresh`, { refresh_token: refreshToken }).then(({ data }) => {
                    localStorage.setItem('access_token', data.access_token);
                    localStorage.setItem('refresh_token', data.refresh_token);
                    return data.access_token as string;
                })
                : Promise.reject(new Error('No refresh token'))
            ).finally(() => {
                this.refreshing = null;
            });
        }
        return this.refreshing;
    }

    getInstance(): AxiosInstance {
        return this.client;
    }
}

const client = new ApiClient();

export const apiClient = client.getInstance();

/** Subscribe to every successful write through `apiClient` (FE-21). */
export const onApiWrite = (listener: WriteListener): (() => void) => client.onWrite(listener);
