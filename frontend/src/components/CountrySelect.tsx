/**
 * <CountrySelect> — a company's country, and the currency it will be billed in
 * (Phase 15 T2-3, FX-1). Used by sign-up, onboarding and company creation.
 */
import React, { useEffect, useState } from 'react';

import { CountryOption, geographyService } from '@/services/geography.service';

interface CountrySelectProps {
    value: string;
    onChange: (code: string, country?: CountryOption) => void;
    label?: string;
    /** Say which currency the company will be billed in. */
    showCurrency?: boolean;
    className?: string;
    selectClassName?: string;
}

export const CountrySelect: React.FC<CountrySelectProps> = ({
    value, onChange, label = 'Country', showCurrency = true, className, selectClassName,
}) => {
    const [countries, setCountries] = useState<CountryOption[]>([]);

    useEffect(() => {
        geographyService.getCountries().then(setCountries).catch(() => setCountries([]));
    }, []);

    const selected = countries.find(c => c.code === value);
    return (
        <div className={className}>
            <label className="block text-sm font-medium text-gray-300 mb-2" htmlFor="country-select">{label}</label>
            <select
                id="country-select"
                value={value}
                onChange={(e) => onChange(e.target.value, countries.find(c => c.code === e.target.value))}
                className={selectClassName ?? 'w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2 text-white'}
            >
                {countries.length === 0 && <option value={value}>{value}</option>}
                {countries.map(c => (
                    <option key={c.code} value={c.code} className="bg-gray-900">{c.name}</option>
                ))}
            </select>
            {showCurrency && selected && (
                <p className="text-xs text-gray-400 mt-1">Billed in {selected.currency}</p>
            )}
        </div>
    );
};
