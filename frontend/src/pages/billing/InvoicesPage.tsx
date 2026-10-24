/**
 * pages/billing/InvoicesPage — tax invoices, credit notes and the billing profile (Phase 15 T6-5, T6-7).
 *
 * Every payment — a top-up or a subscription charge — has one GST invoice
 * (numbered in the financial year's series, HB/2026-27/000123); a refund has a
 * credit note against it. The billing profile (legal name, GSTIN, state) is
 * what the next invoice is made out to: the state decides CGST + SGST (same
 * state as HireBuddha) or IGST (another state). Issued invoices never change.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Download, FileText, Save } from 'lucide-react';

import { BillingProfile, CreditNote, Invoice, plansService } from '@/services/plans.service';
import { creditsService } from '@/services/credits.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

import './WalletPage.css';
import './PlanPage.css';
import '@/pages/admin/MoneyConsole.css';

const REGIME: Record<Invoice['regime'], string> = {
    intra_state: 'CGST + SGST', inter_state: 'IGST', export: 'Export (zero-rated)',
};

export const InvoicesPage: React.FC = () => {
    const [invoices, setInvoices] = useState<Invoice[]>([]);
    const [notes, setNotes] = useState<CreditNote[]>([]);
    const [profile, setProfile] = useState<BillingProfile | null>(null);
    const [form, setForm] = useState({ legal_name: '', gstin: '', billing_state: '', address: '' });
    const [canEdit, setCanEdit] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [docs, prof, options] = await Promise.all([
                plansService.listInvoices(), plansService.getProfile(), creditsService.getTopUpOptions().catch(() => null),
            ]);
            setInvoices(docs.invoices);
            setNotes(docs.credit_notes);
            setProfile(prof);
            setForm({ legal_name: prof.legal_name ?? '', gstin: prof.gstin ?? '', billing_state: prof.billing_state ?? '',
                      address: prof.billing_address?.line1 ?? '' });
            setCanEdit(options?.can_pay ?? false);
            setError(null);
        } catch (err) {
            setError(apiErrorMessage(err, 'Invoices could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const open = async (fn: () => Promise<void>) => {
        try {
            await fn();
        } catch (err) {
            setError(apiErrorMessage(err, 'The PDF could not be opened'));
        }
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        setError(null);
        try {
            const saved = await plansService.putProfile({
                legal_name: form.legal_name.trim() || null,
                gstin: form.gstin.trim().toUpperCase() || null,
                billing_state: form.billing_state.trim().toUpperCase() || null,
                billing_address: { ...(profile?.billing_address ?? {}), line1: form.address.trim() },
            });
            setProfile(saved);
            setSuccess('Billing details saved. They are used from the next invoice.');
        } catch (err) {
            setError(apiErrorMessage(err, 'Billing details were not saved'));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="wallet-page money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><FileText size={22} /> Invoices</h1>
                    <p className="page-subtitle">A GST tax invoice for every payment, and a credit note for every refund.</p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {success && <div className="success-banner">{success}</div>}

            <div className="plan-compare glass">
                {invoices.length === 0 ? (
                    <p className="section-desc" style={{ padding: '1rem' }}>No invoices yet: one is issued with each payment.</p>
                ) : (
                    <table className="plan-table">
                        <thead>
                            <tr><th>Invoice</th><th>Date</th><th>Net</th><th>GST</th><th>Total</th><th>Tax</th><th /></tr>
                        </thead>
                        <tbody>
                            {invoices.map(i => (
                                <tr key={i.id}>
                                    <td>{i.number}</td>
                                    <td>{i.issued_at ? formatDate(i.issued_at) : ''}</td>
                                    <td>{formatMoney(i.net, i.currency)}</td>
                                    <td>{formatMoney(i.tax, i.currency)}</td>
                                    <td><strong>{formatMoney(i.total, i.currency)}</strong></td>
                                    <td className="muted">{REGIME[i.regime] ?? i.regime} {Number(i.tax_rate)}%</td>
                                    <td>
                                        <button className="btn-secondary" onClick={() => open(() => plansService.openInvoicePdf(i.id))}>
                                            <Download size={14} /> PDF
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            {notes.length > 0 && (
                <div className="plan-compare glass">
                    <h2 className="section-title" style={{ padding: '0.5rem 0.75rem' }}>Credit notes</h2>
                    <table className="plan-table">
                        <thead><tr><th>Credit note</th><th>Against</th><th>Date</th><th>Total</th><th>Reason</th><th /></tr></thead>
                        <tbody>
                            {notes.map(n => (
                                <tr key={n.id}>
                                    <td>{n.number}</td>
                                    <td>{n.invoice_number ?? '—'}</td>
                                    <td>{n.issued_at ? formatDate(n.issued_at) : ''}</td>
                                    <td>{formatMoney(n.total, n.currency)}</td>
                                    <td className="muted">{n.reason ?? ''}</td>
                                    <td>
                                        <button className="btn-secondary" onClick={() => open(() => plansService.openCreditNotePdf(n.id))}>
                                            <Download size={14} /> PDF
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            <div className="topup-section glass">
                <h2 className="section-title">Billing details</h2>
                <p className="section-desc">
                    Who invoices are made out to. With a GSTIN you can claim the input tax credit; the state decides
                    CGST + SGST or IGST. {profile?.country_code && profile.country_code !== 'IN' ? 'Outside India, invoices are zero-rated exports.' : ''}
                </p>
                <form className="money-form plan-profile-form" onSubmit={save}>
                    <label>Legal name
                        <input type="text" value={form.legal_name} disabled={!canEdit} placeholder={profile?.name}
                               onChange={(e) => setForm({ ...form, legal_name: e.target.value })} />
                    </label>
                    <label>GSTIN
                        <input type="text" value={form.gstin} disabled={!canEdit} maxLength={15} placeholder="29ABCDE1234F1Z5"
                               onChange={(e) => setForm({ ...form, gstin: e.target.value })} />
                    </label>
                    <label>State code
                        <input type="text" value={form.billing_state} disabled={!canEdit} maxLength={2} placeholder="KA"
                               onChange={(e) => setForm({ ...form, billing_state: e.target.value })} />
                    </label>
                    <label className="grow">Address
                        <input type="text" value={form.address} disabled={!canEdit}
                               onChange={(e) => setForm({ ...form, address: e.target.value })} />
                    </label>
                    {canEdit
                        ? <button type="submit" className="btn-primary" disabled={saving}><Save size={14} /> {saving ? 'Saving…' : 'Save'}</button>
                        : <p className="section-desc">Only your company's admins can change these.</p>}
                </form>
            </div>
        </div>
    );
};

export default InvoicesPage;
