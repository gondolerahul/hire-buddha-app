import React from 'react';
import { BarChart3 } from 'lucide-react';

export const CHART_COLORS = ['#e8c5a0', '#c9956c', '#9b6fa0', '#6b9bd2', '#4dbe8d', '#e8885a', '#a0c8e8', '#d2b96b'];

export const fmtUSD = (v: number) => `$${v.toFixed(2)}`;
export const fmtPct = (v: number) => `${v.toFixed(1)}%`;

export const StatCard: React.FC<{ label: string; value: string | number; icon: React.ElementType; sub?: string; color?: string }> = ({ label, value, icon: Icon, sub, color }) => (
    <div className="stat-card">
        <div className="stat-card-icon" style={{ color: color || '#e8c5a0', background: color ? `${color}20` : 'rgba(232, 197, 160, 0.1)' }}>
            <Icon size={24} />
        </div>
        <div>
            <p className="stat-label">{label}</p>
            <p className="stat-value" style={{ color: color || '#e8c5a0' }}>{value}</p>
            {sub && <p className="stat-sub">{sub}</p>}
        </div>
    </div>
);

export const SectionTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <h3 className="section-title">{children}</h3>
);

export const EmptyChart: React.FC<{ message?: string }> = ({ message = 'No data available for this period' }) => (
    <div className="chart-empty">
        <BarChart3 size={32} opacity={0.3} />
        <p>{message}</p>
    </div>
);
