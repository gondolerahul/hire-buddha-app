/**
 * pages/settings/TeamPage — the people of one company (Phase 15 T9-8, T9-12; 07 §4.3, §4.6).
 *
 * A business admin manages its users, a partner admin its team; staff see the
 * acting company's. An app_admin also sets an app_user's console functions
 * (support, sales, finance, ops), which decide the console menu and reports.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { Badge, Button, Card, Field, Notice, PageHeader } from '@/components/ui/brand';
import { useAuth } from '@/hooks/useAuth';
import { getActingCompany } from '@/services/actingCompany';
import { userService } from '@/services/user.service';
import { StaffFunction, User, UserRole } from '@/types';
import { apiErrorMessage } from '@/utils/apiError';

const FUNCTIONS: StaffFunction[] = ['support', 'sales', 'finance', 'ops'];
const ROLE_LABEL: Record<string, string> = {
    app_admin: 'Platform admin', app_user: 'Platform staff', partner_admin: 'Partner admin', partner_user: 'Partner user',
    tenant_admin: 'Admin', tenant_user: 'User',
};
/** The roles a viewer adds to the company it manages (the API checks again). */
const ADDABLE: Record<string, UserRole[]> = {
    app_admin: [UserRole.APP_ADMIN, UserRole.APP_USER],
    partner_admin: [UserRole.PARTNER_ADMIN, UserRole.PARTNER_USER],
    tenant_admin: [UserRole.TENANT_ADMIN, UserRole.TENANT_USER],
};
const TENANT_ROLES = [UserRole.TENANT_ADMIN, UserRole.TENANT_USER];

export const TeamPage: React.FC = () => {
    const { user } = useAuth();
    const acting = getActingCompany();
    const companyId = acting?.id ?? user?.company_id;
    const viewerRole = user?.role ?? '';
    const [users, setUsers] = useState<User[]>([]);
    const [form, setForm] = useState({ full_name: '', email: '', password: '', role: '' });
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    // Staff acting in a business add that business's roles.
    const roles = acting ? TENANT_ROLES : ADDABLE[viewerRole] ?? [];
    const manages = roles.length > 0 && (viewerRole !== 'app_user');

    const load = useCallback(async () => {
        try {
            setUsers((await userService.getUsers()).filter(u => u.company_id === companyId));
        } catch (err) {
            setError(apiErrorMessage(err, 'The team could not be loaded'));
        }
    }, [companyId]);

    useEffect(() => { load(); }, [load]);

    const act = async (fn: () => Promise<unknown>, done: string) => {
        setError(null);
        setNotice(null);
        try {
            await fn();
            setNotice(done);
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'The change was not saved'));
        }
    };

    const add = (e: React.FormEvent) => {
        e.preventDefault();
        if (!companyId) return;
        act(() => userService.createUser({ ...form, role: (form.role || roles[roles.length - 1]) as UserRole, company_id: companyId }),
            `${form.email} was added.`).then(() => setForm({ full_name: '', email: '', password: '', role: '' }));
    };

    const toggleFunction = (u: User, fn: StaffFunction) => {
        const current = u.staff_functions ?? [];
        const next = current.includes(fn) ? current.filter(f => f !== fn) : [...current, fn];
        act(() => userService.updateUser(u.id, { staff_functions: next }), `${u.email}: ${next.join(', ') || 'no functions'}.`);
    };

    const sorted = useMemo(() => [...users].sort((a, b) => a.email.localeCompare(b.email)), [users]);

    return (
        <div className="b-page">
            <PageHeader eyebrow={acting ? acting.name : 'Settings'} title="Team"
                        subtitle="Who can sign in, and what they can do. Everyone shares the company's wallet." />
            {error && <Notice tone="negative">{error}</Notice>}
            {notice && <Notice tone="positive">{notice}</Notice>}
            <Card title={`${users.length} people`}>
                <table className="b-table">
                    <thead>
                        <tr><th>Name</th><th>E-mail</th><th>Role</th><th>Status</th>
                            {viewerRole === 'app_admin' && !acting && <th>Console functions</th>}
                            {manages && <th />}</tr>
                    </thead>
                    <tbody>
                        {sorted.map(u => {
                            const self = u.id === user?.id;
                            return (
                                <tr key={u.id}>
                                    <td>{u.full_name}</td>
                                    <td>{u.email}</td>
                                    <td>
                                        {manages && !self && roles.includes(u.role) ? (
                                            <select value={u.role} aria-label={`Role of ${u.email}`}
                                                    onChange={e => act(() => userService.updateUser(u.id, { role: e.target.value as UserRole }),
                                                                       `${u.email} is now ${ROLE_LABEL[e.target.value]}.`)}>
                                                {roles.map(r => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                                            </select>
                                        ) : ROLE_LABEL[u.role] ?? u.role}
                                    </td>
                                    <td><Badge tone={u.is_active ? 'positive' : 'neutral'}>{u.is_active ? 'active' : 'deactivated'}</Badge></td>
                                    {viewerRole === 'app_admin' && !acting && (
                                        <td>
                                            {u.role === UserRole.APP_USER ? FUNCTIONS.map(fn => (
                                                <label key={fn} style={{ marginRight: 8 }}>
                                                    <input type="checkbox" checked={(u.staff_functions ?? []).includes(fn)}
                                                           onChange={() => toggleFunction(u, fn)} /> {fn}
                                                </label>
                                            )) : <span className="b-muted">all</span>}
                                        </td>
                                    )}
                                    {manages && (
                                        <td>
                                            {!self && roles.includes(u.role) && (
                                                <Button size="sm" variant={u.is_active ? 'ghost' : 'secondary'}
                                                        onClick={() => act(() => userService.updateUser(u.id, { is_active: !u.is_active }),
                                                                           `${u.email} was ${u.is_active ? 'deactivated' : 'reactivated'}.`)}>
                                                    {u.is_active ? 'Deactivate' : 'Reactivate'}
                                                </Button>
                                            )}
                                        </td>
                                    )}
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </Card>
            {manages && (
                <Card title="Add a person">
                    <form className="b-row" onSubmit={add}>
                        <Field label="Name"><input type="text" required value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} /></Field>
                        <Field label="E-mail"><input type="email" required value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></Field>
                        <Field label="Temporary password" hint="They change it after signing in">
                            <input type="password" required minLength={8} autoComplete="new-password" value={form.password}
                                   onChange={e => setForm({ ...form, password: e.target.value })} />
                        </Field>
                        <Field label="Role">
                            <select value={form.role || roles[roles.length - 1]} onChange={e => setForm({ ...form, role: e.target.value })}>
                                {roles.map(r => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                            </select>
                        </Field>
                        <Button type="submit" variant="primary">Add</Button>
                    </form>
                </Card>
            )}
        </div>
    );
};

export default TeamPage;
