/**
 * components/ui/brand — the design system's core components for the web app (Phase 15 T9-2; 07 §2.8).
 *
 * Button, Badge, Card, Field (label + input/select), Tile (a KPI), Tabs and
 * Notice — styled only with the brand tokens (styles/brand.css). New pages use
 * these instead of per-page glass styles.
 */
import React from 'react';

import './brand.css';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

export const Button: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: 'sm' | 'md' }> = (
    { variant = 'secondary', size = 'md', className = '', ...rest }) => (
    <button className={`b-btn b-btn-${variant} b-btn-${size} ${className}`} {...rest} />
);

export type Tone = 'neutral' | 'positive' | 'warning' | 'negative' | 'accent';

export const Badge: React.FC<{ tone?: Tone; children: React.ReactNode; title?: string }> = ({ tone = 'neutral', children, title }) => (
    <span className={`b-badge b-badge-${tone}`} title={title}>{children}</span>
);

export const Card: React.FC<{ title?: React.ReactNode; eyebrow?: string; actions?: React.ReactNode; children?: React.ReactNode; className?: string }> = (
    { title, eyebrow, actions, children, className = '' }) => (
    <section className={`b-card ${className}`}>
        {(title || actions || eyebrow) && (
            <header className="b-card-head">
                <div>
                    {eyebrow && <p className="eyebrow">{eyebrow}</p>}
                    {title && <h2 className="b-card-title">{title}</h2>}
                </div>
                {actions && <div className="b-card-actions">{actions}</div>}
            </header>
        )}
        {children}
    </section>
);

export const Field: React.FC<{ label: string; hint?: string; children: React.ReactNode; grow?: boolean }> = ({ label, hint, children, grow }) => (
    <label className={`b-field ${grow ? 'b-grow' : ''}`}>
        <span className="b-field-label">{label}</span>
        {children}
        {hint && <span className="b-field-hint">{hint}</span>}
    </label>
);

export const Tile: React.FC<{ label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: Tone; onClick?: () => void }> = (
    { label, value, hint, tone = 'neutral', onClick }) => (
    <div className={`b-tile b-tile-${tone} ${onClick ? 'b-clickable' : ''}`} onClick={onClick} role={onClick ? 'button' : undefined}>
        <p className="b-tile-label">{label}</p>
        <p className="b-tile-value">{value}</p>
        {hint && <p className="b-tile-hint">{hint}</p>}
    </div>
);

export const Tabs: React.FC<{ tabs: Array<{ id: string; label: string }>; value: string; onChange: (id: string) => void }> = ({ tabs, value, onChange }) => (
    <div className="b-tabs" role="tablist">
        {tabs.map(t => (
            <button key={t.id} role="tab" aria-selected={t.id === value} className={t.id === value ? 'active' : ''}
                    onClick={() => onChange(t.id)}>{t.label}</button>
        ))}
    </div>
);

export const Notice: React.FC<{ tone?: Tone; children: React.ReactNode }> = ({ tone = 'neutral', children }) => (
    <div className={`b-notice b-notice-${tone}`} role={tone === 'negative' ? 'alert' : undefined}>{children}</div>
);

export const PageHeader: React.FC<{ eyebrow?: string; title: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode }> = (
    { eyebrow, title, subtitle, actions }) => (
    <div className="b-page-head">
        <div>
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            <h1 className="b-page-title">{title}</h1>
            {subtitle && <p className="b-page-subtitle">{subtitle}</p>}
        </div>
        {actions && <div className="b-card-actions">{actions}</div>}
    </div>
);
