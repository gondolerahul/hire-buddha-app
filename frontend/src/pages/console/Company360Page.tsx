/**
 * pages/console/Company360Page — one company, everything staff need about it (Phase 15 T9-9; 07 §4.1 Company 360).
 *
 * Profile, wallet, plan entitlements and partner, its people, and its reports
 * (revenue, execution health, audit) filtered to it. "Work in this business"
 * opens the Business Workspace as the company (acting, audited).
 */
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { ReportShell } from '@/components/reports/ReportShell';
import { Badge, Button, Card, Notice, PageHeader, Tabs, Tile } from '@/components/ui/brand';
import { useAuth } from '@/hooks/useAuth';
import { setActingCompany } from '@/services/actingCompany';
import { companyService } from '@/services/company.service';
import { moneyConsole, WalletDetail } from '@/services/moneyConsole.service';
import { Assignment, partnerAdmin } from '@/services/partners.service';
import { EntitlementValue, plansService } from '@/services/plans.service';
import { userService } from '@/services/user.service';
import { Company, User } from '@/types';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

const TABS = [
    { id: 'overview', label: 'Overview' }, { id: 'revenue', label: 'Revenue' }, { id: 'health', label: 'Runs' },
    { id: 'audit', label: 'Changes' },
];

export const Company360Page: React.FC = () => {
    const { id = '' } = useParams();
    const navigate = useNavigate();
    const { user } = useAuth();
    const admin = user?.role === 'app_admin';
    const [tab, setTab] = useState('overview');
    const [company, setCompany] = useState<Company | null>(null);
    const [wallet, setWallet] = useState<WalletDetail | null>(null);
    const [entitlements, setEntitlements] = useState<Record<string, EntitlementValue>>({});
    const [assignments, setAssignments] = useState<Assignment[]>([]);
    const [people, setPeople] = useState<User[]>([]);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        companyService.list().then(all => setCompany(all.find(c => c.id === id) ?? null))
            .catch(err => setError(apiErrorMessage(err, 'The company could not be loaded')));
        // Each part is optional: a staff function may not reach it.
        moneyConsole.getWallet(id).then(setWallet).catch(() => setWallet(null));
        if (admin) plansService.companyEntitlements(id).then(r => setEntitlements(r.entitlements)).catch(() => setEntitlements({}));
        partnerAdmin.assignments({ tenant_id: id }).then(setAssignments).catch(() => setAssignments([]));
        userService.getUsers().then(all => setPeople(all.filter(u => u.company_id === id))).catch(() => setPeople([]));
    }, [id, admin]);

    const workIn = () => {
        if (!company) return;
        setActingCompany({ id: company.id, name: company.name });
        navigate('/home');
        window.location.reload();
    };

    const current = assignments.find(a => !a.until);
    const w = wallet?.wallet;
    return (
        <div className="b-page">
            <PageHeader eyebrow="Company 360" title={company?.name ?? 'Company'}
                        subtitle={company ? `${company.type === 'TENANT' ? 'Business' : company.type === 'PARTNER' ? 'Partner' : 'Platform'} · ${company.country_code ?? '—'} · billed in ${company.billing_currency ?? '—'}` : undefined}
                        actions={company?.type === 'TENANT' && <Button variant="primary" onClick={workIn}>Work in this business</Button>} />
            {error && <Notice tone="negative">{error}</Notice>}
            <Tabs tabs={TABS} value={tab} onChange={setTab} />
            {tab === 'overview' && (
                <>
                    <div className="b-tiles">
                        <Tile label="Status" value={company ? <Badge tone={company.status === 'active' ? 'positive' : 'negative'}>{company.status}</Badge> : '—'} />
                        <Tile label="Balance" value={w ? formatMoney(w.available, w.currency) : '—'}
                              tone={w && w.state !== 'ok' ? 'negative' : 'neutral'} hint={w ? `wallet ${w.state}` : undefined} />
                        <Tile label="Owed" value={w ? formatMoney(w.debt, w.currency) : '—'} tone={w && Number(w.debt) > 0 ? 'warning' : 'neutral'} />
                        <Tile label="Spend cap" value={company?.monthly_spend_cap_usd ? formatMoney(company.monthly_spend_cap_usd, 'USD') : 'none'} />
                        <Tile label="People" value={people.length} />
                    </div>
                    <Card title="Partner">
                        {current ? (
                            <p>{current.partner} · {current.relationship} since {current.since ? formatDate(current.since) : '—'}
                                {current.commission_until ? ` · commission until ${formatDate(current.commission_until)}` : ''}</p>
                        ) : <p className="b-muted">Direct customer of HireBuddha.</p>}
                    </Card>
                    {admin && Object.keys(entitlements).length > 0 && (
                        <Card title="Plan and entitlements">
                            <table className="b-table">
                                <tbody>
                                    {Object.entries(entitlements).sort(([a], [b]) => a.localeCompare(b)).map(([key, v]) => (
                                        <tr key={key}>
                                            <td>{key}</td>
                                            <td>{v.enabled ? (v.limit !== null ? `up to ${v.limit}` : 'yes') : 'no'}</td>
                                            <td className="b-muted">{v.source ?? ''}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </Card>
                    )}
                    <Card title="People">
                        <table className="b-table">
                            <tbody>
                                {people.map(p => (
                                    <tr key={p.id}><td>{p.full_name}</td><td>{p.email}</td><td>{p.role}</td>
                                        <td>{p.is_active ? 'active' : 'deactivated'}</td></tr>
                                ))}
                            </tbody>
                        </table>
                    </Card>
                </>
            )}
            {tab === 'revenue' && <ReportShell reportId="R-A02" companyId={id} embedded />}
            {tab === 'health' && <ReportShell reportId="R-A19" companyId={id} embedded />}
            {tab === 'audit' && <ReportShell reportId="R-A24" companyId={id} embedded />}
        </div>
    );
};

export default Company360Page;
