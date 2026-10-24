/**
 * pages/settings/PartnerAccessPage — your partner's access to your account (Phase 15 T8-4; 07 §4.5).
 *
 * Who your partner is, the access it holds (scopes, expiry) or asks for, what
 * it did under it; approve, renew and revoke.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { partnerBusiness } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate, formatDateTime } from '@/utils/datetime';

import '@/pages/admin/MoneyConsole.css';

type Access = Awaited<ReturnType<typeof partnerBusiness.access>>;

const SCOPE_TEXT: Record<string, string> = {
    read: 'look at your account', support: 'make changes (not delete, not billing)', billing: 'manage billing',
    admin: 'act as an admin',
};

export const PartnerAccessPage: React.FC = () => {
    const { user } = useAuth();
    const admin = user?.role === 'tenant_admin';
    const [data, setData] = useState<Access | null>(null);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            setData(await partnerBusiness.access());
        } catch (err) {
            setError(apiErrorMessage(err, 'Partner access could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const decide = async (id: string, approve: boolean) => {
        try {
            if (approve) {
                const days = prompt('For how many days? (blank: no expiry)', '90');
                if (days === null) return;
                await partnerBusiness.approve(id, days ? Number(days) : undefined);
            } else {
                if (!confirm('Revoke this access? Your partner can no longer work in your account.')) return;
                await partnerBusiness.revoke(id);
            }
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The change was not saved'));
        }
    };

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><ShieldCheck size={22} /> Partner access</h1>
                    <p className="page-subtitle">
                        {data?.partner
                            ? `${data.partner.name} (${data.partner.type === 'GOLD' ? 'Gold' : 'Silver'} partner) ${data.partner.relationship === 'resold' ? 'manages' : 'referred'} your account.`
                            : 'You are served by HireBuddha directly.'}
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            <section className="money-card glass">
                <h2>Access</h2>
                {(data?.grants ?? []).length === 0 ? <p className="card-desc">Your partner has no access to your account's data.</p> : (
                    <table className="money-table">
                        <thead><tr><th>Partner</th><th>May</th><th>Status</th><th>Until</th><th>Why</th><th /></tr></thead>
                        <tbody>
                            {data!.grants.map(g => (
                                <tr key={g.id}>
                                    <td>{g.partner}</td>
                                    <td>{g.scopes.map(s => SCOPE_TEXT[s] ?? s).join('; ')}</td>
                                    <td>{g.status}</td>
                                    <td>{g.expires_at ? formatDate(g.expires_at) : 'no expiry'}</td>
                                    <td className="muted">{g.reason}</td>
                                    <td style={{ whiteSpace: 'nowrap' }}>
                                        {admin && g.status !== 'active' && g.status !== 'revoked' && (
                                            <button className="btn-primary" onClick={() => decide(g.id, true)}>
                                                {g.status === 'expired' ? 'Renew' : 'Approve'}
                                            </button>
                                        )}{' '}
                                        {admin && g.status !== 'revoked' && (
                                            <button className="btn-secondary" onClick={() => decide(g.id, false)}>Revoke</button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
            <section className="money-card glass">
                <h2>What your partner did</h2>
                {(data?.events ?? []).length === 0 ? <p className="card-desc">Nothing recorded.</p> : (
                    <table className="money-table">
                        <thead><tr><th>When</th><th>Who</th><th>Request</th></tr></thead>
                        <tbody>
                            {data!.events.map((e, i) => (
                                <tr key={i}>
                                    <td>{e.at ? formatDateTime(e.at) : ''}</td>
                                    <td>{e.user} ({e.partner})</td>
                                    <td><code>{e.method} {e.path}</code></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
        </div>
    );
};

export default PartnerAccessPage;
