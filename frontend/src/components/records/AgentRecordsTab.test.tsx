// @vitest-environment jsdom
/**
 * The agent builder's Records tab (Phase 14 W4-2): ticking what an agent may
 * do in a table sets its capabilities.records and grants exactly the record
 * tools those permissions need.
 */
import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { AgentRecordsTab, recordsOf, toolsFor, type AgentRecords } from './AgentRecordsTab';
import type { Blueprint } from '@/services/records.service';

afterEach(cleanup);

const BLUEPRINT: Blueprint = {
    version: 3,
    objects: {
        contact: { label: 'Contact', plural: 'Contacts', fields: {} },
        order: { label: 'Order', plural: 'Orders', fields: {} },
    },
};

function Harness({ initial }: { initial: AgentRecords }) {
    const [value, setValue] = useState(initial);
    const [tools, setTools] = useState<string[]>(['web_search']);
    const onToolsChange = (ids: string[], granted: boolean) =>
        setTools(prev => (granted ? Array.from(new Set([...prev, ...ids])) : prev.filter(t => !ids.includes(t))));
    return (
        <QueryClientProvider client={new QueryClient()}>
            <AgentRecordsTab value={value} onChange={setValue} onToolsChange={onToolsChange} blueprint={BLUEPRINT} />
            <pre data-testid="value">{JSON.stringify(value)}</pre>
            <pre data-testid="tools">{JSON.stringify([...tools].sort())}</pre>
        </QueryClientProvider>
    );
}

const state = () => ({
    value: JSON.parse(screen.getByTestId('value').textContent || '{}') as AgentRecords,
    tools: JSON.parse(screen.getByTestId('tools').textContent || '[]') as string[],
});

describe('AgentRecordsTab', () => {
    it('lists the tables and grants the tools each permission needs', () => {
        render(<Harness initial={recordsOf(undefined)} />);
        fireEvent.click(screen.getByLabelText('Update Orders'));   // updating means reading too
        expect(state().value.objects).toEqual({ order: ['read', 'update'] });
        expect(state().tools).toEqual(['describe_schema', 'find_records', 'get_record', 'link_records',
                                       'update_record', 'web_search']);
        fireEvent.click(screen.getByLabelText('May run reports'));
        expect(state().tools).toContain('run_report');
    });

    it('withdraws the tools nothing needs any more, and keeps the others', () => {
        render(<Harness initial={{ objects: { contact: ['read', 'create'] }, reports: false, schema_changes: 'none' }} />);
        fireEvent.click(screen.getByLabelText('Read Contacts'));    // no reading: nothing else either
        expect(state().value.objects).toEqual({});
        expect(state().tools).toEqual(['web_search']);
        fireEvent.click(screen.getByLabelText('May propose data changes'));
        expect(state().value.schema_changes).toBe('propose');
        expect(state().tools).toEqual(['describe_schema', 'propose_schema_change', 'web_search']);
    });

    it('reads "*" as every operation', () => {
        const value = recordsOf({ records: { objects: { contact: '*', order: ['read'] } } });
        expect(value.objects).toEqual({ contact: ['read', 'create', 'update', 'delete'], order: ['read'] });
        expect(toolsFor(value)).toContain('archive_record');
    });
});
