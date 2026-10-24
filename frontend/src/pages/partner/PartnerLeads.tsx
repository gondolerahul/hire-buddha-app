/**
 * pages/partner/PartnerLeads — register and follow leads (Phase 15 T8-9, T8-14; 07 §4.3).
 *
 * A lead is yours for the exclusivity window; a duplicate is refused. HireBuddha
 * converts a Silver partner's leads; a Gold partner converts its own.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Target, Plus } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { Lead, partnerPortal } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';

import '@/pages/admin/MoneyConsole.css';
import './Partner.css';

const EMPTY = { company_name: '', contact_name: '', email: '', phone: '', country_code: 'IN', notes: '' };

export const PartnerLeads: React.FC = () => {
    const { user } = useAuth();
    const [rows, setRows] = useState<Lead[]>([]);
    const [gold, setGold] = useState(false);
    const [form, setForm] = useState(EMPTY);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [leads, me] = await Promise.all([partnerPortal.leads(), partnerPortal.me()]);
            setRows(leads);
            setGold(me.partner_type === 'GOLD');
        } catch (err) {
            setError(apiErrorMessage(err, 'Leads could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const register = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
            const lead = await partnerPortal.registerLead({ ...form, email: form.email || null, phone: form.phone || null });
            setNotice(`${lead.company_name} is registered; it is yours until ${formatDate(lead.exclusive_until ?? '')}.`);
            setForm(EMPTY);
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The lead was not registered'));
        } finally {
            setBusy(false);
        }
    };

    const convert = async (lead: Lead) => {
        const email = prompt(`Make ${lead.company_name} a customer. Its admin's e-mail (blank: the lead's):`, lead.email ?? '');
        if (email === null) return;
        try {
            await partnerPortal.convertLead(lead.id, { admin_email: email || undefined });
            setNotice(`${lead.company_name} is now your customer.`);
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The lead was not converted'));
        }
    };

    return (
        <div className="money-console partner-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Target size={22} /> Leads</h1>
                    <p className="page-subtitle">
                        Register a prospective customer: it is yours alone for the exclusivity window.
                        {gold ? ' You convert your own leads.' : ' HireBuddha converts it and sets the customer up.'}
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}
            <section className="money-card glass">
                <h2><Plus size={18} /> Register a lead</h2>
                <form className="money-form" onSubmit={register}>
                    <label>Company<input type="text" required minLength={2} value={form.company_name}
                                         onChange={e => setForm({ ...form, company_name: e.target.value })} /></label>
                    <label>Contact<input type="text" value={form.contact_name}
                                         onChange={e => setForm({ ...form, contact_name: e.target.value })} /></label>
                    <label>E-mail<input type="text" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></label>
                    <label>Phone<input type="text" value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} /></label>
                    <label>Country<input type="text" maxLength={2} value={form.country_code}
                                         onChange={e => setForm({ ...form, country_code: e.target.value.toUpperCase() })} /></label>
                    <label className="grow">Notes<input type="text" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></label>
                    <button type="submit" className="btn-primary" disabled={busy}>Register</button>
                </form>
            </section>
            <section className="money-card glass">
                <h2>Your leads</h2>
                {rows.length === 0 ? <p className="card-desc">None yet.</p> : (
                    <table className="money-table">
                        <thead><tr><th>Company</th><th>Contact</th><th>Status</th><th>Yours until</th><th>Registered</th><th /></tr></thead>
                        <tbody>
                            {rows.map(l => (
                                <tr key={l.id}>
                                    <td>{l.company_name}</td>
                                    <td>{[l.contact_name, l.email].filter(Boolean).join(' · ') || '—'}</td>
                                    <td>{l.status.replace('_', ' ')}{l.lost_reason ? ` (${l.lost_reason})` : ''}</td>
                                    <td>{l.exclusive_until ? formatDate(l.exclusive_until) : '—'}</td>
                                    <td>{l.created_at ? formatDate(l.created_at) : ''}</td>
                                    <td>
                                        {gold && user?.role === 'partner_admin' && ['registered', 'accepted', 'in_progress'].includes(l.status) && (
                                            <button className="btn-secondary" onClick={() => convert(l)}>Make customer</button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
        </div>
    );
};

export default PartnerLeads;
