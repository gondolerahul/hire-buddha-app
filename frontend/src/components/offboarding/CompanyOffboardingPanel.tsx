/**
 * components/offboarding/CompanyOffboardingPanel — closing or deleting one company, for staff
 * (Company 360 → Close or delete; docs/phase15/13 §4, §10).
 *
 * Shows the company's offboarding (its steps, a failed one's error, the certificate), lets an
 * app admin mark it a test business, ask to close it on its behalf, bring erasure forward or retry,
 * and — for a test business, while the switch is on — delete it with its whole workspace now.
 * The delete shows what goes and asks for the exact name and a reason; then it follows the run.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Badge, Button, Card, Field, Notice } from '@/components/ui/brand';
import { apiClient } from '@/services/api.client';
import { CompanyOffboardingView, Offboarding, offboardingService } from '@/services/offboarding.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate, formatDateTime } from '@/utils/datetime';

const DONE = new Set(['erased', 'failed', 'cancelled']);

function tone(state: string): 'positive' | 'warning' | 'negative' | 'neutral' {
    return state === 'erased' ? 'positive' : state === 'failed' ? 'negative' : state === 'cancelled' ? 'neutral' : 'warning';
}

export const OffboardingSteps: React.FC<{ off: Offboarding }> = ({ off }) => (
    <table className="b-table">
        <thead><tr><th>Step</th><th>Outcome</th><th>Attempt</th><th>When</th><th /></tr></thead>
        <tbody>
            {(off.steps ?? []).filter(s => s.outcome !== 'started').map((s, i) => (
                <tr key={`${s.step}-${i}`}>
                    <td>{s.step.replace(/_/g, ' ')}</td>
                    <td><Badge tone={s.outcome === 'failed' ? 'negative' : s.outcome === 'skipped' ? 'neutral' : 'positive'}>{s.outcome}</Badge></td>
                    <td>{s.attempt}</td>
                    <td>{s.at ? formatDateTime(s.at) : '—'}</td>
                    <td className="b-muted">{s.error ?? ''}</td>
                </tr>
            ))}
        </tbody>
    </table>
);

export const CompanyOffboardingPanel: React.FC<{ companyId: string; companyName: string; isAdmin: boolean }> = ({
    companyId, companyName, isAdmin,
}) => {
    const navigate = useNavigate();
    const [view, setView] = useState<CompanyOffboardingView | null>(null);
    const [includeTenants, setIncludeTenants] = useState(false);
    const [confirmName, setConfirmName] = useState('');
    const [reason, setReason] = useState('');
    const [closeReason, setCloseReason] = useState('');
    const [closeExport, setCloseExport] = useState(false);
    const [running, setRunning] = useState<Offboarding | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            setView(await offboardingService.ofCompany(companyId, includeTenants));
        } catch (err) {
            setError(apiErrorMessage(err, 'Not loaded'));
        }
    }, [companyId, includeTenants]);

    useEffect(() => { void load(); }, [load]);

    // Follow a delete or an erasure while it runs.
    useEffect(() => {
        if (!running || DONE.has(running.state)) return;
        const timer = window.setTimeout(async () => {
            try {
                setRunning(await offboardingService.one(running.id));
            } catch {
                // the company row may be gone already; the offboarding record stays
            }
        }, 2000);
        return () => window.clearTimeout(timer);
    }, [running]);

    const act = async (fn: () => Promise<unknown>, done: string) => {
        setError(null);
        setNotice(null);
        try {
            await fn();
            setNotice(done);
            await load();
        } catch (err) {
            setError(apiErrorMessage(err, 'Not done'));
        }
    };

    const deleteNow = async () => {
        setError(null);
        try {
            const out = await offboardingService.deleteNow(companyId, { confirm_name: confirmName, reason,
                                                                        include_test_tenants: includeTenants });
            setRunning(out.offboardings[out.offboardings.length - 1]);
        } catch (err) {
            setError(apiErrorMessage(err, 'Not deleted'));
        }
    };

    const certificate = async (off: Offboarding) => {
        const { data } = await apiClient.get(offboardingService.certificateUrl(off.id), { responseType: 'blob' });
        const url = URL.createObjectURL(data as Blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `erasure-${off.company_ref}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
    };

    if (running) {
        return (
            <Card title={`Deleting ${companyName}`}>
                {running.state === 'erased' ? (
                    <>
                        <Notice tone="positive">Deleted: the business, its people, data, files and workspace are gone ({running.company_ref}).</Notice>
                        <Button onClick={() => void certificate(running)}>Download the certificate</Button>{' '}
                        <Button variant="primary" onClick={() => navigate('/console/companies')}>Back to companies</Button>
                    </>
                ) : running.state === 'failed' ? (
                    <Notice tone="negative">Stopped at {running.last_step ?? 'a step'}: {running.error}. Retry from the Close or delete tab.</Notice>
                ) : (
                    <Notice tone="warning">Deleting… last step done: {running.last_step?.replace(/_/g, ' ') ?? 'starting'}</Notice>
                )}
                <OffboardingSteps off={running} />
            </Card>
        );
    }

    const off = view?.offboarding;
    const check = view?.immediate;
    const rows = check ? Object.values(check.rows).reduce((a, b) => a + b, 0) : 0;
    return (
        <>
            {error && <Notice tone="negative">{error}</Notice>}
            {notice && <Notice tone="positive">{notice}</Notice>}
            {off && off.state !== 'cancelled' && (
                <Card title="Offboarding" actions={<Badge tone={tone(off.state)}>{off.state}</Badge>}>
                    <p>
                        {off.mode === 'immediate' ? 'Immediate delete (test business)' : 'Closure and erasure'}
                        {off.reason ? ` · ${off.reason}` : ''}
                        {off.grace_until && off.state === 'requested' ? ` · erased on ${formatDate(off.grace_until)}` : ''}
                        {!off.confirmed && off.state === 'requested' ? ' · waiting for the business admin to confirm' : ''}
                    </p>
                    {off.error && <Notice tone="negative">{off.error}</Notice>}
                    <OffboardingSteps off={off} />
                    {isAdmin && (
                        <div className="b-row">
                            {off.state === 'failed' && <Button onClick={() => act(() => offboardingService.retry(off.id), 'Retrying.')}>Retry</Button>}
                            {off.state === 'requested' && off.confirmed && (
                                <Button onClick={() => act(() => offboardingService.bringForward(off.id), 'Erasure started.')}>Erase now</Button>
                            )}
                            {off.state === 'requested' && <Button onClick={() => act(() => offboardingService.cancelFor(companyId), 'Closure cancelled.')}>Cancel the closure</Button>}
                            {off.state === 'erased' && <Button onClick={() => void certificate(off)}>Certificate</Button>}
                        </div>
                    )}
                </Card>
            )}
            {isAdmin && (
                <Card title="Test business">
                    <p>{view?.is_test ? 'Marked as a test business: it can be deleted at once.' : 'A real business: it can only be closed through offboarding.'}</p>
                    <Button onClick={() => {
                        const why = window.prompt(view?.is_test ? 'Mark as a real business. Reason:' : 'Mark as a test business (only allowed when no real money moved). Reason:');
                        if (why) void act(() => offboardingService.setTest(companyId, !view?.is_test, why), 'Saved.');
                    }}>{view?.is_test ? 'Mark as a real business' : 'Mark as a test business'}</Button>
                </Card>
            )}
            {isAdmin && (!off || off.state === 'cancelled' || off.state === 'erased') && (
                <Card title="Close this business (on its behalf)">
                    <p className="b-muted">Its admin confirms; after the grace period its data is erased and its books are kept. Remaining credit is not refunded.</p>
                    <Field label="Reason (the business's written request)" grow>
                        <input type="text" value={closeReason} onChange={e => setCloseReason(e.target.value)} />
                    </Field>
                    <label><input type="checkbox" checked={closeExport} onChange={e => setCloseExport(e.target.checked)} /> Prepare an export</label>
                    <div className="b-row">
                        <Button disabled={closeReason.trim().length < 3}
                                onClick={() => act(() => offboardingService.requestFor(companyId, { reason: closeReason, export: closeExport }),
                                                   'Asked: the business admin must confirm.')}>Ask to close</Button>
                    </div>
                </Card>
            )}
            {isAdmin && check && (
                <Card title="Delete now (test business)">
                    {!check.allowed ? (
                        <>
                            <p>Not possible now:</p>
                            <ul>{check.refused.map(r => <li key={r}>{r}</li>)}</ul>
                        </>
                    ) : (
                        <Notice tone="negative">
                            Deletes {companyName} and everything it owns at once, with nothing kept: {rows} rows
                            {check.workspace.database ? `, its database ${check.workspace.database}` : ''}, its files
                            ({check.workspace.storage.join(', ')}), its repositories and its workspace.
                            {check.test_tenants.length > 0 ? ` Also its test businesses: ${check.test_tenants.map(t => t.name).join(', ')}.` : ''}
                            {' '}Backups and soft-deleted copies expire on their own schedule.
                        </Notice>
                    )}
                    <label><input type="checkbox" checked={includeTenants} onChange={e => setIncludeTenants(e.target.checked)} /> Also delete its test businesses (a partner)</label>
                    {check.allowed && (
                        <>
                            <Field label={`Type the name to confirm: ${companyName}`} grow>
                                <input type="text" value={confirmName} onChange={e => setConfirmName(e.target.value)} />
                            </Field>
                            <Field label="Reason" grow>
                                <input type="text" value={reason} onChange={e => setReason(e.target.value)} />
                            </Field>
                            <div className="b-row">
                                <Button variant="danger" disabled={confirmName !== companyName || reason.trim().length < 3}
                                        onClick={() => void deleteNow()}>Delete now</Button>
                            </div>
                        </>
                    )}
                </Card>
            )}
        </>
    );
};

export default CompanyOffboardingPanel;
