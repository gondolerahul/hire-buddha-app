/**
 * pages/partner/PartnerAccessGrantsPage — a Gold partner's grants into its tenants, and asking for one (Phase 15 T8-9, T9-6; 07 §4.3).
 *
 * A partner works inside a tenant only under an active grant; the tenant's
 * admins approve and revoke it on their Partner access page.
 */
import React, { useCallback, useEffect, useState } from 'react';

import { Badge, Button, Card, Field, Notice, PageHeader } from '@/components/ui/brand';
import { useAuth } from '@/hooks/useAuth';
import { Customer, Grant, partnerPortal } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';

const SCOPES: Array<[string, string]> = [
    ['read', 'See the workspace'], ['support', 'Help with its work'], ['billing', 'Billing'], ['admin', 'Administer it'],
];
const TONE: Record<Grant['status'], 'positive' | 'warning' | 'neutral' | 'negative'> = {
    active: 'positive', requested: 'warning', expired: 'neutral', revoked: 'negative',
};

export const PartnerAccessGrantsPage: React.FC = () => {
    const { user } = useAuth();
    const admin = user?.role === 'partner_admin';
    const [grants, setGrants] = useState<Grant[]>([]);
    const [customers, setCustomers] = useState<Customer[]>([]);
    const [form, setForm] = useState({ tenant_id: '', scopes: ['read'], reason: '', days: '30' });
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [g, c] = await Promise.all([partnerPortal.grants(), partnerPortal.customers()]);
            setGrants(g);
            setCustomers(c.customers.filter(x => x.relationship === 'resold'));
        } catch (err) {
            setError(apiErrorMessage(err, 'Access could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const ask = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        try {
            await partnerPortal.askAccess({ tenant_id: form.tenant_id, scopes: form.scopes, reason: form.reason,
                                            days: Number(form.days) || undefined });
            setNotice('Asked: the tenant\'s admins approve it on their Partner access page.');
            setForm({ ...form, reason: '' });
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'Access was not asked for'));
        }
    };

    const toggle = (scope: string) => setForm(f => ({
        ...f, scopes: f.scopes.includes(scope) ? f.scopes.filter(s => s !== scope) : [...f.scopes, scope],
    }));

    return (
        <div className="b-page">
            <PageHeader eyebrow="Partner Portal" title="Tenant access"
                        subtitle="You open a tenant's workspace only under a grant it can see and revoke. Every request you make there is logged." />
            {error && <Notice tone="negative">{error}</Notice>}
            {notice && <Notice tone="positive">{notice}</Notice>}
            <Card title="Grants">
                {grants.length === 0 ? <p className="b-muted">No grants yet.</p> : (
                    <table className="b-table">
                        <thead><tr><th>Tenant</th><th>Scopes</th><th>Status</th><th>Reason</th><th>Expires</th></tr></thead>
                        <tbody>
                            {grants.map(g => (
                                <tr key={g.id}>
                                    <td>{g.tenant ?? g.tenant_id}</td>
                                    <td>{g.scopes.join(', ')}</td>
                                    <td><Badge tone={TONE[g.status]}>{g.status}</Badge></td>
                                    <td className="b-muted">{g.reason ?? '—'}</td>
                                    <td>{g.expires_at ? formatDate(g.expires_at) : 'no expiry'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </Card>
            {admin && (
                <Card title="Ask for access">
                    <form className="b-row" onSubmit={ask}>
                        <Field label="Tenant">
                            <select required value={form.tenant_id} onChange={e => setForm({ ...form, tenant_id: e.target.value })}>
                                <option value="">Choose…</option>
                                {customers.map(c => <option key={c.tenant_id} value={c.tenant_id}>{c.name ?? c.tenant_id}</option>)}
                            </select>
                        </Field>
                        <Field label="For (days)">
                            <input type="number" min={1} max={365} value={form.days} onChange={e => setForm({ ...form, days: e.target.value })} />
                        </Field>
                        <Field label="Reason" grow>
                            <input type="text" required value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} />
                        </Field>
                        <fieldset className="b-row" style={{ border: 0, padding: 0 }}>
                            {SCOPES.map(([scope, label]) => (
                                <label key={scope}>
                                    <input type="checkbox" checked={form.scopes.includes(scope)} onChange={() => toggle(scope)} /> {label}
                                </label>
                            ))}
                        </fieldset>
                        <Button type="submit" variant="primary" disabled={!form.scopes.length}>Ask</Button>
                    </form>
                </Card>
            )}
        </div>
    );
};

export default PartnerAccessGrantsPage;
