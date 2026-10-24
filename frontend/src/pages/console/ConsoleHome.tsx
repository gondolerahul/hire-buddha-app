/**
 * pages/console/ConsoleHome — the Platform Console's home (Phase 15 T9-9, T9-10; 07 §4.1, §8).
 *
 * The platform overview (R-A01) and, for each staff function the viewer has,
 * the places that function works in. An app_admin has them all.
 */
import React from 'react';
import { Link } from 'react-router-dom';

import { ReportShell } from '@/components/reports/ReportShell';
import { Card, PageHeader } from '@/components/ui/brand';
import { useAuth } from '@/hooks/useAuth';
import { StaffFunction } from '@/types';

const DESKS: Array<{ fn: StaffFunction; title: string; links: Array<[string, string]> }> = [
    { fn: 'support', title: 'Support', links: [['/console/companies', 'Companies'], ['/console/users', 'Users'],
                                               ['/console/ops/runs', 'Runs'], ['/console/ops/approvals', 'Approvals oversight']] },
    { fn: 'sales', title: 'Sales', links: [['/console/leads', 'Leads'], ['/console/partners', 'Partner network'],
                                           ['/console/reports/R-A08', 'Acquisition funnel'], ['/console/reports/R-A09', 'Partner performance']] },
    { fn: 'finance', title: 'Finance', links: [['/console/finance/revenue', 'Revenue & margin'], ['/console/finance/receivables', 'Receivables'],
                                               ['/console/finance/payments', 'Payments & invoices'], ['/console/finance/payouts', 'Partner payouts']] },
    { fn: 'ops', title: 'Operations', links: [['/console/ops/health', 'Health & incidents'], ['/console/ops/automation', 'Automation'],
                                              ['/console/ops/numbers', 'Phone number pool'], ['/console/audit', 'Audit log']] },
];

export const ConsoleHome: React.FC = () => {
    const { user } = useAuth();
    const mine = user?.role === 'app_admin' ? DESKS.map(d => d.fn) : user?.staff_functions ?? [];
    return (
        <div className="b-page">
            <PageHeader eyebrow="Platform Console" title={`Hello${user?.full_name ? `, ${user.full_name.split(' ')[0]}` : ''}`}
                        subtitle="The platform at a glance. Amounts are in the console's display currency." />
            <div className="b-tiles">
                {DESKS.filter(d => mine.includes(d.fn)).map(d => (
                    <Card key={d.fn} eyebrow="Your desk" title={d.title}>
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                            {d.links.map(([to, label]) => <li key={to}><Link to={to}>{label}</Link></li>)}
                        </ul>
                    </Card>
                ))}
            </div>
            <h2 className="b-section-title">Waiting for you</h2>
            <ReportShell reportId="R-A25" embedded />
            <h2 className="b-section-title">The platform this month</h2>
            <ReportShell reportId="R-A01" embedded />
        </div>
    );
};

export default ConsoleHome;
