/**
 * pages/apps/CodePage — scratch code and company assets (Phase 14 WS8 8.4; functional spec §7.1).
 *
 * Scratch: what agents wrote while working, kept for the business's retention
 * (7 days by default) and never run inside a live app. **Promote to company
 * asset** opens a pull request in one of the business's repositories (built-in
 * or GitHub) with checks; an owner or admin approves it.
 */
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';

import { JellyButton } from '@/components/ui';
import { formatTime } from '@/components/automation/describe';
import { useAuth } from '@/hooks/useAuth';
import { appsService, type CodeItem } from '@/services/apps.service';
import { problemText } from '@/services/records.service';
import { UserRole } from '@/types';

import { LOCAL_TZ } from '../records/RecordsPage';
import { ReviewCard } from './AppDetail';
import '@/components/automation/automation.css';

const MANAGERS = [UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN];

const ItemPanel: React.FC<{ itemId: string; manager: boolean; onClose: () => void }> = ({ itemId, manager, onClose }) => {
    const queryClient = useQueryClient();
    const item = useQuery({ queryKey: ['code', 'item', itemId], queryFn: () => appsService.codeItem(itemId) });
    const repos = useQuery({ queryKey: ['code', 'repos'], queryFn: appsService.repos });
    const [repoId, setRepoId] = useState('');
    const [newRepo, setNewRepo] = useState('');
    const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
    const act = async (action: () => Promise<unknown>, done: string, fallback: string) => {
        setMessage(null);
        try { await action(); setMessage({ kind: 'ok', text: done }); await queryClient.invalidateQueries({ queryKey: ['code'] }); }
        catch (err) { setMessage({ kind: 'error', text: problemText(err, fallback) }); }
    };
    const data = item.data;
    if (!data) return <p className="ar-note">Loading…</p>;
    return (
        <section className="ar-section" aria-label={data.name}>
            <div className="ar-detail__head">
                <h2 style={{ margin: 0 }}>{data.name}</h2>
                <span className="ar-tag">{data.lane}</span><span className="ar-tag">{data.status}</span>
                <button className="ar-link" onClick={onClose}>close</button>
            </div>
            {data.description && <p>{data.description}</p>}
            {data.lane === 'asset' && <p>In the repository at <span className="ar-mono">{data.path}</span>,
                commit <span className="ar-mono">{data.commit_sha?.slice(0, 7)}</span>.</p>}
            {Object.entries(data.contents || {}).map(([path, text]) => (
                <details key={path} open={Object.keys(data.contents || {}).length === 1}>
                    <summary className="ar-mono">{path}</summary><pre className="ar-json">{text}</pre></details>
            ))}
            {data.review && <ul className="ar-attention"><ReviewCard review={data.review} canApprove={manager} act={act} /></ul>}
            {manager && data.lane === 'scratch' && ['active', 'rejected'].includes(data.status) && (
                <div className="ar-group">
                    <legend>Promote to company asset</legend>
                    <div className="ar-row">
                        <label className="ar-field"><span>Repository</span>
                            <select className="ar-input" value={repoId} onChange={e => setRepoId(e.target.value)}>
                                <option value="">—</option>
                                {(repos.data || []).filter(r => !r.moved_to_repo_id).map(r => (
                                    <option key={r.id} value={r.id}>{r.full_name} ({r.provider === 'github' ? 'GitHub' : 'built-in'})</option>
                                ))}
                            </select></label>
                        <label className="ar-field"><span>…or a new built-in repository</span>
                            <input className="ar-input" value={newRepo} placeholder="tools" onChange={e => setNewRepo(e.target.value)} />
                        </label>
                        <JellyButton size="sm" disabled={!repoId && !newRepo.trim()} onClick={() => act(async () => {
                            const target = repoId || (await appsService.createRepo(newRepo.trim())).id;
                            await appsService.promote(data.id, target);
                        }, 'Pull request opened; the checks are running.', 'Could not open the pull request.')}>
                            Open pull request</JellyButton>
                    </div>
                </div>
            )}
            {message && <p className={`ar-note ar-note--${message.kind === 'ok' ? 'ok' : 'bad'}`} role="status">{message.text}</p>}
        </section>
    );
};

export const CodePage: React.FC = () => {
    const { user } = useAuth();
    const manager = MANAGERS.includes(user?.role as UserRole);
    const [params, setParams] = useSearchParams();
    const [lane, setLane] = useState<'scratch' | 'asset'>('scratch');
    const items = useQuery({ queryKey: ['code', 'items', lane], queryFn: () => appsService.codeItems({ lane }) });
    const repos = useQuery({ queryKey: ['code', 'repos'], queryFn: appsService.repos });
    const open = params.get('item');

    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>Code</h1>
                    <p>Scratch is what agents wrote while working: kept a while, never run inside a live app. Company assets
                        are reviewed code in your repositories.</p>
                </div>
                <div className="ar-row"><Link to="/apps" className="ar-link">Apps</Link>
                    <Link to="/settings" className="ar-link">Retention</Link></div>
            </header>
            {open && <ItemPanel itemId={open} manager={manager} onClose={() => setParams({})} />}
            <nav className="ar-tabs" aria-label="Lanes">
                <button className={lane === 'scratch' ? 'ar-tab--on' : ''} onClick={() => setLane('scratch')}>Scratch</button>
                <button className={lane === 'asset' ? 'ar-tab--on' : ''} onClick={() => setLane('asset')}>Company assets</button>
            </nav>
            <table className="ar-table" aria-label="Code items">
                <thead><tr><th>Name</th><th>Kind</th><th>State</th><th>{lane === 'scratch' ? 'Kept until' : 'Where'}</th><th>Made</th></tr></thead>
                <tbody>
                    {(items.data || []).map((item: CodeItem) => (
                        <tr key={item.id} className="ar-clickable" onClick={() => setParams({ item: item.id })}>
                            <td>{item.name}</td><td>{item.kind.replace('_', ' ')}</td><td>{item.status}</td>
                            <td>{lane === 'scratch' ? formatTime(item.retention_until, LOCAL_TZ) : <span className="ar-mono">{item.path}</span>}</td>
                            <td>{formatTime(item.created_at, LOCAL_TZ)}{item.created_by_run_id &&
                                <> · <Link to={`/work/${item.created_by_run_id}`} onClick={e => e.stopPropagation()}>run</Link></>}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            {items.data && !items.data.length && <p className="ar-note">Nothing here.</p>}
            <section className="ar-section" aria-label="Repositories">
                <h2>Repositories</h2>
                <ul className="ar-attention">{(repos.data || []).map(r => (
                    <li key={r.id}><span className="ar-mono">{r.full_name}</span>
                        <span className="ar-tag">{r.provider === 'github' ? 'GitHub' : 'built-in'}</span>
                        {r.moved_to_repo_id && <span className="ar-tag">moved to GitHub</span>}</li>))}</ul>
                {repos.data && !repos.data.length && <p className="ar-note">No repositories yet: apps and promotions make them.</p>}
            </section>
        </div>
    );
};

export default CodePage;
