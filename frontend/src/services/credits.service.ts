import { apiClient } from './api.client';

/** The wallet's state (Phase 15 §6.3): what new and running work may do. */
export type WalletState = 'ok' | 'in_debt' | 'over_tolerance' | 'suspended';

/** One grant of credit with its own expiry (Phase 15 T4-1). Amounts are exact strings. */
export interface WalletLot {
    id: string;
    kind: 'daily' | 'subscription' | 'subscription_bonus' | 'topup' | 'grant';
    original: string;
    remaining: string;
    granted_at: string | null;
    expires_at: string | null;
    paid: boolean;
}

/**
 * The wallet, in the company's billing currency (Phase 15 M15.2). `available`
 * is what the live lots hold, `held` what running work reserves, `free` what new
 * work can start with, `debt` what is owed. The per-kind numbers are sums of lots.
 */
export interface CreditBalance {
    currency: string;
    state: WalletState;
    account_model: 'pay_as_you_go' | 'subscription';
    available: string;
    held: number;
    free: number;
    debt: string;
    tolerance: string;
    in_debt_since: string | null;
    suspended_at: string | null;
    daily_credits: number;
    daily_expires_at: string | null;
    wallet_balance: number;
    wallet_expires_at: string | null;
    subscription_credits: number;
    subscription_bonus_credits: number;
    sub_credits_expire_at: string | null;
    total_available: number;
    lots: WalletLot[];
}

/** A line of the wallet's ledger (append-only), in its currency. */
export interface LedgerEntry {
    id: string;
    kind: 'grant' | 'deduct' | 'expire' | 'debt_add' | 'debt_repay' | 'adjust' | 'refund' | 'convert';
    amount: string;
    currency: string;
    balance_after: string;
    debt_after: string;
    category: string | null;
    reason: string | null;
    source_type: string | null;
    run_id: string | null;
    created_at: string | null;
}

export interface Subscription {
    id: string;
    plan_tier: number;
    monthly_fee: number;
    bonus_pct: number;
    status: string;
    razorpay_subscription_id: string | null;
    next_billing_date: string | null;
}

export interface TopUpOrder {
    order_id: string;
    amount: string;
    currency: string;
    key_id: string;
}

export interface SubscriptionCheckout {
    razorpay_subscription_id: string;
    amount: number;
    currency: string;
    key_id: string;
    plan_tier: number;
    bonus_credits_pct: number;
    subscription_id: string;
}

/** What the top-up form offers, in the company's currency, and whether this user may pay (Phase 15 T0-3, T4-3). */
export interface TopUpOptions {
    currency: string;
    min: string;
    max: string;
    presets: string[];
    validity_days: number;
    can_pay: boolean;
}

export const creditsService = {
    getBalance: async (): Promise<CreditBalance> => {
        const { data } = await apiClient.get<CreditBalance>('/credits/balance');
        return data;
    },

    getTopUpOptions: async (): Promise<TopUpOptions> => {
        const { data } = await apiClient.get<TopUpOptions>('/credits/topup-options');
        return data;
    },

    initiateTopUp: async (amount: string): Promise<TopUpOrder> => {
        const { data } = await apiClient.post<TopUpOrder>('/credits/topup', { amount });
        return data;
    },

    verifyTopUp: async (payload: {
        razorpay_order_id: string;
        razorpay_payment_id: string;
        razorpay_signature: string;
    }): Promise<{ message: string; currency: string; credits_added: string; new_balance: string; debt: string }> => {
        const { data } = await apiClient.post('/credits/topup/verify', payload);
        return data;
    },

    getLedger: async (limit = 50): Promise<LedgerEntry[]> => {
        const { data } = await apiClient.get<{ entries: LedgerEntry[] }>('/credits/ledger', { params: { limit } });
        return data.entries;
    },

    getSubscription: async (): Promise<{
        subscription: Subscription | null;
        account_model: string;
    }> => {
        const { data } = await apiClient.get('/credits/subscriptions');
        return data;
    },

    createSubscription: async (tierLevel: number): Promise<SubscriptionCheckout> => {
        const { data } = await apiClient.post<SubscriptionCheckout>('/credits/subscriptions', { tier_level: tierLevel });
        return data;
    },

    verifySubscription: async (payload: {
        razorpay_payment_id: string;
        razorpay_subscription_id: string;
        razorpay_signature: string;
    }): Promise<{ message: string; plan_tier: number; monthly_fee: number; bonus_credits_pct: number }> => {
        const { data } = await apiClient.post('/credits/subscriptions/verify', payload);
        return data;
    },

    cancelSubscription: async (id: string): Promise<void> => {
        await apiClient.delete(`/credits/subscriptions/${id}`);
    },

    getSubscriptionTiers: async (): Promise<Array<{
        id: string;
        name: string;
        tier_level: number;
        monthly_fee: number;
        bonus_pct: number;
    }>> => {
        const { data } = await apiClient.get('/credits/subscription-tiers');
        return data;
    },
};
