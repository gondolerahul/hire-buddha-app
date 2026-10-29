/**
 * pages/settings/SupportAccessPage — HireBuddha's staff and your connected accounts (SH-E6).
 *
 * Staff who help you see what your AI employees did, but not what came through
 * your connections (e-mails, messages, comments, files) unless you give support
 * access here, for a few hours or days. Every time a staff member opens such a
 * run it is listed, with the content shown or withheld.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { LifeBuoy } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { supportAccess, type SupportAccess } from '@/services/support.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDateTime } from '@/utils/datetime';

import '@/pages/admin/MoneyConsole.css';

const DURATIONS = [{ hours: 4, label: '4 hours' }, { hours: 24, label: '1 day' }, { hours: 72, label: '3 days' },
                   { hours: 168, label: '7 days' }];

export const SupportAccessPage: React.FC = () => {
    const { user } = useAuth();
    const admin = user?.role === 'tenant_admin';
    const [data, setData] = useState<SupportAccess | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [hours, setHours] = useState(24);
    const [reason, setReason] = useState('');

    const load = useCallback(async () => {
        try {
            setData(await supportAccess.get());
        } catch (err) {
            setError(apiErrorMessage(err, 'Support access could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const give = async () => {
        setError(null);
        try {
            await supportAccess.give(hours, reason.trim());
            setReason('');
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'Support access was not given'));
        }
    };

    const end = async (id: string) => {
        if (!confirm('End support access now? Staff stop seeing your connected accounts\' content at once.')) return;
        try {
            await supportAccess.end(id);
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'Support access was not ended'));
        }
    };

    const active = data?.active;
    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><LifeBuoy size={22} /> Support access</h1>
                    <p className="page-subtitle">
                        HireBuddha's staff see what your AI employees did, but not the content of your connected
                        accounts (e-mails, messages, comments, files) unless you give them access here.
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            <section className="money-card glass">
                <h2>Now</h2>
                {active ? (
                    <p className="card-desc">
                        Staff may see that content until <strong>{formatDateTime(active.expires_at)}</strong>
                        {' '}({active.reason}).{' '}
                        {admin && <button className="btn-secondary" onClick={() => end(active.id)}>End now</button>}
                    </p>
                ) : <p className="card-desc">No access: staff see your runs with that content withheld.</p>}
                {admin && (
                    <div className="money-form">
                        <label>For
                            <select value={hours} onChange={e => setHours(Number(e.target.value))}>
                                {DURATIONS.map(d => <option key={d.hours} value={d.hours}>{d.label}</option>)}
                            </select>
                        </label>
                        <label>Why
                            <input value={reason} onChange={e => setReason(e.target.value)} maxLength={500}
                                   placeholder="e.g. Ticket 1042: replies to Gmail are not sent" />
                        </label>
                        <button className="btn-primary" disabled={reason.trim().length < 3} onClick={give}>
                            {active ? 'Replace access' : 'Give support access'}
                        </button>
                    </div>
                )}
            </section>
            <section className="money-card glass">
                <h2>When staff looked</h2>
                {(data?.views ?? []).length === 0 ? <p className="card-desc">No staff member has opened a run of
                    yours that read your connected accounts.</p> : (
                    <table className="money-table">
                        <thead><tr><th>When</th><th>Who</th><th>Run</th><th>Content</th></tr></thead>
                        <tbody>
                            {data!.views.map((v, i) => (
                                <tr key={i}>
                                    <td>{formatDateTime(v.at)}</td>
                                    <td>{v.staff ?? 'HireBuddha staff'}</td>
                                    <td>{v.run_id ? <a href={`/work/${v.run_id}`}>{v.run_id.slice(0, 8)}</a> : '—'}</td>
                                    <td>{v.withheld ? 'withheld' : 'shown (under your access)'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
            <section className="money-card glass">
                <h2>Earlier access</h2>
                {(data?.grants ?? []).filter(g => !g.active).length === 0 ? <p className="card-desc">None.</p> : (
                    <table className="money-table">
                        <thead><tr><th>Given</th><th>Until</th><th>Why</th><th>Ended</th></tr></thead>
                        <tbody>
                            {data!.grants.filter(g => !g.active).map(g => (
                                <tr key={g.id}>
                                    <td>{g.created_at ? formatDateTime(g.created_at) : ''}</td>
                                    <td>{formatDateTime(g.expires_at)}</td>
                                    <td className="muted">{g.reason}</td>
                                    <td>{g.revoked_at ? formatDateTime(g.revoked_at) : 'expired'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
        </div>
    );
};

export default SupportAccessPage;
