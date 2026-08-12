import { apiClient } from './api.client';

export interface CreditBalance {
    account_model: 'pay_as_you_go' | 'subscription';
    daily_credits: number;
    daily_expires_at: string | null;
    wallet_balance: number;
    wallet_expires_at: string | null;
    subscription_credits: number;
    subscription_bonus_credits: number;
    sub_credits_expire_at: string | null;
    total_available: number;
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
    amount: number;
    currency: string;
    key_id: string;
}

export interface SubscriptionOrder {
    order_id: string;
    amount: number;
    currency: string;
    key_id: string;
    plan_tier: number;
    bonus_credits_pct: number;
    subscription_id: string;
}

export const creditsService = {
    getBalance: async (): Promise<CreditBalance> => {
        const { data } = await apiClient.get<CreditBalance>('/credits/balance');
        return data;
    },

    initiateTopUp: async (amount: number): Promise<TopUpOrder> => {
        const { data } = await apiClient.post<TopUpOrder>('/credits/topup', { amount });
        return data;
    },

    verifyTopUp: async (payload: {
        razorpay_order_id: string;
        razorpay_payment_id: string;
        razorpay_signature: string;
        amount: number;
    }): Promise<{ message: string; credits_added: number; new_balance: number }> => {
        const { data } = await apiClient.post('/credits/topup/verify', payload);
        return data;
    },

    getSubscription: async (): Promise<{
        subscription: Subscription | null;
        account_model: string;
    }> => {
        const { data } = await apiClient.get('/credits/subscriptions');
        return data;
    },

    createSubscription: async (payload: {
        plan_tier: number;
        monthly_fee: number;
    }): Promise<SubscriptionOrder> => {
        const { data } = await apiClient.post<SubscriptionOrder>('/credits/subscriptions', payload);
        return data;
    },

    verifySubscription: async (payload: {
        razorpay_order_id: string;
        razorpay_payment_id: string;
        razorpay_signature: string;
        subscription_id: string;
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
