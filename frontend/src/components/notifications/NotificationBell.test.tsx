// @vitest-environment jsdom
/**
 * NotificationBell — the unread count, the list, and opening one: it is marked
 * read and takes you where it points.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const markRead = vi.fn().mockResolvedValue({});
const markAllRead = vi.fn().mockResolvedValue({ unread: 0, items: [] });

vi.mock('@/services/notification.service', () => ({
    notificationService: {
        list: vi.fn().mockResolvedValue({
            unread: 1,
            items: [
                { id: 'n1', kind: 'automation.event_dead', severity: 'error', title: 'An event failed five times',
                  body: 'Retry it', link: '/automation', created_at: '2026-10-18T10:00:00', read_at: null },
                { id: 'n2', kind: 'automation.loop_stopped', severity: 'warning', title: 'A loop was stopped',
                  body: null, link: null, created_at: '2026-10-17T10:00:00', read_at: '2026-10-17T11:00:00' },
            ],
        }),
        markRead: (...args: unknown[]) => markRead(...args),
        markAllRead: (...args: unknown[]) => markAllRead(...args),
    },
}));

import { NotificationBell } from './NotificationBell';

afterEach(cleanup);

function setup() {
    render(
        <QueryClientProvider client={new QueryClient()}>
            <MemoryRouter initialEntries={['/dashboard']}>
                <Routes>
                    <Route path="/dashboard" element={<NotificationBell expanded />} />
                    <Route path="/automation" element={<p>control room</p>} />
                </Routes>
            </MemoryRouter>
        </QueryClientProvider>,
    );
}

describe('NotificationBell', () => {
    it('shows how many are unread and lists them', async () => {
        setup();
        const bell = await screen.findByLabelText('Notifications, 1 unread');
        fireEvent.click(bell);
        expect(screen.getByText('An event failed five times')).toBeTruthy();
        expect(screen.getByText('A loop was stopped')).toBeTruthy();
    });

    it('marks one read and follows its link', async () => {
        setup();
        fireEvent.click(await screen.findByLabelText('Notifications, 1 unread'));
        fireEvent.click(screen.getByText('An event failed five times'));
        await waitFor(() => expect(screen.getByText('control room')).toBeTruthy());
        expect(markRead).toHaveBeenCalledWith('n1');
    });

    it('marks all read', async () => {
        setup();
        fireEvent.click(await screen.findByLabelText('Notifications, 1 unread'));
        fireEvent.click(screen.getByText('Mark all read'));
        await waitFor(() => expect(markAllRead).toHaveBeenCalled());
    });
});
