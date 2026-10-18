// @vitest-environment jsdom
/**
 * AutomationLimitsForm — decision D47: each limit is "platform default" (left
 * out), "no limit" (null) or a value; everything shown comes from the catalogue.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { LimitInfo, LimitValues } from '@/services/automation.service';

import { AutomationLimitsForm } from './AutomationLimitsForm';

const CATALOGUE: LimitInfo[] = [
    { key: 'max_chain_depth', label: 'Loop limit', help: 'Stops loops.', kind: 'count', choices: [], unit: 'steps', default: null },
    { key: 'overlap', label: 'If the previous run is still going', help: 'Overlap.', kind: 'choice',
      choices: ['allow', 'queue', 'skip'], unit: '', default: 'allow' },
];

function setup(values: LimitValues, inherited: LimitValues | null = { max_chain_depth: 5 }) {
    const onChange = vi.fn();
    render(<AutomationLimitsForm catalogue={CATALOGUE} values={values} inherited={inherited} onChange={onChange} />);
    return onChange;
}

afterEach(cleanup);

describe('AutomationLimitsForm', () => {
    it('shows the platform default for a limit the business left out', () => {
        setup({});
        expect((screen.getByLabelText('Loop limit: kind') as HTMLSelectElement).value).toBe('__inherit__');
        expect(screen.getByText('5 steps')).toBeTruthy();
    });

    it('turns a limit off with null and on with a value', () => {
        const onChange = setup({});
        fireEvent.change(screen.getByLabelText('Loop limit: kind'), { target: { value: '__none__' } });
        expect(onChange).toHaveBeenLastCalledWith({ max_chain_depth: null });
        fireEvent.change(screen.getByLabelText('Loop limit: kind'), { target: { value: '__set__' } });
        expect(onChange).toHaveBeenLastCalledWith({ max_chain_depth: 1 });
    });

    it('edits a value and goes back to the platform default by leaving the key out', () => {
        const onChange = setup({ max_chain_depth: 3, overlap: 'skip' });
        fireEvent.change(screen.getByLabelText('Loop limit'), { target: { value: '12' } });
        expect(onChange).toHaveBeenLastCalledWith({ max_chain_depth: 12, overlap: 'skip' });
        fireEvent.change(screen.getByLabelText('Loop limit: kind'), { target: { value: '__inherit__' } });
        expect(onChange).toHaveBeenLastCalledWith({ overlap: 'skip' });
    });

    it('offers the choices the API lists, and the default', () => {
        const onChange = setup({});
        const select = screen.getByLabelText('If the previous run is still going') as HTMLSelectElement;
        expect(Array.from(select.options).map(o => o.textContent)).toEqual(
            ['Platform default', 'Default (allow)', 'allow', 'queue', 'skip']);
        fireEvent.change(select, { target: { value: 'queue' } });
        expect(onChange).toHaveBeenLastCalledWith({ overlap: 'queue' });
    });

    it('has no platform-default option on the platform form', () => {
        setup({}, null);
        const kind = screen.getByLabelText('Loop limit: kind') as HTMLSelectElement;
        expect(kind.value).toBe('__none__');
        expect(Array.from(kind.options).map(o => o.value)).toEqual(['__none__', '__set__']);
    });
});
