/**
 * services/support.service.ts — what the business decides about its customers' data
 * (docs/phase15/14_connector_approvals/10, wave 3).
 *
 * Support access (SH-E6): HireBuddha's staff see what came through the
 * business's connections only under a grant the business gives for a while.
 * Conversations (META-E4, META-E5): customers who asked for a person, handed
 * back to the AI assistant when the team is done; WhatsApp opt-ins.
 */
import { apiClient } from './api.client';

export interface SupportGrant {
    id: string;
    reason: string;
    granted_by: string | null;
    created_at: string | null;
    expires_at: string;
    active: boolean;
    revoked_at: string | null;
}

export interface SupportView {
    at: string;
    staff: string | null;
    run_id: string | null;
    withheld: boolean;
    under_grant: string | null;
}

export interface SupportAccess {
    active: SupportGrant | null;
    grants: SupportGrant[];
    views: SupportView[];
}

export interface Conversation {
    id: string;
    channel: 'messenger' | 'instagram' | 'whatsapp';
    account_id: string;
    contact_id: string;
    with_person: boolean;
    handed_off_at: string | null;
    handoff_reason: string | null;
    handed_back_at: string | null;
    last_inbound_at: string | null;
    last_ai_at: string | null;
}

export interface OptIn {
    contact: string;
    status: 'in' | 'out';
    source: string;
    evidence: string | null;
    recorded_by: string | null;
    recorded_at: string | null;
}

export const supportAccess = {
    async get(): Promise<SupportAccess> {
        return (await apiClient.get('/support-access')).data;
    },
    async give(hours: number, reason: string): Promise<SupportGrant> {
        return (await apiClient.post('/support-access', { hours, reason })).data;
    },
    async end(id: string): Promise<SupportGrant> {
        return (await apiClient.delete(`/support-access/${id}`)).data;
    },
};

export const conversations = {
    async list(withPerson = false): Promise<Conversation[]> {
        return (await apiClient.get('/conversations', { params: { with_person: withPerson } })).data.conversations;
    },
    async handBack(id: string): Promise<Conversation> {
        return (await apiClient.post(`/conversations/${id}/hand-back`)).data;
    },
    async optIns(contact?: string): Promise<OptIn[]> {
        return (await apiClient.get('/whatsapp/opt-ins', { params: contact ? { contact } : {} })).data.opt_ins;
    },
    async recordOptIn(contact: string, status: 'in' | 'out', source: string, evidence?: string): Promise<unknown> {
        return (await apiClient.post('/whatsapp/opt-ins', { contact, status, source, evidence })).data;
    },
};
