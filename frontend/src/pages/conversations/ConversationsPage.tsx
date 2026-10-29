/**
 * pages/settings/ConversationsPage — customers who asked for a person, and WhatsApp opt-ins (META-E4, META-E5).
 *
 * When a customer asks for a person on Messenger, Instagram or WhatsApp, the AI
 * assistant stops answering and the team is told. Someone replies from the
 * Page's inbox or the WhatsApp number, then hands the conversation back here;
 * the assistant's next reply says first that it is an AI.
 *
 * WhatsApp lets the business start a conversation (outside the 24 hours after
 * the customer's last message) only with an approved template, and only to a
 * customer who opted in. Opt-ins are recorded here, or by the customer replying
 * START (and STOP to opt out).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { MessagesSquare } from 'lucide-react';

import { conversations, type Conversation, type OptIn } from '@/services/support.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDateTime } from '@/utils/datetime';

import '@/pages/admin/MoneyConsole.css';

const CHANNEL: Record<Conversation['channel'], string> = { messenger: 'Messenger', instagram: 'Instagram',
                                                            whatsapp: 'WhatsApp' };

export const ConversationsPage: React.FC = () => {
    const [waiting, setWaiting] = useState<Conversation[]>([]);
    const [optIns, setOptIns] = useState<OptIn[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [form, setForm] = useState({ contact: '', status: 'in' as 'in' | 'out', source: '', evidence: '' });

    const load = useCallback(async () => {
        try {
            const [people, opts] = await Promise.all([conversations.list(true), conversations.optIns()]);
            setWaiting(people);
            setOptIns(opts);
        } catch (err) {
            setError(apiErrorMessage(err, 'Conversations could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const handBack = async (id: string) => {
        try {
            await conversations.handBack(id);
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The conversation was not handed back'));
        }
    };

    const record = async () => {
        setError(null);
        try {
            await conversations.recordOptIn(form.contact.trim(), form.status, form.source.trim(),
                                            form.evidence.trim() || undefined);
            setForm({ contact: '', status: 'in', source: '', evidence: '' });
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The opt-in was not recorded'));
        }
    };

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><MessagesSquare size={22} /> Conversations</h1>
                    <p className="page-subtitle">Customers who asked for a person, and who agreed to WhatsApp messages
                        from you.</p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            <section className="money-card glass">
                <h2>Waiting for a person</h2>
                <p className="card-desc">The AI assistant does not answer these customers until you hand the
                    conversation back. Reply from the Page's inbox or your WhatsApp number first.</p>
                {waiting.length === 0 ? <p className="card-desc">Nobody is waiting.</p> : (
                    <table className="money-table">
                        <thead><tr><th>Since</th><th>Where</th><th>Customer</th><th>They wrote</th><th /></tr></thead>
                        <tbody>
                            {waiting.map(c => (
                                <tr key={c.id}>
                                    <td>{c.handed_off_at ? formatDateTime(c.handed_off_at) : ''}</td>
                                    <td>{CHANNEL[c.channel]}</td>
                                    <td><code>{c.contact_id}</code></td>
                                    <td className="muted">{c.handoff_reason}</td>
                                    <td><button className="btn-primary" onClick={() => handBack(c.id)}>
                                        Hand back to the assistant</button></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
            <section className="money-card glass">
                <h2>WhatsApp opt-ins</h2>
                <p className="card-desc">Outside the 24 hours after a customer's last message, WhatsApp allows only an
                    approved template, and only to a customer who agreed to hear from you. Record where the agreement
                    came from.</p>
                <div className="money-form">
                    <label>Number<input value={form.contact} placeholder="+91 98xxxxxxx"
                                        onChange={e => setForm({ ...form, contact: e.target.value })} /></label>
                    <label>Agreed?<select value={form.status}
                                          onChange={e => setForm({ ...form, status: e.target.value as 'in' | 'out' })}>
                        <option value="in">Opted in</option><option value="out">Opted out</option></select></label>
                    <label>Where<input value={form.source} placeholder="website form, checkout, in person"
                                       onChange={e => setForm({ ...form, source: e.target.value })} /></label>
                    <label>What shows it<input value={form.evidence} placeholder="form id, date"
                                               onChange={e => setForm({ ...form, evidence: e.target.value })} /></label>
                    <button className="btn-primary" disabled={form.contact.trim().length < 6 || form.source.trim().length < 2}
                            onClick={record}>Record</button>
                </div>
                {optIns.length === 0 ? <p className="card-desc">None recorded yet.</p> : (
                    <table className="money-table">
                        <thead><tr><th>Number</th><th>Status</th><th>Where</th><th>Recorded</th></tr></thead>
                        <tbody>
                            {optIns.map(o => (
                                <tr key={o.contact}>
                                    <td><code>{o.contact}</code></td>
                                    <td>{o.status === 'in' ? 'opted in' : 'opted out'}</td>
                                    <td className="muted">{o.source}{o.evidence ? ` (${o.evidence})` : ''}</td>
                                    <td>{o.recorded_at ? formatDateTime(o.recorded_at) : ''}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>
        </div>
    );
};

export default ConversationsPage;
