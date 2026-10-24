/**
 * pages/billing/PlanPage — the company's plan (Phase 15 T6-7, tech design §10, §12; 07 §6.2).
 *
 * The current plan, the plans on offer side by side with what each includes,
 * and subscribing, changing or cancelling. Prices are net in the company's
 * currency with GST added at checkout. An upgrade applies now (the gateway
 * charges the difference); a downgrade and a cancellation wait for the end of
 * the paid cycle. Pay-as-you-go is the plan with no fee.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Check, Minus, Star } from 'lucide-react';

import {
    plansService, PlanOffer, PlansOnOffer, PlanSubscription, withGst,
} from '@/services/plans.service';
import { creditsService } from '@/services/credits.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';
import { loadRazorpay } from '@/utils/razorpay';

import './WalletPage.css';
import './PlanPage.css';

function limitText(limit: number | null | undefined): string {
    return limit === null || limit === undefined ? 'Unlimited' : String(limit);
}

export const PlanPage: React.FC = () => {
    const [offer, setOffer] = useState<PlansOnOffer | null>(null);
    const [subscription, setSubscription] = useState<PlanSubscription | null>(null);
    const [canPay, setCanPay] = useState(false);
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [plans, sub, options] = await Promise.all([
                plansService.listPlans(), plansService.getSubscription(),
                creditsService.getTopUpOptions().catch(() => null),
            ]);
            setOffer(plans);
            setSubscription(sub.subscription);
            setCanPay(options?.can_pay ?? false);
            setError(null);
        } catch (err) {
            setError(apiErrorMessage(err, 'The plans could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const current = offer?.plans.find(p => p.current) ?? null;
    const pending = subscription?.pending_plan_id ? offer?.plans.find(p => p.id === subscription.pending_plan_id) : null;
    const groups = useMemo(() => {
        const out: Record<string, PlansOnOffer['features']> = {};
        for (const f of offer?.features ?? []) (out[f.group] ??= []).push(f);
        return out;
    }, [offer]);

    const subscribe = async (plan: PlanOffer) => {
        setBusy(plan.id);
        setError(null);
        try {
            const checkout = await plansService.subscribe(plan.id);
            let Razorpay: any;
            try {
                Razorpay = await loadRazorpay();
            } catch {
                Razorpay = null;
            }
            if (!Razorpay) {
                setError('Razorpay Checkout could not be loaded. Check the connection and try again.');
                return;
            }
            new Razorpay({
                key: checkout.key_id,
                subscription_id: checkout.razorpay_subscription_id,
                name: 'HireBuddha',
                description: `${plan.name} — ${formatMoney(checkout.amount, checkout.currency)} a month incl. GST`,
                handler: async (response: any) => {
                    try {
                        await plansService.verifySubscription({
                            razorpay_payment_id: response.razorpay_payment_id,
                            razorpay_subscription_id: response.razorpay_subscription_id,
                            razorpay_signature: response.razorpay_signature,
                        });
                        setSuccess(`You are on ${plan.name}. This month's credits are in your wallet, and the invoice is on the Invoices page.`);
                        load();
                    } catch {
                        setError('Payment verification failed. Your credits will arrive when Razorpay confirms the payment.');
                    }
                },
                prefill: {},
                theme: { color: '#c9956c' },
            }).open();
        } catch (err) {
            setError(apiErrorMessage(err, 'The subscription could not be started'));
        } finally {
            setBusy(null);
        }
    };

    const change = async (plan: PlanOffer) => {
        if (!current) return;
        const upgrade = plan.tier_level > current.tier_level;
        const ask = upgrade
            ? `Move to ${plan.name} now? The difference for the rest of this cycle is charged now, and its credits added.`
            : `Move to ${plan.name} at the end of the paid cycle${subscription?.next_billing_date ? ` (${formatDate(subscription.next_billing_date)})` : ''}? You keep ${current.name} until then.`;
        if (!confirm(ask)) return;
        setBusy(plan.id);
        setError(null);
        try {
            const result = await plansService.changePlan(plan.id);
            setSuccess(result.change === 'upgrade' ? `You are on ${plan.name} now.`
                : `You move to ${plan.name} on ${result.effective.includes('T') ? formatDate(result.effective) : result.effective}.`);
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The plan could not be changed'));
        } finally {
            setBusy(null);
        }
    };

    const cancel = async () => {
        if (!subscription) return;
        if (!confirm('Cancel the subscription at the end of the paid cycle? No more payments are taken; you then go to pay-as-you-go, and credits already paid for last until they expire.')) return;
        setBusy('cancel');
        try {
            const result = await plansService.cancel(subscription.id);
            setSuccess(result.ends ? `Your subscription ends on ${formatDate(result.ends)}.` : result.message);
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The subscription could not be cancelled'));
        } finally {
            setBusy(null);
        }
    };

    const action = (plan: PlanOffer) => {
        if (plan.current) return <span className="plan-current-tag">Your plan</span>;
        if (!canPay) return null;
        if (plan.tier_level === 0) {
            return subscription && !subscription.cancel_at_cycle_end
                ? <button className="btn-secondary full-width" onClick={cancel} disabled={!!busy}>Go to pay-as-you-go</button>
                : null;
        }
        if (subscription && current && current.tier_level > 0) {
            return (
                <button className="btn-primary full-width" onClick={() => change(plan)} disabled={!!busy}>
                    {busy === plan.id ? 'Working…' : plan.tier_level > current.tier_level ? 'Upgrade now' : 'Downgrade at cycle end'}
                </button>
            );
        }
        return (
            <button className="btn-primary full-width" onClick={() => subscribe(plan)} disabled={!!busy}>
                {busy === plan.id ? 'Opening checkout…' : 'Subscribe'}
            </button>
        );
    };

    if (!offer) {
        return (
            <div className="wallet-page">
                {error ? <div className="error-banner">{error}</div> : <div className="loading-state"><div className="pulse">Loading plans…</div></div>}
            </div>
        );
    }

    return (
        <div className="wallet-page plan-page">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Star size={22} /> Plan</h1>
                    <p className="page-subtitle">
                        What your plan includes and costs. Prices are in {offer.currency} before GST; the monthly fee
                        becomes credit in your <Link to="/billing">wallet</Link>, with the plan's bonus on top.
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {success && <div className="success-banner">{success}</div>}

            <div className="plan-summary glass">
                <div>
                    <p className="overview-label">Current plan</p>
                    <p className="plan-summary-name">{current?.name ?? 'Pay-as-you-go'}</p>
                    {subscription && (
                        <p className="section-desc">
                            {formatMoney(subscription.amount, subscription.currency)} a month before GST
                            {subscription.next_billing_date && <> · paid through {formatDate(subscription.next_billing_date)}</>}
                        </p>
                    )}
                </div>
                <div className="plan-summary-notes">
                    {subscription?.status === 'past_due' && (
                        <p className="error-banner"><AlertTriangle size={14} /> The last payment failed. Razorpay is retrying; no credits are granted until a payment succeeds.</p>
                    )}
                    {subscription?.cancel_at_cycle_end && (
                        <p className="section-desc">Cancelled: ends {subscription.next_billing_date ? formatDate(subscription.next_billing_date) : 'at the end of the cycle'}, then pay-as-you-go.</p>
                    )}
                    {pending && <p className="section-desc">Moving to {pending.name} at the end of the cycle.</p>}
                    {!canPay && <p className="section-desc">Only your company's admins can change the plan.</p>}
                    {canPay && subscription && !subscription.cancel_at_cycle_end && (
                        <button className="btn-danger" onClick={cancel} disabled={!!busy}>Cancel subscription</button>
                    )}
                </div>
            </div>

            <div className="plan-compare glass">
                <table className="plan-table">
                    <thead>
                        <tr>
                            <th />
                            {offer.plans.map(plan => {
                                const price = withGst(plan.monthly_fee, plan.tax_rate);
                                return (
                                    <th key={plan.id} className={plan.current ? 'is-current' : ''}>
                                        <div className="plan-col-name">{plan.name}</div>
                                        <div className="plan-col-price">
                                            {plan.tier_level === 0 ? 'No fee' : <>{formatMoney(plan.monthly_fee, plan.currency)}<span>/mo</span></>}
                                        </div>
                                        {plan.tier_level > 0 && (
                                            <div className="plan-col-meta">
                                                {formatMoney(price.gross, plan.currency)} with {Number(plan.tax_rate)}% GST
                                                {Number(plan.bonus_pct) > 0 && <> · +{Number(plan.bonus_pct)}% bonus credit</>}
                                            </div>
                                        )}
                                        <div className="plan-col-action">{action(plan)}</div>
                                    </th>
                                );
                            })}
                        </tr>
                    </thead>
                    <tbody>
                        {Object.entries(groups).map(([group, features]) => (
                            <React.Fragment key={group}>
                                <tr className="plan-group-row"><td colSpan={offer.plans.length + 1}>{group}</td></tr>
                                {features.map(f => (
                                    <tr key={f.key}>
                                        <td>{f.label}</td>
                                        {offer.plans.map(plan => {
                                            const ent = plan.entitlements[f.key];
                                            return (
                                                <td key={plan.id} className={plan.current ? 'is-current' : ''}>
                                                    {f.kind === 'limit'
                                                        ? limitText(ent?.limit)
                                                        : ent?.enabled === false
                                                            ? <Minus size={14} aria-label="Not included" className="muted" />
                                                            : <><Check size={14} aria-label="Included" />{ent?.limit != null && <span className="muted"> up to {ent.limit}</span>}</>}
                                                </td>
                                            );
                                        })}
                                    </tr>
                                ))}
                            </React.Fragment>
                        ))}
                    </tbody>
                </table>
            </div>
            <p className="section-desc">Invoices for every payment are on the <Link to="/billing/invoices">Invoices</Link> page.</p>
        </div>
    );
};

export default PlanPage;
