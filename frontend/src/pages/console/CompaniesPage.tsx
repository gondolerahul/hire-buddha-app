/**
 * pages/console/CompaniesPage — every company on the platform (Phase 15 T9-9; 07 §4.1 Directory).
 *
 * Search and filter by type and status; a row opens the company's 360 view.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { CreateCompanyModal } from '@/components/CreateCompanyModal';
import { Badge, Button, Card, Field, Notice, PageHeader } from '@/components/ui/brand';
import { useAuth } from '@/hooks/useAuth';
import { companyService } from '@/services/company.service';
import { Company } from '@/types';
import { apiErrorMessage } from '@/utils/apiError';
import { formatDate } from '@/utils/datetime';

const TYPE_LABEL: Record<Company['type'], string> = { APP: 'Platform', PARTNER: 'Partner', TENANT: 'Business' };

export const CompaniesPage: React.FC = () => {
    const [companies, setCompanies] = useState<Company[]>([]);
    const [q, setQ] = useState('');
    const [type, setType] = useState('');
    const [status, setStatus] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [adding, setAdding] = useState(false);
    const { user } = useAuth();
    const admin = user?.role === 'app_admin';

    const load = () => companyService.list().then(setCompanies)
        .catch(err => setError(apiErrorMessage(err, 'Companies could not be loaded')));
    useEffect(() => { void load(); }, []);

    const byId = useMemo(() => new Map(companies.map(c => [c.id, c.name])), [companies]);
    const shown = useMemo(() => companies.filter(c =>
        (!q || c.name.toLowerCase().includes(q.toLowerCase()) || c.id.startsWith(q))
        && (!type || c.type === type) && (!status || c.status === status)), [companies, q, type, status]);

    return (
        <div className="b-page">
            <PageHeader eyebrow="Directory" title="Companies"
                        subtitle={`${companies.filter(c => c.type === 'TENANT').length} businesses and ${companies.filter(c => c.type === 'PARTNER').length} partners.`}
                        actions={admin && <Button variant="primary" onClick={() => setAdding(true)}>Add a business</Button>} />
            <CreateCompanyModal isOpen={adding} onClose={() => setAdding(false)} type="TENANT" allowTest={admin}
                                onSubmit={async (_id, data) => { await companyService.createCompany(data); await load(); }} />
            {error && <Notice tone="negative">{error}</Notice>}
            <div className="b-row" style={{ marginBottom: 16 }}>
                <Field label="Search" grow><input type="search" value={q} placeholder="Name or id" onChange={e => setQ(e.target.value)} /></Field>
                <Field label="Type">
                    <select value={type} onChange={e => setType(e.target.value)}>
                        <option value="">All</option>
                        {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                </Field>
                <Field label="Status">
                    <select value={status} onChange={e => setStatus(e.target.value)}>
                        <option value="">All</option><option value="active">Active</option><option value="suspended">Suspended</option>
                        <option value="offboarding_requested">Closing</option><option value="erased">Erased</option>
                    </select>
                </Field>
            </div>
            <Card>
                <table className="b-table">
                    <thead><tr><th>Company</th><th>Type</th><th>Under</th><th>Country</th><th>Currency</th><th>Status</th><th>Since</th></tr></thead>
                    <tbody>
                        {shown.map(c => (
                            <tr key={c.id}>
                                <td><Link to={`/console/companies/${c.id}`}>{c.name}</Link>{c.is_test && <> <Badge tone="accent">test</Badge></>}</td>
                                <td>{TYPE_LABEL[c.type]}</td>
                                <td className="b-muted">{c.parent_id ? byId.get(c.parent_id) ?? '—' : '—'}</td>
                                <td>{c.country_code ?? '—'}</td>
                                <td>{c.billing_currency ?? '—'}</td>
                                <td><Badge tone={c.status === 'active' ? 'positive' : 'negative'}>{c.status}</Badge></td>
                                <td className="b-muted">{c.created_at ? formatDate(c.created_at) : '—'}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {shown.length === 0 && <p className="b-muted">No company matches.</p>}
            </Card>
        </div>
    );
};

export default CompaniesPage;
