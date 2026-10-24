/** services/reports.service — the report library (Phase 15 T9-4; 07 §7.4). */
import { apiClient } from './api.client';

export interface ReportTile { label: string; value: string | number | null; kind: 'number' | 'money' | 'percent' | 'text'; hint?: string | null; tone?: string }
export interface ReportColumn { key: string; label: string; kind: 'text' | 'money' | 'number' | 'percent' | 'date' | 'link' }
export interface ReportChart { type: 'bar' | 'stacked' | 'line' | 'pie'; x: string; series: Array<{ key: string; label: string }>; data: Array<Record<string, any>> }

export interface ReportData {
    id: string;
    title: string;
    description: string;
    currency: string;
    as_of: string;
    period: { from: string; to: string } | null;
    filters: Array<{ key: string; label: string; kind: string; choices: string[] }>;
    tiles: ReportTile[];
    chart: ReportChart | null;
    columns: ReportColumn[];
    rows: Array<Record<string, any>>;
    drill: Record<string, string> | null;
    notes: string[];
}

export interface ReportListing { id: string; title: string; description: string; group: string; locked: boolean }

export interface ReportQuery { period?: string; from?: string; to?: string; company_id?: string; [filter: string]: string | undefined }

const clean = (q: ReportQuery) => Object.fromEntries(Object.entries(q).filter(([, v]) => v));

export const reportLibrary = {
    catalogue: async (): Promise<{ workspace: string; reports: ReportListing[] }> => (await apiClient.get('/reports')).data,
    run: async (id: string, query: ReportQuery): Promise<ReportData> =>
        (await apiClient.get<ReportData>(`/reports/${id}`, { params: clean(query) })).data,
    download: async (id: string, query: ReportQuery, format: 'csv' | 'xlsx' | 'pdf'): Promise<void> => {
        const { data } = await apiClient.get(`/reports/${id}`, { params: { ...clean(query), format }, responseType: 'blob' });
        const url = URL.createObjectURL(data as Blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${id}.${format}`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
    },
};
