/**
 * pages/apps/AppsPage — the business's apps (Phase 14 WS8 8.4; functional spec §7.2, §7.5).
 *
 * Every app with its state and address, and **New app** from a template on
 * one technology set (D48): static website, website with forms, mobile app
 * backend, mobile app, CRM / admin tool. A CRM or a backend works with the
 * business's own tables; a form creates records of one table.
 */
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';

import { JellyButton } from '@/components/ui';
import { useAuth } from '@/hooks/useAuth';
import { APP_STATUS_LABEL, appsService, suggestAppName, type AppTemplate } from '@/services/apps.service';
import { problemText, recordsService } from '@/services/records.service';
import { UserRole } from '@/types';

import '@/components/automation/automation.css';

const MANAGERS = [UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN];

export const statusTone = (status: string): string =>
    ({ published: 'active', ready: 'active', building: 'paused', draft: 'paused', stopped: 'paused',
       failed: 'dead' } as Record<string, string>)[status] ?? '';

const NewApp: React.FC<{ templates: AppTemplate[]; onCancel: () => void }> = ({ templates, onCancel }) => {
    const navigate = useNavigate();
    const schema = useQuery({ queryKey: ['records', 'schema'], queryFn: recordsService.schema });
    const tables = Object.entries(schema.data?.objects || {});
    const [template, setTemplate] = useState<AppTemplate>(templates[0]);
    const [displayName, setDisplayName] = useState('');
    const [name, setName] = useState('');
    const [objects, setObjects] = useState<string[]>([]);
    const [formObject, setFormObject] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const appName = name || suggestAppName(displayName);

    const create = async () => {
        setBusy(true);
        setError(null);
        try {
            const params = template.params.form_object !== undefined ? { form_object: formObject || template.params.form_object }
                : undefined;
            const app = await appsService.create({ name: appName, display_name: displayName, template: template.id,
                                                    objects: template.uses_blueprint ? objects : [], params });
            navigate(`/apps/${app.id}`);
        } catch (err) {
            setError(problemText(err, 'Could not create the app.'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <section className="ar-section" aria-label="New app">
            <h2>New app</h2>
            <div className="ar-kinds" role="radiogroup" aria-label="Template">
                {templates.map(t => (
                    <label key={t.id} className={`ar-kind ${t.id === template.id ? 'ar-kind--on' : ''}`} title={t.description}>
                        <input type="radio" checked={t.id === template.id} onChange={() => setTemplate(t)} />
                        <span>{t.name}<br /><small>{t.stack}</small></span>
                    </label>
                ))}
            </div>
            <p className="ar-note">{template.description}</p>
            <div className="ar-row">
                <label className="ar-field"><span>Name</span>
                    <input className="ar-input" value={displayName} onChange={e => setDisplayName(e.target.value)}
                           placeholder="Sales CRM" /></label>
                <label className="ar-field"><span>Web name (part of its address)</span>
                    <input className="ar-input" value={appName} onChange={e => setName(e.target.value)} placeholder="crm" />
                </label>
            </div>
            {template.uses_blueprint && (
                <fieldset className="ar-group">
                    <legend>Tables it works with</legend>
                    {tables.map(([table, spec]) => (
                        <label key={table} className="ar-check ar-check--small">
                            <input type="checkbox" checked={objects.includes(table)} onChange={() => setObjects(
                                objects.includes(table) ? objects.filter(o => o !== table) : [...objects, table])} />
                            <span>{spec.plural}</span>
                        </label>
                    ))}
                </fieldset>
            )}
            {template.params.form_object !== undefined && (
                <label className="ar-field"><span>The form creates records in</span>
                    <select className="ar-input" value={formObject || template.params.form_object}
                            onChange={e => setFormObject(e.target.value)}>
                        {tables.map(([table, spec]) => <option key={table} value={table}>{spec.plural}</option>)}
                    </select>
                    <small>Forms need <Link to="/records/keys">public API access</Link> turned on.</small>
                </label>
            )}
            {!template.deployable && <p className="ar-note">Built and published to the app stores outside HireBuddha.</p>}
            {error && <p className="ar-note ar-note--bad" role="alert">{error}</p>}
            <div className="ar-actions">
                <JellyButton variant="ghost" size="sm" onClick={onCancel}>Cancel</JellyButton>
                <JellyButton size="sm" disabled={busy || !displayName.trim() || !appName
                    || (template.uses_blueprint && !objects.length)} onClick={create}>
                    {busy ? 'Creating…' : 'Create'}</JellyButton>
            </div>
        </section>
    );
};

export const AppsPage: React.FC = () => {
    const { user } = useAuth();
    const manager = MANAGERS.includes(user?.role as UserRole);
    const queryClient = useQueryClient();
    const apps = useQuery({ queryKey: ['apps', 'list'], queryFn: appsService.list, refetchInterval: 20_000 });
    const templates = useQuery({ queryKey: ['apps', 'templates'], queryFn: appsService.templates });
    const reviews = useQuery({ queryKey: ['apps', 'reviews', 'open'], queryFn: () => appsService.reviews({ status: 'open' }) });
    const [creating, setCreating] = useState(false);

    return (
        <div className="page-container ar-page">
            <header className="ar-header">
                <div>
                    <h1>Apps</h1>
                    <p>Websites, CRMs and backends for your customers and staff, built on your records.</p>
                </div>
                <div className="ar-row">
                    <Link to="/code" className="ar-link">Code</Link>
                    {manager && <JellyButton size="sm" onClick={() => setCreating(true)}>+ New app</JellyButton>}
                </div>
            </header>
            {apps.isError && <p className="ar-note ar-note--bad">{problemText(apps.error, 'Apps are not available yet.')}</p>}
            {creating && templates.data && <NewApp templates={templates.data} onCancel={() => {
                setCreating(false); queryClient.invalidateQueries({ queryKey: ['apps'] }); }} />}
            {(reviews.data || []).length > 0 && (
                <section className="ar-section" aria-label="Waiting for review">
                    <h2>Waiting for review</h2>
                    <ul className="ar-attention">
                        {reviews.data!.map(r => (
                            <li key={r.id}>#{r.number} {r.title} — checks {r.checks_status}
                                {r.app_id ? <Link to={`/apps/${r.app_id}?tab=code`}>Open</Link>
                                    : r.code_item_id && <Link to={`/code?item=${r.code_item_id}`}>Open</Link>}</li>
                        ))}
                    </ul>
                </section>
            )}
            <table className="ar-table" aria-label="Apps">
                <thead><tr><th>App</th><th>Template</th><th>State</th><th>Address</th></tr></thead>
                <tbody>
                    {(apps.data || []).map(app => (
                        <tr key={app.id}>
                            <td><Link to={`/apps/${app.id}`}>{app.display_name}</Link> <span className="ar-mono">{app.name}</span></td>
                            <td>{templates.data?.find(t => t.id === app.template)?.name ?? app.template}</td>
                            <td><span className={`ar-pill ar-pill--${statusTone(app.status)}`}>{APP_STATUS_LABEL[app.status]}</span></td>
                            <td>{app.url ? <a href={app.url} target="_blank" rel="noreferrer">{app.hostname || app.url}</a> : '—'}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            {apps.data && !apps.data.length && <p className="ar-note">No apps yet.</p>}
        </div>
    );
};

export default AppsPage;
