// @vitest-environment jsdom
/**
 * RunFiles.test.tsx — the agent-loop run page lists the run's files (FE-32).
 */
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

vi.mock('@/services/api.client', () => ({
    apiClient: { get: vi.fn(async () => ({ data: new Blob(['x']) })) },
}));
vi.mock('@/config/api', () => ({ API_ORIGIN: '', API_BASE_URL: '/api/v1' }));

import { apiClient } from '@/services/api.client';
import type { Artifact } from '@/services/artifact.service';
import { RunFiles } from './RunFiles';

const _file = (id: string, name: string): Artifact => ({
    id, company_id: 'c', campaign_id: null, agent_id: null, run_id: 'r', origin: 'system-generated',
    file_category: 'documents', file_name: name, file_path: `/x/${name}`, file_size: 2048,
    mime_type: 'application/pdf', duration_seconds: null, purpose: 'report', generated_by: 'pdf_generator',
    artifact_metadata: null, created_at: '2026-10-06T00:00:00Z', download_url: `/api/v1/artifacts/${id}/download`,
});

afterEach(cleanup);

describe('RunFiles', () => {
    it('shows nothing when the run produced no file', () => {
        const { container } = render(<RunFiles artifacts={[]} />);
        expect(container.innerHTML).toBe('');
    });

    it('lists each file with a download that goes through the API', () => {
        window.URL.createObjectURL = vi.fn(() => 'blob:x');
        window.URL.revokeObjectURL = vi.fn();
        render(<RunFiles artifacts={[_file('a1', 'report.pdf'), _file('a2', 'chart.png')]} />);
        expect(screen.getByText('report.pdf')).toBeTruthy();
        expect(screen.getByText('chart.png')).toBeTruthy();
        fireEvent.click(screen.getByLabelText('Download report.pdf'));
        expect(apiClient.get).toHaveBeenCalledWith('/artifacts/a1/download', { responseType: 'blob' });
    });
});
