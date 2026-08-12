/**
 * cortex.service.ts — CORTEX Memory Tree API Service
 *
 * Provides typed API calls for the CORTEX memory system endpoints.
 */
import { apiClient } from './api.client';

// --- Types ---

export interface CortexTree {
    id: string;
    entity_id: string;
    task_description: string | null;
    status: 'active' | 'suspended' | 'complete' | 'archived';
    total_nodes: number;
    root_node_id: string | null;
    output_root_id: string | null;
    resume_cursor_id: string | null;
    max_children: number;
    resume_schedule: string | null;
    next_resume_at: string | null;
    created_at: string | null;
    last_active_at: string | null;
}

export interface CortexNodeSummary {
    id: string;
    title: string;
    summary: string | null;
    status: string;
    node_type: string;
    sibling_order: number;
    depth: number;
    content_tokens: number;
}

export interface CortexViewport {
    current_node: CortexNodeSummary;
    children: CortexNodeSummary[];
    parent: CortexNodeSummary | null;
    breadcrumb: { id: string; title: string }[];
}

export interface CortexNodeContent {
    node_id: string;
    title: string;
    content: string;
    page: number;
    total_pages: number;
    content_tokens: number;
}

export interface CortexNodeDetail {
    id: string;
    tree_id: string;
    parent_id: string | null;
    node_type: string;
    title: string;
    summary: string | null;
    content_tokens: number;
    status: string;
    depth: number;
    sibling_order: number;
    source_ref: Record<string, unknown> | null;
    metadata_extra: Record<string, unknown> | null;
    created_at: string | null;
    updated_at: string | null;
}

// --- API Calls ---

export const cortexService = {
    // Tree Management
    async listTrees(entityId?: string, status?: string): Promise<CortexTree[]> {
        const params = new URLSearchParams();
        if (entityId) params.set('entity_id', entityId);
        if (status) params.set('status', status);
        const { data } = await apiClient.get(`/cortex/trees?${params}`);
        return data;
    },

    async getTree(treeId: string): Promise<CortexTree> {
        const { data } = await apiClient.get(`/cortex/trees/${treeId}`);
        return data;
    },

    async createTree(entityId: string, taskDescription: string): Promise<CortexTree> {
        const { data } = await apiClient.post('/cortex/trees', {
            entity_id: entityId,
            task_description: taskDescription,
        });
        return data;
    },

    async resumeTree(treeId: string): Promise<{ tree: CortexTree; viewport: CortexViewport; last_checkpoint: unknown }> {
        const { data } = await apiClient.post(`/cortex/trees/${treeId}/resume`);
        return data;
    },

    async suspendTree(treeId: string): Promise<{ status: string; checkpoint_id: string }> {
        const { data } = await apiClient.post(`/cortex/trees/${treeId}/suspend`);
        return data;
    },

    // Navigation
    async navigate(treeId: string, nodeId: string): Promise<CortexViewport> {
        const { data } = await apiClient.post(`/cortex/trees/${treeId}/navigate/${nodeId}`);
        return data;
    },

    // Content Access
    async readNode(treeId: string, nodeId: string, page = 0): Promise<CortexNodeContent> {
        const { data } = await apiClient.get(`/cortex/trees/${treeId}/nodes/${nodeId}?page=${page}`);
        return data;
    },

    async getNodeDetail(treeId: string, nodeId: string): Promise<CortexNodeDetail> {
        const { data } = await apiClient.get(`/cortex/trees/${treeId}/nodes/${nodeId}/detail`);
        return data;
    },

    async writeNode(treeId: string, parentId: string, nodeType: string, title: string, content?: string, summary?: string): Promise<{ id: string }> {
        const { data } = await apiClient.post(`/cortex/trees/${treeId}/nodes`, {
            parent_id: parentId,
            node_type: nodeType,
            title,
            content,
            summary,
        });
        return data;
    },

    // Document Ingestion (Gap #6)
    async ingestDocument(treeId: string, documentId: string, content: string, filename: string, knowledgeRootId?: string): Promise<{ nodes_created: number }> {
        const { data } = await apiClient.post(`/cortex/trees/${treeId}/ingest`, {
            document_id: documentId,
            content,
            filename,
            knowledge_root_id: knowledgeRootId,
        });
        return data;
    },

    // Checkpointing
    async checkpoint(treeId: string, progressSummary: string, keyFacts: string[] = [], nextSteps: string[] = []): Promise<{ id: string }> {
        const { data } = await apiClient.post(`/cortex/trees/${treeId}/checkpoint`, {
            progress_summary: progressSummary,
            key_facts: keyFacts,
            next_steps: nextSteps,
        });
        return data;
    },

    // Assembly
    async assembleOutput(treeId: string, coherencePass = true): Promise<{ output: string }> {
        const { data } = await apiClient.get(`/cortex/trees/${treeId}/output?coherence_pass=${coherencePass}`);
        return data;
    },
};

