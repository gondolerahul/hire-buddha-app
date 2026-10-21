/**
 * pages/admin/ProviderAppsPanel — HireBuddha's own app with each provider
 * (staff; Phase 14 M1-12, WS5 5.9; docs/how-to/PROVIDER_APP_REGISTRATION_GUIDE.md).
 *
 * Businesses connect their accounts *through* these apps. Each is registered
 * here with its non-secret settings (client id, app id …) and the **names** of
 * its secrets in Key Vault — the values go into Key Vault directly, never
 * through this page. The list says whether each named secret is there.
 */
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { JellyButton } from '@/components/ui';
import { connectionsService, type ProviderAppView } from '@/services/connections.service';
import { problemText } from '@/services/records.service';

const NAMES: Record<string, string> = {
    meta: 'Meta (Facebook, Instagram, WhatsApp)', google: 'Google (Drive, Gmail)', microsoft: 'Microsoft (Outlook)',
    linkedin: 'LinkedIn', x: 'X', github: 'GitHub App',
};
/** Optional settings worth offering per provider (connections/apps.py). */
const OPTIONAL: Record<string, string[]> = {
    meta: ['config_id', 'solution_id', 'graph_version'], microsoft: ['tenant'],
};
const OPTIONAL_REFS: Record<string, string[]> = { meta: ['verify_token'] };

const vaultMark = (present: boolean | null | undefined) =>
    present === true ? '✓ in vault' : present === false ? '✗ not in vault' : '—';

const Editor: React.FC<{ app: ProviderAppView; onSaved: (view: ProviderAppView) => void }> = ({ app, onSaved }) => {
    const settingKeys = Array.from(new Set([...app.required, ...(OPTIONAL[app.provider] ?? []), ...Object.keys(app.settings)]));
    const refKeys = Array.from(new Set([...app.required_refs, ...(OPTIONAL_REFS[app.provider] ?? []), ...Object.keys(app.refs)]));
    const [settings, setSettings] = useState<Record<string, string>>(
        Object.fromEntries(settingKeys.map(k => [k, app.settings[k] ?? ''])));
    const [refs, setRefs] = useState<Record<string, string>>(Object.fromEntries(refKeys.map(k => [k, app.refs[k] ?? ''])));
    const [secret, setSecret] = useState(app.secret ?? `oauth-${app.provider}-client-secret`);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    const save = async () => {
        setBusy(true);
        setError(null);
        try {
            onSaved(await connectionsService.saveOauthApp(app.provider, { settings, refs, secret: secret.trim() || null }));
        } catch (err) {
            setError(problemText(err, 'Could not save.'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="ar-group" aria-label={`${NAMES[app.provider] ?? app.provider} app`}>
            <div className="ar-row">
                {settingKeys.map(key => (
                    <label className="ar-field" key={key}>
                        <span>{key}{app.required.includes(key) ? ' *' : ''}</span>
                        <input className="ar-input ar-mono" aria-label={key} value={settings[key]}
                               onChange={e => setSettings({ ...settings, [key]: e.target.value })} />
                    </label>
                ))}
            </div>
            <div className="ar-row">
                <label className="ar-field">
                    <span>Client secret — its Key Vault name</span>
                    <input className="ar-input ar-mono" aria-label="Client secret vault name" value={secret}
                           onChange={e => setSecret(e.target.value)} />
                </label>
                {refKeys.map(key => (
                    <label className="ar-field" key={key}>
                        <span>{key} — Key Vault name{app.required_refs.includes(key) ? ' *' : ''}</span>
                        <input className="ar-input ar-mono" aria-label={`${key} vault name`} value={refs[key]}
                               onChange={e => setRefs({ ...refs, [key]: e.target.value })} />
                    </label>
                ))}
            </div>
            <p className="ar-note">Only names are saved here. Put each value in the platform Key Vault under that name
                (Azure portal, or <code>az keyvault secret set</code>); it is read when a business connects.</p>
            {error && <p className="ar-note ar-note--bad" role="alert">{error}</p>}
            <div className="ar-actions">
                <JellyButton size="sm" onClick={save} disabled={busy}>{app.registered ? 'Save changes' : 'Register'}</JellyButton>
            </div>
        </div>
    );
};

export const ProviderAppsPanel: React.FC = () => {
    const queryClient = useQueryClient();
    const apps = useQuery({ queryKey: ['admin', 'oauth-apps'], queryFn: connectionsService.oauthApps });
    const [open, setOpen] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);

    if (apps.isError) return <p className="ar-note ar-note--bad">{problemText(apps.error, 'Could not read the apps.')}</p>;
    return (
        <>
            {message && <p className="ar-note" role="status">{message}</p>}
            <table className="ar-table" aria-label="Provider apps">
                <thead><tr><th>Provider</th><th>Registered</th><th>Settings</th><th>Secrets</th><th /></tr></thead>
                <tbody>
                    {(apps.data || []).map(app => (
                        <React.Fragment key={app.provider}>
                            <tr>
                                <td>{NAMES[app.provider] ?? app.provider}</td>
                                <td>{app.registered ? 'Yes' : 'Not yet'}</td>
                                <td className="ar-mono">{Object.entries(app.settings).map(([k, v]) => `${k}=${v}`).join(' · ') || '—'}</td>
                                <td>
                                    {app.registered ? (
                                        <>
                                            <div>client secret: {vaultMark(app.secret_in_vault)}</div>
                                            {Object.keys(app.refs).map(k => <div key={k}>{k}: {vaultMark(app.refs_in_vault[k])}</div>)}
                                        </>
                                    ) : '—'}
                                </td>
                                <td className="ar-row-actions">
                                    <button className="ar-link" onClick={() => setOpen(open === app.provider ? null : app.provider)}>
                                        {app.registered ? 'edit' : 'register'}</button>
                                </td>
                            </tr>
                            {open === app.provider && (
                                <tr><td colSpan={5}>
                                    <Editor app={app} onSaved={view => {
                                        setOpen(null);
                                        setMessage(`${NAMES[view.provider] ?? view.provider}: saved.`);
                                        queryClient.invalidateQueries({ queryKey: ['admin', 'oauth-apps'] });
                                    }} />
                                </td></tr>
                            )}
                        </React.Fragment>
                    ))}
                </tbody>
            </table>
        </>
    );
};

export default ProviderAppsPanel;
