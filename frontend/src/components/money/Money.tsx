/**
 * <Money> and <DualMoney> — amounts on screen (Phase 15 T2-5).
 *
 * <Money amount={1250} currency="INR" />            → ₹1,250.00
 * <DualMoney amount={1250} currency="INR" usd={12.5} /> → ₹1,250.00 ($12.50) — staff views (REQ-BL-4)
 *
 * With no `currency`, the signed-in company's billing currency is used.
 */
import React from 'react';

import { useAuth } from '@/hooks/useAuth';
import { formatMoney, MoneyOptions } from '@/utils/money';

interface MoneyProps extends MoneyOptions {
    amount: number | string | null | undefined;
    currency?: string;
    className?: string;
}

export const Money: React.FC<MoneyProps> = ({ amount, currency, className, ...options }) => {
    const { user } = useAuth();
    const code = currency ?? user?.billing_currency ?? 'INR';
    return <span className={className} title={`${amount ?? 0} ${code}`}>{formatMoney(amount, code, options)}</span>;
};

interface DualMoneyProps extends MoneyProps {
    /** The same amount in USD, shown beside it (staff views). */
    usd?: number | string | null;
}

export const DualMoney: React.FC<DualMoneyProps> = ({ usd, ...props }) => (
    <span className={props.className}>
        <Money {...props} className={undefined} />
        {usd != null && props.currency !== 'USD' && (
            <span className="money-usd" style={{ opacity: 0.6, marginLeft: '0.35em' }}>
                ({formatMoney(usd, 'USD', { digits: props.digits, smallDigits: props.smallDigits })})
            </span>
        )}
    </span>
);
