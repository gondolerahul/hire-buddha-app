"""The report library (Phase 15 T9-4…T9-7; 07 §7).

Every report is a definition (``framework.ReportDef``) and one builder; one
router serves them all (``GET /api/v1/reports``, ``GET /api/v1/reports/{id}``)
in one shape — tiles, a chart, a table, drill-down, export (CSV, XLSX, PDF) —
scoped to the viewer (staff: everything or one company; a partner: its
customers; a business: itself) and in the viewer's money view (customers and
partners never see cost). ``console`` holds R-A01…R-A23, ``partner``
R-P01…R-P10, ``business`` R-T01…R-T14.
"""
