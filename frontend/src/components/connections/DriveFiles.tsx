/**
 * components/connections/DriveFiles — the Drive files HireBuddha may open (GOOG-E4).
 *
 * The Google Drive connector asks only for `drive.file`: HireBuddha reaches the
 * files a person chooses here, in Google's own Picker, and the files it creates.
 * Choosing adds to the list; Remove takes a file off it (agents can no longer
 * open it; the file stays in Drive).
 */
import React, { useState } from 'react';

import { JellyButton } from '@/components/ui';
import { connectionsService, type DriveFile, type PickerSession } from '@/services/connections.service';
import { problemText } from '@/services/records.service';

const PICKER_SCRIPT = 'https://apis.google.com/js/api.js';

/* The few parts of Google's Picker API this screen uses. */
interface PickerDoc { id: string; name?: string; mimeType?: string }
interface PickerData { action: string; docs?: PickerDoc[] }
interface PickerBuilder {
    addView(view: unknown): PickerBuilder;
    enableFeature(feature: unknown): PickerBuilder;
    setOAuthToken(token: string): PickerBuilder;
    setDeveloperKey(key: string): PickerBuilder;
    setAppId(id: string): PickerBuilder;
    setCallback(callback: (data: PickerData) => void): PickerBuilder;
    build(): { setVisible(visible: boolean): void };
}
interface PickerNamespace {
    PickerBuilder: new () => PickerBuilder;
    DocsView: new (viewId?: unknown) => { setIncludeFolders(on: boolean): unknown };
    ViewId: { DOCS: unknown };
    Feature: { MULTISELECT_ENABLED: unknown };
    Action: { PICKED: string };
}
interface GoogleWindow {
    gapi?: { load(api: string, callback: () => void): void };
    google?: { picker?: PickerNamespace };
}

let loading: Promise<void> | null = null;

/** Google's script, once per page. */
const loadPicker = (): Promise<void> => {
    loading = loading ?? new Promise<void>((resolve, reject) => {
        const script = document.createElement('script');
        script.src = PICKER_SCRIPT;
        script.async = true;
        script.onload = () => (window as unknown as GoogleWindow).gapi?.load('picker', () => resolve());
        script.onerror = () => { loading = null; reject(new Error('Could not load the Google Picker.')); };
        document.head.appendChild(script);
    });
    return loading;
};

const choose = (session: PickerSession): Promise<DriveFile[]> => new Promise((resolve) => {
    const picker = (window as unknown as GoogleWindow).google?.picker;
    if (!picker) { resolve([]); return; }
    const view = new picker.DocsView(picker.ViewId.DOCS);
    view.setIncludeFolders(true);
    new picker.PickerBuilder()
        .addView(view)
        .enableFeature(picker.Feature.MULTISELECT_ENABLED)
        .setOAuthToken(session.access_token)
        .setDeveloperKey(session.developer_key)
        .setAppId(session.app_id)
        .setCallback((data) => {
            if (data.action === picker.Action.PICKED) {
                resolve((data.docs ?? []).map(d => ({ id: d.id, name: d.name ?? null, mime_type: d.mimeType ?? null })));
            } else if (data.action === 'cancel') resolve([]);
        })
        .build()
        .setVisible(true);
});

const filesOf = (value: unknown): DriveFile[] => (Array.isArray(value) ? value as DriveFile[] : []);

export const DriveFiles: React.FC<{
    connectionId: string;
    settings: Record<string, unknown>;
    manager: boolean;
    onSaved: () => void;
}> = ({ connectionId, settings, manager, onSaved }) => {
    const [chosen, setChosen] = useState<DriveFile[]>(filesOf(settings.picked_files));
    const [message, setMessage] = useState<{ kind: 'ok' | 'bad'; text: string } | null>(null);
    const [busy, setBusy] = useState(false);
    const created = filesOf(settings.created_files);

    const save = async (files: DriveFile[], done: string) => {
        const saved = await connectionsService.setFiles(connectionId, files);
        setChosen(saved.files);
        setMessage({ kind: 'ok', text: done });
        onSaved();
    };

    const open = async () => {
        setMessage(null);
        setBusy(true);
        try {
            const session = await connectionsService.picker(connectionId);
            await loadPicker();
            const picked = await choose(session);
            if (picked.length) {
                const known = new Set(chosen.map(f => f.id));
                await save([...chosen, ...picked.filter(f => !known.has(f.id))],
                           `${picked.length} file${picked.length === 1 ? '' : 's'} chosen.`);
            }
        } catch (err) {
            setMessage({ kind: 'bad', text: problemText(err, 'Could not open the Google Picker.') });
        } finally {
            setBusy(false);
        }
    };

    return (
        <section className="ar-section" aria-label="Drive files">
            <h2>Drive files HireBuddha may open</h2>
            <p className="ar-note">Your AI employees can open only the files you choose here and the files they
                create. Nothing else in your Drive is reachable.</p>
            {message && <p className={`ar-note ar-note--${message.kind}`} role="status">{message.text}</p>}
            {chosen.length ? (
                <ul className="ar-decisions">{chosen.map(f => (
                    <li key={f.id}><strong>{f.name || f.id}</strong>{f.mime_type && <span> · {f.mime_type}</span>}
                        {manager && <> · <button type="button" className="ar-link" onClick={() =>
                            save(chosen.filter(x => x.id !== f.id), 'Removed: agents can no longer open it.')
                                .catch(err => setMessage({ kind: 'bad', text: problemText(err, 'Could not remove it.') }))}>
                            Remove</button></>}</li>))}
                </ul>
            ) : <p className="ar-note">No files chosen yet.</p>}
            {created.length > 0 && <p className="ar-note">{created.length} file{created.length === 1 ? '' : 's'} created
                by HireBuddha are reachable too.</p>}
            {manager && <div className="ar-actions">
                <JellyButton size="sm" onClick={open} disabled={busy}>{busy ? 'Opening…' : 'Choose files'}</JellyButton>
            </div>}
        </section>
    );
};

export default DriveFiles;
