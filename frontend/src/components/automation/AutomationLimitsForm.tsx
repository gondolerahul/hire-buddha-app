/**
 * components/automation/AutomationLimitsForm — edit one scope's automation
 * limits (decision D47: every limit optional, none by default).
 *
 * A view over the API, no rules of its own (tech spec §20, PR-7): the limits,
 * their labels, kinds and choices come from the API's catalogue. In a
 * business's form each limit is "platform default" (left out), "no limit"
 * (null) or a value; in the platform's form it is "no limit" or a value.
 * Props are plain JSON, so the Generative UI can compose it later.
 */
import React from 'react';

import type { LimitInfo, LimitValue, LimitValues } from '@/services/automation.service';

import './AutomationLimitsForm.css';

const INHERIT = '__inherit__';
const NONE = '__none__';
const SET = '__set__';

export interface AutomationLimitsFormProps {
    catalogue: LimitInfo[];
    /** The scope's own values: absent = inherit, null = no limit. */
    values: LimitValues;
    onChange: (values: LimitValues) => void;
    /** The platform's values, when this form edits a business (shows "platform default"). */
    inherited?: LimitValues | null;
    disabled?: boolean;
}

const describe = (limit: LimitInfo, value: LimitValue | undefined): string => {
    if (value === undefined || value === null) {
        return limit.kind === 'choice' ? `${limit.default ?? 'default'}` : 'no limit';
    }
    return limit.unit ? `${value} ${limit.unit}` : String(value);
};

export const AutomationLimitsForm: React.FC<AutomationLimitsFormProps> = ({
    catalogue, values, onChange, inherited, disabled,
}) => {
    const isBusiness = inherited !== undefined && inherited !== null;

    const update = (key: string, next: LimitValue | undefined) => {
        const copy: LimitValues = { ...values };
        if (next === undefined) delete copy[key];
        else copy[key] = next;
        onChange(copy);
    };

    return (
        <table className="alf">
            <thead>
                <tr>
                    <th>Limit</th>
                    <th>Setting</th>
                    {isBusiness && <th>Platform default</th>}
                </tr>
            </thead>
            <tbody>
                {catalogue.map(limit => {
                    const has = Object.prototype.hasOwnProperty.call(values, limit.key);
                    const value = values[limit.key];
                    const mode = !has ? (isBusiness ? INHERIT : NONE) : value === null ? NONE : SET;
                    return (
                        <tr key={limit.key}>
                            <td>
                                <div className="alf__label">{limit.label}</div>
                                <div className="alf__help">{limit.help}</div>
                            </td>
                            <td>
                                {limit.kind === 'choice' ? (
                                    <select
                                        aria-label={limit.label}
                                        disabled={disabled}
                                        value={mode === SET ? String(value) : mode}
                                        onChange={e => {
                                            const v = e.target.value;
                                            update(limit.key, v === INHERIT ? undefined : v === NONE ? null : v);
                                        }}
                                    >
                                        {isBusiness && <option value={INHERIT}>Platform default</option>}
                                        <option value={NONE}>Default ({limit.default})</option>
                                        {limit.choices.map(choice => <option key={choice} value={choice}>{choice}</option>)}
                                    </select>
                                ) : (
                                    <div className="alf__count">
                                        <select
                                            aria-label={`${limit.label}: kind`}
                                            disabled={disabled}
                                            value={mode}
                                            onChange={e => {
                                                const v = e.target.value;
                                                if (v === INHERIT) update(limit.key, undefined);
                                                else if (v === NONE) update(limit.key, null);
                                                else update(limit.key, typeof value === 'number' ? value : 1);
                                            }}
                                        >
                                            {isBusiness && <option value={INHERIT}>Platform default</option>}
                                            <option value={NONE}>No limit</option>
                                            <option value={SET}>At most…</option>
                                        </select>
                                        {mode === SET && (
                                            <>
                                                <input
                                                    type="number"
                                                    min={1}
                                                    step={1}
                                                    aria-label={limit.label}
                                                    disabled={disabled}
                                                    value={typeof value === 'number' ? value : ''}
                                                    onChange={e => {
                                                        const n = Math.floor(Number(e.target.value));
                                                        update(limit.key, Number.isFinite(n) && n >= 1 ? n : 1);
                                                    }}
                                                />
                                                {limit.unit && <span className="alf__unit">{limit.unit}</span>}
                                            </>
                                        )}
                                    </div>
                                )}
                            </td>
                            {isBusiness && (
                                <td className="alf__inherited">{describe(limit, inherited?.[limit.key])}</td>
                            )}
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );
};
