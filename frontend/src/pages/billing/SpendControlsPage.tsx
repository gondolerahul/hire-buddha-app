/**
 * pages/billing/SpendControlsPage — what the business lets itself spend (Phase 15 T9-8; 07 §4.5 Billing).
 *
 * The monthly spend cap (a limit on what is billed in a calendar month), this
 * month's billed amount against it, and who manages it: a cap a partner or
 * HireBuddha locked is shown, not edited. Automation budgets are on their own
 * page.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { Button, Card, Field, Notice, PageHeader, Tile } from '@/components/ui/brand';
import { useAuth } from '@/hooks/useAuth';
import { apiClient } from '@/services/api.client';
import { getActingCompany } from '@/services/actingCompany';
import { companyService } from '@/services/company.service';
import { ReportData, reportLibrary } from '@/services/reportLibrary.service';
import { Company } from '@/types';
import { apiErrorMessage } from '@/utils/apiError';
import { formatMoney } from '@/utils/money';

interface Lock { key: string; locked_by_role: string }

export const SpendControlsPage: React.FC = () => {
    const { user } = useAuth();
    const companyId = getActingCompany()?.id ?? user?.company_id;
    const [company, setCompany] = useState<Company | null>(null);
    const [overview, setOverview] = useState<ReportData | null>(null);
    const [locks, setLocks] = useState<Lock[]>([]);
    const [cap, setCap] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        if (!companyId) return;
        try {
            const [companies, report, held] = await Promise.all([
                companyService.list(), reportLibrary.run('R-T01', {}),
                apiClient.get<Lock[]>(`/companies/${companyId}/locks`).then(r => r.data),
            ]);
            const own = companies.find(c => c.id === companyId) ?? null;
            setCompany(own);
            setCap(own?.monthly_spend_cap_usd ? String(own.monthly_spend_cap_usd) : '');
            setOverview(report);
            setLocks(held);
        } catch (err) {
            setError(apiErrorMessage(err, 'Spend controls could not be loaded'));
        }
    }, [companyId]);

    useEffect(() => { load(); }, [load]);

    const capLock = locks.find(l => l.key === 'spend_cap');
    const billed = overview?.tiles.find(t => t.label === 'Billed');
    const balance = overview?.tiles.find(t => t.label === 'Balance');
    const runway = overview?.tiles.find(t => t.label === 'Runway');
    const currency = overview?.currency ?? company?.billing_currency ?? 'INR';

    const save = async (value: number | null) => {
        if (!companyId) return;
        setError(null);
        setNotice(null);
        try {
            await companyService.updateCompany(companyId, { monthly_spend_cap_usd: value });
            setNotice(value ? 'The spend cap is saved. Work that would pass it waits until next month or a higher cap.'
                : 'The spend cap is removed.');
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The spend cap was not saved'));
        }
    };

    return (
        <div className="b-page">
            <PageHeader eyebrow="Billing" title="Spend controls"
                        subtitle="Limits on what your company is billed. Your wallet still needs a balance for work to run." />
            {error && <Notice tone="negative">{error}</Notice>}
            {notice && <Notice tone="positive">{notice}</Notice>}
            <div className="b-tiles">
                <Tile label="Billed this month" value={billed ? formatMoney(billed.value, currency) : '—'} hint={billed?.hint ?? undefined} />
                <Tile label="Balance" value={balance ? formatMoney(balance.value, currency) : '—'} tone={(balance?.tone as any) ?? 'neutral'} />
                <Tile label="Runway" value={runway?.value ?? '—'} hint={runway?.hint ?? undefined} />
            </div>
            <Card title="Monthly spend cap">
                {capLock ? (
                    <Notice tone="warning">
                        Your spend cap is managed by {capLock.locked_by_role === 'partner' ? 'your partner' : 'HireBuddha'}
                        {company?.monthly_spend_cap_usd ? `: ${formatMoney(company.monthly_spend_cap_usd, 'USD')} a month` : ': no cap'}.
                        Ask them to change it.
                    </Notice>
                ) : (
                    <form className="b-row" onSubmit={e => { e.preventDefault(); save(cap ? Number(cap) : null); }}>
                        <Field label="Cap (USD a month)" hint={`Billed amounts are in ${currency}; the cap converts at the day's rate`}>
                            <input type="number" min={1} step="0.01" value={cap} onChange={e => setCap(e.target.value)} placeholder="No cap" />
                        </Field>
                        <Button type="submit" variant="primary">Save</Button>
                        {company?.monthly_spend_cap_usd && <Button type="button" variant="ghost" onClick={() => save(null)}>Remove the cap</Button>}
                    </form>
                )}
            </Card>
            <Card title="More controls">
                <ul className="b-muted">
                    <li>Automation budgets and run limits: <Link to="/settings/automation">Automation settings</Link>.</li>
                    <li>Recharges, credit and what you owe: <Link to="/billing">Wallet</Link>.</li>
                    <li>Spend by person and by AI employee: <Link to="/reports/R-T10">Spend by user</Link>, <Link to="/reports/R-T05">AI employee performance</Link>.</li>
                </ul>
            </Card>
        </div>
    );
};

export default SpendControlsPage;
