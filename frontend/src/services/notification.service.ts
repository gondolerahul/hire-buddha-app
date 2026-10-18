/**
 * services/notification.service.ts — your notifications (Phase 14 WS3 3.11):
 * automation problems told to the people who run the business.
 */
import { apiClient } from './api.client';

export interface AppNotification {
    id: string;
    kind: string;
    severity: 'info' | 'warning' | 'error';
    title: string;
    body: string | null;
    link: string | null;
    created_at: string;
    read_at: string | null;
}

export interface NotificationList {
    unread: number;
    items: AppNotification[];
}

export const notificationService = {
    list: async (): Promise<NotificationList> =>
        (await apiClient.get<NotificationList>('/notifications')).data,

    markRead: async (id: string): Promise<AppNotification> =>
        (await apiClient.post<AppNotification>(`/notifications/${id}/read`)).data,

    markAllRead: async (): Promise<NotificationList> =>
        (await apiClient.post<NotificationList>('/notifications/read-all')).data,
};
