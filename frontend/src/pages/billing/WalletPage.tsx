import { formatDate, formatDateTime } from '@/utils/datetime';
import React, { useState, useEffect } from 'react';
import { Wallet, CreditCard, CheckCircle, AlertTriangle, RefreshCw, Star, ListOrdered } from 'lucide-react';
import {
    creditsService, CreditBalance, LedgerEntry, Subscription, TopUpOptions, WalletLot,
} from '@/services/credits.service';
import { formatMoney } from '@/utils/money';
import './WalletPage.css';
import { loadRazorpay } from '@/utils/razorpay';

const LOT_LABEL: Record<WalletLot['kind'], string> = {
    daily: 'Daily credits',
    subscription: 'Subscription credits',
    subscription_bonus: 'Subscription bonus',
    topup: 'Top-up',
    grant: 'Credit from HireBuddha',
};

const ENTRY_LABEL: Record<LedgerEntry['kind'], string> = {
    grant: 'Credit added',
    deduct: 'Usage',
    expire: 'Expired',
    debt_add: 'Usage (owed)',
    debt_repay: 'Debt repaid',
    adjust: 'Adjustment',
    refund: 'Refund',
    convert: 'Currency change',
};

/** What a wallet that is not `ok` means for the company (Phase 15 §6.3). */
function StateBanner({ balance }: { balance: CreditBalance }) {
    if (balance.state === 'ok') return null;
    const owed = formatMoney(balance.debt, balance.currency);
    const text = {
        in_debt: `Your wallet owes ${owed}. New runs, calls and automation wait until it is repaid; work already running finishes.`,
        over_tolerance: `Your wallet owes ${owed}, over its limit. Running work has been stopped and nothing new starts.`,
        suspended: `Your account is suspended for an unpaid balance of ${owed}. It is read-only, and apps and the Data API are off, until the balance is repaid.`,
    }[balance.state];
    return (
        <div className="error-banner wallet-state-banner" role="alert">
            <AlertTriangle size={14} /> {text} A top-up repays the debt first.
        </div>
    );
}

function CreditBucket({ label, amount, currency, expiry, accent, scale }: {
    label: string; amount: number; currency: string; expiry?: string | null; accent?: boolean; scale: number;
}) {
    const pct = scale > 0 ? Math.min((amount / scale) * 100, 100) : 0;
    return (
        <div className={`credit-bucket glass ${accent ? 'accent' : ''}`}>
            <div className="bucket-header">
                <span className="bucket-label">{label}</span>
                <span className="bucket-amount">{formatMoney(amount, currency)}</span>
            </div>
            <div className="bucket-bar">
                <div className="bucket-fill" style={{ width: `${pct}%` }} />
            </div>
            {expiry && (
                <p className="bucket-expiry">Expires: {formatDate(expiry)}</p>
            )}
        </div>
    );
}

export const WalletPage: React.FC = () => {
    const [balance, setBalance] = useState<CreditBalance | null>(null);
    const [subscription, setSubscription] = useState<Subscription | null>(null);
    const [loading, setLoading] = useState(true);
    const [topUpAmount, setTopUpAmount] = useState('');
    const [ledger, setLedger] = useState<LedgerEntry[]>([]);
    const [topping, setTopping] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);
    const [cancellingId, setCancellingId] = useState<string | null>(null);
    // Only the tiers the API offers: the page used to invent three when there
    // were none, which the API then refused (Phase 15 T0-5).
    const [plans, setPlans] = useState<Array<{
        id: string; name: string; tier_level: number; monthly_fee: number; bonus_pct: number;
    }>>([]);
    const [topUpOptions, setTopUpOptions] = useState<TopUpOptions | null>(null);
    // Paying, subscribing and cancelling are the company admins' (T0-3).
    const canPay = topUpOptions?.can_pay ?? false;

    const fetchData = async () => {
        setLoading(true);
        setError(null);
        try {
            const [bal, sub, tiers, options, entries] = await Promise.all([
                creditsService.getBalance(),
                creditsService.getSubscription(),
                creditsService.getSubscriptionTiers().catch(() => []),
                creditsService.getTopUpOptions().catch(() => null),
                creditsService.getLedger(25).catch(() => []),
            ]);
            setBalance(bal);
            setSubscription(sub.subscription);
            setPlans(tiers);
            setTopUpOptions(options);
            setLedger(entries);
            if (options) setTopUpAmount(prev => prev || (options.presets[0] ?? options.min));
        } catch (e: any) {
            setError(e?.response?.data?.detail || 'Failed to load wallet data');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchData(); }, []);

    const currency = balance?.currency ?? topUpOptions?.currency ?? 'INR';

    const handleTopUp = async () => {
        const amount = topUpAmount.trim();
        const amt = Number(amount);
        const min = Number(topUpOptions?.min ?? 0);
        const max = Number(topUpOptions?.max ?? Infinity);
        if (!/^\d+(\.\d{1,2})?$/.test(amount) || amt < min || amt > max) {
            setError(`Enter an amount from ${formatMoney(min, currency)} to ${formatMoney(max, currency)}, `
                + 'with at most two decimals');
            return;
        }
        setTopping(true);
        setError(null);
        try {
            const order = await creditsService.initiateTopUp(amount);
            // Open Razorpay checkout
            let Razorpay: any;
            try {
                Razorpay = await loadRazorpay();
            } catch {
                Razorpay = null;
            }
            if (Razorpay) {
                const rzp = new Razorpay({
                    key: order.key_id,
                    amount: Math.round(amt * 100),
                    currency: order.currency,
                    name: 'HireBuddha',
                    description: 'Wallet Top-Up',
                    order_id: order.order_id,
                    handler: async (response: any) => {
                        try {
                            const result = await creditsService.verifyTopUp({
                                razorpay_order_id: order.order_id,
                                razorpay_payment_id: response.razorpay_payment_id,
                                razorpay_signature: response.razorpay_signature,
                            });
                            setSuccess(`Added ${formatMoney(result.credits_added, result.currency)} to your wallet.`);
                            fetchData();
                        } catch (e: any) {
                            setError('Payment verification failed. Please contact support.');
                        }
                    },
                    prefill: {},
                    theme: { color: '#c9956c' },
                });
                rzp.open();
            } else {
                setError('Razorpay Checkout could not be loaded. Check the connection and try again.');
            }
        } catch (e: any) {
            setError(e?.response?.data?.detail || 'Top-up initiation failed');
        } finally {
            setTopping(false);
        }
    };

    const handleSubscribe = async (tier: number, fee: number) => {
        setError(null);
        try {
            // Step 1: Create a Razorpay subscription on the tier's plan
            const checkout = await creditsService.createSubscription(tier);

            // Step 2: Razorpay checkout authorises the recurring mandate and takes the first charge
            let Razorpay: any;
            try {
                Razorpay = await loadRazorpay();
            } catch {
                Razorpay = null;
            }
            if (Razorpay) {
                const rzp = new Razorpay({
                    key: checkout.key_id,
                    subscription_id: checkout.razorpay_subscription_id,
                    name: 'HireBuddha',
                    description: `Tier ${tier} Subscription — $${fee}/mo`,
                    handler: async (response: any) => {
                        try {
                            // Step 3: Verify the first payment; its credits are granted now
                            const result = await creditsService.verifySubscription({
                                razorpay_payment_id: response.razorpay_payment_id,
                                razorpay_subscription_id: response.razorpay_subscription_id,
                                razorpay_signature: response.razorpay_signature,
                            });
                            setSuccess(`${result.message} — ${result.bonus_credits_pct}% bonus credits every month.`);
                            fetchData();
                        } catch (e: any) {
                            setError('Payment verification failed. Your credits will arrive when Razorpay confirms the payment.');
                        }
                    },
                    prefill: {},
                    theme: { color: '#c9956c' },
                });
                rzp.open();
            } else {
                setError('Razorpay Checkout could not be loaded. Check the connection and try again.');
            }
        } catch (e: any) {
            setError(e?.response?.data?.detail || 'Subscription initiation failed');
        }
    };

    const handleCancel = async (id: string) => {
        if (!confirm('Cancel your subscription? No further payments are taken; credits you have paid for last until they expire.')) return;
        setCancellingId(id);
        try {
            await creditsService.cancelSubscription(id);
            setSuccess('Subscription cancelled. Credits you have paid for last until they expire.');
            fetchData();
        } catch (e: any) {
            setError(e?.response?.data?.detail || 'Cancellation failed');
        } finally {
            setCancellingId(null);
        }
    };

    if (loading) return <div className="wallet-page"><div className="loading-state"><div className="pulse">Loading wallet…</div></div></div>;

    const totalAvail = Number(balance?.available ?? 0);
    const scale = Math.max(totalAvail, 1);

    return (
        <div className="wallet-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Wallet size={24} style={{ marginRight: '0.5rem' }} />Wallet & Credits</h1>
                    <p className="page-subtitle">Manage your credit balance, top-up, and subscription plan</p>
                </div>
                <button className="btn-secondary" onClick={fetchData}><RefreshCw size={14} /> Refresh</button>
            </div>

            {balance && <StateBanner balance={balance} />}
            {error && <div className="error-banner"><AlertTriangle size={14} /> {error}</div>}
            {success && <div className="success-banner"><CheckCircle size={14} /> {success}</div>}

            {/* Credit Overview */}
            <div className="wallet-overview glass">
                <div className="overview-total">
                    <p className="overview-label">Available</p>
                    <p className="overview-amount">{formatMoney(totalAvail, currency)}</p>
                    {balance && balance.held > 0 && (
                        <p className="overview-held">
                            {formatMoney(balance.held, currency)} held by running work · {formatMoney(balance.free, currency)} free
                        </p>
                    )}
                    {balance && Number(balance.debt) > 0 && (
                        <p className="overview-debt">Owed: {formatMoney(balance.debt, currency)}</p>
                    )}
                    <p className="overview-model">
                        {balance?.account_model === 'subscription' ? '📅 Subscription Plan' : '💳 Pay-As-You-Go'}
                    </p>
                </div>

                <div className="credit-buckets">
                    <CreditBucket
                        label="Daily Credits"
                        amount={balance?.daily_credits || 0}
                        currency={currency}
                        scale={scale}
                        expiry={balance?.daily_expires_at}
                        accent
                    />
                    <CreditBucket
                        label="Top-ups"
                        amount={balance?.wallet_balance || 0}
                        currency={currency}
                        scale={scale}
                        expiry={balance?.wallet_expires_at}
                    />
                    {(balance?.account_model === 'subscription'
                        || (balance?.subscription_credits || 0) + (balance?.subscription_bonus_credits || 0) > 0) && (
                        <>
                            <CreditBucket
                                label="Subscription Credits"
                                amount={balance?.subscription_credits || 0}
                                currency={currency}
                                scale={scale}
                                expiry={balance?.sub_credits_expire_at}
                            />
                            <CreditBucket
                                label="Bonus Credits"
                                amount={balance?.subscription_bonus_credits || 0}
                                currency={currency}
                                scale={scale}
                                expiry={balance?.sub_credits_expire_at}
                            />
                        </>
                    )}
                </div>
            </div>

            <div className="wallet-two-col">
                {/* Top-Up Section — the balance is spendable on either account model */}
                {balance && !canPay && (
                    <div className="topup-section glass">
                        <h2 className="section-title"><CreditCard size={18} /> Top Up Wallet</h2>
                        <p className="section-desc">Only your company's admins can add funds or change the plan.</p>
                    </div>
                )}
                {balance && canPay && (
                    <div className="topup-section glass">
                        <h2 className="section-title"><CreditCard size={18} /> Top Up Wallet</h2>
                        <p className="section-desc">
                            Add funds in {currency} via Razorpay. A top-up repays any debt first and is valid
                            for {topUpOptions?.validity_days ?? 90} days.
                        </p>
                        <div className="topup-form">
                            <div className="amount-presets">
                                {(topUpOptions?.presets ?? []).map((v) => (
                                    <button
                                        key={v}
                                        className={`preset-btn ${topUpAmount === v ? 'active' : ''}`}
                                        onClick={() => setTopUpAmount(v)}
                                    >
                                        {formatMoney(v, currency, { digits: 0 })}
                                    </button>
                                ))}
                            </div>
                            <div className="custom-amount">
                                <span className="currency-symbol">{currency}</span>
                                <input
                                    type="number"
                                    min={topUpOptions?.min}
                                    max={topUpOptions?.max}
                                    step="0.01"
                                    value={topUpAmount}
                                    onChange={(e) => setTopUpAmount(e.target.value)}
                                    placeholder="Custom amount"
                                />
                            </div>
                            <button className="btn-primary full-width" onClick={handleTopUp} disabled={topping}>
                                {topping ? 'Processing…' : `Top up ${formatMoney(topUpAmount || 0, currency)}`}
                            </button>
                        </div>
                    </div>
                )}

                {/* Active Subscription */}
                {subscription && (
                    <div className="active-subscription glass">
                        <h2 className="section-title"><Star size={18} /> {subscription.status === 'active' ? 'Active Subscription' : 'Subscription'}</h2>
                        {subscription.status === 'past_due' && (
                            <div className="error-banner"><AlertTriangle size={14} /> The last payment failed. Razorpay is retrying; no credits are granted until a payment succeeds.</div>
                        )}
                        {subscription.status === 'paused' && (
                            <div className="error-banner"><AlertTriangle size={14} /> Paused — no payments are taken and no credits are granted.</div>
                        )}
                        <div className="sub-details">
                            <div className="sub-tier-badge">Tier {subscription.plan_tier}</div>
                            <p className="sub-fee">${subscription.monthly_fee}/mo</p>
                            <p className="sub-bonus">+{subscription.bonus_pct}% Bonus Credits</p>
                            {subscription.next_billing_date && (
                                <p className="sub-next">Paid through: {formatDate(subscription.next_billing_date)}</p>
                            )}
                        </div>
                        {canPay && (
                            <button
                                className="btn-danger"
                                onClick={() => handleCancel(subscription.id)}
                                disabled={cancellingId === subscription.id}
                            >
                                {cancellingId === subscription.id ? 'Cancelling…' : 'Cancel Subscription'}
                            </button>
                        )}
                    </div>
                )}
            </div>

            {/* Credit lots and the ledger (Phase 15 T4-1) */}
            <div className="wallet-two-col">
                <div className="wallet-lots glass">
                    <h2 className="section-title"><Wallet size={18} /> Credit lots</h2>
                    <p className="section-desc">
                        Spent in this order: daily, subscription, bonus, then top-ups by the earliest expiry.
                    </p>
                    {(balance?.lots ?? []).length === 0 ? (
                        <p className="section-desc">No credit right now.</p>
                    ) : (
                        <table className="wallet-table">
                            <thead><tr><th>Kind</th><th>Left</th><th>Of</th><th>Expires</th></tr></thead>
                            <tbody>
                                {(balance?.lots ?? []).map((lot) => (
                                    <tr key={lot.id}>
                                        <td>{LOT_LABEL[lot.kind] ?? lot.kind}</td>
                                        <td>{formatMoney(lot.remaining, currency)}</td>
                                        <td>{formatMoney(lot.original, currency)}</td>
                                        <td>{lot.expires_at ? formatDate(lot.expires_at) : '—'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
                <div className="wallet-ledger glass">
                    <h2 className="section-title"><ListOrdered size={18} /> Recent activity</h2>
                    {ledger.length === 0 ? (
                        <p className="section-desc">Nothing yet.</p>
                    ) : (
                        <table className="wallet-table">
                            <thead><tr><th>When</th><th>What</th><th>Amount</th><th>Balance</th></tr></thead>
                            <tbody>
                                {ledger.map((e) => (
                                    <tr key={e.id}>
                                        <td>{e.created_at ? formatDateTime(e.created_at) : ''}</td>
                                        <td>
                                            {e.source_type === 'staff' ? 'Adjustment by HireBuddha' : ENTRY_LABEL[e.kind] ?? e.kind}
                                            {e.category ? ` · ${e.category.replace('_', ' ')}` : ''}
                                        </td>
                                        <td className={Number(e.amount) < 0 ? 'amount-out' : 'amount-in'}>
                                            {formatMoney(e.amount, e.currency)}
                                        </td>
                                        <td>
                                            {formatMoney(e.balance_after, e.currency)}
                                            {Number(e.debt_after) > 0 && (
                                                <span className="ledger-debt"> (owes {formatMoney(e.debt_after, e.currency)})</span>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>

            {/* Subscription Plans */}
            {!subscription && (
                <div className="plans-section">
                    <h2 className="section-title"><Star size={18} /> Subscription Plans</h2>
                    <p className="section-desc">
                        Subscribe for a monthly auto-debit via Razorpay and bonus credits every month.
                        Credits are spent soonest-expiring first: daily, then subscription, then your wallet balance.
                    </p>
                    {plans.length === 0 && (
                        <p className="section-desc plans-empty">No plans are available at the moment.</p>
                    )}
                    <div className="plans-grid">
                        {plans.map((plan) => (
                            <div key={plan.tier_level} className={`plan-card glass ${plan.tier_level === 2 ? 'popular' : ''}`}>
                                {plan.tier_level === 2 && <div className="popular-badge">Most Popular</div>}
                                <h3 className="plan-name">{plan.name}</h3>
                                <p className="plan-price">${plan.monthly_fee}<span>/mo</span></p>
                                <p className="plan-bonus">+{plan.bonus_pct}% Bonus Credits</p>
                                <ul className="plan-features">
                                    <li><CheckCircle size={14} />{plan.bonus_pct}% Bonus Credits</li>
                                    {plan.tier_level >= 2 && <li><CheckCircle size={14} />Priority Support</li>}
                                    {plan.tier_level >= 3 && <li><CheckCircle size={14} />Unlimited Agents</li>}
                                </ul>
                                {canPay && (
                                    <button
                                        className="btn-primary full-width"
                                        onClick={() => handleSubscribe(plan.tier_level, plan.monthly_fee)}
                                    >
                                        Subscribe — ${plan.monthly_fee}/mo
                                    </button>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};
