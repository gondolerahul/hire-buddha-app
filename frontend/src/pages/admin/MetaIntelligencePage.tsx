/**
 * pages/admin/MetaIntelligencePage — Phase 11 Track 5 admin surface.
 *
 * Three tabs:
 *   1. Anti-Patterns          (read MetaIntelligenceTree)
 *   2. Skill Candidates       (read + (future) promote)
 *   3. Prompt-Update queue    (read + HITL approve)
 */
import React, { useEffect, useState } from 'react';

import { metaService } from '@/services/meta.service';
import type {
    AntiPatternRow,
    PromptCandidate,
    SkillCandidate,
} from '@/types/agentKernel';

import './MetaIntelligencePage.css';

type Tab = 'anti' | 'skill' | 'prompt';

export const MetaIntelligencePage: React.FC = () => {
    const [tab, setTab] = useState<Tab>('anti');

    return (
        <div className="page-container meta-intel-page">
            <header className="page-header">
                <h1>Meta Intelligence</h1>
                <p>Anti-patterns, skill candidates, and prompt-update HITL queue.</p>
            </header>

            <nav className="meta-intel-page__tabs">
                <button
                    className={tab === 'anti' ? 'active' : ''}
                    onClick={() => setTab('anti')}
                >
                    Anti-Patterns
                </button>
                <button
                    className={tab === 'skill' ? 'active' : ''}
                    onClick={() => setTab('skill')}
                >
                    Skill Candidates
                </button>
                <button
                    className={tab === 'prompt' ? 'active' : ''}
                    onClick={() => setTab('prompt')}
                >
                    Prompt Updates
                </button>
            </nav>

            <section className="meta-intel-page__body">
                {tab === 'anti' && <AntiPatternsTab />}
                {tab === 'skill' && <SkillCandidatesTab />}
                {tab === 'prompt' && <PromptCandidatesTab />}
            </section>
        </div>
    );
};

// ---------------------------------------------------------------------------

const AntiPatternsTab: React.FC = () => {
    const [rows, setRows] = useState<AntiPatternRow[]>([]);
    const [loading, setLoading] = useState(true);
    useEffect(() => {
        metaService.listAntiPatterns({ topK: 50 })
            .then(setRows)
            .finally(() => setLoading(false));
    }, []);
    if (loading) return <p>loading…</p>;
    if (!rows.length) return <p className="meta-intel-page__empty">no anti-patterns yet</p>;
    return (
        <table className="meta-intel-page__table">
            <thead>
                <tr>
                    <th>title</th>
                    <th>suggestion</th>
                    <th>evidence</th>
                    <th>tags</th>
                    <th>last seen</th>
                </tr>
            </thead>
            <tbody>
                {rows.map((r) => (
                    <tr key={r.node_id ?? r.title}>
                        <td><strong>{r.title}</strong></td>
                        <td>{r.suggestion}</td>
                        <td>{r.evidence_count}</td>
                        <td>{r.related_tags.join(', ') || '—'}</td>
                        <td className="meta-intel-page__ts">{r.last_seen ?? '—'}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
};

const SkillCandidatesTab: React.FC = () => {
    const [rows, setRows] = useState<SkillCandidate[]>([]);
    const [loading, setLoading] = useState(true);
    const [promoting, setPromoting] = useState<Set<string>>(new Set());

    const reload = () => {
        setLoading(true);
        metaService.listSkillCandidates(50)
            .then(setRows)
            .finally(() => setLoading(false));
    };

    useEffect(() => {
        reload();
    }, []);

    const onPromote = async (id: string) => {
        setPromoting((s) => new Set(s).add(id));
        try {
            const result = await metaService.promoteSkillCandidate(id);
            // eslint-disable-next-line no-alert
            alert(`Promoted to SKILL entity ${result.name} (${result.entity_id.slice(0, 8)}) — status ${result.status}`);
            reload();
        } catch (e) {
            // eslint-disable-next-line no-alert
            alert(`promote failed: ${e}`);
        } finally {
            setPromoting((s) => {
                const next = new Set(s);
                next.delete(id);
                return next;
            });
        }
    };

    if (loading) return <p>loading…</p>;
    if (!rows.length) return <p className="meta-intel-page__empty">no skill candidates yet</p>;
    return (
        <table className="meta-intel-page__table">
            <thead>
                <tr>
                    <th>chain</th>
                    <th>frequency</th>
                    <th>source entity</th>
                    <th>created</th>
                    <th>action</th>
                </tr>
            </thead>
            <tbody>
                {rows.map((r) => {
                    const isPromoted = Boolean(r.metadata.promoted);
                    return (
                        <tr key={r.node_id} className={isPromoted ? 'meta-intel-page__row--promoted' : ''}>
                            <td>
                                <code className="meta-intel-page__chain">
                                    {(r.content.chain ?? []).join(' → ')}
                                </code>
                            </td>
                            <td>{r.metadata.frequency ?? r.content.frequency ?? '—'}</td>
                            <td className="meta-intel-page__id">
                                {(r.metadata.source_entity_id as string ?? r.content.source_entity_id ?? '—').slice(0, 12)}
                            </td>
                            <td className="meta-intel-page__ts">{r.created_at?.slice(0, 16) ?? '—'}</td>
                            <td>
                                {isPromoted ? (
                                    <span className="meta-intel-page__badge">promoted</span>
                                ) : (
                                    <button
                                        onClick={() => onPromote(r.node_id)}
                                        disabled={promoting.has(r.node_id)}
                                    >
                                        {promoting.has(r.node_id) ? 'promoting…' : 'promote → SKILL'}
                                    </button>
                                )}
                            </td>
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );
};

const PromptCandidatesTab: React.FC = () => {
    const [rows, setRows] = useState<PromptCandidate[]>([]);
    const [loading, setLoading] = useState(true);
    const [approving, setApproving] = useState<Set<string>>(new Set());

    const reload = () => {
        setLoading(true);
        metaService
            .listPromptCandidates({ onlyPending: true, limit: 50 })
            .then(setRows)
            .finally(() => setLoading(false));
    };

    useEffect(() => {
        reload();
    }, []);

    const onApprove = async (id: string) => {
        setApproving((s) => new Set(s).add(id));
        try {
            await metaService.approvePromptCandidate(id);
            reload();
        } catch (e) {
            // eslint-disable-next-line no-alert
            alert(`approve failed: ${e}`);
        } finally {
            setApproving((s) => {
                const next = new Set(s);
                next.delete(id);
                return next;
            });
        }
    };

    if (loading) return <p>loading…</p>;
    if (!rows.length)
        return <p className="meta-intel-page__empty">no pending prompt candidates</p>;
    return (
        <div className="meta-intel-page__list">
            {rows.map((r) => (
                <article key={r.node_id} className="meta-intel-page__prompt-card">
                    <header>
                        <strong>{r.title}</strong>
                        <span className="meta-intel-page__ts">{r.created_at?.slice(0, 16)}</span>
                    </header>
                    <p>{r.content.rationale ?? r.summary}</p>
                    {r.content.evidence_run_ids?.length ? (
                        <div className="meta-intel-page__evidence">
                            evidence runs:{' '}
                            {r.content.evidence_run_ids.slice(0, 5).map((id) => (
                                <code key={id}>{id.slice(0, 8)}</code>
                            ))}
                        </div>
                    ) : null}
                    {r.content.prompt_diff ? (
                        <pre className="meta-intel-page__diff">{r.content.prompt_diff}</pre>
                    ) : (
                        <p className="meta-intel-page__pending">
                            (prompt diff not yet computed by the LLM critic-of-critic — Phase 12)
                        </p>
                    )}
                    <button
                        onClick={() => onApprove(r.node_id)}
                        disabled={approving.has(r.node_id)}
                    >
                        {approving.has(r.node_id) ? 'approving…' : 'approve'}
                    </button>
                </article>
            ))}
        </div>
    );
};

export default MetaIntelligencePage;
