/**
 * components/agent/cortex-helpers — utility extractors for legacy
 * CORTEX UI to opt-in to Phase 11 widgets (Provenance ribbon, etc.).
 */
import type { ProvenanceBlock } from '@/types/agentKernel';

/**
 * Pull a typed Provenance block out of a CORTEX node's source_ref.
 * Returns ``null`` when the node doesn't carry one (legacy nodes
 * written before Phase 11 Track 6).
 */
export function extractProvenance(
    sourceRef: Record<string, unknown> | null | undefined,
): ProvenanceBlock | null {
    if (!sourceRef || typeof sourceRef !== 'object') return null;
    const raw = (sourceRef as Record<string, unknown>).provenance;
    if (!raw || typeof raw !== 'object') return null;
    const obj = raw as Record<string, unknown>;
    if (typeof obj.source_type !== 'string') return null;
    return {
        source_type: obj.source_type as ProvenanceBlock['source_type'],
        tool_id: (obj.tool_id as string | null) ?? null,
        url: (obj.url as string | null) ?? null,
        upload_ref: (obj.upload_ref as string | null) ?? null,
        fetched_at: (obj.fetched_at as string | null) ?? null,
        trust_score: typeof obj.trust_score === 'number'
            ? (obj.trust_score as number)
            : 0.5,
        run_id: (obj.run_id as string | null) ?? null,
        step_id: (obj.step_id as string | null) ?? null,
        notes: (obj.notes as string | null) ?? null,
    };
}

/**
 * Read the Track 6 candidate/confirmed lifecycle status from a CORTEX
 * node's source_ref. Returns ``'confirmed'`` for legacy nodes that
 * predate the candidate→confirmed pipeline.
 */
export function extractRuleStatus(
    sourceRef: Record<string, unknown> | null | undefined,
): 'candidate' | 'confirmed' {
    if (!sourceRef || typeof sourceRef !== 'object') return 'confirmed';
    const status = (sourceRef as Record<string, unknown>).status;
    return status === 'candidate' ? 'candidate' : 'confirmed';
}
