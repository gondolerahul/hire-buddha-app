/** pages/reports/ReportPage — one report (Phase 15 T9-4): `/console/reports/:id`, `/partner/reports/:id`, `/reports/:id`. */
import React from 'react';
import { useParams } from 'react-router-dom';

import { ReportShell } from '@/components/reports/ReportShell';

export const ReportPage: React.FC<{ reportId?: string }> = ({ reportId }) => {
    const params = useParams();
    const id = (reportId ?? params.reportId ?? '').toUpperCase();
    return <ReportShell key={id} reportId={id} />;
};

export default ReportPage;
