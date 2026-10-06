/**
 * components/agent/RunFiles — the files a run and its child runs produced (FE-32).
 *
 * Both run layouts show them. The agent-loop layout (the default) had no file
 * list and no download, so a run's files appeared only in the older trace
 * view. The files come from the artifact table by `run_id` (EP-21); the page
 * that owns the run fetches them once and passes them in.
 */
import React from 'react';
import { Download, FileText } from 'lucide-react';

import { apiClient } from '@/services/api.client';
import type { Artifact } from '@/services/artifact.service';
import { API_ORIGIN } from '@/config/api';

import './RunFiles.css';

// Authenticated file download — uses apiClient (with auto token-refresh)
// for /api/ routes, falls back to direct fetch for static artifact paths.
export const downloadArtifactFile = async (fileUrl: string, filename?: string) => {
    try {
        let blob: Blob;
        if (fileUrl.startsWith('/api/')) {
            // Use apiClient which has the 401→refresh interceptor
            const response = await apiClient.get(fileUrl.replace(/^\/api\/v1/, ''), {
                responseType: 'blob',
            });
            blob = response.data as Blob;
        } else {
            // Static file path (e.g. /artifact/system-generated/...) — no auth needed,
            // but it is the API's, not the app's, when the two are on different origins
            const response = await fetch(`${API_ORIGIN}${fileUrl}`);
            if (!response.ok) throw new Error('Download failed');
            blob = await response.blob();
        }
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename || 'document';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (err) {
        console.error('Artifact download failed:', err);
    }
};

const _size = (bytes: number | null) => {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

interface Props {
    artifacts: Artifact[];
}

export const RunFiles: React.FC<Props> = ({ artifacts }) => {
    if (artifacts.length === 0) return null;
    return (
        <section className="agentk-run-files" aria-label="Files this run produced">
            <h2 className="agentk-run-files__title">
                Files <span className="agentk-run-files__count">{artifacts.length}</span>
            </h2>
            <ul className="agentk-run-files__list">
                {artifacts.map((artifact) => (
                    <li key={artifact.id} className="agentk-run-files__item">
                        <FileText size={16} aria-hidden />
                        <span className="agentk-run-files__name" title={artifact.purpose ?? undefined}>
                            {artifact.file_name}
                        </span>
                        <span className="agentk-run-files__meta">{_size(artifact.file_size)}</span>
                        <button
                            type="button"
                            className="agentk-run-files__download"
                            onClick={() =>
                                downloadArtifactFile(`/api/v1/artifacts/${artifact.id}/download`, artifact.file_name)
                            }
                            aria-label={`Download ${artifact.file_name}`}
                        >
                            <Download size={14} aria-hidden /> Download
                        </button>
                    </li>
                ))}
            </ul>
        </section>
    );
};
