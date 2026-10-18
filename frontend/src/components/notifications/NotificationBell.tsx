/**
 * components/notifications/NotificationBell — your notifications in the
 * sidebar (Phase 14 WS3 3.11; functional spec §3.6): a count of the unread,
 * and a list that takes you to what each is about.
 */
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { ago } from '@/components/automation/describe';
import { queryKeys } from '@/queries/keys';
import { notificationService, type AppNotification } from '@/services/notification.service';

import './NotificationBell.css';

export const NotificationBell: React.FC<{ expanded: boolean }> = ({ expanded }) => {
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const [open, setOpen] = useState(false);
    const { data } = useQuery({
        queryKey: queryKeys.notifications.mine,
        queryFn: notificationService.list,
        refetchInterval: 60_000,
    });
    const unread = data?.unread ?? 0;
    const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.notifications.mine });

    const openOne = async (item: AppNotification) => {
        if (!item.read_at) {
            try { await notificationService.markRead(item.id); } catch { /* the list refreshes anyway */ }
            await refresh();
        }
        setOpen(false);
        if (item.link) navigate(item.link);
    };

    return (
        <div className="nb">
            <button className="theme-toggle-button w-full nb__button" onClick={() => setOpen(!open)}
                    aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`} aria-expanded={open}>
                <div className="nav-item-icon nb__icon">
                    <Bell size={20} />
                    {unread > 0 && <span className="nb__badge">{unread > 99 ? '99+' : unread}</span>}
                </div>
                {expanded && <span>Notifications</span>}
            </button>
            {open && (
                <div className="nb__panel glass" role="dialog" aria-label="Notifications">
                    <div className="nb__head">
                        <strong>Notifications</strong>
                        {unread > 0 && (
                            <button className="nb__link" onClick={async () => { await notificationService.markAllRead(); await refresh(); }}>
                                Mark all read
                            </button>
                        )}
                    </div>
                    {!data?.items.length ? <p className="nb__empty">Nothing yet.</p> : (
                        <ul className="nb__list">
                            {data.items.map(item => (
                                <li key={item.id}>
                                    <button className={`nb__item nb__item--${item.severity} ${item.read_at ? '' : 'nb__item--unread'}`}
                                            onClick={() => openOne(item)}>
                                        <span className="nb__title">{item.title}</span>
                                        {item.body && <span className="nb__body">{item.body}</span>}
                                        <span className="nb__time">{ago(item.created_at)}</span>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </div>
    );
};

export default NotificationBell;
