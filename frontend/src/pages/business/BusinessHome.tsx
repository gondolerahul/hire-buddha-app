/**
 * pages/business/BusinessHome — the Business Workspace's home (Phase 15 T9-8, T9-10; 07 §4.5, §8).
 *
 * An admin sees the business at a glance (R-T01: billed against the cap,
 * balance and runway, runs, calls, approvals); a user sees its own work
 * (R-T14). Both get the next things to do.
 */
import React from 'react';
import { Link } from 'react-router-dom';
import { Bot, CheckCircle2, PhoneCall, Wallet } from 'lucide-react';

import { ReportShell } from '@/components/reports/ReportShell';
import { Card, PageHeader } from '@/components/ui/brand';
import { useAuth } from '@/hooks/useAuth';
import { getActingCompany } from '@/services/actingCompany';

export const BusinessHome: React.FC = () => {
    const { user } = useAuth();
    const acting = getActingCompany();
    // Staff and partners acting in a business see its admin view.
    const admin = Boolean(acting) || user?.role === 'tenant_admin';
    const first = user?.full_name?.split(' ')[0];

    const actions: Array<[string, string, string, React.ReactNode]> = [
        ['/agents', 'Run an AI employee', 'Start work, or build a new one from a template', <Bot size={18} key="b" />],
        ['/approvals', 'Approvals', 'Work waiting for a person', <CheckCircle2 size={18} key="c" />],
        ['/calls', 'Calls', 'Live and past calls, campaigns', <PhoneCall size={18} key="p" />],
        ...(admin ? [['/billing', 'Wallet', 'Balance, recharges and what you owe', <Wallet size={18} key="w" />] as [string, string, string, React.ReactNode]] : []),
    ];

    return (
        <div className="b-page">
            <PageHeader eyebrow={acting ? acting.name : 'Business Workspace'} title={first && !acting ? `Hello, ${first}` : 'Home'}
                        subtitle={admin ? 'Your business at a glance.' : 'Your work at a glance.'} />
            <div className="b-tiles">
                {actions.map(([to, title, text, icon]) => (
                    <Link key={to} to={to} style={{ textDecoration: 'none', color: 'inherit' }}>
                        <Card title={<>{icon} {title}</>}><p className="b-muted">{text}</p></Card>
                    </Link>
                ))}
            </div>
            <ReportShell reportId={admin ? 'R-T01' : 'R-T14'} embedded />
            <p className="b-muted" style={{ fontSize: 13 }}>More in <Link to="/reports">Reports</Link>.</p>
        </div>
    );
};

export default BusinessHome;
