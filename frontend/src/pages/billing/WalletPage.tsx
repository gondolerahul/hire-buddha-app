import { parseServerDate } from '@/utils/datetime';
import React, { useState, useEffect } from 'react';
import { Wallet, CreditCard, CheckCircle, AlertTriangle, RefreshCw, Star } from 'lucide-react';
import { creditsService, CreditBalance, Subscription } from '@/services/credits.service';
import './WalletPage.css';
import { loadRazorpay } from '@/utils/razorpay';



function CreditBucket({ label, amount, expiry, accent }: {
    label: string; amount: number; expiry?: string | null; accent?: boolean;
}) {
    const pct = Math.min((amount / 50) * 100, 100);
    return (
        <div className={`credit-bucket glass ${accent ? 'accent' : ''}`}>
            <div className="bucket-header">
                <span className="bucket-label">{label}</span>
                <span className="bucket-amount">${amount.toFixed(2)}</span>
            </div>
            <div className="bucket-bar">
                <div className="bucket-fill" style={{ width: `${pct}%` }} />
            </div>
            {expiry && (
                <p className="bucket-expiry">Expires: {parseServerDate(expiry).toLocaleDateString()}</p>
            )}
        </div>
    );
}

export const WalletPage: React.FC = () => {
    const [balance, setBalance] = useState<CreditBalance | null>(null);
    const [subscription, setSubscription] = useState<Subscription | null>(null);
    const [loading, setLoading] = useState(true);
    const [topUpAmount, setTopUpAmount] = useState('10');
    const [topping, setTopping] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);
    const [cancellingId, setCancellingId] = useState<string | null>(null);
    const [subscriptionTiers, setSubscriptionTiers] = useState<Array<{
        id: string; name: string; tier_level: number; monthly_fee: number; bonus_pct: number;
    }>>([]);

    // Fallback plans if API returns empty (initial seed)
    const FALLBACK_PLANS = [
        { tier_level: 1, name: 'Starter', monthly_fee: 29, bonus_pct: 20 },
        { tier_level: 2, name: 'Growth', monthly_fee: 79, bonus_pct: 30 },
        { tier_level: 3, name: 'Scale', monthly_fee: 199, bonus_pct: 40 },
    ];

    const plans = subscriptionTiers.length > 0 ? subscriptionTiers : FALLBACK_PLANS;

    const fetchData = async () => {
        setLoading(true);
        setError(null);
        try {
            const [bal, sub, tiers] = await Promise.all([
                creditsService.getBalance(),
                creditsService.getSubscription(),
                creditsService.getSubscriptionTiers().catch(() => []),
            ]);
            setBalance(bal);
            setSubscription(sub.subscription);
            setSubscriptionTiers(tiers);
        } catch (e: any) {
            setError(e?.response?.data?.detail || 'Failed to load wallet data');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchData(); }, []);

    const handleTopUp = async () => {
        const amt = parseFloat(topUpAmount);
        if (isNaN(amt) || amt < 1) { setError('Please enter a valid amount (min $1)'); return; }
        setTopping(true);
        setError(null);
        try {
            const order = await creditsService.initiateTopUp(amt);
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
                    amount: amt * 100,
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
                            setSuccess(`Successfully added $${result.credits_added.toFixed(2)} to your wallet!`);
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

    const totalAvail = balance?.total_available || 0;

    return (
        <div className="wallet-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Wallet size={24} style={{ marginRight: '0.5rem' }} />Wallet & Credits</h1>
                    <p className="page-subtitle">Manage your credit balance, top-up, and subscription plan</p>
                </div>
                <button className="btn-secondary" onClick={fetchData}><RefreshCw size={14} /> Refresh</button>
            </div>

            {error && <div className="error-banner"><AlertTriangle size={14} /> {error}</div>}
            {success && <div className="success-banner"><CheckCircle size={14} /> {success}</div>}

            {/* Credit Overview */}
            <div className="wallet-overview glass">
                <div className="overview-total">
                    <p className="overview-label">Total Available</p>
                    <p className="overview-amount">${totalAvail.toFixed(2)}</p>
                    <p className="overview-model">
                        {balance?.account_model === 'subscription' ? '📅 Subscription Plan' : '💳 Pay-As-You-Go'}
                    </p>
                </div>

                <div className="credit-buckets">
                    <CreditBucket
                        label="Daily Credits"
                        amount={balance?.daily_credits || 0}
                        expiry={balance?.daily_expires_at}
                        accent
                    />
                    <CreditBucket
                        label="Wallet Balance"
                        amount={balance?.wallet_balance || 0}
                        expiry={balance?.wallet_expires_at}
                    />
                    {(balance?.account_model === 'subscription'
                        || (balance?.subscription_credits || 0) + (balance?.subscription_bonus_credits || 0) > 0) && (
                        <>
                            <CreditBucket
                                label="Subscription Credits"
                                amount={balance?.subscription_credits || 0}
                                expiry={balance?.sub_credits_expire_at}
                            />
                            <CreditBucket
                                label="Bonus Credits"
                                amount={balance?.subscription_bonus_credits || 0}
                                expiry={balance?.sub_credits_expire_at}
                            />
                        </>
                    )}
                </div>
            </div>

            <div className="wallet-two-col">
                {/* Top-Up Section — the balance is spendable on either account model */}
                {balance && (
                    <div className="topup-section glass">
                        <h2 className="section-title"><CreditCard size={18} /> Top Up Wallet</h2>
                        <p className="section-desc">Add funds via Razorpay. Balance is valid for 365 days.</p>
                        <div className="topup-form">
                            <div className="amount-presets">
                                {[10, 25, 50, 100].map((v) => (
                                    <button
                                        key={v}
                                        className={`preset-btn ${topUpAmount === String(v) ? 'active' : ''}`}
                                        onClick={() => setTopUpAmount(String(v))}
                                    >
                                        ${v}
                                    </button>
                                ))}
                            </div>
                            <div className="custom-amount">
                                <span className="currency-symbol">$</span>
                                <input
                                    type="number"
                                    min="1"
                                    step="1"
                                    value={topUpAmount}
                                    onChange={(e) => setTopUpAmount(e.target.value)}
                                    placeholder="Custom amount"
                                />
                            </div>
                            <button className="btn-primary full-width" onClick={handleTopUp} disabled={topping}>
                                {topping ? 'Processing…' : `Top Up $${topUpAmount}`}
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
                                <p className="sub-next">Paid through: {parseServerDate(subscription.next_billing_date).toLocaleDateString()}</p>
                            )}
                        </div>
                        <button
                            className="btn-danger"
                            onClick={() => handleCancel(subscription.id)}
                            disabled={cancellingId === subscription.id}
                        >
                            {cancellingId === subscription.id ? 'Cancelling…' : 'Cancel Subscription'}
                        </button>
                    </div>
                )}
            </div>

            {/* Subscription Plans */}
            {!subscription && (
                <div className="plans-section">
                    <h2 className="section-title"><Star size={18} /> Subscription Plans</h2>
                    <p className="section-desc">
                        Subscribe for a monthly auto-debit via Razorpay and bonus credits every month.
                        Credits are spent soonest-expiring first: daily, then subscription, then your wallet balance.
                    </p>
                    <div className="plans-grid">
                        {plans.map((plan: any) => (
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
                                <button
                                    className="btn-primary full-width"
                                    onClick={() => handleSubscribe(plan.tier_level, plan.monthly_fee)}
                                >
                                    Subscribe — ${plan.monthly_fee}/mo
                                </button>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};
