/**
 * components/layout/WorkspaceGate — "setting up your workspace" (Phase 14 WS2 2.9, WS8).
 *
 * A new business's own database is made in steps after sign-up. Until it is
 * ready the API answers its pages with 503 `workspace_not_ready`; this shows
 * the steps instead, and the page once they are done. Only in split mode: a
 * single shared database is always ready.
 */
import React from 'react';
import { useQuery } from '@tanstack/react-query';

import { STEP_LABELS, tenancyService } from '@/services/tenancy.service';

export const WorkspaceGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const workspace = useQuery({
        queryKey: ['workspace'],
        queryFn: tenancyService.workspace,
        refetchInterval: query => (query.state.data && !query.state.data.ready ? 3000 : false),
        staleTime: 60_000,
        retry: false,
    });
    const data = workspace.data;
    if (!data || data.ready || data.mode !== 'split') return <>{children}</>;
    const failed = data.steps.some(s => s.outcome === 'failed');
    return (
        <div className="page-container" role="status" aria-label="Setting up your workspace" style={{ maxWidth: 560 }}>
            <h1>Setting up your workspace</h1>
            <p>{failed ? 'A step did not finish. HireBuddha has been told and will try again; you can close this page.'
                : 'Your own database and storage are being prepared. This takes a minute or two.'}</p>
            <ol>
                {data.steps.map(s => (
                    <li key={s.step}>{STEP_LABELS[s.step] ?? s.step} —{' '}
                        <strong>{s.outcome === 'succeeded' || s.outcome === 'skipped' ? 'done'
                            : s.outcome === 'failed' ? 'will be retried' : s.outcome === 'started' ? 'working…' : 'waiting'}</strong>
                    </li>
                ))}
            </ol>
        </div>
    );
};
