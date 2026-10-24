/**
 * pages/partner/PartnerCharges — setup and customisation fees (Phase 15 T8-8, T8-14; 07 §4.3).
 *
 * A Gold partner raises a fee for a tenant it resells, within the range
 * HireBuddha sets; the page shows the range in the tenant's currency and the
 * split (your share, your uplines', the platform's). The tenant pays it with GST;
 * your share is in Earnings once it is paid.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Receipt } from 'lucide-react';

import { Charge, ChargePreview, Customer, partnerPortal } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import '@/pages/admin/MoneyConsole.css';
import './Partner.css';

export const PartnerCharges: React.FC = () => {
    const [rows, setRows] = useState<Charge[]>([]);
    const [tenants, setTenants] = useState<Customer[]>([]);
    const [form, setForm] = useState({ tenant_id: '', fee_kind: 'setup', amount: '', description: '' });
    const [preview, setPreview] = useState<ChargePreview | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [charges, customers] = await Promise.all([partnerPortal.charges(), partnerPortal.customers()]);
            setRows(charges);
            setTenants(customers.customers.filter(c => c.relationship === 'resold'));
        } catch (err) {
            setError(apiErrorMessage(err, 'Charges could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);
    useEffect(() => {
        setPreview(null);
        if (!form.tenant_id) return;
        partnerPortal.chargePreview(form.tenant_id, form.fee_kind).then(setPreview)
            .catch(err => setError(apiErrorMessage(err, 'The fee rule could not be read')));
    }, [form.tenant_id, form.fee_kind]);

    const share = (key: string) => {
        const pct = preview?.split?.[key] ?? 0;
        return form.amount ? formatMoney(Number(form.amount) * pct / 100, preview?.currency ?? 'INR') : `${pct} %`;
    };

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        try {
            const charge = await partnerPortal.raiseCharge({ ...form, description: form.description || undefined });
            setNotice(`${formatMoney(charge.amount, charge.currency)} raised for ${charge.tenant}; its admins are told.`);
            setForm({ ...form, amount: '', description: '' });
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The charge was not raised'));
        }
    };

    const cancel = async (charge: Charge) => {
        if (!confirm(`Cancel the ${charge.fee_kind} fee for ${charge.tenant}?`)) return;
        try {
            await partnerPortal.cancelCharge(charge.id);
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The charge was not cancelled'));
        }
    };

    return (
        <div className="money-console partner-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Receipt size={22} /> Setup &amp; customisation fees</h1>
                    <p className="page-subtitle">Charged to the business directly (not from its wallet), with GST; invoiced by HireBuddha.</p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}
            <section className="money-card glass">
                <h2>Raise a fee</h2>
                <form className="money-form" onSubmit={submit}>
                    <label>Business
                        <select value={form.tenant_id} required onChange={e => setForm({ ...form, tenant_id: e.target.value })}>
                            <option value="">— choose —</option>
                            {tenants.map(t => <option key={t.tenant_id} value={t.tenant_id}>{t.name}</option>)}
                        </select>
                    </label>
                    <label>Fee
                        <select value={form.fee_kind} onChange={e => setForm({ ...form, fee_kind: e.target.value })}>
                            <option value="setup">Setup</option><option value="customisation">Customisation</option>
                        </select>
                    </label>
                    <label>Amount ({preview?.currency ?? '—'}, before GST)
                        <input type="text" inputMode="decimal" required value={form.amount}
                               onChange={e => setForm({ ...form, amount: e.target.value })} />
                    </label>
                    <label className="grow">Description<input type="text" value={form.description}
                                                               onChange={e => setForm({ ...form, description: e.target.value })} /></label>
                    <button type="submit" className="btn-primary" disabled={!preview}>Raise</button>
                </form>
                {preview && preview.min && (
                    <p className="partner-explain">
                        Allowed: {formatMoney(preview.min, preview.currency)} – {formatMoney(preview.max ?? 0, preview.currency)}.
                        Split: you {share('originator')}, your recruiter {share('level1')}, its recruiter {share('level2')},
                        HireBuddha {share('platform')}.
                    </p>
                )}
            </section>
            <section className="money-card glass">
                <h2>Fees raised</h2>
                {rows.length === 0 ? <p className="card-desc">None yet.</p> : (
                    <table className="money-table">
                        <thead><tr><th>Business</th><th>Fee</th><th>Amount</th><th>Status</th><th>Raised</th><th>Paid</th><th /></tr></thead>
                        <tbody>
                            {rows.map(c => (
                                <tr key={c.id}>
                                    <td>{c.tenant}</td>
                                    <td>{c.fee_kind}{c.description ? ` · ${c.description}` : ''}</td>
                                    <td>{formatMoney(c.amount, c.currency)}</td>
                                    <td>{c.status}</td>
                                    <td>{c.created_at ? formatDate(c.created_at) : ''}</td>
                                    <td>{c.paid_at ? formatDate(c.paid_at) : '—'}</td>
                                    <td>{c.status === 'sent' && <button className="btn-secondary" onClick={() => cancel(c)}>Cancel</button>}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
        </div>
    );
};

export default PartnerCharges;
