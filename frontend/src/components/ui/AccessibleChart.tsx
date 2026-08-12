/**
 * components/ui/AccessibleChart — a11y-compliant chart wrapper.
 *
 * Wraps any recharts (or arbitrary visual) component with a `<figure>`
 * + `<figcaption>` + `role="img"` + `aria-label` so Lighthouse a11y
 * stays ≥ 90 even when the underlying SVG has no labels of its own
 * (R-FE-9 in the Phase 11 frontend risk register).
 *
 * Usage:
 *   <AccessibleChart
 *     title="Cost by attribution — last 7d"
 *     summary="Bar chart showing $0.42 critic, $0.18 planner, $0.12 tool"
 *     sourceNote="usage_logs grouped by attribution"
 *   >
 *     <ResponsiveContainer>
 *       <BarChart data={data}>…</BarChart>
 *     </ResponsiveContainer>
 *   </AccessibleChart>
 */
import React from 'react';


export interface AccessibleChartProps {
    /** Short visible heading above the chart. */
    title: string;
    /** Screen-reader-facing summary of the chart's content. */
    summary: string;
    /** Optional footer line describing the data source. */
    sourceNote?: string;
    /** Optional CSS class for the wrapping <figure>. */
    className?: string;
    /** Optional fixed height; defaults to the child's intrinsic size. */
    height?: number;
    children: React.ReactNode;
}


export const AccessibleChart: React.FC<AccessibleChartProps> = ({
    title, summary, sourceNote, className, height, children,
}) => (
    <figure
        className={`a11y-chart ${className ?? ''}`}
        role="figure"
        aria-label={`${title}. ${summary}`}
    >
        <figcaption className="a11y-chart__caption">{title}</figcaption>
        <div
            className="a11y-chart__viz"
            role="img"
            aria-label={summary}
            style={height ? { height } : undefined}
        >
            {children}
        </div>
        {sourceNote && (
            <p className="a11y-chart__source">{sourceNote}</p>
        )}
    </figure>
);


export default AccessibleChart;
