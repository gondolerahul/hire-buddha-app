/**
 * pages/console/AuditLogPage — every staff change, who made it and why (Phase 15 T9-9; 07 §4.1; report R-A24).
 */
import React from 'react';

import { ReportShell } from '@/components/reports/ReportShell';

export const AuditLogPage: React.FC = () => <ReportShell reportId="R-A24" />;

export default AuditLogPage;
