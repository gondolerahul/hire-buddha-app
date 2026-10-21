/**
 * components/layout/ActingCompany — which company a partner or platform admin
 * is working in (Phase 14 M2-4, WS8).
 *
 * `ActingCompanySwitcher` (sidebar) lists the companies the caller may see
 * (`GET /companies`) and shows only when there is more than one. Choosing one
 * makes every request name it (`X-Company-Id`, see services/actingCompany)
 * and reloads the page, so nothing read for the previous company stays on
 * screen. `ActingCompanyBanner` (above the page) says whose data is shown and
 * goes back to the caller's own company.
 */
import React from 'react';
import { Building2 } from 'lucide-react';

import { useCompanyList } from '@/queries/hooks';
import { getActingCompany, setActingCompany, type ActingCompany } from '@/services/actingCompany';
import type { Company } from '@/types';

import './ActingCompany.css';

function choose(company: ActingCompany | null, reload: () => void = () => window.location.reload()): void {
    setActingCompany(company);
    reload();
}

export const ActingCompanySwitcher: React.FC<{ expanded: boolean; ownCompanyId?: string; reload?: () => void }> = ({
    expanded, ownCompanyId, reload,
}) => {
    const { data: companies } = useCompanyList<Company>();
    const others = (companies ?? []).filter((c) => c.id !== ownCompanyId);
    if (!others.length) return null;
    const acting = getActingCompany();

    if (!expanded) {
        return (
            <div className="acting-switcher acting-switcher--compact" title={acting ? `Working in ${acting.name}` : 'Your own company'}>
                <Building2 size={20} />
            </div>
        );
    }
    return (
        <label className="acting-switcher">
            <span className="acting-switcher__label"><Building2 size={14} /> Working in</span>
            <select
                aria-label="Working in"
                value={acting?.id ?? ''}
                onChange={(e) => {
                    const picked = others.find((c) => c.id === e.target.value);
                    choose(picked ? { id: picked.id, name: picked.name } : null, reload);
                }}
            >
                <option value="">My own company</option>
                {others.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                ))}
            </select>
        </label>
    );
};

export const ActingCompanyBanner: React.FC<{ reload?: () => void }> = ({ reload }) => {
    const acting = getActingCompany();
    if (!acting) return null;
    return (
        <div className="acting-banner" role="status">
            <span>You are working in <strong>{acting.name || 'another company'}</strong>: its agents, runs and automation.</span>
            <button type="button" onClick={() => choose(null, reload)}>Back to my company</button>
        </div>
    );
};
