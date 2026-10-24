/**
 * pages/reports/ReportLibrary — a workspace's report catalogue (Phase 15 T9-4…T9-7; 07 §7).
 *
 * The reports the viewer may open, by group; one the plan does not include is
 * shown locked.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Lock } from 'lucide-react';

import { Card, Notice, PageHeader } from '@/components/ui/brand';
import { ReportListing, reportLibrary } from '@/services/reportLibrary.service';
import { apiErrorMessage } from '@/utils/apiError';

const BASE = { console: '/console/reports', partner: '/partner/reports', business: '/reports' } as const;

export const ReportLibrary: React.FC<{ workspace: keyof typeof BASE }> = ({ workspace }) => {
    const [reports, setReports] = useState<ReportListing[]>([]);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        reportLibrary.catalogue().then(res => setReports(res.reports))
            .catch(err => setError(apiErrorMessage(err, 'Reports could not be loaded')));
    }, []);

    const groups = useMemo(() => {
        const out: Record<string, ReportListing[]> = {};
        for (const r of reports) (out[r.group] ??= []).push(r);
        return out;
    }, [reports]);

    return (
        <div className="b-page">
            <PageHeader eyebrow="Reports" title="Report library"
                        subtitle="Every report has a period, filters, a chart, a table and export to CSV, XLSX and PDF." />
            {error && <Notice tone="negative">{error}</Notice>}
            {Object.entries(groups).map(([group, items]) => (
                <Card key={group} title={group}>
                    <table className="b-table">
                        <tbody>
                            {items.map(r => (
                                <tr key={r.id}>
                                    <td style={{ width: 80 }} className="b-muted">{r.id}</td>
                                    <td>
                                        {r.locked
                                            ? <span title="Not in your plan"><Lock size={12} /> {r.title}</span>
                                            : <Link to={`${BASE[workspace]}/${r.id}`}>{r.title}</Link>}
                                    </td>
                                    <td className="b-muted">{r.description}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </Card>
            ))}
        </div>
    );
};

export default ReportLibrary;
