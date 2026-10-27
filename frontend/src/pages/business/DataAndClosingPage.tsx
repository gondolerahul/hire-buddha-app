/**
 * pages/business/DataAndClosingPage — a business's own data requests and closing it
 * (Settings → Data & closing; docs/phase15/13 §5, §6.6, §7).
 *
 * *Data requests*: a person (a contact, a caller) asks to be erased — find every record that
 * holds their e-mail or phone, then erase them. *Close this business*: ask (or confirm what
 * HireBuddha or the partner asked), see when the data goes, cancel within the grace period,
 * download the export. Credit left is not refunded (D-2), and the page says so with the amount.
 */
import React, { useCallback, useEffect, useState } from 'react';

import { Badge, Button, Card, Field, Notice, PageHeader } from '@/components/ui/brand';
import { Offboarding, offboardingService, PersonMatch } from '@/services/offboarding.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';

export const DataAndClosingPage: React.FC = () => {
    const [off, setOff] = useState<Offboarding | null>(null);
    const [credit, setCredit] = useState<{ available: string; currency: string } | null>(null);
    const [graceDays, setGraceDays] = useState(30);
    const [reason, setReason] = useState('');
    const [wantExport, setWantExport] = useState(true);
    const [query, setQuery] = useState('');
    const [matches, setMatches] = useState<PersonMatch[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const mine = await offboardingService.mine();
            setOff(mine.offboarding);
            setCredit(mine.remaining_credit);
            setGraceDays(mine.grace_days);
        } catch (err) {
            setError(apiErrorMessage(err, 'Not loaded'));
        }
    }, []);
    useEffect(() => { void load(); }, [load]);

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

    const download = async () => {
        const link = await offboardingService.exportLink();
        if (link.url) window.location.href = link.url;
    };

    const closing = off && ['requested', 'exporting', 'erasing', 'failed'].includes(off.state);
    const creditText = credit ? formatMoney(Number(credit.available || 0), credit.currency || 'INR') : '—';
    return (
        <div className="b-page">
            <PageHeader eyebrow="Settings" title="Data & closing"
                        subtitle="Erase a person who asked you to, or close this business and erase its data." />
            {error && <Notice tone="negative">{error}</Notice>}
            {notice && <Notice tone="positive">{notice}</Notice>}

            <Card title="Data requests">
                <p className="b-muted">Someone asked you to erase their data. Search by their e-mail address or phone number, review what holds it, then erase.</p>
                <div className="b-row">
                    <Field label="E-mail or phone" grow>
                        <input type="text" value={query} onChange={e => { setQuery(e.target.value); setMatches(null); }} />
                    </Field>
                    <Button onClick={() => act(async () => setMatches((await offboardingService.findPerson(query)).matches),
                                               'Search done.')} disabled={query.trim().length < 3}>Find</Button>
                </div>
                {matches && (
                    matches.length === 0 ? <p>Nothing holds it.</p> : (
                        <>
                            <table className="b-table">
                                <thead><tr><th>Where</th><th>What happens</th></tr></thead>
                                <tbody>
                                    {Object.entries(matches.reduce<Record<string, PersonMatch[]>>((acc, m) => {
                                        (acc[m.table] = acc[m.table] ?? []).push(m);
                                        return acc;
                                    }, {})).map(([table, rows]) => (
                                        <tr key={table}><td>{table.replace(/_/g, ' ')} ({rows.length})</td>
                                            <td>{rows[0].action === 'delete' ? 'deleted' : 'the value replaced by [erased]'}</td></tr>
                                    ))}
                                </tbody>
                            </table>
                            <Button variant="danger" onClick={() => {
                                if (window.confirm(`Erase ${query} from ${matches.length} records? This cannot be undone.`)) {
                                    void act(async () => { await offboardingService.erasePerson(query); setMatches(null); }, 'Erased.');
                                }
                            }}>Erase this person</Button>
                        </>
                    )
                )}
            </Card>

            <Card title="Close this business" actions={off && closing ? <Badge tone="warning">{off.state.replace('_', ' ')}</Badge> : undefined}>
                {closing && off ? (
                    <>
                        {off.state === 'requested' && !off.confirmed ? (
                            <>
                                <Notice tone="warning">Closing this business was requested ({off.reason}). Nothing happens unless you confirm.</Notice>
                                <div className="b-row">
                                    <Button variant="danger" onClick={() => act(offboardingService.confirm, 'Confirmed.')}>Confirm the closure</Button>
                                    <Button onClick={() => act(offboardingService.cancel, 'Kept open.')}>Keep it open</Button>
                                </div>
                            </>
                        ) : off.state === 'requested' ? (
                            <>
                                <Notice tone="warning">
                                    This business is read-only and its data is erased on {off.grace_until ? formatDate(off.grace_until) : '—'}.
                                    Its invoices are kept as the law requires. Credit left ({creditText}) is not refunded.
                                </Notice>
                                <Button onClick={() => act(offboardingService.cancel, 'Closure cancelled: the business is open again.')}>Cancel the closure</Button>
                            </>
                        ) : (
                            <Notice tone="warning">Erasing the data now.</Notice>
                        )}
                        {off.export_requested && (
                            off.export_ready
                                ? <p><Button onClick={() => void download()}>Download the export</Button> (until {off.export_expires_at ? formatDate(off.export_expires_at) : '—'})</p>
                                : <p className="b-muted">The export is prepared when the grace period ends.</p>
                        )}
                    </>
                ) : (
                    <>
                        <p>
                            Closing stops all work at once and makes the business read-only. After {graceDays} days its data —
                            people, agents, records, files, calls, its workspace — is erased; its invoices and payments are kept for
                            tax as the law requires. You can cancel until then. <strong>Credit left ({creditText}) is not refunded.</strong>
                        </p>
                        <Field label="Why are you closing?" grow>
                            <input type="text" value={reason} onChange={e => setReason(e.target.value)} />
                        </Field>
                        <label><input type="checkbox" checked={wantExport} onChange={e => setWantExport(e.target.checked)} /> Prepare an export of our data to download</label>
                        <div className="b-row">
                            <Button variant="danger" disabled={reason.trim().length < 3} onClick={() => {
                                if (window.confirm(`Close this business? Its data is erased in ${graceDays} days.`)) {
                                    void act(() => offboardingService.request({ reason, export: wantExport }), 'Closing: you can cancel until the date shown.');
                                }
                            }}>Close this business</Button>
                        </div>
                    </>
                )}
            </Card>
        </div>
    );
};

export default DataAndClosingPage;
