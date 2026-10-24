/**
 * components/billing/BalanceBar — the business's balance chip and its banners (Phase 15 T9-1; 07 §3).
 *
 * * Balance chip (tenant roles): the available balance in the billing
 *   currency, coloured by state (ok / low / in debt); a click opens Billing.
 * * Balance banner: in debt, over the limit or suspended, with Recharge (06 §6.3).
 * * Lock banner: "Your plan is managed by your partner" when a plan or spend-cap
 *   lock is set (Q5).
 */
import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Lock, Wallet } from 'lucide-react';

import { apiClient } from '@/services/api.client';
import { creditsService } from '@/services/credits.service';
import { formatMoney } from '@/utils/money';

import './BalanceBar.css';

const STATE_TEXT: Record<string, string> = {
    in_debt: 'Your balance is negative: new work waits until it is repaid.',
    over_tolerance: 'Your balance is over its limit: running work has stopped and nothing new starts.',
    suspended: 'Your account is suspended for an unpaid balance: it is read-only until the balance is repaid.',
};

export function useBalance(enabled: boolean) {
    return useQuery({ queryKey: ['wallet', 'balance'], queryFn: creditsService.getBalance, enabled,
                      staleTime: 60_000, refetchInterval: 120_000 });
}

export const BalanceChip: React.FC<{ enabled: boolean; isAdmin: boolean }> = ({ enabled, isAdmin }) => {
    const balance = useBalance(enabled).data;
    if (!balance) return null;
    const debt = Number(balance.debt) > 0;
    const tone = balance.state !== 'ok' || debt ? 'bad' : Number(balance.available) <= 0 ? 'warn' : 'ok';
    const body = (
        <>
            <Wallet size={14} />
            <span>{debt ? `−${formatMoney(balance.debt, balance.currency)}` : formatMoney(balance.available, balance.currency)}</span>
        </>
    );
    return isAdmin
        ? <Link to="/billing" className={`balance-chip ${tone}`} title="Wallet">{body}</Link>
        : <span className={`balance-chip ${tone}`} title="Your company's balance">{body}</span>;
};

export const BalanceBanner: React.FC<{ enabled: boolean; isAdmin: boolean }> = ({ enabled, isAdmin }) => {
    const balance = useBalance(enabled).data;
    if (!balance || balance.state === 'ok' || balance.enforced === false) return null;
    return (
        <div className="shell-banner bad" role="alert">
            <AlertTriangle size={16} />
            <span>{STATE_TEXT[balance.state] ?? `Wallet ${balance.state}`} Owed: {formatMoney(balance.debt, balance.currency)}.</span>
            {isAdmin && <Link to="/billing" className="shell-banner-action">Recharge</Link>}
        </div>
    );
};

export const LockBanner: React.FC<{ companyId?: string; enabled: boolean }> = ({ companyId, enabled }) => {
    const locks = useQuery({
        queryKey: ['locks', companyId],
        queryFn: async () => (await apiClient.get<Array<{ key: string; locked_by_role: string }>>(`/companies/${companyId}/locks`)).data,
        enabled: enabled && !!companyId, staleTime: 5 * 60_000,
    }).data ?? [];
    if (locks.length === 0) return null;
    const byPartner = locks.some(l => l.locked_by_role === 'partner');
    const what = locks.map(l => (l.key === 'spend_cap' ? 'spend cap' : 'plan')).join(' and ');
    return (
        <div className="shell-banner info">
            <Lock size={16} />
            <span>Your {what} {locks.length > 1 ? 'are' : 'is'} managed by {byPartner ? 'your partner' : 'HireBuddha'}.</span>
        </div>
    );
};
