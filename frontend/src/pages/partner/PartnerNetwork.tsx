/**
 * pages/partner/PartnerNetwork — partners you recruited (Phase 15 T8-5, T8-14; 07 §4.3, R-P07).
 *
 * Their names, types, status and level, and the overrides you earned on their
 * customers' payments — never their customers. Invite a partner with a link;
 * HireBuddha reviews every application and sets the type.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Network, Link2 } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { NetworkPartner, partnerPortal } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import '@/pages/admin/MoneyConsole.css';
import './Partner.css';

type Invite = Awaited<ReturnType<typeof partnerPortal.invites>>[number];

export const PartnerNetwork: React.FC = () => {
    const { user } = useAuth();
    const admin = user?.role === 'partner_admin';
    const [partners, setPartners] = useState<NetworkPartner[]>([]);
    const [invites, setInvites] = useState<Invite[]>([]);
    const [currency, setCurrency] = useState('INR');
    const [email, setEmail] = useState('');
    const [link, setLink] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [net, me] = await Promise.all([partnerPortal.network(), partnerPortal.me()]);
            setPartners(net.partners);
            setCurrency(me.currency);
            if (admin) setInvites(await partnerPortal.invites());
        } catch (err) {
            setError(apiErrorMessage(err, 'The network could not be loaded'));
        }
    }, [admin]);

    useEffect(() => { load(); }, [load]);

    const invite = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const made = await partnerPortal.invite(email || undefined);
            setLink(`${window.location.origin}/partners/apply?token=${made.token}`);
            setEmail('');
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The invitation was not made'));
        }
    };

    return (
        <div className="money-console partner-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Network size={22} /> My partners</h1>
                    <p className="page-subtitle">
                        Partners you recruited. You earn overrides on their customers' payments while you sell yourself —
                        never on their joining or their fees.
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            <section className="money-card glass">
                {partners.length === 0 ? <p className="card-desc">No partners recruited yet.</p> : (
                    <table className="money-table">
                        <thead><tr><th>Partner</th><th>Type</th><th>Status</th><th>Level</th><th>Joined</th>{admin && <th>Your overrides</th>}</tr></thead>
                        <tbody>
                            {partners.map(p => (
                                <tr key={p.partner_id}>
                                    <td>{p.name}</td><td>{p.type}</td><td>{p.status.replace('_', ' ')}</td>
                                    <td>{p.level}</td><td>{p.joined ? formatDate(p.joined) : '—'}</td>
                                    {admin && <td>{formatMoney(p.override_earnings ?? 0, currency)}</td>}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
            {admin && (
                <section className="money-card glass">
                    <h2><Link2 size={18} /> Invite a partner</h2>
                    <form className="money-form" onSubmit={invite}>
                        <label className="grow">Their e-mail (optional)
                            <input type="text" value={email} onChange={e => setEmail(e.target.value)} />
                        </label>
                        <button type="submit" className="btn-primary">Make an invitation link</button>
                    </form>
                    {link && <p className="partner-explain">Send them this link: <code>{link}</code></p>}
                    {invites.length > 0 && (
                        <table className="money-table" style={{ marginTop: '1rem' }}>
                            <thead><tr><th>Invited</th><th>Company</th><th>Status</th><th>When</th></tr></thead>
                            <tbody>
                                {invites.map(i => (
                                    <tr key={i.id}>
                                        <td>{i.email ?? '—'}</td><td>{i.company_name ?? '—'}</td>
                                        <td>{i.status.replace('_', ' ')}</td><td>{i.created_at ? formatDate(i.created_at) : ''}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </section>
            )}
        </div>
    );
};

export default PartnerNetwork;
