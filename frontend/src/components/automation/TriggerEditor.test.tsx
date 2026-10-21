// @vitest-environment jsdom
/**
 * TriggerEditor — "When an agent finishes" is saved as an event trigger on
 * run.* for the watched agent, refuses an agent that would start itself, and
 * reopens as the same choice.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Trigger } from '@/services/automation.service';

const createTrigger = vi.fn();
const updateTrigger = vi.fn();

vi.mock('@/queries/hooks', () => ({
    useEntityList: () => ({
        data: [
            { id: 'research', name: 'Research', type: 'AGENT', status: 'ACTIVE' },
            { id: 'writer', name: 'Report Writer', type: 'AGENT', status: 'ACTIVE' },
        ],
    }),
}));

vi.mock('@/services/automation.service', () => ({
    automationService: {
        createTrigger: (...args: unknown[]) => createTrigger(...args),
        updateTrigger: (...args: unknown[]) => updateTrigger(...args),
        preview: vi.fn().mockResolvedValue({ timezone: 'Asia/Kolkata', times: [] }),
        testFilter: vi.fn(),
    },
}));

import { TriggerEditor } from './TriggerEditor';

beforeEach(() => {
    createTrigger.mockReset().mockImplementation(async (fields: Record<string, unknown>) => ({ id: 't1', ...fields }));
    updateTrigger.mockReset().mockImplementation(async (_id: string, fields: Record<string, unknown>) => ({ id: 't1', ...fields }));
});
afterEach(cleanup);

const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe('TriggerEditor: when an agent finishes', () => {
    it('saves an event trigger on run.* for the watched agent', async () => {
        const onSaved = vi.fn();
        render(<TriggerEditor timezone="Asia/Kolkata" onClose={vi.fn()} onSaved={onSaved} />);
        fireEvent.click(screen.getByLabelText('When an agent finishes'));
        fill('Name', 'Write up research');
        fill('Watched agent', 'research');
        fill('Outcome', 'failed');
        fill('Agent', 'writer');
        fireEvent.click(screen.getByText('Save trigger'));
        await waitFor(() => expect(onSaved).toHaveBeenCalled());
        expect(createTrigger).toHaveBeenCalledWith(expect.objectContaining({
            kind: 'event', entity_id: 'writer', event_type: 'run.failed',
            filter: { all: [{ path: 'data.entity_id', op: 'eq', value: 'research' }] },
            cron: null, run_at: null,
        }));
    });

    it('refuses an agent that would start itself each time it finishes', () => {
        render(<TriggerEditor timezone="UTC" onClose={vi.fn()} onSaved={vi.fn()} />);
        fireEvent.click(screen.getByLabelText('When an agent finishes'));
        fill('Name', 'Loop');
        fill('Watched agent', 'writer');
        fill('Agent', 'writer');
        fireEvent.click(screen.getByText('Save trigger'));
        expect(screen.getByRole('alert').textContent).toContain('cannot start itself');
        expect(createTrigger).not.toHaveBeenCalled();
    });

    it('reopens a saved run-finished trigger as the same choice', async () => {
        const saved = {
            id: 't1', name: 'Write up', kind: 'event', enabled: true, entity_id: 'writer',
            event_type: 'run.completed', filter: { all: [{ path: 'data.entity_id', op: 'eq', value: 'research' }] },
            input_template: {}, cron: null, run_at: null,
        } as unknown as Trigger;
        render(<TriggerEditor trigger={saved} timezone="UTC" onClose={vi.fn()} onSaved={vi.fn()} />);
        expect((screen.getByLabelText('When an agent finishes') as HTMLInputElement).checked).toBe(true);
        expect((screen.getByLabelText('Watched agent') as HTMLSelectElement).value).toBe('research');
        fireEvent.click(screen.getByText('Save changes'));
        await waitFor(() => expect(updateTrigger).toHaveBeenCalledWith('t1', expect.objectContaining({
            event_type: 'run.completed', entity_id: 'writer' })));
    });
});

vi.mock('@/services/records.service', () => ({
    recordsService: {
        schema: vi.fn().mockResolvedValue({
            version: 2,
            objects: {
                product: { label: 'Product', plural: 'Products',
                           fields: { name: { type: 'text' }, stock: { type: 'integer', label: 'Stock' },
                                     price: { type: 'money', label: 'Price' } } },
            },
        }),
    },
}));

describe('TriggerEditor: on a schedule, if the records say so (W4-2)', () => {
    it('saves a condition trigger the router can check', async () => {
        const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query');
        const onSaved = vi.fn();
        render(
            <QueryClientProvider client={new QueryClient()}>
                <TriggerEditor timezone="Asia/Kolkata" onClose={vi.fn()} onSaved={onSaved} />
            </QueryClientProvider>,
        );
        fireEvent.click(screen.getByLabelText('On a schedule, if the records say so'));
        fill('Name', 'Re-order when stock is low');
        fill('Cron', '0 * * * *');
        await screen.findByRole('option', { name: 'Products' });
        fill('Records', 'product');
        fireEvent.click(screen.getByText('+ filter'));
        fill('Filter 1 field', 'stock');
        fill('Filter 1 test', 'lt');
        fill('Filter 1 value', '10');
        fill('Comparison', 'gt');
        fill('Compared with', '0');
        fill('Agent', 'writer');
        fireEvent.click(screen.getByText('Save trigger'));
        await waitFor(() => expect(onSaved).toHaveBeenCalled());
        expect(createTrigger).toHaveBeenCalledWith(expect.objectContaining({
            kind: 'condition', cron: '0 * * * *', event_type: null,
            condition: { object: 'product', filter: [['stock', 'lt', 10]], measure: { fn: 'count' }, op: 'gt', value: 0 },
        }));
    });

    it('asks for the field to add up before saving a total', async () => {
        const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query');
        render(
            <QueryClientProvider client={new QueryClient()}>
                <TriggerEditor timezone="UTC" onClose={vi.fn()} onSaved={vi.fn()} />
            </QueryClientProvider>,
        );
        fireEvent.click(screen.getByLabelText('On a schedule, if the records say so'));
        fill('Name', 'Big stock value');
        await screen.findByRole('option', { name: 'Products' });
        fill('Records', 'product');
        fill('Measure', 'sum');
        fill('Agent', 'writer');
        fireEvent.click(screen.getByText('Save trigger'));
        expect(screen.getByRole('alert').textContent).toContain('field to add up');
        expect(createTrigger).not.toHaveBeenCalled();
    });
});
